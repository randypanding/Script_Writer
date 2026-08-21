"""revisionGate 三档门禁（T-32，规格源：inkos runner.ts revisionGate）。

比较修订前后的 checker 计数与判官分：
- did_not_worsen：block/warn 均不增，且（任一 judge_score 缺失 或 分数不降）。
- strict：不变差 且 至少一项真改善（block 降 / warn 降 / 判官分严格提升）。
- lenient：不变差即可；always：无条件放行（用于人工兜底或 A/B 观测）。
"""

from __future__ import annotations

from dataclasses import dataclass

MODES = ("strict", "lenient", "always")


@dataclass(frozen=True)
class Counts:
    """一次修订前后的检查计数快照（judge_score 可缺失）。"""

    block: int = 0
    warn: int = 0
    info: int = 0
    judge_score: float | None = None


def decide(before: Counts, after: Counts, mode: str = "strict") -> bool:
    """判定修订是否可接受。未知 mode 抛 ValueError。"""
    if mode not in MODES:
        raise ValueError(f"未知 revisionGate mode: {mode!r}（可选 {MODES}）")
    if mode == "always":
        return True
    judge_ok = (
        before.judge_score is None
        or after.judge_score is None
        or after.judge_score >= before.judge_score
    )
    did_not_worsen = after.block <= before.block and after.warn <= before.warn and judge_ok
    if not did_not_worsen:
        return False
    if mode == "lenient":
        return True
    # strict：要求至少一项真改善
    judge_improved = (
        before.judge_score is not None
        and after.judge_score is not None
        and after.judge_score > before.judge_score
    )
    return after.block < before.block or after.warn < before.warn or judge_improved
