"""p5 相位重试：after_p5 规则拦截（BM-007 必提台词缺失）时必须带诊断重试。"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from tests.test_pipeline_stub import FullStubRouter

MUST_LINE = "不额外加蔗糖"


class FlakyP5Router(FullStubRouter):
    """首轮 p5 漏掉必提台词（触发 BM-007）；输入带 _previous_failure 时修正。"""

    def __init__(self) -> None:
        super().__init__()
        self.p5_calls: list[dict] = []

    def _p5(self, inputs):
        self.p5_calls.append(inputs)
        payload = json.loads(super()._p5(inputs)["lines_json"])
        fixed = "_previous_failure" in inputs
        if not fixed:
            payload = [ln for ln in payload if MUST_LINE not in ln["text"]]
        return {"lines_json": json.dumps(payload, ensure_ascii=False)}


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=FlakyP5Router(),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


def test_p5_phase_retries_on_rule_block(ctx):
    from nsc.passes.pipeline import run_pipeline

    ir = run_pipeline(ctx)

    router = ctx.router
    assert len(router.p5_calls) > 12, "after_p5 拦截后 p5 应带诊断重试（12 场 × 首轮）"
    retried = [c for c in router.p5_calls if "_previous_failure" in c]
    assert retried, "重试输入必须携带 _previous_failure 诊断"
    assert any("BM-007" in c["_previous_failure"] for c in retried)
    all_text = "".join(ln.text for ln in ir.lines)
    assert MUST_LINE in all_text
