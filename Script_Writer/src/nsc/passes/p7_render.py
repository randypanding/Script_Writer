"""p7_render：完整 IR → 交付物（零 LLM，纯字符串拼装）。

T-08 会替换为带三重锚点的 Fountain/docx 渲染器；本实现只保证端到端可跑通：
novel.md（小说视图）+ script.md（剧本视图）+ manifest.json（D20 溯源清单）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from . import PassContext, new_id

_ROLE_LABEL = {
    "dialogue": "",
    "voiceover": "（内心）",
    "action": "△ ",
    "caption": "【字幕】",
    "sfx": "【音效】",
}


def run(ctx: PassContext, ir: dict[str, Any]) -> dict[str, Any]:
    ctx.run_id = new_id()
    proj = ir["project"]
    out_dir = ctx.out_dir / str(proj.get("title") or proj["id"])
    out_dir.mkdir(parents=True, exist_ok=True)

    chars = {c["id"]: c["name"] for c in ir.get("characters", [])}
    novel_parts: list[str] = [f"# {proj['title']}（小说）", ""]
    script_parts: list[str] = [f"# {proj['title']}（剧本）", ""]

    ch_by_ep = {ch["episode_id"]: ch for ch in ir.get("chapters", [])}
    for ep in sorted(ir.get("episodes", []), key=lambda e: e["order"]):
        script_parts.append(f"\n## 第{ep['no']}集 {ep['title']}")
        scenes = [s for s in ir.get("scenes", []) if s["parent_id"] == ep["id"]]
        for sc in sorted(scenes, key=lambda s: s["order"]):
            script_parts.append(f"\n### 场 {sc['order'] + 1}（{sc.get('summary', '')}）")
            beats = [b for b in ir.get("beats", []) if b["parent_id"] == sc["id"]]
            for b in sorted(beats, key=lambda x: x["order"]):
                script_parts.append(f"\n[{b['beat_kind']}] {b['summary']}")
                lines = [ln for ln in ir.get("lines", []) if ln["parent_id"] == b["id"]]
                for ln in sorted(lines, key=lambda x: x["order"]):
                    label = _ROLE_LABEL.get(ln["line_type"], "")
                    speaker = chars.get(ln.get("character_id") or "", "")
                    head = f"{label}{speaker}：" if speaker else label or "- "
                    script_parts.append(f"{head}{ln['text']}")
        ch = ch_by_ep.get(ep["id"])
        if ch:
            novel_parts.append(f"\n## {ch.get('title') or '第' + str(ep['no']) + '章'}")
            novel_parts.extend(["", *ch["paragraphs"]])

    novel_path = out_dir / "novel.md"
    script_path = out_dir / "script.md"
    novel_path.write_text("\n".join(novel_parts) + "\n", "utf-8")
    script_path.write_text("\n".join(script_parts) + "\n", "utf-8")

    manifest = {
        "project": proj["title"],
        "run_id": ctx.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "artifacts": [str(novel_path), str(script_path)],
        "promptset_ver": ctx.promptset_ver,
        "ruleset_ver": ctx.ruleset_ver,
        "spec_sha": ctx.spec_sha,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
    )
    ctx.record_run("p7_render", input_hash=ctx.run_id, cache_hit=0, usage={}, wall_ms=0)
    return {"artifacts": manifest["artifacts"], "out_dir": str(out_dir)}
