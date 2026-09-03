"""P0 Intake 对 glm-5.3-flash 字段命名漂移的兼容测试（T-07 回归）。

离线回放 transcript：模型返回 missing_fields_ 而非 missing_fields_json。
修复后应自动别名归一，不抛 PassFailure。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from nsc.passes import PassContext
from nsc.passes.p0_intake import run as p0_run
from nsc.runtime.provenance import RunsStore


class GlmCompatRouter:
    """模拟 glm-5.3-flash 在 p0_intake 返回 missing_fields_ 的行为。"""

    def __init__(self, response: dict[str, object]) -> None:
        self.tiers: list[str] = []
        self._response = response

    def resolve(self, tier: str) -> dict:
        return {
            "model": "openai/glm-5.3-flash",
            "temperature": 0.2,
            "max_tokens": 24000,
        }

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        from nsc.runtime.models import LLMResult

        self.tiers.append(tier)
        return LLMResult(
            text=json.dumps(self._response, ensure_ascii=False),
            model_id="openai/glm-5.3-flash",
            tokens_in=100,
            tokens_out=100,
            cost_usd=0.0,
            wall_ms=1,
        )


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=GlmCompatRouter(
            {
                "normalized_brief": json.dumps(
                    {
                        "schema_version": "1.0",
                        "brand_id": "demo_tea",
                        "brand_name": "清野茶事",
                    },
                    ensure_ascii=False,
                ),
                "missing_fields_": "[]",
            }
        ),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


def test_missing_fields_alias_is_accepted(ctx):
    fragment = {
        "raw_brief": ctx.brief,
        "raw_brand": ctx.brand,
    }
    out = p0_run(ctx, fragment)
    assert out["missing_fields"] == []
    assert out["normalized_brief"] is not None


def test_missing_fields_still_required_when_absent(ctx):
    """完全缺字段时仍需 PassFailure（可诊断，不静默降级）。"""
    ctx.router = GlmCompatRouter({"normalized_brief": "{}"})
    fragment = {
        "raw_brief": ctx.brief,
        "raw_brand": ctx.brand,
    }
    with pytest.raises(Exception) as excinfo:
        p0_run(ctx, fragment)
    assert "missing_fields" in str(excinfo.value)
