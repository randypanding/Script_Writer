"""上下文预算装配与历史压缩（T-33 / ADR-0013）。

零 LLM 直连：assemble 纯确定性；compress 的 LLM 调用经 nsc.runtime.models 路由
（make_llm_summarizer），测试一律注入 stub。
"""

from __future__ import annotations

from .assembler import AssembleResult, Layer, assemble, count_tokens
from .compress import compress_history, make_llm_summarizer

__all__ = [
    "AssembleResult",
    "Layer",
    "assemble",
    "compress_history",
    "count_tokens",
    "make_llm_summarizer",
]
