"""IR 不变量测试。这是"代码可丢弃"的验收面（D21 第 2 条）：
重写 src/ 之后，用同一套测试跑通，即等价。所以本文件**不得** import src/nsc 的内部实现细节，
只能 import spec.ir 与公开入口。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from spec.ir.container import NarrativeIR
from spec.ir.invariants import ALL_INVARIANTS, check_all


def test_all_invariants_have_implementation():
    """15+1 条不变量必须都有实现，不允许"文档写了代码没做"。"""
    import spec.ir.invariants as m

    missing = [
        i
        for i in ALL_INVARIANTS
        if not hasattr(m, f"inv_{i.split('-')[1]}") and i not in {"INV-01", "INV-10"}
    ]  # 这两条由 Pydantic 保证
    assert not missing, f"未实现的不变量：{missing}"


def test_golden_ir_passes_all(golden_ir, profiles):
    ir = NarrativeIR.model_validate(golden_ir)
    v = check_all(ir, profiles["short_drama_v1"], stage="final")
    assert v == [], f"黄金 IR 违反不变量：{v}"


@pytest.mark.parametrize(
    "inv", ["INV-03", "INV-05", "INV-06", "INV-07", "INV-08", "INV-12", "INV-15"]
)
def test_each_invariant_catches_its_break(golden_ir, profiles, inv):
    """对每条不变量，必须有一个"破坏它"的 fixture 并被抓到。
    fixture 放 tests/fixtures/broken/<INV-ID>.json。缺失 = 测试失败。"""
    import json
    from pathlib import Path

    p = Path(f"tests/fixtures/broken/{inv}.json")
    assert p.exists(), f"缺少破坏 {inv} 的 fixture：{p}"
    ir = NarrativeIR.model_validate(json.loads(p.read_text("utf-8")))
    v = check_all(ir, profiles["short_drama_v1"], stage="final")
    assert any(x.inv_id == inv for x in v), f"{inv} 未被抓到"


def test_id_stability(golden_ir):
    """INV-16：局部重编译必须保留未变节点的 ID。

    这是**最高优先级测试**。违反它 = 所有历史反馈失效 = 资产系统性损毁。
    """

    # 只改第 3 集的一句台词，其余集内容不变但 ID 被打乱
    pytest.skip("T-03 实现 merge_preserving_ids 后启用")


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=12))
def test_order_is_contiguous_property(n):
    """property-based：任意合法构造出的 IR，同 parent 下 order 必须 0..n-1 连续。"""
    pytest.skip("T-02：需要 IR 构造 strategy（tests/strategies.py）")
