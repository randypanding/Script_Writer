"""编译编排（D5）：p0..p7 正向流水线 + 依赖闭包局部重编译。

编排 = 纯 Python 函数（AGENTS.md §2：禁止引入编排框架）。
每个阶段后立刻跑对应该阶段的 L0（不变量 + spec/checks），失败即 PassFailure，
feedback 文本可直接进 GEPA（D13）。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from nsc.checker.interpreter import CheckReport, RuleSet, evaluate
from nsc.revise.gate import Counts
from nsc.revise.idea_bank import deposit, list_ideas, render_for_prompt
from nsc.revise.snapshot import save_snapshot
from nsc.runtime.ir_io import build_view, merge_preserving_ids
from spec.ir.container import NarrativeIR, NovelChapter, Provenance
from spec.ir.invariants import Violation, check_all, inv_16_id_stability

from . import (
    PassContext,
    PassFailure,
    new_id,
    p0_intake,
    p1_bible,
    p2_arc,
    p3_beatsheet,
    p4_scene,
    p5_dialogue,
    p6_prose,
    p7_render,
)

_DEP_GRAPH: dict[str, Any] = yaml.safe_load(Path("spec/passes/dep_graph.yaml").read_text("utf-8"))

#: spec/checks 规则的合法 stage（DSL §2）。after_p1 只有不变量，没有规则。
_RULE_STAGES = ("after_p2", "after_p3", "after_p4", "after_p5", "after_p6", "final")


def invalidation_closure(changed_fields: list[str]) -> list[list[str]]:
    """字段变更 → 失效的 [(pass, 粒度)]。规则全部来自 dep_graph.yaml。"""
    out: list[list[str]] = []
    for field_name in changed_fields:
        for pattern, targets in _DEP_GRAPH.get("invalidation", {}).items():
            if _field_match(pattern, field_name):
                for t in targets:
                    pair = [t[0], t[1]]
                    if pair not in out:
                        out.append(pair)
    return out


def _field_match(pattern: str, field_name: str) -> bool:
    for alt in pattern.split("|"):
        rx = re.escape(alt).replace(r"\*", "[^.]+")
        if re.fullmatch(rx, field_name):
            return True
        if "." not in alt and field_name.endswith("." + alt):
            return True
    return False


def _dbg(msg: str) -> None:
    """NSC_DEBUG_PIPELINE=1 时把编排轨迹追加到 out/pipeline_debug.log（排障用）。"""
    if not os.environ.get("NSC_DEBUG_PIPELINE"):
        return
    out = Path("out/pipeline_debug.log")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _accum(diag: str, new: str) -> str:
    """累积相位诊断：让重试同时看到历史全部问题，避免"修一个引入一个"的打地鼠。"""
    return f"{diag}\n---\n{new}" if diag else new


def _attempts_of(ctx: PassContext, key: str, default: int) -> int:
    """SW-07：读 profile.pipeline.<key> 的次数旋钮；坏值转 PassFailure（诊断句，review 修正）。"""
    raw = ctx.profile.get("pipeline", {}).get(key, default)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError) as e:
        raise PassFailure(
            None,
            f"profile.pipeline.{key} 必须是正整数，当前为 {raw!r}；请修正 profile 配置后重跑。",
        ) from e


def _pass_attempts(ctx: PassContext) -> int:
    """SW-07：单 Pass 输出波动重试次数（profile.pipeline.pass_attempts，缺省 2）。"""
    return _attempts_of(ctx, "pass_attempts", 2)


def _phase_attempts(ctx: PassContext) -> int:
    """SW-07：p3/p4、p5、p6 相位级定向重生成次数（profile.pipeline.phase_attempts，缺省 3）。"""
    return _attempts_of(ctx, "phase_attempts", 3)


_TRANSIENT_MARKERS = (
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ReadTimeout",
    "RemoteProtocolError",
    "ServiceUnavailableError",
)


def _is_transient(exc: Exception) -> bool:
    """传输层故障判定（shim 重启/CNB 抖动/网关超时）：类名匹配或内建网络异常。

    实证 attempt2：shim 重启期间 APIConnectionError 逃过所有重试通道直接杀死整轮——
    传输故障必须与 PassFailure 走同一条带诊断重试通道，而不是让 2.5h 的跑批陪葬。
    """
    name = type(exc).__name__
    return any(m in name for m in _TRANSIENT_MARKERS) or isinstance(
        exc, (ConnectionError, TimeoutError, OSError)
    )


def _retry_pass(
    fn: Any, ctx: PassContext, fragment: dict[str, Any], *, attempts: int | None = None
) -> Any:
    """生成型 Pass 的输出波动重试：把上次失败诊断注入重试输入（D13 反馈驱动再生成）。

    LLM 输出有随机性（漏字段/数错个数），带诊断的重试能显著降低端到端失败率；
    失败语义不变（全部失败照样抛 PassFailure，GEPA 反馈信号不受影响），缓存只存成功产物。
    attempts：SW-07 缺省读 profile.pipeline.pass_attempts（原常量 2）。
    传输故障（_is_transient）同样重试；耗尽后落成 PassFailure 让相位重试接管。
    """
    total = attempts if attempts is not None else _pass_attempts(ctx)
    last_reason = ""
    for i in range(total):
        frag = {**fragment, "_previous_failure": last_reason} if last_reason else fragment
        try:
            return fn(ctx, frag)
        except PassFailure as e:
            last_reason = str(e)
            if i == total - 1:
                raise
        except Exception as e:  # noqa: BLE001 —— 只放行传输故障,代码 bug 原样上抛
            if not _is_transient(e):
                raise
            last_reason = f"传输故障:{type(e).__name__} {str(e)[:120]}"
            if i == total - 1:
                raise PassFailure(None, last_reason) from e


def _run_checks(
    ctx: PassContext, ir: NarrativeIR, inv_stage: str, rule_stage: str | None = None
) -> tuple[list[Violation], CheckReport | None]:
    """跑阶段 L0（不变量 + 声明式规则）并返回原始结果；不抛 PassFailure（供快照计数）。"""
    violations = check_all(ir, ctx.profile, stage=inv_stage)
    stage = rule_stage if rule_stage in _RULE_STAGES else None
    if stage is None:
        return violations, None
    view = build_view(ir.model_dump(), ctx.profile, ctx.brand)
    rs = RuleSet.load(
        profile_id=str(ctx.profile.get("id", "")),
        industry=str(ctx.brand.get("industry", "")),
        brand_id=str(ctx.brand.get("brand_id", "")),
        stage=stage,
        enabled_domains=list(ctx.profile.get("enabled_check_domains", [])),
    )
    rep = evaluate(rs, view, ctx={"profile": ctx.profile, "brand": ctx.brand})
    return violations, rep


def _fail_on_violations(violations: list[Violation], rep: CheckReport | None) -> None:
    """检查结果 → PassFailure（block/违规即抛，诊断可直接喂 GEPA）。"""
    if violations:
        v = violations[0]
        raise PassFailure(v.node_id, "；".join(x.message for x in violations[:3]))
    if rep is not None:
        if rep.errors:
            raise PassFailure(None, "规则本身报错：" + "；".join(rep.errors[:3]))
        if rep.blocked:
            raise PassFailure(None, rep.as_feedback_text())


def check_stage(
    ctx: PassContext, ir: NarrativeIR, inv_stage: str, rule_stage: str | None = None
) -> None:
    """阶段 L0：先不变量，后声明式规则。block/违规即 PassFailure。

    不变量与规则的 stage 解耦：INV-11（每 Beat 有台词）在 after_p4 的不变量集里，
    但台词 p5 才生成，所以 p4 之后的检查用 after_p3 的不变量 + after_p4 的规则。
    """
    violations, rep = _run_checks(ctx, ir, inv_stage, rule_stage)
    _fail_on_violations(violations, rep)


def _counts_of(violations: list[Violation], rep: CheckReport | None) -> Counts:
    """T-38 快照计数：不变量违规计入 block，规则 findings 按 severity 统计。"""
    block, warn, info = len(violations), 0, 0
    for f in rep.findings if rep is not None else []:
        if f.severity == "block":
            block += 1
        elif f.severity == "warn":
            warn += 1
        else:
            info += 1
    return Counts(block=block, warn=warn, info=info)


def _state_db(ctx: PassContext, project_id: str) -> Path:
    """T-38/T-41 共用的项目 state 库：out/<project_id>/state.db（快照链 + idea bank）。"""
    return ctx.out_dir / project_id / "state.db"


def _snapshot_safe(
    db_path: Path, project_id: str, stage: str, ir: NarrativeIR, counts: Counts
) -> None:
    """T-38 快照落盘。机制容错：失败只记 stderr 一行，绝不破坏主管线。"""
    try:
        save_snapshot(db_path, project_id, stage, ir.model_dump_json(), counts)
    except Exception as e:  # state 库故障不应吞掉编译产物（机制容错，非结构错误吞并）
        sys.stderr.write(f"[snapshot] 快照写入失败（project={project_id} stage={stage}）：{e}\n")


def _final_check_and_snapshot(ctx: PassContext, ir: NarrativeIR, project_id: str) -> None:
    """final 检查 + 快照：先统计计数落盘（有 block 也存，stage=final-blocked，回退需要），再抛。"""
    violations, rep = _run_checks(ctx, ir, "final", "final")
    counts = _counts_of(violations, rep)
    db_path = _state_db(ctx, project_id)
    _snapshot_safe(db_path, project_id, "final-blocked" if counts.block else "final", ir, counts)
    _fail_on_violations(violations, rep)


def _deposit_safe(
    db_path: Path,
    project_id: str,
    node_kind: str,
    content: str,
    source_node_id: str = "",
    removed_run_id: str = "",
    reason: str = "",
) -> None:
    """T-41 idea bank 入库。机制容错：失败只记 stderr 一行。"""
    try:
        deposit(
            db_path,
            project_id,
            node_kind,
            content,
            source_node_id=source_node_id,
            removed_run_id=removed_run_id,
            reason=reason,
        )
    except Exception as e:  # bank 故障不应吞掉重编译（机制容错）
        sys.stderr.write(f"[idea_bank] deposit 失败（project={project_id}）：{e}\n")


def _deposit_removed_beats(
    db_path: Path, project_id: str, raw: dict[str, Any], ep_id: str, run_id: str
) -> None:
    """T-41：局部重编译替换前，把该集被删 Beat 的 summary 存入素材银行。"""
    scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep_id}
    for b in raw["beats"]:
        if b["parent_id"] in scene_ids:
            _deposit_safe(
                db_path,
                project_id,
                "beat",
                str(b.get("summary", "")),
                source_node_id=str(b.get("id", "")),
                removed_run_id=run_id,
                reason="recompile_replace",
            )


def _revivable_layer(db_path: Path, project_id: str) -> str:
    """T-41：idea bank 未复活素材的可选注入层；空库/故障 → 空串（stub 路径零影响）。"""
    try:
        ideas = list_ideas(db_path, project_id)
    except Exception as e:  # bank 故障时静默降级为无注入（机制容错）
        sys.stderr.write(f"[idea_bank] 读取失败（project={project_id}）：{e}\n")
        return ""
    return render_for_prompt(ideas, limit=5) if ideas else ""


def _retrieved(ctx: PassContext, unit_kind: str, query: str) -> str:
    """T-16 检索注入：命中案例格式化成 Pass 的 retrieved_cases；未启用/无命中则空串。"""
    if ctx.retrieval is None or not query:
        return ""
    return ctx.retrieval.fetch(
        query,
        unit_kind=unit_kind,
        profile_id=str(ctx.profile.get("id", "")),
        industry=str(ctx.brand.get("industry", "")),
        brand_id=str(ctx.brand.get("brand_id", "")),
    )


def run_pipeline(ctx: PassContext) -> NarrativeIR:
    """正向全量编译：brief → IR → 交付物。返回最终 IR（产物已落盘 out/）。"""
    run_ids: list[str] = []
    st: dict[str, Any] = {
        "seasons": [],
        "episodes": [],
        "scenes": [],
        "beats": [],
        "lines": [],
        "chapters": [],
        "brand_moments": [],
        "setup_payoffs": [],
        # --- ADR-0012 运行时叙事状态层（p2 规划三张表；facts 由 p3 逐集积累） ---
        "facts": [],
        "threads": [],
        "state_variables": [],
        "dark_threads": [],
        "voice": None,
    }

    def cur() -> NarrativeIR:
        return _assemble(ctx, st, _provenance(ctx, run_ids))

    def track() -> None:
        run_ids.append(ctx.run_id)

    r0 = p0_intake.run(ctx, {"raw_brief": ctx.brief, "raw_brand": ctx.brand})
    track()
    brief = ctx.brief
    st["project"] = {
        "id": new_id(),
        "kind": "project",
        "parent_id": None,
        "order": 0,
        "title": brief.get("project_title") or "未命名项目",
        "logline": (r0["normalized_brief"].split("\n")[0] or "（缺 logline）")[:80],
        "profile_id": brief.get("profile", ""),
        "brand_id": brief.get("brand", ""),
        "client_note": "\n".join(brief.get("notes", [])),
        "provenance_id": ctx.run_id,
        "locked": False,
    }
    st["constraints"] = r0["constraints"]

    r1 = _retry_pass(
        p1_bible.run,
        ctx,
        {
            "normalized_brief": r0["normalized_brief"],
            "retrieved_cases": _retrieved(ctx, "chapter", r0["normalized_brief"]),
        },
    )
    track()
    bible = {k: r1[k] for k in ("characters", "locations", "props", "motifs", "tone")}
    st.update(bible)

    pid = str(st["project"]["id"])
    bank_db = _state_db(ctx, pid)
    # T-41：bank 有未复活素材才附素材层（空则不加，stub 路径零影响）
    revivable = _revivable_layer(bank_db, pid)
    frag2 = {
        "bible": bible,
        "project_id": st["project"]["id"],
        "retrieved_cases": _retrieved(ctx, "scene_card", r0["normalized_brief"]),
    }
    if revivable:
        frag2["revivable_ideas"] = revivable
    r2 = _retry_pass(p2_arc.run, ctx, frag2)
    track()
    st["seasons"] = [r2["season"]]
    st["episodes"] = r2["episodes"]
    st["threads"] = r2.get("threads", [])
    st["state_variables"] = r2.get("state_variables", [])
    st["dark_threads"] = r2.get("dark_threads", [])
    check_stage(ctx, cur(), "after_p1")
    check_stage(ctx, cur(), "after_p2", "after_p2")

    episodes = r2["episodes"]
    # SW-05：p3 fragment 组成旋钮（profile.context.*，缺省 = 原行为）
    p3_ctx = ctx.profile.get("context", {})
    prev_window = max(0, int(p3_ctx.get("prev_summary_window", 1)))
    fact_fields = _known_fact_fields_of(ctx.profile)
    inject_threads = bool(p3_ctx.get("inject_threads", False))
    ep_summaries: list[str] = []
    # p3（逐集）+ p4 + after_p3/p4 检查作为一个相位：L0 拦截（如 BM-002 植入间隔）时
    # 带诊断整体重试（D13 反馈驱动再生成，诊断累积）；重试前恢复相位前的状态。
    diag = ""
    phase_n = _phase_attempts(ctx)
    for attempt in range(phase_n):
        snapshot = {
            k: list(st[k]) for k in ("beats", "setup_payoffs", "brand_moments", "scenes", "facts")
        }
        ep_state_snap = {e["id"]: list(e.get("state_changes", [])) for e in episodes}
        try:
            for i, ep in enumerate(episodes):
                placement = [
                    p for p in r2["placement_plan"] if int(p.get("episode_no", -1)) == ep["no"]
                ]
                frag3: dict[str, Any] = {
                    "episode": ep,
                    "bible": bible,
                    "placement": placement,
                    "required_brand_moment_beats": len(placement),
                    "prev_episode_summary": _window_join(ep_summaries, prev_window),
                    "next_episode_promise": episodes[i + 1]["hook_promise"]
                    if i + 1 < len(episodes)
                    else "",
                    # ADR-0012：跨集回收上下文 + 状态变更声明域（facts/threads 等表见上）
                    "known_facts": _known_facts(st["facts"], fact_fields),
                    "declared_state": _declared_state(st),
                    "retrieved_cases": _retrieved(ctx, "beat_sequence", _ep_query(ep)),
                }
                if diag:
                    frag3["_previous_failure"] = diag
                if revivable:
                    frag3["revivable_ideas"] = revivable
                if inject_threads:
                    frag3["threads"] = _threads_view(st["threads"])
                r3 = _retry_pass(p3_beatsheet.run, ctx, frag3)
                track()
                ep_summaries.append("；".join(b["summary"] for b in r3["beats"]))
                st["beats"] += r3["beats"]
                st["setup_payoffs"] += r3["setup_payoffs"]
                st["brand_moments"] += r3["brand_moments"]
                st["facts"] += r3.get("facts", [])
                ep["state_changes"] = r3.get("state_changes", [])

            for ep in episodes:
                ep_beats = [b for b in st["beats"] if b["_episode_id"] == ep["id"]]
                r4 = _retry_pass(
                    p4_scene.run, ctx, {"episode": ep, "beats": ep_beats, "bible": bible}
                )
                track()
                st["scenes"] += r4["scenes"]
                st["beats"] = [b for b in st["beats"] if b["_episode_id"] != ep["id"]] + r4["beats"]
            st["setup_payoffs"] = p3_beatsheet.resolve_pending(st["setup_payoffs"])
            st["facts"] = p3_beatsheet.apply_fact_cascade(st["facts"])
            ir3 = cur()
            violations, rep = _run_checks(ctx, ir3, "after_p3", "after_p4")
            _fail_on_violations(violations, rep)
            # T-38：p3 全季后处理（facts 级联）完成且相位检查通过 → 存快照
            _snapshot_safe(bank_db, pid, "after_p3", ir3, _counts_of(violations, rep))
            _dbg("p3/p4-phase check passed")
            break
        except PassFailure as e:
            _dbg(f"p3/p4-phase caught: {str(e)[:160]!r}")
            st.update(snapshot)
            for e_ in episodes:
                e_["state_changes"] = ep_state_snap[e_["id"]]
            diag = _accum(diag, str(e))
            if attempt == phase_n - 1:
                raise

    # p5 相位：对白 + after_p5 检查（如 BM-007 必提台词）；拦截时带累积诊断整体重试。
    diag5 = ""
    phase5_n = _phase_attempts(ctx)
    for attempt in range(phase5_n):
        snapshot_lines = list(st["lines"])
        _dbg(f"p5-phase attempt={attempt} scenes={len(st['scenes'])} diag={diag5[:120]!r}")
        try:
            for sc in st["scenes"]:
                sc_beats = [b for b in st["beats"] if b["parent_id"] == sc["id"]]
                frag = _p5_fragment(sc, sc_beats, bible, st["constraints"], brand=ctx.brand)
                frag["retrieved_cases"] = _retrieved(
                    ctx, "dialogue_block", _scene_query(sc, sc_beats)
                )
                if diag5:
                    frag["_previous_failure"] = diag5
                r5 = _retry_pass(p5_dialogue.run, ctx, frag)
                track()
                st["lines"] += r5["lines"]
            check_stage(ctx, cur(), "after_p5", "after_p5")
            _dbg("p5-phase check passed")
            break
        except PassFailure as e:
            _dbg(f"p5-phase caught PassFailure: {str(e)[:160]!r}")
            st["lines"] = snapshot_lines
            diag5 = _accum(diag5, str(e))
            if attempt == phase5_n - 1:
                raise

    if ctx.profile.get("novel", {}).get("enabled"):
        st["voice"] = _voice(ctx, bible)
        # p6 相位：小说 + after_p6 检查（如 NOV-001 锚点覆盖）；同上带累积诊断重试。
        diag6 = ""
        phase6_n = _phase_attempts(ctx)
        for attempt in range(phase6_n):
            snapshot_chapters = list(st["chapters"])
            _dbg(f"p6-phase attempt={attempt} diag={diag6[:120]!r}")
            try:
                for ep in episodes:
                    frag6 = _p6_fragment(cur(), bible, st["voice"], ep["id"])
                    if diag6:
                        frag6["_previous_failure"] = diag6
                    r6 = _retry_pass(p6_prose.run, ctx, frag6)
                    track()
                    st["chapters"].append(r6["chapter"])
                check_stage(ctx, cur(), "after_p6", "after_p6")
                _dbg("p6-phase check passed")
                break
            except PassFailure as e:
                _dbg(f"p6-phase caught PassFailure: {str(e)[:160]!r}")
                st["chapters"] = snapshot_chapters
                diag6 = _accum(diag6, str(e))
                if attempt == phase6_n - 1:
                    raise

    ir = cur()
    p7_render.run(ctx, ir.model_dump())
    track()
    ir = cur()
    _dbg("final check start")
    _final_check_and_snapshot(ctx, ir, pid)  # T-38：final 检查 + 快照（blocked 也存）
    _dbg("final check passed")
    return ir


def recompile_episode(ctx: PassContext, ir: NarrativeIR, ep_no: int) -> NarrativeIR:
    """局部重编译单集：只触发该集的 p3–p7（dep_graph 粒度 episode）。

    契约：未变节点 ID 必须保留（INV-16），locked 节点逐字保留（dep_graph.locked_policy）。
    """
    old = ir
    raw = old.model_dump()
    ep = next((e for e in raw["episodes"] if e["no"] == ep_no), None)
    if ep is None:
        raise PassFailure(None, f"第 {ep_no} 集不存在")
    bible = {k: raw[k] for k in ("characters", "locations", "props", "motifs", "tone")}
    ordered = sorted(raw["episodes"], key=lambda e: e["order"])
    idx = next(i for i, e in enumerate(ordered) if e["no"] == ep_no)

    run_ids: list[str] = []

    def track() -> None:
        run_ids.append(ctx.run_id)

    pid = str(raw["project"]["id"])
    bank_db = _state_db(ctx, pid)
    # T-41：上次重编译存入 bank 的未复活素材作为可选注入层（空则不加）
    revivable = _revivable_layer(bank_db, pid)
    # SW-05：p3 fragment 组成旋钮（与 run_pipeline 同一 profile.context.* 段）
    _p3c = ctx.profile.get("context", {})
    r_window = max(0, int(_p3c.get("prev_summary_window", 1)))

    frag3 = {
        "episode": ep,
        "bible": bible,
        "placement": _placement_of(raw, ep),
        "required_brand_moment_beats": len(_placement_of(raw, ep)),
        "prev_episode_summary": _window_join(
            [_episode_digest(raw, e["id"]) for e in ordered[max(0, idx - r_window) : idx]],
            r_window,
        ),
        "next_episode_promise": ordered[idx + 1]["hook_promise"] if idx + 1 < len(ordered) else "",
        # ADR-0012：其他集已成立的 facts 可被本集回收；状态声明域来自 IR 表
        "known_facts": _known_facts(
            [f for f in raw.get("facts", []) if f.get("episode_no") != ep["no"]],
            _known_fact_fields_of(ctx.profile),
        ),
        "declared_state": _declared_state(raw),
        "retrieved_cases": _retrieved(ctx, "beat_sequence", _ep_query(ep)),
    }
    if revivable:
        frag3["revivable_ideas"] = revivable
    if _p3c.get("inject_threads", False):
        frag3["threads"] = _threads_view(raw.get("threads", []))
    r3 = _retry_pass(p3_beatsheet.run, ctx, frag3)
    track()
    r4 = _retry_pass(p4_scene.run, ctx, {"episode": ep, "beats": r3["beats"], "bible": bible})
    track()
    lines: list[dict[str, Any]] = []
    for sc in r4["scenes"]:
        sc_beats = [b for b in r4["beats"] if b["parent_id"] == sc["id"]]
        frag = _p5_fragment(sc, sc_beats, bible, raw.get("constraints", []), brand=ctx.brand)
        frag["retrieved_cases"] = _retrieved(ctx, "dialogue_block", _scene_query(sc, sc_beats))
        r5 = _retry_pass(p5_dialogue.run, ctx, frag)
        track()
        lines += r5["lines"]

    ep["state_changes"] = r3.get("state_changes", [])
    # T-41：替换/删除 beats 前把被删内容存入 idea bank（回退复用的素材银行）
    _deposit_removed_beats(bank_db, pid, raw, ep["id"], ctx.run_id)
    new_raw = _splice_episode(
        raw,
        ep["id"],
        r4["scenes"],
        r4["beats"],
        lines,
        r3["brand_moments"],
        r3["setup_payoffs"],
        new_facts=r3.get("facts", []),
    )
    new_ir = NarrativeIR.model_validate(_strip_private(new_raw))

    if raw.get("voice"):
        beats_with_lines = _attach_lines(r4["beats"], lines)
        r6 = _retry_pass(
            p6_prose.run,
            ctx,
            {
                "episode": ep,
                "beats": beats_with_lines,
                "scenes_with_lines": _scenes_with_lines(r4["scenes"], beats_with_lines, raw),
                "bible": bible,
                "voice": raw["voice"],
            },
        )
        track()
        keep = [c for c in new_ir.chapters if c.episode_id != ep["id"]]
        new_ir = new_ir.model_copy(
            update={"chapters": [*keep, NovelChapter.model_validate(r6["chapter"])]}
        )

    merged = merge_preserving_ids(old, new_ir)
    _restore_locked(old, merged)
    _remap_overlays(new_ir, merged)
    merged.provenance.extend(_provenance(ctx, run_ids))
    bad = inv_16_id_stability(old, merged)
    if bad:
        raise PassFailure(bad[0].node_id, "；".join(x.message for x in bad[:3]))
    _final_check_and_snapshot(ctx, merged, pid)  # T-38：final 检查 + 快照（blocked 也存）
    p7_render.run(ctx, merged.model_dump())
    return merged


# ---------------------------------------------------------------- 内部 helpers


def _assemble(ctx: PassContext, st: dict[str, Any], provenance: list[Provenance]) -> NarrativeIR:
    raw = {
        "project": st["project"],
        "seasons": st["seasons"],
        "episodes": st["episodes"],
        "scenes": st["scenes"],
        "beats": st["beats"],
        "lines": st["lines"],
        "characters": st.get("characters", []),
        "locations": st.get("locations", []),
        "props": st.get("props", []),
        "brand_moments": st["brand_moments"],
        "setup_payoffs": st["setup_payoffs"],
        "motifs": st.get("motifs", []),
        "constraints": st.get("constraints", []),
        "tone": st.get("tone") or None,
        "voice": st.get("voice"),
        # --- ADR-0012 运行时叙事状态层（缺省→空表，1.0 IR 无损迁移） ---
        "facts": st.get("facts", []),
        "threads": st.get("threads", []),
        "state_variables": st.get("state_variables", []),
        "dark_threads": st.get("dark_threads", []),
        "chapters": st["chapters"],
        "provenance": [p.model_dump() for p in provenance],
    }
    return NarrativeIR.model_validate(_strip_private(raw))


def _strip_private(raw: Any) -> Any:
    if isinstance(raw, dict):
        return {k: _strip_private(v) for k, v in raw.items() if not k.startswith("_")}
    if isinstance(raw, list):
        return [_strip_private(x) for x in raw]
    return raw


def _provenance(ctx: PassContext, run_ids: list[str]) -> list[Provenance]:
    rows = {r["run_id"]: r for r in ctx.store.runs()}
    cols = set(Provenance.model_fields)
    return [
        Provenance.model_validate({k: v for k, v in rows[r].items() if k in cols})
        for r in dict.fromkeys(run_ids)
        if r in rows
    ]


def _voice(ctx: PassContext, bible: dict[str, Any]) -> dict[str, Any]:
    v = {
        "person": "third_limited",
        "tense": "past",
        "style": "web_novel",
        "paragraph_max_chars": 180,
        "interiority": "medium",
        **ctx.profile.get("novel", {}).get("default_voice", {}),
    }
    pro = next((c for c in bible.get("characters", []) if c.get("role") == "protagonist"), None)
    v["pov_character_id"] = pro["id"] if pro else None
    return v


def _episode_digest(raw: dict[str, Any], ep_id: str) -> str:
    scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep_id}
    return "；".join(b["summary"] for b in raw["beats"] if b["parent_id"] in scene_ids)


# --- SW-05 / ADR-0017：p3 fragment 组成的 profile 旋钮（context.* 段，缺省 = 原行为） ---

#: known_facts 投影字段全集（值 = 缺省填充，机制映射，非业务规则）。
_KNOWN_FACT_FIELDS: dict[str, Any] = {
    "id": "",
    "content": "",
    "episode_no": 1,
    "status": "active",
    "type": "plot_event",
}


def _known_fact_fields_of(profile: dict[str, Any]) -> tuple[str, ...]:
    """profile.context.known_fact_fields → 投影字段（白名单交集，缺省 = 原五字段）。

    显式空列表是合法配置（投影面为空，即有意隐藏全部字段），不与"未配置"混同。
    """
    raw = profile.get("context", {}).get("known_fact_fields")
    wanted = list(_KNOWN_FACT_FIELDS) if raw is None else raw
    return tuple(k for k in _KNOWN_FACT_FIELDS if k in wanted)


def _known_facts(
    facts: list[dict[str, Any]], fields: tuple[str, ...] = tuple(_KNOWN_FACT_FIELDS)
) -> list[dict[str, Any]]:
    """p3 的跨集回收上下文（ADR-0012）：已成立 Fact 的最小可见面，供模型引用 id 做回收。

    SW-05：投影字段由 profile.context.known_fact_fields 决定（缺省 = 原五字段）。
    """
    return [
        {k: f.get(k, default) for k, default in _KNOWN_FACT_FIELDS.items() if k in fields}
        for f in facts
        if isinstance(f, dict)
    ]


def _window_join(summaries: list[str], window: int) -> str:
    """prev_episode_summary 窗口（SW-05）：按时间序拼接（远端在前、近端在后）。

    与 compress_history 的【前情】→【上一集】布局一致（review 澄清：chronological）。
    window=1 与原行为逐字节一致（单元素直接返回）；window=0 即恒空串。
    """
    n = max(0, int(window))
    return "\n".join(summaries[-n:]) if n else ""


def _threads_view(threads: list[Any]) -> str:
    """Thread 注入面（SW-05）：p2 规划的叙事线索标题/状态，供 p3 做跨集呼应。"""
    view = [
        {
            "id": t.get("id", ""),
            "title": t.get("title", ""),
            "status": t.get("status", "active"),
            "state": t.get("state", ""),
        }
        for t in threads
        if isinstance(t, dict)
    ]
    return json.dumps(view, ensure_ascii=False)


def _declared_state(st: dict[str, Any]) -> dict[str, Any]:
    """p3 的状态变更声明域（ADR-0012）：只允许对已声明的 StateVariable/DarkThread key 变更。"""
    return {
        "state_variables": [
            {"key": v["key"], "type": v.get("type", "number")}
            for v in st.get("state_variables", [])
            if isinstance(v, dict)
        ],
        "dark_threads": [
            {"key": d["key"]} for d in st.get("dark_threads", []) if isinstance(d, dict)
        ],
    }


def _placement_of(raw: dict[str, Any], ep: dict[str, Any]) -> list[dict[str, Any]]:
    """从已有 IR 反推该集的植入预算（重编译时 p2 不重跑，budget 真相在 IR 里）。"""
    scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep["id"]}
    beat_ids = {b["id"] for b in raw["beats"] if b["parent_id"] in scene_ids}
    return [
        {
            "episode_no": ep["no"],
            "selling_point_id": bm["selling_point_id"],
            "type": bm["type"],
            "intensity": bm["intensity"],
            "modality": bm["modality"],
            "plot_connection": bm["plot_connection"],
            "proof_mode": bm["proof_mode"],
            "intent": bm["integration_note"],
            "prop_id": bm.get("prop_id"),
        }
        for bm in raw.get("brand_moments", [])
        if bm["anchor_beat_id"] in beat_ids
    ]


def _ep_query(ep: dict[str, Any]) -> str:
    """p3_beatsheet 的检索查询：本集标题 + logline + hook_promise。"""
    return " ".join(
        x
        for x in (
            str(ep.get("title", "")),
            str(ep.get("logline", "")),
            str(ep.get("hook_promise", "")),
        )
        if x
    )


def _scene_query(scene: dict[str, Any], beats: list[dict[str, Any]]) -> str:
    """p5_dialogue 的检索查询：场景摘要 + 各 Beat 摘要。"""
    parts = [str(scene.get("summary", ""))]
    parts += [str(b.get("summary", "")) for b in beats]
    return "；".join(p for p in parts if p)


def _p5_fragment(
    scene: dict[str, Any],
    beats: list[dict[str, Any]],
    bible: dict[str, Any],
    constraints: list[dict[str, Any]],
    brand: dict[str, Any] | None = None,
) -> dict[str, Any]:
    present = set(scene.get("present_character_ids", []))
    brand = brand or {}
    return {
        "scene": scene,
        "beats": beats,
        "characters": [c for c in bible.get("characters", []) if c.get("id") in present],
        "brand_constraints": constraints,
        # 必提台词/必现视觉（BM-007/BM-007b）进缓存键：需求变则产物必须重生成
        "must_include_lines": list(brand.get("must_include_lines", [])),
        "must_include_visuals": list(brand.get("must_include_visuals", [])),
    }


def _attach_lines(beats: list[dict[str, Any]], lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**b, "_lines": [ln for ln in lines if ln["parent_id"] == b["id"]]} for b in beats]


def _scenes_with_lines(
    scenes: list[dict[str, Any]], beats: list[dict[str, Any]], raw: dict[str, Any]
) -> list[dict[str, Any]]:
    locs = {loc["id"]: loc["name"] for loc in raw.get("locations", [])}
    chars = {c["id"]: c["name"] for c in raw.get("characters", [])}
    out = []
    for sc in scenes:
        sc_beats = [b for b in beats if b["parent_id"] == sc["id"]]
        out.append(
            {
                **sc,
                "location_name": locs.get(sc["location_id"], ""),
                "character_names": [chars.get(c, "") for c in sc["present_character_ids"]],
                "beats": [
                    {**b, "lines": b.get("_lines", [])}
                    for b in sorted(sc_beats, key=lambda x: x["order"])
                ],
            }
        )
    return out


def _p6_fragment(
    ir: NarrativeIR, bible: dict[str, Any], voice: dict[str, Any], ep_id: str
) -> dict[str, Any]:
    raw = ir.model_dump()
    ep = next(e for e in raw["episodes"] if e["id"] == ep_id)
    scenes = [s for s in raw["scenes"] if s["parent_id"] == ep_id]
    scene_ids = {s["id"] for s in scenes}
    beats = _attach_lines([b for b in raw["beats"] if b["parent_id"] in scene_ids], raw["lines"])
    return {
        "episode": ep,
        "beats": beats,
        "scenes_with_lines": _scenes_with_lines(scenes, beats, raw),
        "bible": _slim_bible_for_episode(bible, scenes),
        "voice": voice,
    }


def _slim_bible_for_episode(
    bible: dict[str, Any], scenes: list[dict[str, Any]]
) -> dict[str, Any]:
    """bible 的按集投影（round17 prompt 瘦身）：只留本集出场的角色与用到的地点，
    外加 tone/motifs；props 不进（台词文本已含全部实体信息，散文编织不查资产表）。"""
    char_ids = {c for sc in scenes for c in sc.get("present_character_ids", [])}
    loc_ids = {sc.get("location_id") for sc in scenes}
    out = {k: v for k, v in bible.items() if k in ("tone", "motifs")}
    out["characters"] = [c for c in bible.get("characters", []) if c.get("id") in char_ids]
    out["locations"] = [loc for loc in bible.get("locations", []) if loc.get("id") in loc_ids]
    return out


def _splice_episode(
    raw: dict[str, Any],
    ep_id: str,
    new_scenes: list[dict[str, Any]],
    new_beats: list[dict[str, Any]],
    new_lines: list[dict[str, Any]],
    new_bms: list[dict[str, Any]],
    new_sps: list[dict[str, Any]],
    *,
    new_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    old_scene_ids = {s["id"] for s in raw["scenes"] if s["parent_id"] == ep_id}
    old_beat_ids = {b["id"] for b in raw["beats"] if b["parent_id"] in old_scene_ids}
    out = dict(raw)
    out["scenes"] = [s for s in raw["scenes"] if s["id"] not in old_scene_ids] + new_scenes
    out["beats"] = [b for b in raw["beats"] if b["id"] not in old_beat_ids] + new_beats
    out["lines"] = [ln for ln in raw["lines"] if ln["parent_id"] not in old_beat_ids] + new_lines
    out["brand_moments"] = [
        bm for bm in raw.get("brand_moments", []) if bm["anchor_beat_id"] not in old_beat_ids
    ] + new_bms
    kept_sps = [
        sp
        for sp in raw.get("setup_payoffs", [])
        if sp["setup_beat_id"] not in old_beat_ids and sp["payoff_beat_id"] not in old_beat_ids
    ]
    out["setup_payoffs"] = kept_sps + p3_beatsheet.resolve_pending(new_sps)
    # ADR-0012：本集 facts 整体替换（p3 的声明粒度是集），其余集保留；级联在全季上重放
    if new_facts is not None:
        ep_no = next(e["no"] for e in raw["episodes"] if e["id"] == ep_id)
        kept_facts = [f for f in raw.get("facts", []) if f.get("episode_no") != ep_no]
        out["facts"] = p3_beatsheet.apply_fact_cascade(kept_facts + new_facts)
    out["chapters"] = [c for c in raw.get("chapters", []) if c["episode_id"] != ep_id]
    return out


def _restore_locked(old: NarrativeIR, merged: NarrativeIR) -> None:
    """locked 节点的 payload 逐字保留（dep_graph.locked_policy）。"""
    for table in ("episodes", "scenes", "beats", "lines"):
        locked = {n.id: n for n in getattr(old, table) if n.locked}
        if not locked:
            continue
        nodes = getattr(merged, table)
        for i, n in enumerate(nodes):
            if n.id in locked:
                nodes[i] = locked[n.id]


def _remap_overlays(new: NarrativeIR, merged: NarrativeIR) -> None:
    """merge_preserving_ids 改完主干 ID 后，parent 链接与覆盖层引用必须同步重映射。"""
    id_map: dict[str, str] = {}
    for table in ("episodes", "scenes", "beats", "lines"):
        for n_new, n_merged in zip(getattr(new, table), getattr(merged, table), strict=True):
            if n_new.id != n_merged.id:
                id_map[n_new.id] = n_merged.id
    if not id_map:
        return
    for table in ("seasons", "episodes", "scenes", "beats", "lines"):
        for n in getattr(merged, table):
            if n.parent_id in id_map:
                n.parent_id = id_map[n.parent_id]
    for bm in merged.brand_moments:
        if bm.anchor_beat_id in id_map:
            bm.anchor_beat_id = id_map[bm.anchor_beat_id]
    for sp in merged.setup_payoffs:
        if sp.setup_beat_id in id_map:
            sp.setup_beat_id = id_map[sp.setup_beat_id]
        if sp.payoff_beat_id in id_map:
            sp.payoff_beat_id = id_map[sp.payoff_beat_id]
    for ch in merged.chapters:
        if ch.episode_id in id_map:
            ch.episode_id = id_map[ch.episode_id]
        for am in ch.anchor_map:
            if am.get("beat_id") in id_map:
                am["beat_id"] = id_map[am["beat_id"]]
            am["line_ids"] = [id_map.get(x, x) for x in am.get("line_ids", [])]
