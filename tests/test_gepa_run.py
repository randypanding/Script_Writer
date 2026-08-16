"""T-13 GEPA 编排测试。

验收（WORK_ORDERS T-13 / gepa_run.py 设计注释）：
- build-dataset 按 case 分层切分（train/val 不共享 case = 不泄漏）
- 回归闸：score_after ≤ score_before + 0.02 时不写入 prompts/（构造退化验证）
- 过闸时写 prompts/<pass>.json 且含 content_hash
- 成本超限不写入
真实 GEPA 调用以注入桩替代（CI 不打 LLM）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from nsc.db import init_schema
from nsc.optimize.build_dataset import build_dataset, split_case_ids
from nsc.optimize.gepa_run import REGRESSION_MARGIN, run


def _mk_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    return conn


def _seed_revisions(conn: sqlite3.Connection) -> None:
    for c in ("case:0001", "case:0002", "case:0003", "case:0004"):
        conn.execute(
            "INSERT INTO cases (case_id, brand_id, profile_id, industry, title, source, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (c, "b", "p", "tea", c, "client", "delivered", "2026-01-01T00:00:00Z"),
        )
    for i, c in enumerate(["case:0001", "case:0002", "case:0003", "case:0004"]):
        fid = f"fb{i}"
        conn.execute(
            """INSERT INTO feedback (feedback_id, case_id, target_node_id, anchor_level, anchor_conf,
               dimension, verdict, severity, rationale_nl, original_text, revised_text, edit_type,
               author, confirmed_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fid,
                c,
                None,
                "bookmark",
                1.0,
                "placement",
                "revise",
                3,
                "r",
                "原",
                "改",
                "replace",
                "客户",
                "op",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            """INSERT INTO revision_pairs (pair_id, feedback_id, unit_kind, context_json,
               before_text, after_text, dimension, split) VALUES (?,?,?,?,?,?,?,?)""",
            (f"rp{i}", fid, "beat_sequence", "{}", "原文", "改后文", "placement", "train"),
        )
    conn.commit()


# ---------------------------------------------------------------- build_dataset
def test_split_case_ids_no_leak():
    train, val = split_case_ids(["case:0001", "case:0002", "case:0003", "case:0004"])
    assert not (train & val)  # 不共享 case = 不泄漏
    assert train | val == {"case:0001", "case:0002", "case:0003", "case:0004"}
    assert len(val) >= 1


def test_split_case_ids_single_case_all_train():
    train, val = split_case_ids(["case:0001"])
    assert train == {"case:0001"} and val == set()


def test_build_dataset_split_by_case(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    _seed_revisions(conn)
    conn.close()
    stats = build_dataset(db, "p3_beatsheet", out_dir=tmp_path / "ds")
    assert stats["n_train"] + stats["n_val"] == 4
    # 防泄漏：train/val 不共享 case
    assert not (set(stats["train_cases"]) & set(stats["val_cases"]))
    # 每条样本带 split 与 human_edits
    for line in Path(stats["train_path"]).read_text().splitlines():
        s = json.loads(line)
        assert s["split"] == "train"
        assert s["human_edits"][0]["after"] == "改后文"


# ---------------------------------------------------------------- gepa_run 回归闸
def _runner_improving(**kw):
    return {
        "instruction": "改进后的指令",
        "score_before": 0.5,
        "score_after": 0.5 + REGRESSION_MARGIN + 0.01,
        "cost_usd": 1.0,
        "detailed_results": None,
    }


def _runner_degrading(**kw):
    return {
        "instruction": "退化的指令",
        "score_before": 0.5,
        "score_after": 0.5,  # 无提升
        "cost_usd": 1.0,
        "detailed_results": None,
    }


def _runner_costly(**kw):
    return {
        "instruction": "x",
        "score_before": 0.5,
        "score_after": 0.9,
        "cost_usd": 999.0,
        "detailed_results": None,
    }


def test_gepa_run_writes_prompt_on_improvement(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    _seed_revisions(conn)
    conn.close()
    out_dir = tmp_path / "prompts"
    res = run(
        "p3_beatsheet",
        db_path=db,
        dataset_dir=tmp_path / "ds",
        out_dir=out_dir,
        rejected_dir=tmp_path / "rej",
        log_root=tmp_path / "log",
        gepa_runner=_runner_improving,
    )
    assert res["written"]
    payload = json.loads(Path(res["path"]).read_text())
    assert payload["instructions"] == "改进后的指令"
    assert payload["_meta"]["content_hash"]
    assert payload["_meta"]["score_after"] > payload["_meta"]["score_before"]


def test_gepa_run_rejects_on_no_improvement(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    _seed_revisions(conn)
    conn.close()
    out_dir = tmp_path / "prompts"
    res = run(
        "p3_beatsheet",
        db_path=db,
        dataset_dir=tmp_path / "ds",
        out_dir=out_dir,
        rejected_dir=tmp_path / "rej",
        log_root=tmp_path / "log",
        gepa_runner=_runner_degrading,
    )
    assert not res["written"]
    assert "回归闸" in res["reason"]
    assert not (out_dir / "p3_beatsheet.json").exists()  # 未写入
    assert list((tmp_path / "rej" / "p3_beatsheet").glob("*.json"))  # 退化进 rejected/


def test_gepa_run_rejects_on_cost_overrun(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    _seed_revisions(conn)
    conn.close()
    out_dir = tmp_path / "prompts"
    res = run(
        "p3_beatsheet",
        db_path=db,
        dataset_dir=tmp_path / "ds",
        out_dir=out_dir,
        rejected_dir=tmp_path / "rej",
        log_root=tmp_path / "log",
        max_cost_usd=20.0,
        gepa_runner=_runner_costly,
    )
    assert not res["written"]
    assert "成本" in res["reason"]
    assert not (out_dir / "p3_beatsheet.json").exists()


def test_gepa_run_empty_trainset(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    conn.close()
    res = run(
        "p3_beatsheet",
        db_path=db,
        dataset_dir=tmp_path / "ds",
        out_dir=tmp_path / "prompts",
        rejected_dir=tmp_path / "rej",
        log_root=tmp_path / "log",
        gepa_runner=_runner_improving,
    )
    assert not res["written"]
    assert "trainset 为空" in res["reason"]
