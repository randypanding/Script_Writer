"""IR 不变量的可执行形态。纯函数，无 IO，无 LLM。

约定：每个 inv_* 返回 list[Violation]（空 = 通过）。
这些是 L0 的一部分，但与 spec/checks/*.yaml 的区别是：
  - invariants.py = **结构完整性**（IR 本身是否是合法的图），与 Profile 无关或仅弱相关
  - spec/checks/*.yaml = **叙事/品牌/合规约束**（图合法但内容不合规）
新增业务约束一律去 spec/checks/，不要往这里加。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .container import NarrativeIR


@dataclass(frozen=True, slots=True)
class Violation:
    inv_id: str
    node_id: str | None
    message: str  # 必须是可直接喂给 GEPA 的诊断句，见 spec/checks/DSL.md §5
    severity: str = "block"


ALL_INVARIANTS: tuple[str, ...] = tuple(f"INV-{i:02d}" for i in range(1, 17))

#: 由 Pydantic 字段约束保证（正则在 ULID，bounds 在 Emotion），无需函数实现。
_SCHEMA_GUARANTEED = {"INV-01", "INV-10"}

#: 成对不变量：需要 old+new 两份 IR，单 IR 的 check_all 跳过（ADR-0007）。
#: 执法点在 merge_preserving_ids 的调用方与 test_recompile / test_id_stability。
_PAIRWISE = {"INV-16"}

#: stage → 应执行的不变量（来自 dep_graph.yaml::invariant_stages）
_INVARIANT_STAGES: dict[str, set[str]] = {
    "after_p1": {"INV-01", "INV-09", "INV-10"},
    "after_p2": {"INV-01", "INV-02", "INV-03", "INV-04", "INV-12", "INV-13"},
    "after_p3": {
        "INV-01",
        "INV-02",
        "INV-03",
        "INV-04",
        "INV-05",
        "INV-06",
        "INV-08",
        "INV-10",
        "INV-15",
    },
    "after_p4": {"INV-01", "INV-02", "INV-03", "INV-04", "INV-11"},
    "after_p5": {"INV-01", "INV-02", "INV-03", "INV-07", "INV-11"},
    "after_p6": {"INV-01", "INV-14"},
    "final": set(ALL_INVARIANTS),
}


def _all_nodes(ir: NarrativeIR) -> list[Any]:
    """收集所有带 id/parent_id/order 的节点（主干层级）。"""
    nodes = [ir.project]
    nodes += ir.seasons + ir.episodes + ir.scenes + ir.beats + ir.lines
    return nodes


def _by_id(ir: NarrativeIR) -> dict[str, Any]:
    return {n.id: n for n in _all_nodes(ir)}


def _linear_index(ir: NarrativeIR) -> dict[str, int]:
    """构造 linear_index 映射：按 episode->scene->beat->line 深度优先连续编号。"""
    idx: dict[str, int] = {}
    counter = 0
    for ep in ir.episodes:
        for sc in (s for s in ir.scenes if s.parent_id == ep.id):
            for bt in (b for b in ir.beats if b.parent_id == sc.id):
                idx[bt.id] = counter
                counter += 1
                for ln in (ln for ln in ir.lines if ln.parent_id == bt.id):
                    idx[ln.id] = counter
                    counter += 1
    return idx


def check_all(ir: NarrativeIR, profile: dict, stage: str = "final") -> list[Violation]:
    """stage ∈ {after_p1..after_p6, final}。早期 stage 跳过尚不适用的不变量。"""
    enabled = _INVARIANT_STAGES.get(stage, set(ALL_INVARIANTS))
    v: list[Violation] = []
    implementable = [i for i in enabled if i not in _SCHEMA_GUARANTEED and i not in _PAIRWISE]
    for inv_id in implementable:
        fn_name = f"inv_{inv_id.split('-')[1]}"
        fn = globals().get(fn_name)
        if fn is None:
            continue  # T-02 的 test_all_invariants_have_implementation 会兜底
        if inv_id in {"INV-09", "INV-13", "INV-15"}:
            # 需要在 ir 之外注入 brand/profile 的，用 profile 近似（profile 含必要数值）
            v.extend(fn(ir, profile))
        else:
            v.extend(fn(ir))
    return sorted(v, key=lambda x: (x.inv_id, x.node_id or ""))


def inv_02(ir: NarrativeIR) -> list[Violation]:
    by_id = _by_id(ir)
    from .nodes import HIERARCHY

    out: list[Violation] = []
    for n in _all_nodes(ir):
        if n.parent_id is None:
            continue
        parent = by_id.get(n.parent_id)
        if parent is None:
            out.append(
                Violation(
                    "INV-02",
                    n.id,
                    f"节点 {n.id}({n.kind}) 的 parent_id={n.parent_id} 不存在。请修正父子链接。",
                )
            )
        elif HIERARCHY.get(n.kind) != parent.kind:
            out.append(
                Violation(
                    "INV-02",
                    n.id,
                    f"节点 {n.id}({n.kind}) 的 parent 是 {parent.kind}，但合法父 kind 应为 {HIERARCHY.get(n.kind)}。请修正。",
                )
            )
    return out


def inv_03(ir: NarrativeIR) -> list[Violation]:
    from collections import defaultdict

    groups: dict[str, list[Any]] = defaultdict(list)
    for n in _all_nodes(ir):
        groups[n.parent_id or "ROOT"].append(n)
    out: list[Violation] = []
    for pid, children in groups.items():
        expected = list(range(len(children)))
        actual = [ch.order for ch in children]
        if sorted(actual) != expected:
            bad = [ch for ch in children if ch.order not in expected]
            out.append(
                Violation(
                    "INV-03",
                    pid,
                    f"parent {pid} 下有 {len(children)} 个节点，其 order 应为 0..{len(children) - 1} 连续，"
                    f"实际含 {[b.id for b in bad]}。请重排 order 使其连续。",
                )
            )
    return out


def inv_04(ir: NarrativeIR) -> list[Violation]:
    by_id = _by_id(ir)
    out: list[Violation] = []
    for n in _all_nodes(ir):
        seen: set[str] = set()
        cur: Any = n
        while cur.parent_id is not None:
            if cur.id in seen:
                out.append(
                    Violation(
                        "INV-04", n.id, f"parent 链在 {cur.id} 处成环。请切断环路使树可达 Project。"
                    )
                )
                seen.clear()
                break
            seen.add(cur.id)
            cur = by_id.get(cur.parent_id)
            if cur is None:
                out.append(
                    Violation(
                        "INV-04",
                        n.id,
                        f"从 {n.id} 向上的 parent 链在某处断裂（parent_id 不存在）。无法到达 Project。",
                    )
                )
                break
    return out


def _episode_beats(ir: NarrativeIR, ep: Any) -> list[Any]:
    """某集的所有 Beat（Beat 挂在 Scene 下，需经 Scene 中转）。"""
    scene_ids = {s.id for s in ir.scenes if s.parent_id == ep.id}
    return [b for b in ir.beats if b.parent_id in scene_ids]


def inv_05(ir: NarrativeIR) -> list[Violation]:
    out: list[Violation] = []
    for ep in ir.episodes:
        hooks = [b for b in _episode_beats(ir, ep) if b.beat_kind == "hook"]
        if len(hooks) != 1:
            out.append(
                Violation(
                    "INV-05",
                    ep.id,
                    f"第 {ep.no} 集有 {len(hooks)} 个 hook Beat（必须恰好 1 个）。请合并或调整。",
                )
            )
    return out


def inv_06(ir: NarrativeIR) -> list[Violation]:
    out: list[Violation] = []
    bm_by_beat: dict[str, list[Any]] = {}
    for bm in ir.brand_moments:
        bm_by_beat.setdefault(bm.anchor_beat_id, []).append(bm)
    for b in ir.beats:
        if b.beat_kind == "brand_moment":
            if b.brand_moment_id is None:
                out.append(
                    Violation(
                        "INV-06",
                        b.id,
                        f"Beat {b.id} 是 brand_moment 但 brand_moment_id 为空。请关联一个 BrandMoment。",
                    )
                )
            elif b.id not in bm_by_beat:
                out.append(
                    Violation(
                        "INV-06",
                        b.id,
                        f"Beat {b.id} 声明 brand_moment_id={b.brand_moment_id}，但没有任何 BrandMoment.anchor_beat_id 指向它。请反向一致。",
                    )
                )
            elif len(bm_by_beat[b.id]) > 1:
                out.append(
                    Violation(
                        "INV-06",
                        b.id,
                        f"Beat {b.id} 被 {len(bm_by_beat[b.id])} 个 BrandMoment 锚定（至多 1 个）。请合并。",
                    )
                )
        else:
            if b.brand_moment_id is not None:
                out.append(
                    Violation(
                        "INV-06",
                        b.id,
                        f"Beat {b.id} 的 beat_kind={b.beat_kind} 但携带 brand_moment_id。非 brand_moment Beat 不得携带。",
                    )
                )
    return out


def inv_07(ir: NarrativeIR) -> list[Violation]:
    scene_by_id = {s.id: s for s in ir.scenes}
    beat_by_id = {b.id: b for b in ir.beats}
    out: list[Violation] = []
    for ln in ir.lines:
        if ln.line_type in {"dialogue", "voiceover"} and ln.character_id is None:
            out.append(
                Violation(
                    "INV-07",
                    ln.id,
                    f"Line {ln.id} 是 {ln.line_type} 但 character_id 为空。说话人必填。",
                )
            )
            continue
        if ln.character_id is None:
            continue
        if ln.parent_id is None:
            continue
        beat = beat_by_id.get(ln.parent_id)
        if beat is None:
            continue
        if beat.parent_id is None:
            continue
        scene = scene_by_id.get(beat.parent_id)
        if scene is not None and ln.character_id not in scene.present_character_ids:
            out.append(
                Violation(
                    "INV-07",
                    ln.id,
                    f"Line {ln.id} 的说话人 {ln.character_id} 不在所属场景的在场角色列表。请修正。",
                )
            )
    return out


def inv_08(ir: NarrativeIR) -> list[Violation]:
    idx = _linear_index(ir)
    out: list[Violation] = []
    for sp in ir.setup_payoffs:
        s = idx.get(sp.setup_beat_id)
        p = idx.get(sp.payoff_beat_id)
        if s is None or p is None:
            out.append(
                Violation(
                    "INV-08",
                    sp.id,
                    f"伏笔 {sp.id} 的 setup/payoff Beat 缺失于主干。请确认两端 Beat 存在。",
                )
            )
        elif s >= p:
            out.append(
                Violation(
                    "INV-08",
                    sp.id,
                    f"伏笔 {sp.id} 的 payoff 位置({p})不晚于 setup 位置({s})。请交换。",
                )
            )
    return out


def inv_09(ir: NarrativeIR, _brand: dict) -> list[Violation]:
    ids = (
        set(_by_id(ir))
        | {c.id for c in ir.characters}
        | {loc.id for loc in ir.locations}
        | {p.id for p in ir.props}
        | {b.id for b in ir.brand_moments}
    )
    out: list[Violation] = []
    for sc in ir.scenes:
        if sc.location_id not in ids:
            out.append(
                Violation(
                    "INV-09",
                    sc.id,
                    f"场景 {sc.id} 的 location_id={sc.location_id} 不存在。请修正。",
                )
            )
        for cid in sc.present_character_ids:
            if cid not in ids:
                out.append(
                    Violation("INV-09", sc.id, f"场景 {sc.id} 引用了不存在的角色 {cid}。请修正。")
                )
    for bm in ir.brand_moments:
        if bm.prop_id and bm.prop_id not in ids:
            out.append(
                Violation(
                    "INV-09", bm.id, f"植入 {bm.id} 引用了不存在的道具 {bm.prop_id}。请修正。"
                )
            )
    return out


def inv_11(ir: NarrativeIR) -> list[Violation]:
    out: list[Violation] = []
    for ep in ir.episodes:
        scenes = [s for s in ir.scenes if s.parent_id == ep.id]
        if not scenes:
            out.append(
                Violation("INV-11", ep.id, f"第 {ep.no} 集没有任何场景。每集至少 1 个场景。")
            )
    for sc in ir.scenes:
        beats = [b for b in ir.beats if b.parent_id == sc.id]
        if not beats:
            out.append(
                Violation("INV-11", sc.id, f"场景 {sc.id} 没有任何 Beat。每场景至少 1 个 Beat。")
            )
        for b in beats:
            lines = [ln for ln in ir.lines if ln.parent_id == b.id]
            if not lines:
                out.append(
                    Violation(
                        "INV-11",
                        b.id,
                        f"Beat {b.id}（{b.beat_kind}）没有任何 Line。每个 Beat 至少 1 条 Line。",
                    )
                )
    return out


def inv_12(ir: NarrativeIR) -> list[Violation]:
    out: list[Violation] = []
    for ep in ir.episodes:
        if ep.no != ep.order + 1:
            out.append(
                Violation(
                    "INV-12",
                    ep.id,
                    f"第 {ep.no} 集 order={ep.order}，集号与 order 不同序（应为 order+1）。请修正。",
                )
            )
    return out


def inv_13(ir: NarrativeIR, profile: dict) -> list[Violation]:
    layers = profile.get("layers", {})
    if layers.get("season") is False:
        if len(ir.seasons) != 1:
            return [
                Violation(
                    "INV-13",
                    None,
                    "Profile 关闭 season 层，但 IR 有多个 Season。应只有 1 个占位 Season。",
                )
            ]
        if ir.seasons and ir.seasons[0].title:
            return [
                Violation(
                    "INV-13",
                    ir.seasons[0].id,
                    "Profile 关闭 season 层时 Season.title 应为空。请清空。",
                )
            ]
    return []


def inv_14(ir: NarrativeIR) -> list[Violation]:
    run_ids = {p.run_id for p in ir.provenance}
    out: list[Violation] = []
    for n in _all_nodes(ir):
        if n.provenance_id not in run_ids:
            out.append(
                Violation(
                    "INV-14",
                    n.id,
                    f"节点 {n.id} 的 provenance_id={n.provenance_id} 不在 provenance 清单中。请补齐运行记录。",
                )
            )
    for ch in ir.chapters:
        if ch.provenance_id not in run_ids:
            out.append(
                Violation(
                    "INV-14",
                    ch.id,
                    f"章节 {ch.id} 的 provenance_id={ch.provenance_id} 不在清单中。请补齐。",
                )
            )
    return out


def inv_15(ir: NarrativeIR, profile: dict) -> list[Violation]:
    tol = profile.get("duration_tolerance", 0.15)
    out: list[Violation] = []
    for ep in ir.episodes:
        total = sum(b.est_duration_s for b in _episode_beats(ir, ep))
        lo = ep.duration_target_s * (1 - tol)
        hi = ep.duration_target_s * (1 + tol)
        if not (lo <= total <= hi):
            out.append(
                Violation(
                    "INV-15",
                    ep.id,
                    f"第 {ep.no} 集 Beat 时长合计 {total:.1f}s，目标 {ep.duration_target_s}s（±{tol:.0%}）。请调整 Beat 时长。",
                )
            )
    return out


def inv_16_id_stability(old: NarrativeIR, new: NarrativeIR) -> list[Violation]:
    """INV-16：局部重编译必须保留未变节点的 ID。

    判定：old 中 text/summary 未变的节点，其 ID 必须与 old 一致。
    """
    out: list[Violation] = []

    # 按内容指纹匹配：未变节点 = 在 new 中存在 render 关键字段相同的节点
    def sig(n: Any) -> str:
        for att in ("text", "summary", "title", "logline"):
            if hasattr(n, att) and getattr(n, att):
                return f"{att}:{getattr(n, att)}"
        return f"{n.kind}:{n.id}"

    # 简化：old 中内容未变的节点在 new 中应能找到同内容节点且保留原 id
    new_sig_to_id: dict[str, str] = {}
    for n in _all_nodes(new):
        new_sig_to_id.setdefault(sig(n), n.id)
    for n in _all_nodes(old):
        s = sig(n)
        if s in new_sig_to_id:
            kept = new_sig_to_id[s]
            if kept != n.id:
                out.append(
                    Violation(
                        "INV-16",
                        n.id,
                        f"节点内容未变但 ID 从 {n.id} 变为 {kept}。局部重编译必须保留未变节点 ID（否则历史反馈失效）。",
                    )
                )
    return out


#: 命名别名：ALL_INVARIANTS 里的 INV-16 对应实现函数名（测试按 `inv_<nn>` 探测）。
inv_16 = inv_16_id_stability
