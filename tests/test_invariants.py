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
    做法：把黄金 IR 全部节点换成新 ULID（模拟"重新生成"），只改一句台词，
    merge_preserving_ids 之后，除那句台词外所有节点必须恢复原 ID。
    """
    import copy

    from ulid import ULID

    from nsc.runtime.ir_io import merge_preserving_ids
    from spec.ir.invariants import inv_16_id_stability

    old = NarrativeIR.model_validate(golden_ir)
    new_raw = copy.deepcopy(golden_ir)

    # 改第 3 集的一句台词内容，其余内容逐字保留
    changed = new_raw["lines"][40]
    changed["text"] = changed["text"] + "（改）"
    changed_id_old = changed["id"]

    # 打乱全部节点 ID（包括 parent 链接一起换），模拟一次全新生成
    id_map: dict[str, str] = {}

    def remap(node_id: str | None) -> str | None:
        if node_id is None:
            return None
        if node_id not in id_map:
            id_map[node_id] = str(ULID())
        return id_map[node_id]

    for table in ("project",):
        new_raw[table]["id"] = remap(new_raw[table]["id"])
    for table in ("seasons", "episodes", "scenes", "beats", "lines"):
        for n in new_raw[table]:
            n["id"] = remap(n["id"])
            n["parent_id"] = remap(n["parent_id"])
    new = NarrativeIR.model_validate(new_raw)
    assert inv_16_id_stability(old, new)  # 未合并前必然违规

    merged = merge_preserving_ids(old, new)
    violations = inv_16_id_stability(old, merged)
    assert violations == [], f"INV-16 被违反：{[v.message for v in violations][:3]}"
    # 被改的那句台词允许拿到新 ID，但其 parent 等未变节点 ID 必须已恢复
    merged_line = next(ln for ln in merged.lines if ln.text.endswith("（改）"))
    assert merged_line.id != changed_id_old or merged_line.id == id_map[changed_id_old]


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=12))
def test_order_is_contiguous_property(n):
    """property-based：任意合法构造出的 IR，同 parent 下 order 必须 0..n-1 连续。"""
    from tests.strategies import build_minimal_ir

    ir = NarrativeIR.model_validate(build_minimal_ir(n_episodes=n))
    violations = check_all(
        ir, {"layers": {"season": False}, "duration_tolerance": 0.5}, stage="final"
    )
    inv03 = [v for v in violations if v.inv_id == "INV-03"]
    assert inv03 == [], f"order 不连续：{[v.message for v in inv03][:3]}"
