"""p5_dialogue：单场 → Line[]。"""

from __future__ import annotations

import json
from typing import Any

from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id


class Module(DSPyPass):
    signature = signatures.Dialogue
    pass_name = "p5_dialogue"


@cached_pass("p5_dialogue")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    scene = fragment["scene"]
    beats = fragment["beats"]
    out = Module()(
        ctx,
        {
            "scene_json": json.dumps(_public_scene(scene), ensure_ascii=False),
            "beats_json": json.dumps(
                [
                    {"index": i, "beat_kind": b["beat_kind"], "summary": b["summary"]}
                    for i, b in enumerate(beats)
                ],
                ensure_ascii=False,
            ),
            "characters_json": json.dumps(fragment["characters"], ensure_ascii=False),
            "brand_constraints": json.dumps(fragment["brand_constraints"], ensure_ascii=False),
            "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
            "retrieved_cases": fragment.get("retrieved_cases", ""),
        },
    )
    raw_lines = inner_json(out["lines_json"], "p5_dialogue", "lines_json")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise PassFailure(scene["id"], "p5_dialogue 输出的 lines 为空")

    per_beat: dict[int, int] = {}
    lines: list[dict[str, Any]] = []
    for ln in raw_lines:
        bi = int(ln.get("beat_index", -1))
        if not (0 <= bi < len(beats)):
            raise PassFailure(scene["id"], f"台词引用了非法 beat_index={bi}")
        order = per_beat.get(bi, 0)
        per_beat[bi] = order + 1
        lines.append(
            {
                "id": new_id(),
                "kind": "line",
                "parent_id": beats[bi]["id"],
                "order": order,
                "line_type": ln.get("line_type", "dialogue"),
                "character_id": ln.get("character_id") or None,
                "text": str(ln.get("text", "")).strip(),
                "subtext": str(ln.get("subtext", "")),
                "delivery": str(ln.get("delivery", "")),
                "is_brand_line": bool(ln.get("is_brand_line", False)),
                "provenance_id": ctx.run_id,
                "locked": False,
            }
        )
    bare = [b["id"] for b in beats if b["id"] not in {ln["parent_id"] for ln in lines}]
    if bare:
        raise PassFailure(scene["id"], f"以下 Beat 没有任何台词：{bare}")
    empties = [ln["id"] for ln in lines if not ln["text"]]
    if empties:
        raise PassFailure(scene["id"], f"存在空文本台词：{empties}")
    return {"scene_id": scene["id"], "lines": lines, "_usage": out["_usage"]}


def _public_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        k: scene[k]
        for k in (
            "location_id",
            "time_of_day",
            "interior",
            "present_character_ids",
            "goal",
            "conflict",
            "turn",
            "entry",
            "exit",
            "summary",
        )
        if k in scene
    }
