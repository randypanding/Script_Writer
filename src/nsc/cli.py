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
def run(
    brief: str,
    profile: str = "",
    out: str = "out/",
    rerank: bool = False,
    no_retrieval: bool = False,
) -> None:
    """端到端编译：brief → IR → 小说 → 剧本。--no-retrieval 关闭案例检索（A/B 对照组）。"""
    from nsc.passes import PassFailure
    from nsc.passes.pipeline import run_pipeline
    from nsc.runtime.ir_io import save

    brief_dict = yaml.safe_load(Path(brief).read_text("utf-8"))
    ctx = _make_ctx(brief_dict, Path(out))
    if not no_retrieval:
        from nsc.retrieval import RetrievalService

        ctx.retrieval = RetrievalService(db_path="cases/cases.db")
    try:
        ir = run_pipeline(ctx)
    except PassFailure as e:
        typer.secho(f"编译失败：{e}", fg="red", err=True)
        raise typer.Exit(1) from e
    ir_path = ctx.out_dir / ir.project.title / "ir.json"
    save(ir, ir_path)
    if no_retrieval:
        typer.secho("（检索已关闭：--no-retrieval）", fg="yellow")
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
def render(ir: str, out: str = "out/") -> None:
    """渲染交付物（含 D29 锚点）：novel.txt/docx、screenplay.fountain、storyboard.csv、anchors.csv + manifest.json。"""
    from nsc.render import render_all
    from nsc.runtime.ir_io import load

    raw = load(ir).model_dump()
    proj = raw["project"]
    profile, brand = _load_assets(proj.get("profile_id", ""), proj.get("brand_id", ""))
    out_dir = Path(out) / str(proj.get("title") or proj["id"])
    manifest = render_all(
        raw,
        out_dir,
        profile_ver=str(profile.get("version", "")),
        brand_ver=str(brand.get("version", "")),
    )
    anchors = manifest["anchors"]
    typer.secho(f"渲染完成：{out_dir}（manifest.json）", fg="green")
    typer.echo(
        f"锚点覆盖：{anchors['anchored']}/{anchors['paragraphs_total']} "
        f"（{anchors['coverage']:.0%}）"
    )


# --- 案例检索（T-16） ---
retrieval_app = typer.Typer()
app.add_typer(retrieval_app, name="retrieval")


@retrieval_app.command("index")
def retrieval_index(
    db: str = "cases/cases.db",
    case_limit: int | None = None,
    no_vectors: bool = False,
) -> None:
    """从已入库的 IR 快照 + 已人工确认修订重建检索池。

    快照 kind 决定 quality；`annotated` 产物 usable_as_example=0（COMPLIANCE §1，
    绝不被注入）。向量缺失/失败自动回退标量，不阻塞建池。
    """
    from nsc.retrieval import builder, pool

    items = builder.build_pool_from_snapshots(db, case_limit=case_limit)
    items += builder.build_pool_from_revisions(db)
    embedder = None
    if not no_vectors:
        from nsc.retrieval import BgeM3Embedder

        embedder = BgeM3Embedder()
    conn = pool.connect(db)
    try:
        pool.upsert_items(conn, items, embedder=embedder)
    finally:
        conn.close()
    usable = sum(1 for it in items if it.usable_as_example)
    typer.secho(f"检索池就绪：{len(items)} 条（其中可用示例 {usable} 条）→ {db}", fg="green")


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


