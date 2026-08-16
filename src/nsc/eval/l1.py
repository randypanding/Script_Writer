"""L1 评测：1 档案例检索的 A/B 增益报告（T-16）。

两臂（同一批 brief）：
  - retrieval：`ctx.retrieval = RetrievalService(...)`（从 cases/cases.db 检索 few-shot）
  - baseline：`ctx.retrieval = None`（--no-retrieval 的等价物）

指标：L0 findings 数（少 = 好）、成本、token、时长。
`compare_arms` 是纯函数，可脱离 LLM 单测；`run_ab_retrieval` 是真实编译编排。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: runner(brief, retrieval_on) -> dict（见 _compile_brief 的返回键）。
Runner = Callable[[dict[str, Any], bool], dict[str, Any]]


@dataclass(slots=True)
class ArmResult:
    arm: str
    findings: int = 0
    cost_usd: float = 0.0
    tokens: int = 0
    wall_ms: int = 0
    status: str = "ok"


def _diff(reduced: int, baseline: int) -> float:
    """findings 的归一化差值：负数 = 检索臂 finding 更少 = 更好。"""
    denom = max(baseline, 1)
    return round((baseline - reduced) / denom, 3)


def compare_arms(retrieval: ArmResult, baseline: ArmResult) -> dict[str, Any]:
    """纯计算：给定两臂结果，产出增益指标（可单测，无 LLM）。"""
    return {
        "retrieval_findings": retrieval.findings,
        "baseline_findings": baseline.findings,
        "findings_gain": _diff(retrieval.findings, baseline.findings),
        "cost_usd": {"retrieval": retrieval.cost_usd, "baseline": baseline.cost_usd},
        "cost_delta_usd": round(retrieval.cost_usd - baseline.cost_usd, 4),
        "tokens": {"retrieval": retrieval.tokens, "baseline": baseline.tokens},
        "wall_ms": {"retrieval": retrieval.wall_ms, "baseline": baseline.wall_ms},
        "retrieval_status": retrieval.status,
        "baseline_status": baseline.status,
    }


def render_report(results: list[dict[str, Any]], out: Path) -> Path:
    """把逐案例指标渲染成 markdown 报告并落盘。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 1 档案例检索 A/B 报告（T-16）", ""]
    lines.append(
        "两臂均为同一批 brief 的完整编译；findings_gain 负值 = 检索臂 L0 finding 更少（更好）。"
    )
    lines.append("")
    if not results:
        lines.append("无样本。")
    else:
        g = [
            r["findings_gain"]
            for r in results
            if r["retrieval_status"] == "ok" and r["baseline_status"] == "ok"
        ]
        avg = round(sum(g) / len(g), 3) if g else None
        lines.append(f"- 样本数：{len(results)}；可用增益 {len(g)} 条；平均 findings_gain = {avg}")
        lines.append("")
        lines.append("| brief | 检索臂 findings | 基线 findings | gain | Δ成本$ | 检索状态 |")
        lines.append("|---|---|---|---|---|---|")
        for r in results:
            lines.append(
                f"| {Path(r['brief']).name} | {r['retrieval_findings']} | {r['baseline_findings']} | "
                f"{r['findings_gain']} | {r['cost_delta_usd']} | {r['retrieval_status']} |"
            )
    out.write_text("\n".join(lines), "utf-8")
    return out


def _default_briefs(sample: int) -> list[Path]:
    """默认样本：examples/ 下的 brief.yaml（不足 sample 时重复自身以满足批量）。"""
    briefs = list(Path("examples").rglob("brief.yaml"))
    if not briefs:
        return []
    out: list[Path] = []
    i = 0
    while len(out) < max(sample, 1) and i < max(sample, 1) * len(briefs):
        out.append(briefs[i % len(briefs)])
        i += 1
    return out


