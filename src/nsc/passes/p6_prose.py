"""p6_prose：单集 Scene[]+Line[] → NovelChapter（段落 + 100% anchor_map）。

LLM 输入经 nsc.context.assemble 预算装配（ADR-0013）：P1=该集 scenes/lines 序列化
（不可裁剪），P5=episode/bible/voice/profile 参考层（逐条装入）；当前 pipeline 无
P2-P4 输入，传空。预算取 profile 的 context.budget，缺省足够大 → 现有内容不丢、
生成语义不变，只把拼装改为过预算装配。
"""

from __future__ import annotations

import json
from typing import Any

from spec.passes import signatures

from ..context import assemble
from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id, with_diag

# profile 未配置 context.budget 时的缺省（token）：远大于单集输入，保证不裁剪。
_DEFAULT_CONTEXT_BUDGET = 32768


class Module(DSPyPass):
    signature = signatures.Prose
    pass_name = "p6_prose"


# ---------------------------------------------------------------- round17 prompt 瘦身
# 实证：p6 首达即撞 shim 20000 护栏（prompt 46631 字符，其中 P1 全字段 dump 占大头）。
# 投影只留散文编织需要的字段；id 一律保留（anchor_map 引用 beat_id/line_ids 是硬契约）。

_SCENE_KEYS = (
    "id",
    "location_name",
    "time_of_day",
    "character_names",
    "goal",
    "conflict",
    "turn",
    "summary",
)
_BEAT_KEYS = ("id", "order", "beat_kind", "summary")
_LINE_KEYS = ("id", "line_type", "character_id", "text", "subtext", "delivery", "is_brand_line")
_PROFILE_KEYS = ("novel", "chars_per_second", "duration_tolerance", "genre", "language")


