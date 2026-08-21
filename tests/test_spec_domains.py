"""SW-02 spec_sha 分域哈希：任何 spec 小编订不得使全量内容缓存失效。

- provenance.spec_domain_fingerprints：按 spec 顶层子域分别取指纹；
- PassContext.cache_versions 的 spec_sha 只取影响生成结构的域（ir+passes），
  checks 域由既有的 ruleset_ver 单独覆盖，rubrics/feedback/rules 等不进缓存键；
- runs 表的 spec_sha 仍是全量指纹（provenance 不弱化）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from nsc.runtime.provenance import spec_domain_fingerprints


def _mk_spec(root: Path) -> None:
    (root / "checks").mkdir(parents=True)
    (root / "rubrics").mkdir()
    (root / "passes").mkdir()
    (root / "ir").mkdir()
    (root / "checks" / "c1.yaml").write_text("a: 1\n", "utf-8")
    (root / "rubrics" / "r1.yaml").write_text("b: 1\n", "utf-8")
    (root / "passes" / "signatures.py").write_text("x = 1\n", "utf-8")
    (root / "ir" / "nodes.py").write_text("y = 1\n", "utf-8")
    (root / "BUDGETS.yaml").write_text("lines: {}\n", "utf-8")


def test_domain_fingerprints_isolate_edits(tmp_path):
    root = tmp_path / "spec"
    _mk_spec(root)
    before = spec_domain_fingerprints(root)
    assert set(before) == {"checks", "rubrics", "passes", "ir", "root"}

    (root / "rubrics" / "r1.yaml").write_text("b: 2\n", "utf-8")  # 只动 rubrics
    after = spec_domain_fingerprints(root)
    changed = {d for d in before if before[d] != after[d]}
    assert changed == {"rubrics"}, "小编订必须只让所属域指纹变化"


def _ctx(tmp_path, spec_shas=None):
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    return PassContext(
        profile={"version": "1", "model_tiers": {}},
        brand={"version": "1"},
        router=None,
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="r",
        spec_sha="full123",
        spec_shas=spec_shas or {},
    )


def test_cache_versions_uses_scoped_domains(tmp_path):
    full = {"ir": "ir1", "passes": "pa1", "rubrics": "ru1", "checks": "ck1", "rules": "rl1"}
    ctx = _ctx(tmp_path, full)
    assert ctx.cache_versions("p3_beatsheet")["spec_sha"] == "ir:ir1|passes:pa1"
    # 与生成无关的域变化不进缓存键（同 Pass 前后比对）
    ctx2 = _ctx(tmp_path, {**full, "rubrics": "ru2", "checks": "ck2"})
    assert (
        ctx2.cache_versions("p5_dialogue")["spec_sha"]
        == ctx.cache_versions("p5_dialogue")["spec_sha"]
    )
    assert (
        ctx2.cache_versions("p3_beatsheet")["spec_sha"]
        == ctx.cache_versions("p3_beatsheet")["spec_sha"]
    )
    # 影响生成结构的域变化必须进缓存键
    ctx3 = _ctx(tmp_path, {**full, "ir": "ir2"})
    assert (
        ctx3.cache_versions("p3_beatsheet")["spec_sha"]
        != ctx.cache_versions("p3_beatsheet")["spec_sha"]
    )


def test_rules_domain_only_invalidates_p5(tmp_path):
    """review 修正：p5 的 self-check 读 spec/rules/L3_canonical（VOICE RULES），
    rules 域编辑必须使 p5 缓存失效；不读该域的 pass（p3）不受牵连。"""
    full = {"ir": "ir1", "passes": "pa1", "rubrics": "ru1", "checks": "ck1", "rules": "rl1"}
    ctx = _ctx(tmp_path, full)
    changed = _ctx(tmp_path, {**full, "rules": "rl2"})
    assert (
        changed.cache_versions("p5_dialogue")["spec_sha"]
        != ctx.cache_versions("p5_dialogue")["spec_sha"]
    ), "rules 域变化必须使 p5 缓存失效"
    assert (
        changed.cache_versions("p3_beatsheet")["spec_sha"]
        == ctx.cache_versions("p3_beatsheet")["spec_sha"]
    ), "rules 域变化不得牵连不读该域的 pass"
    assert ctx.cache_versions("p5_dialogue")["spec_sha"] == "ir:ir1|passes:pa1|rules:rl1"


def test_partial_domain_map_falls_back_to_full_sha(tmp_path):
    """review 修正：半套分域指纹（缺必需域）必须回退全量 spec_sha，
    不得拼出 'ir:|passes:' 之类静默削弱缓存失效条件的键。"""
    ctx = _ctx(tmp_path, {"ir": "ir1"})  # 缺 passes（且缺 p5 需要的 rules）
    assert ctx.cache_versions("p3_beatsheet")["spec_sha"] == "full123"
    assert ctx.cache_versions("p5_dialogue")["spec_sha"] == "full123"


def test_cache_versions_falls_back_to_full_sha(tmp_path):
    """未提供分域指纹（旧测试/旧调用方）时保持原语义：全量 spec_sha。"""
    ctx = _ctx(tmp_path)
    assert ctx.cache_versions("p1_bible")["spec_sha"] == "full123"


def test_make_ctx_wires_domain_fingerprints(tmp_path):
    from nsc.cli import _make_ctx

    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    ctx = _make_ctx(brief, tmp_path / "out")
    assert {"ir", "passes", "checks"} <= set(ctx.spec_shas)
    scoped = ctx.cache_versions("p3_beatsheet")["spec_sha"]
    assert scoped != ctx.spec_sha, "分域指纹接线后，缓存键不得再混入全量 spec_sha"
    assert scoped.startswith("ir:") and "passes:" in scoped
