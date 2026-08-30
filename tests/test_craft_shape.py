"""craft_shape 题材工艺形状（round28）：检测、注入、CRAFT-001 题材豁免。

证据链：Lab W1 分题材锚 v2（522 卡，mined/craft_anchors_v2.json）——治愈系 person 0.33 vs
爆款契约假定的 0.83，混题材约束对低冲突题材是锚错位（round25/26 实证）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from nsc.context.craft_shape import resolve

HEALING_REQUEST = "海南文旅 IP，气质：自由 + 治愈 + 一点点孤独底色，不是热血冒险。"
PLAIN_REQUEST = "写字楼上班的女生，想表达真材实料、不加蔗糖。"


def test_detect_healing() -> None:
    out = resolve({"raw_request": HEALING_REQUEST, "notes": ["温柔克制"]})
    assert out["genre"] == "治愈成长"
    assert out["antagonist_required"] is False
    assert out["ensemble_scene_required"] is False


def test_detect_default() -> None:
    out = resolve({"raw_request": PLAIN_REQUEST, "notes": ["不要出现竞品"]})
    assert out["genre"] == "爆款通用"
    assert out["antagonist_required"] is True


def test_detect_empty_brief_falls_back() -> None:
    out = resolve({})
    assert out["genre"] == "爆款通用"


def test_shape_knowledge_lives_in_spec() -> None:
    """知识在 spec/（AGENTS.md §2）：机制模块不得内置题材关键词/形状。"""
    src = Path("src/nsc/context/craft_shape.py").read_text("utf-8")
    assert "治愈" not in src
    spec = yaml.safe_load(Path("spec/craft_shape.yaml").read_text("utf-8"))
    assert spec["shapes"]["爆款通用"]["antagonist_required"] is True
    assert spec["shapes"]["治愈成长"]["hook_types"][0] in ("承诺", "颠覆")


def test_make_ctx_injects_shape(tmp_path: Path) -> None:
    """_make_ctx 把 craft_shape 注入 profile → 随 profile_json 到达每个 Pass 与检查 bind。"""
    from nsc.cli import _make_ctx

    brief = {
        "project_title": "南浪仔",
        "profile": "short_drama_v1",
        "brand": "demo_tea",
        "raw_request": HEALING_REQUEST,
        "notes": [],
    }
    ctx = _make_ctx(brief, tmp_path)
    assert ctx.profile["craft_shape"]["genre"] == "治愈成长"
    assert ctx.profile["craft_shape"]["antagonist_required"] is False


def _craft001_report(ir_raw: dict, profile: dict):
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.runtime.ir_io import build_view

    rule = yaml.safe_load(Path("spec/checks/structure/CRAFT-001.yaml").read_text("utf-8"))
    rs = RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage=rule["stage"],
        enabled_domains=["structure"],
    )
    rs.rules = [rule]
    view = build_view(ir_raw, profile, {})
    return evaluate(rs, view, ctx={"profile": profile, "brand": {}})


@pytest.fixture()
def fail_fixture() -> dict:
    return json.loads((Path("tests/fixtures/checks/CRAFT-001/fail.json")).read_text("utf-8"))


@pytest.fixture()
def ant_absent_fixture(fail_fixture: dict) -> dict:
    """主角在场、对手不在场:专测对手项豁免(fail.json 连主角也不在场,测不了豁免)。

    集级在场由 build_view 从 scenes.present_character_ids 派生,须注到 scene 层。
    """
    raw = json.loads(json.dumps(fail_fixture))
    pro = next(c["id"] for c in raw["characters"] if c["role"] == "protagonist")
    for sc in raw["scenes"]:
        sc["present_character_ids"] = sorted({*sc.get("present_character_ids", []), pro})
    return raw


def test_craft001_waives_antagonist_for_healing(profiles: dict, ant_absent_fixture: dict) -> None:
    """antagonist_required=false 时,对手不在场不触发(主角在场已满足)。

    round28 实证回归:JMESPath 的 `||` 对布尔 false 回退右值,`false || true` = true,
    豁免被静默吞掉——bind 必须用 `!= false` 比较做缺省,且测试必须断言"不触发"而非仅无 errors。
    """
    profile = {**profiles["short_drama_v1"], "craft_shape": {"antagonist_required": False}}
    rep = _craft001_report(ant_absent_fixture, profile)
    assert not rep.errors, rep.errors
    assert not any(f.rule_id == "CRAFT-001" for f in rep.findings), (
        "豁免失效:antagonist_required=false 时 CRAFT-001 仍触发(JMESPath 真值或回归)"
    )


def test_craft001_fires_when_required(profiles: dict, ant_absent_fixture: dict) -> None:
    """显式 antagonist_required=true 时与旧行为一致：对手不在场即触发。"""
    profile = {**profiles["short_drama_v1"], "craft_shape": {"antagonist_required": True}}
    rep = _craft001_report(ant_absent_fixture, profile)
    assert any(f.rule_id == "CRAFT-001" for f in rep.findings)


def test_craft001_still_fires_without_shape(profiles: dict, golden_ir: dict) -> None:
    """profile 无 craft_shape（旧配置）时 JMESPath 缺省回 true → 行为与现行逐字节一致。"""
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.runtime.ir_io import build_view

    rule = yaml.safe_load(Path("spec/checks/structure/CRAFT-001.yaml").read_text("utf-8"))
    profile = {k: v for k, v in profiles["short_drama_v1"].items() if k != "craft_shape"}
    rs = RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage=rule["stage"],
        enabled_domains=["structure"],
    )
    rs.rules = [rule]
    fail_fixture = json.loads(
        (Path("tests/fixtures/checks/CRAFT-001/fail.json")).read_text("utf-8")
    )
    view = build_view(fail_fixture, profile, {})
    rep = evaluate(rs, view, ctx={"profile": profile, "brand": {}})
    assert any(f.rule_id == "CRAFT-001" for f in rep.findings)


@pytest.mark.parametrize("name", ["Bible", "Arc", "SceneCards"])
def test_signatures_reference_shape(name: str) -> None:
    """种子指令必须引用 craft_shape（否则参数化对 seed 系 Pass 不生效）。"""
    import spec.passes.signatures as sig

    assert "craft_shape" in (getattr(sig, name).__doc__ or "")
