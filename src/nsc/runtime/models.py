"""LLM 路由（T-04）。全项目唯一的 LLM 出口：禁止绕过本模块直接调 openai/litellm。

tier → 模型 的映射在 config/models.yaml（配置是生成物，路由策略是资产）。
成本统计走 litellm.completion_cost；Langfuse trace 在配置缺失时静默降级。
SW-01：每次调用的 prompt/response 落 SQLite transcripts（Lab ADR-0001 §接口），
best-effort——写库失败静默降级，绝不影响路由本身。
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_TRANSCRIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
  ts            TEXT NOT NULL,
  caller        TEXT NOT NULL,
  model         TEXT NOT NULL,
  prompt        TEXT NOT NULL,
  response      TEXT NOT NULL,
  tokens_in     INTEGER NOT NULL DEFAULT 0,
  tokens_out    INTEGER NOT NULL DEFAULT 0,
  cost_usd      REAL NOT NULL DEFAULT 0,
  experiment_id TEXT NOT NULL DEFAULT ''
)
"""


@dataclass(slots=True)
class LLMResult:
    text: str
    model_id: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    wall_ms: int
    trace_id: str = ""
    finish_reason: str = ""


def _has_json(text: str) -> bool:
    """文本里是否含可解析的 JSON 对象/数组（推理兜底的准入判断，纯机械解析）。"""
    from nsc.runtime.json_extract import extract_json

    return extract_json(text) is not None


class ModelRouter:
    """按 tier 路由到具体模型，带重试与成本统计。"""

    def __init__(
        self,
        config_path: str | Path = "config/models.yaml",
        *,
        transcript_db: str | Path | None = None,
        experiment_id: str = "",
    ) -> None:
        cfg = yaml.safe_load(Path(config_path).read_text("utf-8"))
        self.tiers: dict[str, dict[str, Any]] = cfg.get("tiers", {})
        self.budgets: dict[str, float] = cfg.get("budgets", {})
        retry = cfg.get("retry", {})
        self.attempts: int = int(retry.get("attempts", 3))
        # litellm 不认识的新模型（如 LongCat-2.0）用配置价兜底成本统计。
        self.cost_per_mtok: dict[str, float] = cfg.get("cost_usd_per_mtok", {}) or {}
        # SW-01 transcript 台账：库路径/实验号可用环境变量接线（Lab subprocess 场景）。
        self.transcript_db = Path(
            transcript_db or os.environ.get("NSC_TRANSCRIPT_DB") or "out/transcripts.db"
        )
        self.experiment_id = experiment_id or os.environ.get("NSC_EXPERIMENT_ID", "")
        self._tconn: sqlite3.Connection | None = None

    def _transcript_conn(self) -> sqlite3.Connection | None:
        """懒建连接；任何 IO 异常 → 返回 None（本功能 best-effort）。"""
        if self._tconn is None:
            try:
                self.transcript_db.parent.mkdir(parents=True, exist_ok=True)
                # timeout=0:transcripts 是 best-effort 记账,库被并发写锁住时立刻
                # 失败走静默路径,绝不为它阻塞路由(SW-01 review:busy timeout 会加路由延迟)
                self._tconn = sqlite3.connect(str(self.transcript_db), timeout=0.0)
                self._tconn.execute(_TRANSCRIPT_SCHEMA)
                self._tconn.commit()
            except Exception:
                self._tconn = None
        return self._tconn

    def _record_transcript(
        self,
        tier: str,
        model_id: str,
        messages: list[dict[str, str]],
        text: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
    ) -> None:
        conn = self._transcript_conn()
        if conn is None:
            return
        try:
            conn.execute(
                "INSERT INTO transcripts (ts, caller, model, prompt, response,"
                " tokens_in, tokens_out, cost_usd, experiment_id)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(UTC).isoformat(),
                    tier,
                    model_id,
                    json.dumps(messages, ensure_ascii=False),
                    text,
                    tokens_in,
                    tokens_out,
                    cost,
                    self.experiment_id,
                ),
            )
            conn.commit()
        except Exception:
            # best-effort:失败即回滚并弃置连接,防止半开事务长期持锁拖垮后续写入
            try:
                conn.rollback()
            finally:
                self._tconn = None

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
        if cfg.get("api_base"):
            kwargs["api_base"] = cfg["api_base"]
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if seed is not None:
            kwargs["seed"] = seed

        t0 = time.monotonic()
        data: Any = None
        text = ""
        delay = 1.0
        for attempt in range(self.attempts):
            try:
                data = litellm.completion(**kwargs)
            except Exception:
                if attempt == self.attempts - 1:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            text = data.choices[0].message.content or ""
            if text.strip():
                break
            # 推理模型可能把最终答案写进 reasoning_content 而 content 为空（端点行为）→
            # 兜底取推理内容，合法性交给下游容错解析；json_mode 下要求其中确有 JSON，
            # 否则视为纯思考噪声，继续重试。
            rc = str(getattr(data.choices[0].message, "reasoning_content", "") or "")
            if rc.strip() and (not json_mode or _has_json(rc)):
                text = rc
                break
            # 输出预算耗在思考上、content 与有效 reasoning 皆空 → 换 seed 重试（传输层防御）。
            if seed is not None:
                kwargs["seed"] = seed + attempt + 1
            if attempt < self.attempts - 1:
                time.sleep(delay)
                delay *= 2
        wall_ms = int((time.monotonic() - t0) * 1000)
        assert data is not None

        usage = getattr(data, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            cost = float(litellm.completion_cost(completion_response=data) or 0.0)
        except Exception:
            cost = 0.0
        if cost <= 0.0 and self.cost_per_mtok:
            # litellm 无该模型价格（如 LongCat-2.0）→ 用 config 价兜底，保证预算护栏可用。
            cost = (
                tokens_in * float(self.cost_per_mtok.get("input", 0.0))
                + tokens_out * float(self.cost_per_mtok.get("output", 0.0))
            ) / 1_000_000
        self._record_transcript(tier, cfg["model"], messages, text, tokens_in, tokens_out, cost)
        finish_reason = ""
        if data is not None:
            with contextlib.suppress(Exception):
                finish_reason = str(getattr(data.choices[0], "finish_reason", "") or "")
        return LLMResult(
            text=text,
            model_id=cfg["model"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            wall_ms=wall_ms,
            trace_id=self._trace(tier, cfg["model"], text),
            finish_reason=finish_reason,
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
