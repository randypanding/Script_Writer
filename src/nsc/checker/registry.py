"""assert 表达式的白名单函数表（DSL §3）。纯函数、无 IO。"""
from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

_PUNCT = re.compile(r"[\s，。、；：？！“”‘’（）《》…—·,.;:?!\"'()\[\]<>~-]+")


def chars(s: str | None) -> int:
    """中文字符数：去空白与标点后的长度。D26 的度量单位。"""
    return len(_PUNCT.sub("", s or ""))


def count(xs: Any) -> int:
    return len(xs or [])


def min_gap(xs: list[dict], key: str = "linear_index") -> float:
    vals = sorted(x[key] for x in (xs or []) if key in x)
    if len(vals) < 2:
        return float("inf")
    return min(b - a for a, b in zip(vals, vals[1:], strict=True))


def positions(xs: list[dict], total: int, key: str = "order") -> list[float]:
    if not total:
        return []
    return [x[key] / max(total - 1, 1) for x in (xs or [])]


def distinct(xs: list[Any], key: str | None = None) -> int:
    if key:
        return len({x[key] for x in (xs or [])})
    return len(set(xs or []))


def contains_any(s: str | None, words: list[str] | None) -> bool:
    s = s or ""
    return any(w and w in s for w in (words or []))


def regex_any(s: str | None, patterns: list[str] | None) -> bool:
    s = s or ""
    return any(p and re.search(p, s) for p in (patterns or []))


def lcs_len(a: str, b: str) -> int:
    """最长公共**子串**长度（FCT-002）。O(n·m) DP，输入需先截断到 20k 字符。"""
    raise NotImplementedError("T-05")


def sim(a: str, b: str) -> float:
    return fuzz.ratio(a or "", b or "") / 100.0


def emotion_range(beats: list[dict] | None) -> float:
    vs = [b["emotion"]["valence"] for b in (beats or []) if b.get("emotion")]
    return (max(vs) - min(vs)) if vs else 0.0


def monotone_runs(beats: list[dict] | None) -> int: ...
def sum_of(xs: list[dict] | None, key: str) -> float: ...
def pct(a: float, b: float) -> float:
    return (a / b) if b else 0.0


def all_of(xs: list[Any] | None, pred: str) -> bool: ...   # pred 以 x 为变量，用同一 simpleeval 环境
def any_of(xs: list[Any] | None, pred: str) -> bool: ...
def order_of(node_id: str) -> int: ...                      # 由 evaluate() 注入闭包


FUNCS: dict[str, Any] = {
    "chars": chars, "count": count, "min_gap": min_gap, "positions": positions,
    "distinct": distinct, "contains_any": contains_any, "regex_any": regex_any,
    "lcs_len": lcs_len, "sim": sim, "emotion_range": emotion_range,
    "monotone_runs": monotone_runs, "sum_of": sum_of, "pct": pct,
    "all_of": all_of, "any_of": any_of,
    "len": len, "length": len, "min": min, "max": max, "abs": abs, "int": int, "sorted": sorted,
}