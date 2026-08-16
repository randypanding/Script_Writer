"""p0_intake：RawBrief → NormalizedBrief + Constraint[]（轻量补全，tier_bulk）。"""

from __future__ import annotations

from typing import Any

from spec.passes import signatures

from . import DSPyPass, PassContext, cached_pass, inner_json, new_id


class Module(DSPyPass):
    signature = signatures.IntakeNormalize
    pass_name = "p0_intake"


@cached_pass("p0_intake")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    brief, brand = fragment["raw_brief"], fragment["raw_brand"]
    out = Module()(
        ctx,
        {
            "raw_input": brief.get("raw_request", ""),
            "brand_brief_json": _json(brand),
            "profile_json": _json(_profile_digest(ctx)),
        },
    )
    return {
        "normalized_brief": out["normalized_brief"],
        "missing_fields": inner_json(
            out["missing_fields_json"], "p0_intake", "missing_fields_json"
        ),
        "constraints": _compile_constraints(brand),
        "episode_count": int(brief.get("episode_count") or 0),
        "project_title": brief.get("project_title", ""),
        "notes": brief.get("notes", []),
        "_usage": out["_usage"],
    }


def _json(x: Any) -> str:
    import json

    return json.dumps(x, ensure_ascii=False)


def _profile_digest(ctx: PassContext) -> dict[str, Any]:
    p = ctx.profile
    return {
        "id": p.get("id"),
        "episode_count": p.get("episode_count"),
        "duration_target_s": p.get("duration_target_s"),
        "beats_per_episode": p.get("beats_per_episode"),
        "max_scenes_per_episode": p.get("max_scenes_per_episode"),
        "max_characters": p.get("max_characters"),
        "max_line_chars": p.get("max_line_chars"),
    }


def _compile_constraints(brand: dict[str, Any]) -> list[dict[str, Any]]:
    """BrandBrief → Constraint[]（机械映射，无 LLM）。规则知识在 spec/checks。"""
    out: list[dict[str, Any]] = []
    placement = brand.get("placement", {})
    legal = brand.get("legal", {})

    def add(source: str, rule: str, params: dict[str, Any], desc: str) -> None:
        out.append(
            {
                "id": new_id(),
                "source": source,
                "check_rule_id": rule,
                "params": params,
                "description": desc,
                "severity": "block",
            }
        )

    add("brand_brief", "BM-001", dict(placement), "单集植入密度受品牌预算约束")
    add("brand_brief", "BM-006", {}, "必覆盖卖点必须全部落到 BrandMoment")
    add("compliance", "DLG-001", {"banned": brand.get("banned_words", [])}, "禁用词零出现")
    add("compliance", "BM-011", {"competitors": legal.get("competitor_names", [])}, "竞品名零出现")
    add("brand_brief", "FCT-001", {}, "数字参数必须来自 facts")
    return out
