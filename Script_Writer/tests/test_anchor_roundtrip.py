"""T-08 渲染 + D29 锚点往返测试。

核心验收：渲染 docx → 读回 → 100% 恢复 node_id。
这里用内联构造的最小 IR（不依赖 T-06 黄金 IR），保证 ci-local 可跑。
"""

from __future__ import annotations

import pytest

from nsc.render import read_anchors_from_docx, render_all
from nsc.render.docx import read_docx_anchors, render_docx
from nsc.render.fountain import render_fountain
from nsc.render.novel import render_chapter
from nsc.render.storyboard import render_storyboard

#: 固定 ULID（合法字符集，内容无关）
P_ID = "01M04TVA5Z74ZZKYYJRFWXFC8V"
S_ID = "01M04TVA5Z74ZZKYYJRFWXFC8W"
E_ID = "01M04TVA5Z74ZZKYYJRFWXFC94"
SC_ID = "01M04TVA5Z74ZZKYYJRFWXFC95"
B1, B2, B3 = (
    "01M04TVA5Z74ZZKYYJRFWXFC96",
    "01M04TVA5Z74ZZKYYJRFWXFC98",
    "01M04TVA5Z74ZZKYYJRFWXFC9A",
)
C1, C2 = "01M04TVA5Z74ZZKYYJRFWXFC8X", "01M04TVA5Z74ZZKYYJRFWXFC8Y"
LOC = "01M04TVA5Z74ZZKYYJRFWXFC91"


def _minimal_ir() -> dict:
    return {
        "schema_version": "1.0",
        "project": {
            "id": P_ID,
            "kind": "project",
            "title": "清野茶事",
            "logline": "log",
            "profile_id": "short_drama_v1",
            "brand_id": "demo_tea",
            "provenance_id": "run-minimal",
            "order": 0,
            "locked": False,
        },
        "seasons": [
            {
                "id": S_ID,
                "kind": "season",
                "parent_id": P_ID,
                "order": 0,
                "arc_summary": "弧",
                "theme": "真诚",
                "provenance_id": "run-minimal",
            }
        ],
        "episodes": [
            {
                "id": E_ID,
                "kind": "episode",
                "parent_id": S_ID,
                "order": 0,
                "no": 1,
                "title": "第1集",
                "logline": "log",
                "duration_target_s": 90,
                "hook_promise": "hook",
                "cliffhanger": "",
                "provenance_id": "run-minimal",
            }
        ],
        "scenes": [
            {
                "id": SC_ID,
                "kind": "scene",
                "parent_id": E_ID,
                "order": 0,
                "location_id": LOC,
                "interior": True,
                "time_of_day": "day",
                "present_character_ids": [C1, C2],
                "goal": "g",
                "conflict": "c",
                "turn": "t",
                "entry": "e",
                "exit": "x",
                "provenance_id": "run-minimal",
            }
        ],
        "beats": [
            {
                "id": B1,
                "kind": "beat",
                "parent_id": SC_ID,
                "order": 0,
                "beat_kind": "hook",
                "summary": "林晚看见体检报告异常",
                "function": "推动",
                "emotion": {"valence": 0.3, "arousal": 0.4},
                "est_duration_s": 14,
                "brand_moment_id": None,
                "provenance_id": "run-minimal",
            },
            {
                "id": B2,
                "kind": "beat",
                "parent_id": SC_ID,
                "order": 1,
                "beat_kind": "setup",
                "summary": "陈经理催她签字",
                "function": "推动",
                "emotion": {"valence": 0.4, "arousal": 0.5},
                "est_duration_s": 16,
                "brand_moment_id": None,
                "provenance_id": "run-minimal",
            },
            {
                "id": B3,
                "kind": "beat",
                "parent_id": SC_ID,
                "order": 2,
                "beat_kind": "escalation",
                "summary": "她发现同一杯茶两种说法",
                "function": "升级",
                "emotion": {"valence": 0.6, "arousal": 0.6},
                "est_duration_s": 20,
                "brand_moment_id": None,
                "provenance_id": "run-minimal",
            },
        ],
        "lines": [
            {
                "id": "01M04TVA5Z74ZZKYYJRFWXFCA0",
                "kind": "line",
                "parent_id": B1,
                "order": 0,
                "line_type": "dialogue",
                "character_id": C1,
                "text": "这杯茶，不额外加蔗糖。",
                "subtext": "",
                "delivery": "",
                "is_brand_line": False,
                "provenance_id": "run-minimal",
            },
            {
                "id": "01M04TVA5Z74ZZKYYJRFWXFCA1",
                "kind": "line",
                "parent_id": B2,
                "order": 0,
                "line_type": "dialogue",
                "character_id": C2,
                "text": "先签字好吗？",
                "subtext": "",
                "delivery": "",
                "is_brand_line": False,
                "provenance_id": "run-minimal",
            },
        ],
        "characters": [
            {
                "id": C1,
                "name": "林晚",
                "role": "customer_proxy",
                "want": "确认报告",
                "need": "被理解",
                "voice_notes": "短句",
                "voice_tics": [],
                "provenance_id": "run-minimal",
            },
            {
                "id": C2,
                "name": "陈经理",
                "role": "ally",
                "want": "签字",
                "need": "效率",
                "voice_notes": "命令式",
                "voice_tics": [],
                "provenance_id": "run-minimal",
            },
        ],
        "locations": [
            {
                "id": LOC,
                "name": "办公室",
                "interior": True,
                "description": "",
                "cost_tier": "free",
                "shoot_notes": "",
            }
        ],
        "chapters": [
            {
                "id": "01M04TVA5Z74ZZKYYJRFWXFC9H",
                "episode_id": E_ID,
                "order": 0,
                "title": "第1章 一杯茶",
                "paragraphs": [
                    "林晚把体检报告翻了个底朝天，血糖那栏的箭头让她心里一沉。",
                    "陈经理站在门口催促，手里攥着一份要她签字的文件。",
                    "窗外的光打下来，她忽然发现：同一杯茶，怎么会有两种说法。",
                ],
                "anchor_map": [
                    {"paragraph_index": 0, "beat_id": B1, "line_ids": []},
                    {"paragraph_index": 1, "beat_id": B2, "line_ids": []},
                    {"paragraph_index": 2, "beat_id": B3, "line_ids": []},
                ],
                "provenance_id": "run-minimal",
            }
        ],
        "provenance": [],
    }


