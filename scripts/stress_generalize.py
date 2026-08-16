"""T-18 泛化压测：批量生成 brief → 编译 → final L0 门禁（D18：接入新 Profile 不改内核）。

目的：验证 `short_video_v1`（单条 30-60 秒短视频）能泛化——换产品/人群/场景后，
pipeline 仍能端到端通过 final L0，而不是只在 demo_tea 上过拟合。
接入它（以及换 brief）不得修改 src/nsc/{runtime,checker}（WORK_ORDERS T-18 验收）。

批量样本由种子模板生成（写 brief 不需要 LLM）；编译走 Profile 的 model_tiers
（p0_intake 缺省 → tier_bulk，即"tier_bulk 批量生成"）。本脚本自身无 LLM 调用，
也不在 Python 里写业务规则（业务判断都在 spec/checks）。
"""

from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROFILE = "short_video_v1"
DEFAULT_BRAND = "demo_tea"

#: brief 变化池（seed 打散组合）。内容只是"题面"，规则判断全在 spec/checks。
_PROJECT_TITLES = [
    "别眨眼",
    "三秒之后",
    "先别划走",
    "这一杯",
    "抬头一分钟",
    "下班前",
]
_PRODUCTS = [
    ("轻乳茶", "不额外加蔗糖", "下午提神"),
    ("柠檬茶", "用真茶现萃", "饭后解腻"),
    ("冷萃茶", "高山茶基", "低负担解渴"),
]
_AUDIENCES = [
    ("写字楼里 25-30 岁的女生", "怕胖又想喝奶茶"),
    ("加班到深夜的年轻人", "晚上想喝点不刺激的"),
    ("逛商场带孩子的妈妈", "想喝点干净的"),
]
_SCENES = [
    ("门店吧台前", "店员递出一杯茶"),
    ("办公室工位", "午休打开手机点单"),
    ("商场电梯口", "路过看到门店招牌"),
]
_NOTES_POOL = [
    ["不要出现竞品", "结尾要有行动号召"],
    ["不要用药效说法", "突出原料可见"],
    ["全程一个场景", "开头三秒就要有钩子"],
]

_TMPL = (
    "我们想在抖音发一条 {duration} 秒的短视频（单条，不用做成连续剧）。\n"
    "产品是{brand}的{product}，主打{claim}，适合{audience}（{pain}）。\n"
    "想拍{scene}：{action}。预算很低，一个场景、两三个演员就够。\n"
    "希望前几秒就能抓住人，不要一上来就打广告。"
)


@dataclass(slots=True)
class BriefSpec:
    """一份压测 brief 的可变化参数。"""

    title: str
    product: str
    claim: str
    audience: str
    pain: str
    scene: str
    action: str
    notes: list[str] = field(default_factory=list)


def generate_specs(count: int, seed: int) -> list[BriefSpec]:
    """确定性地生成 count 份 brief 规格（无 LLM，纯种子打散）。"""
    rng = random.Random(seed)
    specs: list[BriefSpec] = []
    for i in range(count):
        product, claim, _tag = _PRODUCTS[i % len(_PRODUCTS)]
        audience, pain = _AUDIENCES[(i * 7) % len(_AUDIENCES)]
        scene, action = _SCENES[(i * 3) % len(_SCENES)]
        specs.append(
            BriefSpec(
                title=_PROJECT_TITLES[(i * 5) % len(_PROJECT_TITLES)],
                product=product,
                claim=claim,
                audience=audience,
                pain=pain,
                scene=scene,
                action=action,
                notes=list(_NOTES_POOL[(i * 11) % len(_NOTES_POOL)]),
            )
        )
    rng.shuffle(specs)
    return specs


def spec_to_brief(spec: BriefSpec, profile: str, brand: str) -> dict[str, Any]:
    """BriefSpec → 可交给 pipeline 的 brief dict。"""
    return {
        "project_title": spec.title,
        "profile": profile,
        "brand": brand,
        "raw_request": _TMPL.format(
            duration="45",
            brand=brand,
            product=spec.product,
            claim=spec.claim,
            audience=spec.audience,
            pain=spec.pain,
            scene=spec.scene,
            action=spec.action,
        ),
        "episode_count": 1,  # short_video_v1 只支持单条
        "notes": spec.notes,
    }


# ---------------------------------------------------------------------------
# 编译 + 门禁
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StressResult:
    index: int
    title: str
    status: str = "ok"  # ok | failed
    reason: str = ""
    findings: int = 0
    rules_evaluated: int = 0
    cost_usd: float = 0.0
    wall_ms: int = 0


