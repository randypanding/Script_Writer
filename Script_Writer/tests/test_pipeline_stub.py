"""run_pipeline 编排的全桩端到端测试（无 LLM）。

桩路由按 signature docstring 识别当前 Pass，并从黄金 IR 派生响应：
这同时验证了 p0..p7 的装配契约与"黄金内容能穿过流水线"这一事实。
真实 LLM 的 e2e 见 tests/test_pipeline_llm.py（标 llm，nightly 跑）。
"""

from __future__ import annotations

import json
from pathlib import Path

import diskcache
import pytest
import yaml

import nsc.runtime.cache as cache_mod

GOLDEN = json.loads(Path("tests/fixtures/golden/demo_tea_ir.json").read_text("utf-8"))
G_CHARS = {c["id"]: c for c in GOLDEN["characters"]}
G_LOCS = {loc["id"]: loc for loc in GOLDEN["locations"]}


def _golden_ep(no: int):
    ep = next(e for e in GOLDEN["episodes"] if e["no"] == no)
    scenes = [s for s in GOLDEN["scenes"] if s["parent_id"] == ep["id"]]
    sids = {s["id"] for s in scenes}
    beats = [b for b in GOLDEN["beats"] if b["parent_id"] in sids]
    bids = {b["id"] for b in beats}
    lines = [ln for ln in GOLDEN["lines"] if ln["parent_id"] in bids]
    sps = [
        sp
        for sp in GOLDEN["setup_payoffs"]
        if sp["setup_beat_id"] in bids and sp["payoff_beat_id"] in bids
    ]
    return ep, scenes, beats, lines, sps


