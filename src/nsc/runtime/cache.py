"""内容寻址缓存（D5）。这是"改一集不重跑全季"的唯一实现点。"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

import diskcache

P = ParamSpec("P")
R = TypeVar("R")

_cache = diskcache.Cache(".diskcache/passes", size_limit=8 * 1024**3)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def cache_key(
    *,
    pass_name: str,
    input_fragment: Any,
    promptset_ver: str,
    profile_ver: str,
    brand_ver: str,
    ruleset_ver: str,
    model_id: str,
    temperature: float,
    seed: int | None,
    spec_sha: str,
) -> str:
    """D5 缓存键。任何一项变化都必须导致缓存失效——不要"优化"掉任何一项。"""
    payload = canonical_json(
        {
            "p": pass_name,
            "i": input_fragment,
            "pv": promptset_ver,
            "prv": profile_ver,
            "bv": brand_ver,
            "rv": ruleset_ver,
            "m": model_id,
            "t": temperature,
            "s": seed,
            "spec": spec_sha,
        }
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def cached_pass(pass_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """装饰编译 Pass。被装饰函数必须接受 kwargs `ctx`（含所有版本号）与 `fragment`。

    TODO(agent, T-04): 实现；必须
      1. 命中时写 provenance 标记 cache_hit=true，且不产生成本记录
      2. 未命中时记录 tokens/cost 到 runs 表
      3. 支持 NSC_NO_CACHE=1 环境变量强制绕过
    """

    def deco(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            raise NotImplementedError("T-04")

        return wrapper

    return deco
