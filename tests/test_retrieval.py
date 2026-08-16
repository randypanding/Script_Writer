"""T-16 验收：1 档案例检索。

关键断言（COMPLIANCE §1）：`usable_as_example=0` 的条目**绝不**作为示例注入。
pipeline 注入测试用 golden 桩路由跑完整流水线，断言 retrieved_cases 到达 p1/p2/p3/p5；
--no-retrieval（ctx.retrieval=None）等价物断言为空串。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from nsc.retrieval import RetrievalService, builder, pool, search
from nsc.retrieval.pool import RetrievalItem

MINIMAL_IR = None  # 惰性加载


def _minimal_ir() -> dict:
    global MINIMAL_IR
    if MINIMAL_IR is None:
        from tests.strategies import build_minimal_ir

        MINIMAL_IR = build_minimal_ir(n_episodes=1)
    return MINIMAL_IR


def _upsert(tmp_path, items) -> Path:
    db = tmp_path / "pool.db"
    conn = pool.connect(db)
    try:
        pool.upsert_items(conn, items)
    finally:
        conn.close()
    return db


def _item(item_id: str, *, usable: bool = True, quality: float = 1.0) -> RetrievalItem:
    return RetrievalItem(
        item_id=item_id,
        case_id="case:1",
        unit_kind="beat_sequence",
        industry="beverage",
        profile_id="short_drama_v1",
        content=f"{item_id} 的内容",
        quality=quality,
        usable_as_example=usable,
    )


# ---------------------------------------------------------------- COMPLIANCE §1
def test_search_never_returns_unusable(tmp_path):
    """usable_as_example=0 的条目绝不出现在检索结果里。"""
    db = _upsert(
        tmp_path,
        [_item("usable-1", usable=True, quality=0.5), _item("banned-1", usable=False, quality=1.0)],
    )
    conn = pool.connect(db)
    try:
        hits = search(conn, "查询", k=5)
    finally:
        conn.close()
    assert {h.item_id for h in hits} == {"usable-1"}
    assert all(h.usable_as_example for h in hits)


def test_search_filters_unit_kind_and_industry(tmp_path):
    other = RetrievalItem(
        item_id="other",
        case_id="case:2",
        unit_kind="chapter",
        industry="beauty",
        profile_id="short_drama_v1",
        content="别类",
    )
    db = _upsert(tmp_path, [_item("beat-1"), other])
    conn = pool.connect(db)
    try:
        hits = search(conn, "查询", k=5, unit_kind="beat_sequence", industry="beverage")
    finally:
        conn.close()
    assert [h.item_id for h in hits] == ["beat-1"]


# ---------------------------------------------------------------- builder
def test_builder_annotated_snapshot_marked_unusable(tmp_path):
    """annotated 快照的产物 usable_as_example=0（COMPLIANCE §1）；golden=1。"""
    ir = json.dumps(_minimal_ir(), ensure_ascii=False)
    db = tmp_path / "snap.db"
    conn = pool.connect(db)
    try:
        conn.execute(
            """INSERT INTO cases(case_id, brand_id, profile_id, industry, title, source, status, created_at)
               VALUES ('case:1','demo_tea','short_drama_v1','beverage','t','client','draft','2026-01-01')"""
        )
        conn.execute(
            "INSERT INTO ir_snapshots(snapshot_id, case_id, kind, round, ir_json, spec_sha, created_at) "
            "VALUES ('snap-golden','case:1','golden',1,?,'x','2026-01-01')",
            (ir,),
        )
        conn.execute(
            "INSERT INTO ir_snapshots(snapshot_id, case_id, kind, round, ir_json, spec_sha, created_at) "
            "VALUES ('snap-ann','case:1','annotated',1,?,'x','2026-01-01')",
            (ir,),
        )
        conn.commit()
    finally:
        conn.close()

    items = builder.build_pool_from_snapshots(db)
    golden = [it for it in items if it.meta.get("snapshot_id") == "snap-golden"]
    ann = [it for it in items if it.meta.get("snapshot_id") == "snap-ann"]
    assert golden and ann, "minimal IR 应拆出 unit（scene_card/beat_sequence/dialogue_block）"
    assert all(it.usable_as_example for it in golden)
    assert all(not it.usable_as_example for it in ann)
    assert all(it.quality == 1.0 for it in golden)


def test_builder_revisions_only_confirmed(tmp_path):
    """只有 confirmed_by 非空的修订才进池（未确认 = 仅 LLM 猜测，不得当教材）。"""
    db = tmp_path / "rev.db"
    conn = pool.connect(db)
    try:
        conn.execute(
            """INSERT INTO cases(case_id, brand_id, profile_id, industry, title, source, status, created_at)
               VALUES ('case:1','demo_tea','short_drama_v1','beverage','t','client','draft','2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO feedback(feedback_id, case_id, target_node_id, anchor_level, anchor_conf,
                                    dimension, verdict, severity, confirmed_by, created_at)
               VALUES ('f-conf','case:1',NULL,'bookmark',1.0,'dialogue','revise',3,'huang','2026-01-01'),
                      ('f-unconf','case:1',NULL,'bookmark',1.0,'dialogue','revise',3,'','2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO revision_pairs(pair_id, feedback_id, unit_kind, context_json, before_text, after_text, dimension)
               VALUES ('rp-conf','f-conf','dialogue_block','{}','旧','新','dialogue'),
                      ('rp-unconf','f-unconf','dialogue_block','{}','旧','新','dialogue')"""
        )
        conn.commit()
    finally:
        conn.close()
    items = builder.build_pool_from_revisions(db)
    assert [it.item_id for it in items] == ["rev:rp-conf"]
    assert items[0].content == "新"


# ---------------------------------------------------------------- RetrievalService
def test_service_power_idempotent_degrade(tmp_path):
    """禁用 / 空查询 / 池不存在 → 空串（幂等降级，不报错）。"""
    assert (
        RetrievalService(db_path=tmp_path / "nope.db", enabled=False).fetch(
            "q", unit_kind="chapter"
        )
        == ""
    )
    svc = RetrievalService(db_path=tmp_path / "nope.db", enabled=True)
    assert svc.fetch("", unit_kind="chapter") == ""
    assert svc.fetch("q", unit_kind="chapter") == ""


def test_service_formats_hits(tmp_path):
    items = [
        RetrievalItem(
            item_id="h1",
            case_id="case:9",
            unit_kind="chapter",
            industry="beverage",
            profile_id="short_drama_v1",
            content="某章正文段落",
            quality=1.0,
        )
    ]
    db = _upsert(tmp_path, items)
    svc = RetrievalService(db_path=db)
    text = svc.fetch("查询", unit_kind="chapter", profile_id="short_drama_v1", industry="beverage")
    assert "case:9" in text
    assert "某章正文段落" in text


def test_upsert_idempotent(tmp_path):
    db = _upsert(tmp_path, [_item("x")])
    conn = pool.connect(db)
    try:
        pool.upsert_items(conn, [_item("x"), _item("y")])
        n = conn.execute("SELECT COUNT(*) FROM retrieval_items").fetchone()[0]
    finally:
        conn.close()
    assert n == 2


# ---------------------------------------------------------------- eval A/B
def test_compare_arms_gain():
    from nsc.eval.l1 import ArmResult, compare_arms

    r = compare_arms(ArmResult("retrieval", findings=2), ArmResult("baseline", findings=5))
    assert r["findings_gain"] == 0.6  # 检索臂 finding 更少 → 正增益
    r0 = compare_arms(ArmResult("retrieval", findings=5), ArmResult("baseline", findings=5))
    assert r0["findings_gain"] == 0.0


def test_render_report(tmp_path):
    from nsc.eval.l1 import ArmResult, compare_arms, render_report

    results = [
        {
            "brief": "/x/brief.yaml",
            **compare_arms(ArmResult("retrieval", findings=1), ArmResult("baseline", findings=3)),
        }
    ]
    out = render_report(results, tmp_path / "ab_retrieval.md")
    text = out.read_text("utf-8")
    assert "检索臂 findings" in text
    assert "brief" in text


# ---------------------------------------------------------------- pipeline 注入
def _capturing_router(inner):
    class CapturingRouter:
        """转发给 golden 桩路由，同时记录每次 LLM 调用收到的 retrieved_cases。"""

        def __init__(self, inner):
            self.inner = inner
            self.seen: list[tuple[str, str]] = []

        def resolve(self, tier):
            return self.inner.resolve(tier)

        def complete(self, tier, messages, *, json_mode=False, seed=None):
            inputs = json.loads(messages[-1]["content"])
            self.seen.append(
                (self._guess(messages[0]["content"]), inputs.get("retrieved_cases", ""))
            )
            return self.inner.complete(tier, messages, json_mode=json_mode, seed=seed)

        def _guess(self, system: str) -> str:
            for key, name in (
                ("人物、地点、道具", "p1"),
                ("季/集级弧线", "p2"),
                ("写出 Beat 序列", "p3"),
                ("对白与动作", "p5"),
            ):
                if key in system:
                    return name
            return "other"

    return CapturingRouter(inner)


@pytest.fixture()
def pipeline_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    from test_pipeline_stub import FullStubRouter

    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    router = _capturing_router(FullStubRouter())
    ctx = PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=router,
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )
    return ctx, router


def test_pipeline_injects_retrieved_cases(pipeline_ctx):
    """开启检索：p1/p2/p3/p5 都收到非空 retrieved_cases，且 unit_kind 覆盖四类。"""
    ctx, router = pipeline_ctx
    from nsc.passes.pipeline import run_pipeline

    class RecordingRetrieval:
        def __init__(self):
            self.calls: list[str] = []

        def fetch(self, query, *, unit_kind, profile_id="", industry="", brand_id=""):
            self.calls.append(unit_kind)
            return f"已验证案例 {unit_kind}"

    rec = RecordingRetrieval()
    ctx.retrieval = rec

    ir = run_pipeline(ctx)
    assert len(ir.episodes) == 6

    assert set(rec.calls) == {"chapter", "scene_card", "beat_sequence", "dialogue_block"}
    assert rec.calls.count("chapter") == 1
    assert rec.calls.count("scene_card") == 1
    assert rec.calls.count("beat_sequence") == 6

    by_pass = {
        name: [rc for (n, rc) in router.seen if n == name] for name in ("p1", "p2", "p3", "p5")
    }
    assert by_pass["p1"] and all(x for x in by_pass["p1"])
    assert by_pass["p2"] and all(x for x in by_pass["p2"])
    assert by_pass["p3"] and all(x for x in by_pass["p3"])
    assert by_pass["p5"] and all(x for x in by_pass["p5"])


def test_pipeline_no_retrieval_empty(pipeline_ctx):
    """--no-retrieval（ctx.retrieval=None）：所有 Pass 的 retrieved_cases 都是空串。"""
    ctx, router = pipeline_ctx
    from nsc.passes.pipeline import run_pipeline

    assert ctx.retrieval is None
    ir = run_pipeline(ctx)
    assert len(ir.episodes) == 6
    for name, rc in router.seen:
        if name in ("p1", "p2", "p3", "p5"):
            assert rc == "", f"{name} 在未开启检索时应收到空串，实际 {rc!r}"
