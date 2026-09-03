"""账房层门禁红队对抗夹具（无 LLM）。

覆盖 CMP / BM / FCT / STR / PRD / DLG / NOV-001 共 13 条规则，
每条构造最小 IR 并注入攻击 payload，预期 checker 触发 block/warn。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nsc.checker.interpreter import RuleSet, evaluate
from nsc.runtime.ir_io import build_view

# ---------------------------------------------------------------------------
# 最小 IR 工厂（继承 PR#18 的 _make_ir 并扩展 overrides）
# ---------------------------------------------------------------------------


def _load_yaml(name: str) -> dict:
    return yaml.safe_load(Path(f"spec/checks/compliance/{name}").read_text("utf-8"))


def _make_ir(text: str = "", **overrides) -> dict:
    """最小 IR：project/season/episode/scene/beat/line 足以让 build_view 产出派生字段。"""
    base = {
        "schema_version": "1.0",
        "project": {
            "id": "p1",
            "kind": "project",
            "title": "test",
            "profile_id": "short_drama_v1",
            "brand_id": "demo_tea",
        },
        "seasons": [
            {
                "id": "s1",
                "kind": "season",
                "parent_id": "p1",
                "order": 0,
            }
        ],
        "episodes": [
            {
                "id": "e1",
                "kind": "episode",
                "parent_id": "s1",
                "order": 0,
                "no": 1,
                "title": "第1集",
                "duration_target_s": 90,
            }
        ],
        "scenes": [
            {
                "id": "sc1",
                "kind": "scene",
                "parent_id": "e1",
                "order": 0,
                "location_id": "l1",
                "present_character_ids": ["c1"],
                "goal": "小满想要弄清楚这杯茶的真相。",
                "conflict": "她不敢相信商家说的话。",
                "turn": "店员当面打开包装，她决定再观察一周。",
                "entry": "三点整，小满坐在吧台前排。",
                "exit": "她拎着杯子出门，心里有了答案。",
            }
        ],
        "beats": [
            {
                "id": "b1",
                "kind": "beat",
                "parent_id": "sc1",
                "order": 0,
                "beat_kind": "hook",
                "summary": "三点闹钟响，小满的手指悬在拼单支付键上不敢按。",
                "function": "开场钩子",
                "emotion": {"valence": 0.1, "arousal": 0.75},
                "est_duration_s": 10.0,
                "brand_moment_id": None,
            },
            {
                "id": "b2",
                "kind": "beat",
                "parent_id": "sc1",
                "order": 1,
                "beat_kind": "cliffhanger",
                "summary": "她决定明天带着体检报告去门店问个明白。",
                "function": "集末钩子",
                "emotion": {"valence": 0.5, "arousal": 0.7},
                "est_duration_s": 14.0,
                "brand_moment_id": None,
            },
        ],
        "lines": [
            {
                "id": "l1",
                "kind": "line",
                "parent_id": "b1",
                "order": 0,
                "line_type": "dialogue",
                "character_id": "c1",
                "text": text,
            }
        ],
        "characters": [
            {
                "id": "c1",
                "name": "小满",
                "role": "protagonist",
                "want": "",
                "need": "",
                "voice_notes": "",
                "persona_ref": "",
            }
        ],
        "locations": [{"id": "l1", "name": "办公室", "cost_tier": "free", "cost_weight": 1.0}],
        "props": [
            {
                "id": "pr1",
                "name": "清野轻乳茶",
                "is_brand_product": True,
                "sku_ref": "light_milk_tea",
            }
        ],
        "brand_moments": [],
        "setup_payoffs": [],
        "motifs": [],
        "constraints": [],
        "tone": None,
        "voice": None,
        "chapters": [],
        "provenance": [],
        "facts": [],
        "dark_threads": [],
        "state_variables": [],
        "episode_state": [],
    }
    base.update(overrides)
    return base


def _load_rule(rel_path: str) -> dict:
    return yaml.safe_load(Path(rel_path).read_text("utf-8"))


def _rule_fires(rule: dict, ir: dict, profile: dict, brand: dict) -> bool:
    brand_id = brand.get("id", brand.get("brand_id"))
    assert isinstance(brand_id, str)
    rs = RuleSet.load(
        profile_id=profile["id"],
        industry="beverage",
        brand_id=brand_id,
        stage=rule["stage"],
        enabled_domains=[rule["domain"]],
    )
    rs.rules = [rule]
    view = build_view(ir, profile, brand)
    rep = evaluate(rs, view, ctx={"profile": profile, "brand": brand})
    return any(f.rule_id == rule["id"] for f in rep.findings)


# ---------------------------------------------------------------------------
#  fixture 上下文（与 conftest.py 一致）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def profiles():
    return {
        p.stem: yaml.safe_load(p.read_text("utf-8"))
        for p in Path("profiles").glob("*.yaml")
        if not p.stem.startswith("_")
    }


@pytest.fixture(scope="session")
def demo_brand():
    return yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))


# ---------------------------------------------------------------------------
# CMP-001：绝对化用语（英文/数字混排）
# ---------------------------------------------------------------------------


def test_red_team_cmp001_mixed_english(profiles, demo_brand):
    rule = _load_rule("spec/checks/compliance/CMP-001.yaml")
    text = "This is the NO.1 最好喝的茶，绝对唯一。"
    ir = _make_ir(text=text)
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        f"CMP-001 未能拦截英文混排绝对化用语: {text}"
    )


# ---------------------------------------------------------------------------
# CMP-002：疗效表述绕行（谐音 / 拆字 / 英文混排 / 拼音 / 异体字 / emoji）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "每天一杯，轻松酱糖。",  # 谐音：降→酱
        "白-月-巴 也能喝。",  # 拆字：肥
        "reducing blood sugar naturally.",  # 英文混排
        "jiang tang 稳定，不怕胖。",  # 拼音
        "療效显著，癒合创伤。",  # 异体字
        "降🩸糖、控🩸糖，一身轻松。",  # emoji 插入
    ],
)
def test_red_team_cmp002_evasions(profiles, demo_brand, text):
    rule = _load_rule("spec/checks/compliance/CMP-002.yaml")
    ir = _make_ir(text=text)
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        f"CMP-002 未能拦截绕行变体: {text}"
    )


# ---------------------------------------------------------------------------
# BM-001：品牌植入密度超限
# ---------------------------------------------------------------------------


def test_red_team_bm001_density_overflow(profiles, demo_brand):
    rule = _load_rule("spec/checks/brand/BM-001.yaml")
    ir = _make_ir()
    # 单集 3 个 brand_moment，超过 max_moments_per_episode=2
    ir["beats"] = [
        {
            "id": f"b{i}",
            "kind": "beat",
            "parent_id": "sc1",
            "order": i,
            "beat_kind": "brand_moment",
            "summary": f"品牌植入{i}",
            "function": "卖点",
            "emotion": {"valence": 0.3, "arousal": 0.5},
            "est_duration_s": 12.0,
            "brand_moment_id": f"bm{i}",
        }
        for i in range(3)
    ]
    ir["brand_moments"] = [
        {
            "id": f"bm{i}",
            "anchor_beat_id": f"b{i}",
            "type": "usage",
            "intensity": 2,
            "modality": "both",
            "plot_connection": "high",
            "selling_point_id": "no_sucrose",
            "proof_mode": "reaction",
            "integration_note": "",
            "prop_id": "pr1",
        }
        for i in range(3)
    ]
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        "BM-001 未能拦截品牌 moment 密度超限"
    )


# ---------------------------------------------------------------------------
# BM-007：必提台词原文出现
# ---------------------------------------------------------------------------


def test_red_team_bm007_must_include_missing(profiles, demo_brand):
    rule = _load_rule("spec/checks/brand/BM-007.yaml")
    # 文本中没有"不额外加蔗糖"，改写为"无蔗糖"
    text = "这款茶是无蔗糖的，喝起来很清爽。"
    ir = _make_ir(text=text)
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        f"BM-007 未能拦截必提台词缺失: {text}"
    )


# ---------------------------------------------------------------------------
# BM-011：竞品名零出现
# ---------------------------------------------------------------------------


def test_red_team_bm011_competitor_injection(profiles, demo_brand):
    rule = _load_rule("spec/checks/brand/BM-011.yaml")
    text = "连茗香茶语的老顾客都转来喝清野轻乳茶。"
    ir = _make_ir(text=text)
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        f"BM-011 未能拦截竞品名注入: {text}"
    )


# ---------------------------------------------------------------------------
# FCT-001：产品参数必须来自 BrandBrief
# ---------------------------------------------------------------------------


def test_red_team_fct001_hallucinated_param(profiles, demo_brand):
    rule = _load_rule("spec/checks/fact/FCT-001.yaml")
    text = "这款茶热量只有15千卡，比普通奶茶低一半。"
    ir = _make_ir(text=text)
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        f"FCT-001 未能拦截虚构参数: {text}"
    )


# ---------------------------------------------------------------------------
# STR-001：每集恰好 1 个 Hook Beat 且位于前 20%
# ---------------------------------------------------------------------------


def test_red_team_str001_hook_missing(profiles, demo_brand):
    rule = _load_rule("spec/checks/structure/STR-001.yaml")
    ir = _make_ir()
    # 0 个 hook
    ir["beats"] = [
        {
            "id": f"b{i}",
            "kind": "beat",
            "parent_id": "sc1",
            "order": i,
            "beat_kind": "escalation",
            "summary": f"节拍{i}",
            "function": "推进",
            "emotion": {"valence": 0.0, "arousal": 0.5},
            "est_duration_s": 15.0,
            "brand_moment_id": None,
        }
        for i in range(4)
    ]
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        "STR-001 未能拦截 Hook Beat 缺失"
    )


# ---------------------------------------------------------------------------
# STR-002：每集必须有终态 Beat（cliffhanger / resolution / cta）
# ---------------------------------------------------------------------------


def test_red_team_str002_terminal_missing(profiles, demo_brand):
    rule = _load_rule("spec/checks/structure/STR-002.yaml")
    ir = _make_ir()
    # 末 beat 是 escalation，不是终态
    ir["beats"] = [
        {
            "id": "b0",
            "kind": "beat",
            "parent_id": "sc1",
            "order": 0,
            "beat_kind": "hook",
            "summary": "开场",
            "function": "钩子",
            "emotion": {"valence": 0.1, "arousal": 0.75},
            "est_duration_s": 10.0,
            "brand_moment_id": None,
        },
        {
            "id": "b1",
            "kind": "beat",
            "parent_id": "sc1",
            "order": 1,
            "beat_kind": "escalation",
            "summary": "冲突升级但没有收束",
            "function": "推进",
            "emotion": {"valence": -0.2, "arousal": 0.6},
            "est_duration_s": 20.0,
            "brand_moment_id": None,
        },
    ]
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        "STR-002 未能拦截终态 Beat 缺失"
    )


# ---------------------------------------------------------------------------
# PRD-001：场地成本不超预算档
# ---------------------------------------------------------------------------


def test_red_team_prd001_cost_overflow(profiles, demo_brand):
    rule = _load_rule("spec/checks/producibility/PRD-001.yaml")
    ir = _make_ir()
    # 2 个场地，cost_weight 合计 4 > budget 3.0（expensive=3, cheap=1）
    ir["locations"] = [
        {"id": "l1", "name": "办公室", "cost_tier": "cheap", "cost_weight": 1.0},
        {"id": "l2", "name": "医院", "cost_tier": "expensive", "cost_weight": 3.0},
    ]
    # 让 episode 引用 l1, l2（通过 scenes 的 location_id）
    ir["scenes"] = [
        {
            "id": "sc1",
            "kind": "scene",
            "parent_id": "e1",
            "order": 0,
            "location_id": "l1",
            "present_character_ids": ["c1"],
            "goal": "小满想要弄清楚这杯茶的真相。",
            "conflict": "她不敢相信商家说的话。",
            "turn": "店员当面打开包装，她决定再观察一周。",
            "entry": "三点整，小满坐在吧台前排。",
            "exit": "她拎着杯子出门，心里有了答案。",
        },
        {
            "id": "sc2",
            "kind": "scene",
            "parent_id": "e1",
            "order": 1,
            "location_id": "l2",
            "present_character_ids": ["c1"],
            "goal": "小满想要弄清楚这杯茶的真相。",
            "conflict": "她不敢相信商家说的话。",
            "turn": "店员当面打开包装，她决定再观察一周。",
            "entry": "三点整，小满坐在吧台前排。",
            "exit": "她拎着杯子出门，心里有了答案。",
        },
    ]
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        "PRD-001 未能拦截场地成本超预算"
    )


# ---------------------------------------------------------------------------
# DLG-001：禁用词零出现
# ---------------------------------------------------------------------------


def test_red_team_dlg001_banned_word(profiles, demo_brand):
    rule = _load_rule("spec/checks/dialogue/DLG-001.yaml")
    text = "这款茶养胃又促消化，空腹也能喝。"
    ir = _make_ir(text=text)
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        f"DLG-001 未能拦截禁用词: {text}"
    )


# ---------------------------------------------------------------------------
# DLG-003：说话人必须在场
# ---------------------------------------------------------------------------


def test_red_team_dlg003_speaker_absent(profiles, demo_brand):
    rule = _load_rule("spec/checks/dialogue/DLG-003.yaml")
    ir = _make_ir(text="我不在场，但这句话是我说的。")
    # scene 的 present_character_ids 只有 c1，但 line 的 character_id 是 c2
    ir["lines"][0]["character_id"] = "c2"
    ir["scenes"][0]["present_character_ids"] = ["c1"]
    ir["characters"].append(
        {
            "id": "c2",
            "name": "阿珍",
            "role": "supporting",
            "want": "",
            "need": "",
            "voice_notes": "",
            "persona_ref": "",
        }
    )
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        "DLG-003 未能拦截说话人不在场"
    )


# ---------------------------------------------------------------------------
# NOV-001：小说章节必须 100% 覆盖对应 Beat
# ---------------------------------------------------------------------------


def test_red_team_nov001_coverage_gap(profiles, demo_brand):
    rule = _load_rule("spec/checks/novel/NOV-001.yaml")
    ir = _make_ir()
    # episode 有 2 个 beat，但 chapter 只 anchor 了 1 个 beat
    ir["beats"] = [
        {
            "id": "b0",
            "kind": "beat",
            "parent_id": "sc1",
            "order": 0,
            "beat_kind": "hook",
            "summary": "开场",
            "function": "钩子",
            "emotion": {"valence": 0.1, "arousal": 0.75},
            "est_duration_s": 10.0,
            "brand_moment_id": None,
        },
        {
            "id": "b1",
            "kind": "beat",
            "parent_id": "sc1",
            "order": 1,
            "beat_kind": "cliffhanger",
            "summary": "结尾",
            "function": "钩子",
            "emotion": {"valence": 0.5, "arousal": 0.7},
            "est_duration_s": 14.0,
            "brand_moment_id": None,
        },
    ]
    ir["chapters"] = [
        {
            "id": "ch1",
            "episode_id": "e1",
            "order": 0,
            "title": "第一章",
            "paragraphs": ["只覆盖第一个 beat 的内容。"],
            "anchor_map": [
                {
                    "paragraph_index": 0,
                    "beat_id": "b0",
                    "line_ids": ["l1"],
                }
                # b1 缺失
            ],
            "provenance_id": "test-p6-0001",
            "word_chars": 10,
        }
    ]
    assert _rule_fires(rule, ir, profiles["short_drama_v1"], demo_brand), (
        "NOV-001 未能拦截章节覆盖缺口"
    )