@mine_app.command("validate")
def mine_validate(
    holdout: str = typer.Option(
        ..., help="留出集 jsonl：{rule_id, before, after, rationale_nl, applies, case_id}"
    ),
    rules_root: str = "spec/rules",
) -> None:
    """L1→L2 留出集验证。通过者移动文件到 L2_validated 并附验证报告。"""
    from nsc.mining.validate import validate_candidates

    holdout_by_rule: dict[str, list[dict]] = {}
    for line in Path(holdout).read_text("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        holdout_by_rule.setdefault(str(row.pop("rule_id")), []).append(row)
    results = validate_candidates(
        holdout_by_rule,
        l1_dir=Path(rules_root) / "L1_candidates",
        l2_dir=Path(rules_root) / "L2_validated",
    )
    for r in results:
        mark = "✓ 晋升 L2" if r.passed else "✗ 留 L1"
        typer.secho(
            f"{r.rule_id} [{r.form}] {mark}：{r.reason}", fg="green" if r.passed else "yellow"
        )


@mine_app.command("retire")
def mine_retire(rules_root: str = "spec/rules") -> None:
    """退役 hit_count==0 且超 90 天的 L3 规则；报告 canonical 是否超上限。"""
    from nsc.mining.retire import retire

    res = retire(l3_dir=Path(rules_root) / "L3_canonical")
    for rid in res.retired:
        typer.secho(f"退役 {rid}（hit_count=0 且超 90 天）", fg="yellow")
    if res.over_budget:
        typer.secho(
            f"⚠ canonical 超上限：{res.canonical_count}/{res.max_canonical}，新增前须先合并或退役",
            fg="red",
        )
    else:
        typer.secho(
            f"canonical {res.canonical_count}/{res.max_canonical}；退役 {len(res.retired)} 条",
            fg="cyan",
        )


# --- 优化与评测 ---
@app.command()
def optimize(
    pass_: str = typer.Option(..., "--pass"),
    auto: str = "light",
    db: str = "cases/cases.db",
    max_cost: float = 20.0,
    use_judge: bool = False,
) -> None:
    """跑一趟 GEPA 优化（分趟 + 教师强制 + 回归闸）。写入需 score_after>before+0.02。"""
    from nsc.optimize.gepa_run import run
    from nsc.runtime.models import ModelRouter

    judge = None
    if use_judge:
        from nsc.judge.rubric_judge import RubricJudge

        judge = RubricJudge()
    result = run(
        pass_,  # type: ignore[arg-type]
        auto=auto,  # type: ignore[arg-type]
        db_path=db,
        max_cost_usd=max_cost,
        router=ModelRouter(),
        judge=judge,
    )
    if result["written"]:
        typer.secho(
            f"✓ 写入 {result['path']}（{result['score_before']} → {result['score_after']}，${result['cost_usd']}）",
            fg="green",
        )
    else:
        typer.secho(f"✗ 未写入：{result['reason']}", fg="yellow")


eval_app = typer.Typer()
app.add_typer(eval_app, name="eval")


@eval_app.command("l1")
def eval_l1(
    sample: int = 12,
    ab: str | None = None,
    max_cost_usd: float = typer.Option(3.0, help="本次评测成本上限（美元），超出即中止"),
    tournament: bool = typer.Option(
        False, "--tournament", help="对样本章节跑 Elo 锦标赛（ADR-0014，仅分析不进门禁）"
    ),
) -> None:
    """L1 评测。默认判官评分；--ab retrieval：两臂编译对比检索增益；--tournament：Elo 锦标赛。"""
    from nsc.eval.l1 import run_ab_retrieval, run_l1_judge, run_l1_tournament

    if ab == "retrieval":
        report = run_ab_retrieval(sample=sample, max_cost_usd=max_cost_usd)
        typer.secho(f"检索 A/B 报告：{report}", fg="green")
        return
    if tournament:
        report = run_l1_tournament(sample=sample)
        typer.secho(f"Elo 锦标赛排名：{report}", fg="green")
        return
    report = run_l1_judge(sample=sample, max_cost_usd=max_cost_usd)
    typer.secho(f"判官 L1 报告：{report}", fg="green")


@eval_app.command("build-dataset")
def eval_build(
    pass_: str = typer.Option(..., "--pass"),
    db: str = "cases/cases.db",
    out: str = "eval/datasets",
) -> None:
    """从 cases 生成 GEPA train/val（按 case 分层切分，防泄漏）。"""
    from nsc.optimize.build_dataset import build_dataset

    stats = build_dataset(db, pass_, out_dir=out)
    typer.secho(
        f"数据集 {pass_}：train={stats['n_train']}（{len(stats['train_cases'])} case）"
        f" val={stats['n_val']}（{len(stats['val_cases'])} case）→ {stats['train_path']}",
        fg="green",
    )
    if set(stats["train_cases"]) & set(stats["val_cases"]):
        typer.secho("⚠ train/val 共享 case，存在泄漏！", fg="red", err=True)
        raise typer.Exit(1)


judge_app = typer.Typer()
app.add_typer(judge_app, name="judge")


@judge_app.command("calibrate")
def judge_calibrate(
    db: str = "cases/cases.db",
    report: str = "out/judge_calibration.md",
    limit: int = 200,
    no_llm: bool = False,
    github_output: str | None = typer.Option(
        None, help="把 gate_ok 写入该文件（GitHub Actions 步骤输出）"
    ),
) -> None:
    """跑校准集 → 一致率/κ/位置偏置报告 → 写门禁状态（judge-calibration.yml）。

    --no-llm 无 DB 时仍可出报告（指标为 0，仅用于接线验证）。
    """
    from nsc.judge.calibration import run_calibration

    if no_llm:
        typer.secho("--no-llm：跳过校准，仅验证接线（指标为 0）", fg="yellow")
        return
    from nsc.judge.rubric_judge import RubricJudge

    result = run_calibration(db=db, judge=RubricJudge(), out=report, limit=limit)
    metrics = result["metrics"]
    gate = result["gate"]
    typer.secho(
        f"校准完成：{metrics['n_items']} 条，一致率 {metrics['pairwise_report']}，"
        f"κ {metrics['kappa']}，位置偏置 {metrics['position_bias']}，invalid {metrics['invalid_rate']}",
        fg="green",
    )
    if gate["gate_ok"]:
        typer.secho("门禁开启：判官可参与门禁", fg="green")
    else:
        typer.secho("门禁关闭：判官只能出报告（已写入 judge-calibration.yml）", fg="yellow")
    typer.secho(f"报告：{result['report']}", fg="green")
    if github_output:
        Path(github_output).write_text(f"gate_ok={str(gate['gate_ok']).lower()}\n", "utf-8")
        typer.secho(f"gate_ok 已写入：{github_output}", fg="cyan")


# --- Idea Bank（T-41） ---
bank_app = typer.Typer()
app.add_typer(bank_app, name="bank")


@bank_app.command("list")
def bank_list(
    project: str = typer.Option(..., "--project", help="项目 ID（默认库 out/<project>/state.db）"),
    db: str = typer.Option("", "--db", help="state 库路径；缺省 out/<project>/state.db"),
    all: bool = typer.Option(False, "--all", help="含已复活条目"),
) -> None:
    """列出项目素材银行条目（JSONL；默认只列未复活的可注入候选）。"""
    from nsc.revise import list_ideas

    db_path = Path(db) if db else Path("out") / project / "state.db"
    rows = list_ideas(db_path, project, include_revived=all)
    for row in rows:
        typer.echo(json.dumps(row, ensure_ascii=False))
    if not rows:
        typer.secho("（idea bank 为空）", fg="yellow")


@bank_app.command("revive")
def bank_revive(
    bank_id: str,
    db: str = typer.Option("", "--db", help="state 库路径"),
    project: str = typer.Option("", "--project", help="用于推导默认库 out/<project>/state.db"),
) -> None:
    """标记素材已被重新采用（revive 后不再注入 Pass 上下文）。"""
    from nsc.revise import revive

    if db:
        db_path = Path(db)
    elif project:
        db_path = Path("out") / project / "state.db"
    else:
        db_path = Path("out/state.db")
    try:
        row = revive(db_path, bank_id)
    except ValueError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e
    typer.secho(f"已复活：{row['bank_id']}（{row['node_kind']}）{row['content']}", fg="green")


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
def db_rebuild(
    db: str = "cases/cases.db",
    export_dir: str = "cases/export",
) -> None:
    """从 cases/export/*.jsonl 重建 cases.db（幂等：jsonl 无变化则 db 内容一致）。"""
    from db.migrate import rebuild

    p = rebuild(db, export_dir=export_dir)
    typer.secho(f"db 重建完成：{p}", fg="green")


@db_app.command("export")
def db_export(
    db: str = "cases/cases.db",
    export_dir: str = "cases/export",
) -> None:
    """cases.db 真相表 → cases/export/*.jsonl（幂等）。"""
    from db.migrate import export, open_db

    conn = open_db(db)
    try:
        written = export(conn, export_dir=export_dir)
    finally:
        conn.close()
    typer.secho(f"jsonl 导出完成：{len(written)} 个文件 → {export_dir}", fg="green")


@db_app.command("next-case-id")
def db_next_case_id(db: str = "cases/cases.db") -> None:
    """分配下一个 case:NNNN（永不复用）。"""
    from db.migrate import next_case_id, open_db

    conn = open_db(db)
    try:
        cid = next_case_id(conn)
    finally:
        conn.close()
    typer.echo(cid)


metrics_app = typer.Typer()
app.add_typer(metrics_app, name="metrics")


@metrics_app.command("weekly")
def metrics_weekly(write: str = "docs/metrics/") -> None:
    """D22 北极星 + D23 六个数。"""
    from nsc.metrics.collect import weekly_report

    path = weekly_report(write_dir=write)
    typer.secho(f"指标周报已写入：{path}", fg="green")


dev_app = typer.Typer()
app.add_typer(dev_app, name="dev")


@dev_app.command("split-checks")
def split_checks(batch: str) -> None:
    """把 spec/checks/_BATCH_*.yaml 拆成一文件一规则。"""
