"""T-04 验收：内容寻址缓存的三条硬语义。"""

from __future__ import annotations

import diskcache
import pytest

import nsc.runtime.cache as cache_mod
from nsc.runtime.provenance import RunsStore


class FakeCtx:
    """PassContext 的最小替身：只实现 cached_pass 依赖的两个方法。"""

    def __init__(self, store: RunsStore, brand_ver: str = "1.0.0") -> None:
        self.store = store
        self.brand_ver = brand_ver
        self.calls = 0

    def cache_versions(self, pass_name: str) -> dict:
        return {
            "promptset_ver": "seed",
            "profile_ver": "1.0.0",
            "brand_ver": self.brand_ver,
            "ruleset_ver": "r1",
            "model_id": "fake/model",
            "temperature": 0.0,
            "seed": 1,
            "spec_sha": "s1",
        }

    def record_run(self, pass_name, input_hash, cache_hit, usage, wall_ms) -> None:
        from nsc.runtime.provenance import RunRecord

        self.store.record(
            RunRecord.new(
                pass_name=pass_name,
                spec_sha="s1",
                profile_ver="1.0.0",
                brand_ver=self.brand_ver,
                ruleset_ver="r1",
                promptset_ver="seed",
                model_id="fake/model",
                temperature=0.0,
                seed=1,
                input_hash=input_hash,
                cache_hit=cache_hit,
                tokens_in=usage.get("tokens_in", 0),
                tokens_out=usage.get("tokens_out", 0),
                cost_usd=usage.get("cost_usd", 0.0),
                wall_ms=wall_ms,
            )
        )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    store = RunsStore(tmp_path / "runs.db")
    return store


def _make_pass(ctx: FakeCtx):
    @cache_mod.cached_pass("p_test")
    def p(ctx: FakeCtx, fragment: dict) -> dict:
        ctx.calls += 1
        return {
            "echo": fragment["x"],
            "_usage": {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.01},
        }

    return p


def test_same_input_second_call_is_cache_hit(env):
    ctx = FakeCtx(env)
    p = _make_pass(ctx)
    r1 = p(ctx, {"x": 1})
    r2 = p(ctx, {"x": 1})
    assert r1 == r2
    assert ctx.calls == 1, "同输入二次调用不得再执行 Pass 体"
    runs = env.runs("p_test")
    assert [r["cache_hit"] for r in runs] == [0, 1]
    assert runs[1]["cost_usd"] == 0.0 and runs[1]["tokens_in"] == 0


def test_any_version_change_invalidates(env):
    ctx = FakeCtx(env)
    p = _make_pass(ctx)
    p(ctx, {"x": 1})
    ctx2 = FakeCtx(env, brand_ver="2.0.0")  # 只改一个版本号
    p2 = _make_pass(ctx2)
    p2(ctx2, {"x": 1})
    assert ctx2.calls == 1, "brand_ver 变化后必须重新执行"


def test_no_cache_env_bypasses(env, monkeypatch):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    ctx = FakeCtx(env)
    p = _make_pass(ctx)
    p(ctx, {"x": 1})
    p(ctx, {"x": 1})
    assert ctx.calls == 2, "NSC_NO_CACHE=1 必须强制绕过缓存"
    assert all(r["cache_hit"] == 0 for r in env.runs("p_test"))


def test_different_fragment_invalidates(env):
    ctx = FakeCtx(env)
    p = _make_pass(ctx)
    p(ctx, {"x": 1})
    p(ctx, {"x": 2})
    assert ctx.calls == 2
