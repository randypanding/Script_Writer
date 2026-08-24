"""p3_beatsheet：单集 Beat 序列 + SetupPayoff 声明 + BrandMoment 落成 + 叙事状态声明。

输出契约（对 setup_payoffs_json 的每个条目）：
  {"slug": str, "setup": int | "PENDING:<slug>", "payoff": int | "PENDING:<slug>",
   "kind": "prop|line|promise|secret|skill", "description": str}
跨集回收用 "PENDING:<slug>"，由 pipeline 的全季后处理解引用；解不出即 PassFailure。

ADR-0012 可缺省输出（省略即空表）：
  facts_json：resolves 填同集下标、已知前集 fact 的 id（known_facts）或 null；
  跨集回收状态级联不做 PENDING 解引用（SetupPayoff 的 slug 机制与 Fact 的 id 语义不同），
  由 apply_fact_cascade 全季统一翻转（等价于 resolve_pending 的后处理角色）。
  state_changes_json：key 只能用 declared_state 里已声明的状态变量/暗线 key。
"""

from __future__ import annotations

import json
from typing import Any

from spec.ir.nodes import Beat
from spec.ir.overlays import BrandMoment, Fact
from spec.passes import signatures

from . import (
    DSPyPass,
    PassContext,
    PassFailure,
    cached_pass,
    contract_text,
    inner_json,
    new_id,
    optional_json,
    with_diag,
)
from .schema_bridge import allowed_values, schema_hint

#: Beat 字段真相在 spec/ir；Pass 自动分配的字段不给模型看。
_BEAT_HINT = schema_hint(
    Beat, skip=("id", "kind", "parent_id", "order", "provenance_id", "locked", "brand_moment_id")
)

#: 三条输出格式契约的文案真相在 spec/passes/contracts.yaml（SW-03 / ADR-0015）。
_SP_CONTRACT = contract_text("p3_beatsheet", "setup_payoffs")
_FACT_CONTRACT = contract_text("p3_beatsheet", "facts")
_SC_CONTRACT = contract_text("p3_beatsheet", "state_changes")


class Module(DSPyPass):
    signature = signatures.BeatSheet
    pass_name = "p3_beatsheet"
    optional_outputs = ("facts_json", "state_changes_json")


@cached_pass("p3_beatsheet")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    ep = fragment["episode"]
    inputs = {
        "episode_json": json.dumps(ep, ensure_ascii=False),
        "bible_json": json.dumps(fragment["bible"], ensure_ascii=False),
        "placement_for_episode": json.dumps(fragment["placement"], ensure_ascii=False),
        "prev_episode_summary": fragment.get("prev_episode_summary", ""),
        "next_episode_promise": fragment.get("next_episode_promise", ""),
        "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
        "retrieved_cases": fragment.get("retrieved_cases", ""),
        "beat_schema_hint": _BEAT_HINT,
        "setup_payoffs_contract": _SP_CONTRACT,
        "facts_contract": _FACT_CONTRACT,
        "state_changes_contract": _SC_CONTRACT,
        "known_facts": json.dumps(fragment.get("known_facts", []), ensure_ascii=False),
        "declared_state": json.dumps(fragment.get("declared_state", {}), ensure_ascii=False),
        "required_brand_moment_beats": fragment.get("required_brand_moment_beats", 0),
        # 品牌植入预算真相（brand.placement）：间隔/密度/禁用 Beat 类型，排布时必须遵守
        "brand_placement_budget": json.dumps(ctx.brand.get("placement", {}), ensure_ascii=False),
    }
    # T-41 idea bank：可选"可复活素材"层（pipeline 组装，空则不加）
    revivable = str(fragment.get("revivable_ideas", "") or "")
    if revivable:
        inputs["revivable_ideas"] = revivable
    # SW-05：Thread 注入（profile.context.inject_threads 开关，pipeline 组装 JSON）
    threads = str(fragment.get("threads", "") or "")
    if threads:
        inputs["threads"] = threads
    out = Module()(ctx, with_diag(inputs, fragment))
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

    setup_payoffs = _attach_setup_payoffs(raw_sps, beats, ep)  # 先按下标解引用:下方修复换序不影响
    _repair_load_bearing(beats)
    _repair_brand_gap(beats, _min_gap_beats(ctx))
    _rescale_durations(beats, ep)
    brand_moments = _attach_brand_moments(beats, fragment["placement"], ep)
    facts = _attach_facts(
        optional_json(out, "facts_json", "p3_beatsheet"), ep, fragment.get("known_facts", [])
    )
    state_changes = _attach_state_changes(
        optional_json(out, "state_changes_json", "p3_beatsheet"),
        ep,
        fragment.get("declared_state", {}),
    )
    return {
        "episode_id": ep["id"],
        "beats": beats,
        "brand_moments": brand_moments,
        "setup_payoffs": setup_payoffs,
        "facts": facts,
        "state_changes": state_changes,
        "_usage": out["_usage"],
    }


