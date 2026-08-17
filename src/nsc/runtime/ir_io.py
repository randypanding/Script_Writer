"""IR 的 IO 与计算视图（T-03）。

本模块是 checker 的下游地基：`build_view` 把扁平的 IR 表（container.py）编译成
嵌套文档，供 JMESPath 规则查询。`__` 前缀字段是**计算量**，不落盘（D24）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from spec.ir.container import NarrativeIR

# ------------------------------------------------------------------ 合规上下文

_NUM_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|万|毫升|ml|ML|克|g|G|毫克|mg|元|杯|卡|千卡|kcal|mm|cm)?"
)

#: cost_tier → 场地成本权重（PRD-001 用）
_COST_WEIGHT = {"free": 0, "cheap": 1, "normal": 2, "expensive": 3, "premium": 4}


def _cost_weight(tier: str | None) -> float:
    return float(_COST_WEIGHT.get(tier or "", 1))


def _load_domain_extras() -> dict[str, dict[str, Any]]:
    """按域加载 spec/checks/<domain>/_*.yaml 词表资产（ADR-0011，机制非业务）。

    同域多个 `_` 文件的同名 list 键做拼接，其余键后者覆盖。
    """
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(Path("spec/checks").glob("*/_*.yaml")):
        import yaml

        try:
            data = yaml.safe_load(p.read_text("utf-8"))
        except Exception:
            data = None
        if not isinstance(data, dict):
            continue
        slot = out.setdefault(p.parent.name, {})
        for k, v in data.items():
            if isinstance(v, list) and isinstance(slot.get(k), list):
                slot[k] = slot[k] + v
            else:
                slot[k] = v
    return out


def _load_compliance() -> dict[str, Any]:
    src = Path("spec/checks/compliance/_absolute_terms.yaml")
    if src.exists():
        import yaml

        data = yaml.safe_load(src.read_text("utf-8"))
        terms = [t for t in (data or {}).get("terms", []) if isinstance(t, str)]
    else:
        terms = []
    # CMP-002 的受管制功效/疗效表述模式（正则）。无证据时给空表，规则自动通过。
    regulated = [
        r"治疗|治愈|根治|抗癌|降血糖|降血压|减肥|瘦身|排毒|提高免疫|防癌",
    ]
    base = {"absolute_terms": terms, "regulated_claim_patterns": regulated}
    # `_platform_terms.yaml` 等合规域附加词表并入 compliance（ADR-0011 泛化加载）。
    extra = _load_domain_extras().get("compliance", {})
    return {**extra, **base}


def _brand_view(brand: dict[str, Any]) -> dict[str, Any]:
    """把 brand.yaml 编译成 checker 可用的 ctx.brand（含 `__` 派生字段）。"""
    products = brand.get("products", [])
    selling_points = brand.get("selling_points", [])
    legal = brand.get("legal", {})
    banned = list(brand.get("banned_words", [])) + list(legal.get("banned_words", []))
    for sp in selling_points:
        banned += sp.get("forbidden_phrasings", [])
    facts_vals = [v for p in products for v in p.get("facts", {}).values() if isinstance(v, str)]
    canonical = [p.get("canonical_name") or p.get("name") for p in products if p.get("name")]
    # 错误写法 = 别名中非 canonical 的写法。别名含规范名子串也没关系：
    # BM-009 用 contains_name_variant（被规范名覆盖的出现不算违规，见 ADR-0009）。
    # 去空格变体只有在与规范名不同时才算变体（无空格规范名不得禁自己）。
    forbidden = {a for p in products for a in p.get("aliases", []) if a not in canonical}
    forbidden |= {c.replace(" ", "") for c in canonical if c.replace(" ", "") != c}
    return {
        **brand,
        "placement": brand.get("placement", {}),
        "selling_points": selling_points,
        "legal": legal,
        "__canonical_names": canonical,
        "__forbidden_name_variants": sorted(forbidden),
        "__all_banned_words": list(dict.fromkeys(banned)),
        "__all_fact_values": facts_vals,
    }


def build_view(
    ir: dict[str, Any],
    profile: dict[str, Any],
    brand: dict[str, Any],
    compliance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把扁平 IR 编译成 checker/renderer 用的嵌套视图。

    `item` 语义：`select` 的每个结果。`__` 前缀字段是计算量，供规则使用。
    """
    bv = _brand_view(brand)
    extras = _load_domain_extras()
    compliance = compliance or _load_compliance()
    prose_ctx = extras.get("prose", {})

    # linear_index：按 episode->scene->beat->line 深度优先连续编号
    linear: dict[str, int] = {}
    counter = 0
    for ep in ir.get("episodes", []):
        for sc in (s for s in ir.get("scenes", []) if s.get("parent_id") == ep.get("id")):
            for bt in (b for b in ir.get("beats", []) if b.get("parent_id") == sc.get("id")):
                linear[bt["id"]] = counter
                counter += 1
                for ln in (x for x in ir.get("lines", []) if x.get("parent_id") == bt.get("id")):
                    linear[ln["id"]] = counter
                    counter += 1

    bm_by_beat: dict[str, dict[str, Any]] = {
        m["anchor_beat_id"]: m for m in ir.get("brand_moments", [])
    }
    scene_by_id: dict[str, dict[str, Any]] = {s["id"]: s for s in ir.get("scenes", [])}
    beat_by_id: dict[str, dict[str, Any]] = {b["id"]: b for b in ir.get("beats", [])}
    loc_by_id: dict[str, dict[str, Any]] = {x["id"]: x for x in ir.get("locations", [])}

    def rec_ep(ep: dict[str, Any]) -> dict[str, Any]:
        scenes = [s for s in ir.get("scenes", []) if s.get("parent_id") == ep.get("id")]
        eps = {
            "id": ep.get("id"),
            "no": ep.get("no"),
            "title": ep.get("title"),
            "logline": ep.get("logline"),
            "order": ep.get("order"),
            "duration_target_s": ep.get("duration_target_s"),
            "hook_promise": ep.get("hook_promise"),
            "cliffhanger": ep.get("cliffhanger", ""),
            # --- ADR-0012 运行时叙事状态透传 ---
            "responds_to": ep.get("responds_to", []),
            "state_changes": ep.get("state_changes", []),
            "scenes": [rec_scene(s, ep) for s in scenes],
        }
        # 扁平 beats（无嵌套 lines），供 STR/DLG-006 等用
        ep_beats = []
        for s in scenes:
            for b in ir.get("beats", []):
                if b.get("parent_id") == s.get("id"):
                    ep_beats.append(rec_beat(b, scene_id=s["id"]))
        eps["beats"] = ep_beats
        # 集级派生
        present = {c for s in scenes for c in s.get("present_character_ids", [])}
        lines = []
        for b in ep_beats:
            for ln in b.get("lines", []):
                lines.append(ln)
        texts = [ln["text"] for ln in lines if ln.get("line_type") == "dialogue"]
        eps["__present_character_ids"] = sorted(present)
        eps["__duplicate_line_count"] = len(texts) - len(set(texts))
        eps["__line_count"] = len(lines)
        eps["__dialogue_chars"] = sum(_chars(t) for t in texts)
        # 场地成本（PRD-001）：本集出现过的场地按 cost_tier 折成权重
        eps["__locations"] = [
            {
                "location_id": s.get("location_id"),
                "cost_tier": loc_by_id.get(s.get("location_id", ""), {}).get("cost_tier", "cheap"),
            }
            for s in scenes
        ]
        for loc in eps["__locations"]:
            loc["cost_weight"] = _cost_weight(loc["cost_tier"])
        return eps

    def rec_scene(sc: dict[str, Any], ep: dict[str, Any]) -> dict[str, Any]:
        loc = loc_by_id.get(sc.get("location_id", ""), {})
        beats = []
        for b in ir.get("beats", []):
            if b.get("parent_id") == sc.get("id"):
                beats.append(rec_beat(b, scene_id=sc["id"]))
        return {
            "id": sc.get("id"),
            "goal": sc.get("goal"),
            "conflict": sc.get("conflict"),
            "turn": sc.get("turn"),
            "entry": sc.get("entry"),
            "exit": sc.get("exit"),
            "location_id": sc.get("location_id"),
            "time_of_day": sc.get("time_of_day"),
            "interior": sc.get("interior"),
            "present_character_ids": sc.get("present_character_ids", []),
            "summary": sc.get("summary", ""),
            # --- ADR-0012 场级节奏与知识状态透传 ---
            "opening_attractor": sc.get("opening_attractor", ""),
            "escalation_beats": sc.get("escalation_beats", []),
            "ending_hook": sc.get("ending_hook", ""),
            "knowledge_state": sc.get("knowledge_state"),
            "__location_cost_tier": loc.get("cost_tier", "cheap"),
            "beats": beats,
        }

    def rec_beat(b: dict[str, Any], *, scene_id: str) -> dict[str, Any]:
        bm = bm_by_beat.get(b.get("id") or "")
        lines = []
        for ln in ir.get("lines", []):
            if ln.get("parent_id") == b.get("id"):
                lines.append(
                    {
                        "id": ln.get("id"),
                        "line_type": ln.get("line_type"),
                        "text": ln.get("text"),
                        "character_id": ln.get("character_id"),
                        "delivery": ln.get("delivery", ""),
                        "is_brand_line": ln.get("is_brand_line", False),
                        "__scene_present_character_ids": scene_by_id.get(scene_id, {}).get(
                            "present_character_ids", []
                        ),
                    }
                )
        return {
            "id": b.get("id"),
            "beat_kind": b.get("beat_kind"),
            "summary": b.get("summary"),
            "order": b.get("order"),
            "function": b.get("function", ""),
            "emotion": b.get("emotion") or {"valence": 0.0, "arousal": 0.0},
            "est_duration_s": b.get("est_duration_s"),
            "brand_moment_id": b.get("brand_moment_id"),
            "linear_index": linear.get(b.get("id") or "", -1),
            "__intensity": (bm or {}).get("intensity"),
            "__modality": (bm or {}).get("modality"),
            "lines": lines,
        }

    # 覆盖层
    characters = []
    for c in ir.get("characters", []):
        appearance = 0
        for s in ir.get("scenes", []):
            if c["id"] in s.get("present_character_ids", []):
                appearance += 1
        tics = c.get("voice_tics", [])
        line_count = sum(
            1
            for ln in ir.get("lines", [])
            if ln.get("character_id") == c["id"]
            and ln.get("line_type") in {"dialogue", "voiceover"}
        )
        tic_hit = sum(
            1
            for ln in ir.get("lines", [])
            if ln.get("character_id") == c["id"] and any(t in ln.get("text", "") for t in tics)
        )
        characters.append(
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "role": c.get("role"),
                "persona_ref": c.get("persona_ref", ""),
                "voice_tics": tics,
                "want": c.get("want", ""),
                "need": c.get("need", ""),
                "flaw": c.get("flaw", ""),
                "arc": c.get("arc", ""),
                # --- ADR-0012 角色心智 OS 透传 ---
                "mental_models": c.get("mental_models", []),
                "decision_heuristics": c.get("decision_heuristics", []),
                "honest_boundaries": c.get("honest_boundaries", []),
                "expression_dna": c.get("expression_dna"),
                "__appearance_count": appearance,
                "__tic_hit_count": tic_hit,
                "__line_count": line_count,
                "__tic_hit_ratio": (tic_hit / line_count) if line_count else 0.0,
            }
        )

    brand_moments = []
    for m in ir.get("brand_moments", []):
        ab = beat_by_id.get(m.get("anchor_beat_id", ""), {})
        brand_moments.append(
            {
                "id": m.get("id"),
                "type": m.get("type"),
                "intensity": m.get("intensity"),
                "modality": m.get("modality"),
                "plot_connection": m.get("plot_connection"),
                "selling_point_id": m.get("selling_point_id"),
                "proof_mode": m.get("proof_mode"),
                "integration_note": m.get("integration_note", ""),
                "prop_id": m.get("prop_id"),
                "__anchor_beat_kind": ab.get("beat_kind"),
            }
        )

    setup_payoffs = []
    for sp in ir.get("setup_payoffs", []):
        setup_bt = beat_by_id.get(sp.get("setup_beat_id", ""), {})
        payoff_bt = beat_by_id.get(sp.get("payoff_beat_id", ""), {})
        setup_ep = _episode_of(ir, setup_bt.get("parent_id", ""))
        payoff_ep = _episode_of(ir, payoff_bt.get("parent_id", ""))
        setup_payoffs.append(
            {
                "id": sp.get("id"),
                "kind": sp.get("kind"),
                "description": sp.get("description"),
                "setup_beat_id": sp.get("setup_beat_id"),
                "payoff_beat_id": sp.get("payoff_beat_id"),
                "episode_no": (payoff_ep or {}).get("no", 0),
                "span_episodes": abs(
                    (payoff_ep or {}).get("order", 0) - (setup_ep or {}).get("order", 0)
                ),
            }
        )

    # --- ADR-0012 运行时叙事状态层视图（声明式存储 + 确定性派生量） ---
    max_ep_no = max((e.get("no", 0) for e in ir.get("episodes", [])), default=0)
    facts = [
        {
            "id": f.get("id"),
            "content": f.get("content"),
            "character_ids": f.get("character_ids", []),
            "episode_no": f.get("episode_no", 1),
            "status": f.get("status", "active"),
            "type": f.get("type", "plot_event"),
            "resolves": f.get("resolves"),
            "caused_by": f.get("caused_by", []),
            "known_to": f.get("known_to"),
            "hidden_from": f.get("hidden_from", []),
            "suspense_type": f.get("suspense_type"),
            "narrative_weight": f.get("narrative_weight", "medium"),
            "thread_ids": f.get("thread_ids", []),
            # 派生：高权重伏笔逾期检测（FCT-003 用；>3 集未回收且仍悬置）
            "is_overdue": max_ep_no - f.get("episode_no", 1) > 3
            and f.get("status") == "unresolved",
        }
        for f in ir.get("facts", [])
    ]
    threads = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "state": t.get("state", ""),
            "status": t.get("status", "active"),
        }
        for t in ir.get("threads", [])
    ]
    derived = derive_state(ir)
    state_variables = [
        {
            "key": v.get("key"),
            "name": v.get("name"),
            "type": v.get("type", "number"),
            "initial": v.get("initial", 0),
            "description": v.get("description", ""),
            # 派生：按集号序重放 state_changes 得当前值
            "current": derived.get(v.get("key", ""), v.get("initial", 0)),
        }
        for v in ir.get("state_variables", [])
    ]
    dark_threads = [
        {
            "key": d.get("key"),
            "name": d.get("name"),
            "stages": d.get("stages", []),
            "description": d.get("description", ""),
            # 派生：按集号序累加 int delta 得当前阶段
            "current_stage": derive_stage(ir, d.get("key", "")),
        }
        for d in ir.get("dark_threads", [])
    ]

    # 全文本集合
    all_line_text = [ln.get("text", "") for ln in ir.get("lines", [])]
    all_action_scene = [
        ln.get("text", "")
        for ln in ir.get("lines", [])
        if ln.get("line_type") in {"action", "caption", "sfx"}
    ]
    all_action_scene += [s.get("summary", "") for s in ir.get("scenes", [])]
    all_action_scene += [s.get("entry", "") for s in ir.get("scenes", [])]
    all_action_scene += [s.get("exit", "") for s in ir.get("scenes", [])]
    all_action_scene += [b.get("summary", "") for b in ir.get("beats", [])]
    all_action_scene = [t for t in all_action_scene if t]
    all_text = (
        all_line_text + all_action_scene + [c.get("title", "") for c in ir.get("chapters", [])]
    )
    numeric_claims = [{"value": m.group(0)} for t in all_text for m in _NUM_RE.finditer(t)]

    lines_by_beat: dict[str, list[dict[str, Any]]] = {}
    for ln in ir.get("lines", []):
        if ln.get("line_type") == "dialogue" and ln.get("text"):
            lines_by_beat.setdefault(ln.get("parent_id", ""), []).append(ln)

    chapters = []
    beats_by_ep: dict[str, list[dict[str, Any]]] = {}
    for b in ir.get("beats", []):
        beats_by_ep.setdefault(_episode_id_of(ir, b.get("parent_id", "")), []).append(b)
    for ch in ir.get("chapters", []):
        ep_id = ch.get("episode_id")
        ep_beats = beats_by_ep.get(ep_id, [])
        total = len(ep_beats)
        # 一个 Beat 的任一口播台词出现在章节段落里，即视为被覆盖（NOV-001）。
        paragraphs = ch.get("paragraphs", [])
        para_blob = "\n".join(paragraphs)
        covered_beats = [
            b
            for b in ep_beats
            if any(
                (ln.get("text") or "") in para_blob for ln in lines_by_beat.get(b.get("id", ""), [])
            )
        ]
        covered = len(covered_beats)
        missing_ids = [b.get("id") for b in ep_beats if b not in covered_beats]
        pairs = []
        for para in paragraphs:
            for ln in ir.get("lines", []):
                if ln.get("text") and ln.get("text") in para and ln.get("line_type") == "dialogue":
                    pairs.append(
                        {
                            "chapter_id": ch.get("id"),
                            "line_id": ln.get("id"),
                            "novel_text": para,
                            "line_text": ln.get("text"),
                        }
                    )
                    break
        chapters.append(
            {
                "id": ch.get("id"),
                "episode_id": ch.get("episode_id"),
                "order": ch.get("order"),
                "title": ch.get("title", ""),
                "paragraphs": paragraphs,
                "__beat_coverage": (covered / total) if total else 1.0,
                "__covered_beats": covered,
                "__total_beats": total,
                "__missing_beat_ids": missing_ids,
                "__dialogue_pairs": pairs,
            }
        )

    return {
        "project": ir.get("project"),
        "seasons": ir.get("seasons", []),
        "episodes": [rec_ep(e) for e in ir.get("episodes", [])],
        "characters": characters,
        "locations": ir.get("locations", []),
        "props": ir.get("props", []),
        "brand_moments": brand_moments,
        "setup_payoffs": setup_payoffs,
        "motifs": ir.get("motifs", []),
        # ADR-0012 运行时叙事状态层（含派生 is_overdue/current/current_stage）
        "facts": facts,
        "threads": threads,
        "state_variables": state_variables,
        "dark_threads": dark_threads,
        "chapters": chapters,
        # 全局上下文
        "profile": profile,
        "brand": bv,
        "compliance": compliance,
        "prose": prose_ctx,
        "voice": ir.get("voice"),
        # `__` 全剧计算量
        "__all_line_text": [t for t in all_line_text if t],
        "__all_action_and_scene_text": all_action_scene,
        "__all_text": all_text,
        "__numeric_claims": numeric_claims,
        "__retrieved_case_snippets": ir.get("__retrieved_case_snippets", []),
    }


