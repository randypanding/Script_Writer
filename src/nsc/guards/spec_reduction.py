"""D2 守卫：规范语句必须带 [[form:...]] 形态标记。

设计原则：宁缺毋滥。只对"规范性内容文件"做检查，跳过描述方法论的元文档
（DSL / CONTRACTS / SPEC_RULES / TAXONOMY / PROMOTION / pairwise 协议），
避免把"关于规则的规则"误报成未标记的规范语句。

检查规则：
  1. 段落内出现命令式规范关键词（必须/不得/禁止/只能/严禁/强制） → 要求可约简。
  2. 若该段落所在小节（最近的标题）已带 `[[form:...]]`，则豁免。
  3. 段落自身含 `[[form:...]]` 则豁免。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FORM_RE = re.compile(r"\[\[form:[a-z_]+(?::[a-z_]+)?\]\]")
_COMMAND_WORDS = (
    "必须",
    "不得",
    "禁止",
    "只能",
    "不允许",
    "严禁",
    "强制",
    "必须保证",
    "不许",
    "一律",
    "MUST",
    "SHALL",
)
# 描述编译/方法论本身的元文档，不按规范性语句强标 form。
_META_FILES = {
    "SPEC_RULES.md",
    "DSL.md",
    "CONTRACTS.md",
    "TAXONOMY.md",
    "PROMOTION.md",
    "pairwise_protocol.md",
}
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
_IGNORE_LINE = re.compile(r"^\s*(#|\||- |\* |\d+\. |> |```|`|<!--|$)")


@dataclass(frozen=True)
class Problem:
    file: str
    line: int
    text: str

    def __str__(self) -> str:  # 便于测试输出
        return f"{self.file}:{self.line}: {self.text[:60]}"


def scan(root: Path) -> list[Problem]:
    problems: list[Problem] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith("_") or p.name in _META_FILES:
            continue
        _scan_file(p, problems)
    return problems


def _scan_file(p: Path, out: list[Problem]) -> None:
    lines = p.read_text("utf-8").splitlines()
    para: list[tuple[int, str]] = []
    section_has_form = False

    def flush() -> None:
        if not para:
            return
        body = "\n".join(t for _, t in para)
        if (
            (not _FORM_RE.search(body))
            and section_has_form is False
            and any(w.lower() in body.lower() for w in _COMMAND_WORDS)
        ):
            out.append(Problem(str(p), para[0][0], para[0][1]))
        para.clear()

    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if _HEADING_RE.match(line):
            flush()
            section_has_form = bool(_FORM_RE.search(line))
            continue
        if not line or _IGNORE_LINE.match(line):
            flush()
            continue
        para.append((i, line))
    flush()
