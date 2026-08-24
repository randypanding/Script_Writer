"""p4_scene._assign 映射项类型矫正(round10:随机后端 beat_to_scene 结构漂移实证)。"""
import pytest

from nsc.passes.p4_scene import _assign
from nsc.passes import PassFailure

BEATS = [{"id": f"b{i}"} for i in range(3)]
SCENES = [{"id": "s0"}, {"id": "s1"}]
EP = {"id": "ep1", "no": 1}


def test_canonical_entries():
    out = _assign([{"beat_index": 0, "scene_index": 0},
                   {"beat_index": 1, "scene_index": 0},
                   {"beat_index": 2, "scene_index": 1}], BEATS, SCENES, EP)
    assert [b["parent_id"] for b in out] == ["s0", "s0", "s1"]


def test_string_pair_entries():
    """NPC 输出 "0:0" 式字符串对。"""
    out = _assign(["0:0", "1:0", "2:1"], BEATS, SCENES, EP)
    assert [b["parent_id"] for b in out] == ["s0", "s0", "s1"]


def test_alt_key_names():
    """NPC 输出 beat/scene 键名变体。"""
    out = _assign([{"beat": 0, "scene": 0}, {"beat": 1, "scene": 0}, {"beat": 2, "scene": 1}],
                  BEATS, SCENES, EP)
    assert [b["parent_id"] for b in out] == ["s0", "s0", "s1"]


def test_dict_mapping():
    """NPC 输出 {"0": 0, "1": 0, "2": 1} 字典。"""
    out = _assign({"0": 0, "1": 0, "2": 1}, BEATS, SCENES, EP)
    assert [b["parent_id"] for b in out] == ["s0", "s0", "s1"]


def test_unsalvageable_raises_with_diagnostic():
    """矫正不了的项必须 PassFailure 且带可喂优化器的诊断。"""
    with pytest.raises(PassFailure) as ei:
        _assign([{"foo": "bar"}, {"beat_index": 1, "scene_index": 0},
                 {"beat_index": 2, "scene_index": 1}], BEATS, SCENES, EP)
    assert "beat_to_scene" in str(ei.value)