def emotion_curve(ir: NarrativeIR, episode_id: str) -> list[tuple[int, float, float]]:
    """[(linear_index, valence, arousal)]，按 episode 内线性序。"""
    raw = ir.model_dump()
    ep = next((e for e in raw["episodes"] if e["id"] == episode_id), None)
    if ep is None:
        return []
    linear: dict[str, int] = {}
    counter = 0
    for sc in (s for s in raw["scenes"] if s["parent_id"] == episode_id):
        for bt in (b for b in raw["beats"] if b["parent_id"] == sc["id"]):
            linear[bt["id"]] = counter
            counter += 1
    out = []
    for sc in (s for s in raw["scenes"] if s["parent_id"] == episode_id):
        for bt in (b for b in raw["beats"] if b["parent_id"] == sc["id"]):
            idx = linear[bt["id"]]
            out.append((idx, bt["emotion"]["valence"], bt["emotion"]["arousal"]))
    return sorted(out, key=lambda x: x[0])


def merge_preserving_ids(old: NarrativeIR, new: NarrativeIR) -> NarrativeIR:
    """局部重编译：保留未变节点的 ID（INV-16 的最高优先级契约）。

    判定"未变"：render 关键字段（text/summary/title/logline）相同。
    对 new 中每个节点，若在 old 中能找到内容相同的节点，则复用 old 的 ID。
    """

    def sig(n: Any) -> str:
        for att in ("text", "summary", "title", "logline"):
            v = getattr(n, att, None)
            if v:
                return f"{att}:{v}"
        return f"{n.kind}:{getattr(n, 'id', '')}"

    old_sig_by_kind: dict[str, dict[str, str]] = {}  # kind -> sig -> id
    for n in _flat(old):
        old_sig_by_kind.setdefault(n.kind, {})[sig(n)] = n.id

    new = new.model_copy(deep=True)
    for n in _flat(new):
        s = sig(n)
        matched = old_sig_by_kind.get(n.kind, {}).get(s)
        if matched is not None:
            n.id = matched
    return new


