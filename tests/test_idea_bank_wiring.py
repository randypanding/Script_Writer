"""T-41 Idea Bank 接线 + plateau 停止测试。

验收（WORK_ORDERS T-41）：
- recompile 替换 beats 前 deposit 进 bank（node_kind=beat, reason=recompile_replace）
- 下一次 recompile 的 p3 LLM 输入含"可复活素材"层；revive 后不再注入
- should_stop 真值表（3 轮内不停、第 3 轮 Δ<0.03 停、第 6 轮强制停）
- gepa_run 停止原因透传（plateau_reason / cycles）
- CLI `nsc bank list|revive`
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest

import nsc.runtime.cache as cache_mod
from tests.test_gepa_run import _mk_db, _seed_revisions
from tests.test_recompile import _make_stub

GOLDEN_PATH = Path("tests/fixtures/golden/demo_tea_ir.json")


class CaptureRouter:
    """包装顺序回放桩，捕获每次 LLM 调用的输入 dict。"""

    def __init__(self, inner):
        self.inner = inner
        self.inputs: list[dict] = []

    def resolve(self, tier):
        return self.inner.resolve(tier)

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        self.inputs.append(json.loads(messages[-1]["content"]))
        return self.inner.complete(tier, messages, json_mode=json_mode, seed=seed)

    def p3_inputs(self) -> list[dict]:
        return [i for i in self.inputs if "placement_for_episode" in i]


def _golden_ep5_beat_summaries() -> list[str]:
    raw = json.loads(GOLDEN_PATH.read_text("utf-8"))
    ep = next(e for e in raw["episodes"] if e["no"] == 5)
    scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep["id"]}
    return [b["summary"] for b in raw["beats"] if b["parent_id"] in scene_ids]


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    import yaml

    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        router=_make_stub(),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="t",
        spec_sha="t",
        out_dir=tmp_path / "out",
    )


def _recompile(ctx, router) -> None:
    from nsc.passes.pipeline import recompile_episode
    from spec.ir.container import NarrativeIR

    ctx.router = router
    old = NarrativeIR.model_validate(json.loads(GOLDEN_PATH.read_text("utf-8")))
    recompile_episode(ctx, old, 5)


def _state_db(ctx, old_ir) -> Path:
    return ctx.out_dir / old_ir.project.id / "state.db"


# ---------------------------------------------------------------- idea bank 往返
def test_recompile_deposits_deleted_beats(ctx):
    from nsc.revise import list_ideas
    from spec.ir.container import NarrativeIR

    old = NarrativeIR.model_validate(json.loads(GOLDEN_PATH.read_text("utf-8")))
    pid = old.project.id
    db = _state_db(ctx, old)
    assert list_ideas(db, pid) == []

    _recompile(ctx, _make_stub())

    ideas = list_ideas(db, pid)
    assert ideas, "recompile 替换 beats 前应 deposit 进 idea bank"
    summaries = _golden_ep5_beat_summaries()
    for row in ideas:
        assert row["node_kind"] == "beat"
        assert row["reason"] == "recompile_replace"
        assert row["content"] in summaries
        assert row["source_node_id"]


def test_revivable_layer_injected_then_suppressed_after_revive(ctx):
    from nsc.revise import list_ideas, revive
    from spec.ir.container import NarrativeIR

    old = NarrativeIR.model_validate(json.loads(GOLDEN_PATH.read_text("utf-8")))
    db = _state_db(ctx, old)

    # 第一轮：deposit 落库；第二轮：p3 输入应含素材层
    _recompile(ctx, _make_stub())
    cap = CaptureRouter(_make_stub())
    _recompile(ctx, cap)
    p3s = cap.p3_inputs()
    assert p3s, "重编译应触发 p3 LLM 调用"
    injected = [i for i in p3s if "revivable_ideas" in i]
    assert injected, "bank 有未复活条目时 p3 输入应附素材层"
    assert "(beat)" in injected[0]["revivable_ideas"]
    assert any(s in injected[0]["revivable_ideas"] for s in _golden_ep5_beat_summaries())

    # revive 全部后：下一轮不再注入
    for row in list_ideas(db, old.project.id):
        revive(db, row["bank_id"])
    cap2 = CaptureRouter(_make_stub())
    _recompile(ctx, cap2)
    assert all("revivable_ideas" not in i for i in cap2.p3_inputs())


# ---------------------------------------------------------------- plateau 真值表
def test_should_stop_truth_table():
    from nsc.optimize.plateau import should_stop

    # 3 轮内不停（轮数不足 min_cycles）
    assert should_stop([0.5]) == (False, "")
    assert should_stop([0.5, 0.52]) == (False, "")
    # 第 3 轮 Δ<0.03 → plateau
    assert should_stop([0.5, 0.52, 0.521]) == (True, "plateau")
    # 第 3 轮但 Δ≥0.03 → 继续
    assert should_stop([0.5, 0.52, 0.9]) == (False, "")
    # Δ 恰等于 delta（0.03）不视为 plateau（严格小于）
    assert should_stop([0.5, 0.5, 0.53]) == (False, "")
    # 第 6 轮强制停（max_cycles 优先于 plateau）
    assert should_stop([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]) == (True, "max_cycles")
    assert should_stop([0.5, 0.5, 0.5, 0.5, 0.5, 0.5]) == (True, "max_cycles")
    # 第 5 轮仍在上升 → 不停
    assert should_stop([0.1, 0.2, 0.3, 0.4, 0.5]) == (False, "")


# ---------------------------------------------------------------- gepa_run 透传
def _seed_db(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    _seed_revisions(conn)
    conn.close()
    return db


def test_gepa_run_plateau_reason_passthrough(tmp_path):
    from nsc.optimize.gepa_run import run

    db = _seed_db(tmp_path)

    def flat_runner(**kw):
        return {
            "instruction": "持平指令",
            "score_before": 0.5,
            "score_after": 0.55,
            "cost_usd": 0.5,
            "detailed_results": None,
        }

    res = run(
        "p3_beatsheet",
        db_path=db,
        dataset_dir=tmp_path / "ds",
        out_dir=tmp_path / "p",
        rejected_dir=tmp_path / "r",
        log_root=tmp_path / "l",
        gepa_runner=flat_runner,
    )
    assert res["plateau_reason"] == "plateau"
    assert res["cycles"] == 3  # [0.55, 0.55, 0.55]：第 3 轮 Δ=0 停
    assert res["written"]


def test_gepa_run_max_cycles_passthrough(tmp_path):
    from nsc.optimize.gepa_run import run

    db = _seed_db(tmp_path)
    calls = {"n": 0}

    def rising_runner(**kw):
        calls["n"] += 1
        return {
            "instruction": f"指令v{calls['n']}",
            "score_before": 0.5,
            "score_after": 0.5 + 0.1 * calls["n"],
            "cost_usd": 0.1,
            "detailed_results": None,
        }

    res = run(
        "p3_beatsheet",
        db_path=db,
        dataset_dir=tmp_path / "ds",
        out_dir=tmp_path / "p",
        rejected_dir=tmp_path / "r",
        log_root=tmp_path / "l",
        gepa_runner=rising_runner,
    )
    assert res["plateau_reason"] == "max_cycles"
    assert res["cycles"] == 6  # 每轮 +0.1 从不 plateau → 6 轮上限


# ---------------------------------------------------------------- CLI
def test_bank_cli_list_and_revive(tmp_path):
    from typer.testing import CliRunner

    from nsc.cli import app
    from nsc.revise import deposit

    db = tmp_path / "state.db"
    bid = deposit(db, "p1", "beat", "雨夜分手的 Beat", quality_note="情绪强")
    deposit(db, "p1", "scene", "天台对峙")

    cli = CliRunner()
    res = cli.invoke(app, ["bank", "list", "--project", "p1", "--db", str(db)])
    assert res.exit_code == 0
    rows = [json.loads(x) for x in res.output.splitlines() if x.startswith("{")]
    assert len(rows) == 2
    assert rows[0]["bank_id"] == bid

    res2 = cli.invoke(app, ["bank", "revive", bid, "--db", str(db)])
    assert res2.exit_code == 0
    assert "雨夜分手" in res2.output

    # 已复活 / 不存在 → 非零退出码
    assert cli.invoke(app, ["bank", "revive", bid, "--db", str(db)]).exit_code == 1
    assert cli.invoke(app, ["bank", "revive", "nosuchid", "--db", str(db)]).exit_code == 1
