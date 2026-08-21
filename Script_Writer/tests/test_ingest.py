"""T-11 反馈摄入流水线测试。

覆盖验收：
- 带修订 docx → 结构化 feedback/revision_pairs/preference_pairs/L0 观测条目
- confirmed_by == '' 的条目不进 L1 聚类（显式断言）
- 八维分类各至少一条落库
- 低相似"完全重写"段的语义分支（同一节点 → replace 保留 node_id / 新内容 → delete+insert）
- pandoc markdown 解析、无分类器时的诚实干跑
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import ClassVar

import lxml.etree as etree
import pytest
import yaml
from docx import Document

from nsc.db.feedback_store import FeedbackStore
from nsc.feedback.align import recover_anchors
from nsc.feedback.classify import EditClassify
from nsc.feedback.docx_revisions import extract_revisions, parse_pandoc_markdown
from nsc.feedback.ingest import (
    find_rewrite_candidates,
    ingest_docx,
    ingest_text,
    resolve_rewrites,
)
from nsc.render.anchors import Paragraph
from nsc.runtime.models import LLMResult

FIXTURES = Path(__file__).parent / "fixtures"
ROUND1 = FIXTURES / "ingest" / "demo_tea_round1.docx"

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{_W}}}"

DIMENSIONS = [
    "structural",
    "character",
    "placement",
    "dialogue",
    "factual",
    "compliance",
    "producibility",
    "taste",
]


class StubRouter:
    """确定性假路由：分类按记录序号循环八维；重写归并按字符重合度裁决。"""

    tiers: ClassVar[dict] = {"tier_bulk": {"temperature": 0.2}}

    def complete(
        self,
        tier: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        seed: int | None = None,
    ) -> LLMResult:
        payload = json.loads(messages[-1]["content"])
        if "records" in payload:
            items = [
                {
                    "index": i,
                    "dimension": DIMENSIONS[i % len(DIMENSIONS)],
                    "verdict": "revise",
                    "severity": (i % 5) + 1,
                    "rationale_nl": f"stub 诊断：第 {i} 条编辑暴露了生成习惯的缺陷",
                }
                for i, _ in enumerate(payload["records"])
            ]
            text = json.dumps({"records": items})
        else:
            items = [
                {"index": i, "same_node": len(set(p["before"]) & set(p["after"])) >= 4}
                for i, p in enumerate(payload["pairs"])
            ]
            text = json.dumps({"pairs": items})
        return LLMResult(
            text=text, model_id="stub", tokens_in=1, tokens_out=1, cost_usd=0.0, wall_ms=1
        )


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    return {
        "db_path": tmp_path / "cases.db",
        "obs_dir": tmp_path / "obs",
        "out_dir": tmp_path / "out",
    }


# ---------------------------------------------------------------- docx 端到端
def test_docx_ingest_end_to_end(env: dict):
    report = ingest_docx(ROUND1, case_id="case:0001", router=StubRouter(), **env)

    assert not report.dry_run
    # 4 处编辑：P2 标点 replace、P3 重写 replace、P4 整段 delete、P7 新增 insert
    assert len(report.records) == 4
    assert len(report.feedback_ids) == 4
    by_type = {}
    for r in report.records:
        by_type.setdefault(r.edit_type, []).append(r)
    assert len(by_type["replace"]) == 2
    assert len(by_type["delete"]) == 1
    assert len(by_type["insert"]) == 1

    # L1 书签级锚定：node_id 100% 正确
    anchored = {r.node_id for r in report.records if r.node_id}
    assert anchored == {
        "01M04TVA5Z74ZZKYYJRFWXFC98",
        "01M04TVA5Z74ZZKYYJRFWXFC9A",
        "01M04TVA5Z74ZZKYYJRFWXFC9C",
    }
    assert all(r.anchor_level == "bookmark" for r in report.records if r.node_id)
    # 新增段无锚点 → failed，进 unaligned
    assert len(report.unaligned) == 1
    assert report.unaligned[0].edit_type == "insert"

    store = FeedbackStore(env["db_path"])
    try:
        rows = store.feedback_for_case("case:0001")
        assert len(rows) == 4
        # confirmed_by 必须留空（仅 LLM 猜测）
        assert all(r["confirmed_by"] == "" for r in rows)
        assert {r["dimension"] for r in rows} == set(DIMENSIONS[:4])
        assert {r["author"] for r in rows} == {"客户·林女士"}

        pairs = store.execute("SELECT * FROM revision_pairs").fetchall()
        assert len(pairs) == 3  # 2 replace + 1 delete（insert 无 before 不进）
        prefs = store.execute("SELECT * FROM preference_pairs").fetchall()
        assert len(prefs) == 2  # 仅 replace 产出偏好对，human_pref=b（客户改后）
        assert all(p[6] == "b" for p in prefs)

        obs_rows = store.execute("SELECT * FROM observations_index").fetchall()
        assert len(obs_rows) == 4
    finally:
        store.close()

    obs_files = sorted(env["obs_dir"].glob("obs_*.yaml"))
    assert len(obs_files) == 4
    obs = yaml.safe_load(obs_files[0].read_text("utf-8"))
    assert obs["id"] == "R0-0001"
    assert obs["level"] == "L0"
    assert obs["evidence_ids"] == ["case:0001"]

    queue_lines = (env["out_dir"] / "ingest" / "annotation_queue.jsonl").read_text().splitlines()
    assert len(queue_lines) == 4
    for line in queue_lines:
        item = json.loads(line)
        assert item["run_id"] == report.run_id
        assert item["feedback_id"] in report.feedback_ids
        assert item["confirmed_by"] == ""

    assert (env["out_dir"] / "ingest" / "unaligned.md").exists()


def test_ingest_writes_provenance_runs(env: dict):
    ingest_docx(ROUND1, case_id="case:0001", router=StubRouter(), **env)
    conn = sqlite3.connect(env["db_path"])
    try:
        passes = {r[0] for r in conn.execute("SELECT pass_name FROM runs").fetchall()}
    finally:
        conn.close()
    assert "ingest" in passes
    assert "edit_classify" in passes


# ---------------------------------------------------------------- confirmed_by 门禁（验收硬指标）
def test_confirmed_by_empty_excluded_from_clustering(env: dict):
    ingest_docx(ROUND1, case_id="case:0001", router=StubRouter(), **env)
    store = FeedbackStore(env["db_path"])
    try:
        # 刚摄入的条目（confirmed_by == ''）一律不进 L1 聚类
        assert store.clusterable_feedback() == []
        # 人工确认一条后，只有它进聚类池
        fid = store.feedback_for_case("case:0001")[0]["feedback_id"]
        store.execute(
            "UPDATE feedback SET confirmed_by = 'op:randypan' WHERE feedback_id = ?", (fid,)
        )
        clusterable = store.clusterable_feedback()
        assert [r["feedback_id"] for r in clusterable] == [fid]
    finally:
        store.close()


# ---------------------------------------------------------------- 八维覆盖
def test_eight_dimensions_each_at_least_one(env: dict):
    text = "\n".join(f"第{i}条客户吐槽：这里写得不对。" for i in range(8))
    msg_file = env["out_dir"].parent / "wechat.txt"
    msg_file.write_text(text, "utf-8")

    report = ingest_text(msg_file, case_id="case:0002", router=StubRouter(), **env)
    assert len(report.feedback_ids) == 8

    store = FeedbackStore(env["db_path"])
    try:
        rows = store.feedback_for_case("case:0002")
        assert {r["dimension"] for r in rows} == set(DIMENSIONS)
        assert all(r["edit_type"] == "comment" for r in rows)
        assert all(r["anchor_level"] == "failed" for r in rows)
        assert all(r["confirmed_by"] == "" for r in rows)
        # comment 型无 before，不产 revision/preference 对
        assert store.execute("SELECT COUNT(*) FROM revision_pairs").fetchone()[0] == 0
        assert store.execute("SELECT COUNT(*) FROM preference_pairs").fetchone()[0] == 0
    finally:
        store.close()


# ---------------------------------------------------------------- 低相似重写语义分支
def _rewrite_records() -> list:
    delivered = [
        Paragraph(node_id="01M04TVA5Z74ZZKYYJRFWXFC96", text="开头段"),
        Paragraph(node_id="01M04TVA5Z74ZZKYYJRFWXFC98", text="林晚把体检报告翻了个底朝天"),
        Paragraph(node_id="01M04TVA5Z74ZZKYYJRFWXFC9A", text="结尾段"),
    ]
    returned = ["开头段", "她把体检报告从头到尾看了三遍", "结尾段"]
    return recover_anchors(returned, delivered)


def test_low_similarity_rewrite_is_delete_insert_before_semantics():
    records = _rewrite_records()
    assert {r.edit_type for r in records} == {"delete", "insert"}
    # 候选对归一化为 (delete_idx, insert_idx)，与 DP 回溯方向无关
    assert find_rewrite_candidates(records) == [(1, 0)]


def test_semantic_merge_same_node_keeps_node_id():
    records = _rewrite_records()
    merged = resolve_rewrites(records, EditClassify(StubRouter()).judge_rewrite_pairs)
    # stub 判"同一节点被重写"（字符重合 ≥4）→ 合并为 replace，保留原 node_id
    assert len(merged) == 1
    assert merged[0].edit_type == "replace"
    assert merged[0].node_id == "01M04TVA5Z74ZZKYYJRFWXFC98"
    assert merged[0].before == "林晚把体检报告翻了个底朝天"
    assert merged[0].after == "她把体检报告从头到尾看了三遍"


def test_semantic_reject_keeps_delete_insert():
    delivered = [
        Paragraph(node_id="01M04TVA5Z74ZZKYYJRFWXFC96", text="开头段"),
        Paragraph(node_id="01M04TVA5Z74ZZKYYJRFWXFC98", text="旧版段落内容一"),
        Paragraph(node_id="01M04TVA5Z74ZZKYYJRFWXFC9A", text="结尾段"),
    ]
    returned = ["开头段", "全新写法的替换文字", "结尾段"]
    records = recover_anchors(returned, delivered)
    merged = resolve_rewrites(records, EditClassify(StubRouter()).judge_rewrite_pairs)
    # stub 判"真新内容"（无字符重合）→ 维持 delete + insert，不归并
    assert {r.edit_type for r in merged} == {"delete", "insert"}
    assert len(merged) == 2


def _build_no_bookmark_rewrite_docx(path: Path) -> None:
    """无书签的回收 docx：中段被完全重写（del + ins）。"""
    doc = Document()
    specs = [
        [("plain", "开头段")],
        [("del", "林晚把体检报告翻了个底朝天"), ("ins", "她把体检报告从头到尾看了三遍")],
        [("plain", "结尾段")],
    ]
    for runs in specs:
        p = doc.add_paragraph()
        for kind, text in runs:
            if kind == "plain":
                r = etree.SubElement(p._p, f"{W}r")
                etree.SubElement(r, f"{W}t").text = text
            else:
                el = etree.SubElement(p._p, f"{W}{kind}")
                el.set(f"{W}author", "客户·林女士")
                el.set(f"{W}date", "2026-07-01T10:30:00Z")
                r = etree.SubElement(el, f"{W}r")
                etree.SubElement(r, f"{W}{'delText' if kind == 'del' else 't'}").text = text
    doc.save(str(path))


def test_rewrite_merge_through_ingest_main_path(env: dict):
    returned_docx = env["out_dir"].parent / "returned.docx"
    _build_no_bookmark_rewrite_docx(returned_docx)
    anchors_csv = env["out_dir"].parent / "anchors.csv"
    anchors_csv.write_text(
        "paragraph_no,node_id,text\n"
        "0,01M04TVA5Z74ZZKYYJRFWXFC96,开头段\n"
        "1,01M04TVA5Z74ZZKYYJRFWXFC98,林晚把体检报告翻了个底朝天\n"
        "2,01M04TVA5Z74ZZKYYJRFWXFC9A,结尾段\n",
        "utf-8",
    )
    report = ingest_docx(
        returned_docx,
        case_id="case:0003",
        delivered_path=anchors_csv,
        router=StubRouter(),
        **env,
    )
    # 模糊路径的"完全重写"经语义裁决合并为 replace，node_id 保留
    assert len(report.records) == 1
    rec = report.records[0]
    assert rec.edit_type == "replace"
    assert rec.node_id == "01M04TVA5Z74ZZKYYJRFWXFC98"
    assert rec.anchor_level == "fuzzy"

    store = FeedbackStore(env["db_path"])
    try:
        rows = store.feedback_for_case("case:0003")
        assert len(rows) == 1
        assert rows[0]["target_node_id"] == "01M04TVA5Z74ZZKYYJRFWXFC98"
    finally:
        store.close()


# ---------------------------------------------------------------- pandoc 兜底解析
def test_parse_pandoc_markdown():
    md = (
        "第一段保留。\n\n"
        "陈经理站在门口[。]{.deletion}[！]{.insertion}\n\n"
        "[新增的一整段。]{.insertion}\n"
    )
    returned, ops = parse_pandoc_markdown(md)
    assert returned == ["第一段保留。", "陈经理站在门口！", "新增的一整段。"]
    kinds = [op.kind for op in ops]
    assert kinds == ["delete", "insert", "insert"]


# ---------------------------------------------------------------- 干跑（无分类器）
def test_dry_run_without_classifier_writes_nothing(env: dict):
    report = ingest_docx(ROUND1, case_id="case:0001", router=None, **env)
    assert report.dry_run
    assert report.feedback_ids == []
    assert len(report.records) == 4  # 对齐报告仍产出

    store = FeedbackStore(env["db_path"])
    try:
        assert store.feedback_for_case("case:0001") == []
    finally:
        store.close()
    assert not list(env["obs_dir"].glob("obs_*.yaml")) if env["obs_dir"].exists() else True


# ---------------------------------------------------------------- 既有验收不破坏（fixture 仍可按 T-10 路径消费）
def test_round1_fixture_still_aligns():
    returned, ops = extract_revisions(ROUND1)
    assert len(returned) == 6
    assert any(op.kind == "insert" for op in ops)
    assert any(op.kind == "delete" for op in ops)
    # 整段删除的 del 操作现在保留（returned_index=-1）
    assert any(op.returned_index == -1 for op in ops)
