"""规则 DSL 一致性测试。自动发现 spec/checks/**.yaml，要求每条规则都有 pass/fail fixture。
组织方式借鉴 CheckList 的 MFT（docs/BORROW_MAP.md #13）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

CHECKS = sorted(p for p in Path("spec/checks").rglob("*.yaml") if not p.name.startswith("_"))
FIX = Path("tests/fixtures/checks")


def _rule(p: Path) -> dict:
    return yaml.safe_load(p.read_text("utf-8"))


def test_checks_exist():
    assert len(CHECKS) >= 30, f"首批需要 ≥30 条 L0 规则，当前 {len(CHECKS)}"


@pytest.mark.parametrize("path", CHECKS, ids=lambda p: _rule(p)["id"])
def test_every_rule_has_fixtures(path):
    rid = _rule(path)["id"]
    d = FIX / rid
    assert (d / "pass.json").exists(), f"{rid} 缺少 pass.json"
    assert (d / "fail.json").exists(), f"{rid} 缺少 fail.json"


@pytest.mark.parametrize("path", CHECKS, ids=lambda p: _rule(p)["id"])
def test_rule_pass_and_fail(path, profiles, demo_brand):
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.runtime.ir_io import build_view

    rule = _rule(path)
    rid = rule["id"]
    rs = RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage=rule["stage"],
        enabled_domains=[rule["domain"]],
    )
    rs.rules = [rule]  # 只测这一条
    for name, should_fire in (("pass.json", False), ("fail.json", True)):
        raw = json.loads((FIX / rid / name).read_text("utf-8"))
        view = build_view(raw, profiles["short_drama_v1"], demo_brand)
        rep = evaluate(rs, view, ctx={"profile": profiles["short_drama_v1"], "brand": demo_brand})
        assert not rep.errors, f"{rid} 规则本身报错：{rep.errors}"
        fired = any(f.rule_id == rid for f in rep.findings)
        assert fired == should_fire, f"{rid} 在 {name} 上 fired={fired}，期望 {should_fire}"


@pytest.mark.parametrize("path", CHECKS, ids=lambda p: _rule(p)["id"])
def test_message_quality(path):
    """DSL §5：message 必须是完整诊断句。这条测试直接保护 GEPA 的输入质量。"""
    r = _rule(path)
    msg = r["message"]
    assert len(msg) >= 30, f"{r['id']} 的 message 过短，无法作为 GEPA 反馈"
    assert "{" in msg, f"{r['id']} 的 message 未引用任何具体数值/节点"
    banned = ["invalid", "error", "违规", "不合法", "不符合要求"]
    assert not any(b in msg and len(msg) < 60 for b in banned), (
        f"{r['id']} 的 message 像日志而不是诊断"
    )
