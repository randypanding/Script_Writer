"""T-18 泛化压测脚本的纯函数测试（无 LLM）。

只测不碰 LLM 的部分：brief 规格生成（确定性/覆盖）、brief 渲染、报告渲染。
编译路径（调 LLM）不在单测范围，由真实压测/CI 跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import stress_generalize as sg  # noqa: E402


def test_generate_specs_deterministic():
    a = sg.generate_specs(8, seed=42)
    b = sg.generate_specs(8, seed=42)
    assert len(a) == len(b) == 8
    # 同 seed 完全一致（字段逐一对比）
    for x, y in zip(a, b, strict=True):
        assert x.title == y.title and x.notes == y.notes


def test_generate_specs_differs_by_seed():
    a = sg.generate_specs(12, seed=1)
    b = sg.generate_specs(12, seed=2)
    # 组合足够多样：不同 seed 至少有一处不同
    assert any(
        (x.title, x.product, x.audience, x.notes) != (y.title, y.product, y.audience, y.notes)
        for x, y in zip(a, b, strict=True)
    )


def test_spec_to_brief_fields():
    spec = sg.generate_specs(1, seed=7)[0]
    brief = sg.spec_to_brief(spec, "short_video_v1", "demo_tea")
    assert brief["profile"] == "short_video_v1"
    assert brief["brand"] == "demo_tea"
    assert brief["episode_count"] == 1  # short_video_v1 只支持单条
    assert brief["project_title"]
    assert "产品是demo_tea的" in brief["raw_request"]
    assert isinstance(brief["notes"], list) and brief["notes"]


def test_render_report_ok_and_failed(tmp_path):
    results = [
        sg.StressResult(0, "甲", "ok", findings=2, rules_evaluated=10, cost_usd=0.1, wall_ms=100),
        sg.StressResult(1, "乙", "failed", reason="STR-007 未闭合"),
        sg.StressResult(2, "丙", "ok", findings=0, rules_evaluated=10, cost_usd=0.2, wall_ms=90),
    ]
    out = sg.render_report(results, "short_video_v1", count=3, seed=1, out=tmp_path / "report.md")
    text = out.read_text("utf-8")
    assert "通过 final L0：2/3" in text
    assert "编译失败：1" in text
    assert "STR-007 未闭合" in text
    assert "累计成本：$0.3" in text
