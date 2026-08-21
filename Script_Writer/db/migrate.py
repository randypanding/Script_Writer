"""SQLite ↔ JSONL 双向（D28 / ADR-0006）。

真相在 `cases/export/*.jsonl`（git 可见、可 diff、可审）；`cases/cases.db` 是可重建的工作副本。
- `export()`：db 的"真相表" → jsonl。按主键排序 + 固定列序，输出确定性，保证幂等。
- `rebuild()`：删库重建，按外键依赖顺序从 jsonl 回填。
- `next_case_id()`：`case:NNNN` 四位递增，永不复用。

export 只序列化 7 张真相表（cases/README.md 的清单）。nodes / runs / rules / rule_hits /
judge_scores / observations_index / metrics_weekly 是派生物（由索引 / 统计 / 编译重建），不落 jsonl。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB = "cases/cases.db"
DEFAULT_EXPORT_DIR = "cases/export"

#: 真相表 → 导出文件名。加载顺序即外键依赖顺序（重建时按此回填）。
TABLE_ORDER: list[tuple[str, str]] = [
    ("cases", "cases.jsonl"),
    ("ir_snapshots", "ir_snapshots.jsonl"),
    ("feedback", "feedback.jsonl"),
    ("revision_pairs", "revision_pairs.jsonl"),
    ("preference_pairs", "preference_pairs.jsonl"),
    ("judge_calibration", "judge_calibration.jsonl"),
    ("retrieval_items", "retrieval_items.jsonl"),
]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """按 schema 定义顺序取列名（重建时列序与导出一致，保证往返稳定）。"""
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return [str(row[1]) for row in cur.fetchall()]


def _primary_key(conn: sqlite3.Connection, table: str) -> str:
    """单列主键的列名（7 张真相表均为单列 PK）。"""
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    pk_cols = [str(row[1]) for row in cur.fetchall() if int(row[5]) > 0]
    if len(pk_cols) != 1:
        raise ValueError(f"表 {table} 需要单列主键才能导出 jsonl，实际：{pk_cols}")
    return pk_cols[0]


def export(conn: sqlite3.Connection, export_dir: str | Path) -> list[Path]:
    """db 的真相表 → cases/export/*.jsonl（按主键排序；每行一个对象，列序 = schema）。"""
    out = Path(export_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for table, filename in TABLE_ORDER:
        cols = _table_columns(conn, table)
        pk = _primary_key(conn, table)
        if not cols:
            continue
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {pk}").fetchall()
        target = out / filename
        with target.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(dict(zip(cols, row, strict=True)), ensure_ascii=False))
                f.write("\n")
        written.append(target)
    return written


def rebuild(db_path: str | Path, export_dir: str | Path = DEFAULT_EXPORT_DIR) -> Path:
    """删库重建：cases/export/*.jsonl → cases.db（工作副本，派生表一并清空）。

    返回 db 路径。jsonl 目录不存在或无文件时建出空库（幂等起点）。
    """
    from nsc.db import init_schema

    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    for stale in list(db.parent.glob(f"{db.name}-*")):
        stale.unlink()  # WAL/SHM 侧文件
    db.unlink(missing_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        init_schema(conn)
        src = Path(export_dir)
        for table, filename in TABLE_ORDER:
            f = src / filename
            if not f.exists():
                continue
            lines = [ln for ln in f.read_text("utf-8").splitlines() if ln.strip()]
            if not lines:
                continue
            rows = [json.loads(ln) for ln in lines]
            cols = list(rows[0].keys())
            placeholders = ", ".join("?" for _ in cols)
            conn.executemany(
                f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                [tuple(r.get(c) for c in cols) for r in rows],
            )
        conn.commit()
    finally:
        conn.close()
    return db


def next_case_id(conn: sqlite3.Connection) -> str:
    """case:NNNN 四位递增分配。空库从 case:0001 起；按数值取 max，永不复用。"""
    row = conn.execute("SELECT case_id FROM cases").fetchall()
    max_n = 0
    for (case_id,) in row:
        m = re.match(r"^case:(\d{4})$", str(case_id))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"case:{max_n + 1:04d}"


def open_db(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """打开（不存在则初始化 schema）。"""
    from nsc.db import init_schema

    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    init_schema(conn)
    return conn


def rows_as_dicts(
    conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    """查询 → dict 列表（供统计复用）。"""
    cur = conn.execute(sql, args)
    cols = [c[0] for c in cur.description or []]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
