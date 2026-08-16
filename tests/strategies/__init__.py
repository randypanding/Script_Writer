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
        "schema_version": "1.0",
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
        "chapters": [],
        "provenance": [_run()],
    }
