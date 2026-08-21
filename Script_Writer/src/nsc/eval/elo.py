"""Elo 锦标赛（T-40 / ADR-0014）：章节间相对排序，仅作分析、不进门禁。

参数为 ADR-0014 固定的机制常量（初始 1500、K=32、4 轮 Swiss、无平局、每章截断
3000 字），不属于判官校准阈值，故不入 eval/thresholds.yaml。全部纯函数：
judge_fn 由调用方注入（生产走判官路由，测试走 fake），本模块不碰 LLM。
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

#: 每章文本截断长度（ADR-0014：判官输入上限 3000 字）。
MAX_CHARS = 3000
#: 初始 Elo（ADR-0014）。
INITIAL_ELO = 1500.0

#: judge_fn(a_text, b_text) -> float（约定返回 1.0/0.0，无平局）。
JudgeFn = Callable[[str, str], float]


def pair_swiss(elo: dict[str, float], round_no: int) -> list[tuple[str, str]]:
    """按 Elo 降序相邻两两配对（同一轮内每队只出现一次）。

    稳定排序：同分保持 dict 插入序（由 run_tournament 用 seed 洗牌控制）。
    奇数参赛者轮空：从底部按 round_no 轮转，避免同一队每轮坐冷板凳。
    """
    order = sorted(elo, key=lambda x: -elo[x])
    if len(order) % 2 == 1 and order:
        order.pop(len(order) - 1 - (round_no % len(order)))
    return [(order[i], order[i + 1]) for i in range(0, len(order) - 1, 2)]


def update_elo(elo: dict[str, float], a: str, b: str, score_a: float, k: int = 32) -> None:
    """标准 Elo（就地更新）：exp_a = 1/(1+10**((elo_b-elo_a)/400))；b 侧对称、零和。"""
    exp_a = 1.0 / (1.0 + 10.0 ** ((elo[b] - elo[a]) / 400.0))
    delta = k * (score_a - exp_a)
    elo[a] += delta
    elo[b] -= delta


def run_tournament(
    chapters: list[dict],
    judge_fn: JudgeFn,
    rounds: int = 4,
    k: int = 32,
    seed: int = 0,
) -> dict[str, Any]:
    """Swiss Elo 锦标赛：chapters = [{id, text}]，返回 {rankings, rounds_log}。

    无平局：judge_fn 返回值规约为二值（>0.5 记 a 胜，否则 b 胜）。
    seed 决定初始同分（全员 1500）时的配对顺序 → 同 seed 同结果。
    """
    rng = random.Random(seed)
    ids = [str(c["id"]) for c in chapters]
    rng.shuffle(ids)
    elo = {i: INITIAL_ELO for i in ids}
    texts = {str(c["id"]): str(c["text"])[:MAX_CHARS] for c in chapters}
    wins = {i: 0 for i in ids}
    losses = {i: 0 for i in ids}
    rounds_log: list[list[dict[str, Any]]] = []
    for round_no in range(rounds):
        matches: list[dict[str, Any]] = []
        for a, b in pair_swiss(elo, round_no):
            score_a = 1.0 if float(judge_fn(texts[a], texts[b])) > 0.5 else 0.0
            winner, loser = (a, b) if score_a > 0.5 else (b, a)
            wins[winner] += 1
            losses[loser] += 1
            before_a, before_b = elo[a], elo[b]
            update_elo(elo, a, b, score_a, k=k)
            matches.append(
                {
                    "round": round_no,
                    "a": a,
                    "b": b,
                    "winner": winner,
                    "elo_a_before": round(before_a, 1),
                    "elo_b_before": round(before_b, 1),
                    "elo_a_after": round(elo[a], 1),
                    "elo_b_after": round(elo[b], 1),
                }
            )
        rounds_log.append(matches)
    order = sorted(ids, key=lambda i: (-elo[i], -wins[i], i))
    rankings = [
        {"id": i, "elo": round(elo[i], 1), "rank": n + 1, "wins": wins[i], "losses": losses[i]}
        for n, i in enumerate(order)
    ]
    return {"rankings": rankings, "rounds_log": rounds_log}
