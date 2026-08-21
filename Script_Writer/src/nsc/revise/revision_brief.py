"""多源修订 brief 合成器（T-31，规格源：docs/UPGRADE_PLAN_2026-08-17.md §6.2 / autonovel gen_brief）。

把三类诊断源（checker findings / 判官结果 / 目标字数）压成一份固定五节的修订指令，
供两处消费：
  - gepa_metric.py 的 feedback 通道（问题清单来源 = PROBLEM + WHAT TO CHANGE）；
  - p5_dialogue 自检子步（整段五节文本作为自我修订的问题清单输入）。

全部确定性、无 LLM。判定表（brief_type / 截断优先级）规格在方案文档 §6.2。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: VOICE RULES 的规则资产目录（form==prompt 的规则文本；测试用 monkeypatch 替换）。
_L3_DIR = Path("spec/rules/L3_canonical")

#: spec/BUDGETS.yaml::feedback.gepa_feedback_chars（GEPA feedback 与 brief 共用预算）。
DEFAULT_MAX_CHARS = 2600

#: 密度堆叠类规则 → COMPRESS；冗长类规则 → TIGHTEN（规则真相在 spec/checks/prose/）。
_COMPRESS_RULES = frozenset({"PRS-003", "PRS-004", "PRS-015"})
_TIGHTEN_RULES = frozenset({"PRS-001", "PRS-002", "PRS-012"})

#: WHAT TO CHANGE 的条目顺序（截断从尾部删 → info 先于 warn 被丢弃）。
_SEVERITY_RANK = {"warn": 0, "info": 1}


@dataclass
class BriefSources:
    """brief 的输入源。checker_findings 为 Finding as dict（rule_id/severity/message/fix_hint…）。"""

    checker_findings: list[dict]
    judge: dict | None = None  # {weakest_dimension, strongest_sentence, score: 0..1, note}
    target_kind: str = "chapter"  # chapter|scene|episode
    target_text_chars: int = 0  # 当前目标文本字数（TARGET 字数公式用）


def _fget(f: Any, key: str, default: Any = "") -> Any:
    if isinstance(f, dict):
        return f.get(key, default)
    return getattr(f, key, default)


def brief_type(score: float | None, findings: list[dict]) -> str:
    """判定修订力度：分数优先；无分数时按 findings 的密度/冗长规则驱动，默认 FIX。"""
    if score is not None:
        if score <= 0.5:
            return "REWRITE"
        if score <= 0.7:
            return "FIX"
        return "POLISH"
    for f in findings:
        if _fget(f, "rule_id") in _COMPRESS_RULES or "density" in set(_fget(f, "tags") or ()):
            return "COMPRESS"
    for f in findings:
        if _fget(f, "rule_id") in _TIGHTEN_RULES:
            return "TIGHTEN"
    return "FIX"


def _voice_rules(l3_dir: Path) -> list[str]:
    """spec/rules/L3_canonical 中 form==prompt 的规则文本；form 字段缺失时退化为全部 rationale。

    加载失败或无命中 → 空列表（渲染成一行"无"）。
    """
    try:
        docs = []
        for p in sorted(l3_dir.glob("R3-*.yaml")):
            d = yaml.safe_load(p.read_text("utf-8"))
            if isinstance(d, dict) and d.get("id"):
                docs.append(d)
    except Exception:
        return []
    if not docs:
        return []
    has_form = any("form" in d for d in docs)
    if has_form:
        docs = [d for d in docs if d.get("form") == "prompt"]
    lines = []
    for d in docs:
        # form==prompt 时 target 即规则文本；退化模式（无 form 字段）下 target 是文件路径，只取 rationale。
        text = str(d.get("target") or "").strip() if has_form else ""
        why = str(d.get("rationale") or "").strip()
        if text and why:
            lines.append(f"- {text}（{why}）")
        elif text or why:
            lines.append(f"- {text or why}")
    return lines


def _target_line(btype: str, chars: int) -> str:
    if btype == "COMPRESS":
        return f"压缩至 {int(chars * 0.55)} 字（原 {chars} 字 × 0.55）"
    if btype == "TIGHTEN":
        return f"收紧至 {int(chars * 0.85)} 字（原 {chars} 字 × 0.85）"
    return f"约 {chars} 字"


def _compile(
    sources: BriefSources, max_chars: int
) -> tuple[str, dict[str, list[str] | str], int, list[str]]:
    """组装五节素材并执行截断。返回 (brief_type, 各节正文, 截断条数, WHAT TO CHANGE 剩余行)。"""
    findings = list(sources.checker_findings)
    judge = sources.judge or {}
    score = judge.get("score")
    score = float(score) if isinstance(score, (int, float)) else None
    btype = brief_type(score, findings)

    # PROBLEM：block findings 全文 + 判官最弱维度/注记（不参与截断）。
    problem: list[str] = [
        f"- [{_fget(f, 'rule_id')}] {_fget(f, 'message')}"
        for f in findings
        if _fget(f, "severity") == "block"
    ]
    if judge.get("weakest_dimension"):
        line = f"- 判官最弱维度：{judge['weakest_dimension']}"
        if judge.get("note"):
            line += f"（{judge['note']}）"
        problem.append(line)

    # WHAT TO KEEP：判官最强句 + 零 findings 说明行。
    keep: list[str] = []
    if judge.get("strongest_sentence"):
        keep.append(f"- 判官标注最强句（保持原样）：{judge['strongest_sentence']}")
    if not findings:
        keep.append("- 本次检查零 findings，无强制变更项。")
    if not keep:
        keep = ["无"]

    # WHAT TO CHANGE：warn/info 的 message+fix_hint 编号清单。
    change = [f for f in findings if _fget(f, "severity") in _SEVERITY_RANK]
    change.sort(key=lambda f: _SEVERITY_RANK[_fget(f, "severity")])  # 稳定排序：同级保持 checker 序
    change_lines: list[str] = []
    for i, f in enumerate(change, 1):
        s = f"{i}. [{_fget(f, 'rule_id')}] {_fget(f, 'message')}"
        hint = str(_fget(f, "fix_hint") or "").strip()
        if hint:
            s += f"（{hint}）"
        change_lines.append(s)

    voice = _voice_rules(_L3_DIR)
    target = _target_line(btype, int(sources.target_text_chars))

    def _render() -> str:
        secs = (
            ("## PROBLEM", "\n".join(problem)),
            ("## WHAT TO KEEP", "\n".join(keep)),
            ("## WHAT TO CHANGE", "\n".join(change_lines)),
            ("## VOICE RULES", "\n".join(voice) if voice else "无"),
            ("## TARGET", target),
        )
        parts = [f"# Revision Brief ({btype})"]
        parts += [title if not body else f"{title}\n{body}" for title, body in secs]
        return "\n\n".join(parts)

    # 截断：超 max_chars 从 WHAT TO CHANGE 尾部删条目（PROBLEM 不删），文末加截断标记。
    removed = 0
    while change_lines:
        suffix = f"\n…(已截断 {removed} 条)"
        if len(_render()) + len(suffix) <= max_chars:
            break
        change_lines.pop()
        removed += 1
    bodies: dict[str, list[str] | str] = {
        "PROBLEM": problem,
        "WHAT TO KEEP": keep,
        "WHAT TO CHANGE": change_lines,
        "VOICE RULES": "\n".join(voice) if voice else "无",
        "TARGET": target,
    }
    return btype, bodies, removed, list(change_lines)


def brief_sections(sources: BriefSources, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, str]:
    """返回 {节名: 正文}（不带节标题）。gepa_metric 只取 PROBLEM / WHAT TO CHANGE。"""
    _, bodies, removed, change_lines = _compile(sources, max_chars)
    out = {k: "\n".join(v) if isinstance(v, list) else str(v) for k, v in bodies.items()}
    if removed:
        marker = f"…(已截断 {removed} 条)"
        out["WHAT TO CHANGE"] = ("\n".join(change_lines) + "\n" + marker).lstrip("\n")
    return out


def build_brief(sources: BriefSources, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """合成固定五节修订 brief（标题精确、顺序固定），≤ max_chars，文末带截断标记。"""
    btype, bodies, removed, _ = _compile(sources, max_chars)
    secs = (
        ("## PROBLEM", "\n".join(bodies["PROBLEM"])),
        ("## WHAT TO KEEP", "\n".join(bodies["WHAT TO KEEP"])),
        ("## WHAT TO CHANGE", "\n".join(bodies["WHAT TO CHANGE"])),
        ("## VOICE RULES", str(bodies["VOICE RULES"])),
        ("## TARGET", str(bodies["TARGET"])),
    )
    parts = [f"# Revision Brief ({btype})"]
    parts += [title if not body else f"{title}\n{body}" for title, body in secs]
    text = "\n\n".join(parts)
    if removed:
        text += f"\n…(已截断 {removed} 条)"
    if len(text) > max_chars:  # PROBLEM 自身超预算的最后手段：字符级截断，保住截断标记
        marker = f"…(已截断 {removed} 条)" if removed else "…(已截断)"
        text = text[: max_chars - len(marker) - 1].rstrip() + "\n" + marker
    return text
