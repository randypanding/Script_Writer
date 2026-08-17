"""Idea Bank（T-32，规格源：One-Sentence Idea Bank）：被删节点的素材银行。

删除节点时 deposit 入库（记录来源与原因），后续 Pass 上下文可注入
render_for_prompt 的"可复活素材"块，revive 标记已被重新采用。
bank_id = sha256(project_id + node_kind + content)[:16]：确定性、同素材幂等。
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """CREATE TABLE IF NOT EXISTS idea_bank(
    bank_id TEXT PRIMARY KEY,
    project_id TEXT,
    node_kind TEXT,
    content TEXT,
    source_node_id TEXT,
    removed_run_id TEXT,
    reason TEXT,
    quality_note TEXT DEFAULT '',
    revived INTEGER DEFAULT 0,
    created_at TEXT
)"""


def _conn(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _rows_to_dicts(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cur.description or []]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def deposit(
    db_path: str | Path,
    project_id: str,
    node_kind: str,
    content: str,
    source_node_id: str = "",
    removed_run_id: str = "",
    reason: str = "",
    quality_note: str = "",
) -> str:
    """入库一条被删素材，返回确定性 bank_id（同素材幂等覆盖）。"""
    bank_id = hashlib.sha256(f"{project_id}{node_kind}{content}".encode()).hexdigest()[:16]
    with closing(_conn(db_path)) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO idea_bank
               (bank_id, project_id, node_kind, content, source_node_id, removed_run_id,
                reason, quality_note, revived, created_at)
               VALUES (?,?,?,?,?,?,?,?,'0',?)""",
            (
                bank_id,
                project_id,
                node_kind,
                content,
                source_node_id,
                removed_run_id,
                reason,
                quality_note,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    return bank_id


def list_ideas(
    db_path: str | Path, project_id: str, include_revived: bool = False
) -> list[dict[str, Any]]:
    """列出项目素材；默认只列未复活的（可注入上下文的候选）。"""
    sql = "SELECT * FROM idea_bank WHERE project_id = ?"
    if not include_revived:
        sql += " AND revived = 0"
    sql += " ORDER BY created_at"
    with closing(_conn(db_path)) as conn:
        return _rows_to_dicts(conn.execute(sql, (project_id,)))


def revive(db_path: str | Path, bank_id: str) -> dict[str, Any]:
    """标记素材已被重新采用（revived=1）并返回该行；不存在或已复活抛 ValueError。"""
    with closing(_conn(db_path)) as conn:
        rows = _rows_to_dicts(conn.execute("SELECT * FROM idea_bank WHERE bank_id = ?", (bank_id,)))
        if not rows:
            raise ValueError(f"素材不存在: {bank_id}")
        if rows[0]["revived"]:
            raise ValueError(f"素材已复活过: {bank_id}")
        conn.execute("UPDATE idea_bank SET revived = 1 WHERE bank_id = ?", (bank_id,))
        conn.commit()
        rows2 = _rows_to_dicts(
            conn.execute("SELECT * FROM idea_bank WHERE bank_id = ?", (bank_id,))
        )
    return rows2[0]


def render_for_prompt(ideas: list[dict[str, Any]], limit: int = 5) -> str:
    """渲染成注入 Pass 上下文的"可复活素材"块；空列表返回空串。"""
    if not ideas:
        return ""
    lines = ["可复活素材（历史被删但值得复用的 idea，供参考）："]
    for idea in ideas[:limit]:
        note = idea.get("quality_note") or ""
        suffix = f" [{note}]" if note else ""
        lines.append(f"- ({idea.get('node_kind', '')}) {idea.get('content', '')}{suffix}")
    return "\n".join(lines)
