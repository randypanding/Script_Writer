#!/usr/bin/env python
"""corpus 泄漏守卫 v0(L-00 落地,L-15 升级滚动哈希索引)。

两道防线:
1. 路径防线:corpus/ 与 transcripts/ 下任何文件被 git 跟踪 → 失败。
2. 内容防线:对每个待提交文本文件抽取 50 字符探针(小文件全量滑窗,大文件等距采样 500 枚),
   在语料拼接串中做定点搜索;任一命中 → 失败(疑似 >50 字符原文泄漏)。

退出码:0 通过(含无语料时仅路径防线生效,打印警告),1 失败。
"""
from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORBIDDEN = ("corpus/", "transcripts/")
PROBE_LEN = 50
MAX_PROBES_PER_FILE = 500
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".py", ".txt", ".json", ".jsonl", ".toml"}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def load_corpus_blob() -> str | None:
    corpus = ROOT / "corpus"
    if not corpus.exists():
        return None
    parts = []
    for p in sorted(corpus.rglob("*")):
        if p.is_file() and p.suffix in {".txt", ".md", ".fountain"}:
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts) if parts else None


def probes_of(text: str) -> list[str]:
    if len(text) <= PROBE_LEN:
        return [text] if text.strip() else []
    starts = range(len(text) - PROBE_LEN + 1)
    if len(starts) > MAX_PROBES_PER_FILE:
        rng = random.Random(0)
        starts = sorted(rng.sample(list(starts), MAX_PROBES_PER_FILE))
    return [text[i : i + PROBE_LEN] for i in starts]


def main() -> int:
    files = tracked_files()
    bad_paths = [f for f in files if f.startswith(FORBIDDEN)]
    # .gitignore 里 force-allow 的占位文件豁免
    bad_paths = [f for f in bad_paths if not f.endswith(".gitkeep")]
    if bad_paths:
        print("路径防线失败:以下禁地文件被 git 跟踪:")
        for f in bad_paths:
            print(f"  {f}")
        return 1

    blob = load_corpus_blob()
    if blob is None:
        # 无语料 = 无泄漏对象,路径防线已足够;CI 视为通过但打印警告
        print("警告:无语料,内容防线跳过", file=sys.stderr)
        return 0

    for f in files:
        p = ROOT / f
        if p.suffix not in TEXT_SUFFIXES or not p.is_file() or f.startswith("tests/fixtures/"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for probe in probes_of(text):
            if probe.strip() and probe in blob:
                print(f"内容防线失败:{f} 含与语料一致的 ≥{PROBE_LEN} 字符片段")
                return 1
    print(f"泄漏守卫通过({len(files)} 个跟踪文件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
