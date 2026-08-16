"""资产层守卫的测试（守卫本身也要被测）。"""

from __future__ import annotations

from pathlib import Path


def test_every_spec_statement_is_reducible():
    """D2：spec/**/*.md 中的规范语句必须带 [[form:...]] 标记。"""
    from nsc.guards.spec_reduction import scan

    problems = scan(Path("spec"))
    assert problems == [], "以下语句缺少形态标记：\n" + "\n".join(map(str, problems))


def test_brand_mapping_complete():
    """spec/brand/mapping.md 中每一行的规则 ID 都必须存在。"""
    from nsc.guards.checks_schema import validate_brand_mapping

    assert validate_brand_mapping() == []


def test_canonical_rules_have_evidence():
    from nsc.guards.checks_schema import validate_rules

    assert validate_rules(level="L3") == []


def test_no_business_if_in_python():
    """AGENTS.md §2：禁止在 Python 里写业务规则。
    启发式：src/ 中出现 spec/checks 里已有规则的关键词组合即报警（人工白名单在 spec/BUDGETS.yaml）。"""
    from nsc.guards.budgets import scan_business_logic

    assert scan_business_logic() == []


def test_runtime_line_budget():
    from nsc.guards.budgets import line_counts

    counts = line_counts()
    assert counts["runtime+checker"] <= 1500, (
        f"手写运行时 {counts['runtime+checker']} 行 > 1500（D21）。把知识抽回 spec/。"
    )


def test_prompts_not_hand_edited():
    from nsc.guards.prompts_untouched import verify

    assert verify() == []


def test_canonical_rule_cap():
    import yaml

    n = len(list(Path("spec/rules/L3_canonical").glob("R3-*.yaml")))
    cap = yaml.safe_load(Path("spec/BUDGETS.yaml").read_text("utf-8"))["max_canonical_rules"]
    assert n <= cap, f"canonical 规则 {n} 条 > 上限 {cap}（PROMOTION.md 反膨胀）"
