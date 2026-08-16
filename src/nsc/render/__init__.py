"""渲染编排（p7_render）：从完整 IR 产出全部交付物 + manifest.json。

零 LLM。交付物：
  novel.txt / novel.docx（含锚点）/ screenplay.fountain / storyboard.csv / anchors.csv
manifest.json 记录版本、时间、每份产物的字节数与锚点统计（D20 Provenance）。
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .anchors import Paragraph
from .docx import read_docx_anchors, render_docx
from .fountain import render_fountain
from .novel import render_novel
from .storyboard import render_storyboard


def render_all(
    ir: dict[str, Any],
    out_dir: str | Path = "out/demo_tea",
    *,
    profile_ver: str = "",
    brand_ver: str = "",
    ruleset_ver: str = "",
    promptset_ver: str = "",
) -> dict[str, Any]:
    """渲染全部交付物到 out_dir，返回 manifest（也写入 out_dir/manifest.json）。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    chapters = ir.get("chapters", [])
    novel_paragraphs = render_novel(chapters)

    # 小说纯文本
    novel_txt = "\n\n".join(
        f"# {ch.get('title', '')}\n\n" + "\n\n".join(ch.get("paragraphs", [])) for ch in chapters
    )
    (out / "novel.txt").write_text(novel_txt, "utf-8")

    # 小说 docx（含锚点）
    render_docx(novel_paragraphs, out / "novel.docx")

    # 剧本
    (out / "screenplay.fountain").write_text(render_fountain(ir), "utf-8")

    # 分镜表
    (out / "storyboard.csv").write_text(render_storyboard(ir), "utf-8")

    # 锚点表（可供 T-10 反向对齐直接消费）
    _write_anchors_csv(novel_paragraphs, out / "anchors.csv")

    anchored = sum(1 for p in novel_paragraphs if p.node_id)
    manifest = {
        "schema_version": "1.0",
        "kind": "render_manifest",
        "created_at": datetime.now(UTC).isoformat(),
        "profile_ver": profile_ver,
        "brand_ver": brand_ver,
        "ruleset_ver": ruleset_ver,
        "promptset_ver": promptset_ver,
        "artifacts": {
            "novel.txt": (out / "novel.txt").stat().st_size,
            "novel.docx": (out / "novel.docx").stat().st_size,
            "screenplay.fountain": (out / "screenplay.fountain").stat().st_size,
            "storyboard.csv": (out / "storyboard.csv").stat().st_size,
            "anchors.csv": (out / "anchors.csv").stat().st_size,
        },
        "anchors": {
            "paragraphs_total": len(novel_paragraphs),
            "anchored": anchored,
            "coverage": (anchored / len(novel_paragraphs)) if novel_paragraphs else 0.0,
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    return manifest


def _write_anchors_csv(paragraphs: list[Paragraph], path: Path) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["paragraph_no", "node_id", "text"])
    for i, p in enumerate(paragraphs):
        writer.writerow([i, p.node_id or "", p.text])
    path.write_text(buf.getvalue(), "utf-8")


def read_anchors_from_docx(path: str | Path) -> list[Paragraph]:
    """供 T-10 反向对齐读取交付 docx 的锚点段落序列。"""
    return read_docx_anchors(path)