def _compile_brief(brief: dict[str, Any], retrieval_on: bool) -> dict[str, Any]:
    """真实编译一臂：返回 findings 数 / 成本 / token / 时长 / 状态。"""
    import time

    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.passes import PassContext, PassFailure
    from nsc.passes.pipeline import run_pipeline
    from nsc.runtime.ir_io import build_view
    from nsc.runtime.models import ModelRouter
    from nsc.runtime.provenance import RunsStore, spec_fingerprint

    profile = yaml.safe_load(Path(f"profiles/{brief.get('profile', '')}.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path(f"brands/{brief.get('brand', '')}/brand.yaml").read_text("utf-8"))
    spec_files = list(Path("spec").rglob("*.py")) + list(Path("spec").rglob("*.yaml"))
    ctx = PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=ModelRouter(),
        store=RunsStore(Path("out") / "eval_runs.db"),
        ruleset_ver=spec_fingerprint(list(Path("spec/checks").rglob("*.yaml")))[:12],
        spec_sha=spec_fingerprint(spec_files)[:12],
        out_dir=Path("out") / "eval",
    )
    if retrieval_on:
        from nsc.retrieval import RetrievalService

        ctx.retrieval = RetrievalService(db_path="cases/cases.db")
    t0 = time.monotonic()
    try:
        ir = run_pipeline(ctx)
    except PassFailure as e:
        return {
            "findings": 0,
            "cost_usd": 0.0,
            "tokens": 0,
            "wall_ms": 0,
            "status": f"failed:{e.reason[:80]}",
        }
    wall_ms = int((time.monotonic() - t0) * 1000)
    view = build_view(ir.model_dump(), profile, brand)
    rs = RuleSet.load(
        profile_id=brief.get("profile", ""),
        industry=brand.get("industry", ""),
        brand_id=brief.get("brand", ""),
        stage="final",
        enabled_domains=profile.get("enabled_check_domains", []),
    )
    rep = evaluate(rs, view, ctx={"profile": profile, "brand": brand})
    runs = ctx.store.runs()

    def f(r: dict[str, object], key: str) -> float:
        return float(str(r[key] or 0))

    def i(r: dict[str, object], key: str) -> int:
        return int(str(r[key] or 0))

    return {
        "findings": len(rep.findings),
        "cost_usd": round(sum(f(r, "cost_usd") for r in runs), 4),
        "tokens": sum(i(r, "tokens_in") + i(r, "tokens_out") for r in runs),
        "wall_ms": wall_ms,
        "status": "ok",
    }


def run_ab_retrieval(
    *,
    sample: int = 12,
    out_dir: Path = Path("out/eval"),
    briefs: list[Path] | None = None,
    runner: Runner | None = None,
) -> Path:
    """对样本 brief 各跑两臂编译，比较 L0 findings / 成本，写报告并返回路径。

    runner 可注入（测试用桩），默认走真实 ModelRouter 编译。
    """
    briefs = briefs if briefs is not None else _default_briefs(sample)
    runner = runner or _compile_brief
    results: list[dict[str, Any]] = []
    for b in briefs:
        brief = yaml.safe_load(b.read_text("utf-8"))
        ret = runner(brief, True)
        base = runner(brief, False)
        results.append(
            {
                "brief": str(b),
                **compare_arms(ArmResult("retrieval", **ret), ArmResult("baseline", **base)),
            }
        )
    return render_report(results, Path(out_dir) / "ab_retrieval.md")


# ------------------------------------------------------------------ JSON 摘要
def _summary_json(results: list[dict[str, Any]]) -> dict[str, Any]:
    """与数据库 metrics_weekly.retrieval_gain 同口径的汇总（供 nsc metrics 复用）。"""
    ok = [r for r in results if r["retrieval_status"] == "ok" and r["baseline_status"] == "ok"]
    return {
        "n": len(results),
        "usable_n": len(ok),
        "retrieval_gain": (round(sum(r["findings_gain"] for r in ok) / len(ok), 3) if ok else 0.0),
        "cost_delta_usd": round(sum(r["cost_delta_usd"] for r in ok), 4) if ok else 0.0,
    }


# ------------------------------------------------------------------ 判官 L1（T-08b）
def collect_units(raw: dict[str, Any]) -> list[dict[str, str]]:
    """把 IR 拍平成可判分单位：episode/scene/beat 各抽一段文本。"""
    units: list[dict[str, str]] = []
    for ep in raw.get("episodes", []):
        title = " ".join(x for x in (str(ep.get("title", "")), str(ep.get("logline", ""))) if x)
        units.append({"kind": "episode", "id": str(ep.get("id", "")), "text": title})
    for sc in raw.get("scenes", []):
        units.append(
            {
                "kind": "scene",
                "id": str(sc.get("id", "")),
                "text": str(sc.get("summary", "")),
            }
        )
    for bt in raw.get("beats", []):
        units.append(
            {
                "kind": "beat",
                "id": str(bt.get("id", "")),
                "text": str(bt.get("summary", "")),
            }
        )
    return units


def judge_units(
    units: list[dict[str, str]],
    judge: Any,
    rubric: dict[str, Any],
    *,
    context: str = "",
    max_calls: int = 64,
    seed: int = 1,
) -> list[dict[str, Any]]:
    """对每个单位判其适用维度（rubric applies_to），返回判分明细。judge 可注入桩。"""
    results: list[dict[str, Any]] = []
    for u in units:
        for dim_id, dim in rubric["dimensions"].items():
            if u["kind"] not in dim.get("applies_to", []):
                continue
            sc = judge.judge_absolute(dim_id, context, u["text"], seed=seed)
            results.append(
                {
                    "dimension": dim_id,
                    "unit_kind": u["kind"],
                    "unit_id": u["id"],
                    "score": sc.score,
                    "invalid": int(sc.invalid),
                }
            )
            if len(results) >= max_calls:
                return results
    return results


def aggregate_l1(results: list[dict[str, Any]], rubric: dict[str, Any]) -> dict[str, Any]:
    """按 rubric 权重聚合加权均值 + 逐维均值。纯函数（可单测）。"""
    dims = rubric["dimensions"]
    total_w = 0.0
    total_s = 0.0
    per_dim: dict[str, list[float]] = {}
    for r in results:
        w = float(dims.get(r["dimension"], {}).get("weight", 0.0))
        total_w += w
        total_s += w * r["score"]
        per_dim.setdefault(r["dimension"], []).append(r["score"])
    return {
        "aggregate": round(total_s / total_w, 3) if total_w else 0.0,
        "per_dimension": {d: round(sum(v) / len(v), 3) for d, v in per_dim.items()},
        "n_judged": len(results),
    }


def _compile_for_judge(brief: dict[str, Any]) -> dict[str, Any]:
    """真实编译：brief → IR（dict）。判官 L1 用它取单位。"""
    from nsc.passes import PassContext, PassFailure
    from nsc.passes.pipeline import run_pipeline
    from nsc.runtime.models import ModelRouter
    from nsc.runtime.provenance import RunsStore, spec_fingerprint

    profile = yaml.safe_load(Path(f"profiles/{brief.get('profile', '')}.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path(f"brands/{brief.get('brand', '')}/brand.yaml").read_text("utf-8"))
    spec_files = list(Path("spec").rglob("*.py")) + list(Path("spec").rglob("*.yaml"))
    ctx = PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=ModelRouter(),
        store=RunsStore(Path("out") / "eval_runs.db"),
        ruleset_ver=spec_fingerprint(list(Path("spec/checks").rglob("*.yaml")))[:12],
        spec_sha=spec_fingerprint(spec_files)[:12],
        out_dir=Path("out") / "eval",
    )
    try:
        ir = run_pipeline(ctx)
    except PassFailure as e:
        return {"error": e.reason}
    return ir.model_dump()


def _render_l1_report(
    rows: list[dict[str, Any]], agg_all: float, blocked: bool, gate: bool, out: Path
) -> Path:
    from nsc.eval.gate import load_thresholds

    l1 = load_thresholds().get("l1", {})
    aggregate_min = float(l1.get("aggregate_min", 3.2))
    per_dim_min = float(l1.get("per_dimension_min_report_only", 2.5))
    lines = ["# 判官 L1 评测报告（T-08b）", ""]
    lines.append(f"- 样本数：{len(rows)}；聚合分（加权均值）= {agg_all}（门槛 {aggregate_min}）")
    lines.append(f"- 门禁（JUDGE_GATE_ENABLED）：{'开' if gate else '关'}")
    lines.append(
        f"- 结论：{'阻塞' if blocked else '通过' if agg_all >= aggregate_min else '未达门槛（仅报告）'}"
    )
    lines.append("")
    lines.append("| brief | 聚合分 | 判分样本 | 逐维 |")
    lines.append("|---|---|---|---|")
    for r in rows:
        pd = "; ".join(f"{k}={v}" for k, v in r["per_dimension"].items())
        lines.append(f"| {Path(r['brief']).name} | {r['aggregate']} | {r['n_judged']} | {pd} |")
    lines.append("")
    lines.append(f"逐维报告门槛：{per_dim_min}（低于仅提示，不阻塞）")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), "utf-8")
    return out