#: 承重/特殊拍：机械修复永不动这些 kind（品牌拍有数量契约、hook/cliffhanger 有首尾语义）。
_PROTECTED_KINDS = frozenset({"hook", "brand_moment", "cliffhanger", "inciting", "climax"})


def _repair_load_bearing(beats: list[dict[str, Any]]) -> None:
    """STR-014 机械兜底：缺 inciting/climax 时把最合适的非保护 Beat 改写之。

    随机后端常漏 climax（实证 attempt 4/5 同门连死两轮），相位重试只复述诊断不改结构。
    inciting 取居中且唤起最高者（fix_hint），climax 取后段唤起最高者且不落集末拍。
    """
    n = len(beats)
    kinds = {b["beat_kind"] for b in beats}
    if "inciting" not in kinds:
        pool = [b for b in beats if b["beat_kind"] not in _PROTECTED_KINDS]
        if pool:
            center = (n - 1) / 2
            pick = max(pool, key=lambda b: (b["emotion"]["arousal"], -abs(b["order"] - center)))
            pick["beat_kind"] = "inciting"
    if "climax" not in kinds:
        pool = [
            b
            for b in beats
            if b["beat_kind"] not in _PROTECTED_KINDS and b["order"] < n - 1
        ]
        if pool:
            pick = max(pool, key=lambda b: (b["emotion"]["arousal"], b["order"]))
            pick["beat_kind"] = "climax"


