"""db ↔ jsonl 一致性守卫（ADR-0006 / D28）。

检查 `cases/cases.db` 的 7 张真相表是否与 `cases/export/*.jsonl` 一致。
CI 中跑；若 db 不存在则跳过（幂等起点）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_DB = Path("cases/cases.db")
_EXPORT = Path("cases/export")
_TABLES = [
    "cases",
    "ir_snapshots",
    "feedback",
    "revision_pairs",
    "preference_pairs",
    "judge_calibration",
    "retrieval_items",
]


def verify() -> list[str]:
    """返回不一致描述列表；空列表 = 一致。"""
    if not _DB.exists():
        return []
    if not _EXPORT.exists():
        return [f"jsonl 导出目录不存在：{_EXPORT}（跑一次 make db-export 生成）"]
    problems: list[str] = []
    conn = sqlite3.connect(str(_DB))
    try:
        for table in _TABLES:
            filename = f"{table}.jsonl"
            fp = _EXPORT / filename
            if not fp.exists():
                problems.append(f"缺少 {filename}（跑一次 make db-export 生成）")
                continue
            # 读 db 全量
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
            if not cols:
                continue
            pk = [
                c[1]
                for c in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                if int(c[5]) > 0
            ]
            pk_col = pk[0] if pk else cols[0]
            rows = conn.execute(
                f"SELECT {', '.join(cols)} FROM {table} ORDER BY {pk_col}"
            ).fetchall()
            db_objs = [
                json.dumps(dict(zip(cols, r, strict=True)), ensure_ascii=False, sort_keys=True)
                for r in rows
            ]

            # 读 jsonl
            lines = [ln for ln in fp.read_text("utf-8").splitlines() if ln.strip()]
            jl_objs = [
                json.dumps(json.loads(ln), ensure_ascii=False, sort_keys=True) for ln in lines
            ]

            if db_objs != jl_objs:
                problems.append(
                    f"{table}：db 有 {len(db_objs)} 行，jsonl 有 {len(jl_objs)} 行"
                    f"（跑 make db-export 同步）"
                )
    finally:
        conn.close()
    return problems


def main() -> int:
    problems = verify()
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
