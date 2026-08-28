"""p2_arc：Bible → Season + Episode[] + 植入预算分配（placement_plan）+ 叙事状态规划。"""

from __future__ import annotations

import json
import re
from dataclasses import replace as _dc_replace
from typing import Any, cast

from spec.ir.overlays import BrandMoment, DarkThread, StateVariable, Thread
from spec.passes import signatures

from . import (
    DSPyPass,
    PassContext,
    PassFailure,
    cached_pass,
    inner_json,
    new_id,
    optional_json,
    parse_winner,
    with_diag,
)
from .schema_bridge import allowed_values, coerce_enum, schema_hint

#: placement_plan 的取值真相在 BrandMoment（spec/ir）；机械派生给模型看。
_PLACEMENT_HINT = schema_hint(
    BrandMoment, skip=("id", "anchor_beat_id", "integration_note", "prop_id")
)

#: ADR-0012 叙事状态三张表的字段真相（key 由 Pass 校验 slug，id 由 Pass 分配）。
_STATE_HINTS = {
    "threads": schema_hint(Thread, skip=("id",)),
    "dark_threads": schema_hint(DarkThread),
    "state_variables": schema_hint(StateVariable),
}

#: StateVariable/DarkThread 的 key 契约（spec/ir.nodes.Slug）
_SLUG_RE = re.compile(r"[a-z0-9_]{2,48}")


class Module(DSPyPass):
    signature = signatures.Arc
    pass_name = "p2_arc"
    optional_outputs = ("threads_json", "dark_threads_json", "state_variables_json")


def _best_of_n(
    ctx: PassContext, inputs: dict[str, Any], fragment: dict[str, Any], n: int
) -> dict[str, Any]:
    """best-of-n 候选 + 监制重排（R4）：同一季生成 n 版弧线，四标准选优。

    动机（实证 round24）：conflict person 缺口（50% vs 爆款 83%）的决策点在季弧层——
    节拍重排救不了弧级的"独自旅行"结构；季弧全季仅一次调用，best-of-n 成本极低。
    失败候选直接淘汰；重排故障保首候选（永不比单发差）。
    """
    cands: list[dict[str, Any]] = []
    for i in range(n):
        ctx_i = _dc_replace(ctx, seed=(ctx.seed or 0) + i * 1000) if ctx.seed is not None else ctx
        try:
            cands.append(cast(dict[str, Any], Module()(ctx_i, with_diag(inputs, fragment))))
        except PassFailure:
            continue
    if not cands:
        raise PassFailure(None, "p2_arc best-of-n 全部候选失败")
    if len(cands) == 1:
        return cands[0]
    return cands[_rerank(ctx, inputs, cands)]


def _rerank(ctx: PassContext, inputs: dict[str, Any], cands: list[dict[str, Any]]) -> int:
    """季弧重排：人与人冲突覆盖+赌注升级/前提可复述/钩型收束/植入计划合理。"""
    digest = []
    for i, c in enumerate(cands):
        try:
            eps = json.loads(c.get("episodes_json", "[]"))
        except (TypeError, json.JSONDecodeError):
            eps = []
        digest.append(
            {
                "candidate": i,
                "season_arc": str(c.get("season_arc", ""))[:200],
                "episodes": [
                    {
                        "no": ep.get("no"),
                        "logline": str(ep.get("logline", ""))[:80],
                        "hook_promise": str(ep.get("hook_promise", ""))[:60],
                        "cliffhanger": str(ep.get("cliffhanger", ""))[:60],
                    }
                    for ep in eps
                    if isinstance(ep, dict)
                ],
            }
        )
    prompt = (
        f"你是短剧监制。下面是同一季的 {len(cands)} 版弧线候选,按四条标准选一版:\n"
        "①人与人冲突覆盖:每集是否都有明确的对手方的人在场(不是主角独自感受/独自旅行——\n"
        "  爆款短剧 83% 的冲突是人与人);\n"
        "②赌注是否逐集升级(主角失败会失去什么,且一集比一集重);\n"
        "③season_arc 是否有一句可复述的前提,每集 logline 是否推进或拷问它;\n"
        "④第 1 集钩子是否威胁/承诺/颠覆型,各集 cliffhanger 是否落在揭露或危险上;\n"
        "⑤植入分配是否融进冲突线而非孤立于剧情。\n"
        '只输出合法 JSON {"winner": 候选序号(从0), "reason": "一句话"},不要任何其他内容。\n\n'
        f"bible: {inputs['bible_json'][:500]}\n"
        f"candidates: {json.dumps(digest, ensure_ascii=False)}"
    )
    try:
        res = ctx.router.complete(
            ctx.tier_of("p2_arc"),
            [{"role": "user", "content": prompt}],
            json_mode=True,
            seed=ctx.seed,
        )
        return parse_winner(res.text, len(cands))
    except Exception:
        return 0


