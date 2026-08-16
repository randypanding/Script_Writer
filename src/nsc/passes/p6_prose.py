"""p6_prose：单集 Scene[]+Line[] → NovelChapter（段落 + 100% anchor_map）。"""

from __future__ import annotations

import json
from typing import Any

from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id, with_diag


class Module(DSPyPass):
    signature = signatures.Prose
    pass_name = "p6_prose"


@cached_pass("p6_prose")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    ep = fragment["episode"]
    beats = fragment["beats"]
    out = Module()(
        ctx,
        with_diag(
            {
                "episode_json": json.dumps(ep, ensure_ascii=False),
                "scenes_with_lines_json": json.dumps(
                    fragment["scenes_with_lines"], ensure_ascii=False
                ),
                "bible_json": json.dumps(fragment["bible"], ensure_ascii=False),
                "voice_json": json.dumps(fragment["voice"], ensure_ascii=False),
                "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
            },
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
    for am in anchor_map:
        if am.get("beat_id") not in beat_ids:
            raise PassFailure(
                ep["id"], f"anchor_map 引用了不属于本集的 beat_id={am.get('beat_id')}"
            )
        bad = [x for x in am.get("line_ids", []) if x not in line_ids]
        if bad:
            raise PassFailure(ep["id"], f"anchor_map 引用了未知 line_id：{bad}")
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