class FullStubRouter:
    """按 system 提示里的种子指令特征识别 Pass，返回黄金派生的 JSON。"""

    def __init__(self) -> None:
        self.tiers: list[str] = []

    def resolve(self, tier: str) -> dict:
        return {"model": f"stub/{tier}", "temperature": 0.0, "max_tokens": 4000}

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        from nsc.runtime.models import LLMResult

        self.tiers.append(tier)
        system = messages[0]["content"]
        inputs = json.loads(messages[-1]["content"])
        if "归一化" in system:
            payload = self._p0(inputs)
        elif "人物、地点、道具" in system:
            payload = self._p1(inputs)
        elif "季/集级弧线" in system:
            payload = self._p2(inputs)
        elif "组织成可拍摄的场景" in system:
            payload = self._p4(inputs)
        elif "写出 Beat 序列" in system:
            payload = self._p3(inputs)
        elif "对白与动作" in system:
            payload = self._p5(inputs)
        elif "编织成一章小说" in system:
            payload = self._p6(inputs)
        else:  # pragma: no cover - 防御
            raise AssertionError(f"未识别的 Pass 指令：{system[:50]}")
        return LLMResult(
            text=json.dumps(payload, ensure_ascii=False),
            model_id="stub/model",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            wall_ms=1,
        )

    def _p0(self, inputs):
        return {
            "normalized_brief": "六集短剧：写字楼女生小满与楼下茶饮店从对峙到信任",
            "missing_fields_json": "[]",
        }

    def _p1(self, inputs):
        strip = lambda coll: [{k: v for k, v in x.items() if k != "id"} for x in coll]  # noqa: E731
        return {
            "characters_json": json.dumps(strip(GOLDEN["characters"]), ensure_ascii=False),
            "locations_json": json.dumps(strip(GOLDEN["locations"]), ensure_ascii=False),
            "props_json": json.dumps(strip(GOLDEN["props"]), ensure_ascii=False),
            "motifs_json": json.dumps(
                [
                    {k: v for k, v in m.items() if k not in ("id", "occurrence_beat_ids")}
                    for m in GOLDEN["motifs"]
                ],
                ensure_ascii=False,
            ),
            "tone_json": json.dumps(GOLDEN["tone"], ensure_ascii=False),
        }

    def _p2(self, inputs):
        plan = []
        for no in range(1, 7):
            _ep, _scenes, beats, _lines, _sps = _golden_ep(no)
            bids = {b["id"] for b in beats}
            for bm in GOLDEN["brand_moments"]:
                if bm["anchor_beat_id"] in bids:
                    plan.append(
                        {
                            "episode_no": no,
                            "selling_point_id": bm["selling_point_id"],
                            "type": bm["type"],
                            "intensity": bm["intensity"],
                            "modality": bm["modality"],
                            "plot_connection": bm["plot_connection"],
                            "proof_mode": bm["proof_mode"],
                            "intent": bm["integration_note"],
                        }
                    )
        return {
            "episodes_json": json.dumps(
                [
                    {
                        "no": e["no"],
                        "title": e["title"],
                        "logline": e["logline"],
                        "hook_promise": e["hook_promise"],
                        "cliffhanger": e["cliffhanger"],
                        "duration_target_s": e["duration_target_s"],
                        # ADR-0012：每集回收上一集悬念（STR-016 闭环）
                        "responds_to": [e["no"] - 1] if e["no"] >= 2 else [],
                    }
                    for e in GOLDEN["episodes"]
                ],
                ensure_ascii=False,
            ),
            "placement_plan_json": json.dumps(plan, ensure_ascii=False),
            "season_arc": GOLDEN["seasons"][0]["arc_summary"],
            # ADR-0012：叙事状态三张表（FCT-006/007 要求每集有状态推进）
            "threads_json": json.dumps(
                [{"title": "无糖真相", "state": "推进中", "status": "active"}], ensure_ascii=False
            ),
            "state_variables_json": json.dumps(
                [{"key": "trust_level", "name": "信任度", "type": "number", "initial": 0}],
                ensure_ascii=False,
            ),
            "dark_threads_json": json.dumps(
                [
                    {
                        "key": "sugar_free_truth",
                        "name": "无糖真相暗线",
                        "stages": ["起疑", "半揭", "全揭"],
                    }
                ],
                ensure_ascii=False,
            ),
        }

    def _p3(self, inputs):
        ep_in = json.loads(inputs["episode_json"])
        _ep, _scenes, beats, _lines, sps = _golden_ep(ep_in["no"])
        idx = {b["id"]: i for i, b in enumerate(beats)}
        # 黄金节拍没有 escalation（STR-018 要求每集至少一个升级/阻碍/反转拍）：
        # 机械把一个 setup/payoff 拍标成 escalation，数量与顺序不变。
        kinds = [b["beat_kind"] for b in beats]
        if not any(k in ("escalation", "complication", "reversal") for k in kinds):
            for i, k in enumerate(kinds):
                if k in ("setup", "payoff"):
                    kinds[i] = "escalation"
                    break
        return {
            "beats_json": json.dumps(
                [
                    {
                        "beat_kind": kinds[i],
                        "summary": b["summary"],
                        "function": b["function"],
                        "emotion": b["emotion"],
                        "est_duration_s": b["est_duration_s"],
                    }
                    for i, b in enumerate(beats)
                ],
                ensure_ascii=False,
            ),
            "setup_payoffs_json": json.dumps(
                [
                    {
                        "setup": idx[sp["setup_beat_id"]],
                        "payoff": idx[sp["payoff_beat_id"]],
                        "kind": sp["kind"],
                        "description": sp["description"],
                        "slug": "",
                    }
                    for sp in sps
                ],
                ensure_ascii=False,
            ),
            # ADR-0012：每集状态推进（FCT-006/007）；暗线只在首末各推一步（界内）
            "state_changes_json": json.dumps(
                [{"key": "trust_level", "delta": 1, "reason": "本集信任推进一格"}],
                ensure_ascii=False,
            ),
        }

    def _p4(self, inputs):
        bible = json.loads(inputs["bible_json"])
        loc_by_name = {loc["name"]: loc["id"] for loc in bible["locations"]}
        char_by_name = {c["name"]: c["id"] for c in bible["characters"]}
        in_beats = json.loads(inputs["beats_json"])
        summaries = [b["summary"] for b in in_beats]
        g_beats = {b["summary"]: b for b in GOLDEN["beats"]}
        g_scene_of = {}
        for b in GOLDEN["beats"]:
            g_scene_of[b["id"]] = b["parent_id"]
        scene_order: list[str] = []
        for s in summaries:
            sid = g_scene_of[g_beats[s]["id"]]
            if sid not in scene_order:
                scene_order.append(sid)
        scenes_json = []
        for sid in scene_order:
            g_sc = next(s for s in GOLDEN["scenes"] if s["id"] == sid)
            scenes_json.append(
                {
                    "location_id": loc_by_name[G_LOCS[g_sc["location_id"]]["name"]],
                    "time_of_day": g_sc["time_of_day"],
                    "interior": g_sc["interior"],
                    "present_character_ids": [
                        char_by_name[G_CHARS[c]["name"]] for c in g_sc["present_character_ids"]
                    ],
                    "goal": g_sc["goal"],
                    "conflict": g_sc["conflict"],
                    "turn": g_sc["turn"],
                    "entry": g_sc["entry"],
                    "exit": g_sc["exit"],
                    "summary": g_sc["summary"],
                    # ADR-0012：场级节奏与知识状态（STR-017 要求首场开场点/末场切出钩 ≥4 字）
                    "opening_attractor": "特写：体检报告上的空腹血糖读数",
                    "escalation_beats": ["签字催促", "两种说法对质"],
                    "ending_hook": "黑屏前一帧：报告背面还有一行字",
                    "knowledge_state": {
                        "audience_knows": "报告读数异常",
                        "characters_know": "林晚知道异常",
                        "hidden": "陈经理改过备注",
                        "new_evidence": "配料表照片",
                    },
                }
            )
        mapping = [
            {"beat_index": i, "scene_index": scene_order.index(g_scene_of[g_beats[s]["id"]])}
            for i, s in enumerate(summaries)
        ]
        return {
            "scenes_json": json.dumps(scenes_json, ensure_ascii=False),
            "beat_to_scene": json.dumps(mapping),
        }

    def _p5(self, inputs):
        chars = json.loads(inputs["characters_json"])
        char_by_name = {c["name"]: c["id"] for c in chars}
        in_beats = json.loads(inputs["beats_json"])
        g_beats = {b["summary"]: b for b in GOLDEN["beats"]}
        out_lines = []
        for i, b in enumerate(in_beats):
            g_beat = g_beats[b["summary"]]
            for ln in GOLDEN["lines"]:
                if ln["parent_id"] != g_beat["id"]:
                    continue
                out_lines.append(
                    {
                        "beat_index": i,
                        "line_type": ln["line_type"],
                        "character_id": char_by_name.get(G_CHARS[ln["character_id"]]["name"])
                        if ln["character_id"]
                        else None,
                        "text": ln["text"],
                        "subtext": ln["subtext"],
                        "delivery": ln["delivery"],
                        "is_brand_line": ln["is_brand_line"],
                    }
                )
        return {"lines_json": json.dumps(out_lines, ensure_ascii=False)}

    def _p6(self, inputs):
        swl = json.loads(inputs["scenes_with_lines_json"])
        paragraphs, anchor_map = [], []
        for sc in swl:
            for b in sc["beats"]:
                dlg = next((x for x in b["lines"] if x["line_type"] == "dialogue"), None)
                para = f"她后来总会想起这一刻。「{dlg['text']}」" if dlg else b["summary"]
                anchor_map.append(
                    {
                        "paragraph_index": len(paragraphs),
                        "beat_id": b["id"],
                        "line_ids": [x["id"] for x in b["lines"]],
                    }
                )
                paragraphs.append(para)
        return {
            "chapter_title": "章",
            "paragraphs_json": json.dumps(paragraphs, ensure_ascii=False),
            "anchor_map_json": json.dumps(anchor_map, ensure_ascii=False),
        }


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
        router=FullStubRouter(),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test-rules",
        spec_sha="test-spec",
        out_dir=tmp_path / "out",
    )


def test_run_pipeline_end_to_end_stub(ctx):
    from nsc.checker.interpreter import RuleSet, evaluate
    from nsc.passes.pipeline import run_pipeline
    from nsc.runtime.ir_io import build_view

    ir = run_pipeline(ctx)

    assert len(ir.episodes) == 6
    assert len(ir.chapters) == 6
    view = build_view(ir.model_dump(), ctx.profile, ctx.brand)
    rs = RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage="final",
        enabled_domains=ctx.profile["enabled_check_domains"],
    )
    rep = evaluate(rs, view, ctx={"profile": ctx.profile, "brand": ctx.brand})
    assert rep.errors == []
    assert rep.findings == [], rep.as_feedback_text()

    out_dir = ctx.out_dir / ir.project.title
    assert (out_dir / "novel.md").exists()
    assert (out_dir / "script.md").exists()
    assert (out_dir / "manifest.json").exists()

    ran = {r["pass_name"] for r in ctx.store.runs()}
    assert ran == {
        "p0_intake",
        "p1_bible",
        "p2_arc",
        "p3_beatsheet",
        "p4_scene",
        "p5_dialogue",
        "p6_prose",
        "p7_render",
    }
