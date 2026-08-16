"""T-17：SQLite ↔ JSONL 双向测试（D28 / ADR-0006）。

覆盖：
- export → rebuild → export 输出逐字节一致（幂等，验收：make db-rebuild && make db-export 无 diff）
- rebuild 后 db 内容与 jsonl 一致
- next_case_id 递增且永不复用；空库从 case:0001 起
- export 目录缺失时 rebuild 产出空库（幂等起点）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db.migrate import export, next_case_id, open_db, rebuild


def _seed(conn, n_cases: int = 2, n_feedback: int = 3) -> None:
    from ulid import ULID

    for i in range(1, n_cases + 1):
        conn.execute(
            "INSERT INTO cases (case_id, brand_id, profile_id, industry, title,"
            " source, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                f"case:{i:04d}",
                "demo_tea",
                "short_drama_v1",
                "tea",
                f"title{i}",
                "client",
                "delivered",
                "2026-08-01T00:00:00+00:00",
            ),
        )
    for i in range(n_feedback):
        conn.execute(
            "INSERT INTO feedback (feedback_id, case_id, anchor_level, anchor_conf,"
            " dimension, verdict, severity, rationale_nl, original_text, revised_text,"
            " edit_type, author, confirmed_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(ULID()),
                f"case:{i % n_cases + 1:04d}",
                "bookmark",
                1.0,
                "structural",
                "revise",
                3,
                "r",
                "before",
                "after",
                "replace",
                "op",
                "",
                "2026-08-01T00:00:00+00:00",
            ),
        )
    conn.commit()


def _files(export_dir: Path) -> dict[str, str]:
    return {p.name: p.read_text("utf-8") for p in export_dir.glob("*.jsonl")}


def test_round_trip_idempotent(tmp_path: Path):
    db1 = tmp_path / "a.db"
    exp1 = tmp_path / "export1"
    conn = open_db(db1)
    _seed(conn)
    export(conn, exp1)
    conn.close()
    before = _files(exp1)
    assert len(before) == 7

    # rebuild（jsonl → 新 db）→ 再 export，必须逐字节一致
    db2 = tmp_path / "b.db"
    rebuild(db2, export_dir=exp1)
    exp2 = tmp_path / "export2"
    conn = open_db(db2)
    export(conn, exp2)
    conn.close()
    after = _files(exp2)

    assert set(before) == set(after)
    for name in before:
        assert before[name] == after[name], f"{name} 不一致（幂等失败）"


def test_rebuild_db_matches_jsonl(tmp_path: Path):
    db = tmp_path / "cases.db"
    exp = tmp_path / "export"
    conn = open_db(db)
    _seed(conn, n_cases=2, n_feedback=5)
    export(conn, exp)
    conn.close()

    rebuilt = tmp_path / "rebuilt.db"
    rebuild(rebuilt, export_dir=exp)
    conn = sqlite3.connect(str(rebuilt))
    try:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 5
        dims = {r[0] for r in conn.execute("SELECT DISTINCT dimension FROM feedback")}
        assert dims == {"structural"}
    finally:
        conn.close()


def test_rebuild_empty_export_dir_is_empty_db(tmp_path: Path):
    db = tmp_path / "d.db"
    rebuild(db, export_dir=tmp_path / "empty")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
    finally:
        conn.close()


def test_next_case_id_increments_and_never_reuses(tmp_path: Path):
    db = tmp_path / "c.db"
    conn = open_db(db)
    try:
        assert next_case_id(conn) == "case:0001"
        _seed(conn, n_cases=3)
        assert next_case_id(conn) == "case:0004"
        assert next_case_id(conn) == "case:0004"  # 两次调用不推进（永不复用，分配即用）
    finally:
        conn.close()
