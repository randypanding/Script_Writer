"""DB 迁移与 JSONL 双向。"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_MIGRATION = Path("db/migrations/0001_init.sql")


def init_schema(conn: sqlite3.Connection) -> None:
    """按 0001_init.sql 初始化（幂等：已有 cases 表则跳过）。

    无 sqlite-vec 加载能力的 Python 构建跳过 vec0 虚拟表（仅检索用，T-16）。
    """
    vec_ok = False
    try:
        import sqlite_vec

        conn.enable_load_extension(True)  # type: ignore[attr-defined]
        sqlite_vec.load(conn)
        vec_ok = True
    except Exception:
        vec_ok = False
    already = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cases'"
    ).fetchone()
    if _MIGRATION.exists() and not already:
        sql = _MIGRATION.read_text("utf-8")
        if not vec_ok:
            sql = re.sub(r"CREATE VIRTUAL TABLE[^;]*vec0[^;]*;", "", sql, flags=re.IGNORECASE)
        conn.executescript(sql)
        conn.commit()
