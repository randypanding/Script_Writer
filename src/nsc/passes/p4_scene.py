"""p4_scene：单集 Beat[] → Scene[] + Beat→Scene 归属。"""

from __future__ import annotations

import json
from typing import Any

from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id


class Module(DSPyPass):
    signature = signatures.SceneCards
    pass_name = "p4_scene"


@cached_pass("p4_scene")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    ep = fragment["episode"]
    beats = fragment["beats"]
    out = Module()(
        ctx,
        {
            "beats_json": json.dumps(_public_beats(beats), ensure_ascii=False),
            "bible_json": json.dumps(fragment["bible"], ensure_ascii=False),
            "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
        },
    )
    raw_scenes = inner_json(out["scenes_json"], "p4_scene", "scenes_json")
    mapping = inner_json(out["beat_to_scene"], "p4_scene", "beat_to_scene")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise PassFailure(ep["id"], "p4_scene 输出的 scenes 为空")

    scenes: list[dict[str, Any]] = []
    for i, sc in enumerate(raw_scenes):
        loc = sc.get("location_id", "")
        present = sc.get("present_character_ids") or []
        scenes.append(
            {
                "id": new_id(),
                "kind": "scene",
                "parent_id": ep["id"],
                "order": i,
                "location_id": loc,
                "time_of_day": sc.get("time_of_day", "unspecified"),
                "interior": bool(sc.get("interior", True)),
                "present_character_ids": present,
                "goal": str(sc.get("goal", "")).strip(),
                "conflict": str(sc.get("conflict", "")).strip(),
                "turn": str(sc.get("turn", "")).strip(),
                "entry": str(sc.get("entry", "")).strip(),
                "exit": str(sc.get("exit", "")).strip(),
                "summary": str(sc.get("summary", "")),
                "provenance_id": ctx.run_id,
                "locked": False,
            }
        )

    assigned = _assign(mapping, beats, scenes, ep)
    return {"episode_id": ep["id"], "scenes": scenes, "beats": assigned, "_usage": out["_usage"]}


def _public_beats(beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": i,
            "beat_kind": b["beat_kind"],
            "summary": b["summary"],
            "est_duration_s": b["est_duration_s"],
        }
        for i, b in enumerate(beats)
    ]


def _assign(
    mapping: Any,
    beats: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    ep: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(mapping, list):
        raise PassFailure(ep["id"], "p4_scene 输出的 beat_to_scene 应为列表")
    beat_to_scene: dict[int, int] = {}
    for m in mapping:
        beat_to_scene[int(m["beat_index"])] = int(m["scene_index"])
    out = []
    scene_counters: dict[int, int] = {}
    for i, b in enumerate(beats):
        si = beat_to_scene.get(i)
        if si is None or not (0 <= si < len(scenes)):
            raise PassFailure(ep["id"], f"第 {ep['no']} 集第 {i} 个 Beat 未分配到合法场景（{si}）")
        order = scene_counters.get(si, 0)
        scene_counters[si] = order + 1
        out.append({**b, "parent_id": scenes[si]["id"], "order": order})
    empty = [s["id"] for s in scenes if s["id"] not in {b["parent_id"] for b in out}]
    if empty:
        raise PassFailure(ep["id"], f"第 {ep['no']} 集存在空场景 {empty}")
    return out
