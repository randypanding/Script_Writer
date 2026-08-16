"""判官校准（T-08b / D8）：校准集 → 一致率 / Cohen κ / 位置偏置 → 报告 + 门禁状态。

校准集来源见 pairwise_protocol.md §5：revision_pairs（人类改后 = 偏好改后）+ preference_pairs
（人类直接标注偏好）。指标计算是纯函数（可脱离 LLM 单测），LLM 只负责产出判定。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nsc.eval.gate import evaluate_calibration, write_gate_state
from nsc.judge.pairwise import run_pairwise
from nsc.judge.rubric_judge import RubricJudge


@dataclass(slots=True)
class CalibrationItem:
    item_id: str
    pair_id: str
    dimension: str
    unit_kind: str
    context: str
    a_text: str
    b_text: str
    human_verdict: str  # 'a' | 'b' | 'tie'
    human_score: float | None
    source: str


@dataclass(slots=True)
class PairwiseOutcome:
    dimension: str
    judge_verdict: str
    human_verdict: str
    a_position_wins: int  # 正向调用里 A 位胜（用于位置偏置）
    invalid: int


def build_calibration_items(db: str | Path, *, limit: int = 200) -> list[CalibrationItem]:
    """组装校准集：revision_pairs（仅人工确认过的）在前，preference_pairs 补足。"""
    conn = sqlite3.connect(db)
    items: list[CalibrationItem] = []
    try:
        rows = conn.execute(
            """SELECT rp.pair_id, rp.unit_kind, rp.context_json, rp.before_text, rp.after_text, rp.dimension
               FROM revision_pairs rp JOIN feedback f ON f.feedback_id = rp.feedback_id
               WHERE f.confirmed_by != '' ORDER BY rp.pair_id"""
        ).fetchall()
        for pair_id, unit_kind, ctx, before, after, dim in rows:
            items.append(
                CalibrationItem(
                    pair_id,
                    pair_id,
                    dim,
                    unit_kind,
                    ctx or "",
                    before,
                    after,
                    "b",
                    None,
                    "revision",
                )
            )
        rows = conn.execute(
            """SELECT pair_id, unit_kind, context_json, a_text, b_text, human_pref, dimension, origin
               FROM preference_pairs ORDER BY pair_id"""
        ).fetchall()
        for pair_id, unit_kind, ctx, a_text, b_text, human_pref, dim, origin in rows:
            items.append(
                CalibrationItem(
                    pair_id,
                    pair_id,
                    dim,
                    unit_kind,
                    ctx or "",
                    a_text,
                    b_text,
                    human_pref,
                    None,
                    origin,
                )
            )
    finally:
        conn.close()
    if limit and len(items) > limit:
        rev = [it for it in items if it.source == "revision"]
        pref = [it for it in items if it.source != "revision"]
        items = rev[: max(1, int(limit * 0.4))] + pref[: max(0, limit - max(1, int(limit * 0.4)))]
    return items


def cohen_kappa(rater1: list[str], rater2: list[str]) -> float:
    """Cohen 的 κ（类别一致率修正）。空样本 → 0。"""
    n = len(rater1)
    if n == 0 or n != len(rater2):
        return 0.0
    labels = sorted(set(rater1) | set(rater2))
    if len(labels) < 2:
        return 1.0 if all(a == b for a, b in zip(rater1, rater2, strict=True)) else 0.0
    obs = sum(1 for a, b in zip(rater1, rater2, strict=True) if a == b) / n

    def p(xs: list[str]) -> dict[str, float]:
        return {v: xs.count(v) / n for v in labels}

    p1, p2 = p(rater1), p(rater2)
    exp = sum(p1[v] * p2[v] for v in labels)
    if exp >= 1.0:
        return 1.0 if obs == 1.0 else 0.0
    return round((obs - exp) / (1 - exp), 3)


def compute_metrics(
    outcomes: list[PairwiseOutcome],
    scores_pairs: list[tuple[int, int]],
    judge_ver: str,
) -> dict[str, Any]:
    """纯计算：逐维一致率 + 总体 + κ（评分 + 判定） + 位置偏置 + invalid 率。"""
    n = len(outcomes)
    by_dim: dict[str, dict[str, int]] = {}
    for o in outcomes:
        row = by_dim.setdefault(o.dimension, {"n": 0, "agree": 0})
        row["n"] += 1
        if o.judge_verdict == o.human_verdict:
            row["agree"] += 1
    by_dimension = {
        d: {"n": r["n"], "agreement": round(r["agree"] / r["n"], 3)} for d, r in by_dim.items()
    }
    overall = sum(1 for o in outcomes if o.judge_verdict == o.human_verdict) / n if n else 0.0
    a_wins = sum(1 for o in outcomes if o.a_position_wins)
    return {
        "n_items": n,
        "judge_ver": judge_ver,
        "pairwise_report": round(overall, 3),
        "pairwise_gate": round(overall, 3),
        "kappa": cohen_kappa([str(h) for h, _ in scores_pairs], [str(j) for _, j in scores_pairs]),
        "kappa_verdict": cohen_kappa(
            [o.human_verdict for o in outcomes], [o.judge_verdict for o in outcomes]
        ),
        "invalid_rate": (round(sum(1 for o in outcomes if o.invalid) / n, 3) if n else 0.0),
        "position_bias": round(abs(a_wins / n - 0.5), 3) if n else 0.0,
        "by_dimension": by_dimension,
    }


def render_report(metrics: dict[str, Any], ev: dict[str, Any], out: Path) -> Path:
    lines = ["# 判官校准报告（T-08b / D8）", ""]
    lines.append(f"- 校准样本：{metrics['n_items']} 条")
    lines.append(f"- 判官版本：{metrics['judge_ver']}")
    lines.append("")
    lines.append("| 指标 | 值 | 门槛 | 通过 |")
    lines.append("|---|---|---|---|")
    for d in ev["detail"]:
        mark = "✓" if d["pass"] else "✗"
        lines.append(f"| {d['metric']} | {d['value']:.3f} | {d['threshold']} | {mark} |")
    lines.append("")
    lines.append("### 逐维成对一致率")
    lines.append("| 维度 | 一致率 | 样本数 |")
    lines.append("|---|---|---|")
    for dim, row in sorted(metrics.get("by_dimension", {}).items()):
        lines.append(f"| {dim} | {row['agreement']:.3f} | {row['n']} |")
    lines.append("")
    gate_ok = bool(ev["gate_ok"])
    lines.append(f"门禁：{'开启' if gate_ok else '关闭（判官只能出报告）'}（JUDGE_GATE_ENABLED）")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), "utf-8")
    return out


def run_calibration(
    *,
    db: str | Path = "cases/cases.db",
    judge: RubricJudge | None = None,
    stub: Any | None = None,
    out: str | Path = "out/judge_calibration.md",
    limit: int = 200,
    seed: int = 1,
    gate_state: str | Path = "judge-calibration.yml",
) -> dict[str, Any]:
    """跑校准集 → 指标 → 报告 → 门禁状态。`stub` 可注入确定性判官（测试桩）。

    返回 {"metrics", "gate", "report", "gate_state"}。
    """
    active = judge or stub
    if active is None:
        raise ValueError("run_calibration 需要 judge（真实）或 stub（测试）")
    conn = sqlite3.connect(db)
    items = build_calibration_items(db, limit=limit)
    outcomes: list[PairwiseOutcome] = []
    scores_pairs: list[tuple[int, int]] = []
    try:
        for it in items:
            res = run_pairwise(
                active,
                conn,
                pair_id=it.pair_id,
                unit_kind=it.unit_kind,
                dimension=it.dimension,
                context=it.context,
                a_text=it.a_text,
                b_text=it.b_text,
                seed=seed,
            )
            call1, resolved = res["call1"], res["resolved"]
            outcomes.append(
                PairwiseOutcome(
                    it.dimension,
                    resolved.winner,
                    it.human_verdict,
                    int(call1.winner == "a"),
                    int(resolved.invalid),
                )
            )
            if it.human_score is not None:
                chosen = it.b_text if it.human_verdict == "b" else it.a_text
                sc = active.judge_absolute(it.dimension, it.context, chosen, seed=seed)
                if not sc.invalid:
                    scores_pairs.append((int(it.human_score), round(sc.score)))
        for row in conn.execute(
            "SELECT pair_id, dimension, human_score FROM judge_calibration WHERE human_score IS NOT NULL"
        ):
            pair_id, dim, human_score = row
            pref = conn.execute(
                "SELECT a_text, b_text, context_json FROM preference_pairs WHERE pair_id=?",
                (pair_id,),
            ).fetchone()
            if pref is None:
                continue
            _a_text, b_text, ctx = pref
            sc = active.judge_absolute(dim, ctx or "", b_text, seed=seed)
            if not sc.invalid:
                scores_pairs.append((int(human_score), round(sc.score)))
    finally:
        conn.close()
    metrics = compute_metrics(outcomes, scores_pairs, str(getattr(active, "judge_ver", "stub")))
    ev = evaluate_calibration(metrics)
    report_path = render_report(metrics, ev, Path(out))
    gate_path = write_gate_state(metrics, gate_state)
    return {
        "metrics": metrics,
        "gate": ev,
        "report": str(report_path),
        "gate_state": str(gate_path),
    }
