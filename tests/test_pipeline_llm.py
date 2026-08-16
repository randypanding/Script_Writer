"""T-07 端到端验收（需要真实 LLM，标 llm；CI 的 test-fast 不跑）。

nsc run --brief examples/demo_tea/brief.yaml 端到端产出 6 集，L0 全绿。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.llm


def test_run_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setenv("NSC_CACHE_DIR", str(tmp_path / "cache"))
    from nsc.cli import _load_assets, _make_ctx
    from nsc.passes.pipeline import run_pipeline
    from spec.ir.invariants import check_all

    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    ctx = _make_ctx(brief, tmp_path / "out")
    ir = run_pipeline(ctx)

    assert len(ir.episodes) == 6
    assert len(ir.chapters) == 6

    # L0 全绿（不变量 + 全部声明式规则）
    profile, brand = _load_assets("short_drama_v1", "demo_tea")
    assert check_all(ir, profile, stage="final") == []
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.runtime.ir_io import build_view

    view = build_view(ir.model_dump(), profile, brand)
    rs = RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage="final",
        enabled_domains=profile["enabled_check_domains"],
    )
    rep = evaluate(rs, view, ctx={"profile": profile, "brand": brand})
    assert rep.errors == []
    assert not rep.blocked, rep.as_feedback_text()

    # 交付物落盘
    out_dir = tmp_path / "out" / ir.project.title
    assert (out_dir / "novel.md").exists()
    assert (out_dir / "script.md").exists()
    assert (out_dir / "manifest.json").exists()
    json.loads((out_dir / "manifest.json").read_text("utf-8"))
