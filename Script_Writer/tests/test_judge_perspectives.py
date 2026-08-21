"""T-39 验收：三视角判官（ADR-0014）。

覆盖：三视角注记解析（含/不含/类型异常）、JudgeScore/JudgeDecision 透传、
disagreement 标志、指令内嵌三视角要求、成对归并仅透传、聚合分不变、
校准报告视角分歧统计。全部无 LLM（CannedRouter 固定输出，照 tests/test_judge.py）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nsc.db import init_schema
from nsc.judge.rubric_judge import (
    JudgeDecision,
    JudgeScore,
    RubricJudge,
    load_rubric,
    merge_pairwise,
    parse_absolute,
    parse_pairwise,
)
from nsc.runtime.models import LLMResult, ModelRouter


class CannedRouter(ModelRouter):
    """固定输出路由：返回同一段 JSON，记录 system 指令。"""

    def __init__(self, response: str) -> None:
        super().__init__(config_path=str(Path("config/models.yaml").resolve()))
        self.response = response
        self.calls: list[str] = []

    def resolve(self, tier: str) -> dict:
        return {"model": "stub-model"}

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        self.calls.append(messages[0]["content"])
        return LLMResult(
            text=self.response,
            model_id="stub-model",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            wall_ms=1,
            trace_id="",
        )


_WITH_PERSPECTIVES = (
    '{"score": 4.0, "rationale": "ok", "cited_spans": ["台词"], "invalid": false, '
    '"perspectives": {"editor": {"note": "句法干净，声音一致"}, '
    '"genre_reader": {"note": "钩子快，翻页欲强"}, '
    '"lay_reader": {"note": "情绪诚实，不煽情"}}, '
    '"perspective_disagreement": true}'
)
_WITHOUT = '{"score": 3.5, "rationale": "ok", "cited_spans": ["台词"]}'


# ---------------------------------------------------------------- 解析（防御式）
def test_parse_absolute_with_perspectives():
    s = parse_absolute(_WITH_PERSPECTIVES)
    assert s.perspectives["editor"]["note"] == "句法干净，声音一致"
    assert s.perspectives["genre_reader"]["note"] == "钩子快，翻页欲强"
    assert s.perspectives["lay_reader"]["note"] == "情绪诚实，不煽情"
    assert s.perspective_disagreement is True
    assert s.score == 4.0
    assert s.invalid is False


def test_parse_absolute_without_perspectives():
    s = parse_absolute(_WITHOUT)
    assert s.perspectives == {}  # LLM 省略 → 空 dict，不失败
    assert s.perspective_disagreement is False
    assert s.invalid is False
    assert s.score == 3.5


def test_parse_absolute_perspectives_bad_type():
    s = parse_absolute('{"score": 4, "cited_spans": ["x"], "perspectives": ["不是dict"]}')
    assert s.perspectives == {}
    assert s.perspective_disagreement is False
    assert s.invalid is False


def test_parse_absolute_string_note_compat():
    s = parse_absolute(
        '{"score": 4, "cited_spans": ["x"], '
        '"perspectives": {"editor": "直接给了字符串", "bogus": {"note": "忽略未知视角"}}}}'
    )
    assert s.perspectives == {"editor": {"note": "直接给了字符串"}}


def test_parse_pairwise_with_perspectives():
    d = parse_pairwise(
        '{"winner":"a","margin":2,"cited_spans":["台词"],'
        '"perspectives":{"editor":{"note":"A 更利落"},'
        '"genre_reader":{"note":"B 节奏拖"},'
        '"lay_reader":{"note":"A 像人话"}}}'
    )
    assert d.winner == "a"
    assert set(d.perspectives) == {"editor", "genre_reader", "lay_reader"}


def test_parse_pairwise_without_perspectives():
    d = parse_pairwise('{"winner":"b","margin":1,"cited_spans":["x"]}')
    assert d.perspectives == {}
    assert d.perspective_disagreement is False


# ---------------------------------------------------------------- 指令内嵌三视角
def test_absolute_prompt_embeds_three_perspectives():
    j = RubricJudge(router=CannedRouter("{}"))
    system = j._absolute_messages("naturalness", "ctx", "文本")[0]["content"]
    assert "编辑" in system
    assert "类型读者" in system
    assert "普通读者" in system
    assert "perspectives" in system
    assert "perspective_disagreement" in system


def test_pairwise_prompt_embeds_three_perspectives():
    j = RubricJudge(router=CannedRouter("{}"))
    system = j._pairwise_messages("naturalness", "ctx", "A", "B")[0]["content"]
    assert "编辑" in system
    assert "类型读者" in system
    assert "普通读者" in system
    assert "perspective_disagreement" in system


# ---------------------------------------------------------------- 透传
def test_judge_absolute_perspectives_passthrough():
    j = RubricJudge(router=CannedRouter(_WITH_PERSPECTIVES))
    s = j.judge_absolute("naturalness", "ctx", "文本")
    assert s.score == 4.0
    assert s.perspectives["editor"]["note"] == "句法干净，声音一致"
    assert s.perspective_disagreement is True


def test_merge_pairwise_passthrough_perspectives():
    call1 = JudgeDecision(
        winner="a",
        cited_spans=["x"],
        perspectives={"editor": {"note": "好"}},
        perspective_disagreement=True,
    )
    call2 = JudgeDecision(winner="b", cited_spans=["x"])  # 省略 perspectives
    merged = merge_pairwise(call1, call2)
    assert merged.winner == "a"  # 归并逻辑不变
    assert merged.perspectives == {"editor": {"note": "好"}}  # 仅透传
    assert merged.perspective_disagreement is True


def test_merge_pairwise_fallback_to_call2_perspectives():
    call1 = JudgeDecision(winner="a", cited_spans=["x"])
    call2 = JudgeDecision(
        winner="b",
        cited_spans=["x"],
        perspectives={"lay_reader": {"note": "注记"}},
    )
    merged = merge_pairwise(call1, call2)
    assert merged.perspectives == {"lay_reader": {"note": "注记"}}
    assert merged.perspective_disagreement is False


# ---------------------------------------------------------------- 聚合不变
def test_aggregate_l1_unchanged_with_perspectives():
    from nsc.eval.l1 import aggregate_l1

    rubric = load_rubric()
    results = [
        {
            "dimension": "naturalness",
            "score": 5.0,
            "unit_kind": "line",
            "perspectives": {"editor": {"note": "n"}},
            "perspective_disagreement": True,
        },
        {
            "dimension": "hook_strength",
            "score": 3.0,
            "unit_kind": "beat",
            "perspectives": {},
            "perspective_disagreement": False,
        },
    ]
    agg = aggregate_l1(results, rubric)
    assert agg["aggregate"] == pytest.approx(4.111, abs=0.001)  # 与 test_judge.py 同值


def test_judge_units_carries_perspectives():
    from nsc.eval.l1 import judge_units

    j = RubricJudge(router=CannedRouter(_WITH_PERSPECTIVES))
    units = [{"kind": "chapter", "id": "c1", "text": "文本"}]
    rows = judge_units(units, j, j.rubric)
    assert rows
    for r in rows:
        assert r["perspectives"]["editor"]["note"] == "句法干净，声音一致"
        assert r["perspective_disagreement"] is True
        assert r["score"] == 4.0


# ---------------------------------------------------------------- 校准：视角分歧统计
def test_compute_metrics_perspective_stat():
    from nsc.judge.calibration import PairwiseOutcome, compute_metrics

    outcomes = [PairwiseOutcome("dialogue", "b", "b", 0, 0)]
    m = compute_metrics(outcomes, [], "t", perspective_flags=[True, False, False])
    assert m["n_perspectives"] == 3
    assert m["perspective_disagreement_rate"] == round(1 / 3, 3)


def test_compute_metrics_without_perspectives_zero():
    from nsc.judge.calibration import PairwiseOutcome, compute_metrics

    m = compute_metrics([PairwiseOutcome("dialogue", "a", "a", 0, 0)], [], "t")
    assert m["n_perspectives"] == 0
    assert m["perspective_disagreement_rate"] == 0.0


def test_render_report_includes_perspective_stat(tmp_path):
    from nsc.eval.gate import evaluate_calibration
    from nsc.judge.calibration import compute_metrics, render_report

    metrics = compute_metrics([], [], "t", perspective_flags=[True, False])
    ev = evaluate_calibration(metrics)
    out = render_report(metrics, ev, tmp_path / "r.md")
    text = out.read_text("utf-8")
    assert "视角分歧" in text
    assert "1/2" in text


class PerspectivesStubJudge:
    """带三视角注记的确定性判官：judge_absolute 全部自报分歧；成对 resolved 也带注记。"""

    judge_ver = "stub-persp"

    def __init__(self) -> None:
        from types import SimpleNamespace

        self.router = SimpleNamespace(resolve=lambda tier: {"model": "stub-model"})

    def judge_pair(self, dimension, context, a, b, *, seed=1):
        call1 = JudgeDecision(
            winner="b",
            margin=2,
            cited_spans=["x"],
            perspectives={"editor": {"note": "改后更利落"}, "lay_reader": {"note": "更真"}},
            perspective_disagreement=True,
        )
        call2 = JudgeDecision(winner="a", margin=2, cited_spans=["x"])
        resolved = merge_pairwise(call1, call2)
        return call1, call2, resolved

    def judge_absolute(self, dimension, context, text, *, seed=1):
        return JudgeScore(
            score=4.0,
            cited_spans=["x"],
            perspectives={"editor": {"note": "n"}, "genre_reader": {"note": "n"}},
            perspective_disagreement=True,
        )


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
           VALUES ('rp1','f1','dialogue_block','{}','旧稿','新稿','dialogue')"""
    )
    conn.commit()
    conn.close()
    return db


def test_run_calibration_counts_perspective_disagreement(tmp_path):
    from nsc.judge.calibration import run_calibration

    db = _calib_db(tmp_path)
    res = run_calibration(
        db=db,
        stub=PerspectivesStubJudge(),
        out=tmp_path / "calib.md",
        gate_state=tmp_path / "state.yml",
    )
    m = res["metrics"]
    # 一对成对（resolved 带注记）+ 一次绝对评分（人类分缺失时不触发，但成对侧已计入）
    assert m["n_perspectives"] >= 1
    assert m["perspective_disagreement_rate"] == 1.0
    text = Path(res["report"]).read_text("utf-8")
    assert "视角分歧" in text
