"""T-38 快照接线测试：run_pipeline / recompile_episode 末尾把 IR 落盘 state.db。

验收（WORK_ORDERS T-38）：stub 管线跑完后 out/<project_id>/state.db 存在且可
list_snapshots / best_snapshot；recompile 后快照数 +1；rollback_to 取回的
ir_json 可 model_validate 成 NarrativeIR；check 有 block 时仍存（stage=final-blocked）；
快照失败不破坏主管线。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from tests.test_pipeline_stub import FullStubRouter
from tests.test_recompile import _make_stub

GOLDEN_PATH = Path("tests/fixtures/golden/demo_tea_ir.json")


def _assets() -> tuple[dict, dict, dict]:
    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    return profile, brand, brief


@pytest.fixture()
def _no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))


@pytest.fixture()
def run_ctx(tmp_path, monkeypatch, _no_cache):
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile, brand, brief = _assets()
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=FullStubRouter(),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="t",
        spec_sha="t",
        out_dir=tmp_path / "out",
    )


@pytest.fixture()
def recompile_ctx(tmp_path, monkeypatch, _no_cache):
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile, brand, _brief = _assets()
    return PassContext(
        profile=profile,
        brand=brand,
        router=_make_stub(),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="t",
        spec_sha="t",
        out_dir=tmp_path / "out",
    )


def test_run_pipeline_writes_state_db(run_ctx):
    from nsc.passes.pipeline import run_pipeline
    from nsc.revise import best_snapshot, list_snapshots, rollback_to
    from spec.ir.container import NarrativeIR

    ir = run_pipeline(run_ctx)
    pid = ir.project.id
    db = run_ctx.out_dir / pid / "state.db"
    assert db.exists(), "stub 管线跑完后 out/<project_id>/state.db 应存在"

    stages = {r["stage"] for r in list_snapshots(db, pid)}
    assert "after_p3" in stages, "p3 全季后处理完成后应存一份快照"
    assert "final" in stages, "final 检查通过后应存一份快照"

    best = best_snapshot(db, pid, "final")
    assert best is not None
    assert best["block"] == 0 and best["warn"] == 0  # stub 管线全绿

    restored = NarrativeIR.model_validate(json.loads(best["ir_json"]))
    assert restored.project.id == pid

    back = rollback_to(db, best["id"])
    assert NarrativeIR.model_validate(json.loads(back["ir_json"]))


def test_recompile_appends_final_snapshot(recompile_ctx):
    from nsc.passes.pipeline import recompile_episode
    from nsc.revise import list_snapshots
    from spec.ir.container import NarrativeIR

    old = NarrativeIR.model_validate(json.loads(GOLDEN_PATH.read_text("utf-8")))
    pid = old.project.id
    db = recompile_ctx.out_dir / pid / "state.db"
    assert list_snapshots(db, pid, "final") == []

    recompile_episode(recompile_ctx, old, 5)
    first = list_snapshots(db, pid, "final")
    assert len(first) == 1
    assert NarrativeIR.model_validate(json.loads(first[0]["ir_json"]))

    # 第二次重编译（provenance 变化 → ir_json 不同）→ final 快照 +1
    recompile_ctx.router = _make_stub()
    recompile_episode(recompile_ctx, old, 5)
    assert len(list_snapshots(db, pid, "final")) == len(first) + 1


def test_final_blocked_snapshot_still_saved(run_ctx, monkeypatch):
    """check 有 block：快照仍落盘（回退需要），stage 标 final-blocked，管线照常抛错。"""
    from nsc.passes import PassFailure, pipeline
    from nsc.passes.pipeline import run_pipeline
    from nsc.revise import list_snapshots

    real = pipeline.check_all

    class _V:
        node_id = "node_x"
        message = "INV-TEST 假违规"

    def fake(ir, profile, stage="final"):
        return [_V()] if stage == "final" else real(ir, profile, stage=stage)

    monkeypatch.setattr(pipeline, "check_all", fake)
    with pytest.raises(PassFailure):
        run_pipeline(run_ctx)

    db = next(run_ctx.out_dir.glob("*/state.db"))
    pid = db.parent.name
    blocked = list_snapshots(db, pid, "final-blocked")
    assert len(blocked) == 1
    assert blocked[0]["block"] >= 1  # 不变量违规计入 block


def test_snapshot_failure_never_breaks_pipeline(run_ctx, monkeypatch, capsys):
    from nsc.passes import pipeline

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pipeline, "save_snapshot", boom)
    ir = pipeline.run_pipeline(run_ctx)  # 快照失败不能吞掉主管线
    assert len(ir.episodes) == 6
    assert "快照" in capsys.readouterr().err  # 失败记 stderr 一行
