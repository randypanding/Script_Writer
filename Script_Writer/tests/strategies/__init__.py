"""IR 构造策略（Hypothesis 的 `@given` 数据源 + 测试 fixture 生成器）。

只依赖 spec.ir 公开入口，不 import src/nsc 内部实现——保证"重写 src 之后同一套测试仍绿"。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ulid import ULID

RUN_ID = "run-minimal-000001"


def _ulid() -> str:
    return str(ULID())


def _run() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "pass_name": "p0_intake",
        "spec_sha": "x" * 40,
        "profile_ver": "1.0",
        "brand_ver": "1.0",
        "ruleset_ver": "x" * 12,
        "promptset_ver": "1.0",
        "model_id": "openai/gpt-5.1",
        "temperature": 0.7,
        "seed": 1,
        "input_hash": "x" * 64,
        "case_refs": [],
        "created_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "cost_usd": 0.01,
        "tokens_in": 10,
        "tokens_out": 10,
    }


def build_minimal_ir(*, n_episodes: int = 1, beats_per_ep: int = 5) -> dict[str, Any]:
    """构造一份结构合法、通过全部不变量与 L0 检查的最小 IR。

    用于 golden fixture 与 checker pass 用例。6 集真实剧情由强模型完成（T-06）。
    """
    project_id = _ulid()
    season_id = _ulid()
    char_ids = {
        "protagonist": _ulid(),
        "customer_proxy": _ulid(),
        "ally": _ulid(),
        "antagonist": _ulid(),
    }
    loc_office = _ulid()
    loc_store = _ulid()
    prop_cup = _ulid()
    thread_id = _ulid()
    fact_a = _ulid()  # 伏笔（第 1 集埋，后被 B 回收）
    fact_b = _ulid()  # 回收 A 的情节事件

    characters = [
        {
            "id": char_ids["protagonist"],
            "name": "林晚",
            "role": "protagonist",
            "want": "想在不靠节食的前提下控糖",
            "need": "接受自己的不完美",
            "voice_notes": "短句、爱反问",
            "voice_tics": ["完了", "真的假的"],
            "persona_ref": "office_woman_28",
            "mental_models": [
                {
                    "name": "热量守恒",
                    "description": "把一切快乐折算成热量负债",
                    "trigger": "看到配料表",
                    "action_tendency": "先放下再说",
                    "failure_mode": "错过眼前这杯",
                }
            ],
            "decision_heuristics": ["先看配料表再开口"],
            "honest_boundaries": ["不当面对小满说教"],
            "expression_dna": {
                "syntax": "短句",
                "rhetoric": "反问",
                "emotion_temperature": "低温",
                "signature_lines": ["这杯茶，不额外加蔗糖。"],
            },
        },
        {
            "id": char_ids["customer_proxy"],
            "name": "小满",
            "role": "customer_proxy",
            "want": "下午别再说教",
            "need": "被当成朋友而不是病人",
            "voice_notes": "吐槽、损友式",
            "voice_tics": ["你听我说", "就这"],
            "persona_ref": "office_woman_28",
        },
        {
            "id": char_ids["ally"],
            "name": "阿哲",
            "role": "ally",
            "want": "把店做下去",
            "need": "被信任",
            "voice_notes": "慢、诚恳",
            "persona_ref": "",
        },
        {
            "id": char_ids["antagonist"],
            "name": "陈经理",
            "role": "antagonist",
            "want": "压预算",
            "need": "被看见价值",
            "voice_notes": "公事公办",
            "persona_ref": "",
        },
    ]
    locations = [
        {"id": loc_office, "name": "办公室工位", "cost_tier": "free"},
        {"id": loc_store, "name": "清野茶事门店", "cost_tier": "cheap"},
    ]
    props = [
        {
            "id": prop_cup,
            "name": "清野轻乳茶",
            "is_brand_product": True,
            "sku_ref": "light_milk_tea",
        }
    ]

    episodes_list = []
    scenes = []
    beats = []
    lines = []
    brand_moments = []
    setup_payoffs = []
    for ep_no in range(1, n_episodes + 1):
        ep_id = _ulid()
        order = ep_no - 1
        # ADR-0012：状态变更声明（暗线首末各 +1 步，信任度每集 +1）+ 悬念回收声明
        state_changes = [{"key": "trust_level", "delta": 1, "reason": "本集信任推进一格"}]
        if ep_no == 1 or ep_no == n_episodes:
            state_changes.append(
                {"key": "sugar_free_truth", "delta": 1, "reason": "暗线揭示推进一步"}
            )
        episodes_list.append(
            {
                "id": ep_id,
                "kind": "episode",
                "parent_id": season_id,
                "order": order,
                "no": ep_no,
                "title": f"第{ep_no}集 谁在偷喝我的茶",
                "logline": "林晚发现体检报告异常",
                "duration_target_s": 90,
                "hook_promise": "林晚的体检报告到底藏了什么？",
                "cliffhanger": "" if ep_no == n_episodes else "报告背面还有一行字",
                "responds_to": [ep_no - 1] if ep_no >= 2 else [],
                "state_changes": state_changes,
                "provenance_id": RUN_ID,
                "locked": False,
            }
        )
        scene_id = _ulid()
        scenes.append(
            {
                "id": scene_id,
                "kind": "scene",
                "parent_id": ep_id,
                "order": 0,
                "location_id": loc_office,
                "time_of_day": "day",
                "interior": True,
                "present_character_ids": [char_ids["protagonist"], char_ids["customer_proxy"]],
                "goal": "林晚要确认报告读数",
                "conflict": "陈经理催着要她签字",
                "turn": "她发现同一杯茶两种说法",
                "entry": "林晚刚坐下",
                "exit": "她抓起杯子出门",
                "opening_attractor": "体检报告特写：空腹血糖临界",
                "escalation_beats": ["签字催促", "两种说法对质"],
                "ending_hook": "报告背面还有一行字",
                "knowledge_state": {
                    "audience_knows": "报告读数异常",
                    "characters_know": "林晚知道异常，小满不知道",
                    "hidden": "陈经理改过备注",
                    "new_evidence": "配料表照片",
                },
                "provenance_id": RUN_ID,
                "locked": False,
            }
        )
        kinds = [
            "hook",
            "setup",
            "escalation",
            "brand_moment",
            "cta" if ep_no == n_episodes else "cliffhanger",
        ]
        dur = [14, 16, 20, 20, 20]
        setup_beat: Any = None
        payoff_beat: Any = None
        for bi, (kind, d) in enumerate(zip(kinds, dur, strict=True)):
            beat_id = _ulid()
            beats.append(
                {
                    "id": beat_id,
                    "kind": "beat",
                    "parent_id": scene_id,
                    "order": bi,
                    "beat_kind": kind,
                    "summary": f"第{ep_no}集第{bi}拍：{kind}",
                    "function": "推动",
                    "emotion": {"valence": 0.3 + 0.15 * bi, "arousal": 0.4 + 0.1 * bi},
                    "est_duration_s": d,
                    "brand_moment_id": beat_id if kind == "brand_moment" else None,
                    "provenance_id": RUN_ID,
                    "locked": False,
                }
            )
            if kind == "brand_moment":
                brand_moments.append(
                    {
                        "id": beat_id,
                        "anchor_beat_id": beat_id,
                        "type": "usage",
                        "intensity": 2,
                        "modality": "both",
                        "plot_connection": "high",
                        "selling_point_id": "no_sucrose",
                        "proof_mode": "reaction",
                        "integration_note": "林晚顺手把无蔗糖的茶递给小满",
                        "prop_id": prop_cup,
                    }
                )
            if kind == "setup":
                setup_beat = beat_id
            if kind in ("cliffhanger", "cta"):
                payoff_beat = beat_id
            # 非 action Beat 至少 1 条 Line
            line_id = _ulid()
            lines.append(
                {
                    "id": line_id,
                    "kind": "line",
                    "parent_id": beat_id,
                    "order": 0,
                    "line_type": "dialogue",
                    "character_id": char_ids["protagonist"],
                    "text": "这杯茶，不额外加蔗糖。",
                    "subtext": "",
                    "delivery": "",
                    "is_brand_line": kind == "brand_moment",
                    "provenance_id": RUN_ID,
                    "locked": False,
                }
            )
        setup_payoffs.append(
            {
                "id": _ulid(),
                "setup_beat_id": setup_beat,
                "payoff_beat_id": payoff_beat,
                "kind": "prop",
                "description": "茶杯标签在集末被看清",
            }
        )

    return {
        "schema_version": "1.1",
        "project": {
            "id": project_id,
            "kind": "project",
            "parent_id": None,
            "order": 0,
            "title": "清野茶事 · 六集短剧",
            "logline": "一个怕胖的女生在办公室里找一杯能喝的茶",
            "profile_id": "short_drama_v1",
            "brand_id": "demo_tea",
            "client_note": "",
            "provenance_id": RUN_ID,
            "locked": False,
        },
        "seasons": [
            {
                "id": season_id,
                "kind": "season",
                "parent_id": project_id,
                "order": 0,
                "title": "",
                "arc_summary": "从怀疑到信任",
                "theme": "真诚",
                "provenance_id": RUN_ID,
                "locked": False,
            }
        ],
        "episodes": episodes_list,
        "scenes": scenes,
        "beats": beats,
        "lines": lines,
        "characters": characters,
        "locations": locations,
        "props": props,
        "brand_moments": brand_moments,
        "setup_payoffs": setup_payoffs,
        "motifs": [],
        "constraints": [],
        "tone": None,
        "voice": None,
        # --- ADR-0012 运行时叙事状态层（合法样例，INV-17..20 全绿） ---
        "facts": [
            {
                "id": fact_a,
                "content": "茶杯标签背面写着代糖来源",
                "character_ids": [char_ids["protagonist"]],
                "episode_no": 1,
                "status": "resolved",
                "type": "foreshadowing",
                "resolves": None,
                "caused_by": [],
                "known_to": "reader_only",
                "hidden_from": [],
                "suspense_type": "foreshadow",
                "narrative_weight": "high",
                "thread_ids": [thread_id],
            },
            {
                "id": fact_b,
                "content": "标签被当众看清，伏笔回收",
                "character_ids": [char_ids["protagonist"], char_ids["customer_proxy"]],
                "episode_no": 2 if n_episodes >= 2 else 1,
                "status": "active",
                "type": "plot_event",
                "resolves": fact_a,
                "caused_by": [fact_a],
                "known_to": "all",
                "hidden_from": [],
                "suspense_type": None,
                "narrative_weight": "medium",
                "thread_ids": [thread_id],
            },
        ],
        "threads": [
            {
                "id": thread_id,
                "title": "这杯茶到底加没加糖",
                "state": "已揭底",
                "status": "resolved" if n_episodes >= 2 else "active",
            }
        ],
        "state_variables": [
            {
                "key": "trust_level",
                "name": "林晚对小满的信任度",
                "type": "number",
                "initial": 0,
                "description": "每集 +1，重放派生 current",
            }
        ],
        "dark_threads": [
            {
                "key": "sugar_free_truth",
                "name": "无糖真相暗线",
                "stages": ["只看表面", "起疑半揭", "当面全揭"],
                "description": "首末集各推进一步",
            }
        ],
        "chapters": [],
        "provenance": [_run()],
    }
