"""T-13 数据集构建：从 cases 生成 GEPA 的 trainset/valset。

铁律（SOP_GEPA §数据切分）：**按 case 切分，绝不按节点切分**。同一个项目的
不同集出现在 train/val 两侧 = 泄漏（人物、调性、品牌约束全都一样）。

数据源：revision_pairs（人类修订对，trainset 暴露 revised_text 给 feedback）
+ ir_snapshots（golden 作为结构参考答案）。每条样本带 meta.split 供 metric 分流。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from nsc.db import init_schema

#: 默认切分比例（按 case）。val 至少 1 个 case（有 ≥2 个 case 时）。
_VAL_FRAC = 0.25


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    return conn


def split_case_ids(case_ids: list[str], val_frac: float = _VAL_FRAC) -> tuple[set[str], set[str]]:
    """确定性按 case 切分。返回 (train_case_ids, val_case_ids)。

    确定性（排序后取）保证可复现；单 case 时全进 train（val 为空，由调用方处理）。
    """
    ids = sorted(set(case_ids))
    if len(ids) < 2:
        return set(ids), set()
    n_val = max(1, round(len(ids) * val_frac))
    val = set(ids[-n_val:])
    train = set(ids[:-n_val])
    return train, val


def build_dataset(
    db_path: str | Path,
    pass_name: str,
    *,
    out_dir: str | Path = "eval/datasets",
    val_frac: float = _VAL_FRAC,
) -> dict[str, Any]:
    """从 db 生成某个 pass 的 train/val jsonl。返回统计。

    每条样本字段：
      - pass_name / case_id / split（train|val）
      - gold_*：黄金/参考答案字段（structure_match 用）
      - human_edits：仅 trainset 在 metric 里暴露（gepa_metric 按 split 分流，val 不泄漏）
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT rp.pair_id, rp.unit_kind, rp.before_text, rp.after_text, rp.dimension,
                      rp.context_json, f.case_id
               FROM revision_pairs rp JOIN feedback f ON f.feedback_id = rp.feedback_id
               WHERE f.confirmed_by <> '' ORDER BY rp.pair_id"""
        ).fetchall()
        golden = conn.execute(
            "SELECT case_id, ir_json FROM ir_snapshots WHERE kind = 'golden'"
        ).fetchall()
    finally:
        conn.close()

    golden_by_case = {cid: json.loads(ir) for cid, ir in golden}
    case_ids = [r[6] for r in rows] + [cid for cid, _ in golden]
    train_cases, val_cases = split_case_ids(case_ids, val_frac)

    samples: list[dict[str, Any]] = []
    for _pair_id, unit_kind, before, after, dim, ctx_json, case_id in rows:
        split = "val" if case_id in val_cases else "train"
        try:
            ctx = json.loads(ctx_json or "{}")
        except json.JSONDecodeError:
            ctx = {}
        samples.append(
            {
                "pass_name": pass_name,
                "case_id": case_id,
                "split": split,
                "unit_kind": unit_kind,
                "human_edits": [
                    {
                        "before": before,
                        "after": after,
                        "rationale": ctx.get("human_comment", ""),
                        "dimension": dim,
                        "field": _field_for(pass_name, unit_kind),
                    }
                ],
                "gold": _gold_fields(pass_name, golden_by_case.get(case_id)),
            }
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    train_path = out / f"{pass_name}_train.jsonl"
    val_path = out / f"{pass_name}_val.jsonl"
    n_train = n_val = 0
    with train_path.open("w", encoding="utf-8") as ft, val_path.open("w", encoding="utf-8") as fv:
        for s in samples:
            line = json.dumps(s, ensure_ascii=False) + "\n"
            if s["split"] == "train":
                ft.write(line)
                n_train += 1
            else:
                fv.write(line)
                n_val += 1
    return {
        "pass_name": pass_name,
        "train_path": str(train_path),
        "val_path": str(val_path),
        "n_train": n_train,
        "n_val": n_val,
        "train_cases": sorted(train_cases),
        "val_cases": sorted(val_cases),
    }


def _field_for(pass_name: str, unit_kind: str) -> str:
    """revision 对应到预测产物的哪个字段（edit_distance 用）。"""
    if pass_name == "p6_prose" or unit_kind == "chapter":
        return "paragraphs_json"
    if pass_name == "p5_dialogue" or unit_kind == "dialogue_block":
        return "lines_json"
    if pass_name == "p3_beatsheet" or unit_kind == "beat_sequence":
        return "beats_json"
    return "season_arc"


def _gold_fields(pass_name: str, ir: dict[str, Any] | None) -> dict[str, Any]:
    """从黄金 IR 抽 structure_match 需要的参考字段（无黄金则空）。"""
    if not ir:
        return {}
    if pass_name == "p3_beatsheet":
        return {
            "beats_json": [{"beat_kind": b.get("beat_kind")} for b in ir.get("beats", [])],
            "setup_payoffs_json": ir.get("setup_payoffs", []),
        }
    if pass_name == "p5_dialogue":
        return {
            "lines_json": [
                {
                    "character_id": ln.get("character_id"),
                    "text": ln.get("text"),
                    "is_brand_line": ln.get("is_brand_line", False),
                }
                for ln in ir.get("lines", [])
            ]
        }
    if pass_name == "p6_prose":
        paras: list[str] = []
        anchors: list[dict[str, Any]] = []
        for ch in ir.get("chapters", []):
            paras += [str(p) for p in ch.get("paragraphs", [])]
            anchors += list(ch.get("anchor_map", []) or [])
        return {"paragraphs_json": paras, "anchor_map_json": anchors}
    return {}
