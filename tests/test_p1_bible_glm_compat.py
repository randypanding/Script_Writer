"""P1 Bible 对 glm-5.3-flash 字段命名漂移与输出截断的兼容测试（T-07 回归）。

离线回放 transcript：
1. 字段名漂移：`characters_json` -> `characters_`（系统性 `*_json` -> `*_`）
2. 输出截断：response 仅 7609 字符，但 JSON 实际包含 5 个字段（未被截断）
   注：tokens_out=13855 含 reasoning，content 约 7600 chars，疑似 bigmodel coding paas 端点
   对 content 长度有限制，但 JSON 结构完整。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from nsc.passes import PassContext
from nsc.passes.p1_bible import run as p1_run
from nsc.runtime.provenance import RunsStore


class GlmCompatRouter:
    """模拟 glm-5.3-flash 在 p1_bible 返回 *_ 别名字段的行为。"""

    def __init__(self, response: dict[str, object]) -> None:
        self.tiers: list[str] = []
        self._response = response

    def resolve(self, tier: str) -> dict:
        return {
            "model": "openai/glm-5.3-flash",
            "temperature": 0.8,
            "max_tokens": 32000,
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


def _minimal_bible() -> dict[str, object]:
    """最小可过 p1_bible 的 5 字段 JSON（别名 *_ 形式）。"""
    return {
        "characters_": json.dumps(
            [
                {
                    "name": "测试角色",
                    "role": "protagonist",
                    "age_range": "26-30",
                    "want": "测试动机",
                    "need": "测试需求",
                    "flaw": "测试缺陷",
                    "arc": "测试弧线",
                    "voice_notes": "测试声音",
                    "voice_tics": [],
                    "forbidden_words": [],
                    "persona_ref": "office_woman_28",
                    "mental_models": [],
                    "decision_heuristics": [],
                    "honest_boundaries": [],
                    "expression_dna": None,
                }
            ],
            ensure_ascii=False,
        ),
        "locations_": json.dumps(
            [
                {
                    "name": "测试地点",
                    "interior": True,
                    "description": "测试描述",
                    "cost_tier": "free",
                    "shoot_notes": "测试备注",
                }
            ],
            ensure_ascii=False,
        ),
        "props_": json.dumps(
            [
                {
                    "name": "测试道具",
                    "is_brand_product": False,
                    "sku_ref": "",
                    "cost_tier": "free",
                }
            ],
            ensure_ascii=False,
        ),
        "motifs_": json.dumps(
            [
                {
                    "name": "测试母题",
                    "description": "测试描述",
                }
            ],
            ensure_ascii=False,
        ),
        "tone_": json.dumps(
            {
                "tone_words": ["真诚"],
                "banned_words": [],
                "register": "colloquial",
                "humor": "light",
                "reference_works": [],
            },
            ensure_ascii=False,
        ),
    }


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
        router=GlmCompatRouter(_minimal_bible()),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


def test_bible_json_alias_is_accepted(ctx):
    """`*_json` 漂移成 `*_` 时应自动别名归一。"""
    fragment = {
        "normalized_brief": {
            "schema_version": "1.0",
            "brand_id": "demo_tea",
            "brand_name": "清野茶事",
        },
        "brand_brief_json": json.dumps(ctx.brand, ensure_ascii=False),
        "profile_json": json.dumps(ctx.profile, ensure_ascii=False),
        "retrieved_cases": "",
    }
    out = p1_run(ctx, fragment)
    assert "characters" in out
    assert "locations" in out
    assert len(out["characters"]) > 0


def test_bible_missing_all_fields_still_fails(ctx):
    """所有字段均缺失时仍 PassFailure（可诊断）。"""
    ctx.router = GlmCompatRouter({})
    fragment = {
        "normalized_brief": {"schema_version": "1.0"},
        "brand_brief_json": "{}",
        "profile_json": "{}",
        "retrieved_cases": "",
    }
    with pytest.raises(Exception) as excinfo:
        p1_run(ctx, fragment)
    assert "p1_bible" in str(excinfo.value)
