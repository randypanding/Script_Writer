"""nsc CLI —— CLI 是唯一 UI（第十四章：P2 前不做 Web UI）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _load_assets(profile_id: str, brand_id: str) -> tuple[dict, dict]:
    profile = yaml.safe_load(Path(f"profiles/{profile_id}.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path(f"brands/{brand_id}/brand.yaml").read_text("utf-8"))
    return profile, brand


def _make_ctx(brief: dict, out_dir: Path, router: Any = None) -> Any:
    from nsc.passes import PassContext
    from nsc.runtime.models import ModelRouter
    from nsc.runtime.provenance import RunsStore, spec_fingerprint

    profile, brand = _load_assets(brief.get("profile", ""), brief.get("brand", ""))
    spec_files = list(Path("spec").rglob("*.py")) + list(Path("spec").rglob("*.yaml"))
    prompts = list(Path("prompts").glob("*.json")) if Path("prompts").exists() else []
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=router or ModelRouter(),
        store=RunsStore(out_dir / "runs.db"),
        ruleset_ver=spec_fingerprint(list(Path("spec/checks").rglob("*.yaml")))[:12],
        spec_sha=spec_fingerprint(spec_files)[:12],
        promptset_ver=spec_fingerprint(prompts)[:12] if prompts else "seed",
        out_dir=out_dir,
    )


# --- 编译 ---
@app.command()
def run(brief: str, profile: str = "", out: str = "out/", rerank: bool = False) -> None:
    """端到端编译：brief → IR → 小说 → 剧本。"""
    from nsc.passes import PassFailure
    from nsc.passes.pipeline import run_pipeline
    from nsc.runtime.ir_io import save

    brief_dict = yaml.safe_load(Path(brief).read_text("utf-8"))
    ctx = _make_ctx(brief_dict, Path(out))
    try:
        ir = run_pipeline(ctx)
    except PassFailure as e:
        typer.secho(f"编译失败：{e}", fg="red", err=True)
        raise typer.Exit(1) from e
    ir_path = ctx.out_dir / ir.project.title / "ir.json"
    save(ir, ir_path)
    typer.secho(f"编译完成：{ir_path}", fg="green")


@app.command()
def recompile(
    ir: str,
    episode: int | None = None,
    scene: str | None = None,
    from_pass: str = "",
    force: bool = False,
) -> None:
    """局部重编译（依赖闭包由 spec/passes/dep_graph.yaml 给出）。"""
    from nsc.passes import PassFailure
    from nsc.passes.pipeline import recompile_episode
    from nsc.runtime.ir_io import load, save

    old = load(ir)
    if episode is None:
        typer.secho("目前只支持 --episode 粒度的局部重编译", fg="red", err=True)
        raise typer.Exit(2)
    brief_dict = {"profile": old.project.profile_id, "brand": old.project.brand_id}
    ctx = _make_ctx(brief_dict, Path(ir).parent.parent if Path(ir).parent.name else Path("out"))
    try:
        new = recompile_episode(ctx, old, episode)
    except PassFailure as e:
        typer.secho(f"重编译失败：{e}", fg="red", err=True)
        raise typer.Exit(1) from e
    save(new, ir)
    typer.secho(f"已重编译第 {episode} 集并保留未变节点 ID：{ir}", fg="green")


@app.command()
def check(ir: str, stage: str = "final", fmt: str = "text") -> None:
    """L0 检查。exit code：0 全绿 / 1 有 block / 2 规则本身报错。"""
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.runtime.ir_io import build_view
    from spec.ir.container import NarrativeIR
    from spec.ir.invariants import check_all

    raw = json.loads(Path(ir).read_text("utf-8"))
    proj = raw.get("project", {})
    profile, brand = _load_assets(proj.get("profile_id", ""), proj.get("brand_id", ""))

    violations = check_all(NarrativeIR.model_validate(raw), profile, stage=stage)
    view = build_view(raw, profile, brand)
    rs = RuleSet.load(
        profile_id=proj.get("profile_id", ""),
        industry=brand.get("industry", ""),
        brand_id=brand.get("brand_id", ""),
        stage=stage,
        enabled_domains=list(profile.get("enabled_check_domains", [])),
    )
    rep = evaluate(rs, view, ctx={"profile": profile, "brand": brand})
    for v in violations:
        typer.secho(f"[{v.inv_id}] {v.message}", fg="red")
    if rep.findings:
        typer.echo(rep.as_feedback_text())
    if rep.errors:
        for e in rep.errors:
            typer.secho(f"规则报错：{e}", fg="red", err=True)
        raise typer.Exit(2)
    typer.echo(f"rules_evaluated={rep.rules_evaluated} stage={stage}")
    if violations or rep.blocked:
        raise typer.Exit(1)
    typer.secho("L0 全绿", fg="green")


@app.command()
def render(ir: str, target: list[str] = typer.Option(None)) -> None:
    """渲染交付物（含锚点）。"""


# --- 反馈与飞轮 ---
feedback_app = typer.Typer()
app.add_typer(feedback_app, name="ingest")


def _ingest_common(
    kind: str,
    path: str,
    case: str,
    delivered: str | None,
    db: str,
    out: str,
    obs_dir: str,
    no_classify: bool,
) -> None:
    from nsc.feedback.ingest import ingest_docx, ingest_text
    from nsc.runtime.models import ModelRouter

    router = None if no_classify else ModelRouter()
    kwargs: dict[str, Any] = {
        "case_id": case,
        "db_path": db,
        "router": router,
        "obs_dir": obs_dir,
        "out_dir": out,
    }
    if kind == "docx":
        report = ingest_docx(path, delivered_path=delivered, **kwargs)
    else:
        report = ingest_text(path, **kwargs)
    if report.dry_run:
        typer.secho(
            f"干跑（--no-classify）：恢复 {len(report.records)} 处编辑，未落库"
            "（dimension 未判定，schema 不允许写入）",
            fg="yellow",
        )
        return
    typer.secho(
        f"摄入完成：{len(report.feedback_ids)} 条 feedback "
        f"（{len(report.unaligned)} 条对齐失败，见 out/ingest/unaligned.md）\n"
        f"annotation 队列：{report.queue_path}（confirmed_by 均为空，请到 Langfuse 批量确认）",
        fg="green",
    )


@feedback_app.command("docx")
def ingest_docx_cmd(
    path: str,
    case: str,
    delivered: str = typer.Option(None, help="交付物（docx/anchors.csv/txt），供 L3 模糊对齐"),
    db: str = "cases/cases.db",
    out: str = "out",
    obs_dir: str = "spec/rules/L0_observations",
    no_classify: bool = False,
) -> None:
    """带修订 docx → 结构化反馈条目（feedback/revision_pairs/preference_pairs/L0 观测）。"""
    _ingest_common("docx", path, case, delivered, db, out, obs_dir, no_classify)


@feedback_app.command("text")
def ingest_text_cmd(
    path: str,
    case: str,
    db: str = "cases/cases.db",
    out: str = "out",
    obs_dir: str = "spec/rules/L0_observations",
    no_classify: bool = False,
) -> None:
    """纯文本/微信消息摄入：每行一条 comment 型反馈。"""
    _ingest_common("text", path, case, None, db, out, obs_dir, no_classify)


mine_app = typer.Typer()
app.add_typer(mine_app, name="mine")


@mine_app.command("run")
def mine_run(
    db: str = "cases/cases.db",
    rules_root: str = "spec/rules",
    open_pr: bool = False,
) -> None:
    """L0→L1 聚类归纳：已确认观察 → HDBSCAN 聚类 → RuleInduce → L1_candidates。"""
    from nsc.mining.induce import run_mine
    from nsc.runtime.models import ModelRouter

    candidates = run_mine(db, router=ModelRouter(), rules_root=Path(rules_root))
    if not candidates:
        typer.secho(
            "无满足晋升门槛的簇（同簇需 ≥3 条观察且 ≥2 个 case，且 feedback.confirmed_by 非空）",
            fg="yellow",
        )
        return
    for c in candidates:
        typer.secho(
            f"候选规则 {c.rule_id}（{c.dimension}，簇 {c.cluster_id}）→ {c.path}", fg="green"
        )
    typer.secho(
        f"共 {len(candidates)} 条 L1 候选。它们不参与门禁；L1→L2 需 `nsc mine validate`（T-15）。",
        fg="cyan",
    )


@mine_app.command("retire")
def mine_retire() -> None: ...


# --- 优化与评测 ---
@app.command()
def optimize(pass_: str = typer.Option(..., "--pass"), auto: str = "light") -> None: ...


eval_app = typer.Typer()
app.add_typer(eval_app, name="eval")


@eval_app.command("l1")
def eval_l1(sample: int = 12) -> None: ...
@eval_app.command("build-dataset")
def eval_build(pass_: str = typer.Option(..., "--pass")) -> None: ...


judge_app = typer.Typer()
app.add_typer(judge_app, name="judge")


@judge_app.command("calibrate")
def judge_calibrate(report: str = "out/judge_calibration.md") -> None: ...


# --- 冷启动 ---
annotate_app = typer.Typer()
app.add_typer(annotate_app, name="annotate")


@annotate_app.command("ingest")
def annotate_ingest(source: str) -> None:
    """逆向标注：字幕/转写 → Narrative IR（D15）。遵守 COMPLIANCE.md §1。"""


@annotate_app.command("priors")
def annotate_priors(out: str = "profiles/_mined_priors.yaml") -> None: ...
@annotate_app.command("roundtrip")
def annotate_roundtrip(case: str) -> None:
    """往返重建评测（D16）：原片→IR→重生成→对比。IR 设计的唯一无监督信号。"""


# --- 数据与指标 ---
db_app = typer.Typer()
app.add_typer(db_app, name="db")


@db_app.command("rebuild")
def db_rebuild() -> None: ...
@db_app.command("export")
def db_export() -> None: ...


metrics_app = typer.Typer()
app.add_typer(metrics_app, name="metrics")


@metrics_app.command("weekly")
def metrics_weekly(write: str = "docs/metrics/") -> None:
    """D22 北极星 + D23 六个数。"""


dev_app = typer.Typer()
app.add_typer(dev_app, name="dev")


@dev_app.command("split-checks")
def split_checks(batch: str) -> None:
    """把 spec/checks/_BATCH_*.yaml 拆成一文件一规则。"""
