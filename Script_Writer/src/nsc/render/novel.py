"""小说渲染：把 NovelChapter 变成锚定段落序列（L1 书签的文本来源）。"""

from __future__ import annotations

from typing import Any

from .anchors import Paragraph


def render_chapter(chapter: dict[str, Any]) -> list[Paragraph]:
    """一个章节 → 锚定段落序列。

    每个段落通过 `chapter["anchor_map"]`（[{paragraph_index, beat_id, line_ids}]）
    映射回 beat_id。anchor_map 缺失/不完整时，段落的 node_id 置 None（尽力恢复）。
    """
    paragraphs = chapter.get("paragraphs", [])
    anchor_map: dict[int, str] = {}
    for entry in chapter.get("anchor_map", []):
        idx = entry.get("paragraph_index")
        if isinstance(idx, int) and entry.get("beat_id"):
            anchor_map[idx] = entry["beat_id"]

    out: list[Paragraph] = []
    for i, text in enumerate(paragraphs):
        out.append(Paragraph(node_id=anchor_map.get(i), text=text, kind="novel_paragraph"))
    return out


def render_novel(chapters: list[dict[str, Any]]) -> list[Paragraph]:
    """全部章节 → 平铺的锚定段落序列（章标题不作为锚点段）。"""
    out: list[Paragraph] = []
    for ch in chapters:
        out.extend(render_chapter(ch))
    return out