def _ctx_for(brief: dict[str, Any], out_dir: Path, index: int) -> Any:
    """构造 PassContext（同 nsc.cli._make_ctx，仅 out_dir/run 隔离）。"""
    from nsc.passes import PassContext
    from nsc.runtime.models import ModelRouter
    from nsc.runtime.provenance import RunsStore, spec_fingerprint

    profile = yaml.safe_load(Path(f"profiles/{brief['profile']}.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path(f"brands/{brief['brand']}/brand.yaml").read_text("utf-8"))
    spec_files = list(Path("spec").rglob("*.py")) + list(Path("spec").rglob("*.yaml"))
    prompts = list(Path("prompts").glob("*.json")) if Path("prompts").exists() else []
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=ModelRouter(),
        store=RunsStore(out_dir / f"runs/{index:03d}.db"),
        ruleset_ver=spec_fingerprint(list(Path("spec/checks").rglob("*.yaml")))[:12],
        spec_sha=spec_fingerprint(spec_files)[:12],
        promptset_ver=spec_fingerprint(prompts)[:12] if prompts else "seed",
        out_dir=out_dir / f"cases/{index:03d}",
        seed=index,
    )


def compile_one(brief: dict[str, Any], out_dir: Path, index: int) -> StressResult:
    """编译一份 brief 并跑 final L0。返回 status/reason/findings/cost。"""
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.passes import PassFailure
    from nsc.passes.pipeline import run_pipeline
    from nsc.runtime.ir_io import build_view

    ctx = _ctx_for(brief, out_dir, index)
    t0 = time.monotonic()
    try:
        ir = run_pipeline(ctx)
    except PassFailure as e:
        return StressResult(index, brief.get("project_title", ""), "failed", e.reason)
    wall_ms = int((time.monotonic() - t0) * 1000)
    runs = ctx.store.runs()
    cost = round(sum(float(str(r.get("cost_usd") or 0)) for r in runs), 4)
    # final 阶段规则再跑一遍，统计 warn/info（block 已在 pipeline 内拦截）
    view = build_view(ir.model_dump(), ctx.profile, ctx.brand)
    rs = RuleSet.load(
        profile_id=str(ctx.profile.get("id", "")),
        industry=str(ctx.brand.get("industry", "")),
        brand_id=str(ctx.brand.get("brand_id", "")),
        stage="final",
        enabled_domains=list(ctx.profile.get("enabled_check_domains", [])),
    )
    rep = evaluate(rs, view, ctx={"profile": ctx.profile, "brand": ctx.brand})
    return StressResult(
        index,
        brief.get("project_title", ""),
        "ok",
        findings=len(rep.findings),
        rules_evaluated=rep.rules_evaluated,
        cost_usd=cost,
        wall_ms=wall_ms,
    )


def render_report(
    results: list[StressResult], profile: str, count: int, seed: int, out: Path
) -> Path:
    """逐条结果 → markdown 报告（可单测，无 LLM）。"""
    ok = [r for r in results if r.status == "ok"]
    fail = [r for r in results if r.status == "failed"]
    total_cost = round(sum(r.cost_usd for r in results), 4)
    lines = [
        f"# 泛化压测报告（T-18 · {profile}）",
        "",
        f"- 样本：{len(results)} 份 brief（seed={seed}，count={count}）",
        f"- 通过 final L0：{len(ok)}/{len(results)}",
        f"- 编译失败：{len(fail)}",
        f"- 累计成本：${total_cost}",
        "",
        "| # | 标题 | 状态 | findings | 规则数 | 成本$ | 耗时ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.index} | {r.title} | {r.status} | {r.findings} | "
            f"{r.rules_evaluated} | {r.cost_usd} | {r.wall_ms} |"
        )
    if fail:
        lines.append("")
        lines.append("## 失败明细")
        lines.append("")
        for r in fail:
            lines.append(f"- #{r.index} {r.title}：{r.reason}")
        lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), "utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-18 泛化压测（批量 brief → 编译 → final L0）")
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--brand", default=DEFAULT_BRAND)
    ap.add_argument("--count", type=int, default=5, help="批量生成几份 brief")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="out/stress")
    ap.add_argument("--dry-run", action="store_true", help="只生成 brief 不调 LLM（接线验证）")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    specs = generate_specs(args.count, args.seed)
    briefs = [spec_to_brief(s, args.profile, args.brand) for s in specs]
    if args.dry_run:
        for i, b in enumerate(briefs):
            print(f"#{i} {b['project_title']} · {b['raw_request'][:40]}…")
        print(f"dry-run：生成 {len(briefs)} 份 brief，未调用 LLM。")
        return 0

    results: list[StressResult] = []
    for i, b in enumerate(briefs):
        r = compile_one(b, out_dir, i)
        results.append(r)
        print(f"#{i} {r.title}: {r.status}" + (f"（{r.reason[:60]}）" if r.reason else ""))
    report = render_report(results, args.profile, args.count, args.seed, out_dir / "report.md")
    print(f"压测报告：{report}")
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
