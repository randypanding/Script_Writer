"""p5_dialogue：单场 → Line[]。"""

from __future__ import annotations

import json
from typing import Any

from spec.ir.nodes import Line
from spec.passes import signatures

from . import DSPyPass, PassContext, PassFailure, cached_pass, inner_json, new_id, with_diag
from .schema_bridge import allowed_values, schema_hint

#: Line 字段真相在 spec/ir；beat_index 是归属下标（Pass 装配用），id 等由 Pass 分配。
_LINE_HINT = schema_hint(Line, skip=("id", "kind", "parent_id", "order", "provenance_id", "locked"))
_LINE_TYPES = allowed_values(Line, "line_type")


class Module(DSPyPass):
    signature = signatures.Dialogue
    pass_name = "p5_dialogue"


def _visual_contract(visuals: list[Any]) -> str:
    """必现视觉契约文案：逐字原文要求 + 用品牌数据动态生成的示范动作行。"""
    base = (
        "must_include_lines 里的每一句必须在某条对白(dialogue)中逐字原文出现；"
        "must_include_visuals 里的每一项必须逐字原文写进某条 line_type=action 的动作行，"
        "不得改写、不得替换其中任何词（例如不得把'logo'换成'标志'）。"
    )
    if visuals:
        base += f'示范动作行："镜头拉近，{visuals[0]}清晰可见。"——动作行里必须出现与该视觉项完全一致的字面子串。'
    return base


def _naming_contract(brand: dict[str, Any]) -> str:
    """产品命名契约（BM-009 真相在 brand 资产）：机械派生规范名与禁用简称。"""
    canonical: list[str] = []
    forbidden: list[str] = []
    for p in brand.get("products", []):
        canon = str(p.get("canonical_name") or p.get("name") or "")
        if canon:
            canonical.append(canon)
        forbidden += [
            str(a) for a in p.get("aliases", []) if str(a) != canon and str(a) not in canonical
        ]
    if not canonical:
        return ""
    return (
        f"产品名唯一规范写法：{canonical}。任何语境（对白、动作行、菜单、招牌、字幕）"
        f"都不得单独使用简称或变体（如 {sorted(set(forbidden)) or '别名'}），"
        "提到产品必须写完整规范名。"
    )


@cached_pass("p5_dialogue")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    scene = fragment["scene"]
    beats = fragment["beats"]
    visuals = list(
        fragment.get("must_include_visuals") or ctx.brand.get("must_include_visuals", [])
    )
    # 本场对白字数目标：按本场 Beat 的 est_duration_s × 语速机械推算（DLG-006 的前置指导）
    cps = float(ctx.profile.get("chars_per_second", 4.5))
    scene_secs = sum(float(b.get("est_duration_s", 0.0)) for b in beats)
    chars_lo = int(scene_secs * cps * 0.8)
    chars_hi = int(scene_secs * cps * 1.3)
    out = Module()(
        ctx,
        with_diag(
            {
                "scene_json": json.dumps(_public_scene(scene), ensure_ascii=False),
                "beats_json": json.dumps(
                    [
                        {"index": i, "beat_kind": b["beat_kind"], "summary": b["summary"]}
                        for i, b in enumerate(beats)
                    ],
                    ensure_ascii=False,
                ),
                "characters_json": json.dumps(fragment["characters"], ensure_ascii=False),
                "brand_constraints": json.dumps(fragment["brand_constraints"], ensure_ascii=False),
                # 必提台词/必现视觉真相在 BrandBrief（BM-007/BM-007b）：台词逐字进对白，
                # 视觉符号写进动作行（line_type=action），整部剧本各至少一处
                "must_include_lines": json.dumps(
                    fragment.get("must_include_lines") or ctx.brand.get("must_include_lines", []),
                    ensure_ascii=False,
                ),
                "must_include_visuals": json.dumps(visuals, ensure_ascii=False),
                "brand_must_contract": _visual_contract(visuals),
                "product_naming_contract": _naming_contract(ctx.brand),
                "dialogue_length_target": (
                    f"本场对白（dialogue）总字数目标 {chars_lo}-{chars_hi} 字"
                    f"（按本场 Beat 时长 {scene_secs:.0f}s × {cps} 字/秒推算）；"
                    "对白太少会导致成片时长不足（DLG-006）。"
                ),
                "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
                "retrieved_cases": fragment.get("retrieved_cases", ""),
                "line_schema_hint": _LINE_HINT + "；另需 beat_index: int（归属第几个 Beat，从 0）",
            },
            fragment,
        ),
    )
    raw_lines = inner_json(out["lines_json"], "p5_dialogue", "lines_json")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise PassFailure(scene["id"], "p5_dialogue 输出的 lines 为空")

    per_beat: dict[int, int] = {}
    lines: list[dict[str, Any]] = []
    char_ids = {str(c.get("id")) for c in fragment["characters"]}
    char_by_name = {str(c.get("name", "")): str(c.get("id")) for c in fragment["characters"]}
    for ln in raw_lines:
        bi = int(ln.get("beat_index", -1))
        if not (0 <= bi < len(beats)):
            raise PassFailure(scene["id"], f"台词引用了非法 beat_index={bi}")
        order = per_beat.get(bi, 0)
        per_beat[bi] = order + 1
        lt = str(ln.get("line_type", "dialogue")).strip().lower()
        cid = str(ln.get("character_id") or "") or None
        if cid and cid not in char_ids:  # 模型可能给了角色名而非 ULID：机械回退按名字解析
            cid = char_by_name.get(cid.strip(), cid)
        if cid and cid not in char_ids:  # 既不是已知 ID 也不是名字 = 伪造引用，拦截驱动重试
            raise PassFailure(
                scene["id"],
                f"台词引用了不存在的 character_id={cid}。只能使用 characters_json 里给出的角色 id"
                f"（{sorted(char_ids)}）或角色名。",
            )
        lines.append(
            {
                "id": new_id(),
                "kind": "line",
                "parent_id": beats[bi]["id"],
                "order": order,
                "line_type": lt if lt in _LINE_TYPES else "dialogue",
                "character_id": cid,
                "text": str(ln.get("text", "")).strip(),
                "subtext": str(ln.get("subtext", "")),
                "delivery": str(ln.get("delivery", "")),
                "is_brand_line": bool(ln.get("is_brand_line", False)),
                "provenance_id": ctx.run_id,
                "locked": False,
            }
        )
    bare = [b["id"] for b in beats if b["id"] not in {ln["parent_id"] for ln in lines}]
    if bare:
        raise PassFailure(scene["id"], f"以下 Beat 没有任何台词：{bare}")
    empties = [ln["id"] for ln in lines if not ln["text"]]
    if empties:
        raise PassFailure(scene["id"], f"存在空文本台词：{empties}")
    return {"scene_id": scene["id"], "lines": lines, "_usage": out["_usage"]}


def _public_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        k: scene[k]
        for k in (
            "location_id",
            "time_of_day",
            "interior",
            "present_character_ids",
            "goal",
            "conflict",
            "turn",
            "entry",
            "exit",
            "summary",
        )
        if k in scene
    }
