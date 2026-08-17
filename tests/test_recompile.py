"""T-07 验收：依赖闭包与局部重编译。

test_voice_change_only_invalidates_prose：改 NarrativeVoice 只能失效 p6/p7（D27 的收益）。
test_recompile_episode_only_runs_that_episode：重编译第 5 集只触发该集 p3–p7（runs 表断言）。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from nsc.passes.pipeline import invalidation_closure


def test_voice_change_only_invalidates_prose():
    """改 voice.* 只能重跑 p6/p7（dep_graph.yaml::invalidation）。"""
    for field_name in ("voice.person", "voice.tense", "voice.style"):
        closure = invalidation_closure([field_name])
        passes = sorted(p for p, _gran in closure)
        assert passes == ["p6_prose", "p7_render"], (
            f"{field_name} 的失效闭包应为 p6/p7，实际 {closure}"
        )


def test_episode_logline_invalidates_self_episode_chain():
    closure = invalidation_closure(["episode.logline"])
    passes = sorted(p for p, _gran in closure)
    assert passes == ["p3_beatsheet", "p4_scene", "p5_dialogue", "p6_prose", "p7_render"]


def test_narrative_state_change_invalidates_p3_to_p7():
    """ADR-0012：facts/threads/state_variables/dark_threads 任一变更 → 全部集 p3..p7 失效。"""
    for field_name in (
        "facts.resolves",
        "threads.status",
        "state_variables.initial",
        "dark_threads.stages",
    ):
        closure = invalidation_closure([field_name])
        passes = sorted(p for p, _gran in closure)
        assert passes == ["p3_beatsheet", "p4_scene", "p5_dialogue", "p6_prose", "p7_render"], (
            f"{field_name} 的失效闭包应为 p3..p7，实际 {closure}"
        )


# ---------------------------------------------------------------- 桩路由
class StubRouter:
    """按调用顺序回放预置响应；p6 的 anchor_map 从输入里的真实 beat/line id 现算。"""

    def __init__(self, handlers: list) -> None:
        self.handlers = handlers
        self.calls: list[str] = []

    def resolve(self, tier: str) -> dict:
        return {"model": f"stub/{tier}", "temperature": 0.0, "max_tokens": 4000}

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        from nsc.runtime.models import LLMResult

        handler = self.handlers[len(self.calls)]
        self.calls.append(tier)
        inputs = json.loads(messages[-1]["content"])
        payload = handler(inputs)
        return LLMResult(
            text=json.dumps(payload, ensure_ascii=False),
            model_id="stub/model",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            wall_ms=1,
        )


def _golden_ep5():
    raw = json.loads(Path("tests/fixtures/golden/demo_tea_ir.json").read_text("utf-8"))
    ep = next(e for e in raw["episodes"] if e["no"] == 5)
    scenes = [s for s in raw["scenes"] if s["parent_id"] == ep["id"]]
    scene_ids = {s["id"] for s in scenes}
    beats = [b for b in raw["beats"] if b["parent_id"] in scene_ids]
    beat_ids = {b["id"] for b in beats}
    lines = [ln for ln in raw["lines"] if ln["parent_id"] in beat_ids]
    sp = next(
        sp
        for sp in raw["setup_payoffs"]
        if sp["setup_beat_id"] in beat_ids and sp["payoff_beat_id"] in beat_ids
    )
    return raw, ep, scenes, beats, lines, sp


def _make_stub():
    _raw, _ep, scenes, beats, lines, sp = _golden_ep5()
    beat_idx = {b["id"]: i for i, b in enumerate(beats)}

    def p3_handler(inputs):
        return {
            "beats_json": json.dumps(
                [
                    {
                        "beat_kind": b["beat_kind"],
                        "summary": b["summary"],
                        "function": b["function"],
                        "emotion": b["emotion"],
                        "est_duration_s": b["est_duration_s"],
                    }
                    for b in beats
                ],
                ensure_ascii=False,
            ),
            "setup_payoffs_json": json.dumps(
                [
                    {
                        "setup": beat_idx[sp["setup_beat_id"]],
                        "payoff": beat_idx[sp["payoff_beat_id"]],
                        "kind": sp["kind"],
                        "description": sp["description"],
                        "slug": "",
                    }
                ],
                ensure_ascii=False,
            ),
        }

    def p4_handler(inputs):
        return {
            "scenes_json": json.dumps(
                [
                    {
                        "location_id": sc["location_id"],
                        "time_of_day": sc["time_of_day"],
                        "interior": sc["interior"],
                        "present_character_ids": sc["present_character_ids"],
                        "goal": sc["goal"],
                        "conflict": sc["conflict"],
                        "turn": sc["turn"],
                        "entry": sc["entry"],
                        "exit": sc["exit"],
                        "summary": sc["summary"],
                    }
                    for sc in scenes
                ],
                ensure_ascii=False,
            ),
            "beat_to_scene": json.dumps(
                [{"beat_index": i, "scene_index": 0} for i in range(len(beats))]
            ),
        }

    def p5_handler(inputs):
        n_local = len(inputs["beats_json"] and json.loads(inputs["beats_json"]))
        local_beats = [b for b in beats if b["parent_id"] == scenes[0]["id"]]
        local_idx = {b["id"]: i for i, b in enumerate(local_beats)}
        assert n_local == len(local_beats)
        return {
            "lines_json": json.dumps(
                [
                    {
                        "beat_index": local_idx[ln["parent_id"]],
                        "line_type": ln["line_type"],
                        "character_id": ln["character_id"],
                        "text": ln["text"],
                        "subtext": ln["subtext"],
                        "delivery": ln["delivery"],
                        "is_brand_line": ln["is_brand_line"],
                    }
                    for ln in lines
                ],
                ensure_ascii=False,
            )
        }

    def p6_handler(inputs):
        swl = json.loads(inputs["scenes_with_lines_json"])
        paragraphs, anchor_map = [], []
        for sc in swl:
            for b in sc["beats"]:
                dlg = next((x for x in b["lines"] if x["line_type"] == "dialogue"), None)
                para = f"她后来想起这一刻。「{dlg['text']}」" if dlg else b["summary"]
                anchor_map.append(
                    {
                        "paragraph_index": len(paragraphs),
                        "beat_id": b["id"],
                        "line_ids": [x["id"] for x in b["lines"]],
                    }
                )
                paragraphs.append(para)
        return {
            "chapter_title": "第五章 一周之约",
            "paragraphs_json": json.dumps(paragraphs, ensure_ascii=False),
            "anchor_map_json": json.dumps(anchor_map, ensure_ascii=False),
        }

    return StubRouter([p3_handler, p4_handler, p5_handler, p6_handler])


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        router=_make_stub(),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


def test_recompile_episode_only_runs_that_episode(ctx):
    from nsc.passes.pipeline import recompile_episode
    from spec.ir.container import NarrativeIR
    from spec.ir.invariants import inv_16_id_stability

    raw = json.loads(Path("tests/fixtures/golden/demo_tea_ir.json").read_text("utf-8"))
    old = NarrativeIR.model_validate(raw)

    merged = recompile_episode(ctx, old, 5)

    ran = sorted({r["pass_name"] for r in ctx.store.runs()})
    assert ran == ["p3_beatsheet", "p4_scene", "p5_dialogue", "p6_prose", "p7_render"], (
        f"重编译第 5 集只能触发该集 p3–p7，实际 {ran}"
    )
    bad = inv_16_id_stability(old, merged)
    assert bad == [], f"INV-16 被违反：{[v.message for v in bad][:3]}"
    # 其他集内容逐字未动
    for ep_old, ep_new in zip(old.episodes, merged.episodes, strict=True):
        if ep_old.no != 5:
            assert ep_old.id == ep_new.id
    old_scene_ids = {s.id for s in old.scenes if s.parent_id != old.episodes[4].id}
    assert old_scene_ids <= {s.id for s in merged.scenes}
