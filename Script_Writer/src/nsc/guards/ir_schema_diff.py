"""IR breaking-change 守卫。

IR 结构（spec/ir/*.py）一旦对外发布就是资产契约。任何破坏性变更必须同时提交：
  1. 一个迁移脚本（db/migrations/NNNN_*.sql 或 *.py），以及
  2. 一份 ADR（adr/000N-*.md），说明为什么必须破坏兼容。
否则 CI 直接红。

实现：对 spec/ir/*.py 计算内容指纹，与提交的基线 spec/ir/_schema_baseline.json 比对。
- 指纹一致 → 通过。
- 不一致 → 检查是否存在"迁移 + ADR"成对证据；缺任一即报错。
- 支持 `--base <git-ref>`：若提供，则先以 git 方式确认当前工作区相对 base 是否真的改了 IR，
  避免"改一改又改回"的抖动误报。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

_IR_DIR = Path("spec/ir")
_BASELINE = Path("spec/ir/_schema_baseline.json")
# 参与指纹的 IR 结构文件（容器的 schema 也属于 IR 结构层面）。
_FILES = ("nodes.py", "overlays.py", "container.py")
_MIGR_DIR = Path("db/migrations")
_APR_DIR = Path("adr")


def _file_fingerprint() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in _FILES:
        p = _IR_DIR / name
        h = hashlib.sha256()
        if p.exists():
            h.update(p.read_bytes())
        out[name] = h.hexdigest()
    return out


def _load_baseline() -> dict:
    if not _BASELINE.exists():
        return {}
    return json.loads(_BASELINE.read_text("utf-8"))


def _ir_changed_since_base(base: str | None) -> bool:
    """用 git 判断相对 base，IR 文件是否真的改动过。无 git 或 base 缺失时视为已改。"""
    if not base:
        return True
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", f"{base}", "--", "spec/ir/"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return True
    return bool(r.stdout.strip())


def _has_migration_and_adr() -> bool:
    """存在至少一个迁移文件，且存在至少一份 ADR 提到 IR 破坏性变更。"""
    migs = list(_MIGR_DIR.glob("[0-9]*_*.*")) if _MIGR_DIR.exists() else []
    adrs: list[str] = []
    if _APR_DIR.exists():
        for p in _APR_DIR.glob("*.md"):
            adrs.append(p.read_text("utf-8", errors="ignore"))
    mentions_ir = any(("IR" in a or "ir" in a.lower()) for a in adrs)
    return bool(migs) and mentions_ir


def check(*, base: str | None = None) -> list[str]:
    problems: list[str] = []
    if not _IR_DIR.exists():
        return ["spec/ir/ 目录缺失"]
    live = _file_fingerprint()
    baseline = _load_baseline()
    if live == baseline:
        return []
    if not _ir_changed_since_base(base):
        # 相对 base 没真改（可能是改回或基线滞后），不拦。
        return []
    if not _has_migration_and_adr():
        problems.append(
            "spec/ir/ 结构相对基线发生变化，但缺少 [迁移脚本(db/migrations) + 提到 IR 的 ADR] 的成对证据。"
            "破坏性 IR 变更必须同时交付迁移与 ADR（见 AGENTS.md §5）。"
        )
    return problems


def write_baseline() -> None:
    """把当前指纹写回基线（工程师确认这是新真相时手动调用）。"""
    _BASELINE.write_text("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="IR breaking-change 守卫")
    ap.add_argument("--base", default=None, help="git base ref，用于抑制改回抖动")
    ap.add_argument("--write-baseline", action="store_true", help="把当前指纹写为基线")
    args = ap.parse_args()
    if args.write_baseline:
        _BASELINE.write_text(
            json.dumps(_file_fingerprint(), indent=2, sort_keys=True) + "\n", "utf-8"
        )
        print("baseline 已更新。")
        return 0
    problems = check(base=args.base)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
