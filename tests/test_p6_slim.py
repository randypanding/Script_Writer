"""round17:p6 prompt 瘦身投影(实证 p6 首达 prompt 46631 字符撞 shim 护栏):

- _slim_scenes:剥 IR 管理字段,保留 id(anchor_map 硬契约)与叙事字段;
- _slim_profile:只留下笔/时长相关键;
- _slim_bible_for_episode:角色/地点按集过滤。
"""
import json

from nsc.passes.p6_prose import _slim_profile, _slim_scenes
from nsc.passes.pipeline import _slim_bible_for_episode


def _scene():
    return {
        "id": "sc1", "kind": "scene", "parent_id": "ep1", "order": 0,
        "location_id": "loc1", "location_name": "茶店", "time_of_day": "afternoon",
        "present_character_ids": ["c1", "c2"], "character_names": ["小满", "阿茶"],
        "goal": "g", "conflict": "c", "turn": "t", "summary": "s",
        "entry": "e", "exit": "x", "knowledge_state": {"k": "v"},
        "provenance_id": "run", "locked": False,
        "beats": [
            {
                "id": "b1", "kind": "beat", "parent_id": "sc1", "order": 0,
                "beat_kind": "hook", "summary": "开场", "est_duration_s": 12.0,
                "emotion": {"valence": 0.1, "arousal": 0.5}, "provenance_id": "run",
                "lines": [
                    {"id": "l1", "kind": "line", "parent_id": "b1", "order": 0,
                     "line_type": "dialogue", "character_id": "c1", "text": "台词",
                     "subtext": "s", "delivery": "d", "is_brand_line": False,
                     "provenance_id": "run", "locked": False}
                ],
            }
        ],
    }


def test_slim_scenes_keeps_ids_and_narrative_drops_fat():
    slim = _slim_scenes([_scene()])[0]
    assert slim["id"] == "sc1"
    assert "knowledge_state" not in slim and "provenance_id" not in slim and "locked" not in slim
    beat = slim["beats"][0]
    assert beat["id"] == "b1" and "est_duration_s" not in beat and "emotion" not in beat
    line = beat["lines"][0]
    assert line["id"] == "l1" and line["text"] == "台词" and "provenance_id" not in line


def test_slim_scenes_shrinks_size():
    sc = _scene()
    assert len(json.dumps(_slim_scenes([sc]), ensure_ascii=False)) < len(
        json.dumps([sc], ensure_ascii=False)
    )


def test_slim_profile():
    prof = {"novel": {"enabled": True}, "chars_per_second": 4.5, "pipeline": {"x": 1},
            "retrieval": {"y": 2}, "genre": "drama"}
    slim = _slim_profile(prof)
    assert set(slim) == {"novel", "chars_per_second", "genre"}


def test_slim_bible_for_episode():
    bible = {
        "characters": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
        "locations": [{"id": "loc1"}, {"id": "loc2"}],
        "props": [{"id": "p1"}],
        "tone": {"register": "warm"},
        "motifs": ["茶"],
    }
    slim = _slim_bible_for_episode(bible, [_scene()])
    assert {c["id"] for c in slim["characters"]} == {"c1", "c2"}
    assert [loc["id"] for loc in slim["locations"]] == ["loc1"]
    assert "props" not in slim and slim["tone"] == {"register": "warm"}
