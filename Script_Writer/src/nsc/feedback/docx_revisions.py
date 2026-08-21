"""OOXML 修订解析（T-10 主路径）：从客户回收的 docx 里提取修订。

主路径：直接解析 `word/document.xml` 的 `w:ins` / `w:del` / `w:commentRange*`，
拿到作者与时间戳（`w:author` / `w:date`）。
兜底：pandoc `--track-changes=all`（仅当 OOXML 无修订且 pandoc 可用时）。

输出统一为两层：
  extract_paragraph_states: list[ParaState]  —— 逐段 before/after + 书签 node_id + 修订/批注
  extract_revisions:        (list[str], list[RevisionOp]) —— T-10 的兼容视图
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import lxml.etree as etree

from nsc.render.anchors import node_id_from_beacon

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{_W}}}"

_TextMode = Literal["before", "after"]


@dataclass(slots=True)
class RevisionOp:
    """一处修订。paragraph_index 是 body 段落原始序号（0 起，含空段）。"""

    paragraph_index: int
    kind: str  # "insert" | "delete" | "comment"
    text: str
    author: str = ""
    ts: str = ""  # ISO 时间戳，可能为空
    before: str = ""  # 同段删除文本（replace 时）
    after: str = ""  # 同段插入文本（replace 时）
    returned_index: int = -1  # 在 extract_revisions 返回文本列表中的下标；-1 = 未进入（整段删除）


@dataclass(slots=True)
class ParaState:
    """一个段落的完整状态：修订前/后文本 + L1 书签 + 修订操作 + 批注。"""

    paragraph_index: int
    node_id: str | None
    before: str  # 拒绝全部修订后的文本（= 交付原文）
    after: str  # 接受全部修订后的文本（= 客户现文）
    ops: list[RevisionOp] = field(default_factory=list)
    comments: list[RevisionOp] = field(default_factory=list)


def _run_text(run: etree._Element) -> str:
    """提取一个 run 内的全部 w:t / w:delText 文本 + 换行。"""
    parts: list[str] = []
    for tag in (f"{W}t", f"{W}delText"):
        for t in run.iter(tag):
            parts.append(t.text or "")
    for _br in run.iter(f"{W}br"):
        parts.append("\n")
    return "".join(parts)


def _paragraph_text(p: etree._Element, mode: _TextMode = "after") -> str:
    """段落文本。mode=after：含插入、不含删除；mode=before：含删除、不含插入。"""
    parts: list[str] = []
    for child in p:
        tag = etree.QName(child).localname
        if tag == "r":
            parts.append(_run_text(child))
        elif (tag == "ins" and mode == "after") or (tag == "del" and mode == "before"):
            parts.append("".join(_run_text(run) for run in child.iter(f"{W}r")))
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
                ts=meta["ts"],
                after=meta["text"],
            )
        )
    return ops


def _bookmark_node_id(p: etree._Element) -> str | None:
    """段落内的 L1 锚点书签（NID_<ulid>）→ node_id。"""
    for bm in p.iter(f"{W}bookmarkStart"):
        nid = node_id_from_beacon(bm.get(f"{W}name", ""))
        if nid:
            return nid
    return None


def extract_paragraph_states(path: str | Path) -> list[ParaState]:
    """逐段提取 before/after/书签/修订/批注。完全无内容的空段被跳过。"""
    path = Path(path)
    with zipfile.ZipFile(path) as doczip:
        if "word/document.xml" not in doczip.namelist():
            raise ValueError(f"不是有效的 docx：{path}")
        root = etree.fromstring(doczip.read("word/document.xml"))
        comments = _extract_comments(doczip)

    body = root.find(f"{W}body")
    paragraphs = list(body.iter(f"{W}p")) if body is not None else []

    states: list[ParaState] = []
    for i, p in enumerate(paragraphs):
        state = ParaState(
            paragraph_index=i,
            node_id=_bookmark_node_id(p),
            before=_paragraph_text(p, "before"),
            after=_paragraph_text(p, "after"),
            ops=_collect_ops(p, i),
            comments=_collect_comments(p, i, comments),
        )
        if not (state.before.strip() or state.after.strip() or state.ops or state.comments):
            continue
        states.append(state)
    return states


def extract_revisions(path: str | Path) -> tuple[list[str], list[RevisionOp]]:
    """解析 docx，返回 (最终段落文本, 修订操作)。

    整段被删（after 为空）的段落不进 returned，但其 del 操作保留在 ops 中
    （returned_index=-1），供摄入层产出 delete 记录。
    """
    states = extract_paragraph_states(path)
    returned: list[str] = []
    ops: list[RevisionOp] = []
    for s in states:
        r_idx = -1
        if s.after.strip():
            r_idx = len(returned)
            returned.append(s.after)
        for op in s.ops + s.comments:
            op.returned_index = r_idx
            ops.append(op)
    return returned, ops


_PANDOC_SPAN_RE = re.compile(r"\[([^\]]*)\]\{\s*\.(insertion|deletion)[^}]*\}")


def parse_pandoc_markdown(md: str) -> tuple[list[str], list[RevisionOp]]:
    """解析 pandoc `--track-changes=all` 的 markdown 输出。

    pandoc 把修订渲染为 `[文本]{.insertion}` / `[文本]{.deletion}` 跨度。
    """
    returned: list[str] = []
    ops: list[RevisionOp] = []
    for block in re.split(r"\n\s*\n", md):
        block = block.strip()
        if not block:
            continue
        block = block.lstrip("#").strip()
        block_ops: list[RevisionOp] = []
        after_parts: list[str] = []
        last = 0
        for m in _PANDOC_SPAN_RE.finditer(block):
            after_parts.append(block[last : m.start()])
            kind = "insert" if m.group(2) == "insertion" else "delete"
            block_ops.append(RevisionOp(paragraph_index=-1, kind=kind, text=m.group(1)))
            if kind == "insert":
                after_parts.append(m.group(1))
            last = m.end()
        after_parts.append(block[last:])
        after = "".join(after_parts).strip()
        r_idx = len(returned) if after else -1
        if after:
            returned.append(after)
        for op in block_ops:
            op.paragraph_index = r_idx
            op.returned_index = r_idx
            ops.append(op)
    return returned, ops


def _pandoc_fallback(path: str | Path) -> tuple[list[str], list[RevisionOp]]:
    """pandoc --track-changes=all 兜底。仅当 pandoc 可用时使用。"""
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc 不可用，且 OOXML 主路径未产出修订")
    proc = subprocess.run(
        ["pandoc", "-f", "docx", "-t", "markdown", "--track-changes=all", "--wrap=none", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_pandoc_markdown(proc.stdout)


def parse_revisions(path: str | Path) -> tuple[list[str], list[RevisionOp]]:
    """入口：优先 OOXML；无修订时尝试 pandoc 兜底。"""
    returned, ops = extract_revisions(path)
    if not ops:
        try:
            return _pandoc_fallback(path)
        except (RuntimeError, subprocess.CalledProcessError):
            pass
    return returned, ops
