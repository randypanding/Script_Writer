"""IR 不变量测试。这是"代码可丢弃"的验收面（D21 第 2 条）：
重写 src/ 之后，用同一套测试跑通，即等价。所以本文件**不得** import src/nsc 的内部实现细节，
只能 import spec.ir 与公开入口。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from spec.ir.container import NarrativeIR
from spec.ir.invariants import ALL_INVARIANTS, check_all


def test_all_invariants_have_implementation():
    """19+1 条不变量必须都有实现，不允许"文档写了代码没做"。"""
    import spec.ir.invariants as m

    missing = [
        i
        for i in ALL_INVARIANTS
        if not hasattr(m, f"inv_{i.split('-')[1]}") and i not in {"INV-01", "INV-10"}
    ]  # 这两条由 Pydantic 保证
    assert not missing, f"未实现的不变量：{missing}"


def test_golden_ir_passes_all(golden_ir, profiles):
    ir = NarrativeIR.model_validate(golden_ir)
    v = check_all(ir, profiles["short_drama_v1"], stage="final")
    assert v == [], f"黄金 IR 违反不变量：{v}"


@pytest.mark.parametrize(
    "inv",
    [
        "INV-03",
        "INV-05",
        "INV-06",
        "INV-07",
        "INV-08",
        "INV-12",
        "INV-15",
        "INV-17",
        "INV-18",
        "INV-19",
        "INV-20",
    ],
)
def test_each_invariant_catches_its_break(golden_ir, profiles, inv):
    """对每条不变量，必须有一个"破坏它"的 fixture 并被抓到。
    fixture 放 tests/fixtures/broken/<INV-ID>.json。缺失 = 测试失败。"""
    import json
    from pathlib import Path

    p = Path(f"tests/fixtures/broken/{inv}.json")
    assert p.exists(), f"缺少破坏 {inv} 的 fixture：{p}"
    ir = NarrativeIR.model_validate(json.loads(p.read_text("utf-8")))
    v = check_all(ir, profiles["short_drama_v1"], stage="final")
    assert any(x.inv_id == inv for x in v), f"{inv} 未被抓到"


def test_id_stability(golden_ir):
    """INV-16：局部重编译必须保留未变节点的 ID。

    这是**最高优先级测试**。违反它 = 所有历史反馈失效 = 资产系统性损毁。
    做法：把黄金 IR 全部节点换成新 ULID（模拟"重新生成"），只改一句台词，
    merge_preserving_ids 之后，除那句台词外所有节点必须恢复原 ID。
    """
    import copy

    from ulid import ULID

    from nsc.runtime.ir_io import merge_preserving_ids
    from spec.ir.invariants import inv_16_id_stability

    old = NarrativeIR.model_validate(golden_ir)
    new_raw = copy.deepcopy(golden_ir)

    # 改第 3 集的一句台词内容，其余内容逐字保留
    changed = new_raw["lines"][40]
    changed["text"] = changed["text"] + "（改）"
    changed_id_old = changed["id"]

    # 打乱全部节点 ID（包括 parent 链接一起换），模拟一次全新生成
    id_map: dict[str, str] = {}

    def remap(node_id: str | None) -> str | None:
        if node_id is None:
            return None
        if node_id not in id_map:
            id_map[node_id] = str(ULID())
        return id_map[node_id]

    for table in ("project",):
        new_raw[table]["id"] = remap(new_raw[table]["id"])
    for table in ("seasons", "episodes", "scenes", "beats", "lines"):
        for n in new_raw[table]:
            n["id"] = remap(n["id"])
            n["parent_id"] = remap(n["parent_id"])
    new = NarrativeIR.model_validate(new_raw)
    assert inv_16_id_stability(old, new)  # 未合并前必然违规

    merged = merge_preserving_ids(old, new)
    violations = inv_16_id_stability(old, merged)
    assert violations == [], f"INV-16 被违反：{[v.message for v in violations][:3]}"
    # 被改的那句台词允许拿到新 ID，但其 parent 等未变节点 ID 必须已恢复
    merged_line = next(ln for ln in merged.lines if ln.text.endswith("（改）"))
    assert merged_line.id != changed_id_old or merged_line.id == id_map[changed_id_old]


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=12))
def test_order_is_contiguous_property(n):
    """property-based：任意合法构造出的 IR，同 parent 下 order 必须 0..n-1 连续。"""
    from tests.strategies import build_minimal_ir

    ir = NarrativeIR.model_validate(build_minimal_ir(n_episodes=n))
    violations = check_all(
        ir, {"layers": {"season": False}, "duration_tolerance": 0.5}, stage="final"
    )
    inv03 = [v for v in violations if v.inv_id == "INV-03"]
    assert inv03 == [], f"order 不连续：{[v.message for v in inv03][:3]}"


# ============================================================ ADR-0012 · IR 1.1
# INV-17..20（运行时叙事状态层）+ 派生纯函数 + 1.0→1.1 无损迁移。


@settings(max_examples=30, deadline=None)
@given(st.integers(min_value=1, max_value=12))
def test_narrative_state_invariants_hold_on_minimal_ir(n):
    """property-based：合法构造的叙事状态层（Fact/Thread/StateVar/DarkThread）
    必须同时通过 INV-17..20。"""
    from tests.strategies import build_minimal_ir

    ir = NarrativeIR.model_validate(build_minimal_ir(n_episodes=n))
    violations = check_all(
        ir, {"layers": {"season": False}, "duration_tolerance": 0.5}, stage="final"
    )
    bad = [v for v in violations if v.inv_id in {"INV-17", "INV-18", "INV-19", "INV-20"}]
    assert bad == [], f"叙事状态不变量被违反：{[v.message for v in bad][:3]}"


def _minimal_ir(n_episodes: int = 2):
    from tests.strategies import build_minimal_ir

    return build_minimal_ir(n_episodes=n_episodes)


def test_inv17_resolves_reference_and_cascade():
    """INV-17 双向：悬空 resolves / 自指 / resolved 无回收者 / 有回收者但未级联。"""
    import copy

    import spec.ir.invariants as inv

    ir = NarrativeIR.model_validate(_minimal_ir())
    assert inv.inv_17(ir) == []

    # 悬空引用（连带让 fact_a 失去回收者，两条都归 INV-17）
    raw = copy.deepcopy(_minimal_ir())
    raw["facts"][1]["resolves"] = "0" * 26  # ULID 形合法但必不存在
    v = inv.inv_17(NarrativeIR.model_validate(raw))
    assert {x.inv_id for x in v} == {"INV-17"}
    assert any("指向不存在的 Fact" in x.message for x in v)

    # 自指（连带让 fact_a 失去回收者，故应有两条，都归 INV-17）
    raw = copy.deepcopy(_minimal_ir())
    raw["facts"][1]["resolves"] = raw["facts"][1]["id"]
    v = inv.inv_17(NarrativeIR.model_validate(raw))
    assert {x.inv_id for x in v} == {"INV-17"}
    assert any("指向自身" in x.message for x in v)

    # resolved 但无回收者（删掉回收方）
    raw = copy.deepcopy(_minimal_ir())
    raw["facts"] = raw["facts"][:1]
    v = inv.inv_17(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-17"] and "没有任何非 deprecated" in v[0].message

    # 有回收者但目标未级联为 resolved
    raw = copy.deepcopy(_minimal_ir())
    raw["facts"][0]["status"] = "unresolved"
    v = inv.inv_17(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-17"] and "仍为" in v[0].message


def test_inv18_caused_by_existence_and_temporal_order():
    """INV-18：caused_by 引用存在 + 成因不晚于结果。"""
    import copy

    import spec.ir.invariants as inv

    ir = NarrativeIR.model_validate(_minimal_ir())
    assert inv.inv_18(ir) == []

    # 成因晚于结果（因果倒置）
    raw = copy.deepcopy(_minimal_ir())
    raw["facts"][0]["episode_no"] = 3  # fact_b(ep2).caused_by=[fact_a(ep3)]
    v = inv.inv_18(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-18"] and "晚于结果" in v[0].message

    # 悬空引用
    raw = copy.deepcopy(_minimal_ir())
    raw["facts"][1]["caused_by"] = ["0" * 26]
    v = inv.inv_18(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-18"] and "不存在" in v[0].message


def test_inv19_stage_bounds_and_numeric_delta():
    """INV-19：暗线阶段界内 + number 型 delta 必须数值型。"""
    import copy

    import spec.ir.invariants as inv

    ir = NarrativeIR.model_validate(_minimal_ir(3))
    assert inv.inv_19(ir) == []

    # 阶段越界：3 段暗线累计推 3 步
    raw = copy.deepcopy(_minimal_ir(3))
    raw["episodes"][1]["state_changes"].append(
        {"key": "sugar_free_truth", "delta": 1, "reason": "多推一步"}
    )
    v = inv.inv_19(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-19"] and "current_stage=3" in v[0].message

    # 负向越界：第 1 集回退 2 步，末集 +1 抵消后仍为 -1
    raw = copy.deepcopy(_minimal_ir(3))
    raw["episodes"][0]["state_changes"] = [
        {"key": "sugar_free_truth", "delta": -2, "reason": "回退"}
    ]
    v = inv.inv_19(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-19"] and "current_stage=-1" in v[0].message

    # number 型变量收到字符串 delta
    raw = copy.deepcopy(_minimal_ir(2))
    raw["episodes"][0]["state_changes"].append(
        {"key": "trust_level", "delta": "涨了一点点", "reason": "手滑"}
    )
    v = inv.inv_19(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-19"] and "delta 必须是 int/float" in v[0].message


def test_inv20_responds_to_backreference():
    """INV-20：responds_to 必须指向存在且更早的集。"""
    import copy

    import spec.ir.invariants as inv

    ir = NarrativeIR.model_validate(_minimal_ir(3))
    assert inv.inv_20(ir) == []

    raw = copy.deepcopy(_minimal_ir(3))
    raw["episodes"][1]["responds_to"] = [2]  # 自指（2 不 < 2）
    v = inv.inv_20(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-20"] and "严格小于" in v[0].message

    raw = copy.deepcopy(_minimal_ir(3))
    raw["episodes"][1]["responds_to"] = [9]  # 不存在的集号
    v = inv.inv_20(NarrativeIR.model_validate(raw))
    assert [x.inv_id for x in v] == ["INV-20"] and "不存在的集号" in v[0].message


def test_derive_state_and_stage_replay():
    """derive_state / derive_stage：确定性重放（number 累加 / string 覆盖 / 暗线步进）。"""
    import copy

    from nsc.runtime.ir_io import derive_stage, derive_state

    raw = _minimal_ir(3)
    assert derive_state(raw)["trust_level"] == 3
    assert derive_stage(raw, "sugar_free_truth") == 2

    # string 型：后面的声明覆盖前面的
    raw = copy.deepcopy(raw)
    raw["state_variables"].append(
        {"key": "mood", "name": "心情", "type": "string", "initial": "平静"}
    )
    raw["episodes"][0]["state_changes"].append({"key": "mood", "delta": "炸毛", "reason": "被催"})
    raw["episodes"][1]["state_changes"].append({"key": "mood", "delta": "缓和", "reason": "和解"})
    derived = derive_state(raw)
    assert derived["mood"] == "缓和"
    assert derived["trust_level"] == 3
    assert derive_stage(raw, "sugar_free_truth") == 2


def test_build_view_narrative_state_derivations(profiles, demo_brand):
    """build_view：四张新表 + is_overdue/current/current_stage 派生 + 新字段透传。"""
    import copy

    from nsc.runtime.ir_io import build_view

    profile = profiles["short_drama_v1"]
    raw = _minimal_ir(6)
    view = build_view(raw, profile, demo_brand)
    assert view["state_variables"][0]["current"] == 6
    assert view["dark_threads"][0]["current_stage"] == 2
    foreshadow = next(f for f in view["facts"] if f["type"] == "foreshadowing")
    assert foreshadow["is_overdue"] is False  # 已 resolved，不逾期
    assert view["threads"][0]["title"]

    # unresolved 且距今 >3 集 → 逾期
    raw = copy.deepcopy(raw)
    raw["facts"][0]["status"] = "unresolved"
    view2 = build_view(raw, profile, demo_brand)
    f = next(x for x in view2["facts"] if x["episode_no"] == 1)
    assert f["is_overdue"] is True  # 6 - 1 = 5 > 3

    # Scene/Episode/Character 新字段透传
    sc = view2["episodes"][0]["scenes"][0]
    assert sc["opening_attractor"] == "体检报告特写：空腹血糖临界"
    assert sc["escalation_beats"] == ["签字催促", "两种说法对质"]
    assert sc["ending_hook"] == "报告背面还有一行字"
    assert sc["knowledge_state"]["hidden"] == "陈经理改过备注"
    assert view2["episodes"][0]["responds_to"] == []
    assert view2["episodes"][1]["responds_to"] == [1]
    assert any(c["key"] == "trust_level" for c in view2["episodes"][0]["state_changes"])
    ch0 = view2["characters"][0]
    assert ch0["mental_models"][0]["name"] == "热量守恒"
    assert ch0["decision_heuristics"] == ["先看配料表再开口"]
    assert ch0["expression_dna"]["syntax"] == "短句"


def test_migration_1_0_ir_is_lossless(golden_ir, profiles, demo_brand, tmp_path):
    """ADR-0012 迁移：1.0 黄金 IR → load 后为 1.1，且全规则检查结果逐条一致。"""
    import json
    from pathlib import Path

    import yaml

    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.runtime.ir_io import build_view, load

    assert golden_ir["schema_version"] == "1.0"  # 黄金 fixture 保持 1.0 原貌
    profile = profiles["short_drama_v1"]

    # 防御式加载规则：spec/checks 由并行工单频繁改写，个别文件可能瞬时不可解析。
    # 迁移等价性只要求前后用**同一**规则集，跳过不可解析者不损结论。
    domains = set(profile.get("enabled_check_domains", []))
    rules = []
    for p in sorted(Path("spec/checks").rglob("*.yaml")):
        if p.name.startswith("_"):
            continue
        try:
            docs = [d for d in yaml.safe_load_all(p.read_text("utf-8")) if isinstance(d, dict)]
        except yaml.YAMLError:
            continue
        for r in docs:
            if r.get("id") and r.get("status", "active") == "active" and r.get("domain") in domains:
                rules.append(r)
    assert rules, "spec/checks 下无可加载规则，迁移等价测试失去对象"
    rs = RuleSet(Path("spec/checks"))
    rs.rules = sorted(rules, key=lambda r: r["id"])

    def run_check(ir_dict):
        view = build_view(ir_dict, profile, demo_brand)
        rep = evaluate(rs, view, ctx={"profile": profile, "brand": demo_brand})
        assert rep.errors == [], f"规则本身报错：{rep.errors[:3]}"
        return sorted((f.rule_id, f.severity, f.node_id or "", f.message) for f in rep.findings)

    before = run_check(golden_ir)

    # load()：显式迁移 1.0→1.1；model_validate：校验入口同样自动迁移
    p = tmp_path / "golden_1_0.json"
    p.write_text(json.dumps(golden_ir, ensure_ascii=False), "utf-8")
    ir = load(p)
    assert ir.schema_version == "1.1"
    assert NarrativeIR.model_validate(golden_ir).schema_version == "1.1"

    after = run_check(ir.model_dump())
    assert after == before, "迁移改变了检查结果——违反 ADR-0012 无损迁移承诺"
