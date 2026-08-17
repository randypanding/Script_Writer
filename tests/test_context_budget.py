"""T-33：上下文预算装配与历史压缩（ADR-0013；来源 FicForge budget + StoryWriter MessageRedact）。

全 stub，无真实 LLM：summarize 一律注入；make_llm_summarizer 用 fake router 单测缓存。
"""

from __future__ import annotations

import pytest

from nsc.context import assemble, compress_history, count_tokens, make_llm_summarizer
from nsc.context.assembler import AssembleResult, Layer
from nsc.passes import PassFailure

# ---------- count_tokens ----------


def test_count_tokens_estimor_and_monotonicity():
    # 机制常量：max(1, len//2)（中文 ≈ 2 字符/token 的保守估算）
    assert count_tokens("") == 1
    assert count_tokens("ab") == 1
    assert count_tokens("abc") == 1
    assert count_tokens("abcd") == 2
    prev = 0
    for n in range(0, 40):
        cur = count_tokens("x" * n)
        assert cur >= prev  # 单调不减
        prev = cur


# ---------- assemble：P0/P1 不可裁 ----------


def test_p0_p1_over_budget_raises():
    with pytest.raises(PassFailure):
        assemble(
            p0_system="s" * 100,
            p1_current="c" * 100,
            p2_prev_summary="",
            p3_facts=[],
            p4_rag=[],
            p5_bible=[],
            budget=10,
        )


def test_p0_p1_exact_fit_does_not_raise():
    res = assemble(
        p0_system="ab",
        p1_current="cd",
        p2_prev_summary="",
        p3_facts=[],
        p4_rag=[],
        p5_bible=[],
        budget=2,  # tokens(P0)+tokens(P1) == 2，恰好装下
    )
    assert [lay.name for lay in res.layers] == ["P0", "P1"]
    assert res.used == 2
    assert res.dropped == [] and res.degraded == []


# ---------- assemble：P4 整层丢弃 ----------


def test_p4_whole_layer_dropped():
    p4_text = "r" * 40 + "\n" + "r" * 40  # 81 chars → 40 tokens
    res = assemble(
        p0_system="s",
        p1_current="c",
        p2_prev_summary="",
        p3_facts=[],
        p4_rag=["r" * 40, "r" * 40],
        p5_bible=["b"],
        budget=1 + 1 + 40 - 1,  # rem=39 → P4 配额 max(0, 39-400)=0 → 整层放不下
    )
    assert res.dropped == ["P4"]
    assert all(lay.name != "P4" for lay in res.layers)
    assert "r" * 40 not in "".join(lay.text for lay in res.layers)
    assert p4_text not in "".join(lay.text for lay in res.layers)
    # P5 有 core_guarantee 保底，不受 P4 挤占影响
    assert any(lay.name == "P5" and lay.text == "b" for lay in res.layers)
    assert res.used <= 1 + 1 + 40 - 1


# ---------- assemble：P3 降级 hint ----------


def test_p3_degraded_hint_appended_to_tail_layer():
    facts = [f"事实{i:02d}" for i in range(8)]  # 每条 5 chars
    res = assemble(
        p0_system="s",
        p1_current="c",
        p2_prev_summary="",
        p3_facts=facts,
        p4_rag=[],
        p5_bible=[],
        budget=407,  # rem=405 → P3 配额 5：装下 2 条（2+3 token），第 3 条起超出
    )
    assert res.degraded == ["P3:丢弃6条unresolved事实"]
    tail = res.layers[-1]
    assert tail.name == "P3"
    assert "P3:丢弃6条unresolved事实" in tail.text  # hint 行追加在尾部层
    assert "事实00" in tail.text and "事实01" in tail.text
    assert "事实02" not in tail.text.split("P3:丢弃")[0]
    assert res.used <= 407


# ---------- assemble：P5 core_guarantee 保底 ----------


def test_p5_core_guarantee_under_tiny_budget():
    res = assemble(
        p0_system="s",
        p1_current="c",
        p2_prev_summary="",
        p3_facts=[],
        p4_rag=[],
        p5_bible=["x" * 800, "y" * 800],  # 每条 400 token
        budget=12,  # rem=10，远不够 → P5 配额 = max(400, 10) = 400
    )
    p5 = next(lay for lay in res.layers if lay.name == "P5")
    assert p5.text == "x" * 800  # 第一条恰好 400 token 装入；第二条超出即停（静默）
    assert p5.tokens == 400
    assert res.used >= 400  # 保底超额属设计内（budget 不足以覆盖低保时）


