"""canonical 规则冲突/重复守卫（D11 / PROMOTION.md）。

- 相邻 canonical 规则 target 指向同一 checks 规则 → 重复。
- `taste` 类规则只能 `scope.kind == client`（TAXONOMY.md 硬约束）。
- canonical 规则总数受 spec/BUDGETS.yaml::max_canonical_rules 约束（由 test 单独断言）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CANONICAL_DIR = Path("spec/rules/L3_canonical")
_BUDGET_YAML = Path("spec/BUDGETS.yaml")


def _canonical_rules() -> list[dict]:
    rules: list[dict] = []
    for p in sorted(_CANONICAL_DIR.glob("*.yaml")):
        r = yaml.safe_load(p.read_text("utf-8")) or {}
        if r.get("id"):
            r["_file"] = str(p)
            rules.append(r)
    return rules


def check_conflicts() -> list[str]:
    """target 相同的 canonical 规则不能超过 1 条（重复会稀释证据）。"""
    seen: dict[str, str] = {}
    problems: list[str] = []
    for r in _canonical_rules():
        tgt = r.get("target")
        if not tgt:
            continue
        if tgt in seen:
            problems.append(
                f"{r['_file']}: target {tgt} 与 {seen[tgt]} 重复。合并证据或改 target。"
            )
        else:
            seen[tgt] = r["_file"]
    return problems


def check_taste_scope() -> list[str]:
    """D11/taste 类观察只能产出 scope.kind == client 的规则。"""
    problems: list[str] = []
    for r in _canonical_rules():
        if r.get("dimension") == "taste":
            scope = r.get("scope") or {}
            if scope.get("kind") != "client":
                problems.append(
                    f"{r['_file']}: taste 类规则只能 scope.kind == client，实际 {scope.get('kind')!r}。"
                )
    return problems


def main() -> int:
    problems = check_conflicts() + check_taste_scope()
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
