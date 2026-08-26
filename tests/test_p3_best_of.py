"""R3:p3 best-of-n + 监制重排(实证动机:RLHF 磨平靠采样+选择绕开;
R2 教训:选择标准必须纳入植入自然度)。"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest

import nsc.passes.p3_beatsheet as p3
from nsc.passes import PassContext, PassFailure


class _FakeRes:
    text = '{"winner": 1, "reason": "张力最强"}'


class _FakeRouter:
    def __init__(self, text='{"winner": 1}'):
        self._text = text
        self.calls = []

    def complete(self, tier, messages, **kw):
        self.calls.append(messages)
        return SimpleNamespace(text=self._text)


@dataclass
class _CtxDouble:  # dataclasses.replace 需要真 dataclass(SimpleNamespace 不行)
    router: Any
    profile: dict = field(default_factory=lambda: {"pipeline": {}})
    seed: int | None = 7

    def tier_of(self, pass_name: str) -> str:
        return "tier_plan"


def _ctx(router) -> PassContext:
    return cast(PassContext, _CtxDouble(router=router))


# ---------- _parse_winner ----------


@pytest.mark.parametrize(
    ("text", "n", "want"),
    [
        ('{"winner": 2, "reason": "x"}', 3, 2),
        ('```json\n{"winner": 1}\n```', 3, 1),
        ('{"winner": 5}', 3, 0),  # 越界 → 保首候选
        ('{"winner": -1}', 3, 0),
        ("散文没有 JSON", 3, 0),
        ('{"winner": "abc"}', 3, 0),
        ("", 3, 0),
    ],
)
def test_parse_winner(text, n, want):
    assert p3._parse_winner(text, n) == want


# ---------- _best_of_n ----------


def _mk_out(tag):
    return {
        "beats_json": f'[{{"beat_kind": "hook", "summary": "{tag}", "emotion": {{"arousal": 0.9}}}}]',
        "setup_payoffs_json": "[]",
        "_usage": {},
    }


def test_best_of_n_picks_rerank_winner(monkeypatch):
    calls = {"n": 0}

    class FakeModule:
        def __call__(self, ctx, inputs):
            calls["n"] += 1
            return _mk_out(f"候选{calls['n']}")

    monkeypatch.setattr(p3, "Module", lambda: FakeModule())
    router = _FakeRouter('{"winner": 2}')
    out = p3._best_of_n(_ctx(router), {"episode_json": "{}"}, {"episode": {"id": "e1"}}, 3)
    assert calls["n"] == 3
    assert "候选3" in out["beats_json"]  # winner=2 → 第三候选
    assert router.calls  # 重排确实调用了 router


def test_best_of_n_tolerates_candidate_failures(monkeypatch):
    calls = {"n": 0}

    class FlakyModule:
        def __call__(self, ctx, inputs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PassFailure("e1", "候选失败")
            return _mk_out("独苗")

    monkeypatch.setattr(p3, "Module", lambda: FlakyModule())
    out = p3._best_of_n(_ctx(_FakeRouter()), {"episode_json": "{}"}, {"episode": {"id": "e1"}}, 3)
    assert "独苗" in out["beats_json"]  # 单候选不重排直接返回


def test_best_of_n_all_fail_raises(monkeypatch):
    class DeadModule:
        def __call__(self, ctx, inputs):
            raise PassFailure("e1", "全灭")

    monkeypatch.setattr(p3, "Module", lambda: DeadModule())
    with pytest.raises(PassFailure):
        p3._best_of_n(_ctx(_FakeRouter()), {"episode_json": "{}"}, {"episode": {"id": "e1"}}, 2)


def test_rerank_router_failure_keeps_first(monkeypatch):
    class BoomRouter:
        def complete(self, tier, messages, **kw):
            raise ConnectionError("shim down")

    assert p3._rerank(_ctx(BoomRouter()), {"episode_json": "{}"}, [_mk_out("a"), _mk_out("b")]) == 0
