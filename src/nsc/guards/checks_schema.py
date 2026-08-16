"""checks schema 守卫：
- validate_brand_mapping：spec/brand/mapping.md 里出现的每条规则 ID 必须存在。
- validate_rules：L3 canonical 规则必须有 evidence；L3 与 checks 规则 ID 对齐。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_MAPPING = Path("spec/brand/mapping.md")
_RULE_ID = re.compile(r"`([A-Z]{2,3}-\d+[a-z]?)`")


def _rule_ids() -> set[str]:
    ids: set[str] = set()
    for p in Path("spec/checks").rglob("*.yaml"):
        if p.name.startswith("_"):
            continue
        for doc in _load_docs(p):
            if doc.get("id"):
                ids.add(doc["id"])
    return ids


def _load_docs(p: Path) -> list[dict]:
    text = p.read_text("utf-8")
    if text.lstrip().startswith("---"):
        return [d for d in yaml.safe_load_all(text) if d]
    return [yaml.safe_load(text)]


def validate_brand_mapping() -> list[str]:
    """mapping.md 表格中引用的规则 ID 必须存在于 spec/checks/**.yaml。"""
    if not _MAPPING.exists():
        return ["spec/brand/mapping.md 缺失"]
    known = _rule_ids()
    problems = []
    for line_no, line in enumerate(_MAPPING.read_text("utf-8").splitlines(), start=1):
        for rid in _RULE_ID.findall(line):
            if rid not in known:
                problems.append(f"{_MAPPING}:{line_no}: 规则 {rid} 不存在于 spec/checks/")
    return problems


def validate_rules(*, level: str = "L3") -> list[str]:
    """L3 canonical 规则必须：有 evidence_ids 且 target 指向存在的 checks 规则。"""
    if level != "L3":
        return []
    known = _rule_ids()
    problems = []
    for p in sorted(Path("spec/rules/L3_canonical").glob("R3-*.yaml")):
        r = yaml.safe_load(p.read_text("utf-8")) or {}
        if not r.get("evidence_ids"):
            problems.append(f"{p}: 缺少 evidence_ids")
        tgt = r.get("target")
        if (
            tgt
            and tgt.startswith("spec/checks/")
            and tgt.split("/")[-1].replace(".yaml", "") not in known
        ):
            problems.append(f"{p}: target 指向不存在的规则 {tgt}")
    return problems


def main() -> int:
    problems = validate_brand_mapping() + validate_rules(level="L3")
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
