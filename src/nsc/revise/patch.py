"""spot-fix 补丁引擎（T-32，规格源：inkos spot-fix-patches.ts）。

全确定性、无 LLM：解析 LLM 输出的 PATCH 块，两级匹配（精确 → 空白归一化模糊）
唯一命中后替换；落位率 ≥50% 才接受整体结果，否则保留原文。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATCH_BLOCK = re.compile(
    r"---\s*PATCH(?:\s+\d+)?\s*---[ \t]*\n(.*?)---\s*END\s+PATCH\s*---",
    re.DOTALL,
)
_TARGET_REPL = re.compile(
    r"TARGET_TEXT:[ \t]*\n(.*?)\nREPLACEMENT_TEXT:[ \t]*\n(.*)",
    re.DOTALL,
)

#: 落位门槛：成功 patch 数 / 总 patch 数 低于此比例则整体拒绝。
APPLY_MIN_RATIO = 0.5


@dataclass(frozen=True)
class Patch:
    """一处原文替换：target 唯一命中则替换为 replacement。"""

    target: str
    replacement: str


@dataclass
class PatchResult:
    """apply_patches 的结果。applied=False 时 content 为原文。"""

    applied: bool
    content: str
    applied_count: int
    skipped_count: int
    touched_chars: int
    rejected_reason: str = ""


def _trim_blank_lines(s: str) -> str:
    """去掉首尾的空白行，保留内部换行结构。"""
    lines = s.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def parse_patches(llm_output: str) -> list[Patch]:
    """从 LLM 输出解析 PATCH 块（允许 PATCH 后无编号）；target 为空的块丢弃。"""
    patches: list[Patch] = []
    for block in _PATCH_BLOCK.findall(llm_output):
        m = _TARGET_REPL.search(block)
        if m is None:
            continue
        target = _trim_blank_lines(m.group(1))
        if not target.strip():
            continue
        patches.append(Patch(target=target, replacement=_trim_blank_lines(m.group(2))))
    return patches


def _norm(s: str) -> str:
    """空白归一化：连续空白折叠为单空格并去首尾。"""
    return re.sub(r"\s+", " ", s).strip()


def _find_unique(text: str, target: str) -> tuple[int, int] | None:
    """精确匹配且要求唯一：出现第二处或未命中 → None。"""
    idx = text.find(target)
    if idx == -1 or text.find(target, idx + 1) != -1:
        return None
    return (idx, idx + len(target))


def _find_fuzzy(text: str, target: str) -> tuple[int, int] | None:
    """空白归一化后的唯一命中，并把归一化区间线性扫描映射回原文区间。

    归一化后 target 长度 < 10 视为证据不足，拒绝模糊匹配。
    """
    nt = _norm(target)
    if len(nt) < 10:
        return None
    norm_chars: list[str] = []
    pos_map: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue  # 连续空白只折叠成一个归一化空格
            norm_chars.append(" ")
            pos_map.append(i)
            prev_space = True
        else:
            norm_chars.append(ch)
            pos_map.append(i)
            prev_space = False
    norm_text = "".join(norm_chars)
    idx = norm_text.find(nt)
    if idx == -1 or norm_text.find(nt, idx + 1) != -1:
        return None
    return (pos_map[idx], pos_map[idx + len(nt) - 1] + 1)


def apply_patches(content: str, patches: list[Patch]) -> PatchResult:
    """逐 patch 独立 best-effort（先精确后模糊），单点失败只计入 skipped。

    门槛：落位率（applied/len(patches)）≥ 0.5 才 applied=True；否则保留原文。
    """
    if not patches:
        return PatchResult(
            applied=False,
            content=content,
            applied_count=0,
            skipped_count=0,
            touched_chars=0,
            rejected_reason="无补丁可应用",
        )
    buf = content
    applied = 0
    skipped = 0
    touched = 0
    for p in patches:
        span = _find_unique(buf, p.target)
        if span is None:
            span = _find_fuzzy(buf, p.target)
        if span is None:
            skipped += 1
            continue
        s, e = span
        buf = buf[:s] + p.replacement + buf[e:]
        applied += 1
        touched += len(p.target)
    if applied / len(patches) >= APPLY_MIN_RATIO:
        return PatchResult(
            applied=True,
            content=buf,
            applied_count=applied,
            skipped_count=skipped,
            touched_chars=touched,
        )
    return PatchResult(
        applied=False,
        content=content,
        applied_count=applied,
        skipped_count=skipped,
        touched_chars=touched,
        rejected_reason=f"落位率 {applied}/{len(patches)}={applied / len(patches):.0%} 低于 50% 门槛，保留原文",
    )
