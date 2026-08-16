"""p3_beatsheet：单集 Beat 序列 + SetupPayoff 声明 + BrandMoment 落成。

输出契约（对 setup_payoffs_json 的每个条目）：
  {"slug": str, "setup": int | "PENDING:<slug>", "payoff": int | "PENDING:<slug>",
   "kind": "prop|line|promise|secret|skill", "description": str}
跨集回收用 "PENDING:<slug>"，由 pipeline 的全季后处理解引用；解不出即 PassFailure。
"""

from __future__ import annotations

import json
from typing import Any

from spec.ir.nodes import Beat
from spec.ir.overlays import BrandMoment
from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id, with_diag
from .schema_bridge import allowed_values, schema_hint

#: Beat 字段真相在 spec/ir；Pass 自动分配的字段不给模型看。
_BEAT_HINT = schema_hint(
    Beat, skip=("id", "kind", "parent_id", "order", "provenance_id", "locked", "brand_moment_id")
)

#: setup_payoffs_json 的格式契约（本模块输出契约，机械复述给模型，防把下标写成描述）。
_SP_CONTRACT = (
    'setup_payoffs_json 每个条目形如 {"slug":"小写短标识","setup":<beats_json 的下标 int>,'
    '"payoff":<beats_json 的下标 int> 或 "PENDING:<对方条目 slug>","kind":"prop|line|promise|secret|skill",'
    '"description":"一句话"}。setup/payoff 只能填整数下标（0 起）或 PENDING 字符串，'
    "绝不能填情节描述文字。"
)


class Module(DSPyPass):
    signature = signatures.BeatSheet
    pass_name = "p3_beatsheet"


@cached_pass("p3_beatsheet")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    ep = fragment["episode"]
    out = Module()(
        ctx,
        with_diag(
            {
                "episode_json": json.dumps(ep, ensure_ascii=False),
                "bible_json": json.dumps(fragment["bible"], ensure_ascii=False),
                "placement_for_episode": json.dumps(fragment["placement"], ensure_ascii=False),
                "prev_episode_summary": fragment.get("prev_episode_summary", ""),
                "next_episode_promise": fragment.get("next_episode_promise", ""),
                "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
                "retrieved_cases": fragment.get("retrieved_cases", ""),
                "beat_schema_hint": _BEAT_HINT,
                "setup_payoffs_contract": _SP_CONTRACT,
                "required_brand_moment_beats": fragment.get("required_brand_moment_beats", 0),
                # 品牌植入预算真相（brand.placement）：间隔/密度/禁用 Beat 类型，排布时必须遵守
                "brand_placement_budget": json.dumps(
                    ctx.brand.get("placement", {}), ensure_ascii=False
                ),
            },
            fragment,
        ),
    )
    raw_beats = inner_json(out["beats_json"], "p3_beatsheet", "beats_json")
    raw_sps = inner_json(out["setup_payoffs_json"], "p3_beatsheet", "setup_payoffs_json")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise PassFailure(ep["id"], "p3_beatsheet 输出的 beats 为空")

    beats: list[dict[str, Any]] = []
    for i, b in enumerate(raw_beats):
        emo = b.get("emotion") or {}
        summary = str(b.get("summary", "")).strip()
        if not summary:
            raise PassFailure(ep["id"], f"第 {ep['no']} 集第 {i} 个 Beat 缺 summary")
        beats.append(
            {
                "id": new_id(),
                "kind": "beat",
                "parent_id": None,  # p4 装配场景后回填
                "order": i,
                "beat_kind": b.get("beat_kind", ""),
                "summary": summary,
                "function": str(b.get("function", "")),
                "emotion": {
                    "valence": float(emo.get("valence", 0.0)),
                    "arousal": float(emo.get("arousal", 0.0)),
                },
                "est_duration_s": float(b.get("est_duration_s", 0.0)),
                "brand_moment_id": None,  # 下方回填
                "provenance_id": ctx.run_id,
                "locked": False,
                "_episode_id": ep["id"],
            }
        )

    brand_moments = _attach_brand_moments(beats, fragment["placement"], ep)
    setup_payoffs = _attach_setup_payoffs(raw_sps, beats, ep)
    return {
        "episode_id": ep["id"],
        "beats": beats,
        "brand_moments": brand_moments,
        "setup_payoffs": setup_payoffs,
        "_usage": out["_usage"],
    }


def _coerce_intensity(v: Any) -> int:
    """IR 契约 intensity ∈ [1,5]（int）。模型若给语义词/越界值，机械归一到合法值域。"""
    try:
        return min(max(int(v), 1), 5)
    except (TypeError, ValueError):
        return {"very_low": 1, "low": 2, "medium": 3, "high": 4, "very_high": 5}.get(
            str(v).strip().lower(), 2
        )


