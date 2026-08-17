"""p4_scene：单集 Beat[] → Scene[] + Beat→Scene 归属（含场级节奏/知识状态字段）。"""

from __future__ import annotations

import json
from typing import Any

from spec.ir.nodes import KnowledgeState, Scene
from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id, with_diag
from .schema_bridge import allowed_values, schema_hint

#: Scene 字段真相在 spec/ir；Pass 自动分配的字段不给模型看。
_SCENE_HINT = schema_hint(
    Scene, skip=("id", "kind", "parent_id", "order", "provenance_id", "locked")
)
_TOD = allowed_values(Scene, "time_of_day")


class Module(DSPyPass):
    signature = signatures.SceneCards
    pass_name = "p4_scene"


@cached_pass("p4_scene")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    ep = fragment["episode"]
    beats = fragment["beats"]
    out = Module()(
        ctx,
        with_diag(
            {
                "beats_json": json.dumps(_public_beats(beats), ensure_ascii=False),
                "bible_json": json.dumps(fragment["bible"], ensure_ascii=False),
                "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
                "scene_schema_hint": _SCENE_HINT,
            },
            fragment,
        ),
    )
    raw_scenes = inner_json(out["scenes_json"], "p4_scene", "scenes_json")
    mapping = inner_json(out["beat_to_scene"], "p4_scene", "beat_to_scene")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise PassFailure(ep["id"], "p4_scene 输出的 scenes 为空")

    scenes: list[dict[str, Any]] = []
    bible_chars = fragment["bible"].get("characters", [])
    bible_locs = fragment["bible"].get("locations", [])
    loc_ids = {str(loc.get("id")) for loc in bible_locs}
    loc_by_name = {str(loc.get("name", "")): str(loc.get("id")) for loc in bible_locs}
    char_ids = {str(c.get("id")) for c in bible_chars}
    char_by_name = {str(c.get("name", "")): str(c.get("id")) for c in bible_chars}
    for i, sc in enumerate(raw_scenes):
        loc = str(sc.get("location_id", ""))
        if loc not in loc_ids:  # 模型可能给了地点名而非 ULID：机械回退按名字解析
            loc = loc_by_name.get(loc.strip(), loc)
        if loc not in loc_ids:  # 伪造引用：拦截驱动重试（避免 ValidationError 崩管线）
            raise PassFailure(
                ep["id"],
                f"场景引用了不存在的 location_id={loc}。只能使用 bible 里的地点 id"
                f"（{sorted(loc_ids)}）或地点名。",
            )
        tod = str(sc.get("time_of_day", "unspecified")).strip().lower()
        present: list[str] = []
        for cid in sc.get("present_character_ids") or []:  # 角色名同理回退
            cid = str(cid)
            cid = cid if cid in char_ids else char_by_name.get(cid.strip(), cid)
            if cid not in char_ids:
                raise PassFailure(
                    ep["id"],
                    f"场景引用了不存在的角色 {cid}。只能使用 bible 里的角色 id"
                    f"（{sorted(char_ids)}）或角色名。",
                )
            present.append(cid)
        scenes.append(
            {
                "id": new_id(),
                "kind": "scene",
                "parent_id": ep["id"],
                "order": i,
                "location_id": loc,
                "time_of_day": tod if tod in _TOD else "unspecified",
                "interior": bool(sc.get("interior", True)),
                "present_character_ids": present,
                "goal": str(sc.get("goal", "")).strip(),
                "conflict": str(sc.get("conflict", "")).strip(),
                "turn": str(sc.get("turn", "")).strip(),
                "entry": str(sc.get("entry", "")).strip(),
                "exit": str(sc.get("exit", "")).strip(),
                "summary": str(sc.get("summary", "")),
                # --- ADR-0012 场级节奏与知识状态（可缺省→默认空） ---
                "opening_attractor": str(sc.get("opening_attractor", "") or ""),
                "escalation_beats": _escalation(sc.get("escalation_beats")),
                "ending_hook": str(sc.get("ending_hook", "") or ""),
                "knowledge_state": _knowledge_state(sc.get("knowledge_state")),
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


def _escalation(raw: Any) -> list[str]:
    """escalation_beats 机械归一（ADR-0012，省略→空表）：非 list/空串条目丢弃。"""
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _knowledge_state(raw: Any) -> dict[str, str] | None:
    """knowledge_state 机械归一（ADR-0012，省略→None）：extra 键过滤防 ValidationError。"""
    if not isinstance(raw, dict):
        return None
    return {k: str(v) for k, v in raw.items() if k in KnowledgeState.model_fields} or None


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
