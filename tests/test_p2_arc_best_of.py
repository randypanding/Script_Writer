"""R4:p2 arc best-of-n + 监制重排(实证 round24:conflict person 缺口的决策点在季弧层,
节拍重排救不了弧级"独自旅行"结构;季弧全季一次调用,best-of 成本极低)。"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest

import nsc.passes.p2_arc as p2
from nsc.passes import PassContext, PassFailure


class _FakeRouter:
    def __init__(self, text='{"winner": 1}'):
        self._text = text
        self.calls = []

    def complete(self, tier, messages, **kw):
        self.calls.append(messages)
        return SimpleNamespace(text=self._text)


@dataclass
class _CtxDouble:
    router: Any
    profile: dict = field(default_factory=lambda: {"pipeline": {}})
    seed: int | None = 7

    def tier_of(self, pass_name: str) -> str:
        return "tier_plan"


def _ctx(router) -> PassContext:
    return cast(PassContext, _CtxDouble(router=router))


def _mk_out(tag):
    return {
        "episodes_json": f'[{{"no": 1, "logline": "{tag}", "hook_promise": "h", "cliffhanger": "c"}}]',
        "season_arc": tag,
        "_usage": {},
    }


def test_best_of_n_picks_rerank_winner(monkeypatch):
    calls = {"n": 0}

    class FakeModule:
        def __call__(self, ctx, inputs):
            calls["n"] += 1
            return _mk_out(f"弧{calls['n']}")

    monkeypatch.setattr(p2, "Module", lambda: FakeModule())
    router = _FakeRouter('{"winner": 2}')
    out = p2._best_of_n(_ctx(router), {"bible_json": "{}"}, {}, 3)
    assert calls["n"] == 3
    assert out["season_arc"] == "弧3"
    assert router.calls


def test_best_of_n_tolerates_candidate_failures(monkeypatch):
    calls = {"n": 0}

    class FlakyModule:
        def __call__(self, ctx, inputs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PassFailure(None, "失败")
            return _mk_out("独苗")

    monkeypatch.setattr(p2, "Module", lambda: FlakyModule())
    out = p2._best_of_n(_ctx(_FakeRouter()), {"bible_json": "{}"}, {}, 3)
    assert out["season_arc"] == "独苗"


def test_best_of_n_all_fail_raises(monkeypatch):
    class DeadModule:
        def __call__(self, ctx, inputs):
            raise PassFailure(None, "全灭")

    monkeypatch.setattr(p2, "Module", lambda: DeadModule())
    with pytest.raises(PassFailure):
        p2._best_of_n(_ctx(_FakeRouter()), {"bible_json": "{}"}, {}, 2)


def test_rerank_router_failure_keeps_first(monkeypatch):
    class BoomRouter:
        def complete(self, tier, messages, **kw):
            raise ConnectionError("down")

    assert p2._rerank(_ctx(BoomRouter()), {"bible_json": "{}"}, [_mk_out("a"), _mk_out("b")]) == 0


def test_parse_winner_shared():
    from nsc.passes import parse_winner

    assert parse_winner('{"winner": 1}', 3) == 1
    assert parse_winner("散文", 3) == 0
    assert parse_winner('{"winner": 9}', 3) == 0
