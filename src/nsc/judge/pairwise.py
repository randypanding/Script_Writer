"""成对比较协议编排（T-08b）：两次调用 + swap 消除位置偏置 → 落 judge_scores。

协议见 spec/rubrics/pairwise_protocol.md §3：调用 1 顺序 (A,B)，调用 2 顺序 (B,A)，
两次结论相反 → tie；cited_spans 为空 → 重试后记 invalid。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ulid import ULID

from nsc.judge.rubric_judge import RubricJudge


def new_id() -> str:
    return str(ULID())


def judge_model_id(judge: RubricJudge) -> str:
    try:
        return str(judge.router.resolve(judge.tier).get("model", ""))
    except Exception:
        return ""


def run_pairwise(
    judge: RubricJudge,
    conn: sqlite3.Connection,
    *,
    pair_id: str,
    unit_kind: str,
    dimension: str,
    context: str,
    a_text: str,
    b_text: str,
    run_id: str = "",
    seed: int = 1,
) -> dict[str, Any]:
    """对一对文本判一次：两次调用（正向 + swap）+ 归并，结果三行写入 judge_scores。"""
    call1, call2, resolved = judge.judge_pair(dimension, context, a_text, b_text, seed=seed)
    model_id = judge_model_id(judge)
    judge_ver = judge.judge_ver
    rows = [
        (
            new_id(),
            run_id,
            pair_id,
            dimension,
            "pairwise",
            call1.winner,
            call1.margin,
            call1.rationale,
            json.dumps(call1.cited_spans, ensure_ascii=False),
            judge_ver,
            model_id,
            0,
            int(call1.invalid),
        ),
        (
            new_id(),
            run_id,
            pair_id,
            dimension,
            "pairwise",
            call2.winner,
            call2.margin,
            call2.rationale,
            json.dumps(call2.cited_spans, ensure_ascii=False),
            judge_ver,
            model_id,
            1,
            int(call2.invalid),
        ),
        (
            new_id(),
            run_id,
            pair_id,
            dimension,
            "pairwise",
            resolved.winner,
            resolved.margin,
            resolved.rationale,
            json.dumps(resolved.cited_spans, ensure_ascii=False),
            judge_ver,
            model_id,
            0,
            int(resolved.invalid),
        ),
    ]
    conn.executemany(
        """INSERT INTO judge_scores
           (score_id, run_id, pair_id, unit_id, dimension, mode, verdict, margin, rationale,
            cited_spans_json, judge_ver, model_id, swapped, invalid, created_at)
           VALUES (?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
        rows,
    )
    conn.commit()
    return {"pair_id": pair_id, "resolved": resolved, "call1": call1, "call2": call2}
