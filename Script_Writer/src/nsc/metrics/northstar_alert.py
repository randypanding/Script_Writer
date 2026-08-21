"""北极星趋势告警（D22）：结构性编辑率必须单调下降。

从 `eval/thresholds.yaml::northstar` 读告警配置：
- window_weeks（默认 8）：滑动的周数
- alert_on_slope_above（默认 0.0）：8 周线性回归斜率超过该值即告警（非上升 = 斜率 ≤ 0）

用法：`python -m nsc.metrics.northstar_alert --window 8`
退出码 0 = 正常；1 = 触发告警（CI 变红 = 提醒）。
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

_THRESHOLDS = Path("eval/thresholds.yaml")


def _config() -> dict:
    import yaml

    t = yaml.safe_load(_THRESHOLDS.read_text("utf-8")) or {}
    return t.get("northstar", {}) or {}


def _slope(values: list[float]) -> float:
    """最小二乘斜率：结构性编辑率随周数的变化。正值 = 上升 = 恶化。"""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values, strict=True))
    den = sum((x - x_mean) ** 2 for x in xs)
    return num / den if den else 0.0


def alert(
    db_path: str = "cases/cases.db",
    *,
    window: int | None = None,
    slope_threshold: float | None = None,
) -> dict:
    """检查结构性编辑率的 8 周趋势。返回 {ok, slope, window, n, alert, message}。"""
    cfg = _config()
    window = window or int(cfg.get("window_weeks", 8))
    slope_threshold = (
        float(slope_threshold)
        if slope_threshold is not None
        else float(cfg.get("alert_on_slope_above", 0.0))
    )
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT week, structural_edit_rate FROM metrics_weekly ORDER BY week DESC LIMIT ?",
            (window,),
        ).fetchall()
    finally:
        conn.close()
    weeks = [str(r[0]) for r in rows][::-1]
    rates = [float(r[1]) for r in rows][::-1]
    n = len(rates)
    if n < 2:
        return {
            "ok": True,
            "alert": False,
            "slope": 0.0,
            "window": window,
            "n": n,
            "message": f"历史数据不足（{n} 周 < 2），暂不告警",
        }
    s = _slope(rates)
    fired = s > slope_threshold
    return {
        "ok": not fired,
        "alert": fired,
        "slope": round(s, 5),
        "window": window,
        "n": n,
        "weeks": weeks,
        "message": (
            f"结构性编辑率斜率 {s:.5f} > {slope_threshold}，趋势上升 → 告警"
            if fired
            else f"结构性编辑率斜率 {s:.5f} ≤ {slope_threshold}，趋势正常"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="北极星趋势告警（D22）")
    ap.add_argument("--db", default="cases/cases.db")
    ap.add_argument(
        "--window", type=int, default=None, help="滑动周数（默认取 eval/thresholds.yaml）"
    )
    args = ap.parse_args(argv)
    res = alert(args.db, window=args.window)
    print(res["message"])
    if not res["ok"] and not res["alert"] and res.get("weeks"):
        print(f"最近 {res['window']} 周：{res['weeks']}")
    return 1 if res["alert"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
