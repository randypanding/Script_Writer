"""T-12 GEPA metric + feedback function 测试。

验收（WORK_ORDERS T-12 / gepa_metric.py 设计注释）断言：
① pred_name 路由生效（p3 的 feedback 不含 DLG-002）
② split="val" 时不泄漏 revised_text
③ 长度 ≤ budget
④ 有 block finding 时 score == 0.0
⑤ WEIGHTS 求和为 1
⑥ feedback 文本包含五节结构且 block 在第一节
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from nsc.optimize.gepa_metric import (
    FEEDBACK_BUDGET_CHARS,
    WEIGHTS,
    MetricParts,
    _aggregate,
    build_feedback,
    make_metric,
)
from nsc.optimize.structure_match import structure_match


@dataclass(frozen=True)
class FakeFinding:
    rule_id: str
    severity: str
    message: str
    fix_hint: str = ""
    domain: str = ""
    tags: tuple = ()


def _runner(findings, rate):
    return lambda pred: (findings, rate)


def _judge(scores):
    return lambda gold, pred: scores


def _mk_parts(
    *,
    structure_match: float = 0.8,
    checker: float = 1.0,
    rubric: float = 0.5,
    edit_distance: float | None = None,
    findings: list | None = None,
    rubric_detail: dict[str, float] | None = None,
    human_edits: list[dict] | None = None,
    notes: list[str] | None = None,
) -> MetricParts:
    return MetricParts(
        structure_match=structure_match,
        checker=checker,
        rubric=rubric,
        edit_distance=edit_distance,
        findings=findings or [],
        rubric_detail=rubric_detail or {},
        human_edits=human_edits or [],
        notes=notes or [],
    )


# ⑤ WEIGHTS 求和为 1
def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


# ④ 有 block finding 时 score == 0.0
def test_block_finding_forces_zero_score():
    parts = _mk_parts(findings=[FakeFinding("BM-001", "block", "植入超预算")])
    assert _aggregate(parts, has_edits=False) == 0.0


def test_score_in_range_without_block():
    parts = _mk_parts(structure_match=0.8, checker=0.9, rubric=0.6, edit_distance=0.5)
    s = _aggregate(parts, has_edits=True)
    assert 0.0 < s <= 1.0
    # 无 edits 时重新归一化，仍在范围内
    s2 = _aggregate(_mk_parts(edit_distance=None), has_edits=False)
    assert 0.0 < s2 <= 1.0


# ① pred_name 路由生效
def test_pred_name_routing_filters_dialogue_finding_for_p3():
    dlg_finding = FakeFinding(
        "DLG-002", "block", "台词太长超过 60 字", domain="dialogue", tags=("length",)
    )
    bm_finding = FakeFinding(
        "BM-001", "block", "品牌植入超过预算 2 处", domain="brand", tags=("density",)
    )
    parts = _mk_parts(findings=[dlg_finding, bm_finding])
    fb = build_feedback(parts, pred_name="p3_beatsheet", reveal_human_edits=False)
    # p3 的路由 check_domains=[structure, brand]、tags 含 density → 保留 BM-001，滤掉 DLG-002
    assert "BM-001" in fb
    assert "DLG-002" not in fb


def test_pred_name_routing_keeps_dialogue_for_p5():
    dlg_finding = FakeFinding(
        "DLG-002", "block", "台词太长超过 60 字", domain="dialogue", tags=("length",)
    )
    parts = _mk_parts(findings=[dlg_finding])
    fb = build_feedback(parts, pred_name="p5_dialogue", reveal_human_edits=False)
    assert "DLG-002" in fb


# ② valset 不泄漏 revised_text
def test_val_split_does_not_leak_revised_text():
    edits = [
        {"before": "原", "after": "机密的客户改后文本", "rationale": "r", "dimension": "placement"}
    ]
    parts = _mk_parts(human_edits=edits)
    fb_val = build_feedback(parts, pred_name="p2_arc", reveal_human_edits=False)
    assert "机密的客户改后文本" not in fb_val
    assert "【人类是怎么改的】" not in fb_val
    fb_train = build_feedback(parts, pred_name="p2_arc", reveal_human_edits=True)
    assert "机密的客户改后文本" in fb_train


def test_metric_val_does_not_leak():
    edits = [{"before": "原", "after": "机密改后XYZ", "rationale": "r", "dimension": "placement"}]
    gold = {"pass_name": "p2_arc", "beats_json": [], "human_edits": edits}
    pred = {"beats_json": []}
    metric = make_metric(split="val", check_runner=_runner([], 1.0), judge_enabled=False)
    out = metric(gold, pred, pred_name="p2_arc")
    assert "机密改后XYZ" not in out.feedback


# ③ 长度 ≤ budget
def test_feedback_within_budget():
    findings = [
        FakeFinding(f"R{i:03d}", "block", "很长的诊断信息" * 30, domain="brand") for i in range(10)
    ]
    edits = [
        {"before": "原" * 50, "after": "改" * 50, "rationale": "r" * 50, "dimension": "placement"}
        for _ in range(5)
    ]
    parts = _mk_parts(
        findings=findings,
        human_edits=edits,
        rubric_detail={"placement_integration": 0.2},
        notes=["做得好的地方"],
    )
    fb = build_feedback(
        parts, pred_name="p3_beatsheet", reveal_human_edits=True, budget=FEEDBACK_BUDGET_CHARS
    )
    assert len(fb) <= FEEDBACK_BUDGET_CHARS


# ⑥ 五节结构且 block 在第一节
def test_feedback_five_sections_and_block_first():
    findings = [
        FakeFinding("BM-001", "block", "植入超预算", domain="brand", tags=("density",)),
        FakeFinding("STR-007", "warn", "节奏偏慢", domain="structure", tags=("pacing",)),
    ]
    parts = _mk_parts(
        findings=findings,
        human_edits=[{"before": "a", "after": "b", "rationale": "r", "dimension": "structural"}],
        rubric_detail={"hook_strength": 0.3},
        notes=["hook 起手有具体冲突"],
    )
    fb = build_feedback(parts, pred_name="p3_beatsheet", reveal_human_edits=True)
    assert fb.startswith("【必须修正】")
    for section in (
        "【必须修正】",
        "【人类是怎么改的】",
        "【判官打分最低的维度】",
        "【建议】",
        "【做对了的地方（保持）】",
    ):
        assert section in fb
    # block 节在最前
    assert fb.index("【必须修正】") < fb.index("【人类是怎么改的】")


# ---------------------------------------------------------------- structure_match
def test_structure_match_p3_identical_is_one():
    g = {
        "beats_json": [
            {"beat_kind": "hook"},
            {"beat_kind": "brand_moment"},
            {"beat_kind": "cliffhanger"},
        ],
        "setup_payoffs_json": [{"setup": "a", "payoff": "b"}],
    }
    assert structure_match("p3_beatsheet", g, g) == pytest.approx(1.0)


def test_structure_match_p3_detects_hook_misplacement():
    g = {
        "beats_json": [{"beat_kind": "hook"}, {"beat_kind": "setup"}],
        "setup_payoffs_json": [{"a": 1}],
    }
    p = {
        "beats_json": [{"beat_kind": "setup"}, {"beat_kind": "hook"}],
        "setup_payoffs_json": [{"a": 1}],
    }
    assert structure_match("p3_beatsheet", g, p) < 1.0


def test_structure_match_p5_must_include_line():
    g = {"lines_json": [{"character_id": "c1", "text": "必提台词原文", "is_brand_line": True}]}
    p_hit = {"lines_json": [{"character_id": "c1", "text": "必提台词原文"}]}
    p_miss = {"lines_json": [{"character_id": "c1", "text": "完全不同的东西"}]}
    assert structure_match("p5_dialogue", g, p_hit) > structure_match("p5_dialogue", g, p_miss)


def test_structure_match_unknown_pass_generic():
    g = {"season_arc": "整季弧线"}
    assert structure_match("p2_arc", g, g) == pytest.approx(1.0)
    assert 0.0 <= structure_match("p2_arc", g, {"season_arc": "别的"}) < 1.0
