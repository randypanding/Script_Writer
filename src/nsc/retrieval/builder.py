"""检索池构建（T-16）：从已验证的资产派生 retrieval_items。

两个积累来源：
  1. IR 快照（golden/human_revised/annotated）——种子池：把已验证的 IR 拆成
     beat_sequence / scene_card / dialogue_block / chapter 四种 unit。
  2. 已人工确认的 revision_pairs——飞轮池：客户接受的"改后文本"即最高质量示例。

质量口径（retrieval_items.quality）：人类接受=1.0；判官高分≈0.6；生成物=0.3。
COMPLIANCE §1：逆向标注（annotate）产出的节点不可作为示例，导出时置 usable_as_example=0。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ulid import ULID

from .pool import RetrievalItem

#: 快照 kind → 质量（golden 是人工审定，最高）。
DEFAULT_QUALITY_BY_KIND = {
    "golden": 1.0,
    "human_revised": 0.8,
    "annotated": 0.6,  # 逆向标注：结构可参考，但内容不进交付物示例
    "generated": 0.3,
}


def _conn(db_path: str | Path) -> sqlite3.Connection:
    from nsc.db import init_schema

    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    return conn


def build_pool_from_snapshots(
    db_path: str | Path,
    *,
    quality_by_kind: dict[str, float] | None = None,
    case_limit: int | None = None,
) -> list[RetrievalItem]:
    """从 ir_snapshots 拆 unit 进池。返回生成的条目（调用方再 upsert）。

    `annotated` 快照的产物仅作统计，usable_as_example=0（COMPLIANCE §1）。
    """
    quality = {**DEFAULT_QUALITY_BY_KIND, **(quality_by_kind or {})}
    conn = _conn(db_path)
    try:
        sql = "SELECT s.snapshot_id, s.case_id, s.kind, s.ir_json, c.industry, c.profile_id, c.brand_id"
        sql += " FROM ir_snapshots s JOIN cases c ON c.case_id = s.case_id"
        sql += " ORDER BY s.created_at"
        if case_limit:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (case_limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    items: list[RetrievalItem] = []
    for snapshot_id, case_id, kind, ir_json, industry, profile_id, brand_id in rows:
        try:
            ir = json.loads(ir_json)
        except json.JSONDecodeError:
            continue
        base = dict(
            case_id=case_id,
            industry=industry or "unknown",
            profile_id=profile_id or "unknown",
            brand_id=brand_id or "",
            quality=quality.get(kind, 0.3),
        )
        usable = kind != "annotated"
        items += _extract_units(ir, base, snapshot_id, usable)
    return items


def _extract_units(
    ir: dict[str, Any], base: dict[str, Any], snapshot_id: str, usable: bool
) -> list[RetrievalItem]:
    out: list[RetrievalItem] = []
    for ch in ir.get("chapters", []):
        text = "\n".join(ch.get("paragraphs", []))
        if text.strip():
            out.append(
                RetrievalItem(
                    item_id=str(ULID()),
                    unit_kind="chapter",
                    content=text,
                    node_id=ch.get("id"),
                    meta={"snapshot_id": snapshot_id, "episode_no": ch.get("order", 0) + 1},
                    usable_as_example=usable,
                    **base,
                )
            )

    ep_by_id = {e["id"]: e for e in ir.get("episodes", [])}
    sc_by_id = {s["id"]: s for s in ir.get("scenes", [])}
    scene_of_beat = {b["id"]: b["parent_id"] for b in ir.get("beats", [])}
    beats_by_scene: dict[str, list[dict[str, Any]]] = {}
    for b in ir.get("beats", []):
        beats_by_scene.setdefault(b["parent_id"], []).append(b)
    for sc_id, beats in beats_by_scene.items():
        sc = sc_by_id.get(sc_id)
        if sc is None:
            continue
        ordered = sorted(beats, key=lambda b: b["order"])
        scene_card = (
            f"场景：{sc.get('summary', '')}\n目标：{sc.get('goal', '')}\n"
            f"冲突：{sc.get('conflict', '')}\n转折：{sc.get('turn', '')}"
        )
        out.append(
            RetrievalItem(
                item_id=str(ULID()),
                unit_kind="scene_card",
                content=scene_card,
                node_id=sc_id,
                meta={"snapshot_id": snapshot_id},
                usable_as_example=usable,
                **base,
            )
        )
        dialogue = [
            ln.get("text", "")
            for b in ordered
            for ln in ir.get("lines", [])
            if ln.get("parent_id") == b["id"] and ln.get("line_type") in ("dialogue", "voiceover")
        ]
        if dialogue:
            out.append(
                RetrievalItem(
                    item_id=str(ULID()),
                    unit_kind="dialogue_block",
                    content="\n".join(dialogue),
                    node_id=sc_id,
                    meta={
                        "snapshot_id": snapshot_id,
                        "beat_count": len(ordered),
                        "summary": sc.get("summary", ""),
                    },
                    usable_as_example=usable,
                    **base,
                )
            )

    # beat_sequence：以集为单位（场景 → 集）
    ep_of_scene = {sc_id: sc["parent_id"] for sc_id, sc in sc_by_id.items()}
    seq_by_ep: dict[str, list[str]] = {}
    for b in ir.get("beats", []):
        ep_id = ep_of_scene.get(scene_of_beat.get(b["id"], ""), "")
        if ep_id:
            seq_by_ep.setdefault(ep_id, []).append(b["summary"])
    for ep_id, summaries in seq_by_ep.items():
        ep = ep_by_id.get(ep_id)
        if ep is None:
            continue
        content = f"第{ep['no']}集（{ep['title']}）：\n" + "\n".join(f"- {s}" for s in summaries)
        out.append(
            RetrievalItem(
                item_id=str(ULID()),
                unit_kind="beat_sequence",
                content=content,
                node_id=ep_id,
                meta={"snapshot_id": snapshot_id, "episode_no": ep["no"]},
                usable_as_example=usable,
                **base,
            )
        )
    return out


def build_pool_from_revisions(db_path: str | Path, *, quality: float = 1.0) -> list[RetrievalItem]:
    """从**已人工确认**的修订对构建飞轮池。

    只收 confirmed_by 非空的 feedback 对应的 revision_pairs：未确认（仅 LLM 猜测）
    不进池，否则会把幻觉当教材。content 取改后文本（人类接受版）。
    """
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            """SELECT rp.pair_id, rp.unit_kind, rp.after_text, rp.before_text, rp.dimension,
                      rp.context_json, f.case_id, f.confirmed_by,
                      c.industry, c.profile_id, c.brand_id
               FROM revision_pairs rp
               JOIN feedback f ON f.feedback_id = rp.feedback_id
               JOIN cases c ON c.case_id = f.case_id
               WHERE f.confirmed_by <> ''"""
        ).fetchall()
    finally:
        conn.close()

    items: list[RetrievalItem] = []
    for (
        pair_id,
        unit_kind,
        after,
        before,
        dimension,
        context_json,
        case_id,
        confirmed,
        industry,
        profile_id,
        brand_id,
    ) in rows:
        try:
            context = json.loads(context_json or "{}")
        except json.JSONDecodeError:
            context = {}
        if not (after or "").strip():
            continue
        items.append(
            RetrievalItem(
                item_id=f"rev:{pair_id}",
                case_id=case_id,
                unit_kind=unit_kind,
                industry=industry or "unknown",
                profile_id=profile_id or "unknown",
                brand_id=brand_id or "",
                quality=quality,
                content=after,
                node_id=context.get("node_id"),
                meta={
                    "dimension": dimension,
                    "confirmed_by": confirmed,
                    "before": (before or "")[:200],
                },
                usable_as_example=True,
            )
        )
    return items
