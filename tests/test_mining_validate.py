"""T-15 规则验证与退役测试。

验收（WORK_ORDERS T-15）：
- 留出集验证协议在合成数据上可复现
- 120 条上限（max_canonical_rules）可检测
- taste 类只能产出 scope: client（兜底强制）
- hit_count==0 且超 90 天 → 退役为 deprecated
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from nsc.mining.retire import enforce_taste_scope, retire, should_retire
from nsc.mining.validate import validate_candidates, validate_check_rule


def _l1_rule(rid: str, statement: str, dimension: str = "placement") -> dict:
    return {
        "id": rid,
        "level": "L1",
        "statement": statement,
        "scope": {"kind": "global"},
        "form": "check",
        "dimension": dimension,
        "evidence_ids": ["case:0001", "case:0002", "case:0003"],
        "created_at": "2026-01-01T00:00:00Z",
        "extra": {"counterexamples": "x", "conflicts_with": "", "check_draft_yaml": ""},
    }


def _write_l1(l1_dir: Path, rule: dict) -> Path:
    l1_dir.mkdir(parents=True, exist_ok=True)
    p = l1_dir / f"{rule['id']}.yaml"
    p.write_text(yaml.safe_dump(rule, allow_unicode=True, sort_keys=False), "utf-8")
    return p


# ---------------------------------------------------------------- validate
def test_validate_check_rule_passes_on_good_holdout(tmp_path):
    rule = _l1_rule("R1-0001", "植入卖点应由动作承载不得宣读参数")
    holdout = [
        {
            "before": "这款茶热量只有三分之一",
            "after": "（推过去）不加糖",
            "rationale_nl": "宣读参数",
            "applies": True,
        },
        {"before": "参数宣称", "after": "动作", "rationale_nl": "宣读参数太假", "applies": True},
        {"before": "无关", "after": "无关", "rationale_nl": "别的问题", "applies": False},
    ]
    res = validate_check_rule(rule, holdout)
    assert res.passed
    assert res.precision >= 0.8
    assert res.recall >= 0.3


def test_validate_check_rule_fails_on_bad_holdout():
    rule = _l1_rule("R1-0002", "植入卖点应由动作承载不得宣读参数")
    holdout = [
        {"before": "a", "after": "b", "rationale_nl": "完全不相关", "applies": True},
        {"before": "c", "after": "d", "rationale_nl": "也不相关", "applies": True},
    ]
    res = validate_check_rule(rule, holdout)
    assert not res.passed
    assert res.recall < 0.3


def test_validate_candidates_promotes_passing_to_l2(tmp_path):
    l1 = tmp_path / "L1_candidates"
    l2 = tmp_path / "L2_validated"
    _write_l1(l1, _l1_rule("R1-0001", "植入卖点应由动作承载不得宣读参数"))
    holdout = {
        "R1-0001": [
            {
                "before": "宣读参数",
                "after": "动作",
                "rationale_nl": "宣读参数",
                "applies": True,
                "case_id": "case:0009",
            },
            {
                "before": "宣读参数",
                "after": "动作",
                "rationale_nl": "宣读参数",
                "applies": True,
                "case_id": "case:0010",
            },
        ]
    }
    results = validate_candidates(holdout, l1_dir=l1, l2_dir=l2, report_dir=tmp_path / "rep")
    assert results[0].passed
    assert not (l1 / "R1-0001.yaml").exists()  # 移走
    promoted = yaml.safe_load((l2 / "R1-0001.yaml").read_text())
    assert promoted["level"] == "L2"
    assert promoted["validation_report"]
    assert "case:0009" in promoted["evidence_ids"]


def test_validate_candidates_keeps_failing_in_l1(tmp_path):
    l1 = tmp_path / "L1_candidates"
    l2 = tmp_path / "L2_validated"
    _write_l1(l1, _l1_rule("R1-0003", "植入卖点应由动作承载不得宣读参数"))
    holdout = {"R1-0003": [{"before": "a", "after": "b", "rationale_nl": "无关", "applies": True}]}
    results = validate_candidates(holdout, l1_dir=l1, l2_dir=l2, report_dir=tmp_path / "rep")
    assert not results[0].passed
    assert (l1 / "R1-0003.yaml").exists()  # 未晋升
    assert not (l2 / "R1-0003.yaml").exists()


# ---------------------------------------------------------------- retire
def _l3_rule(rid: str, *, hit_count: int, days_old: int, dimension: str = "placement") -> dict:
    ts = (datetime.now(UTC) - timedelta(days=days_old)).isoformat()
    return {
        "id": rid,
        "level": "L3",
        "statement": "某条规则陈述足够长",
        "scope": {"kind": "global"},
        "form": "check",
        "dimension": dimension,
        "target": f"spec/checks/brand/{rid}.yaml",
        "evidence_ids": ["case:0001", "case:0002", "case:0003"],
        "hit_count": hit_count,
        "created_at": ts,
        "last_fired_at": None,
        "validation_report": "x",
    }


def test_should_retire_zero_hits_and_old():
    assert should_retire(_l3_rule("R3-0001", hit_count=0, days_old=120))
    assert not should_retire(_l3_rule("R3-0002", hit_count=0, days_old=30))  # 太新
    assert not should_retire(_l3_rule("R3-0003", hit_count=5, days_old=120))  # 有命中


def test_retire_marks_deprecated(tmp_path):
    l3 = tmp_path / "L3_canonical"
    l3.mkdir(parents=True)
    old = _l3_rule("R3-0001", hit_count=0, days_old=120)
    fresh = _l3_rule("R3-0002", hit_count=3, days_old=120)
    (l3 / "R3-0001.yaml").write_text(yaml.safe_dump(old, allow_unicode=True), "utf-8")
    (l3 / "R3-0002.yaml").write_text(yaml.safe_dump(fresh, allow_unicode=True), "utf-8")
    res = retire(l3_dir=l3, budgets=tmp_path / "BUDGETS.yaml")
    assert res.retired == ["R3-0001"]
    assert res.kept == ["R3-0002"]
    assert yaml.safe_load((l3 / "R3-0001.yaml").read_text())["level"] == "deprecated"
    assert yaml.safe_load((l3 / "R3-0002.yaml").read_text())["level"] == "L3"


def test_retire_detects_over_budget(tmp_path):
    l3 = tmp_path / "L3_canonical"
    l3.mkdir(parents=True)
    for i in range(3):
        (l3 / f"R3-{i:04d}.yaml").write_text(
            yaml.safe_dump(_l3_rule(f"R3-{i:04d}", hit_count=1, days_old=1), allow_unicode=True),
            "utf-8",
        )
    budgets = tmp_path / "BUDGETS.yaml"
    budgets.write_text("max_canonical_rules: 2\n", "utf-8")
    res = retire(l3_dir=l3, budgets=budgets)
    assert res.over_budget
    assert res.canonical_count == 3
    assert res.max_canonical == 2


def test_enforce_taste_scope_forces_client():
    rule = {"dimension": "taste", "scope": {"kind": "global"}}
    out = enforce_taste_scope(rule)
    assert out["scope"]["kind"] == "client"
    # 非 taste 不动
    other = {"dimension": "placement", "scope": {"kind": "global"}}
    assert enforce_taste_scope(other)["scope"]["kind"] == "global"
