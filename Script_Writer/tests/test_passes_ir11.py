"""T-35/T-36 验收：IR 1.1 新节点（ADR-0012）接入 p1..p4 与 pipeline（全桩，无 LLM）。

覆盖两条路径：
  - 桩返回含新字段 → IR 1.1 四张表（facts/threads/state_variables/dark_threads）+
    Episode.responds_to/state_changes + Scene 节奏/知识状态字段 + Character 心智 OS
    正确填充，跨集 resolves 闭环且 INV-17..20 全绿；
  - 桩剥掉全部新输出字段（旧 prompt 形态）→ pipeline 照常产出 IR 1.1，新表默认空
    （Wave B 规则对缺失只出 warn/info，不拦截）。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from tests.test_pipeline_stub import FullStubRouter

KNOWN_ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
EP_ULID = "01BJZ3NDEKTSV4RRFFQ69G5FAV"


def _no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))


def _make_ctx(tmp_path, router):
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=router,
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


class IR11Router(FullStubRouter):
    """黄金桩 + IR 1.1 增量：p1 心智 OS / p2 responds_to 过滤样例 / p3 facts + 暗线步进。"""

    def _p1(self, inputs):
        payload = super()._p1(inputs)
        chars = json.loads(payload["characters_json"])
        chars[0]["mental_models"] = [
            {
                "name": "热量守恒",
                "description": "把快乐折算成热量负债",
                "trigger": "看到配料表",
                "action_tendency": "先放下再说",
                "failure_mode": "错过眼前这杯",
                "invented_field": "应被机械过滤",
            }
        ]
        chars[0]["decision_heuristics"] = ["先看配料表再开口"]
        chars[0]["honest_boundaries"] = ["不当面对小满说教"]
        chars[0]["expression_dna"] = {
            "syntax": "短句",
            "rhetoric": "反问",
            "emotion_temperature": "低温",
            "signature_lines": ["这杯茶，不额外加蔗糖。"],
        }
        payload["characters_json"] = json.dumps(chars, ensure_ascii=False)
        return payload

    def _p2(self, inputs):
        payload = super()._p2(inputs)
        eps = json.loads(payload["episodes_json"])
        for e in eps:
            if e["no"] >= 2:
                e["responds_to"] = [e["no"] - 1, 99]  # 99 越界，应被 INV-20 机械过滤丢弃
        payload["episodes_json"] = json.dumps(eps, ensure_ascii=False)
        return payload

    def _p3(self, inputs):
        payload = super()._p3(inputs)
        ep_no = json.loads(inputs["episode_json"])["no"]
        known = json.loads(inputs.get("known_facts", "[]"))
        facts = [
            {
                "content": f"第{ep_no}集：茶杯标签背面写着代糖来源",
                "type": "foreshadowing",
                "status": "unresolved",
                "resolves": None,
                "episode_no": ep_no,
                "narrative_weight": "high",
            }
        ]
        if ep_no == 1:
            facts.append(
                {
                    "content": "第1集：同集内标签当众被看清",
                    "type": "plot_event",
                    "status": "active",
                    "resolves": 0,  # 同集下标引用
                    "episode_no": ep_no,
                    "narrative_weight": "medium",
                }
            )
        elif known:
            facts.append(
                {
                    "content": f"第{ep_no}集：前集伏笔在此被回收",
                    "type": "plot_event",
                    "status": "active",
                    "resolves": known[0]["id"],  # 跨集 id 引用
                    "episode_no": ep_no,
                    "narrative_weight": "medium",
                }
            )
        payload["facts_json"] = json.dumps(facts, ensure_ascii=False)
        if ep_no in (1, 6):  # 暗线首末各推一步（3 段暗线，2 步界内）
            changes = json.loads(payload["state_changes_json"])
            changes.append({"key": "sugar_free_truth", "delta": 1, "reason": "暗线推进一步"})
            payload["state_changes_json"] = json.dumps(changes, ensure_ascii=False)
        return payload


class OmitIR11Router(FullStubRouter):
    """旧 prompt 形态：剥掉全部 IR 1.1 新输出字段 → 可缺省路径。"""

    def _p2(self, inputs):
        payload = super()._p2(inputs)
        for k in ("threads_json", "dark_threads_json", "state_variables_json"):
            payload.pop(k, None)
        eps = json.loads(payload["episodes_json"])
        for e in eps:
            e.pop("responds_to", None)
        payload["episodes_json"] = json.dumps(eps, ensure_ascii=False)
        return payload

    def _p3(self, inputs):
        payload = super()._p3(inputs)
        payload.pop("state_changes_json", None)
        return payload

    def _p4(self, inputs):
        payload = super()._p4(inputs)
        scenes = json.loads(payload["scenes_json"])
        for sc in scenes:
            for k in ("opening_attractor", "escalation_beats", "ending_hook", "knowledge_state"):
                sc.pop(k, None)
        payload["scenes_json"] = json.dumps(scenes, ensure_ascii=False)
        return payload


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    _no_cache(tmp_path, monkeypatch)
    return _make_ctx(tmp_path, IR11Router())


def test_run_pipeline_populates_ir11_tables(ctx):
    """含新字段的桩 → IR 1.1 四张表 + 集级声明 + 场级字段 + 心智 OS 全部落位，INV-17..20 绿。"""
    from nsc.passes.pipeline import run_pipeline
    from nsc.runtime.ir_io import build_view, derive_stage, derive_state
    from spec.ir.invariants import check_all

    ir = run_pipeline(ctx)

    # p2 三张表 + Episode.responds_to（越界集号 99 被 INV-20 机械过滤）
    assert [t.title for t in ir.threads] == ["无糖真相"]
    assert [v.key for v in ir.state_variables] == ["trust_level"]
    assert [d.key for d in ir.dark_threads] == ["sugar_free_truth"]
    assert ir.episodes[0].responds_to == []
    assert ir.episodes[1].responds_to == [1]

    # p3 facts：每集 2 条（本集伏笔 + 回收条，回收指向第 1 集伏笔或同集下标），级联翻 resolved
    assert len(ir.facts) == 12
    foreshadow = next(f for f in ir.facts if f.type == "foreshadowing")
    assert foreshadow.status == "resolved"
    same_ep = next(f for f in ir.facts if f.content.startswith("第1集：同集"))
    assert same_ep.resolves == foreshadow.id
    cross = next(f for f in ir.facts if f.content.startswith("第2集：前集"))
    assert cross.resolves == foreshadow.id

    # p3 Episode.state_changes 落到对应集
    assert {c.key for c in ir.episodes[0].state_changes} == {"trust_level", "sugar_free_truth"}
    assert [c.key for c in ir.episodes[1].state_changes] == ["trust_level"]

    # p4 Scene 节奏与知识状态
    sc = ir.scenes[0]
    assert sc.opening_attractor == "特写：体检报告上的空腹血糖读数"
    assert sc.escalation_beats == ["签字催促", "两种说法对质"]
    assert sc.knowledge_state is not None and sc.knowledge_state.hidden == "陈经理改过备注"

    # p1 心智 OS（嵌套 extra 键被机械过滤后仍通过 extra="forbid" 校验）
    ch = ir.characters[0]
    assert ch.mental_models[0].name == "热量守恒"
    assert ch.decision_heuristics == ["先看配料表再开口"]
    assert ch.honest_boundaries == ["不当面对小满说教"]
    assert ch.expression_dna is not None and ch.expression_dna.syntax == "短句"

    # INV-17..20 在 pipeline final 已跑过，这里显式复核
    assert check_all(ir, ctx.profile, stage="final") == []

    # 派生量：信任度重放 6 集 = 6；暗线 2 步（首末集各 +1），界内
    raw = ir.model_dump()
    assert derive_state(raw)["trust_level"] == 6
    assert derive_stage(raw, "sugar_free_truth") == 2
    view = build_view(raw, ctx.profile, ctx.brand)
    assert view["state_variables"][0]["current"] == 6
    assert view["dark_threads"][0]["current_stage"] == 2


def test_run_pipeline_ir11_fields_omitted_defaults_empty(tmp_path, monkeypatch):
    """旧 prompt 形态（新输出字段全部缺席）→ pipeline 照常产出 IR 1.1，新表默认空。"""
    _no_cache(tmp_path, monkeypatch)
    from nsc.passes.pipeline import run_pipeline

    ir = run_pipeline(_make_ctx(tmp_path, OmitIR11Router()))

    assert ir.facts == []
    assert ir.threads == []
    assert ir.state_variables == []
    assert ir.dark_threads == []
    assert all(ep.responds_to == [] and ep.state_changes == [] for ep in ir.episodes)
    assert all(sc.opening_attractor == "" and sc.ending_hook == "" for sc in ir.scenes)
    assert all(sc.knowledge_state is None for sc in ir.scenes)
    assert all(not c.mental_models and c.expression_dna is None for c in ir.characters)
    assert len(ir.chapters) == 6  # 后续 Pass 未受影响


def test_p2_new_outputs_default_empty_when_omitted(tmp_path, monkeypatch):
    """Pass 级可缺省：p2 只回必填输出 → 新表默认空、responds_to 默认 []。"""

    class OldPromptRouter:
        def resolve(self, tier: str) -> dict:
            return {"model": f"stub/{tier}", "temperature": 0.0, "max_tokens": 4000}

        def complete(self, tier, messages, *, json_mode=False, seed=None):
            from nsc.runtime.models import LLMResult

            return LLMResult(
                text=json.dumps(
                    {
                        "episodes_json": json.dumps(
                            [{"title": "第1集", "logline": "x", "hook_promise": "y"}]
                        ),
                        "placement_plan_json": "[]",
                        "season_arc": "弧线",
                    },
                    ensure_ascii=False,
                ),
                model_id="stub/model",
                tokens_in=1,
                tokens_out=1,
                cost_usd=0.0,
                wall_ms=1,
            )

    _no_cache(tmp_path, monkeypatch)
    from nsc.passes import p2_arc

    ctx = _make_ctx(tmp_path, OldPromptRouter())
    r = p2_arc.run(
        ctx,
        {
            "bible": {"characters": [], "locations": [], "props": [], "motifs": [], "tone": None},
            "project_id": KNOWN_ULID,
        },
    )
    assert r["threads"] == []
    assert r["state_variables"] == []
    assert r["dark_threads"] == []
    assert all(e["responds_to"] == [] for e in r["episodes"])


_BEATS = [
    {
        "beat_kind": "hook",
        "summary": "办公室：小满发现体检报告，冲突是与陈经理对质，反转是背面还有一行字",
        "emotion": {"valence": 0.2, "arousal": 0.5},
        "est_duration_s": 12,
    }
]
_FACTS = [
    {
        "content": "伏笔A",
        "type": "foreshadowing",
        "status": "unresolved",
        "resolves": None,
        "episode_no": 2,
        "narrative_weight": "high",
    },
    {
        "content": "同集回收",
        "type": "plot_event",
        "status": "active",
        "resolves": 0,
        "episode_no": 2,
    },
    {
        "content": "跨集回收",
        "type": "plot_event",
        "status": "active",
        "resolves": KNOWN_ULID,
        "episode_no": 2,
    },
]


class _P3Router:
    """按 resolves 覆写构造 p3 响应（beats 最小合法 + facts + state_changes）。"""

    def __init__(self, resolves_override: object | None = None) -> None:
        self.override = resolves_override

    def resolve(self, tier: str) -> dict:
        return {"model": f"stub/{tier}", "temperature": 0.0, "max_tokens": 4000}

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        from nsc.runtime.models import LLMResult

        facts = [dict(f) for f in _FACTS]
        if self.override is not None:
            facts[2]["resolves"] = self.override
        return LLMResult(
            text=json.dumps(
                {
                    "beats_json": json.dumps(_BEATS, ensure_ascii=False),
                    "setup_payoffs_json": "[]",
                    "facts_json": json.dumps(facts, ensure_ascii=False),
                    "state_changes_json": json.dumps(
                        [
                            {"key": "trust_level", "delta": 1, "reason": "推进"},
                            {"key": "undeclared_key", "delta": 1, "reason": "应被丢弃"},
                        ],
                        ensure_ascii=False,
                    ),
                },
                ensure_ascii=False,
            ),
            model_id="stub/model",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            wall_ms=1,
        )


_P3_FRAG = {
    "episode": {"id": EP_ULID, "kind": "episode", "no": 2, "title": "t", "hook_promise": "h"},
    "bible": {"characters": [], "locations": []},
    "placement": [],
    "required_brand_moment_beats": 0,
    "known_facts": [
        {
            "id": KNOWN_ULID,
            "content": "第一集伏笔",
            "episode_no": 1,
            "status": "unresolved",
            "type": "foreshadowing",
        }
    ],
    "declared_state": {
        "state_variables": [{"key": "trust_level", "type": "number"}],
        "dark_threads": [],
    },
}


def test_p3_fact_reference_resolution_and_cascade(tmp_path, monkeypatch):
    """p3：同集下标→新 id、跨集 id 原样保留、未声明 key 的 state_change 被丢弃；级联幂等。"""
    _no_cache(tmp_path, monkeypatch)
    from nsc.passes import p3_beatsheet

    r = p3_beatsheet.run(_make_ctx(tmp_path, _P3Router()), dict(_P3_FRAG))
    fa, fb, fc = r["facts"]
    assert fb["resolves"] == fa["id"]  # 同集下标 → Pass 分配的新 id
    assert fc["resolves"] == KNOWN_ULID  # 跨集已知 id 原样保留
    assert [c["key"] for c in r["state_changes"]] == ["trust_level"]  # 未声明 key 丢弃

    cascaded = p3_beatsheet.apply_fact_cascade([dict(f) for f in r["facts"]])
    assert cascaded[0]["status"] == "resolved"  # 被 fb/fc 回收 → 级联翻转
    assert cascaded[1]["status"] == "active"
    again = p3_beatsheet.apply_fact_cascade([dict(f) for f in cascaded])
    assert again[0]["status"] == "resolved"  # 幂等

    # 自称 resolved 却无人回收 → 降回 unresolved（INV-17 充要的机械执行）
    orphan = [dict(f) for f in r["facts"][:1]]
    orphan[0]["status"] = "resolved"
    assert p3_beatsheet.apply_fact_cascade(orphan)[0]["status"] == "unresolved"


def test_p3_fact_bad_reference_raises_passfailure(tmp_path, monkeypatch):
    """伪造跨集引用 / 自我回收 → PassFailure，诊断句可直接喂重试。"""
    _no_cache(tmp_path, monkeypatch)
    from nsc.passes import PassFailure, p3_beatsheet

    ctx = _make_ctx(tmp_path, _P3Router(resolves_override="不存在的id"))
    with pytest.raises(PassFailure, match="不是已知 fact id"):
        p3_beatsheet.run(ctx, dict(_P3_FRAG))

    ctx2 = _make_ctx(tmp_path, _P3Router(resolves_override=2))  # 指向自身下标
    with pytest.raises(PassFailure, match="自我回收"):
        p3_beatsheet.run(ctx2, dict(_P3_FRAG))