@cached_pass("p2_arc")
def run(ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
    inputs = {
        "bible_json": json.dumps(fragment["bible"], ensure_ascii=False),
        "brand_brief_json": json.dumps(ctx.brand, ensure_ascii=False),
        "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
        "retrieved_cases": fragment.get("retrieved_cases", ""),
        "placement_schema_hint": _PLACEMENT_HINT + "；intensity 必须是 1-5 的整数",
        "narrative_state_hints": _STATE_HINTS,
    }
    # T-41 idea bank：可选"可复活素材"层（pipeline 组装，空则不加）
    revivable = str(fragment.get("revivable_ideas", "") or "")
    if revivable:
        inputs["revivable_ideas"] = revivable
    # R4：best-of-n 候选 + 监制重排（profile.pipeline.arc_best_of，缺省 1 = 原行为单次生成）
    arc_best_of = int(ctx.profile.get("pipeline", {}).get("arc_best_of", 1) or 1)
    if arc_best_of > 1:
        out = _best_of_n(ctx, inputs, fragment, arc_best_of)
    else:
        out = Module()(ctx, with_diag(inputs, fragment))
    episodes = inner_json(out["episodes_json"], "p2_arc", "episodes_json")
    placement = inner_json(out["placement_plan_json"], "p2_arc", "placement_plan_json")
    if not isinstance(episodes, list) or not episodes:
        raise PassFailure(None, "p2_arc 输出的 episodes 为空")
    if not isinstance(placement, list):
        raise PassFailure(None, "p2_arc 输出的 placement_plan 应为列表")

    season_id = new_id()
    season = {
        "id": season_id,
        "kind": "season",
        "parent_id": fragment["project_id"],
        "order": 0,
        "title": "",
        "arc_summary": out.get("season_arc", "") or "整季弧线",
        "theme": "",
        "provenance_id": ctx.run_id,
        "locked": False,
    }
    target = int(ctx.profile.get("duration_target_s", 90))
    ep_nodes = []
    for i, ep in enumerate(episodes):
        ep_nodes.append(
            {
                "id": new_id(),
                "kind": "episode",
                "parent_id": season_id,
                "order": i,
                "no": i + 1,
                "title": str(ep.get("title", "")).strip() or f"第{i + 1}集",
                "logline": str(ep.get("logline", "")).strip() or "（缺 logline）",
                "duration_target_s": int(ep.get("duration_target_s") or target),
                "hook_promise": str(ep.get("hook_promise", "")).strip(),
                "cliffhanger": str(ep.get("cliffhanger", "") or ""),
                # ADR-0012：回收声明机械过滤，保证 INV-20（引用存在且严格更早）
                "responds_to": _coerce_responds_to(ep.get("responds_to"), no=i + 1),
                "provenance_id": ctx.run_id,
                "locked": False,
            }
        )
    return {
        "season": season,
        "episodes": ep_nodes,
        "placement_plan": placement,
        "threads": _coerce_threads(optional_json(out, "threads_json", "p2_arc")),
        "state_variables": _coerce_state_vars(optional_json(out, "state_variables_json", "p2_arc")),
        "dark_threads": _coerce_dark_threads(optional_json(out, "dark_threads_json", "p2_arc")),
        "_usage": out["_usage"],
    }


def _coerce_responds_to(refs: Any, *, no: int) -> list[int]:
    """ADR-0012 / INV-20 机械归一：只保留指向更早集的合法集号，非法值丢弃不失败。"""
    out: list[int] = []
    for r in refs or []:
        try:
            r = int(r)
        except (TypeError, ValueError):
            continue
        if 1 <= r < no and r not in out:
            out.append(r)
    return out


def _coerce_threads(raw: Any) -> list[dict[str, Any]]:
    """Thread[] 机械归一（可缺省→空表）：缺标题/非 dict 丢弃；status 落合法值域。"""
    out = []
    for t in raw if isinstance(raw, list) else []:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title", "")).strip()
        if not title:
            continue
        out.append(
            {
                "id": new_id(),
                "title": title,
                "state": str(t.get("state", "") or ""),
                "status": coerce_enum(
                    t.get("status", "active"), allowed_values(Thread, "status"), "active"
                ),
            }
        )
    return out


def _coerce_state_vars(raw: Any) -> list[dict[str, Any]]:
    """StateVariable[] 机械归一（可缺省→空表）：key 必须 slug、name 必填，其余落默认。"""
    out = []
    for v in raw if isinstance(raw, list) else []:
        if not isinstance(v, dict):
            continue
        key = str(v.get("key", "")).strip()
        name = str(v.get("name", "")).strip()
        if not key or not name or not _SLUG_RE.fullmatch(key):
            continue
        typ = str(v.get("type", "number") or "number").strip().lower()
        init = v.get("initial", 0)
        out.append(
            {
                "key": key,
                "name": name,
                "type": typ if typ in ("number", "string") else "number",
                "initial": init
                if isinstance(init, (int, float, str)) and not isinstance(init, bool)
                else 0,
                "description": str(v.get("description", "") or ""),
            }
        )
    return out


def _coerce_dark_threads(raw: Any) -> list[dict[str, Any]]:
    """DarkThread[] 机械归一（可缺省→空表）：key 必须 slug、stages 至少 2 段。"""
    out = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict):
            continue
        key = str(d.get("key", "")).strip()
        name = str(d.get("name", "")).strip()
        stages = [str(s).strip() for s in d.get("stages") or [] if str(s).strip()]
        if not key or not name or len(stages) < 2 or not _SLUG_RE.fullmatch(key):
            continue
        out.append(
            {
                "key": key,
                "name": name,
                "stages": stages,
                "description": str(d.get("description", "") or ""),
            }
        )
    return out
