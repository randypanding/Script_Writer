"""p1_bible：NormalizedBrief + BrandBrief → Character/Location/Prop/Motif/ToneSpec。"""

from __future__ import annotations

import json
from typing import Any

from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id


class Module(DSPyPass):
    signature = signatures.Bible
    pass_name = "p1_bible"


@cached_pass("p1_bible")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    out = Module()(
        ctx,
        {
            "normalized_brief": fragment["normalized_brief"],
            "brand_brief_json": json.dumps(ctx.brand, ensure_ascii=False),
            "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
            "retrieved_cases": fragment.get("retrieved_cases", ""),
        },
    )
    characters = _assign_ids(inner_json(out["characters_json"], "p1_bible", "characters_json"))
    locations = _assign_ids(inner_json(out["locations_json"], "p1_bible", "locations_json"))
    props = _assign_ids(inner_json(out["props_json"], "p1_bible", "props_json"))
    motifs = _assign_ids(inner_json(out["motifs_json"], "p1_bible", "motifs_json"))
    tone = inner_json(out["tone_json"], "p1_bible", "tone_json")
    for coll, name in ((characters, "characters"), (locations, "locations")):
        if not isinstance(coll, list) or not coll:
            raise PassFailure(None, f"p1_bible 输出的 {name} 为空")
    return {
        "characters": characters,
        "locations": locations,
        "props": props,
        "motifs": motifs,
        "tone": tone,
        "_usage": out["_usage"],
    }


def _assign_ids(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise PassFailure(None, "p1_bible 输出应为列表")
    return [{"id": new_id(), **{k: v for k, v in it.items() if k != "id"}} for it in items]
