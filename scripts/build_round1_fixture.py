"""生成 tests/fixtures/ingest/demo_tea_round1.docx（T-10 验收 fixture）。

构造一份"客户已修订"的 docx：基于交付小说，注入 OOXML 的 w:ins / w:del，
覆盖 5 类编辑：整段删除 / 整段新增 / 顺序调整 / 大幅重写 / 只改标点。
生成一次后作为 fixture 提交，测试直接读取。
"""

from __future__ import annotations

from pathlib import Path

import lxml.etree as etree
from docx import Document

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{_W}}}"
AUTHOR = "客户·林女士"
TS = "2026-07-01T10:30:00Z"

#: 交付段落（node_id, text）
DELIVERED = [
    ("01M04TVA5Z74ZZKYYJRFWXFC96", "林晚把体检报告翻了个底朝天，血糖那栏的箭头让她心里一沉。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC98", "陈经理站在门口催促，手里攥着一份要她签字的文件。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9A", "窗外的光打下来，她忽然发现：同一杯茶，怎么会有两种说法。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9C", "她抓起杯子，快步走出办公室，决定自己去查清楚。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9E", "电梯里，她翻到报告最后一页，呼吸停了一拍。"),
    ("01M04TVA5Z74ZZKYYJRFWXFC9G", "回到工位，她把那杯茶放在桌上，发了很久的呆。"),
]

#: 每段的 run 规格：[(run_kind, text)]，run_kind ∈ plain | ins | del
#: 覆盖：整段删除 / 整段新增 / 大幅重写 / 只改标点
_RUNS = [
    [("plain", "林晚把体检报告翻了个底朝天，血糖那栏的箭头让她心里一沉。")],
    [
        ("plain", "陈经理站在门口催促，手里攥着一份要她签字的文件"),
        ("del", "。"),
        ("ins", "！"),
    ],  # 只改标点
    [
        ("del", "窗外的光打下来，她忽然发现：同一杯茶，怎么会有两种说法。"),
        ("ins", "窗外的光打下来，她忽然发现：同一杯茶，竟有两种完全不同的说法。"),
    ],  # 大幅重写
    [("del", "她抓起杯子，快步走出办公室，决定自己去查清楚。")],  # 整段删除
    [("plain", "电梯里，她翻到报告最后一页，呼吸停了一拍。")],
    [("plain", "回到工位，她把那杯茶放在桌上，发了很久的呆。")],
    [("ins", "这笔账，她决定当面问清楚。")],  # 整段新增
]


def _run(parent: etree._Element, text: str, tag: str = "t") -> None:
    r = etree.SubElement(parent, f"{W}r")
    etree.SubElement(r, f"{W}{tag}").text = text


def _rev(parent: etree._Element, kind: str, text: str) -> None:
    """向段落追加修订 run。kind: ins / del。"""
    el = etree.SubElement(parent, f"{W}{kind}")
    el.set(f"{W}author", AUTHOR)
    el.set(f"{W}date", TS)
    _run(el, text, tag="delText" if kind == "del" else "t")


def build_round1() -> Path:
    doc = Document()
    counter = 1
    for i, runs in enumerate(_RUNS):
        p = doc.add_paragraph()
        node_id = DELIVERED[i][0] if i < len(DELIVERED) else None
        # L1 书签（新增段无锚点）
        if node_id:
            p._p.insert(0, _bookmark(counter, f"NID_{node_id}", "start"))
            counter += 1
        for kind, text in runs:
            if kind == "plain":
                _run(p._p, text)
            else:
                _rev(p._p, kind, text)
        if node_id:
            p._p.insert(0, _bookmark(counter - 1, "", "end"))

    out = Path("tests/fixtures/ingest/demo_tea_round1.docx")
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def _bookmark(pid: int, name: str, kind: str) -> etree._Element:
    el = etree.Element(f"{W}bookmark{kind.capitalize()}")
    el.set(f"{W}id", str(pid))
    if name:
        el.set(f"{W}name", name)
    return el


if __name__ == "__main__":
    p = build_round1()
    print(f"fixture 已生成：{p}")
    # 校验可读回
    from nsc.feedback.docx_revisions import extract_revisions

    returned, ops = extract_revisions(p)
    print("returned:", returned)
    print("ops:", [(o.kind, o.text) for o in ops])
