"""Fountain 剧本渲染（零 LLM，p7_render 的一支）。

从 IR 的 scene/beat/line 派生剧本。Fountain 是纯文本标准格式（fountain.io），
可直接被 screenplain/jouvence 渲染成 PDF。
"""

from __future__ import annotations

from typing import Any


def _scene_heading(scene: dict[str, Any], location: dict[str, Any] | None) -> str:
    loc_name = (location or {}).get("name") or scene.get("location_id", "未知地点")
    interior = scene.get("interior", True)
    t = scene.get("time_of_day", "unspecified")
    prefix = "INT." if interior else "EXT."
    token = {"day": " - DAY", "night": " - NIGHT", "dawn": " - DAWN", "dusk": " - DUSK"}.get(t, "")
    return f"{prefix} {loc_name}{token}"


def render_fountain(
    ir: dict[str, Any],
    *,
    per_episode: bool = True,
) -> str:
    """整部 → Fountain 文本。每次换集插入 `===` 分隔行。"""
    lines: list[str] = []
    for ep in ir.get("episodes", []):
        lines.append(f"## {ep.get('no', '?')}. {ep.get('title', '')}")
        lines.append(f"    {ep.get('logline', '')}")
        for sc in (s for s in ir.get("scenes", []) if s.get("parent_id") == ep.get("id")):
            loc = next(
                (x for x in ir.get("locations", []) if x.get("id") == sc.get("location_id")),
                None,
            )
            lines.append(_scene_heading(sc, loc))
            for bt in (b for b in ir.get("beats", []) if b.get("parent_id") == sc.get("id")):
                if bt.get("beat_kind") == "brand_moment":
                    lines.append(f"    [品牌植入：{bt.get('summary', '')}]")
                for ln in (x for x in ir.get("lines", []) if x.get("parent_id") == bt.get("id")):
                    lines.append(_render_line(ln, ir))
            lines.append("")
    return "\n".join(lines)


def _render_line(ln: dict[str, Any], ir: dict[str, Any]) -> str:
    ltype = ln.get("line_type")
    if ltype in ("dialogue", "voiceover"):
        char_id = ln.get("character_id")
        char = next((c for c in ir.get("characters", []) if c.get("id") == char_id), None)
        name = (char or {}).get("name", "？")
        delivery = ln.get("delivery") or ""
        hint = f" ({delivery})" if delivery else ""
        return f"{name}{hint}\n    {ln.get('text', '')}"
    if ltype == "action":
        return ln.get("text", "")
    if ltype == "caption":
        return f"    [{ln.get('text', '')}]"
    if ltype == "sfx":
        return f"    SOUND: {ln.get('text', '')}"
    return ln.get("text", "")
