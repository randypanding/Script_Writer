"""T-10 反向对齐器测试。

覆盖 5 类编辑（整段删/增/重排/大幅重写/只改标点），
并在 fixtures/ingest/demo_tea_round1.docx 上端到端验收：恢复率≥90%、node_id 100% 正确。
"""

from __future__ import annotations

from pathlib import Path

from nsc.feedback.align import align_paragraphs, recover_anchors
from nsc.feedback.docx_revisions import extract_revisions
from nsc.render.anchors import Paragraph

FIXTURES = Path(__file__).parent / "fixtures"

#: 交付段（node_id, text）——与 scripts/build_round1_fixture.py 的 DELIVERED 一致
DELIVERED = [
    ("01M04TVA5Z74ZZKYYJRFWXFC96", "林晚把体检报告翻了个底朝天，血糖那栏的箭头让她心里一沉。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC98", "陈经理站在门口催促，手里攥着一份要她签字的文件。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9A", "窗外的光打下来，她忽然发现：同一杯茶，怎么会有两种说法。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9C", "她抓起杯子，快步走出办公室，决定自己去查清楚。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9E", "电梯里，她翻到报告最后一页，呼吸停了一拍。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9G", "回到工位，她把那杯茶放在桌上，发了很久的呆。"),
]


def _delivered_paras() -> list[Paragraph]:
    return [Paragraph(node_id=nid, text=text) for nid, text in DELIVERED]


def _delivered_texts() -> list[str]:
    return [t for _, t in DELIVERED]


# ---------------------------------------------------------------- 5 类编辑（对齐层）
def test_align_whole_paragraph_delete():
    pairs = align_paragraphs(["A", "B", "C"], ["A", "C"])
    assert pairs == [(0, 0), (1, None), (2, 1)]


def test_align_whole_paragraph_insert():
    pairs = align_paragraphs(["A", "B"], ["A", "X", "B"])
    assert pairs == [(0, 0), (None, 1), (1, 2)]


def test_align_reorder_is_monotonic():
    delivered = ["第一段", "第二段", "第三段", "第四段"]
    returned = ["第一段", "第四段", "第三段", "第二段"]
    pairs = align_paragraphs(delivered, returned)
    # 单调性：两个序列的下标都非递减，绝不交叉
    d_idx = [d for d, _ in pairs if d is not None]
    r_idx = [r for _, r in pairs if r is not None]
    assert d_idx == sorted(d_idx)
    assert r_idx == sorted(r_idx)
    # 重排后仍能各自对齐到原段
    by_text = {idx: delivered[idx] for idx in range(len(delivered))}
    for d, r in pairs:
        if d is not None and r is not None:
            assert by_text[d] == returned[r]


def test_align_recognizable_rewrite_stays_anchored():
    # 相似度仍可辨的改写（~0.85）→ 保留 node_id，不判成 delete+insert
    delivered = ["开头", "窗外的光打下来，她忽然发现：同一杯茶，怎么会有两种说法。", "结尾"]
    returned = ["开头", "窗外的光打下来，她忽然发现：同一杯茶，竟有两种完全不同的说法。", "结尾"]
    pairs = align_paragraphs(delivered, returned)
    mapping = {d: r for d, r in pairs}
    assert mapping.get(1) == 1


def test_align_total_rewrite_not_false_matched():
    # 相似度过低（< _MIN_MATCH）的"完全重写"→ 不强行配成 replace，
    # 而是 delete+insert（确定性对齐到此为止，交给强模型判定）。
    delivered = ["开头", "旧版段落内容一", "结尾"]
    returned = ["开头", "完全重写的另一段内容", "结尾"]
    pairs = align_paragraphs(delivered, returned)
    mapping = {d: r for d, r in pairs}
    # 旧段被删、新段被插，绝不误配成"同段 replace"
    assert (1, 1) not in mapping
    assert (1, None) in pairs
    assert (None, 1) in pairs


def test_align_punctuation_only():
    delivered = ["甲", "乙字句。"]
    returned = ["甲", "乙字句！"]
    pairs = align_paragraphs(delivered, returned)
    assert pairs == [(0, 0), (1, 1)]


# ---------------------------------------------------------------- node_id 恢复
def test_recover_anchors_node_ids():
    delivered = _delivered_paras()
    returned = [
        "林晚把体检报告翻了个底朝天，血糖那栏的箭头让她心里一沉。",
        "陈经理站在门口催促，手里攥着一份要她签字的文件！",  # 只改标点
        "窗外的光打下来，她忽然发现：同一杯茶，竟有两种完全不同的说法。",  # 大幅重写
        "电梯里，她翻到报告最后一页，呼吸停了一拍。",
        "回到工位，她把那杯茶放在桌上，发了很久的呆。",
        "这笔账，她决定当面问清楚。",  # 新增
    ]
    records = recover_anchors(returned, delivered)

    by_before = {r.before: r for r in records}
    # 大幅重写 → replace，node_id 正确
    r3 = by_before["窗外的光打下来，她忽然发现：同一杯茶，怎么会有两种说法。"]
    assert r3.edit_type == "replace"
    assert r3.node_id == "01M04TVA5Z74ZZKYYJRFWXFC9A"
    # 只改标点 → replace
    r2 = by_before["陈经理站在门口催促，手里攥着一份要她签字的文件。"]
    assert r2.edit_type == "replace"
    assert r2.node_id == "01M04TVA5Z74ZZKYYJRFWXFC98"
    # 整段删除 → delete
    r4 = by_before["她抓起杯子，快步走出办公室，决定自己去查清楚。"]
    assert r4.edit_type == "delete"
    assert r4.node_id == "01M04TVA5Z74ZZKYYJRFWXFC9C"
    # 新增 → insert，node_id=None
    assert any(r.edit_type == "insert" and r.node_id is None for r in records)


# ---------------------------------------------------------------- 端到端（docx fixture）
def test_docx_round1_fixture_end_to_end():
    """验收：fixtures/ingest/demo_tea_round1.docx 恢复率≥90%、node_id 100% 正确。"""
    fixture = FIXTURES / "ingest" / "demo_tea_round1.docx"
    returned, ops = extract_revisions(fixture)

    # 修订操作被结构化提取（含作者/时间戳）
    assert all(op.author == "客户·林女士" for op in ops)
    assert any(op.kind == "insert" for op in ops)
    assert any(op.kind == "delete" for op in ops)

    records = recover_anchors(returned, _delivered_paras())
    edits = [r for r in records if r.edit_type in ("replace", "delete", "insert")]

    # 期望 4 处编辑：P2 标点、P3 重写、P4 删除、新增
    assert len(edits) == 4

    # node_id 正确率：所有带 node_id 的恢复条目都正确（100%）
    expected_ids = {
        "01M04TVA5Z74ZZKYYJRFWXFC98",  # P2
        "01M04TVA5Z74ZZKYYJRFWXFC9A",  # P3
        "01M04TVA5Z74ZZKYYJRFWXFC9C",  # P4
    }
    recovered_ids = {r.node_id for r in edits if r.node_id}
    assert recovered_ids == expected_ids

    # 恢复率：4 处编辑全部检出 → 100% ≥ 90%
    recovery = len(edits) / 4.0
    assert recovery >= 0.9
