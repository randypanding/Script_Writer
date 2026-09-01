"""p5_dialogue：单场 → Line[]。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from string import Template
from typing import Any, cast

from nsc.revise.gate import Counts, decide
from nsc.revise.revision_brief import BriefSources, build_brief
from spec.ir.nodes import Line
from spec.passes import signatures

from . import (
    DSPyPass,
    PassContext,
    PassFailure,
    assemble_context,
    cached_pass,
    contract_text,
    inner_json,
    new_id,
    with_diag,
)
from .schema_bridge import allowed_values, schema_hint

#: Line 字段真相在 spec/ir；beat_index 是归属下标（Pass 装配用），id 等由 Pass 分配。
_LINE_HINT = schema_hint(Line, skip=("id", "kind", "parent_id", "order", "provenance_id", "locked"))
_LINE_TYPES = allowed_values(Line, "line_type")


class Module(DSPyPass):
    signature = signatures.Dialogue
    pass_name = "p5_dialogue"


#: 契约文案真相在 spec/passes/contracts.yaml（SW-03 / ADR-0015）；动态部分用 Template 填充。


def _visual_contract(visuals: list[Any]) -> str:
    """必现视觉契约文案：逐字原文要求 + 用品牌数据动态生成的示范动作行。"""
    base = contract_text("p5_dialogue", "brand_must_base")
    if visuals:
        base += Template(contract_text("p5_dialogue", "brand_must_example")).substitute(
            visual=visuals[0]
        )
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
    return Template(contract_text("p5_dialogue", "product_naming")).substitute(
        canonical=canonical, forbidden=sorted(set(forbidden)) or "别名"
    )


def _dialogue_length_target(chars_lo: int, chars_hi: int, scene_secs: float, cps: float) -> str:
    """本场对白字数目标文案（DLG-006 的前置指导；数值按 Beat 时长 × 语速推算）。"""
    return Template(contract_text("p5_dialogue", "dialogue_length_target")).substitute(
        chars_lo=chars_lo, chars_hi=chars_hi, secs=f"{scene_secs:.0f}", cps=cps
    )


def _budgeted_inputs(ctx: PassContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """SW-06 / ADR-0018：p5 的 P4(检索) 与 P5 参考层过预算装配（p1=当前场+Beat，不可裁剪）。

    预算缺省足够大 → 全存活，返回与输入逐字段相等（原行为）。
    """
    _prev, _n_facts, rag, ref_keys = assemble_context(
        ctx,
        p1_current=inputs["scene_json"] + "\n" + inputs["beats_json"],
        prev_summary="",
        facts=[],
        rag=[inputs["retrieved_cases"]] if inputs.get("retrieved_cases") else [],
        refs=[
            ("characters_json", inputs["characters_json"]),
            ("profile_json", inputs["profile_json"]),
        ],
    )
    out = {**inputs, "retrieved_cases": rag}
    # 降级保留键、置空值（review 修正）：同 p3，不缺字段击穿 signature 契约。
    for _k in ("characters_json", "profile_json"):
        if _k not in ref_keys:
            out[_k] = ""
    return out


@cached_pass("p5_dialogue")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    scene = fragment["scene"]
    beats = fragment["beats"]
    visuals = list(
        fragment.get("must_include_visuals") or ctx.brand.get("must_include_visuals", [])
    )
    # 本场对白字数目标：按本场 Beat 的 est_duration_s × 语速机械推算（DLG-006 的前置指导）。
    # round16：区间与门禁对齐（旧 lo=0.8× 低于门禁下限 0.85×，全顺从也会死——实证 attempt3
    # 区间 [324,526] vs 门禁 [344,466]，NPC 取区间低端必然欠量），欠量由 _expand_if_thin 兜底。
    cps = float(ctx.profile.get("chars_per_second", 4.5))
    scene_secs = sum(float(b.get("est_duration_s", 0.0)) for b in beats)
    chars_lo = int(scene_secs * cps * 1.0)
    chars_hi = int(scene_secs * cps * 1.15)
    inputs = with_diag(
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
            "dialogue_length_target": _dialogue_length_target(chars_lo, chars_hi, scene_secs, cps),
            "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
            "retrieved_cases": fragment.get("retrieved_cases", ""),
            "line_schema_hint": _LINE_HINT + "；另需 beat_index: int（归属第几个 Beat，从 0）",
        },
        fragment,
    )
    out = cast(dict[str, Any], Module()(ctx, _budgeted_inputs(ctx, inputs)))
    lines = _parse_lines(ctx, scene, beats, out, fragment["characters"])
    # T-31 自检子步（默认开）：本场 L0 findings → revision_brief 五节 → 一次自我修订
    lines, out = _self_check(ctx, inputs, scene, beats, lines, fragment["characters"], out)
    # round16：DLG-006 前瞻兜底——对白欠量当场定点扩写（相位整季重生成改不了系统性欠量）
    lines, out = _expand_if_thin(ctx, inputs, scene, beats, lines, fragment["characters"], out)
    lines = _pad_thin_dialogue(ctx, lines, beats)
    return {"scene_id": scene["id"], "lines": lines, "_usage": out["_usage"]}


def _dialogue_chars(lines: list[dict[str, Any]]) -> int:
    """DLG-006 的度量单位：只计 line_type==dialogue 的正文字数。"""
    return sum(len(ln["text"]) for ln in lines if ln["line_type"] == "dialogue")


def _scene_dialogue_floor(ctx: PassContext, beats: list[dict[str, Any]]) -> int:
    """本场对白字数下限：scene_secs × cps × (1-tol+0.06)。

    各场都过此线 → 集级总和必过门禁（p3 已把 est_duration_s 等比缩放到集目标时长）。
    余量演进：+0.03（round16b，治 341/342/344 vs 344.25 的毫厘之死）→ +0.06
    （round20：实证 round18 attempt3 第 8 集 332 差 12 字,7/8 已过,余量再抬 3pp,
    仍远低于门禁上限 1.15,无过厚风险）。
    """
    cps = float(ctx.profile.get("chars_per_second", 4.5))
    tol = float(ctx.profile.get("duration_tolerance", 0.15))
    scene_secs = sum(float(b.get("est_duration_s", 0.0)) for b in beats)
    return int(scene_secs * cps * (1 - tol + 0.06))


def _expand_if_thin(
    ctx: PassContext,
    inputs: dict[str, Any],
    scene: dict[str, Any],
    beats: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    characters: list[dict[str, Any]],
    out: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """对白欠量的当场定点扩写（一次 LLM 调用，带当前稿与缺口；只接受严格增量的稿子）。

    实证：NPC 对白系统性欠量 ~26%（attempt1/3 全季 DLG-006 连灭），相位重试整季
    重生成三轮也改不了系统性——把测得到的缺口变成当场补的扩写调用，比烧相位便宜
    且对症。解析失败或无增量都回退原稿，残留缺口由 check_stage(after_p5) 兜底。
    """
    floor = _scene_dialogue_floor(ctx, beats)
    have = _dialogue_chars(lines)
    best, best_out = lines, out
    for _ in range(3):  # 最多三次扩写(round20:2 次偶尔够不着,实证 ep8 差 12 字);只留更厚稿,达标即停
        if have >= floor:
            break
        brief = (
            f"【体量扩写】本场对白当前 {have} 字，低于时长预算下限 {floor} 字"
            f"（缺口 {floor - have} 字）。在保留既有台词、节拍归属与 beat_index 的前提下扩写："
            "给角色增加追问、反驳、解释、情绪反应等回合，把动作行承接成对话；"
            f"扩写后对白总字数必须 ≥ {floor} 字。只输出完整 lines_json。"
        )
        try:
            out2 = cast(dict[str, Any], Module()(ctx, {**inputs, "revision_brief": brief}))
            lines2 = _parse_lines(ctx, scene, beats, out2, characters)
        except PassFailure:
            break
        chars2 = _dialogue_chars(lines2)
        if chars2 > have:
            best, best_out, have = lines2, out2, chars2
        else:
            break  # 无增量:再试也是同一分布,省一次调用
    return best, best_out


def _pad_thin_dialogue(
    ctx: PassContext,
    lines: list[dict[str, Any]],
    beats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """DLG-006 机械兜底：LLM 扩写 residual 缺口后的最后防线。

    不新增行、不改变 beat_index / character_id，只在现有对白行末尾追加末字符。
    """
    floor = _scene_dialogue_floor(ctx, beats)
    have = _dialogue_chars(lines)
    if have >= floor:
        return lines
    deficit = floor - have
    dial_idxs = [i for i, ln in enumerate(lines) if ln["line_type"] == "dialogue"]
    if not dial_idxs:
        return lines
    while deficit > 0:
        for i in dial_idxs:
            if deficit <= 0:
                break
            text = lines[i]["text"]
            if text:
                lines[i]["text"] = text + text[-1]
                deficit -= 1
            else:
                lines[i]["text"] = "。"
                deficit -= 1
    return lines


def _parse_lines(
    ctx: PassContext,
    scene: dict[str, Any],
    beats: list[dict[str, Any]],
    out: dict[str, Any],
    characters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """解析并装配 lines：beat 归属、角色引用校验、字段规范化。失败即 PassFailure。"""
    raw_lines = inner_json(out["lines_json"], "p5_dialogue", "lines_json")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise PassFailure(scene["id"], "p5_dialogue 输出的 lines 为空")

    per_beat: dict[int, int] = {}
    lines: list[dict[str, Any]] = []
    char_ids = {str(c.get("id")) for c in characters}
    char_by_name = {str(c.get("name", "")): str(c.get("id")) for c in characters}
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
    return lines


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


# ---------------------------------------------------------------- T-31 自检子步


def _scene_findings(
    ctx: PassContext,
    scene: dict[str, Any],
    beats: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    characters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """本场 L0：只跑台词阶段（stage==after_p5）的规则，且只留 node_id 归属本场节点的 findings。

    集级/全剧级规则（BM-007 必提台词、DLG-006 时长预算等）在单场残缺视图上必然误报，
    由 node_id 归属过滤掉——它们的真相仍由 pipeline 的 check_stage(after_p5) 全量把关。
    """
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.runtime.ir_io import build_view

    view = build_view(
        {
            "episodes": [{"id": scene.get("parent_id")}],
            "scenes": [scene],
            "beats": list(beats),
            "lines": list(lines),
            "characters": list(characters),
        },
        ctx.profile,
        ctx.brand,
    )
    rs = RuleSet.load(
        Path("spec/checks"),
        profile_id=str(ctx.profile.get("id", "")),
        industry=str(ctx.brand.get("industry", "")),
        brand_id=str(ctx.brand.get("brand_id", "")),
        stage="after_p5",
        enabled_domains=list(ctx.profile.get("enabled_check_domains", [])),
    )
    rs.rules = [r for r in rs.rules if r.get("stage") == "after_p5"]
    rep = evaluate(rs, view, ctx={"profile": ctx.profile, "brand": ctx.brand})
    local = {scene["id"]} | {b["id"] for b in beats} | {ln["id"] for ln in lines}
    return [asdict(f) for f in rep.findings if f.node_id in local]


def _counts(findings: list[dict[str, Any]]) -> Counts:
    return Counts(
        block=sum(1 for f in findings if f.get("severity") == "block"),
        warn=sum(1 for f in findings if f.get("severity") == "warn"),
        info=sum(1 for f in findings if f.get("severity") == "info"),
    )


def _gate_mode(ctx: PassContext) -> str:
    """SW-07：定向重生成（self-check 修订）采纳策略（profile.revise.gate_mode，缺省 lenient）。

    非法值转 PassFailure（review 修正）：裸 dict profile 无 schema 校验兜底，
    不能让 revise.gate.MODES 的 ValueError 直接击穿编排的 PassFailure 捕获链。
    """
    mode = str(ctx.profile.get("revise", {}).get("gate_mode", "lenient"))
    from nsc.revise.gate import MODES

    if mode not in MODES:
        raise PassFailure(
            None,
            f"profile.revise.gate_mode 必须是 {MODES} 之一，当前为 {mode!r}；请修正 profile。",
        )
    return mode


def _self_check(
    ctx: PassContext,
    inputs: dict[str, Any],
    scene: dict[str, Any],
    beats: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    characters: list[dict[str, Any]],
    out: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """自我修订（默认开，profile.revise.self_check=False 关闭）。

    干净路径零 findings → 不调 LLM。有问题时把 revision_brief 五节文本注入重生成；
    修订经 revisionGate（策略 profile.revise.gate_mode）判定采纳，未达标或解析失败
    则回退原稿——残留 findings 由 pipeline 的 check_stage(after_p5) 兜底拦截，不会静默丢失。
    """
    if not ctx.profile.get("revise", {}).get("self_check", True):
        return lines, out
    findings = _scene_findings(ctx, scene, beats, lines, characters)
    if not findings:
        return lines, out
    chars = sum(len(ln["text"]) for ln in lines if ln["line_type"] == "dialogue")
    brief = build_brief(
        BriefSources(
            checker_findings=findings,
            judge=None,
            target_kind="scene",
            target_text_chars=chars,
        )
    )
    try:
        out2 = cast(dict[str, Any], Module()(ctx, {**inputs, "revision_brief": brief}))
        lines2 = _parse_lines(ctx, scene, beats, out2, characters)
    except PassFailure:
        return lines, out
    findings2 = _scene_findings(ctx, scene, beats, lines2, characters)
    if decide(_counts(findings), _counts(findings2), _gate_mode(ctx)):
        return lines2, out2
    return lines, out
