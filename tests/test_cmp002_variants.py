"""CMP-002 疗效表述变体对抗性测试（W4 demo_tea 五类死因加固）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nsc.checker.interpreter import RuleSet, evaluate
from nsc.runtime.ir_io import build_view


def _load_cmp002_rule() -> dict:
    return yaml.safe_load(
        Path("spec/checks/compliance/CMP-002.yaml").read_text("utf-8")
    )


def _make_ir(text: str) -> dict:
    """最小 IR：project/season/episode/scene/beat/line 足以让 build_view 产出 __all_text。"""
    return {
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
            }
        ],
        "scenes": [
            {
                "id": "sc1",
                "kind": "scene",
                "parent_id": "e1",
                "order": 0,
                "location_id": "l1",
                "present_character_ids": [],
                "goal": "",
                "conflict": "",
                "turn": "",
                "entry": "",
                "exit": "",
            }
        ],
        "beats": [
            {
                "id": "b1",
                "kind": "beat",
                "parent_id": "sc1",
                "order": 0,
                "beat_kind": "hook",
                "summary": "",
                "function": "",
                "emotion": {"valence": 0.0, "arousal": 0.0},
                "est_duration_s": 10,
                "brand_moment_id": None,
            }
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
                "name": "林晚",
                "role": "protagonist",
                "want": "",
                "need": "",
                "voice_notes": "",
                "persona_ref": "",
            }
        ],
        "locations": [{"id": "l1", "name": "办公室", "cost_tier": "free"}],
        "props": [
            {
                "id": "pr1",
                "name": "清野轻乳茶",
                "is_brand_product": True,
                "sku_ref": "light_milk_tea",
            }
        ],
        "brand_moments": [
            {
                "id": "bm1",
                "anchor_beat_id": "b1",
                "type": "usage",
                "intensity": 2,
                "modality": "both",
                "plot_connection": "high",
                "selling_point_id": "no_sucrose",
                "proof_mode": "reaction",
                "integration_note": "",
                "prop_id": "pr1",
            }
        ],
        "setup_payoffs": [],
        "motifs": [],
        "constraints": [],
        "tone": None,
        "voice": None,
        "chapters": [],
        "provenance": [],
    }


def _cmp002_fires(text: str) -> bool:
    profile = {"id": "short_drama_v1"}
    brand = {
        "id": "demo_tea",
        "legal": {"claim_whitelist": []},
        "products": [],
        "selling_points": [],
        "banned_words": [],
    }
    ir = _make_ir(text)
    view = build_view(ir, profile, brand)
    rule = _load_cmp002_rule()
    rs = RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage=rule["stage"],
        enabled_domains=[rule["domain"]],
    )
    rs.rules = [rule]
    rep = evaluate(rs, view, ctx={"profile": profile, "brand": brand})
    return any(f.rule_id == "CMP-002" for f in rep.findings)


# ---------- 应拦截：原有 10 词（放松基线） ----------


@pytest.mark.parametrize(
    "text",
    [
        "这杯茶能帮忙降血糖。",
        "治疗癌症的神奇茶饮。",
        "坚持喝就能治愈肥胖。",
        "这款产品可以根治口臭。",
        "抗癌首选，每天一杯。",
        "排毒养颜，一身轻松。",
        "提高免疫，不生病。",
        "减肥茶，轻松瘦身。",
    ],
)
def test_cmp002_blocks_legacy_claims(text):
    """确保原有 10 词覆盖不被后续改动放松。"""
    assert _cmp002_fires(text), f"CMP-002 未能拦截既有疗效表述: {text}"


# ---------- 应拦截：demo_tea 茶饮绕行 ----------


@pytest.mark.parametrize(
    "text",
    [
        # 降糖/控糖/抗糖（茶饮最常见绕行）
        "每天一杯，轻松降糖。",
        "帮助控糖，稳血糖。",
        "阻糖吸收，不怕胖。",
        "抗糖化，延缓衰老。",
        # 燃脂/减脂/纤体
        "燃脂又排毒。",
        "燃烧脂肪，清肠通便。",
        "减脂塑形就靠它。",
        "纤体配方，喝出好身材。",
        # 代谢/肠道
        "提高代谢，促进新陈代谢。",
        "调理肠胃，改善肠道。",
        "调节肠道菌群。",
        "改善便秘，通便排毒。",
        "润肠通便，一身轻松。",
    ],
)
def test_cmp002_blocks_tea_evasions(text):
    """demo_tea 茶饮常见疗效绕行必须被拦截。"""
    assert _cmp002_fires(text), f"CMP-002 未能拦截茶饮绕行: {text}"


# ---------- 应拦截：护肤品/医美功效 ----------


@pytest.mark.parametrize(
    "text",
    [
        # 祛斑/美白/提亮
        "祛斑美白，一瓶搞定。",
        "淡斑焕白，提亮肤色。",
        # 毛孔/细纹/皱纹
        "收缩毛孔，细致毛孔。",
        "淡化细纹，淡化皱纹。",
        # 屏障修复/敏感肌
        "修复屏障，修复痘印。",
        "修复敏感肌，舒缓镇静。",
        # 黑色素/胶原蛋白
        "阻断黑色素，抑制黑色素。",
        "促进胶原蛋白生成。",
        "增加胶原蛋白，紧致肌肤。",
        # 医美/械字号
        "医美级配方。",
        "械字号面膜。",
        # 消炎/镇静/抗炎
        "消炎镇静，快速退红。",
        "抗炎舒缓，改善泛红。",
    ],
)
def test_cmp002_blocks_skincare_claims(text):
    """护肤品/医美常见疗效宣称必须被拦截。"""
    assert _cmp002_fires(text), f"CMP-002 未能拦截护肤品疗效宣称: {text}"


# ---------- 应拦截：生理功能 / TCM 功效 ----------


@pytest.mark.parametrize(
    "text",
    [
        # 血压/血脂/内分泌
        "降压舒缓，守护心血管。",
        "降低胆固醇，守护心脏。",
        "调节内分泌，改善体质。",
        # 免疫/衰老
        "增强免疫，少生病。",
        "提升免疫力，增强抵抗力。",
        "抗氧化，延缓衰老。",
        "抗衰老，年轻十岁。",
        "逆转衰老不是梦。",
        # 睡眠/过敏/血栓
        "改善睡眠，一觉到天亮。",
        "预防血栓，守护血管。",
        "抗过敏，温和不刺激。",
        # DNA/止血/软化血管
        "修复DNA，从根源抗衰。",
        "止血化瘀，活血止痛。",
        "软化血管，降火祛湿。",
        # TCM
        "清热解毒，去火降火。",
        "滋阴补肾，补气血。",
        "暖宫驱寒，祛湿消肿。",
        "止痒消炎，舒缓肌肤。",
    ],
)
def test_cmp002_blocks_physiological_claims(text):
    """生理功能改善 / TCM 常见疗效宣称必须被拦截。"""
    assert _cmp002_fires(text), f"CMP-002 未能拦截生理/TCM疗效宣称: {text}"


# ---------- 不应拦截：合法叙事与体验描述 ----------


@pytest.mark.parametrize(
    "text",
    [
        "这杯茶，不额外加蔗糖。",
        "口感清爽，回甘不错。",
        "今天天气真好。",
        "林晚发现体检报告异常。",
        "喝完觉得很舒服。",
    ],
)
def test_cmp002_allows_benign_text(text):
    """体验描述与事实陈述不应触发 CMP-002。"""
    assert not _cmp002_fires(text), f"CMP-002 误伤合法叙事: {text}"
