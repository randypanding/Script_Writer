"""截断检测：finish_reason=length 或 tokens_out 顶格时，generate_json 应给出截断诊断。"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from nsc.passes import PassContext, PassFailure
from nsc.passes.p0_intake import run as p0_run
from nsc.runtime.provenance import RunsStore


class TruncationRouter:
    """模拟 finish_reason=length 且 tokens_out 顶格的响应。"""

    def __init__(self, response: dict[str, object], *, max_tokens: int) -> None:
        self.tiers: list[str] = []
        self._response = response
        self._max_tokens = max_tokens

    def resolve(self, tier: str) -> dict:
        return {
            "model": "openai/glm-5.3",
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
        }

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        from nsc.runtime.models import LLMResult

        self.tiers.append(tier)
        return LLMResult(
            text=json.dumps(self._response, ensure_ascii=False),
            model_id="openai/glm-5.3",
            tokens_in=100,
            tokens_out=self._max_tokens,
            cost_usd=0.0,
            wall_ms=1,
            finish_reason="length",
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
        router=TruncationRouter(
            {
                "normalized_brief": json.dumps({"schema_version": "1.0", "brand_id": "demo_tea"}, ensure_ascii=False),
                "missing_fields_json": "[]",
            },
            max_tokens=24000,
        ),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


def test_truncation_finish_reason_gives_diagnosis(ctx):
    """finish_reason=length 且 tokens_out 顶格时，应抛出含'截断'诊断的 PassFailure。"""
    fragment = {
        "raw_brief": ctx.brief,
        "raw_brand": ctx.brand,
    }
    with pytest.raises(PassFailure) as excinfo:
        p0_run(ctx, fragment)
    msg = str(excinfo.value)
    assert "截断" in msg or "max_tokens" in msg


def test_no_truncation_when_tokens_not_at_limit():
    """tokens_out 未顶格且 finish_reason=stop 时，不应触发截断诊断。"""
    from nsc.passes.p0_intake import run as p0_run

    class OkRouter:
        def resolve(self, tier): return {"model": "openai/glm-5.3", "temperature": 0.2, "max_tokens": 24000}
        def complete(self, tier, messages, *, json_mode=False, seed=None):
            from nsc.runtime.models import LLMResult
            return LLMResult(
                text=json.dumps({"normalized_brief": "{}", "missing_fields_json": "[]"}, ensure_ascii=False),
                model_id="openai/glm-5.3",
                tokens_in=100,
                tokens_out=100,
                cost_usd=0.0,
                wall_ms=1,
                finish_reason="stop",
            )

    import nsc.runtime.cache as cache_mod
    from nsc.runtime.provenance import RunsStore
    import diskcache
    ctx = PassContext(
        profile=yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8")),
        brand=yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8")),
        brief=yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8")),
        router=OkRouter(),
        store=RunsStore(Path("/tmp/nonexistent")),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=Path("/tmp/out"),
    )
    out = p0_run(ctx, {"raw_brief": ctx.brief, "raw_brand": ctx.brand})
    assert "normalized_brief" in out