def run_l1_judge(
    *,
    sample: int = 12,
    out_dir: Path = Path("out/eval"),
    briefs: list[Path] | None = None,
    compile_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    judge: Any | None = None,
    seed: int = 1,
) -> Path:
    """判官 L1：对样本编译产物逐单位判分 → 加权聚合 → 门禁判定 → 报告。

    compile_runner / judge 可注入（测试桩）；默认走真实编译 + RubricJudge。
    """
    from nsc.eval.gate import gate_enabled, load_thresholds
    from nsc.judge.rubric_judge import RubricJudge

    if judge is None:
        judge = RubricJudge()
    rubric = judge.rubric
    briefs = briefs if briefs is not None else _default_briefs(sample)
    compile_runner = compile_runner or _compile_for_judge
    rows: list[dict[str, Any]] = []
    for b in briefs:
        raw = compile_runner(yaml.safe_load(b.read_text("utf-8")))
        if "error" in raw:
            rows.append(
                {
                    "brief": str(b),
                    "aggregate": 0.0,
                    "per_dimension": {},
                    "n_judged": 0,
                    "error": raw["error"],
                }
            )
            continue
        results = judge_units(collect_units(raw), judge, rubric, context=str(b), seed=seed)
        rows.append({"brief": str(b), **aggregate_l1(results, rubric)})
    agg_all = round(sum(r["aggregate"] for r in rows) / len(rows), 3) if rows else 0.0
    l1 = load_thresholds().get("l1", {})
    aggregate_min = float(l1.get("aggregate_min", 3.2))
    gate = gate_enabled()
    blocked = gate and agg_all < aggregate_min
    return _render_l1_report(rows, agg_all, blocked, gate, Path(out_dir) / "l1.md")
