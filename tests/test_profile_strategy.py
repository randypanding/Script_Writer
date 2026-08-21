"""SW-07 pipeline 策略 profile 化：重试次数 / 定向重生成策略 / self-check 开关 / 检索 top-k。

这些原是 pipeline.py、p5_dialogue.py、cli.py 里的代码常量；现在全部从
profile 的 pipeline.* / revise.* / retrieval.* 段读取，缺省值 = 原常量（零行为变化）。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod
from tests.test_pipeline_stub import FullStubRouter


def _mini_ctx(tmp_path, profile: dict):
    """策略读取测试用的最小 PassContext（真实类，防鸭子类型漂移）。"""
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    return PassContext(
        profile=profile,
        brand={},
        router=None,
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="t",
        spec_sha="t",
    )


def test_retry_pass_attempts_from_profile(tmp_path):
    from nsc.passes import PassFailure
    from nsc.passes.pipeline import _retry_pass

    calls = []

    def flaky(ctx, frag):
        calls.append(1)
        raise PassFailure(None, "boom")

    # 显式 attempts 优先（既有调用方语义不变）
    with pytest.raises(PassFailure):
        _retry_pass(flaky, _mini_ctx(tmp_path, {}), {}, attempts=1)
    assert len(calls) == 1

    calls.clear()
    with pytest.raises(PassFailure):
        _retry_pass(flaky, _mini_ctx(tmp_path, {"pipeline": {"pass_attempts": 1}}), {})
    assert len(calls) == 1, "pass_attempts=1 时只允许一次尝试"

    calls.clear()
    with pytest.raises(PassFailure):
        _retry_pass(flaky, _mini_ctx(tmp_path, {}), {})
    assert len(calls) == 2, "缺省保持原常量 attempts=2"


class FlakyP5Router(FullStubRouter):
    """首轮 p5 漏掉必提台词（触发 BM-007）；输入带 _previous_failure 时修正。"""

    MUST_LINE = "不额外加蔗糖"

    def _p5(self, inputs):
        payload = json.loads(super()._p5(inputs)["lines_json"])
        if "_previous_failure" not in inputs:
            payload = [ln for ln in payload if self.MUST_LINE not in ln["text"]]
        return {"lines_json": json.dumps(payload, ensure_ascii=False)}


def _ctx(tmp_path, monkeypatch, profile: dict):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

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


def test_phase_attempts_from_profile(tmp_path, monkeypatch):
    """phase_attempts=1：p5 相位首轮被 BM-007 拦截后不得重试，整体抛 PassFailure。"""
    from nsc.passes import PassFailure
    from nsc.passes.pipeline import _phase_attempts, run_pipeline

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    profile["pipeline"] = {"phase_attempts": 1}
    assert _phase_attempts(_ctx(tmp_path, monkeypatch, profile)) == 1

    ctx = _ctx(tmp_path, monkeypatch, profile)
    with pytest.raises(PassFailure):
        run_pipeline(ctx)

    profile2 = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    assert _phase_attempts(_ctx(tmp_path, monkeypatch, profile2)) == 3, "缺省保持原常量 3"


def test_revise_gate_mode_read_from_profile(tmp_path):
    from nsc.passes import p5_dialogue
    from nsc.passes.pipeline import _pass_attempts

    assert p5_dialogue._gate_mode(_mini_ctx(tmp_path, {})) == "lenient", "缺省保持原常量 lenient"
    assert (
        p5_dialogue._gate_mode(_mini_ctx(tmp_path, {"revise": {"gate_mode": "strict"}})) == "strict"
    ), "revise.gate_mode 必须可从 profile 读"
    assert _pass_attempts(_mini_ctx(tmp_path, {"pipeline": {"pass_attempts": 4}})) == 4


def test_retrieval_top_k_from_profile(tmp_path):
    from nsc.cli import _make_retrieval

    base = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    svc = _make_retrieval(_mini_ctx(tmp_path, {**base, "retrieval": {"top_k": 5}}))
    assert svc is not None and svc.k == 5, "retrieval.top_k 必须驱动检索条数"

    svc2 = _make_retrieval(_mini_ctx(tmp_path, dict(base)))
    assert svc2 is not None and svc2.k == 3, "缺省保持原常量 k=3"