def _slim_scenes(scenes_with_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """scenes_with_lines 的散文投影：剥掉 IR 管理字段（provenance/locked/knowledge_state 等）。"""
    out = []
    for sc in scenes_with_lines:
        slim = {k: sc[k] for k in _SCENE_KEYS if k in sc}
        slim["beats"] = [
            {
                **{k: b[k] for k in _BEAT_KEYS if k in b},
                "lines": [{k: ln[k] for k in _LINE_KEYS if k in ln} for ln in b.get("lines", [])],
            }
            for b in sc.get("beats", [])
        ]
        out.append(slim)
    return out


def _slim_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """profile 的散文投影：只留下笔/时长相关的键（全量 profile dump 有数千字管理配置）。"""
    return {k: v for k, v in profile.items() if k in _PROFILE_KEYS}


@cached_pass("p6_prose")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    ep = fragment["episode"]
    beats = fragment["beats"]
    refs = [
        ("episode_json", json.dumps(fragment["episode"], ensure_ascii=False)),
        ("bible_json", json.dumps(fragment["bible"], ensure_ascii=False)),
        ("voice_json", json.dumps(fragment["voice"], ensure_ascii=False)),
        ("profile_json", json.dumps(_slim_profile(ctx.profile), ensure_ascii=False)),
    ]
    assembled = assemble(
        p0_system="",
        p1_current=json.dumps(_slim_scenes(fragment["scenes_with_lines"]), ensure_ascii=False),
        p2_prev_summary="",
        p3_facts=[],
        p4_rag=[],
        p5_bible=[text for _key, text in refs],
        budget=int(ctx.profile.get("context", {}).get("budget", _DEFAULT_CONTEXT_BUDGET)),
    )
    p1 = next((lay for lay in assembled.layers if lay.name == "P1"), None)
    p5 = next((lay for lay in assembled.layers if lay.name == "P5"), None)
    # P5 逐条装入是前缀式：从装配结果还原存活字段（首条未装入即后继全弃）。
    tail = p5.text if p5 is not None else ""
    ref_inputs: dict[str, str] = {}
    for key, text in refs:
        if text and tail.startswith(text):
            ref_inputs[key] = text
            tail = tail[len(text) + 1 :]  # 跳过层内 join 分隔符 "\n"
        else:
            break
    out = Module()(
        ctx,
        with_diag(
            {"scenes_with_lines_json": p1.text if p1 else "", **ref_inputs},
            fragment,
        ),
    )
    paragraphs = inner_json(out["paragraphs_json"], "p6_prose", "paragraphs_json")
    anchor_map = inner_json(out["anchor_map_json"], "p6_prose", "anchor_map_json")
    if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
        raise PassFailure(ep["id"], "p6_prose 输出的 paragraphs 应为字符串列表")
    if not paragraphs:
        raise PassFailure(ep["id"], "p6_prose 输出的 paragraphs 为空")

    beat_ids = {b["id"] for b in beats}
    line_ids = {ln["id"] for b in beats for ln in b.get("_lines", [])}
    if not isinstance(anchor_map, list):
        raise PassFailure(ep["id"], "p6_prose 输出的 anchor_map 应为列表")
    # round14 方法论：结构性约束一律机械兜底。anchor_map 的 beat_id/line_ids 若引用不存在
    # 的节点，直接过滤，不让 LLM 通过相位重试碰运气。
    filtered = []
    for am in anchor_map:
        if am.get("beat_id") not in beat_ids:
            continue
        valid_line_ids = [x for x in am.get("line_ids", []) if x in line_ids]
        filtered.append({**am, "line_ids": valid_line_ids})
    anchor_map = filtered
    # 覆盖判定与 NOV-001 口径一致（真相在规则）：Beat 的任一对白原文出现在段落里才算覆盖。
    # anchor_map 只是声明，文本证据才算数；这里提前拦，诊断可直接驱动重试。
    para_blob = "\n".join(paragraphs)
    missing = [
        b
        for b in beats
        if not any(
            str(ln.get("text") or "") and str(ln.get("text")) in para_blob
            for ln in b.get("_lines", [])
            if ln.get("line_type") == "dialogue"
        )
    ]
    if missing:
        desc = "；".join(f"[{b['id']}] {b.get('summary', '')}" for b in missing)
        raise PassFailure(
            ep["id"],
            f"以下 Beat 的对白未逐字织入章节段落（NOV-001 覆盖率不足）：{desc}。"
            "请重写段落，让这些 Beat 的台词原文出现在小说里。",
        )

    # NOV-002 生成侧机械预检：段落过长会把 fuzz.ratio(line, para) 拉穿 0.7。
    # 当 line 是 para 的子串时，ratio ≈ len(line)/len(para)；因此用 len(para)/len(line)
    # 作为快速上界，超过 5 倍即视为高风险，直接 phase retry。
    line_by_id = {ln["id"]: ln for b in beats for ln in b.get("_lines", [])}
    para_of = {}
    for am in anchor_map:
        idx = am.get("paragraph_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(paragraphs):
            continue
        para_of.setdefault(idx, []).extend(am.get("line_ids", []))
    for idx, para in enumerate(paragraphs):
        for lid in para_of.get(idx, []):
            ln = line_by_id.get(lid)
            if not ln or ln.get("line_type") != "dialogue":
                continue
            text = str(ln.get("text") or "")
            if not text or text not in para:
                continue
            if len(para) > len(text) * 5:
                raise PassFailure(
                    ep["id"],
                    f"Beat [{ln.get('parent_id', '?')}] 的 Line [{lid}] 对白所在段落过长"
                    f"（段落 {len(para)} 字 vs 对白 {len(text)} 字），"
                    "NOV-002 相似度会被拉低；请缩短段落或将对话独立成段。",
                )

    chapter = {
        "id": new_id(),
        "episode_id": ep["id"],
        "order": ep["order"],
        "title": str(out.get("chapter_title", "")).strip(),
        "paragraphs": paragraphs,
        "anchor_map": anchor_map,
        "provenance_id": ctx.run_id,
        "word_chars": sum(len(p) for p in paragraphs),
    }
    return {"episode_id": ep["id"], "chapter": chapter, "_usage": out["_usage"]}
