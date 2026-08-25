"""round18:暗线步进钳制(实证 round17 attempt1 全量产物死于 final 门:
current_stage 5/7 超出 [0,2]——NPC 的 int delta 跨集累加溢出 stages 上限,
相位重试改不了系统性,机械钳制保累加值恒在 [0, len(stages)-1])。"""
from nsc.passes.pipeline import _clamp_dark_thread_deltas


def _ep(order, deltas):
    return {"order": order, "no": order + 1,
            "state_changes": [{"key": k, "delta": d, "reason": "r"} for k, d in deltas]}


def test_overflow_clamped_to_cap():
    eps = [_ep(0, [("t1", 2)]), _ep(1, [("t1", 2)]), _ep(2, [("t1", 3)])]
    dark = [{"key": "t1", "stages": ["a", "b", "c"]}]  # cap = 2
    _clamp_dark_thread_deltas(eps, dark)
    deltas = [ch["delta"] for ep in eps for ch in ep["state_changes"]]
    assert deltas == [2, 0, 0]  # 累加 2→2→2,后续步进被钳到 0
    assert sum(deltas) <= 2


def test_negative_clamped_to_zero():
    eps = [_ep(0, [("t1", -3)]), _ep(1, [("t1", 1)])]
    dark = [{"key": "t1", "stages": ["a", "b"]}]
    _clamp_dark_thread_deltas(eps, dark)
    deltas = [ch["delta"] for ep in eps for ch in ep["state_changes"]]
    assert deltas == [0, 1]


def test_idempotent():
    eps = [_ep(0, [("t1", 5)]), _ep(1, [("t1", 5)])]
    dark = [{"key": "t1", "stages": ["a", "b", "c"]}]
    _clamp_dark_thread_deltas(eps, dark)
    first = [ch["delta"] for ep in eps for ch in ep["state_changes"]]
    _clamp_dark_thread_deltas(eps, dark)
    second = [ch["delta"] for ep in eps for ch in ep["state_changes"]]
    assert first == second == [2, 0]


def test_non_dark_and_bool_untouched():
    eps = [_ep(0, [("other", 99), ("t1", True)])]
    dark = [{"key": "t1", "stages": ["a", "b"]}]
    _clamp_dark_thread_deltas(eps, dark)
    chs = eps[0]["state_changes"]
    assert chs[0]["delta"] == 99  # 非暗线 key 不动
    assert chs[1]["delta"] is True  # bool 不动


def test_empty_dark_threads_noop():
    eps = [_ep(0, [("t1", 5)])]
    _clamp_dark_thread_deltas(eps, [])
    assert eps[0]["state_changes"][0]["delta"] == 5
