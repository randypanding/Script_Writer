"""检索池（T-16）：retrieval_items（标量） + retrieval_vec（BGE-M3 向量）。

COMPLIANCE §1 硬约束：`usable_as_example=0` 的条目（逆向标注片段、完整台词等）
**绝不**作为示例注入任何 Pass。`search()` 无条件过滤该列，调用方拿不到禁用条目。

检索路径（可靠性递减）：
  1. 向量 KNN（retrieval_vec 存在且给了 embedder）→ 在标量候选内重排；
  2. 标量回退（无 vec 表 / 嵌入失败）→ 按 quality DESC 取前 k。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .embed import Embedder

#: unit_kind 的合法取值（与 Work Order T-16 一致）。
UNIT_KINDS = ("beat_sequence", "scene_card", "dialogue_block", "chapter")

#: 向量重排前先按标量条件取的候选池大小（再在其中取 top-k）。
_CANDIDATE_POOL = 64


@dataclass(slots=True)
class RetrievalItem:
    item_id: str
    case_id: str
    unit_kind: str  # beat_sequence | scene_card | dialogue_block | chapter
    industry: str
    profile_id: str
    content: str
    brand_id: str = ""
    node_id: str | None = None
    quality: float = 0.0  # 人类接受=1.0；判官高分≈0.6；生成物=0.3
    meta: dict[str, Any] = field(default_factory=dict)
    usable_as_example: bool = True  # COMPLIANCE §1：逆向标注片段必须置 False


def connect(db_path: str | Any) -> sqlite3.Connection:
    """打开检索池连接（schema 缺失时按迁移初始化）。"""
    from nsc.db import init_schema

    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    return conn


def _has_vec_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='retrieval_vec'"
    ).fetchone()
    return row is not None


def upsert_items(
    conn: sqlite3.Connection, items: list[RetrievalItem], embedder: Embedder | None = None
) -> None:
    """写入 retrieval_items（幂等，item_id 主键），并在可用时填充 retrieval_vec 向量。

    向量写入失败不阻塞标量落库（vec 只是检索加速，不是真相）。
    """
    now = datetime.now(UTC).isoformat()
    for it in items:
        conn.execute(
            """INSERT INTO retrieval_items
               (item_id, case_id, node_id, unit_kind, industry, profile_id, brand_id,
                quality, content, meta_json, usable_as_example, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(item_id) DO UPDATE SET
                 case_id=excluded.case_id, node_id=excluded.node_id,
                 unit_kind=excluded.unit_kind, industry=excluded.industry,
                 profile_id=excluded.profile_id, brand_id=excluded.brand_id,
                 quality=excluded.quality, content=excluded.content,
                 meta_json=excluded.meta_json,
                 usable_as_example=excluded.usable_as_example""",
            (
                it.item_id,
                it.case_id,
                it.node_id,
                it.unit_kind,
                it.industry,
                it.profile_id,
                it.brand_id,
                it.quality,
                it.content,
                json.dumps(it.meta, ensure_ascii=False),
                int(it.usable_as_example),
                now,
            ),
        )
    conn.commit()

    if embedder is None or not _has_vec_table(conn):
        return
    try:
        vecs = embedder.encode([it.content for it in items])
        for it, v in zip(items, vecs, strict=True):
            conn.execute(
                "INSERT INTO retrieval_vec(rowid, item_id, embedding) VALUES (NULL, ?, ?)",
                (it.item_id, json.dumps(v)),
            )
        conn.commit()
    except Exception:
        # vec 只是加速层：任何嵌入失败都不应让标量池不可用
        conn.rollback()


def search(
    conn: sqlite3.Connection,
    query: str,
    embedder: Embedder | None = None,
    *,
    k: int = 3,
    unit_kind: str | None = None,
    industry: str | None = None,
    profile_id: str | None = None,
    quality_min: float = 0.0,
    prefer_vec: bool = True,
) -> list[RetrievalItem]:
    """按 unit_kind/industry/profile/quality 过滤后取前 k。

    **无条件过滤 `usable_as_example=1`**（COMPLIANCE §1，调用方拿不到禁用条目）。
    """
    k = max(1, int(k))
    candidates = _scalar_candidates(
        conn,
        limit=max(k, _CANDIDATE_POOL),
        unit_kind=unit_kind,
        industry=industry,
        profile_id=profile_id,
        quality_min=quality_min,
    )
    if not candidates:
        return []

    if prefer_vec and embedder is not None and _has_vec_table(conn):
        ranked = _vec_rank(conn, candidates, embedder, query)
        if ranked:
            candidates = ranked
    return candidates[:k]


def _scalar_candidates(
    conn: sqlite3.Connection,
    *,
    limit: int,
    unit_kind: str | None,
    industry: str | None,
    profile_id: str | None,
    quality_min: float,
) -> list[RetrievalItem]:
    where = ["usable_as_example = 1"]
    args: list[Any] = []
    if unit_kind:
        where.append("unit_kind = ?")
        args.append(unit_kind)
    if industry:
        where.append("industry = ?")
        args.append(industry)
    if profile_id:
        where.append("profile_id = ?")
        args.append(profile_id)
    if quality_min > 0:
        where.append("quality >= ?")
        args.append(quality_min)
    args.append(limit)
    rows = conn.execute(
        f"""SELECT item_id, case_id, node_id, unit_kind, industry, profile_id, brand_id,
                   quality, content, meta_json, usable_as_example
            FROM retrieval_items
            WHERE {" AND ".join(where)}
            ORDER BY quality DESC, created_at DESC
            LIMIT ?""",
        args,
    ).fetchall()
    return [_row_to_item(r) for r in rows]


def _vec_rank(
    conn: sqlite3.Connection,
    candidates: list[RetrievalItem],
    embedder: Embedder,
    query: str,
) -> list[RetrievalItem]:
    """用 vec0 KNN 对候选重排；查询/表为空或查询失败则返回 []（保持原序）。"""
    try:
        qv = embedder.encode([query])[0]
        rows = conn.execute(
            "SELECT item_id FROM retrieval_vec WHERE embedding MATCH ? AND k = ?",
            (json.dumps(qv), len(candidates)),
        ).fetchall()
    except Exception:
        return []
    if not rows:
        return []
    rank = {str(r[0]): i for i, r in enumerate(rows)}
    ordered = sorted(candidates, key=lambda it: rank.get(it.item_id, len(rank)))
    return ordered if ordered else candidates


def _row_to_item(row: tuple[Any, ...]) -> RetrievalItem:
    return RetrievalItem(
        item_id=str(row[0]),
        case_id=str(row[1]),
        node_id=row[2],
        unit_kind=str(row[3]),
        industry=str(row[4]),
        profile_id=str(row[5]),
        brand_id=str(row[6]),
        quality=float(row[7]),
        content=str(row[8]),
        meta=json.loads(row[9] or "{}"),
        usable_as_example=bool(row[10]),
    )


def format_examples(items: list[RetrievalItem], *, max_chars: int = 4000) -> str:
    """检索命中 → 注入 Pass 的 few-shot 文本（retrieved_cases）。

    每条例举 case_id / unit_kind / quality 便于溯源；超长截断。
    """
    blocks: list[str] = []
    used = 0
    for it in items:
        header = f"### 已验证案例 {it.case_id}（{it.unit_kind}，quality={it.quality:.1f}）"
        body = it.content.strip()
        if not body:
            continue
        if used + len(header) + len(body) + 2 > max_chars:
            break
        blocks.append(f"{header}\n{body}")
        used += len(header) + len(body) + 2
    return "\n\n".join(blocks)
