"""p3/p4 结构机械修复(round14):随机后端反复犯同一批结构缺陷——缺 inciting/climax
承重节拍(STR-014)、植入扎堆(BM-002)、支线集主角缺席(STR-010)。相位重试只会
轮轮复述同一诊断而结构不变(实证 attempt 4/5 各烧 ~1.5h 死于同一批门禁),
机械修复把"指望模型遵守"换成"结构必然成立",优于烧轮次。"""

from nsc.passes.p3_beatsheet import _repair_brand_gap, _repair_load_bearing
from nsc.passes.p4_scene import _repair_protagonist_present


def _beat(i, kind, arousal=0.5):
    return {
        "id": f"b{i}",
        "order": i,
        "beat_kind": kind,
        "emotion": {"valence": 0.0, "arousal": arousal},
        "summary": f"节拍{i}",
    }


def _kinds(beats):
    return [b["beat_kind"] for b in beats]


# ---------- _repair_load_bearing(STR-014) ----------


def test_missing_climax_converts_highest_arousal_late_beat():
    beats = [
        _beat(0, "hook"),
        _beat(1, "inciting"),
        _beat(2, "escalation", 0.6),
        _beat(3, "brand_moment"),
        _beat(4, "escalation", 0.9),
        _beat(5, "cliffhanger"),
    ]
    _repair_load_bearing(beats)
    assert beats[4]["beat_kind"] == "climax"  # 唤起最高的后段非保护拍
    assert "inciting" in _kinds(beats) and beats[1]["beat_kind"] == "inciting"


def test_missing_inciting_converts_central_beat():
    beats = [
        _beat(0, "hook"),
        _beat(1, "setup", 0.3),
        _beat(2, "escalation", 0.8),
        _beat(3, "reversal", 0.4),
        _beat(4, "climax"),
        _beat(5, "cliffhanger"),
    ]
    _repair_load_bearing(beats)
    assert beats[2]["beat_kind"] == "inciting"  # 居中且唤起最高
    assert _kinds(beats).count("climax") == 1


def test_both_present_is_noop():
    beats = [_beat(0, "hook"), _beat(1, "inciting"), _beat(2, "climax"), _beat(3, "cliffhanger")]
    before = _kinds(beats)
    _repair_load_bearing(beats)
    assert _kinds(beats) == before


def test_never_touches_protected_kinds():
    """全保护拍的退化集:无可改写对象时不强行制造,交给检查器报真问题。"""
    beats = [
        _beat(0, "hook"),
        _beat(1, "brand_moment"),
        _beat(2, "brand_moment"),
        _beat(3, "cliffhanger"),
    ]
    _repair_load_bearing(beats)
    assert _kinds(beats) == ["hook", "brand_moment", "brand_moment", "cliffhanger"]


def test_climax_not_on_last_beat():
    """fix_hint:climax 紧邻集末终态之前——集末拍不许被改写为 climax。"""
    beats = [
        _beat(0, "hook"),
        _beat(1, "inciting"),
        _beat(2, "escalation", 0.7),
        _beat(3, "escalation", 0.99),
    ]
    _repair_load_bearing(beats)
    assert beats[2]["beat_kind"] == "climax"
    assert beats[3]["beat_kind"] == "escalation"


# ---------- _repair_brand_gap(BM-002,min_gap=2) ----------


def test_adjacent_brand_beats_get_spaced():
    beats = [_beat(0, "brand_moment"), _beat(1, "brand_moment")] + [
        _beat(i, "escalation") for i in range(2, 6)
    ]
    _repair_brand_gap(beats, 2)
    bm_idx = [i for i, b in enumerate(beats) if b["beat_kind"] == "brand_moment"]
    assert bm_idx[1] - bm_idx[0] >= 2
    assert [b["order"] for b in beats] == list(range(6))  # order 重排
    assert sorted(b["id"] for b in beats) == [f"b{i}" for i in range(6)]  # 一拍不丢


def test_gap_already_ok_is_noop():
    beats = [_beat(0, "brand_moment"), _beat(1, "escalation"), _beat(2, "brand_moment")]
    before = [b["id"] for b in beats]
    _repair_brand_gap(beats, 2)
    assert [b["id"] for b in beats] == before


def test_unfixable_gap_terminates_without_oscillation():
    """植入拍多过非植入拍时无处可挪:有限步内退出(历史上朴素 while 会在两种
    排列间振荡死循环),保持现状交给检查器。"""
    beats = [_beat(0, "brand_moment"), _beat(1, "brand_moment"), _beat(2, "brand_moment")]
    _repair_brand_gap(beats, 2)  # 不死循环即通过
    assert len(beats) == 3


def test_gap_repair_moves_later_brand_beat_not_earlier():
    beats = [
        _beat(0, "hook"),
        _beat(1, "brand_moment"),
        _beat(2, "escalation"),
        _beat(3, "brand_moment"),
        _beat(4, "escalation"),
        _beat(5, "cliffhanger"),
    ]
    _repair_brand_gap(beats, 3)
    bm_idx = [i for i, b in enumerate(beats) if b["beat_kind"] == "brand_moment"]
    assert bm_idx[1] - bm_idx[0] >= 3


# ---------- _repair_protagonist_present(STR-010) ----------


def _chars():
    return [
        {"id": "c-pro", "role": "protagonist"},
        {"id": "c-sup1", "role": "supporting"},
        {"id": "c-sup2", "role": "supporting"},
    ]


def _scene(chars):
    return {"id": "sc", "present_character_ids": list(chars)}


def test_protagonist_missing_added_to_biggest_scene():
    scenes = [_scene(["c-sup1"]), _scene(["c-sup1", "c-sup2"])]
    _repair_protagonist_present(scenes, _chars())
    assert "c-pro" in scenes[1]["present_character_ids"]
    assert "c-pro" not in scenes[0]["present_character_ids"]


def test_protagonist_present_is_noop():
    scenes = [_scene(["c-pro"]), _scene(["c-sup1"])]
    _repair_protagonist_present(scenes, _chars())
    assert scenes[1]["present_character_ids"] == ["c-sup1"]


def test_empty_scenes_no_crash():
    _repair_protagonist_present([], _chars())
    _repair_protagonist_present([_scene(["c-sup1"])], [])  # 无主角定义也不崩


def test_setup_payoff_kind_enum_coerced():
    """R4 attempt1 实证:NPC 把 Fact 的 type 值 'plot_event' 写进 setup_payoff.kind 炸 literal。"""
    from nsc.passes.p3_beatsheet import _coerce_enum

    allowed = ("prop", "line", "promise", "secret", "skill")
    assert _coerce_enum("plot_event", allowed, "promise") == "promise"
    assert _coerce_enum("secret", allowed, "promise") == "secret"  # 合法值原样
