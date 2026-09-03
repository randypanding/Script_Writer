"""round16:p5 对白体量双补丁(实证 attempt1/3 全季 DLG-006 连灭,NPC 系统性欠量 ~26%):

1. 目标区间与门禁对齐——旧 chars_lo=0.8× 低于 DLG-006 下限 0.85×,模型全顺从也会死;
2. _expand_if_thin——欠量当场定点扩写,只接受严格增量;此处测纯函数部分。
"""

import json
from types import SimpleNamespace
from typing import cast

import diskcache

import nsc.runtime.cache as cache_mod
from nsc.passes import PassContext
from nsc.passes.p5_dialogue import (
    _dialogue_chars,
    _pad_thin_dialogue,
    _scene_dialogue_floor,
    run,
)
from nsc.runtime.provenance import RunsStore


def _ln(t, lt="dialogue"):
    return {"line_type": lt, "text": t}


def test_dialogue_chars_counts_only_dialogue():
    lines = [_ln("一二三四五"), _ln("动作行不算", "action"), _ln("六七")]
    assert _dialogue_chars(lines) == 7


def test_scene_dialogue_floor_matches_gate_ratio():
    ctx = cast(
        PassContext, SimpleNamespace(profile={"chars_per_second": 4.5, "duration_tolerance": 0.15})
    )
    beats = [{"est_duration_s": 50.0}, {"est_duration_s": 40.0}]  # 90s ≈ 一集
    floor = _scene_dialogue_floor(ctx, beats)
    # round16b:瞄准线 = 门禁线 + 6pp 余量(round20:ep8 差 12 字实证,仍远低于上限 1.15)
    assert floor == int(90 * 4.5 * 0.91) == 368
    assert floor > int(90 * 4.5 * 0.85)  # 严格高于门禁下限


def test_scene_dialogue_floor_defaults():
    ctx = cast(PassContext, SimpleNamespace(profile={}))
    beats = [{"est_duration_s": 100.0}]
    assert _scene_dialogue_floor(ctx, beats) == int(100 * 4.5 * 0.91)


def test_pad_thin_dialogue_noop_when_above_floor():
    ctx = cast(
        PassContext, SimpleNamespace(profile={"chars_per_second": 4.5, "duration_tolerance": 0.15})
    )
    beats = [{"est_duration_s": 50.0}, {"est_duration_s": 40.0}]
    long_text = "一" * 200
    lines = [_ln(long_text), _ln("动作行不算", "action"), _ln(long_text)]
    result = _pad_thin_dialogue(ctx, lines, beats)
    assert result is lines
    assert _dialogue_chars(result) == 400


def test_pad_thin_dialogue_meets_floor():
    ctx = cast(
        PassContext, SimpleNamespace(profile={"chars_per_second": 4.5, "duration_tolerance": 0.15})
    )
    beats = [{"est_duration_s": 50.0}, {"est_duration_s": 40.0}]
    lines = [_ln("呼"), _ln("walks", "action"), _ln("吸"), _ln("sits", "action")]
    result = _pad_thin_dialogue(ctx, lines, beats)
    assert _dialogue_chars(result) >= _scene_dialogue_floor(ctx, beats)


def test_pad_thin_dialogue_noop_when_no_dialogue():
    ctx = cast(
        PassContext, SimpleNamespace(profile={"chars_per_second": 4.5, "duration_tolerance": 0.15})
    )
    beats = [{"est_duration_s": 50.0}, {"est_duration_s": 40.0}]
    lines = [_ln("walks", "action"), _ln("sits", "action")]
    result = _pad_thin_dialogue(ctx, lines, beats)
    assert result is lines


def test_pad_thin_dialogue_pads_dialogue_only():
    ctx = cast(
        PassContext, SimpleNamespace(profile={"chars_per_second": 4.5, "duration_tolerance": 0.15})
    )
    beats = [{"est_duration_s": 50.0}, {"est_duration_s": 40.0}]
    lines = [_ln("呼"), _ln("walks", "action"), _ln("吸"), _ln("sits", "action")]
    action_texts = [ln["text"] for ln in lines if ln["line_type"] == "action"]
    result = _pad_thin_dialogue(ctx, lines, beats)
    assert _dialogue_chars(result) >= _scene_dialogue_floor(ctx, beats)
    assert [ln["text"] for ln in result if ln["line_type"] == "action"] == action_texts


def test_run_short_stub_meets_floor(tmp_path, monkeypatch):
    """DLG-006 mechanical fallback: thin LLM output must still meet floor."""
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))

    scene = {
        "id": "scene:001",
        "parent_id": "ep:001",
        "location_id": "loc:001",
        "time_of_day": "day",
        "interior": True,
        "present_character_ids": ["char:001"],
        "goal": "test",
        "conflict": "test",
        "turn": "test",
        "entry": "test",
        "exit": "test",
        "summary": "test scene",
    }
    beats = [
        {"id": "beat:001", "beat_kind": "setup", "summary": "beat 1", "est_duration_s": 50.0},
        {"id": "beat:002", "beat_kind": "complication", "summary": "beat 2", "est_duration_s": 40.0},
    ]
    characters = [{"id": "char:001", "name": "Alice"}]
    fragment = {
        "scene": scene,
        "beats": beats,
        "characters": characters,
        "brand_constraints": {},
    }

    ctx = PassContext(
        profile={"chars_per_second": 4.5, "duration_tolerance": 0.15},
        brand={"must_include_lines": [], "must_include_visuals": []},
        brief={},
        router=None,
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )

    class MockModule:
        def __call__(self, ctx, inputs):
            in_beats = json.loads(inputs["beats_json"])
            out_lines = []
            for i, _b in enumerate(in_beats):
                out_lines.append(
                    {
                        "beat_index": i,
                        "line_type": "dialogue",
                        "character_id": "char:001",
                        "text": "呼",
                        "subtext": "",
                        "delivery": "",
                        "is_brand_line": False,
                    }
                )
                out_lines.append(
                    {
                        "beat_index": i,
                        "line_type": "action",
                        "character_id": None,
                        "text": "walks",
                        "subtext": "",
                        "delivery": "",
                        "is_brand_line": False,
                    }
                )
            return {"lines_json": json.dumps(out_lines, ensure_ascii=False), "_usage": {}}

    import nsc.passes.p5_dialogue as p5_mod

    monkeypatch.setattr(p5_mod, "Module", MockModule)
    monkeypatch.setattr(
        p5_mod, "_self_check", lambda ctx, inputs, scene, beats, lines, chars, out: (lines, out)
    )
    monkeypatch.setattr(
        p5_mod,
        "_expand_if_thin",
        lambda ctx, inputs, scene, beats, lines, chars, out: (lines, out),
    )

    result = run(ctx, fragment)
    floor = _scene_dialogue_floor(ctx, beats)
    actual = _dialogue_chars(result["lines"])
    assert actual >= floor, f"dialogue {actual} < floor {floor}"
