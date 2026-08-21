"""规则退役与反膨胀（T-15 / PROMOTION.md §反膨胀 §→deprecated）。

- 退役：hit_count == 0 且 last_fired_at 超 90 天（或从未命中且创建超 90 天）→ level=deprecated。
- 上限：L3_canonical 总数 ≤ spec/BUDGETS.yaml::max_canonical_rules（120）。新增须先合并/退役。
- taste 维度只能 scope.kind == client（与 guards/rules_conflict 一致，这里在退役/晋升路径再兜一道）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

L3_DIR = Path("spec/rules/L3_canonical")
BUDGETS = Path("spec/BUDGETS.yaml")

#: 退役门槛（PROMOTION.md §→deprecated）。
RETIRE_AFTER_DAYS = 90


@dataclass(slots=True)
class RetireResult:
    retired: list[str]
    kept: list[str]
    over_budget: bool
    max_canonical: int
    canonical_count: int


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text("utf-8")) or {}


def max_canonical_rules(budgets: Path = BUDGETS) -> int:
    data = _load(budgets) if budgets.exists() else {}
    return int(data.get("max_canonical_rules", 120))


def _parse_ts(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def should_retire(rule: dict[str, Any], *, now: datetime | None = None) -> bool:
    """hit_count == 0 且（last_fired_at 或 created_at）超过 90 天。"""
    if int(rule.get("hit_count", 0)) != 0:
        return False
    now = now or datetime.now(UTC)
    ref = _parse_ts(rule.get("last_fired_at")) or _parse_ts(rule.get("created_at"))
    if ref is None:
        return False
    return (now - ref) >= timedelta(days=RETIRE_AFTER_DAYS)


def canonical_count(l3_dir: Path = L3_DIR) -> int:
    if not l3_dir.exists():
        return 0
    return sum(
        1 for p in l3_dir.glob("*.yaml") if _load(p).get("id") and _load(p).get("level") == "L3"
    )


def retire(
    *,
    l3_dir: Path = L3_DIR,
    budgets: Path = BUDGETS,
    now: datetime | None = None,
) -> RetireResult:
    """扫描 L3_canonical，把满足退役条件的规则标为 deprecated（不删文件，保留审计）。"""
    now = now or datetime.now(UTC)
    retired: list[str] = []
    kept: list[str] = []
    if l3_dir.exists():
        for p in sorted(l3_dir.glob("*.yaml")):
            rule = _load(p)
            rid = rule.get("id")
            if not rid or rule.get("level") != "L3":
                continue
            if should_retire(rule, now=now):
                rule["level"] = "deprecated"
                p.write_text(yaml.safe_dump(rule, allow_unicode=True, sort_keys=False), "utf-8")
                retired.append(str(rid))
            else:
                kept.append(str(rid))
    count = canonical_count(l3_dir)
    mx = max_canonical_rules(budgets)
    return RetireResult(
        retired=retired,
        kept=kept,
        over_budget=count > mx,
        max_canonical=mx,
        canonical_count=count,
    )


def enforce_taste_scope(rule: dict[str, Any]) -> dict[str, Any]:
    """taste 维度强制 client scope（晋升/退役路径的兜底，与 guards 一致）。"""
    if rule.get("dimension") == "taste":
        scope = rule.get("scope") or {}
        if scope.get("kind") != "client":
            scope["kind"] = "client"
            scope.setdefault("value", "")
            rule["scope"] = scope
    return rule