# ---------- assemble：总 used ≤ budget（正常路径） ----------


def test_used_within_budget_no_loss():
    p0, p1, p2 = "系统指令", "当前集" * 50, "上一集摘要" * 20
    p3, p4, p5 = ["事实甲", "事实乙"], ["参考一", "参考二"], ["设定一", "设定二"]
    need = (
        count_tokens(p0)
        + count_tokens(p1)
        + count_tokens(p2)
        + count_tokens("\n".join(p3))
        + count_tokens("\n".join(p4))
        + count_tokens("\n".join(p5))
    )
    budget = need + 400 + 10  # 留足 core_guarantee 与富余
    res = assemble(
        p0_system=p0,
        p1_current=p1,
        p2_prev_summary=p2,
        p3_facts=p3,
        p4_rag=p4,
        p5_bible=p5,
        budget=budget,
    )
    assert isinstance(res, AssembleResult)
    assert all(isinstance(lay, Layer) for lay in res.layers)
    assert [lay.name for lay in res.layers] == ["P0", "P1", "P2", "P3", "P4", "P5"]
    assert res.dropped == [] and res.degraded == []
    assert res.used == sum(lay.tokens for lay in res.layers) <= budget


# ---------- compress_history ----------


def test_compress_history_far_compressed_recent_kept():
    eps = [
        {"no": 1, "text": "第1集正文" + "a" * 4000},
        {"no": 2, "text": "第2集正文" + "b" * 4000},
        {"no": 3, "text": "第3集正文" + "c" * 4000},
    ]
    calls: list[tuple[str, int]] = []

    def stub(text: str, target: int) -> str:
        calls.append((text, target))
        return text[:target]

    out = compress_history(eps, current_no=3, summarize=stub, keep_recent=1, ratio=0.1)
    # 远端（no <= 3-1-1=1）：只有第 1 集被压缩，目标长度 = int(len*0.1)
    assert calls == [(eps[0]["text"], 400)]
    # 近端（第 2 集）：保留原文前 2000 字符；当前集（第 3 集）不进入历史
    assert "【前情】" in out and "【上一集】" in out
    assert out.index("【前情】") < out.index("【上一集】")
    assert eps[0]["text"][:400] in out
    assert eps[1]["text"][:2000] in out
    assert len(eps[1]["text"]) > 2000 and eps[1]["text"] not in out
    assert eps[2]["text"] not in out


def test_compress_history_same_text_summarized_once():
    same = "同文" * 50
    eps = [{"no": 1, "text": same}, {"no": 2, "text": same}, {"no": 3, "text": "近" * 10}]
    calls: list[str] = []

    def counting(text: str, target: int) -> str:
        calls.append(text)
        return text[:target]

    out = compress_history(eps, current_no=4, summarize=counting, keep_recent=1)
    # no <= 4-1-1=2 的两集同文 → 内容寻址去重，只调一次 summarize
    assert calls.count(same) == 1 and len(calls) == 1
    assert "近" * 10 in out  # 第 3 集是最近一集，原文保留


def test_compress_history_empty_episodes():
    out = compress_history([], current_no=1, summarize=lambda t, n: t[:n])
    assert out == ""


# ---------- make_llm_summarizer：路由 + 内容寻址缓存 ----------


class FakeRouter:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        from nsc.runtime.models import LLMResult

        self.calls += 1
        assert messages[0]["role"] == "system"  # 提示词承载目标长度，原文走 user 消息
        return LLMResult(
            text="摘要", model_id="stub", tokens_in=1, tokens_out=1, cost_usd=0.0, wall_ms=1
        )


def test_make_llm_summarizer_caches_by_content(tmp_path, monkeypatch):
    import diskcache

    import nsc.runtime.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "c")))
    r = FakeRouter()
    s = make_llm_summarizer(router=r, tier="tier_bulk")
    assert s("剧本甲", 8) == "摘要"
    assert s("剧本甲", 8) == "摘要"
    assert r.calls == 1  # 同 text 不重复调用（内存 dict 命中）
    assert s("剧本乙", 8) == "摘要"
    assert r.calls == 2

    # 新实例共享 runtime.cache 的持久内容寻址缓存 → 同 text 零调用
    r2 = FakeRouter()
    s2 = make_llm_summarizer(router=r2, tier="tier_bulk")
    assert s2("剧本甲", 8) == "摘要"
    assert r2.calls == 0
