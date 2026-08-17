"""plateau 停止判据（T-41，规格源：inkos runner.ts 的 plateau 检测）。

可复用纯函数：输入逐轮归一化指标历史，输出 (是否停止, 原因)。
- 轮数 ≥ max_cycles → 强制停（"max_cycles"，优先于 plateau）
- 轮数 ≥ min_cycles 且最近两轮 |Δ| < delta → 平台停（"plateau"）
供 gepa_run 的迭代循环与 revision 循环共用。
"""

from __future__ import annotations


def should_stop(
    history: list[float],
    min_cycles: int = 3,
    max_cycles: int = 6,
    delta: float = 0.03,
) -> tuple[bool, str]:
    """判定优化循环是否停止。history 为逐轮归一化指标（越长越新）。"""
    if len(history) >= max_cycles:
        return True, "max_cycles"
    if len(history) >= max(min_cycles, 2) and abs(history[-1] - history[-2]) < delta:
        return True, "plateau"
    return False, ""
