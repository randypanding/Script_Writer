"""p1_bible：NormalizedBrief + BrandBrief → Character/Location/Prop/Motif/ToneSpec。"""

from __future__ import annotations

import json
from typing import Any

from spec.ir.nodes import ExpressionDNA, MentalModel
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
        _null_str_fields_to_default(
            filter_extra(inner_json(out["characters_json"], "p1_bible", "characters_json"), Character),
            Character,
        )
    )
    characters = _sanitize_mind(characters)
    locations = _assign_ids(
        _null_str_fields_to_default(
            filter_extra(inner_json(out["locations_json"], "p1_bible", "locations_json"), Location),
            Location,
        )
    )
    props = _assign_ids(_sanitize_props(filter_extra(inner_json(out["props_json"], "p1_bible", "props_json"), Prop)))
    motifs = _assign_ids(
        _null_str_fields_to_default(
            filter_extra(inner_json(out["motifs_json"], "p1_bible", "motifs_json"), Motif),
            Motif,
        )
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


def _null_str_fields_to_default(coll: Any, model_cls: Any) -> Any:
    """通用归一:NPC 显式给字段 null 时归一为字段默认值/默认工厂产出
    (pydantic str/list 拒 None;随机后端 ValidationError props.sku_ref、
    characters.persona_ref 系列实证)。"""
    from pydantic_core import PydanticUndefined

    if not isinstance(coll, list):
        return coll
    for item in coll:
        if not isinstance(item, dict):
            continue
        for name, f in model_cls.model_fields.items():
            if item.get(name) is None:
                if f.default is not None and f.default is not PydanticUndefined:
                    item[name] = f.default
                elif f.default_factory is not None:
                    item[name] = f.default_factory()
            elif item.get(name) == "" and f.is_required() and f.annotation is str:
                # NPC 给空串(实证 round18 attempt1 characters.4.need string_too_short):
                # 必填 str 空串必炸校验,占位与 null 归一同哲学——残缺输入宁占位不崩管线
                item[name] = "（未填）"
    return coll


def _sanitize_props(props: Any) -> Any:
    """Prop 机械归一:NPC 显式给 sku_ref=null 时归一为 ""(pydantic str 拒 None;
    随机后端 ValidationError props.N.sku_ref 实证)。"""
    return _null_str_fields_to_default(props, Prop)


def _sanitize_mind(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """角色心智 OS（ADR-0012）机械归一：省略 → 默认空；嵌套 extra 键过滤、畸形条目丢弃。

    IR 模型全部 extra="forbid"，模型发明的嵌套键会炸校验——与 filter_extra 同一哲学，
    在 Pass 边界把四个可选字段清洗成一定能通过 Character 校验的形态。
    """
    for c in characters:
        models = []
        for m in c.get("mental_models") or []:
            if not isinstance(m, dict):
                continue
            m = {k: str(v) for k, v in m.items() if k in MentalModel.model_fields and v is not None}
            if str(m.get("name", "")).strip():
                models.append(m)
        c["mental_models"] = models[:5]  # Character 契约 max_length=5
        c["decision_heuristics"] = _str_list(c.get("decision_heuristics"))[:7]  # max_length=7
        c["honest_boundaries"] = _str_list(c.get("honest_boundaries"))
        c["expression_dna"] = _sanitize_dna(c.get("expression_dna"))
    return characters


def _sanitize_dna(dna: Any) -> dict[str, Any] | None:
    if not isinstance(dna, dict):
        return None
    out: dict[str, Any] = {
        k: str(v)
        for k, v in dna.items()
        if k in ExpressionDNA.model_fields and k != "signature_lines" and v is not None
    }
    lines = dna.get("signature_lines")
    out["signature_lines"] = [str(x) for x in lines] if isinstance(lines, list) else []
    return out


def _str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _assign_ids(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise PassFailure(None, "p1_bible 输出应为列表")
    return [{"id": new_id(), **{k: v for k, v in it.items() if k != "id"}} for it in items]
