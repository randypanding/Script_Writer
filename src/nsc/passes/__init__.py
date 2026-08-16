"""编译 Pass（p0..p7）。编排 = 纯 Python 函数 + @cached_pass（AGENTS.md §2）。

每个 Pass 是一个 DSPy Module（GEPA 的优化对象），但其 LLM 出口必须经
`src/nsc/runtime/models.py` 的路由（AGENTS.md §2 硬约束）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import dspy
from ulid import ULID

from nsc.runtime.cache import cached_pass
from nsc.runtime.provenance import RunRecord, RunsStore

__all__ = ["PassContext", "PassFailure", "cached_pass", "generate_json", "new_id"]


class PassFailure(Exception):  # noqa: N818  名字由 docs/HANDOFF_STRONG_MODEL.md 约定
    """结构性失败：禁止静默降级（AGENTS.md §7）。携带 node_id 供二分定位。"""

    def __init__(self, node_id: str | None, reason: str) -> None:
        self.node_id = node_id
        self.reason = reason
        super().__init__(f"[{node_id or '-'}] {reason}")


def new_id() -> str:
    return str(ULID())


@dataclass
class PassContext:
    """一次编译的运行上下文。所有版本号集中在这里，缓存键由 cache_versions 给出。"""

    profile: dict[str, Any]
    brand: dict[str, Any]
    router: Any
    store: RunsStore
    ruleset_ver: str
    spec_sha: str
    brief: dict[str, Any] = field(default_factory=dict)
    promptset_ver: str = "seed"
    seed: int | None = 1
    out_dir: Path = Path("out")
    run_id: str = ""

    def tier_of(self, pass_name: str) -> str:
        return self.profile.get("model_tiers", {}).get(pass_name, "tier_bulk")

    def _model_cfg(self, pass_name: str) -> dict[str, Any]:
        if self.router is None:
            return {}
        return self.router.resolve(self.tier_of(pass_name))

    def cache_versions(self, pass_name: str) -> dict[str, Any]:
        cfg = self._model_cfg(pass_name)
        return {
            "promptset_ver": self.promptset_ver,
            "profile_ver": str(self.profile.get("version", "")),
            "brand_ver": str(self.brand.get("version", "")),
            "ruleset_ver": self.ruleset_ver,
            "model_id": str(cfg.get("model", "none")),
            "temperature": float(cfg.get("temperature", 0.0)),
            "seed": self.seed,
            "spec_sha": self.spec_sha,
        }

    def record_run(
        self,
        pass_name: str,
        input_hash: str,
        cache_hit: int,
        usage: dict[str, Any],
        wall_ms: int,
    ) -> str:
        cfg = self._model_cfg(pass_name)
        self.store.record(
            RunRecord.new(
                run_id=self.run_id or new_id(),
                pass_name=pass_name,
                spec_sha=self.spec_sha,
                profile_ver=str(self.profile.get("version", "")),
                brand_ver=str(self.brand.get("version", "")),
                ruleset_ver=self.ruleset_ver,
                promptset_ver=self.promptset_ver,
                model_id=str(cfg.get("model", "none")),
                temperature=float(cfg.get("temperature", 0.0)),
                seed=self.seed,
                input_hash=input_hash,
                cache_hit=cache_hit,
                tokens_in=int(usage.get("tokens_in", 0)),
                tokens_out=int(usage.get("tokens_out", 0)),
                cost_usd=float(usage.get("cost_usd", 0.0)),
                wall_ms=wall_ms,
                langfuse_trace_id=str(usage.get("trace_id", "")),
            )
        )
        return self.run_id


class DSPyPass(dspy.Module):
    """把一个 dspy.Signature 落实为可运行 Module 的基类。

    指令来源优先级：prompts/<pass>.json（GEPA 产物） > signature docstring（种子）。
    """

    signature: type[dspy.Signature]
    pass_name: str = ""

    def forward(self, ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
        return generate_json(ctx, self.pass_name, self.signature, fragment)


def _load_prompt(pass_name: str) -> str:
    p = Path("prompts") / f"{pass_name}.json"
    if p.exists():
        data = json.loads(p.read_text("utf-8"))
        return str(data.get("instructions", ""))
    return ""


def parse_json_loose(text: str, pass_name: str) -> dict[str, Any]:
    """容错解析模型输出：剥代码围栏后 json.loads。失败即 PassFailure。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        raise PassFailure(None, f"{pass_name} 输出不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise PassFailure(None, f"{pass_name} 输出应为 JSON 对象")
    return data


def generate_json(
    ctx: PassContext,
    pass_name: str,
    signature: type[dspy.Signature],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """经路由调用 LLM，按 signature 的输出字段解析 JSON。结构性失败抛 PassFailure。"""
    instructions = _load_prompt(pass_name) or (signature.__doc__ or "").strip()
    out_fields: dict[str, str] = {}
    for name, f in signature.output_fields.items():
        extra: Any = getattr(f, "json_schema_extra", None) or {}
        out_fields[name] = str(extra.get("desc", ""))
    system = (
        f"{instructions}\n\n"
        "只输出一个 JSON 对象，键与含义如下（值为字符串，列表/对象请序列化为 JSON 字符串）：\n"
        + json.dumps(out_fields, ensure_ascii=False, indent=2)
    )
    user = json.dumps(inputs, ensure_ascii=False)
    res = ctx.router.complete(
        ctx.tier_of(pass_name),
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        json_mode=True,
        seed=ctx.seed,
    )
    data = parse_json_loose(res.text, pass_name)
    missing = [k for k in out_fields if k not in data]
    if missing:
        raise PassFailure(None, f"{pass_name} 输出缺少字段 {missing}")
    data["_usage"] = {
        "tokens_in": res.tokens_in,
        "tokens_out": res.tokens_out,
        "cost_usd": res.cost_usd,
        "trace_id": res.trace_id,
    }
    return data


def inner_json(value: Any, pass_name: str, field_name: str) -> Any:
    """输出字段里的嵌套 JSON 字符串 → Python 对象。"""
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value or "")
    except json.JSONDecodeError as e:
        raise PassFailure(None, f"{pass_name}.{field_name} 不是合法 JSON：{e}") from e
