"""round15 两个健壮性补丁(8/26 08:00 交付倒排下的止血):

1. _rescale_durations——DLG-006 六集全灭的根因:NPC 系统性低估 est_duration_s
   (合计 ~70s vs 目标 90s),p5 按它换算对白地板必然欠量。把各拍时长等比缩放到
   集目标时长,下游体量地板才算真账。
2. _retry_pass 传输容错:shim 重启/CNB 抖动抛 APIConnectionError 直接杀死整轮
   (实证 attempt2 殉爆),传输故障应走与 PassFailure 相同的带诊断重试通道。
"""
from types import SimpleNamespace

import pytest

from nsc.passes.p3_beatsheet import _rescale_durations
from nsc.passes.pipeline import _retry_pass
from nsc.passes import PassFailure


def _beat(i, secs):
    return {"id": f"b{i}", "order": i, "beat_kind": "escalation",
            "emotion": {"valence": 0.0, "arousal": 0.5}, "summary": f"节拍{i}",
            "est_duration_s": secs}


def test_rescale_sums_to_target_preserving_ratios():
    beats = [_beat(0, 20.0), _beat(1, 30.0), _beat(2, 20.0)]  # 合计 70s
    _rescale_durations(beats, {"duration_target_s": 90.0, "no": 1})
    total = sum(b["est_duration_s"] for b in beats)
    assert abs(total - 90.0) < 0.05
    assert beats[1]["est_duration_s"] > beats[0]["est_duration_s"]  # 比例保持


def test_rescale_zero_durations_even_split():
    beats = [_beat(0, 0.0), _beat(1, 0.0), _beat(2, 0.0)]
    _rescale_durations(beats, {"duration_target_s": 90.0, "no": 1})
    assert all(abs(b["est_duration_s"] - 30.0) < 0.01 for b in beats)


def test_rescale_no_target_is_noop():
    beats = [_beat(0, 20.0)]
    _rescale_durations(beats, {"no": 1})
    assert beats[0]["est_duration_s"] == 20.0


# ---------- _retry_pass 传输容错 ----------

class APIConnectionError(Exception):  # 类名匹配即视为传输故障(与 openai 同名)
    pass


def _ctx():
    return SimpleNamespace(profile={})


def test_transient_error_retried_then_succeeds():
    calls = {"n": 0}

    def flaky(ctx, frag):
        calls["n"] += 1
        if calls["n"] == 1:
            raise APIConnectionError("connection reset")
        return {"ok": True}

    assert _retry_pass(flaky, _ctx(), {}) == {"ok": True}
    assert calls["n"] == 2


def test_transient_error_exhausted_becomes_pass_failure():
    def always(ctx, frag):
        raise APIConnectionError("down")

    with pytest.raises(PassFailure):
        _retry_pass(always, _ctx(), {}, attempts=3)


def test_non_transient_error_propagates_without_retry():
    calls = {"n": 0}

    def buggy(ctx, frag):
        calls["n"] += 1
        raise ValueError("代码 bug 不该重试")

    with pytest.raises(ValueError):
        _retry_pass(buggy, _ctx(), {})
    assert calls["n"] == 1
