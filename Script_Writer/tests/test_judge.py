"""T-08b 验收：判官 v1。

覆盖：输出解析/校验、成对协议（swap 相反→tie）、校准指标（一致率/κ/位置偏置）、
门禁（JUDGE_GATE_ENABLED）、run_calibration 端到端（stub 判官）、L1 判分聚合、
5 维 × ≥2 锚例存在性。全部无 LLM。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from nsc.db import init_schema
from nsc.judge.rubric_judge import (
    JudgeDecision,
    RubricJudge,
    load_anchors,
    load_rubric,
    merge_pairwise,
    parse_absolute,
    parse_pairwise,
)
from nsc.runtime.models import LLMResult, ModelRouter


class CannedRouter(ModelRouter):
    """固定输出路由：返回同一段 JSON，记录调用。"""

    def __init__(self, response: str) -> None:
        super().__init__(config_path=str(Path("config/models.yaml").resolve()))
        self.response = response
        self.calls: list[str] = []

    def resolve(self, tier: str) -> dict:
        return {"model": "stub-model"}

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        self.calls.append(messages[-1]["content"])
        return LLMResult(
            text=self.response,
            model_id="stub-model",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            wall_ms=1,
            trace_id="",
        )


class StubJudge:
    """确定性判官：按 a_text 前缀返回判定。用于校准端到端。"""

    judge_ver = "stub"

    def __init__(self) -> None:
        self.router = SimpleNamespace(resolve=lambda tier: {"model": "stub-model"})

    def judge_pair(self, dimension, context, a, b, *, seed=1):
        if a.startswith("AGREE-B"):
            return (
                JudgeDecision(winner="b", margin=2, cited_spans=["x"], rationale="ok"),
                JudgeDecision(winner="a", margin=2, cited_spans=["x"]),
                JudgeDecision(winner="b", margin=2, cited_spans=["x"]),
            )
        if a.startswith("TIE-"):
            return (
                JudgeDecision(winner="a", margin=1, cited_spans=["x"]),
                JudgeDecision(winner="a", margin=1, cited_spans=["x"]),
                JudgeDecision(winner="tie", rationale="两次相反"),
            )
        return (
            JudgeDecision(invalid=True, rationale="no cite"),
            JudgeDecision(invalid=True, rationale="no cite"),
            JudgeDecision(invalid=True, rationale="no cite"),
        )

    def judge_absolute(self, dimension, context, text, *, seed=1):
        from nsc.judge.rubric_judge import JudgeScore

        return JudgeScore(score=4.0, cited_spans=["x"])


def _calib_db(tmp_path: Path) -> Path:
    db = tmp_path / "calib.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.execute(
        """INSERT INTO cases(case_id,brand_id,profile_id,industry,title,source,status,created_at)
           VALUES ('case:1','demo_tea','short_drama_v1','beverage','t','client','draft','2026-01-01')"""
    )
    conn.execute(
        """INSERT INTO feedback(feedback_id,case_id,target_node_id,anchor_level,anchor_conf,
                                dimension,verdict,severity,confirmed_by,created_at)
           VALUES ('f1','case:1',NULL,'bookmark',1.0,'dialogue','revise',3,'huang','2026-01-01')"""
    )
    conn.execute(
        """INSERT INTO revision_pairs(pair_id,feedback_id,unit_kind,context_json,before_text,after_text,dimension)
           VALUES ('rp1','f1','dialogue_block','{}','AGREE-B 旧','AGREE-B 新','dialogue')"""
    )
    conn.execute(
        """INSERT INTO preference_pairs(pair_id,case_id,unit_kind,a_text,b_text,context_json,human_pref,dimension,origin)
           VALUES ('pp1','case:1','dialogue_block','TIE- a','TIE- b','{}','a','dialogue','regeneration'),
                  ('pp2','case:1','dialogue_block','INVALID- a','INVALID- b','{}','b','dialogue','regeneration')"""
    )
    conn.execute(
        """INSERT INTO judge_calibration(item_id,pair_id,dimension,human_verdict,human_score,source,created_at)
           VALUES ('jc1','pp1','dialogue','b',4,'preference','2026-01-01'),
                  ('jc2','pp2','dialogue','b',2,'preference','2026-01-01')"""
    )
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------- 解析 / 校验
def test_parse_pairwise_ok():
    d = parse_pairwise(
        '{"winner":"b","margin":2,"rationale":"更自然","cited_spans":["台词"],"invalid":false}'
    )
    assert d.winner == "b"
    assert d.margin == 2
    assert d.cited_spans == ["台词"]
    assert d.invalid is False


def test_parse_pairwise_empty_citation_invalid():
    d = parse_pairwise('{"winner":"a","cited_spans":[]}')
    assert d.invalid is True  # 无引用 span → 判定无效（协议 §3）


def test_parse_pairwise_garbage_invalid():
    d = parse_pairwise("不是 JSON")
    assert d.invalid is True


def test_parse_absolute_clamps():
    assert parse_absolute('{"score":9,"cited_spans":["x"]}').score == 5.0
    assert parse_absolute('{"score":0,"cited_spans":["x"]}').score == 1.0
    assert parse_absolute('{"score":4.5,"cited_spans":["x"]}').score == 4.5


# ---------------------------------------------------------------- swap / 归并
def test_merge_pairwise_contradiction_is_tie():
    # 调用1：(A,B) winner a → 原始 a；调用2：(B,A) winner a → 原始 b。相反 → tie
    resolved = merge_pairwise(
        JudgeDecision(winner="a", cited_spans=["x"]),
        JudgeDecision(winner="a", cited_spans=["x"]),
    )
    assert resolved.winner == "tie"


def test_merge_pairwise_agree():
    resolved = merge_pairwise(
        JudgeDecision(winner="a", cited_spans=["x"]),
        JudgeDecision(winner="b", cited_spans=["x"]),
    )
    assert resolved.winner == "a"


def test_merge_pairwise_single_invalid_fallback():
    resolved = merge_pairwise(
        JudgeDecision(winner="a", cited_spans=["x"]), JudgeDecision(invalid=True)
    )
    assert resolved.winner == "a"


def test_judge_pair_swap_contradiction_via_canned():
    """真实 RubricJudge + 固定"b"输出：两次调用方向相反 → 归并成 tie（位置偏置消解）。"""
    j = RubricJudge(
        router=CannedRouter('{"winner":"b","margin":2,"rationale":"x","cited_spans":["a"]}')
    )
    call1, call2, resolved = j.judge_pair("naturalness", "ctx", "A", "B")
    assert call1.winner == "b"  # 顺序 (A,B) → 原始 b
    assert call2.winner == "b"  # 顺序 (B,A) → 原始 a
    assert resolved.winner == "tie"


def test_rubric_judge_builds_prompt_with_anchors():
    j = RubricJudge(router=CannedRouter("{}"))
    msgs = j._pairwise_messages("naturalness", "ctx", "A", "B")
    assert msgs[0]["role"] == "system"
    assert "台词自然度" in msgs[0]["content"]
    assert "锚例" in msgs[0]["content"] or "参考锚例" in msgs[0]["content"]
    assert "【B】" in msgs[1]["content"]


# ---------------------------------------------------------------- 锚例资产
def test_all_dimensions_have_anchors():
    rubric = load_rubric()
    assert len(rubric["dimensions"]) >= 5
    for dim_id, _dim in rubric["dimensions"].items():
        anchors = load_anchors(dim_id)
        assert len(anchors) >= 2, f"{dim_id} 锚例不足 2 对"
        scores = [int(a["score"]) for a in anchors]
        assert min(scores) <= 2, f"{dim_id} 缺低分锚（≤2）"
        assert 5 in scores, f"{dim_id} 缺满分锚（5）"
        assert all(a.get("why") for a in anchors), f"{dim_id} 锚例缺 why"


# ---------------------------------------------------------------- 指标（纯函数）
def test_cohen_kappa():
    from nsc.judge.calibration import cohen_kappa

    assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0
    assert cohen_kappa(["a", "b"], ["a", "a"]) == 0.0
    assert cohen_kappa([], []) == 0.0


def test_compute_metrics():
    from nsc.judge.calibration import PairwiseOutcome, compute_metrics

    outcomes = [
        PairwiseOutcome("dialogue", "b", "b", 0, 0),  # 一致，A 位未胜
        PairwiseOutcome("dialogue", "tie", "a", 1, 0),  # 不一致，A 位胜
        PairwiseOutcome("dialogue", "tie", "b", 0, 1),  # 不一致，invalid
    ]
    m = compute_metrics(outcomes, [(4, 4), (2, 4)], "t")
    assert m["n_items"] == 3
    assert m["pairwise_report"] == round(1 / 3, 3)
    assert m["invalid_rate"] == round(1 / 3, 3)
    assert m["position_bias"] == 0.167
    assert m["kappa"] == 0.0  # 人类 [4,2] vs 判官 [4,4]：一半一致


# ---------------------------------------------------------------- 门禁
def test_gate_enabled_respects_env(monkeypatch):
    from nsc.eval import gate as g

    monkeypatch.setenv("JUDGE_GATE_ENABLED", "0")
    assert g.gate_enabled() is False
    monkeypatch.setenv("JUDGE_GATE_ENABLED", "true")
    assert g.gate_enabled() is True
    monkeypatch.delenv("JUDGE_GATE_ENABLED")
    monkeypatch.setattr(g, "GATE_STATE_PATH", Path("/nonexistent/state.yml"))
    assert g.gate_enabled() is True  # 默认开


def test_gate_state_file_fallback(tmp_path, monkeypatch):
    from nsc.eval import gate as g

    state = tmp_path / "state.yml"
    state.write_text("judge_gate_enabled: false\n", "utf-8")
    monkeypatch.setattr(g, "GATE_STATE_PATH", state)
    monkeypatch.delenv("JUDGE_GATE_ENABLED", raising=False)
    assert g.gate_enabled() is False


def test_evaluate_calibration_thresholds():
    from nsc.eval.gate import evaluate_calibration

    good = {
        "n_items": 100,
        "pairwise_report": 0.8,
        "pairwise_gate": 0.8,
        "kappa": 0.7,
        "invalid_rate": 0.02,
        "position_bias": 0.05,
    }
    assert evaluate_calibration(good)["gate_ok"] is True
    bad = {**good, "kappa": 0.3}
    assert evaluate_calibration(bad)["gate_ok"] is False
    few = {**good, "n_items": 3}
    assert evaluate_calibration(few)["gate_ok"] is False  # <50 条不过闸


# ---------------------------------------------------------------- 校准端到端
def test_run_calibration_stub(tmp_path):
    from nsc.judge.calibration import run_calibration

    db = _calib_db(tmp_path)
    res = run_calibration(
        db=db,
        stub=StubJudge(),
        out=tmp_path / "calib.md",
        gate_state=tmp_path / "state.yml",
    )
    m = res["metrics"]
    assert m["n_items"] == 3
    assert m["pairwise_report"] == round(1 / 3, 3)
    assert m["invalid_rate"] == round(1 / 3, 3)
    assert m["kappa"] == 0.0
    assert res["gate"]["gate_ok"] is False  # 未过校准门槛 → 关闸

    report = Path(res["report"])
    assert report.exists()
    assert "门禁" in report.read_text("utf-8")

    state = yaml.safe_load(Path(res["gate_state"]).read_text("utf-8"))
    assert state["judge_gate_enabled"] is False

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT swapped, invalid, verdict FROM judge_scores").fetchall()
    finally:
        conn.close()
    assert len(rows) == 3 * 3  # 每对 3 行：正向 + swap + 归并
    swapped = [r for r in rows if r[0] == 1]
    assert len(swapped) == 3


def test_run_calibration_requires_judge(tmp_path):
    from nsc.judge.calibration import run_calibration

    db = _calib_db(tmp_path)
    with pytest.raises(ValueError):
        run_calibration(db=db, out=tmp_path / "x.md", gate_state=tmp_path / "s.yml")


# ---------------------------------------------------------------- L1 判分聚合
def test_aggregate_l1_weighted():
    from nsc.eval.l1 import aggregate_l1

    rubric = load_rubric()
    results = [
        {"dimension": "naturalness", "score": 5.0, "unit_kind": "line"},
        {"dimension": "hook_strength", "score": 3.0, "unit_kind": "beat"},
    ]
    agg = aggregate_l1(results, rubric)
    assert agg["aggregate"] == pytest.approx(4.111, abs=0.001)
    assert agg["per_dimension"]["naturalness"] == 5.0


def test_run_l1_judge_stub(tmp_path):
    from nsc.eval.l1 import run_l1_judge

    raw = {
        "episodes": [{"id": "e1", "title": "第一集", "logline": "素颜直播"}],
        "scenes": [{"id": "s1", "summary": "直播间对峙"}],
        "beats": [{"id": "b1", "summary": "关掉美颜"}],
    }
    judge = RubricJudge(router=CannedRouter('{"score":4.0,"rationale":"x","cited_spans":["台词"]}'))
    brief = tmp_path / "b.yaml"
    brief.write_text("profile: short_drama_v1\nbrand: demo_tea\n", "utf-8")
    report = run_l1_judge(
        briefs=[brief],
        compile_runner=lambda _b: raw,
        judge=judge,
        out_dir=tmp_path,
    )
    text = report.read_text("utf-8")
    assert "聚合分" in text
    assert "门禁" in text
    # 单位：episode(4 维适用)+scene(3 维)+beat(2 维)=9 判分
    assert "9" in text
