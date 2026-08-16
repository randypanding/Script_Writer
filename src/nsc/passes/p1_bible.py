"""p1_bible：NormalizedBrief + BrandBrief → Character/Location/Prop/Motif/ToneSpec。"""

from __future__ import annotations

import json
from typing import Any

from spec.ir.overlays import Character, Location, Motif, Prop, ToneSpec
from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id, with_diag
from .schema_bridge import filter_extra, schema_hint


class Module(DSPyPass):
    signature = signatures.Bible
    pass_name = "p1_bible"


#: 输出字段 → IR 模型（字段白名单真相在 spec/ir，机械派生给模型看，防发明 extra 字段）。
#: Motif.occurrence_beat_ids 引用尚不存在的 Beat（p3 才生成），p1 阶段不可填。
_OUTPUT_MODELS: dict[str, type] = {
    "characters_json": Character,
    "locations_json": Location,
    "props_json": Prop,
    "motifs_json": Motif,
    "tone_json": ToneSpec,
}
_HINT_SKIP: dict[str, tuple[str, ...]] = {"motifs_json": ("id", "occurrence_beat_ids")}


@cached_pass("p1_bible")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    out = Module()(
        ctx,
        with_diag(
            {
                "normalized_brief": fragment["normalized_brief"],
                "brand_brief_json": json.dumps(ctx.brand, ensure_ascii=False),
                "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
                "retrieved_cases": fragment.get("retrieved_cases", ""),
                "output_schema_hints": {
                    k: schema_hint(m, skip=_HINT_SKIP.get(k, ("id",)))
                    for k, m in _OUTPUT_MODELS.items()
                },
            },
            fragment,
        ),
    )
    characters = _assign_ids(
        filter_extra(inner_json(out["characters_json"], "p1_bible", "characters_json"), Character)
    )
    locations = _assign_ids(
        filter_extra(inner_json(out["locations_json"], "p1_bible", "locations_json"), Location)
    )
    props = _assign_ids(filter_extra(inner_json(out["props_json"], "p1_bible", "props_json"), Prop))
    motifs = _assign_ids(
        filter_extra(inner_json(out["motifs_json"], "p1_bible", "motifs_json"), Motif)
    )
    for m in motifs if isinstance(motifs, list) else []:
        m.pop("occurrence_beat_ids", None)  # p1 阶段 Beat 尚不存在，引用必为伪造
    tone = filter_extra(inner_json(out["tone_json"], "p1_bible", "tone_json"), ToneSpec)
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
