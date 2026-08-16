"""IR 不变量的可执行形态。纯函数，无 IO，无 LLM。

约定：每个 inv_* 返回 list[Violation]（空 = 通过）。
这些是 L0 的一部分，但与 spec/checks/*.yaml 的区别是：
  - invariants.py = **结构完整性**（IR 本身是否是合法的图），与 Profile 无关或仅弱相关
  - spec/checks/*.yaml = **叙事/品牌/合规约束**（图合法但内容不合规）
新增业务约束一律去 spec/checks/，不要往这里加。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .container import NarrativeIR


@dataclass(frozen=True, slots=True)
class Violation:
    inv_id: str
    node_id: str | None
    message: str          # 必须是可直接喂给 GEPA 的诊断句，见 spec/checks/DSL.md §5
    severity: str = "block"


ALL_INVARIANTS: tuple[str, ...] = tuple(f"INV-{i:02d}" for i in range(1, 17))


def check_all(ir: NarrativeIR, profile: dict, stage: str = "final") -> list[Violation]:
    """stage ∈ {after_p3, after_p4, after_p5, after_p6, final}。
    早期 stage 跳过尚不适用的不变量（如 INV-07 需要 Line 存在）。
    映射表见 spec/passes/dep_graph.yaml::invariant_stages。
    """
    raise NotImplementedError("→ T-02")


# 逐条实现签名（agent 按此实现，勿改签名）
def inv_02(ir: NarrativeIR) -> list[Violation]: ...
def inv_03(ir: NarrativeIR) -> list[Violation]: ...
def inv_04(ir: NarrativeIR) -> list[Violation]: ...
def inv_05(ir: NarrativeIR) -> list[Violation]: ...
def inv_06(ir: NarrativeIR) -> list[Violation]: ...
def inv_07(ir: NarrativeIR) -> list[Violation]: ...
def inv_08(ir: NarrativeIR) -> list[Violation]: ...
def inv_09(ir: NarrativeIR, brand: dict) -> list[Violation]: ...
def inv_11(ir: NarrativeIR) -> list[Violation]: ...
def inv_12(ir: NarrativeIR) -> list[Violation]: ...
def inv_13(ir: NarrativeIR, profile: dict) -> list[Violation]: ...
def inv_14(ir: NarrativeIR) -> list[Violation]: ...
def inv_15(ir: NarrativeIR, profile: dict) -> list[Violation]: ...
def inv_16_id_stability(old: NarrativeIR, new: NarrativeIR) -> list[Violation]: ...