def _coerce_enum(v: Any, allowed: tuple[str, ...], default: str) -> str:
    """IR Literal 值域机械归一：合法原样，别名映射，非法落默认。值域真相在 spec/ir。"""
    s = str(v).strip().lower()
    if s in allowed:
        return s
    aliases = {"audio": "verbal", "text": "verbal", "strong": "high", "weak": "low"}
    return aliases.get(s, default)


def _attach_brand_moments(
    beats: list[dict[str, Any]], placement: list[dict[str, Any]], ep: dict[str, Any]
) -> list[dict[str, Any]]:
    bm_beats = [b for b in beats if b["beat_kind"] == "brand_moment"]
    if len(bm_beats) != len(placement):
        raise PassFailure(
            ep["id"],
            f"第 {ep['no']} 集有 {len(bm_beats)} 个 brand_moment Beat，"
            f"但植入预算分配了 {len(placement)} 处。请让两者一一对应。",
        )
    out = []
    for b, plan in zip(bm_beats, placement, strict=True):
        bm_id = new_id()
        b["brand_moment_id"] = bm_id
        out.append(
            {
                "id": bm_id,
                "anchor_beat_id": b["id"],
                "type": _coerce_enum(
                    plan.get("type", "scene"), allowed_values(BrandMoment, "type"), "scene"
                ),
                "intensity": _coerce_intensity(plan.get("intensity", 2)),
                "modality": _coerce_enum(
                    plan.get("modality", "visual"),
                    allowed_values(BrandMoment, "modality"),
                    "visual",
                ),
                "plot_connection": _coerce_enum(
                    plan.get("plot_connection", "low"),
                    allowed_values(BrandMoment, "plot_connection"),
                    "low",
                ),
                "selling_point_id": plan.get("selling_point_id", ""),
                "proof_mode": _coerce_enum(
                    plan.get("proof_mode", "reaction"),
                    allowed_values(BrandMoment, "proof_mode"),
                    "reaction",
                ),
                "integration_note": str(plan.get("intent", "")).strip() or "（缺植入说明）",
                "prop_id": plan.get("prop_id") or None,
            }
        )
    return out


def _attach_setup_payoffs(
    raw_sps: Any, beats: list[dict[str, Any]], ep: dict[str, Any]
) -> list[dict[str, Any]]:
    if not isinstance(raw_sps, list):
        raise PassFailure(ep["id"], "p3_beatsheet 输出的 setup_payoffs 应为列表")
    out = []
    for sp in raw_sps:
        entry = {
            "id": new_id(),
            "kind": sp.get("kind", "promise"),
            "description": str(sp.get("description", "")).strip() or "（缺伏笔描述）",
            "_slug": str(sp.get("slug", "")),
            "_episode_id": ep["id"],
        }
        for side in ("setup", "payoff"):
            ref = sp.get(side)
            if isinstance(ref, str) and ref.startswith("PENDING:"):
                entry[f"{side}_beat_id"] = ref
            elif isinstance(ref, int) and 0 <= ref < len(beats):
                entry[f"{side}_beat_id"] = beats[ref]["id"]
            else:
                raise PassFailure(
                    ep["id"],
                    f"第 {ep['no']} 集的伏笔条目引用非法 {side}={ref!r}"
                    "（应为 Beat 下标或 PENDING:<slug>）",
                )
        out.append(entry)
    return out


def resolve_pending(setup_payoffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全季后处理：解引用 PENDING:<slug>。规则：slug 相同的条目互为两端。"""
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for sp in setup_payoffs:
        by_slug.setdefault(sp["_slug"], []).append(sp)
    for slug, group in by_slug.items():
        for sp in group:
            for side in ("setup", "payoff"):
                ref = sp[f"{side}_beat_id"]
                if isinstance(ref, str) and ref.startswith("PENDING:"):
                    target_slug = ref[len("PENDING:") :]
                    donor = next(
                        (
                            g
                            for g in by_slug.get(target_slug, [])
                            if g is not sp and not str(g[f"{side}_beat_id"]).startswith("PENDING:")
                        ),
                        None,
                    )
                    if donor is None:
                        raise PassFailure(
                            sp["_episode_id"],
                            f"伏笔 {sp['description']} 的 {side} 引用 PENDING:{target_slug} "
                            "无法解引用（没有对应条目提供真实 Beat）",
                        )
                    sp[f"{side}_beat_id"] = donor[f"{side}_beat_id"]
        if slug:
            continue
    return [
        {
            "id": sp["id"],
            "setup_beat_id": sp["setup_beat_id"],
            "payoff_beat_id": sp["payoff_beat_id"],
            "kind": sp["kind"],
            "description": sp["description"],
        }
        for sp in setup_payoffs
    ]
