"""SW-06 接线休眠模块：assembler P2-P4 层进 p3/p5 输入装配；compress_history 进 p3 远端历史。

- nsc.context.assemble / compress_history 在 main 上已实现未接线（T-33 只落了模块）；
- 本卡接线：p3 的 prev_summary(P2)/known_facts(P3)/retrieved(P4) 与 p3/p5 的参考层(P5)
  过预算装配；history_compress 开时远端历史走 LLM 压缩；
- 缺省（budget=32768, history_compress=false）= 原行为逐字节不变。
"""

from __future__ import annotations

from pathlib import Path

import diskcache
import yaml

import nsc.runtime.cache as cache_mod
from tests.test_pipeline_stub import FullStubRouter

COMPRESS_MARK = "压缩成不超过"


class CompressRouter(FullStubRouter):
    """回答历史压缩 summarize 调用（纯文本），其余走黄金桩。"""

    def __init__(self) -> None:
        super().__init__()
        self.summarize_calls: list[str] = []

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        system = messages[0]["content"]
        if COMPRESS_MARK in system:
            self.summarize_calls.append(messages[-1]["content"])
            from nsc.runtime.models import LLMResult

            return LLMResult(
                text=f"SUM<{len(messages[-1]['content'])}>",
                model_id="stub/model",
                tokens_in=1,
                tokens_out=1,
                cost_usd=0.0,
                wall_ms=0,
            )
        return super().complete(tier, messages, json_mode=json_mode, seed=seed)


class RecordingRouter(CompressRouter):
    def __init__(self) -> None:
        super().__init__()
        self.p3_inputs: list[dict] = []

    def _p3(self, inputs):
        self.p3_inputs.append(inputs)
        return super()._p3(inputs)


# ---------------------------------------------------------------- assemble_context 单元
def _mini_ctx(tmp_path, context_cfg: dict | None):
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = {"id": "t", "version": "1", "context": context_cfg or {}}
    return PassContext(
        profile=profile,
        brand={},
        router=None,
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="t",
        spec_sha="t",
    )


def test_assemble_context_default_budget_keeps_everything(tmp_path):
    from nsc.passes import assemble_context

    facts = ['{"id": "f1"}', '{"id": "f2"}']
    refs = [("bible_json", "BIBLE" * 100), ("profile_json", "PROFILE" * 100)]
    prev, n_facts, rag, ref_keys = assemble_context(
        _mini_ctx(tmp_path, {}),
        p1_current="EPISODE" * 50,
        prev_summary="PREV",
        facts=facts,
        rag=["RAG"],
        refs=refs,
    )
    assert prev == "PREV" and n_facts == 2 and rag == "RAG"
    assert ref_keys == ["bible_json", "profile_json"]


def test_assemble_context_tight_budget_drops_in_order(tmp_path):
    from nsc.passes import assemble_context

    # 预算：装下 P1 后剩 ~700：P3 可装、P4（1000 token）整层丢、P2 截尾、P5 低保
    prev, n_facts, rag, ref_keys = assemble_context(
        _mini_ctx(tmp_path, {"budget": 800, "core_guarantee": 400}),
        p1_current="E" * 100,  # 50 token
        prev_summary="P" * 4000,  # 2000 token → 必截尾
        facts=['{"id": "f1"}', '{"id": "f2"}'],
        rag=["R" * 2000],
        refs=[("bible_json", "B" * 100)],
    )
    assert rag == "", "P4 检索层超配额必须整层丢弃"
    assert prev and len(prev) < 4000, "P2 超配额必须截尾保留末尾"
    assert 0 <= n_facts <= 2
    assert isinstance(ref_keys, list)


# ---------------------------------------------------------------- p5 输入预算装配
def test_p5_budgeted_inputs(tmp_path):
    from nsc.passes import p5_dialogue

    inputs = {
        "scene_json": '{"id": "s1"}',
        "beats_json": "[]",
        "characters_json": "C" * 200,
        "profile_json": "P" * 200,
        "retrieved_cases": "R" * 4000,
    }
    kept = p5_dialogue._budgeted_inputs(_mini_ctx(tmp_path, {}), inputs)
    assert kept == inputs, "缺省预算下 p5 输入必须逐字段不变"

    tight = p5_dialogue._budgeted_inputs(_mini_ctx(tmp_path, {"budget": 500}), dict(inputs))
    assert tight["retrieved_cases"] == "", "预算吃紧时 P4 检索层丢弃"
    assert "characters_json" in tight or "profile_json" in tight, "P5 参考层有低保"
    # review 修正：降级不删键——signature 的必填 InputField 必须仍在（值可为空）
    for key in ("characters_json", "profile_json"):
        assert key in tight, f"预算降级不得删除 {key}（置空而非缺字段）"


def test_p3_degradation_keeps_keys(tmp_path):
    """review 修正：p3 参考层降级保留键、置空值，不缺字段击穿 signature 契约。"""
    from nsc.passes import p3_beatsheet

    out = p3_beatsheet._budgeted_inputs(
        _mini_ctx(tmp_path, {"budget": 80, "core_guarantee": 40}),
        {
            "episode_json": "E" * 80,
            "prev_episode_summary": "P" * 4000,
            "retrieved_cases": "",
            "bible_json": "B" * 4000,
            "profile_json": "P" * 4000,
        },
        [],
    )
    assert {"episode_json", "bible_json", "profile_json"} <= set(out), "降级后必填键仍在"
    assert out["bible_json"] == "" or out["profile_json"] == "", "超额参考层被置空"
    assert out["prev_episode_summary"] == "", "P2 零配额整层丢弃后为空串（键仍在）"


# ---------------------------------------------------------------- compress_history 接线（全桩管线）
def _ctx(tmp_path, monkeypatch, router, context_cfg: dict):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    profile["context"] = context_cfg
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=router,
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="t",
        spec_sha="t",
        out_dir=tmp_path / "out",
    )


def test_compress_wiring_far_and_recent(tmp_path, monkeypatch):
    from nsc.passes.pipeline import run_pipeline

    router = RecordingRouter()
    ctx = _ctx(
        tmp_path,
        monkeypatch,
        router,
        {"history_compress": True, "prev_summary_window": 3, "history_keep_recent": 1},
    )
    run_pipeline(ctx)
    inputs = router.p3_inputs
    # 第 2 集：历史只有 1 集 = 近端 → 原文窗口，无压缩调用参与该集
    assert "【前情】" not in inputs[1]["prev_episode_summary"]
    # 第 4 集：窗口 3、近端 1 → 两集远端走压缩，一集近端保原文
    prev4 = inputs[3]["prev_episode_summary"]
    assert prev4.startswith("【前情】") and "【上一集】" in prev4
    assert "SUM<" in prev4, "远端历史必须是 LLM 压缩摘要"
    assert router.summarize_calls, "compress_history 必须经 make_llm_summarizer 调 LLM"


def test_compress_off_by_default(tmp_path, monkeypatch):
    from nsc.passes.pipeline import run_pipeline

    router = RecordingRouter()
    ctx = _ctx(
        tmp_path,
        monkeypatch,
        router,
        {"prev_summary_window": 3},  # 未开 history_compress：纯原文窗口（SW-05 行为）
    )
    run_pipeline(ctx)
    assert router.summarize_calls == [], "缺省不得产生压缩 LLM 调用"
    assert "【前情】" not in router.p3_inputs[3]["prev_episode_summary"]
