"""分镜表渲染（storyboard.csv，零 LLM）。供拍摄/剪辑使用。"""

from __future__ import annotations

import csv
import io
from typing import Any


def render_storyboard(ir: dict[str, Any]) -> str:
    """整部 → storyboard.csv 文本。列：集/场/拍/类型/时长/summary/植入。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["episode", "scene", "beat", "beat_kind", "est_duration_s", "summary", "brand_moment"]
    )
    for ep in ir.get("episodes", []):
        for sc in (s for s in ir.get("scenes", []) if s.get("parent_id") == ep.get("id")):
            for bt in (b for b in ir.get("beats", []) if b.get("parent_id") == sc.get("id")):
                writer.writerow(
                    [
                        ep.get("no", ""),
                        _scene_index(ir, sc.get("id")),
                        _beat_index(ir, sc.get("id"), bt.get("id")),
                        bt.get("beat_kind", ""),
                        round(bt.get("est_duration_s", 0), 1),
                        bt.get("summary", ""),
                        "Y" if bt.get("brand_moment_id") else "",
                    ]
                )
    return buf.getvalue()


def _scene_index(ir: dict[str, Any], scene_id: str) -> int:
    return next((b.get("order", 0) for b in ir.get("scenes", []) if b.get("id") == scene_id), 0)


def _beat_index(ir: dict[str, Any], scene_id: str, beat_id: str) -> int:
    beats = [b for b in ir.get("beats", []) if b.get("parent_id") == scene_id]
    return next((i for i, b in enumerate(beats) if b.get("id") == beat_id), 0)
