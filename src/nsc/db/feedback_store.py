"""feedback / revision_pairs / preference_pairs / observations_index 的最小读写（T-11）。

db 是可重建工作副本，真相在 cases/export/*.jsonl（D28，双向同步归 T-17）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ulid import ULID

from nsc.db import init_schema
from nsc.feedback.align import EditRecord


class FeedbackStore:
    """反馈相关四张表的写入 + L1 聚类池查询。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        init_schema(self._conn)

    def ensure_case(self, case_id: str) -> str:
        """case 不存在时补最小行。返回 brand_id（供 L0 observation 的 scope 使用）。"""
        row = self._conn.execute(
            "SELECT brand_id FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row:
            return str(row[0])
        self._conn.execute(
            """INSERT INTO cases (case_id, brand_id, profile_id, industry, title,
               source, status, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (
                case_id,
                "unknown",
                "unknown",
                "unknown",
                case_id,
                "client",
                "delivered",
                datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()
        return "unknown"

    def insert_feedback(self, case_id: str, rec: EditRecord) -> str:
        if rec.dimension is None or rec.verdict is None or rec.severity is None:
            raise ValueError(
                "未分类的 EditRecord 不得落库（dimension/verdict/severity 为 NOT NULL）"
            )
        feedback_id = str(ULID())
        self._conn.execute(
            """INSERT INTO feedback (feedback_id, case_id, target_node_id, anchor_level,
               anchor_conf, dimension, verdict, severity, rationale_nl, original_text,
               revised_text, edit_type, author, confirmed_by, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                feedback_id,
                case_id,
                rec.node_id,
                rec.anchor_level,
                rec.anchor_confidence,
                rec.dimension,
                rec.verdict,
                rec.severity,
                rec.rationale_nl,
                rec.before,
                rec.after,
                rec.edit_type,
                rec.author,
                "",  # confirmed_by 必须留空：仅 LLM 猜测，人工确认后才进 L1 聚类
                datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()
        return feedback_id

    def insert_revision_pair(
        self, feedback_id: str, rec: EditRecord, unit_kind: str, split: str = "train"
    ) -> str:
        pair_id = str(ULID())
        context = {
            "node_id": rec.node_id,
            "anchor_level": rec.anchor_level,
            "anchor_confidence": rec.anchor_confidence,
            "author": rec.author,
            "ts": rec.ts,
            "human_comment": rec.human_comment,
        }
        self._conn.execute(
            """INSERT INTO revision_pairs (pair_id, feedback_id, unit_kind, context_json,
               before_text, after_text, dimension, split) VALUES (?,?,?,?,?,?,?,?)""",
            (
                pair_id,
                feedback_id,
                unit_kind,
                json.dumps(context, ensure_ascii=False),
                rec.before,
                rec.after,
                rec.dimension,
                split,
            ),
        )
        self._conn.commit()
        return pair_id

    def insert_preference_pair(
        self, case_id: str, rec: EditRecord, unit_kind: str, split: str = "train"
    ) -> str:
        pair_id = str(ULID())
        context = {"node_id": rec.node_id, "anchor_level": rec.anchor_level}
        self._conn.execute(
            """INSERT INTO preference_pairs (pair_id, case_id, unit_kind, a_text, b_text,
               context_json, human_pref, dimension, origin, split) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                pair_id,
                case_id,
                unit_kind,
                rec.before,
                rec.after,
                json.dumps(context, ensure_ascii=False),
                "b",  # 人类偏好 = 客户改后版本
                rec.dimension,
                "revision",
                split,
            ),
        )
        self._conn.commit()
        return pair_id

    def insert_observation_index(self, obs_id: str, feedback_id: str, yaml_path: Path) -> None:
        self._conn.execute(
            """INSERT INTO observations_index (obs_id, feedback_id, cluster_id, yaml_path, created_at)
               VALUES (?,?,?,?,?)""",
            (obs_id, feedback_id, None, str(yaml_path), datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def clusterable_feedback(self) -> list[dict[str, Any]]:
        """L1 聚类的唯一入口（T-14 消费）：confirmed_by 非空 = 人工确认过。"""
        cur = self._conn.execute("SELECT * FROM feedback WHERE confirmed_by <> ''")
        cols = [c[0] for c in cur.description or []]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def feedback_for_case(self, case_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM feedback WHERE case_id = ? ORDER BY created_at", (case_id,)
        )
        cols = [c[0] for c in cur.description or []]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def execute(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        """确认回写等运维操作的最小逃生舱（如 UPDATE confirmed_by）。"""
        cur = self._conn.execute(sql, args)
        self._conn.commit()
        return cur

    def close(self) -> None:
        self._conn.close()
