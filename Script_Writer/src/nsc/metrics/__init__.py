"""指标仪表盘（D22 北极星 + D23 六个数，T-20）。

纯确定性计算，无 LLM：输入 cases.db + out/eval/ab_retrieval.json，
输出 metrics_weekly 一行 + docs/metrics/latest.md。
北极星 = 结构性编辑率（structural 类编辑数 / 交付集数，D11 八类分解，混算即失败）。
"""

from __future__ import annotations

from nsc.metrics.collect import compute_weekly, weekly_report

__all__ = ["compute_weekly", "weekly_report"]
