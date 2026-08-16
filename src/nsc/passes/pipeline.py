"""编译编排（D5）：p0..p7 正向流水线 + 依赖闭包局部重编译。

编排 = 纯 Python 函数（AGENTS.md §2：禁止引入编排框架）。
每个阶段后立刻跑对应该阶段的 L0（不变量 + spec/checks），失败即 PassFailure，
feedback 文本可直接进 GEPA（D13）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from nsc.checker.interpreter import RuleSet, evaluate
from nsc.runtime.ir_io import build_view, merge_preserving_ids
from spec.ir.container import NarrativeIR, NovelChapter, Provenance
from spec.ir.invariants import check_all, inv_16_id_stability

from . import (
    PassContext,
    PassFailure,
    new_id,
    p0_intake,
    p1_bible,
    p2_arc,
    p3_beatsheet,
    p4_scene,
    p5_dialogue,
    p6_prose,
    p7_render,
)

_DEP_GRAPH: dict[str, Any] = yaml.safe_load(Path("spec/passes/dep_graph.yaml").read_text("utf-8"))

#: spec/checks 规则的合法 stage（DSL §2）。after_p1 只有不变量，没有规则。
_RULE_STAGES = ("after_p2", "after_p3", "after_p4", "after_p5", "after_p6", "final")


def invalidation_closure(changed_fields: list[str]) -> list[list[str]]:
    """字段变更 → 失效的 [(pass, 粒度)]。规则全部来自 dep_graph.yaml。"""
    out: list[list[str]] = []
    for field_name in changed_fields:
        for pattern, targets in _DEP_GRAPH.get("invalidation", {}).items():
            if _field_match(pattern, field_name):
                for t in targets:
                    pair = [t[0], t[1]]
                    if pair not in out:
                        out.append(pair)
    return out


def _field_match(pattern: str, field_name: str) -> bool:
    for alt in pattern.split("|"):
        rx = re.escape(alt).replace(r"\*", "[^.]+")
        if re.fullmatch(rx, field_name):
            return True
        if "." not in alt and field_name.endswith("." + alt):
            return True
    return False


def check_stage(
    ctx: PassContext, ir: NarrativeIR, inv_stage: str, rule_stage: str | None = None
) -> None:
    """阶段 L0：先不变量，后声明式规则。block/违规即 PassFailure。

    不变量与规则的 stage 解耦：INV-11（每 Beat 有台词）在 after_p4 的不变量集里，
    但台词 p5 才生成，所以 p4 之后的检查用 after_p3 的不变量 + after_p4 的规则。
    """
    violations = check_all(ir, ctx.profile, stage=inv_stage)
    if violations:
        v = violations[0]
        raise PassFailure(v.node_id, "；".join(x.message for x in violations[:3]))
    stage = rule_stage if rule_stage in _RULE_STAGES else None
    if stage is None:
        return
    view = build_view(ir.model_dump(), ctx.profile, ctx.brand)
    rs = RuleSet.load(
        profile_id=str(ctx.profile.get("id", "")),
        industry=str(ctx.brand.get("industry", "")),
        brand_id=str(ctx.brand.get("brand_id", "")),
        stage=stage,
        enabled_domains=list(ctx.profile.get("enabled_check_domains", [])),
    )
    rep = evaluate(rs, view, ctx={"profile": ctx.profile, "brand": ctx.brand})
    if rep.errors:
        raise PassFailure(None, "规则本身报错：" + "；".join(rep.errors[:3]))
    if rep.blocked:
        raise PassFailure(None, rep.as_feedback_text())


def run_pipeline(ctx: PassContext) -> NarrativeIR:
    """正向全量编译：brief → IR → 交付物。返回最终 IR（产物已落盘 out/）。"""
    run_ids: list[str] = []
    st: dict[str, Any] = {
        "seasons": [],
        "episodes": [],
        "scenes": [],
        "beats": [],
        "lines": [],
        "chapters": [],
        "brand_moments": [],
        "setup_payoffs": [],
        "voice": None,
    }

    def cur() -> NarrativeIR:
        return _assemble(ctx, st, _provenance(ctx, run_ids))

    def track() -> None:
        run_ids.append(ctx.run_id)

    r0 = p0_intake.run(ctx, {"raw_brief": ctx.brief, "raw_brand": ctx.brand})
    track()
    brief = ctx.brief
    st["project"] = {
        "id": new_id(),
        "kind": "project",
        "parent_id": None,
        "order": 0,
        "title": brief.get("project_title") or "未命名项目",
        "logline": (r0["normalized_brief"].split("\n")[0] or "（缺 logline）")[:80],
        "profile_id": brief.get("profile", ""),
        "brand_id": brief.get("brand", ""),
        "client_note": "\n".join(brief.get("notes", [])),
        "provenance_id": ctx.run_id,
        "locked": False,
    }
    st["constraints"] = r0["constraints"]

    r1 = p1_bible.run(ctx, {"normalized_brief": r0["normalized_brief"]})
    track()
    bible = {k: r1[k] for k in ("characters", "locations", "props", "motifs", "tone")}
    st.update(bible)

    r2 = p2_arc.run(ctx, {"bible": bible, "project_id": st["project"]["id"]})
    track()
    st["seasons"] = [r2["season"]]
    st["episodes"] = r2["episodes"]
    check_stage(ctx, cur(), "after_p1")
    check_stage(ctx, cur(), "after_p2", "after_p2")

    episodes = r2["episodes"]
    prev_summary = ""
    for i, ep in enumerate(episodes):
        r3 = p3_beatsheet.run(
            ctx,
            {
                "episode": ep,
                "bible": bible,
                "placement": [
                    p for p in r2["placement_plan"] if int(p.get("episode_no", -1)) == ep["no"]
                ],
                "prev_episode_summary": prev_summary,
                "next_episode_promise": episodes[i + 1]["hook_promise"]
                if i + 1 < len(episodes)
                else "",
            },
        )
        track()
        prev_summary = "；".join(b["summary"] for b in r3["beats"])
        st["beats"] += r3["beats"]
        st["setup_payoffs"] += r3["setup_payoffs"]
        st["brand_moments"] += r3["brand_moments"]

    for ep in episodes:
        ep_beats = [b for b in st["beats"] if b["_episode_id"] == ep["id"]]
        r4 = p4_scene.run(ctx, {"episode": ep, "beats": ep_beats, "bible": bible})
        track()
        st["scenes"] += r4["scenes"]
        st["beats"] = [b for b in st["beats"] if b["_episode_id"] != ep["id"]] + r4["beats"]
    st["setup_payoffs"] = p3_beatsheet.resolve_pending(st["setup_payoffs"])
    check_stage(ctx, cur(), "after_p3", "after_p4")

    for sc in st["scenes"]:
        sc_beats = [b for b in st["beats"] if b["parent_id"] == sc["id"]]
        r5 = p5_dialogue.run(ctx, _p5_fragment(sc, sc_beats, bible, st["constraints"]))
        track()
        st["lines"] += r5["lines"]
    check_stage(ctx, cur(), "after_p5", "after_p5")

    if ctx.profile.get("novel", {}).get("enabled"):
        st["voice"] = _voice(ctx, bible)
        for ep in episodes:
            r6 = p6_prose.run(ctx, _p6_fragment(cur(), bible, st["voice"], ep["id"]))
            track()
            st["chapters"].append(r6["chapter"])
        check_stage(ctx, cur(), "after_p6", "after_p6")

    ir = cur()
    p7_render.run(ctx, ir.model_dump())
    track()
    ir = cur()
    check_stage(ctx, ir, "final", "final")
    return ir


def recompile_episode(ctx: PassContext, ir: NarrativeIR, ep_no: int) -> NarrativeIR:
    """局部重编译单集：只触发该集的 p3–p7（dep_graph 粒度 episode）。

    契约：未变节点 ID 必须保留（INV-16），locked 节点逐字保留（dep_graph.locked_policy）。
    """
    old = ir
    raw = old.model_dump()
    ep = next((e for e in raw["episodes"] if e["no"] == ep_no), None)
    if ep is None:
        raise PassFailure(None, f"第 {ep_no} 集不存在")
    bible = {k: raw[k] for k in ("characters", "locations", "props", "motifs", "tone")}
    ordered = sorted(raw["episodes"], key=lambda e: e["order"])
    idx = next(i for i, e in enumerate(ordered) if e["no"] == ep_no)

    run_ids: list[str] = []

    def track() -> None:
        run_ids.append(ctx.run_id)

    r3 = p3_beatsheet.run(
        ctx,
        {
            "episode": ep,
            "bible": bible,
            "placement": _placement_of(raw, ep),
            "prev_episode_summary": _episode_digest(raw, ordered[idx - 1]["id"]) if idx > 0 else "",
            "next_episode_promise": ordered[idx + 1]["hook_promise"]
            if idx + 1 < len(ordered)
            else "",
        },
    )
    track()
    r4 = p4_scene.run(ctx, {"episode": ep, "beats": r3["beats"], "bible": bible})
    track()
    lines: list[dict[str, Any]] = []
    for sc in r4["scenes"]:
        sc_beats = [b for b in r4["beats"] if b["parent_id"] == sc["id"]]
        r5 = p5_dialogue.run(ctx, _p5_fragment(sc, sc_beats, bible, raw.get("constraints", [])))
        track()
        lines += r5["lines"]

    new_raw = _splice_episode(
        raw, ep["id"], r4["scenes"], r4["beats"], lines, r3["brand_moments"], r3["setup_payoffs"]
    )
    new_ir = NarrativeIR.model_validate(_strip_private(new_raw))

    if raw.get("voice"):
        beats_with_lines = _attach_lines(r4["beats"], lines)
        r6 = p6_prose.run(
            ctx,
            {
                "episode": ep,
                "beats": beats_with_lines,
                "scenes_with_lines": _scenes_with_lines(r4["scenes"], beats_with_lines, raw),
                "bible": bible,
                "voice": raw["voice"],
            },
        )
        track()
        keep = [c for c in new_ir.chapters if c.episode_id != ep["id"]]
        new_ir = new_ir.model_copy(
            update={"chapters": [*keep, NovelChapter.model_validate(r6["chapter"])]}
        )

    merged = merge_preserving_ids(old, new_ir)
    _restore_locked(old, merged)
    _remap_overlays(new_ir, merged)
    merged.provenance.extend(_provenance(ctx, run_ids))
    bad = inv_16_id_stability(old, merged)
    if bad:
        raise PassFailure(bad[0].node_id, "；".join(x.message for x in bad[:3]))
    check_stage(ctx, merged, "final", "final")
    p7_render.run(ctx, merged.model_dump())
    return merged


# ---------------------------------------------------------------- 内部 helpers


def _assemble(ctx: PassContext, st: dict[str, Any], provenance: list[Provenance]) -> NarrativeIR:
    raw = {
        "project": st["project"],
        "seasons": st["seasons"],
        "episodes": st["episodes"],
        "scenes": st["scenes"],
        "beats": st["beats"],
        "lines": st["lines"],
        "characters": st.get("characters", []),
        "locations": st.get("locations", []),
        "props": st.get("props", []),
        "brand_moments": st["brand_moments"],
        "setup_payoffs": st["setup_payoffs"],
        "motifs": st.get("motifs", []),
        "constraints": st.get("constraints", []),
        "tone": st.get("tone") or None,
        "voice": st.get("voice"),
        "chapters": st["chapters"],
        "provenance": [p.model_dump() for p in provenance],
    }
    return NarrativeIR.model_validate(_strip_private(raw))


def _strip_private(raw: Any) -> Any:
    if isinstance(raw, dict):
        return {k: _strip_private(v) for k, v in raw.items() if not k.startswith("_")}
    if isinstance(raw, list):
        return [_strip_private(x) for x in raw]
    return raw


def _provenance(ctx: PassContext, run_ids: list[str]) -> list[Provenance]:
    rows = {r["run_id"]: r for r in ctx.store.runs()}
    cols = set(Provenance.model_fields)
    return [
        Provenance.model_validate({k: v for k, v in rows[r].items() if k in cols})
        for r in dict.fromkeys(run_ids)
        if r in rows
    ]


def _voice(ctx: PassContext, bible: dict[str, Any]) -> dict[str, Any]:
    v = {
        "person": "third_limited",
        "tense": "past",
        "style": "web_novel",
        "paragraph_max_chars": 180,
        "interiority": "medium",
        **ctx.profile.get("novel", {}).get("default_voice", {}),
    }
    pro = next((c for c in bible.get("characters", []) if c.get("role") == "protagonist"), None)
    v["pov_character_id"] = pro["id"] if pro else None
    return v


def _episode_digest(raw: dict[str, Any], ep_id: str) -> str:
    scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep_id}
    return "；".join(b["summary"] for b in raw["beats"] if b["parent_id"] in scene_ids)


def _placement_of(raw: dict[str, Any], ep: dict[str, Any]) -> list[dict[str, Any]]:
    """从已有 IR 反推该集的植入预算（重编译时 p2 不重跑，budget 真相在 IR 里）。"""
    scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep["id"]}
    beat_ids = {b["id"] for b in raw["beats"] if b["parent_id"] in scene_ids}
    return [
        {
            "episode_no": ep["no"],
            "selling_point_id": bm["selling_point_id"],
            "type": bm["type"],
            "intensity": bm["intensity"],
            "modality": bm["modality"],
            "plot_connection": bm["plot_connection"],
            "proof_mode": bm["proof_mode"],
            "intent": bm["integration_note"],
            "prop_id": bm.get("prop_id"),
        }
        for bm in raw.get("brand_moments", [])
        if bm["anchor_beat_id"] in beat_ids
    ]


def _p5_fragment(
    scene: dict[str, Any],
    beats: list[dict[str, Any]],
    bible: dict[str, Any],
    constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    present = set(scene.get("present_character_ids", []))
    return {
        "scene": scene,
        "beats": beats,
        "characters": [c for c in bible.get("characters", []) if c.get("id") in present],
        "brand_constraints": constraints,
    }


def _attach_lines(beats: list[dict[str, Any]], lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**b, "_lines": [ln for ln in lines if ln["parent_id"] == b["id"]]} for b in beats]


def _scenes_with_lines(
    scenes: list[dict[str, Any]], beats: list[dict[str, Any]], raw: dict[str, Any]
) -> list[dict[str, Any]]:
    locs = {loc["id"]: loc["name"] for loc in raw.get("locations", [])}
    chars = {c["id"]: c["name"] for c in raw.get("characters", [])}
    out = []
    for sc in scenes:
        sc_beats = [b for b in beats if b["parent_id"] == sc["id"]]
        out.append(
            {
                **sc,
                "location_name": locs.get(sc["location_id"], ""),
                "character_names": [chars.get(c, "") for c in sc["present_character_ids"]],
                "beats": [
                    {**b, "lines": b.get("_lines", [])}
                    for b in sorted(sc_beats, key=lambda x: x["order"])
                ],
            }
        )
    return out


def _p6_fragment(
    ir: NarrativeIR, bible: dict[str, Any], voice: dict[str, Any], ep_id: str
) -> dict[str, Any]:
    raw = ir.model_dump()
    ep = next(e for e in raw["episodes"] if e["id"] == ep_id)
    scenes = [s for s in raw["scenes"] if s["parent_id"] == ep_id]
    scene_ids = {s["id"] for s in scenes}
    beats = _attach_lines([b for b in raw["beats"] if b["parent_id"] in scene_ids], raw["lines"])
    return {
        "episode": ep,
        "beats": beats,
        "scenes_with_lines": _scenes_with_lines(scenes, beats, raw),
        "bible": bible,
        "voice": voice,
    }


def _splice_episode(
    raw: dict[str, Any],
    ep_id: str,
    new_scenes: list[dict[str, Any]],
    new_beats: list[dict[str, Any]],
    new_lines: list[dict[str, Any]],
    new_bms: list[dict[str, Any]],
    new_sps: list[dict[str, Any]],
) -> dict[str, Any]:
    old_scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep_id}
    old_beat_ids = {b["id"] for b in raw["beats"] if b["parent_id"] in old_scene_ids}
    out = dict(raw)
    out["scenes"] = [s for s in raw["scenes"] if s["id"] not in old_scene_ids] + new_scenes
    out["beats"] = [b for b in raw["beats"] if b["id"] not in old_beat_ids] + new_beats
    out["lines"] = [ln for ln in raw["lines"] if ln["parent_id"] not in old_beat_ids] + new_lines
    out["brand_moments"] = [
        bm for bm in raw.get("brand_moments", []) if bm["anchor_beat_id"] not in old_beat_ids
    ] + new_bms
    kept_sps = [
        sp
        for sp in raw.get("setup_payoffs", [])
        if sp["setup_beat_id"] not in old_beat_ids and sp["payoff_beat_id"] not in old_beat_ids
    ]
    out["setup_payoffs"] = kept_sps + p3_beatsheet.resolve_pending(new_sps)
    out["chapters"] = [c for c in raw.get("chapters", []) if c["episode_id"] != ep_id]
    return out


def _restore_locked(old: NarrativeIR, merged: NarrativeIR) -> None:
    """locked 节点的 payload 逐字保留（dep_graph.locked_policy）。"""
    for table in ("episodes", "scenes", "beats", "lines"):
        locked = {n.id: n for n in getattr(old, table) if n.locked}
        if not locked:
            continue
        nodes = getattr(merged, table)
        for i, n in enumerate(nodes):
            if n.id in locked:
                nodes[i] = locked[n.id]


def _remap_overlays(new: NarrativeIR, merged: NarrativeIR) -> None:
    """merge_preserving_ids 改完主干 ID 后，parent 链接与覆盖层引用必须同步重映射。"""
    id_map: dict[str, str] = {}
    for table in ("episodes", "scenes", "beats", "lines"):
        for n_new, n_merged in zip(getattr(new, table), getattr(merged, table), strict=True):
            if n_new.id != n_merged.id:
                id_map[n_new.id] = n_merged.id
    if not id_map:
        return
    for table in ("seasons", "episodes", "scenes", "beats", "lines"):
        for n in getattr(merged, table):
            if n.parent_id in id_map:
                n.parent_id = id_map[n.parent_id]
    for bm in merged.brand_moments:
        if bm.anchor_beat_id in id_map:
            bm.anchor_beat_id = id_map[bm.anchor_beat_id]
    for sp in merged.setup_payoffs:
        if sp.setup_beat_id in id_map:
            sp.setup_beat_id = id_map[sp.setup_beat_id]
        if sp.payoff_beat_id in id_map:
            sp.payoff_beat_id = id_map[sp.payoff_beat_id]
    for ch in merged.chapters:
        if ch.episode_id in id_map:
            ch.episode_id = id_map[ch.episode_id]
        for am in ch.anchor_map:
            if am.get("beat_id") in id_map:
                am["beat_id"] = id_map[am["beat_id"]]
            am["line_ids"] = [id_map.get(x, x) for x in am.get("line_ids", [])]
