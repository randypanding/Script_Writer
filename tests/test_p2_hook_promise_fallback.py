"""p2_arc hook_promise 机械兜底(W4 demo_tea 实证:p2 连续产出空 hook_promise 是五类死因之一)。

STR-011(after_p2,block)能检出空 hook_promise,但修正靠 LLM 重试——随机后端
反复省略时重试只是复述诊断不改结构(round14 方法论:结构性约束一律机械兜底)。
本测试要求 p2_arc 在构造阶段就把空 hook_promise 确定性补成非空,让结构必然成立。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest

import nsc.passes.p2_arc as p2
from nsc.checker.registry import chars
from nsc.passes import PassContext


class _FakeRouter:
    def __init__(self, text=""):
        self._text = text

    def complete(self, tier, messages, **kw):
        return SimpleNamespace(text=self._text)


@dataclass
class _CtxDouble:
    router: Any
    profile: dict = field(default_factory=lambda: {"pipeline": {}})
    brand: dict = field(default_factory=dict)
    seed: int | None = 7
    run_id: str = "run-test"

    def tier_of(self, pass_name: str) -> str:
        return "tier_plan"

    def cache_versions(self, pass_name: str) -> dict[str, Any]:
        return {
            "promptset_ver": "seed",
            "profile_ver": "1",
            "brand_ver": "1",
            "ruleset_ver": "x",
            "model_id": "m",
            "temperature": 0.0,
            "seed": self.seed,
            "spec_sha": "s",
        }

    def record_run(self, *args, **kwargs) -> str:
        return self.run_id


def _ctx(router) -> PassContext:
    return cast(PassContext, _CtxDouble(router=router))


def _episodes(*specs: dict) -> str:
    """从 {no,title,logline,hook_promise,cliffhanger} 列表拼 episodes_json。"""
    base = {
        "title": "默认标题",
        "logline": "默认 logline",
        "hook_promise": "",
        "cliffhanger": "",
    }
    out = []
    for s in specs:
        ep = dict(base)
        ep.update(s)
        out.append(ep)
    return json.dumps(out, ensure_ascii=False)


def _mk_out(episodes_json: str) -> dict[str, Any]:
    return {
        "episodes_json": episodes_json,
        "placement_plan_json": "[]",
        "season_arc": "测试弧线",
        "_usage": {},
    }


# ---------- 直接测 helper ----------

def test_fallback_preserves_non_empty_hook_promise():
    """已有非空 hook_promise 不得被覆盖。"""
    assert p2._fallback_hook_promise(
        {"hook_promise": "林晚的体检报告藏了什么？", "logline": "x"}, 1
    ) == "林晚的体检报告藏了什么？"


def test_fallback_fills_empty_from_logline():
    """空 hook_promise 从 logline 确定性派生,且非空。"""
    got = p2._fallback_hook_promise(
        {"hook_promise": "   ", "logline": "林晚发现体检报告异常"}, 1
    )
    assert chars(got) >= 6  # 必过 STR-011 门槛
    assert "林晚" in got  # 派生应包含 logline 语义


def test_fallback_deterministic():
    """确定性:同输入同输出(机械兜底不引入随机性)。"""
    ep = {"hook_promise": "", "logline": "同一 logline"}
    assert p2._fallback_hook_promise(ep, 3) == p2._fallback_hook_promise(ep, 3)


def test_fallback_falls_back_to_title_when_logline_empty():
    """logline 也为空时,回退到 title 派生(极退化路径)。"""
    got = p2._fallback_hook_promise(
        {"hook_promise": "", "logline": "", "title": "第3集 谁在偷喝我的茶"}, 3
    )
    assert chars(got) >= 6


def test_fallback_none_hook_promise():
    """None 不是合法 hook_promise,应回退到 logline 派生。"""
    got = p2._fallback_hook_promise(
        {"hook_promise": None, "logline": "林晚发现体检报告异常"}, 1
    )
    assert chars(got) >= 6
    assert "林晚" in got


def test_fallback_zero_hook_promise():
    """数字 0 也不是合法 hook_promise,应回退到 logline 派生。"""
    got = p2._fallback_hook_promise(
        {"hook_promise": 0, "logline": "林晚发现体检报告异常"}, 1
    )
    assert chars(got) >= 6


def test_fallback_list_hook_promise():
    """列表/对象等非字符串值应回退,不得原样返回。"""
    got = p2._fallback_hook_promise(
        {"hook_promise": [], "logline": "林晚发现体检报告异常"}, 1
    )
    assert chars(got) >= 6


def test_fallback_dict_hook_promise():
    """字典原样返回通常过短,应回退到 logline 派生。"""
    got = p2._fallback_hook_promise(
        {"hook_promise": {}, "logline": "林晚发现体检报告异常"}, 1
    )
    assert chars(got) >= 6


# ---------- 端到端:经 run() ----------

def test_run_repairs_all_empty_hook_promises(monkeypatch):
    """W4 实证场景:6 集 hook_promise 全空,run() 后全部被机械补成非空。"""
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    specs = [
        {"no": i + 1, "title": f"第{i+1}集", "logline": f"第{i+1}集 logline 内容", "hook_promise": ""}
        for i in range(6)
    ]
    fake_out = _mk_out(_episodes(*specs))

    class FakeModule:
        def __call__(self, ctx, inputs):
            return fake_out

    monkeypatch.setattr(p2, "Module", lambda: FakeModule())
    frag = {"bible": {}, "project_id": "p1", "retrieved_cases": ""}
    out = p2.run(_ctx(_FakeRouter()), frag)
    promises = [e["hook_promise"] for e in out["episodes"]]
    assert len(promises) == 6
    for hp in promises:
        assert chars(hp) >= 6, f"hook_promise 仍为空或过短: {hp!r}"


def test_run_preserves_existing_hook_promises(monkeypatch):
    """LLM 已给出非空 hook_promise 的集不得被改写。"""
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    specs = [
        {"no": 1, "hook_promise": "第一集自己的承诺", "logline": "l1"},
        {"no": 2, "hook_promise": "", "logline": "第二集 logline"},
    ]
    fake_out = _mk_out(_episodes(*specs))

    class FakeModule:
        def __call__(self, ctx, inputs):
            return fake_out

    monkeypatch.setattr(p2, "Module", lambda: FakeModule())
    frag = {"bible": {}, "project_id": "p1", "retrieved_cases": ""}
    out = p2.run(_ctx(_FakeRouter()), frag)
    by_no = {e["no"]: e["hook_promise"] for e in out["episodes"]}
    assert by_no[1] == "第一集自己的承诺"  # 保留
    assert chars(by_no[2]) >= 6  # 补全
