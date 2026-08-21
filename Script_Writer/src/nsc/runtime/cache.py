"""内容寻址缓存（D5）。这是"改一集不重跑全季"的唯一实现点。"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import time
from collections.abc import Callable
from typing import Any

import diskcache

_cache = diskcache.Cache(
    os.environ.get("NSC_CACHE_DIR", ".diskcache/passes"), size_limit=8 * 1024**3
)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _rebind_prov(obj: Any, run_id: str) -> Any:
    """递归重写产物里的 provenance_id（缓存命中路径专用）。"""
    if isinstance(obj, dict):
        return {
            k: (run_id if k == "provenance_id" else _rebind_prov(v, run_id)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_rebind_prov(x, run_id) for x in obj]
    return obj


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


def cached_pass(pass_name: str) -> Callable[..., Callable[..., Any]]:
    """装饰编译 Pass。被装饰函数签名必须是 fn(ctx, fragment) -> dict。

    ctx 协议（见 src/nsc/passes/__init__.py::PassContext）：
      - ctx.cache_versions(pass_name) -> dict：promptset/profile/brand/ruleset/model 等版本号
      - ctx.record_run(pass_name, input_hash, cache_hit, usage, wall_ms)：写 runs 表
    命中时只写 cache_hit=1 的零成本记录；NSC_NO_CACHE=1 强制绕过（仍会写 runs）。
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(ctx: Any, fragment: Any) -> Any:
            from ulid import ULID

            ctx.run_id = str(ULID())
            key = cache_key(
                pass_name=pass_name,
                input_fragment=fragment,
                **ctx.cache_versions(pass_name),
            )
            disabled = os.environ.get("NSC_NO_CACHE") == "1"
            if not disabled and key in _cache:
                ctx.record_run(pass_name, key, cache_hit=1, usage={}, wall_ms=0)
                # 命中时把产物内的 provenance_id 重绑定到本次运行记录（INV-14）
                return _rebind_prov(_cache[key], ctx.run_id)
            t0 = time.monotonic()
            result = fn(ctx, fragment)
            wall_ms = int((time.monotonic() - t0) * 1000)
            _cache[key] = result
            usage = result.get("_usage", {}) if isinstance(result, dict) else {}
            ctx.record_run(pass_name, key, cache_hit=0, usage=usage, wall_ms=wall_ms)
            return result

        return wrapper

    return deco
