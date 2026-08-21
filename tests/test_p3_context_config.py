"""SW-05 p3 fragment 组成数据化：prev_summary 窗口 / known_facts 投影 / Thread 注入开关。

三个旋钮此前硬编码在 pipeline.py（窗口=1、投影=五字段、threads 永不注入）；
现在由 profile 的 context.* 段驱动，缺省 = 原行为（零变化）。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import yaml

import nsc.runtime.cache as cache_mod
from tests.test_pipeline_stub import FullStubRouter


# ---------------------------------------------------------------- known_facts 投影
def test_known_facts_projection_fields():
    from nsc.passes.pipeline import _known_facts

    facts = [
        {
            "id": "f1",
            "content": "林晚怕苦",
            "episode_no": 2,
            "status": "active",
            "type": "backstory",
        }
    ]
    # 缺省 = 原五字段（含各字段缺省值填充）
    assert _known_facts(facts) == [
        {
            "id": "f1",
            "content": "林晚怕苦",
            "episode_no": 2,
            "status": "active",
            "type": "backstory",
        }
    ]
    # 窄投影：只保留 profile 指定的字段
    assert _known_facts(facts, ("id", "content")) == [{"id": "f1", "content": "林晚怕苦"}]
    # 字段缺省仍生效
    assert _known_facts([{"id": "f2", "content": "x"}])[0]["status"] == "active"


def test_known_facts_fields_from_profile(tmp_path):
    from nsc.passes.pipeline import _known_fact_fields_of

    assert _known_fact_fields_of({}) == ("id", "content", "episode_no", "status", "type")
    ctx_profile = {"context": {"known_fact_fields": ["id", "content"]}}
    assert _known_fact_fields_of(ctx_profile) == ("id", "content")


# ---------------------------------------------------------------- 窗口与 Thread 注入（全桩管线）
class RecordingRouter(FullStubRouter):
    """记录每次 p3 的输入，其余行为与黄金桩一致。"""

    def __init__(self) -> None:
        super().__init__()
        self.p3_inputs: list[dict] = []

    def _p3(self, inputs):
        self.p3_inputs.append(inputs)
        return super()._p3(inputs)


def _ctx(tmp_path, monkeypatch, context_cfg: dict | None):
    monkeypatch.setenv("NSC_NO_CACHE", "1")
    monkeypatch.setattr(cache_mod, "_cache", diskcache.Cache(str(tmp_path / "cache")))
    from nsc.passes import PassContext
    from nsc.runtime.provenance import RunsStore

    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    if context_cfg is not None:
        profile["context"] = context_cfg
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    brief = yaml.safe_load(Path("examples/demo_tea/brief.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        brief=brief,
        router=RecordingRouter(),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


def _run(ctx):
    from nsc.passes.pipeline import run_pipeline

    run_pipeline(ctx)
    return ctx.router.p3_inputs


def test_prev_summary_window_default_is_one(tmp_path, monkeypatch):
    inputs = _run(_ctx(tmp_path, monkeypatch, None))
    summaries = {ep_no: inp["prev_episode_summary"] for ep_no, inp in enumerate(inputs)}
    assert summaries[0] == "", "首集为空"
    # 原行为：第 N 集只看到第 N-1 集的 Beat 摘要
    for i in range(2, len(inputs)):
        assert summaries[i] != summaries[i - 1], "相邻集窗口内容不同（各自只含前一集）"


def test_prev_summary_window_two_includes_grandparent(tmp_path, monkeypatch):
    inputs = _run(_ctx(tmp_path, monkeypatch, {"prev_summary_window": 2}))
    summaries = {ep_no: inp["prev_episode_summary"] for ep_no, inp in enumerate(inputs)}
    assert summaries[0] == ""
    assert summaries[1] != "", "第二集窗口=第一集摘要"
    # 窗口=2：第 3 集的窗口严格包含第 2 集的窗口（多了第 1 集摘要）
    assert summaries[2].startswith(summaries[1]), "近端摘要在前，远端追加在后"
    assert len(summaries[2]) > len(summaries[1])


def test_threads_injection_switch(tmp_path, monkeypatch):
    inputs_off = _run(_ctx(tmp_path, monkeypatch, None))
    assert all("threads" not in inp for inp in inputs_off), "缺省不注入 threads（原行为）"

    inputs_on = _run(_ctx(tmp_path, monkeypatch, {"inject_threads": True}))
    assert inputs_on and all("threads" in inp for inp in inputs_on)
    threads = json.loads(inputs_on[0]["threads"])
    assert isinstance(threads, list)
    if threads:  # 黄金桩 p2 可能没产出 threads；有则校验投影面
        assert set(threads[0]) == {"id", "title", "status", "state"}