def _flat(ir: NarrativeIR) -> list[Any]:
    nodes: list[Any] = [ir.project]
    nodes += ir.seasons + ir.episodes + ir.scenes + ir.beats + ir.lines
    return nodes


def save(ir: NarrativeIR, path: str | Path) -> None:
    Path(path).write_text(json.dumps(ir.model_dump(), ensure_ascii=False, indent=2), "utf-8")


def load(path: str | Path) -> NarrativeIR:
    data = json.loads(Path(path).read_text("utf-8"))
    if isinstance(data, dict) and data.get("schema_version") == "1.0":
        # ADR-0012：1.0→1.1 无损迁移。新字段全部可选默认空，
        # 迁移 = 纯字段默认 + 版本号提升（回滚 = 忽略新字段重序列化）。
        data["schema_version"] = "1.1"
    return NarrativeIR.model_validate(data)


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _episodes_by_no(ir_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """按人类可见集号升序返回集列表（重放 state_changes 的确定性顺序）。"""
    return sorted(ir_dict.get("episodes", []), key=lambda e: e.get("no", 0))


def derive_state(ir_dict: dict[str, Any]) -> dict[str, float | str | int]:
    """ADR-0012：StateVariable 当前值（确定性重放，纯函数）。

    从 initial 出发，按 episode_no 升序重放各集 state_changes：
    number 型且 delta 为数值 → 累加；否则（string 型 / 非数值 delta）→ 覆盖。
    IR 本体永不被改写，current 只进计算视图。
    """
    out: dict[str, float | str | int] = {}
    for v in ir_dict.get("state_variables", []):
        k = v.get("key")
        if k:
            out[k] = v.get("initial", 0)
    for ep in _episodes_by_no(ir_dict):
        for ch in ep.get("state_changes", []):
            k = ch.get("key")
            if k not in out:
                continue
            cur, d = out[k], ch.get("delta")
            out[k] = cur + d if _is_num(cur) and _is_num(d) else d
    return out


def derive_stage(ir_dict: dict[str, Any], key: str) -> int:
    """ADR-0012：DarkThread 当前阶段（确定性重放，纯函数）。

    按 episode_no 升序累加各集 state_changes 里 key 匹配的 int delta，
    从 0 起步；合法范围 [0, len(stages)-1] 由 INV-19 把关。
    """
    stage = 0
    for ep in _episodes_by_no(ir_dict):
        for ch in ep.get("state_changes", []):
            if ch.get("key") != key:
                continue
            d = ch.get("delta")
            if isinstance(d, int) and not isinstance(d, bool):
                stage += d
    return stage


def _chars(s: str) -> int:
    import re as _re

    return len(_re.sub(r"[\s，。、；：？！“”‘’（）《》…—·,.;:?!\"'()\[\]<>~-]+", "", s or ""))


def _episode_id_of(ir: dict, scene_id: str) -> str:
    for ep in ir.get("episodes", []):
        if any(
            s.get("parent_id") == ep.get("id") and s.get("id") == scene_id
            for s in ir.get("scenes", [])
        ):
            return ep.get("id", "")
    for s in ir.get("scenes", []):
        if s.get("id") == scene_id:
            return s.get("parent_id", "")
    return ""


def _episode_of(ir: dict, scene_id: str) -> dict[str, Any]:
    eid = _episode_id_of(ir, scene_id)
    return next((e for e in ir.get("episodes", []) if e.get("id") == eid), {})
