"""SQLite 快照链（T-32）：内容哈希主键 + 最优快照选取 + 回滚。

独立 state 库，不碰 cases.db 与 db/migrations（那是 T-17 的领域）。
id = sha256(project_id + stage + ir_json)[:16]：同内容幂等覆盖（INSERT OR REPLACE），
配 gate.Counts 存检查计数，best_snapshot 按 (block, warn, info)↑ → judge_score↓ →
created_at↓ 取最优，供退步回滚（T-41 plateau）使用。
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nsc.revise.gate import Counts

_SCHEMA = """CREATE TABLE IF NOT EXISTS snapshots(
    id TEXT PRIMARY KEY,
    project_id TEXT,
    stage TEXT,
    ir_json TEXT,
    block INTEGER,
    warn INTEGER,
    info INTEGER,
    judge_score REAL,
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


def save_snapshot(
    db_path: str | Path,
    project_id: str,
    stage: str,
    ir_json: str,
    counts: Counts,
    judge_score: float | None = None,
) -> str:
    """落盘一条快照，返回内容哈希 id。同内容重复保存为幂等覆盖。"""
    sid = hashlib.sha256(f"{project_id}{stage}{ir_json}".encode()).hexdigest()[:16]
    js = judge_score if judge_score is not None else counts.judge_score
    with closing(_conn(db_path)) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO snapshots
               (id, project_id, stage, ir_json, block, warn, info, judge_score, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                sid,
                project_id,
                stage,
                ir_json,
                counts.block,
                counts.warn,
                counts.info,
                js,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    return sid


def list_snapshots(
    db_path: str | Path, project_id: str, stage: str | None = None
) -> list[dict[str, Any]]:
    """按项目（可再按 stage）列出快照，created_at 升序。"""
    sql = "SELECT * FROM snapshots WHERE project_id = ?"
    args: list[Any] = [project_id]
    if stage is not None:
        sql += " AND stage = ?"
        args.append(stage)
    sql += " ORDER BY created_at"
    with closing(_conn(db_path)) as conn:
        return _rows_to_dicts(conn.execute(sql, args))


def best_snapshot(db_path: str | Path, project_id: str, stage: str) -> dict[str, Any] | None:
    """取最优快照：(block, warn, info) 升序 → judge_score 降序（NULL 视为 -inf）→ created_at 降序。"""
    rows = list_snapshots(db_path, project_id, stage)
    if not rows:
        return None
    # 多趟稳定排序：越晚排序的键优先级越高
    rows.sort(key=lambda r: str(r["created_at"] or ""), reverse=True)
    rows.sort(key=lambda r: -(r["judge_score"] if r["judge_score"] is not None else float("-inf")))
    rows.sort(key=lambda r: (r["block"], r["warn"], r["info"]))
    return rows[0]


def rollback_to(db_path: str | Path, snapshot_id: str) -> dict[str, Any]:
    """按 id 取回快照整行（ir_json/stage/计数等）；不存在抛 KeyError。"""
    with closing(_conn(db_path)) as conn:
        rows = _rows_to_dicts(conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)))
    if not rows:
        raise KeyError(f"快照不存在: {snapshot_id}")
    return rows[0]
