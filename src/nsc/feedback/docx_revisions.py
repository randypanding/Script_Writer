"""OOXML 修订解析（T-10 主路径）：从客户回收的 docx 里提取修订。

主路径：直接解析 `word/document.xml` 的 `w:ins` / `w:del` / `w:commentRange*`，
拿到作者与时间戳（`w:author` / `w:date`）。
兜底：pandoc `--track-changes=all`（仅当 pandoc 可用且 OOXML 无修订时）。

输出统一为：
  returned_paragraphs: list[str]          —— 修订应用后的最终段落文本
  revision_ops:        list[RevisionOp]    —— 结构化的修订操作
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lxml.etree as etree

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{_W}}}"


@dataclass(slots=True)
class RevisionOp:
    """一处修订。paragraph_index 是该段落在整个文档中的序号（0 起）。"""

    paragraph_index: int
    kind: str  # "insert" | "delete"
    text: str
    author: str = ""
    ts: str = ""  # ISO 时间戳，可能为空
    before: str = ""  # 同段删除文本（replace 时）
    after: str = ""  # 同段插入文本（replace 时）


def _run_text(run: etree._Element) -> str:
    """提取一个 run 内的全部 w:t / w:delText 文本 + 换行。"""
    parts: list[str] = []
    for tag in (f"{W}t", f"{W}delText"):
        for t in run.iter(tag):
            parts.append(t.text or "")
    for _br in run.iter(f"{W}br"):
        parts.append("\n")
    return "".join(parts)


def _paragraph_text(p: etree._Element, *, keep_del: bool = False) -> str:
    """段落最终文本。keep_del=True 时把删除文本也算进去（用于计算 before）。"""
    parts: list[str] = []
    for child in p:
        tag = etree.QName(child).localname
        if tag == "r":
            # 若在 w:del 内由父层处理；这里处理普通 run
            parts.append(_run_text(child))
        elif tag == "ins":
            parts.append("".join(_run_text(run) for run in child.iter(f"{W}r")))
        elif tag == "del":
            if keep_del:
                parts.append("".join(_run_text(run) for run in child.iter(f"{W}r")))
        elif tag == "pPr":
            continue
    return "".join(parts)


def _collect_ops(p: etree._Element, idx: int) -> list[RevisionOp]:
    """收集段落内的 ins/del。"""
    ops: list[RevisionOp] = []
    for child in p:
        tag = etree.QName(child).localname
        if tag == "ins":
            text = "".join(_run_text(run) for run in child.iter(f"{W}r"))
            ops.append(
                RevisionOp(
                    paragraph_index=idx,
                    kind="insert",
                    text=text,
                    author=child.get(f"{W}author", ""),
                    ts=child.get(f"{W}date", ""),
                )
            )
        elif tag == "del":
            text = "".join(_run_text(run) for run in child.iter(f"{W}r"))
            ops.append(
                RevisionOp(
                    paragraph_index=idx,
                    kind="delete",
                    text=text,
                    author=child.get(f"{W}author", ""),
                    ts=child.get(f"{W}date", ""),
                )
            )
    return ops


def _extract_comments(doczip: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    """word/comments.xml → {comment_id: {author, ts, text}}。"""
    if "word/comments.xml" not in doczip.namelist():
        return {}
    root = etree.fromstring(doczip.read("word/comments.xml"))
    comments: dict[str, dict[str, Any]] = {}
    for c in root.iter(f"{W}comment"):
        cid = c.get(f"{W}id", "")
        text = "".join(t.text or "" for t in c.iter(f"{W}t"))
        comments[cid] = {
            "author": c.get(f"{W}author", ""),
            "ts": c.get(f"{W}date", ""),
            "text": text,
        }
    return comments


def _collect_comments(
    p: etree._Element,
    idx: int,
    comments: dict[str, dict[str, Any]],
) -> list[RevisionOp]:
    """把段落内的 w:commentRangeStart 批注转成 comment 类 RevisionOp。"""
    ops: list[RevisionOp] = []
    for start in p.iter(f"{W}commentRangeStart"):
        cid = start.get(f"{W}id", "")
        meta = comments.get(cid)
        if meta is None:
            continue
        ops.append(
            RevisionOp(
                paragraph_index=idx,
                kind="comment",
                text="",
                author=meta["author"],
                after=meta["text"],
            )
        )
    return ops


def extract_revisions(path: str | Path) -> tuple[list[str], list[RevisionOp]]:
    """解析 docx，返回 (最终段落文本, 修订操作)。"""
    path = Path(path)
    with zipfile.ZipFile(path) as doczip:
        if "word/document.xml" not in doczip.namelist():
            raise ValueError(f"不是有效的 docx：{path}")
        root = etree.fromstring(doczip.read("word/document.xml"))
        comments = _extract_comments(doczip)

    body = root.find(f"{W}body")
    paragraphs = list(body.iter(f"{W}p")) if body is not None else []

    # 只取 body 的直接子级段落（跳过表格内段落，除非需要）
    returned: list[str] = []
    ops: list[RevisionOp] = []
    for i, p in enumerate(paragraphs):
        text = _paragraph_text(p)
        if text.strip() == "":
            continue  # 整段被删/空段：从最终文本中剔除，交给对齐器判为 delete
        returned.append(text)
        ops.extend(_collect_ops(p, i))
        ops.extend(_collect_comments(p, i, comments))

    return returned, ops


def _pandoc_fallback(path: str | Path) -> tuple[list[str], list[RevisionOp]]:
    """pandoc --track-changes=all 兜底。仅当 pandoc 可用时使用。"""
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc 不可用，且 OOXML 主路径未产出修订")
    # 理想实现：pandoc -t markdown --track-changes=all，解析 [一夜删除] 转义符。
    # 本阶段以 OOXML 主路径为准，此处标记为未实现但保留入口。
    raise NotImplementedError("pandoc 兜底待 T-10 后期接入")


def parse_revisions(path: str | Path) -> tuple[list[str], list[RevisionOp]]:
    """入口：优先 OOXML；无修订时尝试 pandoc 兜底。"""
    returned, ops = extract_revisions(path)
    if not ops:
        try:
            return _pandoc_fallback(path)
        except (RuntimeError, NotImplementedError):
            pass
    return returned, ops