def test_chapter_paragraphs_anchored_to_beats():
    paras = render_chapter(_minimal_ir()["chapters"][0])
    assert [p.node_id for p in paras] == [B1, B2, B3]
    assert next(p.text for p in paras) == "林晚把体检报告翻了个底朝天，血糖那栏的箭头让她心里一沉。"


def test_docx_roundtrip_restores_100_percent_node_ids(tmp_path):
    """渲染 → 读回 → 100% 恢复 node_id（T-08 核心验收）。"""
    ir = _minimal_ir()
    paras = render_chapter(ir["chapters"][0])
    path = tmp_path / "novel.docx"
    render_docx(paras, path)

    back = read_docx_anchors(path)
    expected = [
        (B1, "林晚把体检报告翻了个底朝天，血糖那栏的箭头让她心里一沉。"),
        (B2, "陈经理站在门口催促，手里攥着一份要她签字的文件。"),
        (B3, "窗外的光打下来，她忽然发现：同一杯茶，怎么会有两种说法。"),
    ]
    restored = [(p.node_id, p.text) for p in back]
    assert restored == expected
    # 100% 锚定
    assert all(node is not None for node, _ in restored)


def test_render_all_produces_manifest_and_anchors(tmp_path):
    ir = _minimal_ir()
    manifest = render_all(ir, tmp_path / "out")
    assert manifest["anchors"]["coverage"] == 1.0
    assert (tmp_path / "out" / "novel.txt").exists()
    assert (tmp_path / "out" / "novel.docx").exists()
    assert (tmp_path / "out" / "screenplay.fountain").exists()
    assert (tmp_path / "out" / "storyboard.csv").exists()
    assert (tmp_path / "out" / "anchors.csv").exists()
    assert (tmp_path / "out" / "manifest.json").exists()
    # 从渲染出的 docx 读回锚点，仍能 100% 恢复
    back = read_anchors_from_docx(tmp_path / "out" / "novel.docx")
    assert [p.node_id for p in back] == [B1, B2, B3]


def test_fountain_renders_scene_and_dialogue():
    text = render_fountain(_minimal_ir())
    assert "INT. 办公室 - DAY" in text
    assert "林晚" in text
    assert "这杯茶，不额外加蔗糖。" in text


def test_storyboard_csv_rows():
    csv_text = render_storyboard(_minimal_ir())
    assert csv_text.startswith("episode,scene,beat,beat_kind")
    assert "hook" in csv_text
    assert f"{B1}" not in csv_text  # 行内不含裸 node_id（只含序号）


@pytest.mark.golden
def test_fountain_snapshot(snapshot):
    """syrupy 快照：渲染输出稳定（T-08 的 golden 回归）。"""
    assert render_fountain(_minimal_ir()) == snapshot
