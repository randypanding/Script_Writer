"""nsc CLI —— CLI 是唯一 UI（第十四章：P2 前不做 Web UI）。"""
from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

# --- 编译 ---
@app.command()
def run(brief: str, profile: str = "", out: str = "out/", rerank: bool = False) -> None:
    """端到端编译：brief → IR → 小说 → 剧本。"""


@app.command()
def recompile(ir: str, episode: int | None = None, scene: str | None = None,
              from_pass: str = "", force: bool = False) -> None:
    """局部重编译（依赖闭包由 spec/passes/dep_graph.yaml 给出）。"""


@app.command()
def check(ir: str, stage: str = "final", fmt: str = "text") -> None:
    """L0 检查。exit code：0 全绿 / 1 有 block / 2 规则本身报错。"""


@app.command()
def render(ir: str, target: list[str] = typer.Option(None)) -> None:
    """渲染交付物（含锚点）。"""


# --- 反馈与飞轮 ---
feedback_app = typer.Typer(); app.add_typer(feedback_app, name="ingest")
@feedback_app.command("docx")
def ingest_docx(path: str, case: str) -> None: ...
@feedback_app.command("text")
def ingest_text(path: str, case: str) -> None: ...

mine_app = typer.Typer(); app.add_typer(mine_app, name="mine")
@mine_app.command("run")
def mine_run(open_pr: bool = False) -> None:
    """L0→L1 聚类归纳 → L1→L2 验证 → 输出候选规则 PR。"""
@mine_app.command("retire")
def mine_retire() -> None: ...

# --- 优化与评测 ---
@app.command()
def optimize(pass_: str = typer.Option(..., "--pass"), auto: str = "light") -> None: ...

eval_app = typer.Typer(); app.add_typer(eval_app, name="eval")
@eval_app.command("l1")
def eval_l1(sample: int = 12) -> None: ...
@eval_app.command("build-dataset")
def eval_build(pass_: str = typer.Option(..., "--pass")) -> None: ...

judge_app = typer.Typer(); app.add_typer(judge_app, name="judge")
@judge_app.command("calibrate")
def judge_calibrate(report: str = "out/judge_calibration.md") -> None: ...

# --- 冷启动 ---
annotate_app = typer.Typer(); app.add_typer(annotate_app, name="annotate")
@annotate_app.command("ingest")
def annotate_ingest(source: str) -> None:
    """逆向标注：字幕/转写 → Narrative IR（D15）。遵守 COMPLIANCE.md §1。"""
@annotate_app.command("priors")
def annotate_priors(out: str = "profiles/_mined_priors.yaml") -> None: ...
@annotate_app.command("roundtrip")
def annotate_roundtrip(case: str) -> None:
    """往返重建评测（D16）：原片→IR→重生成→对比。IR 设计的唯一无监督信号。"""

# --- 数据与指标 ---
db_app = typer.Typer(); app.add_typer(db_app, name="db")
@db_app.command("rebuild")
def db_rebuild() -> None: ...
@db_app.command("export")
def db_export() -> None: ...

metrics_app = typer.Typer(); app.add_typer(metrics_app, name="metrics")
@metrics_app.command("weekly")
def metrics_weekly(write: str = "docs/metrics/") -> None:
    """D22 北极星 + D23 六个数。"""

dev_app = typer.Typer(); app.add_typer(dev_app, name="dev")
@dev_app.command("split-checks")
def split_checks(batch: str) -> None:
    """把 spec/checks/_BATCH_*.yaml 拆成一文件一规则。"""