def _min_gap_beats(ctx: PassContext) -> int:
    try:
        return int(ctx.brand.get("placement", {}).get("min_gap_beats", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _repair_brand_gap(beats: list[dict[str, Any]], min_gap: int) -> None:
    """BM-002 机械兜底：brand_moment 间距不足时，把后一个植入拍向后移到首个
    非植入空位（间距达标处）。只换序不改内容；步数有限（防两种排列间振荡死循环，
    无处可挪时保持现状交给检查器报真问题）；结束后 order 重排。
    """
    if min_gap <= 1:
        return
    for _ in range(len(beats) * 2):
        idx = [i for i, b in enumerate(beats) if b["beat_kind"] == "brand_moment"]
        bad = next(((a, b_) for a, b_ in zip(idx, idx[1:]) if b_ - a < min_gap), None)
        if bad is None:
            break
        a, b_ = bad
        target = next(
            (t for t in range(a + min_gap, len(beats)) if beats[t]["beat_kind"] != "brand_moment"),
            None,
        )
        if target is None:  # 集长不足/植入过密：修不了，保持原样
            break
        beats.insert(target, beats.pop(b_))
    for i, bt in enumerate(beats):
        bt["order"] = i


def _rescale_durations(beats: list[dict[str, Any]], ep: dict[str, Any]) -> None:
    """DLG-006 根因机械归一：NPC 系统性低估 est_duration_s（全集合计 ~70s vs 目标 90s，
    实证 attempt3 六集对白全灭），p5 按它换算对白地板必然欠量。把各拍时长等比缩放到
    集目标时长（duration_target_s），让下游体量地板算真账；全 0 时均分；无目标不动。"""
    try:
        target = float(ep.get("duration_target_s") or 0)
    except (TypeError, ValueError):
        return
    if target <= 0 or not beats:
        return
    total = sum(float(b.get("est_duration_s") or 0) for b in beats)
    if total <= 0:
        for b in beats:
            b["est_duration_s"] = round(target / len(beats), 2)
        return
    scale = target / total
    for b in beats:
        b["est_duration_s"] = round(float(b.get("est_duration_s") or 0) * scale, 2)


def _attach_facts(
    raw: Any, ep: dict[str, Any], known_facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fact[] 机械归一（ADR-0012，可缺省→空表）。

    resolves：int=同集 facts_json 下标（两遍解析，允许前向引用），str=已知前集 fact 的 id；
    伪造引用即 PassFailure（诊断可喂重试）。id 由 Pass 分配，模型永远写不出新 fact 的 id。
    """
    known_ids = {str(f.get("id")) for f in known_facts if isinstance(f, dict)}
    entries: list[dict[str, Any]] = []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict):
            continue
        content = str(f.get("content", "")).strip()
        if not content:
            continue
        try:
            episode_no = max(1, int(f.get("episode_no") or ep["no"]))
        except (TypeError, ValueError):
            episode_no = int(ep["no"])
        entries.append(
            {
                "id": new_id(),
                "content": content,
                "type": _coerce_enum(
                    f.get("type", "plot_event"), allowed_values(Fact, "type"), "plot_event"
                ),
                "status": _coerce_enum(
                    f.get("status", "active"), allowed_values(Fact, "status"), "active"
                ),
                "_resolves_raw": f.get("resolves"),
                "episode_no": episode_no,
                "narrative_weight": _coerce_enum(
                    f.get("narrative_weight", "medium"),
                    allowed_values(Fact, "narrative_weight"),
                    "medium",
                ),
            }
        )
    for i, e in enumerate(entries):
        e["resolves"] = _coerce_resolves(e.pop("_resolves_raw"), i, entries, known_ids, ep)
    return entries


def _coerce_resolves(
    ref: Any, self_idx: int, entries: list[dict[str, Any]], known_ids: set[str], ep: dict[str, Any]
) -> str | None:
    if ref is None:
        return None
    if isinstance(ref, bool):
        raise PassFailure(
            ep["id"], f"第 {ep['no']} 集的 Fact resolves={ref!r} 非法（应为下标/已知 id/null）。"
        )
    if isinstance(ref, int):
        if not 0 <= ref < len(entries):
            raise PassFailure(
                ep["id"],
                f"第 {ep['no']} 集的 Fact resolves 下标 {ref} 越界（本集共 {len(entries)} 条 Fact）。",
            )
        if ref == self_idx:
            raise PassFailure(
                ep["id"], f"第 {ep['no']} 集的 Fact resolves 指向自身，伏笔不得自我回收（INV-17）。"
            )
        return entries[ref]["id"]
    if isinstance(ref, str) and ref.strip():
        ref = ref.strip()
        if ref in known_ids:
            return ref
        raise PassFailure(
            ep["id"],
            f"第 {ep['no']} 集的 Fact resolves={ref!r} 不是已知 fact id。"
            f"跨集回收只能引用 known_facts 里的 id（如 {sorted(known_ids)[:3]}），"
            "尚未回收请填 null。",
        )
    raise PassFailure(
        ep["id"],
        f"第 {ep['no']} 集的 Fact resolves={ref!r} 非法（应为下标 int/已知 id 字符串/null）。",
    )


def _attach_state_changes(
    raw: Any, ep: dict[str, Any], declared: dict[str, Any]
) -> list[dict[str, Any]]:
    """StateChange[] 机械归一（ADR-0012，可缺省→空表）。

    只保留已声明 key 的条目；delta 按声明类型转换（暗线→int 步进，number→数值，
    string→字符串），转不动的丢弃——这是 INV-19 的机械前置，语义仍由 final 不变量把关。
    """
    if not isinstance(declared, dict):
        declared = {}
    var_type = {
        str(v.get("key")): str(v.get("type", "number"))
        for v in declared.get("state_variables", [])
        if isinstance(v, dict)
    }
    dark_keys = {str(d.get("key")) for d in declared.get("dark_threads", []) if isinstance(d, dict)}
    out: list[dict[str, Any]] = []
    for ch in raw if isinstance(raw, list) else []:
        if not isinstance(ch, dict):
            continue
        key = str(ch.get("key", "")).strip()
        reason = str(ch.get("reason", "")).strip()
        if not key or not reason or "delta" not in ch:
            continue
        delta = _coerce_delta(key, ch["delta"], var_type, dark_keys)
        if delta is None:
            continue
        out.append({"key": key, "delta": delta, "reason": reason})
    return out


def _coerce_delta(
    key: str, raw: Any, var_type: dict[str, str], dark_keys: set[str]
) -> float | int | str | None:
    if isinstance(raw, bool):
        return None
    if key in dark_keys:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if var_type.get(key) == "string":
        return str(raw)
    if key in var_type:
        try:
            d = float(raw)
        except (TypeError, ValueError):
            return None
        return int(d) if d.is_integer() else d
    return None  # 未声明的 key：丢弃（状态表以 p2 声明为真相）


def apply_fact_cascade(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全季后处理（INV-17 级联的机械执行，pipeline 在收集完各集 facts 后调用）：

    - 被任何非 deprecated Fact.resolves 指向的目标 → status=resolved；
    - 自称 resolved 却无人回收 → 降回 unresolved。

    跨集回收时，前集 Fact 无法被后集模型重写（id 已定、不再输出），
    状态翻转只能在这里统一完成——角色等价于 SetupPayoff 的 resolve_pending。
    幂等：重复执行结果不变。
    """
    resolved_ids = {
        f["resolves"] for f in facts if f.get("resolves") and f.get("status") != "deprecated"
    }
    for f in facts:
        if f["id"] in resolved_ids:
            f["status"] = "resolved"
        elif f["status"] == "resolved":
            f["status"] = "unresolved"
    return facts


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
    """全季后处理:解引用 PENDING:<slug>。规则:slug 相同的条目互为两端。

    降级语义(round12):无 donor 时删除该条目而不是 PassFailure——随机后端几乎从不
    补 donor,悬空 PENDING 由此成为最高频死法;解除跨集伏笔契约(叙事文本保留)
    优于全管线死亡。"""
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for sp in setup_payoffs:
        by_slug.setdefault(sp["_slug"], []).append(sp)
    kept: list[dict[str, Any]] = []
    for slug, group in by_slug.items():
        for sp in group:
            demoted = False
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
                        demoted = True  # 无 donor → 解除契约,不致命
                        break
                    sp[f"{side}_beat_id"] = donor[f"{side}_beat_id"]
            if not demoted:
                kept.append(sp)
    return [
        {
            "id": sp["id"],
            "setup_beat_id": sp["setup_beat_id"],
            "payoff_beat_id": sp["payoff_beat_id"],
            "kind": sp["kind"],
            "description": sp["description"],
        }
        for sp in kept
    ]
