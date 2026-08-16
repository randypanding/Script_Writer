"""LLM 路由（T-04）。全项目唯一的 LLM 出口：禁止绕过本模块直接调 openai/litellm。

tier → 模型 的映射在 config/models.yaml（配置是生成物，路由策略是资产）。
成本统计走 litellm.completion_cost；Langfuse trace 在配置缺失时静默降级。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class LLMResult:
    text: str
    model_id: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    wall_ms: int
    trace_id: str = ""


class ModelRouter:
    """按 tier 路由到具体模型，带重试与成本统计。"""

    def __init__(self, config_path: str | Path = "config/models.yaml") -> None:
        cfg = yaml.safe_load(Path(config_path).read_text("utf-8"))
        self.tiers: dict[str, dict[str, Any]] = cfg.get("tiers", {})
        self.budgets: dict[str, float] = cfg.get("budgets", {})
        retry = cfg.get("retry", {})
        self.attempts: int = int(retry.get("attempts", 3))

    def resolve(self, tier: str) -> dict[str, Any]:
        if tier not in self.tiers:
            raise KeyError(f"未知模型 tier：{tier}（config/models.yaml 未定义）")
        return self.tiers[tier]

    def complete(
        self,
        tier: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        seed: int | None = None,
    ) -> LLMResult:
        import litellm

        cfg = self.resolve(tier)
        kwargs: dict[str, Any] = {
            "model": cfg["model"],
            "messages": messages,
            "temperature": cfg.get("temperature", 0.7),
            "max_tokens": cfg.get("max_tokens", 4000),
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if seed is not None:
            kwargs["seed"] = seed

        t0 = time.monotonic()
        resp = None
        delay = 1.0
        for attempt in range(self.attempts):
            try:
                resp = litellm.completion(**kwargs)
                break
            except Exception:
                if attempt == self.attempts - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        wall_ms = int((time.monotonic() - t0) * 1000)
        assert resp is not None
        data: Any = resp

        usage = getattr(data, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            cost = float(litellm.completion_cost(completion_response=data) or 0.0)
        except Exception:
            cost = 0.0
        text = data.choices[0].message.content or ""
        return LLMResult(
            text=text,
            model_id=cfg["model"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            wall_ms=wall_ms,
            trace_id=self._trace(tier, cfg["model"], text),
        )

    def _trace(self, tier: str, model_id: str, text: str) -> str:
        """Langfuse trace（best-effort）：未配置环境变量时直接跳过。"""
        if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
            return ""
        try:
            from langfuse import Langfuse

            lf = Langfuse()
            trace_fn = getattr(lf, "trace", None)
            if trace_fn is None:
                return ""
            trace = trace_fn(name=f"nsc.{tier}", metadata={"model": model_id})
            trace.generation(name="completion", model=model_id, output=text[:2000])
            return str(trace.id)
        except Exception:
            return ""
