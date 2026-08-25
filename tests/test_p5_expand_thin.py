"""round16:p5 对白体量双补丁(实证 attempt1/3 全季 DLG-006 连灭,NPC 系统性欠量 ~26%):

1. 目标区间与门禁对齐——旧 chars_lo=0.8× 低于 DLG-006 下限 0.85×,模型全顺从也会死;
2. _expand_if_thin——欠量当场定点扩写,只接受严格增量;此处测纯函数部分。
"""
from types import SimpleNamespace

from nsc.passes.p5_dialogue import _dialogue_chars, _scene_dialogue_floor


def _ln(t, lt="dialogue"):
    return {"line_type": lt, "text": t}


def test_dialogue_chars_counts_only_dialogue():
    lines = [_ln("一二三四五"), _ln("动作行不算", "action"), _ln("六七")]
    assert _dialogue_chars(lines) == 7


def test_scene_dialogue_floor_matches_gate_ratio():
    ctx = SimpleNamespace(profile={"chars_per_second": 4.5, "duration_tolerance": 0.15})
    beats = [{"est_duration_s": 50.0}, {"est_duration_s": 40.0}]  # 90s ≈ 一集
    floor = _scene_dialogue_floor(ctx, beats)
    # round16b:瞄准线 = 门禁线 + 6pp 余量(round20:ep8 差 12 字实证,仍远低于上限 1.15)
    assert floor == int(90 * 4.5 * 0.91) == 368
    assert floor > int(90 * 4.5 * 0.85)  # 严格高于门禁下限


def test_scene_dialogue_floor_defaults():
    ctx = SimpleNamespace(profile={})
    beats = [{"est_duration_s": 100.0}]
    assert _scene_dialogue_floor(ctx, beats) == int(100 * 4.5 * 0.91)
