"""Pass 输出 ↔ IR schema 桥（机械层，无业务判断）。

强模型（如 LongCat-2.0）会"好心"发明 IR 未定义的字段（visual_cue/style/pacing…），
而 IR 全部 `extra="forbid"`。字段白名单的真相唯一来源是 `spec/ir/` 的 pydantic 模型：
本模块只做两件事——
  1. `schema_hint`：把 IR 模型的字段清单机械序列化成 prompt 提示（让模型不用猜）；
  2. `filter_extra`：丢弃 IR 模型未定义的键（与 p2..p5 的白名单重建同一哲学）。
"""

from __future__ import annotations

import typing
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


def _allowed_values(annotation: Any) -> str:
    """Literal / StrEnum 的合法取值（机械提取；其它类型返回空串）。"""
    if typing.get_origin(annotation) is typing.Literal:
        return "|".join(str(v) for v in typing.get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return "|".join(m.value for m in annotation)
    return ""


def allowed_values(model: type[BaseModel], field_name: str) -> tuple[str, ...]:
    """IR 模型某字段的合法取值（Literal/StrEnum 机械提取；其它类型返回空元组）。"""
    vals = _allowed_values(model.model_fields[field_name].annotation)
    return tuple(vals.split("|")) if vals else ()


def coerce_enum(v: Any, allowed: tuple[str, ...], default: str) -> str:
    """值域机械归一：合法（小写）原样，非法落默认。值域真相在 spec/ir。"""
    s = str(v).strip().lower()
    return s if s in allowed else default


def schema_hint(model: type[BaseModel], *, skip: tuple[str, ...] = ("id",)) -> str:
    """IR 模型 → 一行字段清单：name(类型[, 取值][, 必填])。供 prompt 注入。"""
    parts: list[str] = []
    for name, f in model.model_fields.items():
        if name in skip:
            continue
        ann = str(f.annotation).replace("typing.", "").replace("spec.ir.", "")
        seg = f"{name}: {ann}"
        vals = _allowed_values(f.annotation)
        if vals:
            seg += f" ∈ {{{vals}}}"
        if f.is_required():
            seg += "（必填）"
        if f.description:
            seg += f"—{f.description}"
        parts.append(seg)
    return "；".join(parts)


def filter_extra(obj: Any, model: type[BaseModel]) -> Any:
    """丢弃 dict 里 IR 模型未定义的键（id 由 Pass 分配，一并剥掉）。列表逐项处理。"""
    if isinstance(obj, list):
        return [filter_extra(x, model) for x in obj]
    if isinstance(obj, dict):
        allowed = set(model.model_fields)
        return {k: v for k, v in obj.items() if k in allowed and k != "id"}
    return obj
