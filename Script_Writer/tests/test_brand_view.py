"""BM-009 产品名判定回归：派生（_brand_view）+ 覆盖感知匹配（contains_name_variant）。

真实压测（T-18 / ADR-0009）暴露：纯子串匹配把规范名"清野轻乳茶"里的合法子串
"轻乳茶"误判为误用。修复后：规范名内的出现不算违规，单独误用仍然拦。
"""

from __future__ import annotations

from nsc.checker.registry import contains_name_variant
from nsc.runtime.ir_io import _brand_view

CANON = ["清野轻乳茶"]
BAD = ["轻乳茶"]  # 别名 ⊂ 规范名


def test_brand_view_forbidden_derivation():
    brand = {
        "products": [
            {"name": "轻乳茶", "canonical_name": "清野轻乳茶", "aliases": ["轻乳茶"]},
        ]
    }
    view = _brand_view(brand)
    assert view["__canonical_names"] == CANON
    assert "轻乳茶" in view["__forbidden_name_variants"]
    # 无空格规范名不得把自己禁掉（去空格变体 == 自身时不进禁用集）
    assert "清野轻乳茶" not in view["__forbidden_name_variants"]


def test_name_variant_inside_canonical_ok():
    # 规范名原文出现：子串"轻乳茶"被规范名覆盖 → 不违规
    assert not contains_name_variant("那你试试清野轻乳茶，不额外加蔗糖。", BAD, CANON)
    assert not contains_name_variant("清野轻乳茶的杯身logo清晰可见", BAD, CANON)


def test_name_variant_standalone_fires():
    # 单独用别名（丢品牌前缀）→ 违规
    assert contains_name_variant("这杯轻乳茶真好喝。", BAD, CANON)
    # 规范名与误用并存：误用那一处仍要拦
    assert contains_name_variant("清野轻乳茶不错，这杯轻乳茶也便宜", BAD, CANON)


def test_name_variant_edge_cases():
    assert not contains_name_variant("", BAD, CANON)
    assert not contains_name_variant("随便说点什么", BAD, CANON)
    assert not contains_name_variant("这杯轻乳茶真好喝。", [], CANON)
    # canon 为空 → 无覆盖基准 → bad 出现即违规
    assert contains_name_variant("这杯轻乳茶真好喝。", BAD, [])
