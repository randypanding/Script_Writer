"""评测门禁（T-08b）：阈值加载 + JUDGE_GATE_ENABLED + 校准结果判定。

D8：未过校准门槛的判官只能出报告，不能参与门禁。
`judge calibrate` 未过闸时会把仓库变量 JUDGE_GATE_ENABLED 写为 false（协议 §4）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

THRESHOLDS_PATH = Path("eval/thresholds.yaml")
GATE_STATE_PATH = Path("judge-calibration.yml")


def load_thresholds(path: str | Path = THRESHOLDS_PATH) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text("utf-8")) or {}


def gate_var_name() -> str:
    return str(load_thresholds().get("l1", {}).get("judge_gate_enabled_var", "JUDGE_GATE_ENABLED"))


def gate_enabled() -> bool:
    """判官是否允许参与门禁。优先级：环境变量 > judge-calibration.yml > 默认开启。"""
    val = os.environ.get(gate_var_name())
    if val is not None:
        return val.strip().lower() not in ("0", "false", "off", "no", "")
    if GATE_STATE_PATH.exists():
        data = yaml.safe_load(GATE_STATE_PATH.read_text("utf-8")) or {}
        return bool(data.get("judge_gate_enabled", True))
    return True


def evaluate_calibration(metrics: dict[str, Any]) -> dict[str, Any]:
    """对照 eval/thresholds.yaml 逐项判定是否过闸。返回逐项明细 + 汇总。"""
    t = load_thresholds().get("judge_calibration", {})
    checks = [
        ("pairwise_report", "pairwise_report"),
        ("pairwise_gate", "pairwise_gate"),
        ("kappa_gate", "kappa"),
        ("max_invalid_rate", "invalid_rate"),
        ("max_position_bias", "position_bias"),
        ("min_calibration_items", "n_items"),
    ]
    detail: list[dict[str, Any]] = []
    ok = True
    for key, metric in checks:
        threshold = float(t.get(key, 0.0))
        value = float(metrics.get(metric, 0.0))
        if key in ("max_invalid_rate", "max_position_bias"):
            passed = value <= threshold
        elif key == "min_calibration_items":
            passed = value >= threshold
        else:
            passed = value >= threshold
        ok = ok and passed
        detail.append(
            {
                "metric": metric,
                "value": value,
                "threshold": threshold,
                "pass": bool(passed),
            }
        )
    return {"gate_ok": bool(ok), "detail": detail}


def write_gate_state(metrics: dict[str, Any], path: str | Path = GATE_STATE_PATH) -> Path:
    """未过闸 → JUDGE_GATE_ENABLED 写 false（判官降级为仅报告）。"""
    ev = evaluate_calibration(metrics)
    p = Path(path)
    p.write_text(
        yaml.safe_dump(
            {"judge_gate_enabled": bool(ev["gate_ok"]), "metrics": metrics},
            allow_unicode=True,
        ),
        "utf-8",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：读取校准 metrics JSON → 判定门禁 → 退出码 0/1。"""
    global THRESHOLDS_PATH
    import argparse
    import json

    ap = argparse.ArgumentParser(description="评测门禁判定（D8）")
    ap.add_argument(
        "--thresholds", default=None, help=f"eval/thresholds.yaml 路径（默认 {THRESHOLDS_PATH}）"
    )
    ap.add_argument(
        "metrics",
        nargs="?",
        help="校准 metrics JSON 文件；缺省则从 GATE_STATE_PATH 读取",
    )
    args = ap.parse_args(argv)

    if args.thresholds:
        THRESHOLDS_PATH = Path(args.thresholds)

    if args.metrics:
        metrics = json.loads(Path(args.metrics).read_text("utf-8"))
        ev = evaluate_calibration(metrics)
    else:
        if not GATE_STATE_PATH.exists():
            # CI 场景（judge-calibration.yml 尚未提交）：回退到 gate_enabled() 的
            # 环境变量（JUDGE_GATE_ENABLED）/ 默认开启，避免硬失败。
            enabled = gate_enabled()
            print(f"无校准状态文件；JUDGE_GATE_ENABLED={str(enabled).lower()}")
            return 0 if enabled else 1
        state = yaml.safe_load(GATE_STATE_PATH.read_text("utf-8")) or {}
        ev = evaluate_calibration(state.get("metrics") or {})
    for d in ev["detail"]:
        print(f"{d['metric']}: {d['value']}/{d['threshold']} -> {'PASS' if d['pass'] else 'FAIL'}")
    print(f"gate_ok={str(ev['gate_ok']).lower()}")
    return 0 if ev["gate_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
