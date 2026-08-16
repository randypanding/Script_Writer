"""prompts/ 不可手改守卫（AGENTS.md §0：生成物 B1）。

prompts/ 只允许由 `nsc optimize` / `nsc compile-prompts` 写入。
守卫：prompts/ 已跟踪的文件若与"编译源"不一致则报警；本仓库脚手架阶段
prompts/ 尚未生成，故返回空列表（目录不存在或为空即通过）。
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path("prompts")


def verify() -> list[str]:
    if not _ROOT.exists():
        return []
    # 脚手架阶段：prompts/ 不应有手写 .md/.txt 内容文件。
    # 一旦有编译产物，这里应比对 `nsc compile-prompts` 的刻印哈希。
    problems = []
    for p in sorted(_ROOT.rglob("*")):
        if p.is_file() and p.suffix in (".md", ".txt", ".yaml", ".yml"):
            problems.append(f"prompts/ 出现未被 nsc 编译产物刻印的文件：{p}")
    return problems


def main() -> int:
    problems = verify()
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
