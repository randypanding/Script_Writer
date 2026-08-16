"""行数预算守卫 + 业务逻辑泄漏启发式扫描（D21 / AGENTS.md §2）。"""

from __future__ import annotations

from pathlib import Path

_BUDGET_YAML = Path("spec/BUDGETS.yaml")
# 预算 key 里"运行时 + checker"的目录（行长按 D21 的口径）。
_CODE_DIRS = ("src/nsc/runtime", "src/nsc/checker")


def line_counts() -> dict[str, int]:
    """统计手写代码行数（去空行、纯注释、以及守卫白名单文件）。"""
    import yaml

    whitelist = set()
    if _BUDGET_YAML.exists():
        whitelist = set(
            yaml.safe_load(_BUDGET_YAML.read_text("utf-8")).get("business_logic_whitelist", [])
        )
    total = 0
    for d in _CODE_DIRS:
        for p in Path(d).glob("*.py"):
            if str(p) in whitelist:
                continue
            total += _count_lines(p)
    return {"runtime+checker": total}


def _count_lines(p: Path) -> int:
    n = 0
    for raw in p.read_text("utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        n += 1
    return n


def scan_business_logic() -> list[str]:
    """启发式：Python 里出现"业务规则关键词"即报警（人工白名单在 BUDGETS.yaml）。

    只做低误报的启发：整行以 `if`/`elif` 开头且条件里出现中文业务词。真正判定靠 review。
    """
    import yaml

    whitelist = set()
    if _BUDGET_YAML.exists():
        whitelist = set(
            yaml.safe_load(_BUDGET_YAML.read_text("utf-8")).get("business_logic_whitelist", [])
        )
    hints = ("必须", "不得", "禁止", "至少", "不得超过", "hook", "brand_moment")
    problems: list[str] = []
    for d in _CODE_DIRS:
        for p in Path(d).glob("*.py"):
            if str(p) in whitelist:
                continue
            for i, raw in enumerate(p.read_text("utf-8").splitlines(), start=1):
                s = raw.lstrip()
                if (s.startswith("if ") or s.startswith("elif ")) and any(h in s for h in hints):
                    problems.append(f"{p}:{i}: {s.strip()[:60]}")
    return problems
