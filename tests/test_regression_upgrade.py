"""T-42 端到端回归验收（stub，无 LLM）。

覆盖本次长篇工程化升级（docs/UPGRADE_PLAN_2026-08-17.md）的落地面：
  1. golden IR × 全八域规则零 block（warn 基线紧约束防回归膨胀）；
  2. 规则台账对账：落盘 YAML 文件数 == RuleSet 加载数，且在 90 上限内；
  3. IR 1.1 迁移：1.0 golden 直接 model_validate 即升级，四张新表默认空；
  4. 新模块（textstats / revise / context / eval.elo）可导入且关键符号在位。
"""

from __future__ import annotations

import importlib
from collections import Counter
from pathlib import Path

import yaml

#: 验收口径启用全部八个域（profile 的 enabled_check_domains 仍为七域，
#: prose 域由 ADR-0011 新增，验收时显式并入）。
ALL_DOMAINS = [
    "structure",
    "brand",
    "dialogue",
    "novel",
    "prose",
    "compliance",
    "fact",
    "producibility",
]

#: 规则预算（spec/BUDGETS.yaml `max_active_check_rules: 90`）。
MAX_RULES = 90
MIN_RULES = 70


def _load_ruleset():
    from nsc.checker.interpreter import RuleSet

    return RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage="final",
        enabled_domains=ALL_DOMAINS,
    )


def test_golden_zero_block(profiles, demo_brand, golden_ir):
    """golden IR 过全部 79 条规则：零 block；warn 不超基线+2。"""
    from nsc.checker.interpreter import evaluate
    from nsc.runtime.ir_io import build_view

    profile = profiles["short_drama_v1"]
    view = build_view(golden_ir, profile, demo_brand)
    rep = evaluate(_load_ruleset(), view, ctx={"profile": profile, "brand": demo_brand})

    assert rep.errors == [], rep.errors
    blocks = [f for f in rep.findings if f.severity == "block"]
    assert blocks == [], "\n".join(f"[{f.rule_id}] {f.message}" for f in blocks)

    warns = [f for f in rep.findings if f.severity == "warn"]
    infos = [f for f in rep.findings if f.severity == "info"]
    # warn 基线 = 21（2026-08-17 实测）。全部来自 golden 1.0 fixture 缺 Wave B
    # 字段与章节样本量小：FCT-006×6 / STR-016×5 / STR-017×6 / PRS-001×2 / PRS-002×2。
    # 上限取基线+2 以防回归膨胀；若基线下移（fixture 补齐新字段），请同步收紧此值。
    assert len(warns) <= 23, f"warn={len(warns)} 超过基线上限 23（当前基线 21）:\n" + "\n".join(
        sorted(f.rule_id for f in warns)
    )
    print(f"golden 零 block 达成：warn={len(warns)}（基线 21） info={len(infos)}")


def test_rule_inventory():
    """规则台账对账：落盘数 == 加载数 == 79；新规则 ID 全部在位。"""
    # 落盘规则数 = spec/checks/**/*.yaml（非 `_` 前缀）中 id 非空且 active 的文档数，
    # 与 RuleSet.load 的扫描口径一致（支持单文件多 YAML 文档）。
    on_disk = 0
    for p in sorted(Path("spec/checks").rglob("*.yaml")):
        if p.name.startswith("_"):
            continue
        for doc in yaml.safe_load_all(p.read_text("utf-8")):
            if doc and doc.get("id") and doc.get("status", "active") == "active":
                on_disk += 1

    rs = _load_ruleset()
    ids = {r["id"] for r in rs.rules}
    assert len(rs.rules) == on_disk, f"落盘 {on_disk} 条 vs 加载 {len(rs.rules)} 条"
    assert MIN_RULES <= on_disk <= MAX_RULES, on_disk
    assert (
        on_disk == 81
    )  # 48 存量 + 23 Wave A + 7 Wave B + 1 校正（UPGRADE_PLAN §5）+ 2 CRAFT（2026-08-27 R2 正向契约）

    by_domain = Counter(r["domain"] for r in rs.rules)
    assert by_domain["prose"] == 16, by_domain  # ADR-0011 新域整建制

    expected_new = (
        [f"CMP-{i:03d}" for i in range(3, 8)]  # 平台合规（Wave A）
        + [f"STR-{i:03d}" for i in range(14, 19)]  # 承重红线 + 悬念闭环（Wave A/B）
        + ["FCT-003", "FCT-006", "FCT-007", "DLG-008"]  # Wave B
        + [f"PRS-{i:03d}" for i in range(1, 17)]  # prose 域 16 条（Wave A）
    )
    missing = sorted(rid for rid in expected_new if rid not in ids)
    assert missing == [], f"新增规则缺失: {missing}"


def test_ir11_tables_present(golden_ir):
    """IR 1.1 迁移：1.0 golden 允许缺新表，validate 即升级且四表默认空。"""
    from spec.ir.container import NarrativeIR

    for key in ("facts", "threads", "state_variables", "dark_threads"):
        assert key not in golden_ir  # 顶层允许缺新表（1.0 落盘物）
    ir = NarrativeIR.model_validate(golden_ir)
    assert ir.schema_version == "1.1"  # ADR-0012：before-validator 无损迁移
    assert ir.facts == []
    assert ir.threads == []
    assert ir.state_variables == []
    assert ir.dark_threads == []


def test_modules_importable():
    """升级新增模块全部可导入，关键符号在位。"""
    textstats = importlib.import_module("nsc.textstats")
    revise = importlib.import_module("nsc.revise")
    context = importlib.import_module("nsc.context")
    elo = importlib.import_module("nsc.eval.elo")
    for mod, names in (
        (revise, ("apply_patches", "decide", "save_snapshot", "build_brief")),
        (context, ("assemble", "compress_history")),
        (elo, ("run_tournament",)),
        (textstats, ("para_cv", "sent_cv", "chapter_ngram_repeats")),
    ):
        for name in names:
            obj = getattr(mod, name, None)
            assert callable(obj), f"{mod.__name__}.{name} 不存在或不可调用"
