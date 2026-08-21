"""确定性文本统计（T-27 / ADR-0011）。纯函数、零业务阈值、零 LLM、零 IO。

所有阈值（0.15、333、300……）一律写在 `spec/checks/prose/*.yaml`，本包只提供度量。
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from itertools import pairwise
from typing import Any

#: 与 checker.registry.chars 同口径：去空白与标点后的字符数
_PUNCT = re.compile(r"[\s，。、；：？！“”‘’（）《》…—·,.;:?!\"'()\[\]<>~-]+")
_HANZI = re.compile(r"[\u4e00-\u9fff]+")
_SENT_SEP = re.compile(r"[。！？!?；;]")


def _chars(s: str) -> int:
    return len(_PUNCT.sub("", s or ""))


def split_paragraphs(text: str) -> list[str]:
    """按换行切段（一个或多个连续换行均为段界），去首尾空白、丢空段。

    与 `join_text` 互逆：`split_paragraphs(join_text(xs))` 还原 xs（PRS-001/012 依赖）。
    """
    return [p.strip() for p in re.split(r"\s*\n\s*", text or "") if p.strip()]


def split_sentences(text: str) -> list[str]:
    """按 。！？!?；; 切句，丢弃切分后 ≤2 字的碎片（语气词残句）。"""
    return [p.strip() for p in _SENT_SEP.split(text or "") if len(p.strip()) > 2]


def join_text(paras: list[str] | None) -> str:
    """段落列表拼成单文本（`"\\n".join`），供句级/段级统计与 message 渲染。"""
    return "\n".join(paras or [])


def _cv(lengths: list[int]) -> float:
    """总体变异系数 std/mean；空表或均值 0 返回 1.0（视为"不判定"）。"""
    if not lengths:
        return 1.0
    mean = statistics.fmean(lengths)
    if mean == 0:
        return 1.0
    return statistics.pstdev(lengths) / mean


def para_cv(text: str) -> float:
    """段落字符长度（去空白标点）总体变异系数；段数 <3 返回 1.0。"""
    paras = split_paragraphs(text)
    if len(paras) < 3:
        return 1.0
    return _cv([_chars(p) for p in paras])


def sent_cv(text: str) -> float:
    """句子字符长度变异系数；句数 ≤2 返回 1.0。"""
    sents = split_sentences(text)
    if len(sents) <= 2:
        return 1.0
    return _cv([_chars(s) for s in sents])


def max_consecutive_char_lines(text: str, ch: str) -> int:
    """按 `split_sentences`，最长的"连续句子都包含 ch"的句数。"""
    best = cur = 0
    for s in split_sentences(text):
        cur = cur + 1 if ch and ch in s else 0
        best = max(best, cur)
    return best


def long_paras(text: str, n: int) -> int:
    """字符长度（去空白标点）> n 的段落数。"""
    return sum(1 for p in split_paragraphs(text) if _chars(p) > n)


def density_exceeds(text: str, words: list[str], unit: int) -> bool:
    """词表命中总数是否超过 `max(1, chars // unit)`（chars 为去空白标点字符数）。"""
    hits = sum((text or "").count(w) for w in (words or []) if w)
    return hits > max(1, _chars(text or "") // max(unit, 1))


def max_word_count(text: str, words: list[str]) -> int:
    """words 中单个词在文本里出现次数的最大值（无命中为 0）。"""
    return max(((text or "").count(w) for w in (words or [])), default=0)


def same_prefix_runs(text: str) -> int:
    """相邻句前 2 字符相同的最长连续句数（句式开头复读检测）。"""
    sents = split_sentences(text)
    best = cur = 1 if sents else 0
    for a, b in pairwise(sents):
        cur = cur + 1 if a[:2] == b[:2] else 1
        best = max(best, cur)
    return best


def _ngram_list(text: str, n: int) -> list[str]:
    """纯汉字 n-gram 列表：`[\\u4e00-\\u9fff]+` 连续段内按步长 n 不重叠取片段。"""
    if n <= 0:
        return []
    grams: list[str] = []
    for run in _HANZI.findall(text or ""):
        grams.extend(run[i : i + n] for i in range(0, len(run) - n + 1, n))
    return grams


def hanzi_ngrams(text: str, n: int) -> set[str]:
    """纯汉字 n-gram 集合（标点/数字/字母打断连续段）。"""
    return set(_ngram_list(text, n))


def chapter_ngram_repeats(chapters: list[dict[str, Any]], order: int, n: int) -> int:
    """当前章（order 相等）中出现 ≥2 次、且在更早章节（order 更小）出现过的 n-gram 个数。"""
    cur = next((c for c in (chapters or []) if c.get("order") == order), None)
    if cur is None:
        return 0
    counts = Counter(_ngram_list(join_text(cur.get("paragraphs") or []), n))
    prev: set[str] = set()
    for c in chapters or []:
        o = c.get("order")
        if o is not None and o < order:
            prev |= hanzi_ngrams(join_text(c.get("paragraphs") or []), n)
    return sum(1 for g, k in counts.items() if k >= 2 and g in prev)
