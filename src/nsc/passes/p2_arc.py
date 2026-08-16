"""p2_arc：Bible → Season + Episode[] + 植入预算分配（placement_plan）。"""

from __future__ import annotations

import json
from typing import Any

from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id


class Module(DSPyPass):
    signature = signatures.Arc
    pass_name = "p2_arc"


@cached_pass("p2_arc")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    out = Module()(
        ctx,
        {
            "bible_json": json.dumps(fragment["bible"], ensure_ascii=False),
            "brand_brief_json": json.dumps(ctx.brand, ensure_ascii=False),
            "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
            "retrieved_cases": fragment.get("retrieved_cases", ""),
        },
    )
    episodes = inner_json(out["episodes_json"], "p2_arc", "episodes_json")
    placement = inner_json(out["placement_plan_json"], "p2_arc", "placement_plan_json")
    if not isinstance(episodes, list) or not episodes:
        raise PassFailure(None, "p2_arc 输出的 episodes 为空")
    if not isinstance(placement, list):
        raise PassFailure(None, "p2_arc 输出的 placement_plan 应为列表")

    season_id = new_id()
    season = {
        "id": season_id,
        "kind": "season",
        "parent_id": fragment["project_id"],
        "order": 0,
        "title": "",
        "arc_summary": out.get("season_arc", "") or "整季弧线",
        "theme": "",
        "provenance_id": ctx.run_id,
        "locked": False,
    }
    target = int(ctx.profile.get("duration_target_s", 90))
    ep_nodes = []
    for i, ep in enumerate(episodes):
        ep_nodes.append(
            {
                "id": new_id(),
                "kind": "episode",
                "parent_id": season_id,
                "order": i,
                "no": i + 1,
                "title": str(ep.get("title", "")).strip() or f"第{i + 1}集",
                "logline": str(ep.get("logline", "")).strip() or "（缺 logline）",
                "duration_target_s": int(ep.get("duration_target_s") or target),
                "hook_promise": str(ep.get("hook_promise", "")).strip(),
                "cliffhanger": str(ep.get("cliffhanger", "") or ""),
                "provenance_id": ctx.run_id,
                "locked": False,
            }
        )
    return {
        "season": season,
        "episodes": ep_nodes,
        "placement_plan": placement,
        "_usage": out["_usage"],
    }
