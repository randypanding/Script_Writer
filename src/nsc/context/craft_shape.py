"""craft_shape 题材工艺形状（round28）：检测机制。

知识（题材关键词、每题材的形状参数）全部在 spec/craft_shape.yaml；
本模块只做"读 spec → 数关键词 → 返回形状"的机制映射（AGENTS.md §2：
禁止在 Python 里写业务规则）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_SPEC_PATH = Path("spec/craft_shape.yaml")


def _load_spec(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or _SPEC_PATH).read_text("utf-8"))


def brief_text(brief: dict[str, Any]) -> str:
    """题材检测的输入面：标题 + 原始需求 + 客户备注（与 Lab genre_classify 同源的信息面）。"""
    parts = [str(brief.get("project_title", "")), str(brief.get("raw_request", ""))]
    parts += [str(x) for x in (brief.get("notes") or [])]
    return " ".join(p for p in parts if p)


def resolve(brief: dict[str, Any], spec_path: Path | None = None) -> dict[str, Any]:
    """brief → {"genre": 桶名, **shape}。零命中/平票落 default_shape（与 Lab detect_genre 同语义）。"""
    data = _load_spec(spec_path)
    text = brief_text(brief)
    best, best_hits = str(data["default_shape"]), 0
    for genre, kws in (data.get("detect", {}).get("keywords") or {}).items():
        hits = sum(1 for kw in kws if kw in text)
        if hits > best_hits:
            best, best_hits = genre, hits
    shape = dict(data["shapes"][best])
    return {"genre": best, **shape}


def attach(
    profile: dict[str, Any], brief: dict[str, Any], spec_path: Path | None = None
) -> dict[str, Any]:
    """把解析结果并入 profile 副本（供 PassContext 使用；不修改调用方的 profile 模板）。"""
    return {**profile, "craft_shape": resolve(brief, spec_path)}
