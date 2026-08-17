"""assert 表达式的白名单函数表（DSL §3）。纯函数、无 IO。"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from rapidfuzz import fuzz
from simpleeval import EvalWithCompoundTypes, FeatureNotAvailable

_CTX_RE = re.compile(r"@\.__ctx\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")

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
    return min(b - a for a, b in pairwise(vals))


def positions(xs: list[dict], total: int, key: str = "order") -> list[float]:
    if not total:
        return []
    return [x[key] / max(total - 1, 1) for x in (xs or [])]


def distinct(xs: list[Any], key: str | None = None) -> int:
    if key:
        return len({x[key] for x in (xs or [])})
    return len(set(xs or []))


def contains_any(s: str | list[str] | None, words: list[str] | None) -> bool:
    """s 为单个字符串或文本列表；任一文本含任一关键词即 True（CMP/BM 商用红线）。"""
    if isinstance(s, (list, tuple)):
        return any(contains_any(t, words) for t in s)
    s = s or ""
    return any(w and w in s for w in (words or []))


def count_any(s: str | None, words: list[str] | None) -> int:
    """s 中所有 words 的出现次数之和（NOV-006/007 的弱化词/空泛词堆叠检测）。"""
    s = s or ""
    return sum(s.count(w) for w in (words or []) if w)


def contains_name_variant(s: str | None, bad: list[str] | None, canon: list[str] | None) -> bool:
    """产品名违规判定（BM-009）：bad 变体出现、且该出现不被任何规范名覆盖才算违规。

    纯子串匹配会把规范名里的合法子串（如"轻乳茶"⊂"清野轻乳茶"）误判为误用；
    这里先把规范名的出现区间标为已覆盖，bad 变体只有落在覆盖区外才计违规。
    """
    text = s or ""
    covered = [False] * len(text)
    for c in canon or []:
        if not c:
            continue
        start = text.find(c)
        while start >= 0:
            for k in range(start, start + len(c)):
                covered[k] = True
            start = text.find(c, start + 1)
    for b in bad or []:
        if not b:
            continue
        pos = text.find(b)
        while pos >= 0:
            if not all(covered[pos : pos + len(b)]):
                return True
            pos = text.find(b, pos + 1)
    return False


def regex_any(s: str | list[str] | None, patterns: list[str] | None) -> bool:
    """s 为单个字符串或文本列表；任一文本命中任一 pattern 即 True（CMP-002）。"""
    if isinstance(s, (list, tuple)):
        return any(regex_any(t, patterns) for t in s)
    s = s or ""
    return any(p and re.search(p, s) for p in (patterns or []))


def lcs_len(a: str, b: str | list[str] | tuple[str, ...]) -> int:
    """最长公共**子串**长度（FCT-002）。O(n·m) DP，输入需先截断到 20k 字符。

    `b` 允许是文本列表（如 `__all_text`），此时拼接为单串再比较。
    """
    if isinstance(b, (list, tuple)):
        b = "".join(x for x in b if isinstance(x, str))  # 拼接为单串再比较
    a, b = (a or "")[:20000], (b or "")[:20000]
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = prev[:]
        cur[0] = 0
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
            else:
                cur[j] = 0
        prev = cur
    return best


def sim(a: str, b: str) -> float:
    return fuzz.ratio(a or "", b or "") / 100.0


def emotion_range(beats: list[dict] | None) -> float:
    vs = [b["emotion"]["valence"] for b in (beats or []) if b.get("emotion")]
    return (max(vs) - min(vs)) if vs else 0.0


def monotone_runs(beats: list[dict] | None) -> int:
    """情绪单调连续段（同向变化）的最大长度。"""
    beats = beats or []
    if not beats:
        return 0
    vs = [b["emotion"]["valence"] for b in beats if b.get("emotion")]
    if not vs:
        return 0
    best = cur_len = 1
    for i in range(1, len(vs)):
        if (vs[i] - vs[i - 1]) >= 0:
            cur_len += 1
        else:
            cur_len = 1
        best = max(best, cur_len)
    return best


def sum_of(xs: list[dict] | None, key: str) -> float:
    return sum(float(x[key]) for x in (xs or []) if key in x)


def pct(a: float, b: float) -> float:
    return (a / b) if b else 0.0


#: evaluate() 注入的全局闭包（order_of / exists 等需要视图上下文）
_RUNTIME: dict[str, Any] = {}


class SafeEval(EvalWithCompoundTypes):
    """simpleeval 子类：允许 `item.__字段`（我们专用于计算视图字段的命名）。

    安全边界与基类一致：只放行 dict 键名以 `__` 开头的属性读取，其余（`func_`、
    `__class__` 等方法/属性）仍被基类拦截。不引入任何新能力。
    """

    def _eval_attribute(self, node: Any) -> Any:
        if node.attr.startswith("__"):
            base = self._eval(node.value)
            if isinstance(base, dict):
                return base[node.attr]
            raise FeatureNotAvailable(f"__attribute access on non-dict: {node.attr}")
        return super()._eval_attribute(node)


#: 把 full 的 dict 当 item 用。Jinja/simpleeval 的 `item.no` 在 dict 上走属性兜底。
_AT_NOT_FOUND = object()


def _resolve_pred(pred: str) -> tuple[str, dict[str, Any]]:
    """把谓词里的 `@.__ctx.a.b` 换成 `__vN`，值从 _RUNTIME['ctx'] 解析。"""
    extra: dict[str, Any] = {}
    counter = [0]

    def _sub(m: re.Match) -> str:
        path = m.group(1).split(".")
        val: Any = _RUNTIME.get("ctx", _RUNTIME)
        for key in path:
            val = val.get(key) if isinstance(val, dict) else getattr(val, key, None)
        name = f"__v{counter[0]}"
        counter[0] += 1
        extra[name] = val
        return name

    return _CTX_RE.sub(_sub, pred), extra


def _all_of(xs: list[Any] | None, pred: str) -> bool:
    resolved, extra = _resolve_pred(pred)
    return all(
        bool(SafeEval(names={**_RUNTIME, "x": x, **extra}, functions=FUNCS).eval(resolved))
        for x in (xs or [])
    )


def _any_of(xs: list[Any] | None, pred: str) -> bool:
    resolved, extra = _resolve_pred(pred)
    return any(
        bool(SafeEval(names={**_RUNTIME, "x": x, **extra}, functions=FUNCS).eval(resolved))
        for x in (xs or [])
    )


def _order_of(node_id: str) -> int:
    return _RUNTIME.get("_order_of", lambda _: -1)(node_id)


def _exists(path: str, item: Any) -> bool:
    import jmespath

    return jmespath.search(path, item) is not None


def all_of(xs: list[Any] | None, pred: str) -> bool:
    return _all_of(xs, pred)


def any_of(xs: list[Any] | None, pred: str) -> bool:
    return _any_of(xs, pred)


def order_of(node_id: str) -> int:
    return _order_of(node_id)


#: 供 evaluate() 注入运行期上下文（_RUNTIME 遮蔽，避免全局泄漏）
def set_runtime(ctx: dict[str, Any], order_of_fn: Any) -> None:
    _RUNTIME.clear()
    _RUNTIME.update(ctx)
    _RUNTIME["_order_of"] = order_of_fn


FUNCS: dict[str, Any] = {
    "chars": chars,
    "count": count,
    "min_gap": min_gap,
    "positions": positions,
    "distinct": distinct,
    "contains_any": contains_any,
    "count_any": count_any,
    "contains_name_variant": contains_name_variant,
    "regex_any": regex_any,
    "lcs_len": lcs_len,
    "sim": sim,
    "emotion_range": emotion_range,
    "monotone_runs": monotone_runs,
    "sum_of": sum_of,
    "pct": pct,
    "all_of": all_of,
    "any_of": any_of,
    "order_of": order_of,
    "len": len,
    "length": len,
    "min": min,
    "max": max,
    "abs": abs,
    "int": int,
    "sorted": sorted,
}
