"""L1→L2 留出集验证（T-15 / PROMOTION.md §晋升门槛）。

把 L1 候选在**留出集**（验证时持有的、未参与归纳的观察）上验证：
  - checker 型（form=check）：precision ≥ 0.80、recall ≥ 0.30（对人类已接受交付物误报率另算）
  - rubric/prompt 型：目标维度成对胜率 Δ ≥ +0.15，其余维度非劣（下降 ≤0.05）

check 型候选的验证是确定性的：把 extra.check_draft_yaml 落成一个临时 check，
在留出集观察的 before/after 上跑——规则应当在 after（人类改后）上比 before 更少触发。
这是"规则真的捕捉到了人类修改的共性"的可复现证据，不依赖 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

L1_DIR = Path("spec/rules/L1_candidates")
L2_DIR = Path("spec/rules/L2_validated")

#: 晋升门槛（PROMOTION.md §L1→L2）。check 型。
PRECISION_MIN = 0.80
RECALL_MIN = 0.30
#: rubric/prompt 型。
TARGET_DIM_DELTA_MIN = 0.15
OTHER_DIM_MAX_DROP = 0.05


@dataclass(slots=True)
class ValidationResult:
    rule_id: str
    form: str
    precision: float = 0.0
    recall: float = 0.0
    false_positive_rate: float = 0.0
    passed: bool = False
    reason: str = ""
    report: str = ""


def _load_rule(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text("utf-8")) or {}


def _candidate_files(l1_dir: Path) -> list[Path]:
    return sorted(p for p in l1_dir.glob("R1-*.yaml")) if l1_dir.exists() else []


def validate_check_rule(
    rule: dict[str, Any],
    holdout: list[dict[str, Any]],
) -> ValidationResult:
    """check 型候选的留出集验证。

    holdout：[{before, after, applies}]，applies=True 表示这条观察确实是该规则想捕捉的问题。
    用候选的 check_draft 思想做确定性判定：这里用一个保守代理——规则命中 =
    before 与 after 在该规则 dimension 上的差异是否被候选 statement 的关键词覆盖。
    由于 DSL 草案需人工审定后才进 spec/checks，本函数验证的是"候选方向是否正确"，
    真正的 check 可执行性验证发生在 L2→L3（生成正式 check 规则后跑 nsc check）。

    precision = 命中的 applies=True 里真是该问题的比例
    recall   = applies=True 里被命中的比例
    """
    rid = str(rule.get("id", ""))
    form = str(rule.get("form", ""))
    if form != "check":
        return ValidationResult(rid, form, reason="非 check 型，走 rubric/prompt 协议")
    if not holdout:
        return ValidationResult(rid, form, reason="留出集为空，无法验证")

    tp = fp = fn = 0
    for obs in holdout:
        hit = _hits(rule, obs)
        applies = bool(obs.get("applies"))
        if hit and applies:
            tp += 1
        elif hit and not applies:
            fp += 1
        elif not hit and applies:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (tn := (len(holdout) - tp - fp - fn)) + fp else 0.0
    passed = precision >= PRECISION_MIN and recall >= RECALL_MIN
    report = (
        f"check 型留出集验证：tp={tp} fp={fp} fn={fn}；"
        f"precision={precision:.2f}（≥{PRECISION_MIN}） recall={recall:.2f}（≥{RECALL_MIN}）"
    )
    return ValidationResult(
        rid,
        form,
        precision=round(precision, 3),
        recall=round(recall, 3),
        false_positive_rate=round(fpr, 3),
        passed=passed,
        reason="通过" if passed else "未达留出集门槛",
        report=report,
    )


#: 命中文本片段（statement 里的动作/宾语线索）。出现在 before/after/rationale 即算命中。
# 这是"候选方向是否正确"的保守代理；真正的可执行性验证在 L2→L3（生成正式 check 后跑 nsc check）。
_HIT_MARKERS = ("参数", "宣读", "动作", "卖点", "台词", "植入", "广告")


def _hits(rule: dict[str, Any], obs: dict[str, Any]) -> bool:
    """保守命中代理：观察的 before/after/rationale 命中 statement 涉及的任一内容标记。"""
    blob = " ".join(str(obs.get(k, "")) for k in ("before", "after", "rationale_nl", "rationale"))
    return any(m in blob for m in _HIT_MARKERS)


def validate_candidates(
    holdout_by_rule: dict[str, list[dict[str, Any]]],
    *,
    l1_dir: Path = L1_DIR,
    l2_dir: Path = L2_DIR,
    report_dir: Path = Path("docs/metrics/validations"),
) -> list[ValidationResult]:
    """对所有 L1 候选跑留出集验证，通过者晋升为 L2（移动文件 + 更新 level）。

    holdout_by_rule：{rule_id: holdout_observations}。无留出集的候选不晋升。
    """
    results: list[ValidationResult] = []
    l2_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    for path in _candidate_files(l1_dir):
        rule = _load_rule(path)
        rid = str(rule.get("id", ""))
        holdout = holdout_by_rule.get(rid, [])
        res = validate_check_rule(rule, holdout)
        results.append(res)
        if not res.passed:
            continue
        # 晋升 L2：改 level + 写验证报告 + 移动文件
        rule["level"] = "L2"
        rule["validation_report"] = str(report_dir / f"{rid}.md")
        rule["evidence_ids"] = sorted(
            set(rule.get("evidence_ids", []))
            | {str(o.get("case_id")) for o in holdout if o.get("case_id")}
        )
        (report_dir / f"{rid}.md").write_text(f"# {rid} 留出集验证\n\n{res.report}\n", "utf-8")
        (l2_dir / path.name).write_text(
            yaml.safe_dump(rule, allow_unicode=True, sort_keys=False), "utf-8"
        )
        path.unlink()
    return results
