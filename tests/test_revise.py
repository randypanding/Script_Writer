"""T-32 revise 模块测试：spot-fix patch 引擎 / revisionGate 三档 / 快照链 / Idea Bank。

全确定性，无 LLM 调用。
"""

from __future__ import annotations

import pytest

from nsc.revise import (
    Counts,
    Patch,
    apply_patches,
    best_snapshot,
    decide,
    deposit,
    list_ideas,
    list_snapshots,
    parse_patches,
    render_for_prompt,
    revive,
    rollback_to,
    save_snapshot,
)
from nsc.revise.patch import _find_fuzzy, _find_unique, _norm

# ---------------------------------------------------------------------------
# parse_patches
# ---------------------------------------------------------------------------


def test_parse_patches_numbered() -> None:
    out = """一些前置说明，可忽略。

--- PATCH 1 ---
TARGET_TEXT:
他推门而入，看见桌上的茶还冒着热气。

REPLACEMENT_TEXT:
他推门而入，茶几上的茶早已凉透。

--- END PATCH ---
"""
    patches = parse_patches(out)
    assert patches == [
        Patch(
            target="他推门而入，看见桌上的茶还冒着热气。",
            replacement="他推门而入，茶几上的茶早已凉透。",
        )
    ]


def test_parse_patches_unnumbered() -> None:
    out = """--- PATCH ---
TARGET_TEXT:
第一段目标
REPLACEMENT_TEXT:
第一段替换
--- END PATCH ---
--- PATCH 2 ---
TARGET_TEXT:
第二段目标
REPLACEMENT_TEXT:
第二段替换
--- END PATCH ---
"""
    patches = parse_patches(out)
    assert [p.target for p in patches] == ["第一段目标", "第二段目标"]
    assert [p.replacement for p in patches] == ["第一段替换", "第二段替换"]


def test_parse_patches_empty_target_dropped() -> None:
    out = """--- PATCH 1 ---
TARGET_TEXT:

REPLACEMENT_TEXT:
替换文
--- END PATCH ---
--- PATCH 2 ---
TARGET_TEXT:
有效目标
REPLACEMENT_TEXT:
有效替换
--- END PATCH ---
"""
    patches = parse_patches(out)
    assert patches == [Patch(target="有效目标", replacement="有效替换")]


def test_parse_patches_no_section() -> None:
    assert parse_patches("没有任何补丁的普通 LLM 输出。\n") == []
    assert parse_patches("") == []


# ---------------------------------------------------------------------------
# 两级匹配
# ---------------------------------------------------------------------------


def test_find_unique_exact_hit() -> None:
    text = "前缀。目标句子在这里。后缀。"
    assert _find_unique(text, "目标句子在这里") == (3, 3 + len("目标句子在这里"))


def test_find_unique_ambiguous_returns_none() -> None:
    text = "重复句。中间。重复句。"
    assert _find_unique(text, "重复句。") is None


def test_find_unique_miss_returns_none() -> None:
    assert _find_unique("完全不同的文本", "不存在") is None


def test_norm_collapses_whitespace() -> None:
    assert _norm("  a \n\t b  c \n") == "a b c"


def test_find_fuzzy_whitespace_hit_coordinates() -> None:
    text = "开场白。他慢慢地\n\n  走进  房间，坐下。收尾。"
    target = "他慢慢地 走进\t房间，坐下"  # 归一化后与原文同形，空白形态不同
    span = _find_fuzzy(text, target)
    assert span is not None
    s, e = span
    # 坐标映射回原文：区间内容归一化后与 target 归一化一致，且起点落在非空白字符上
    assert _norm(text[s:e]) == _norm(target)
    assert text[s] == "他"
    assert text[e - 1] == "下"  # 区间止于 target 末字符（不含其后的句号）


def test_find_fuzzy_short_target_rejected() -> None:
    assert _find_fuzzy("随便一段较长的正文内容", "短句") is None  # _norm 长度 < 10


def test_find_fuzzy_ambiguous_returns_none() -> None:
    text = "同一句话重复出现。同一句话重复出现。"
    assert _find_fuzzy(text, "同一句话 重复出现") is None


# ---------------------------------------------------------------------------
# apply_patches
# ---------------------------------------------------------------------------


def test_apply_patches_all_hit() -> None:
    content = "甲段独特文本一。乙段独特文本二。"
    patches = [
        Patch(target="甲段独特文本一", replacement="甲改"),
        Patch(target="乙段独特文本二", replacement="乙改"),
    ]
    r = apply_patches(content, patches)
    assert r.applied
    assert r.content == "甲改。乙改。"
    assert r.applied_count == 2
    assert r.skipped_count == 0
    assert r.touched_chars == len("甲段独特文本一") + len("乙段独特文本二")


def test_apply_patches_threshold_2_of_5_rejected() -> None:
    content = "甲段独特文本一。乙段独特文本二。"
    patches = [
        Patch(target="甲段独特文本一", replacement="甲改"),
        Patch(target="乙段独特文本二", replacement="乙改"),
        Patch(target="不存在一", replacement="x"),
        Patch(target="不存在二", replacement="y"),
        Patch(target="不存在三", replacement="z"),
    ]
    r = apply_patches(content, patches)
    assert not r.applied
    assert r.content == content  # 低于门槛保留原文
    assert r.applied_count == 2
    assert r.skipped_count == 3
    assert "2/5" in r.rejected_reason and "50%" in r.rejected_reason


def test_apply_patches_threshold_3_of_5_accepted() -> None:
    content = "甲段独特文本一。乙段独特文本二。丙段独特文本三。"
    patches = [
        Patch(target="甲段独特文本一", replacement="甲改"),
        Patch(target="乙段独特文本二", replacement="乙改"),
        Patch(target="丙段独特文本三", replacement="丙改"),
        Patch(target="不存在一", replacement="x"),
        Patch(target="不存在二", replacement="y"),
    ]
    r = apply_patches(content, patches)
    assert r.applied  # 3/5 = 60% ≥ 50%
    assert r.content == "甲改。乙改。丙改。"
    assert r.applied_count == 3 and r.skipped_count == 2


def test_apply_patches_single_failure_skips() -> None:
    content = "唯一目标句在这里。"
    r = apply_patches(
        content,
        [
            Patch(target="唯一目标句在这里", replacement="改后"),
            Patch(target="幽灵", replacement="g"),
        ],
    )
    assert r.applied  # 1/2 = 50% 过线
    assert r.content == "改后。"
    assert r.skipped_count == 1
    assert r.touched_chars == len("唯一目标句在这里")


def test_apply_patches_fuzzy_fallback_used() -> None:
    content = "他把杯子放下，\n转身离开了房间。"  # 原文换行
    target = "他把杯子放下， 转身离开了房间。"  # LLM 引用时写成空格：精确失败，模糊命中
    r = apply_patches(content, [Patch(target=target, replacement="他摔门而去。")])
    assert r.applied
    assert r.content == "他摔门而去。"


def test_apply_patches_empty() -> None:
    r = apply_patches("原文", [])
    assert not r.applied
    assert r.content == "原文"
    assert r.rejected_reason


# ---------------------------------------------------------------------------
# gate 三档真值表
# ---------------------------------------------------------------------------

B = Counts(block=2, warn=3, info=1, judge_score=0.6)


def test_gate_strict_improve_block() -> None:
    assert decide(B, Counts(block=1, warn=3, info=1, judge_score=0.6), "strict")


def test_gate_strict_flat_no_improve() -> None:
    a = Counts(block=2, warn=3, info=1, judge_score=0.6)
    assert not decide(B, a, "strict")
    assert decide(B, a, "lenient")  # 宽松档：不变差即放行


def test_gate_strict_judge_score_improvement_alone() -> None:
    # block/warn 持平，判官分提升 → strict 也放行
    assert decide(B, Counts(block=2, warn=3, info=1, judge_score=0.7), "strict")


def test_gate_did_not_worsen_violations() -> None:
    worse_block = Counts(block=3, warn=3, info=1, judge_score=0.9)
    worse_warn = Counts(block=2, warn=4, info=1, judge_score=0.9)
    worse_judge = Counts(block=1, warn=0, info=0, judge_score=0.5)
    for a in (worse_block, worse_warn, worse_judge):
        assert not decide(B, a, "strict")
        assert not decide(B, a, "lenient")
        assert decide(B, a, "always")  # always 无条件放行


def test_gate_judge_score_none_branches() -> None:
    b_none = Counts(block=2, warn=3, info=1, judge_score=None)
    # before 无分：judge 条款放行，宽松档通过
    assert decide(b_none, Counts(block=2, warn=3, info=1, judge_score=0.1), "lenient")
    # strict 要求真改善：block/warn 持平且 judge 非双双非 None → 拒
    assert not decide(b_none, Counts(block=2, warn=3, info=1, judge_score=0.9), "strict")
    # after 无分但 block 改善 → strict 过（did_not_worsen 的 judge 条款因 None 放行）
    assert decide(B, Counts(block=1, warn=3, info=1, judge_score=None), "strict")


def test_gate_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="mode"):
        decide(B, B, "yolo")


# ---------------------------------------------------------------------------
# snapshot 快照链
# ---------------------------------------------------------------------------


def test_snapshot_save_list_rollback_roundtrip(tmp_path) -> None:
    db = tmp_path / "state.db"
    counts = Counts(block=2, warn=1, info=0, judge_score=0.5)
    sid = save_snapshot(db, "proj1", "p3_beatsheet", '{"v": 1}', counts)
    assert len(sid) == 16

    rows = list_snapshots(db, "proj1")
    assert len(rows) == 1
    assert rows[0]["ir_json"] == '{"v": 1}'
    assert rows[0]["block"] == 2 and rows[0]["warn"] == 1
    assert rows[0]["judge_score"] == 0.5
    assert rows[0]["stage"] == "p3_beatsheet"
    assert rows[0]["created_at"]

    # 同内容重复保存 → INSERT OR REPLACE 幂等
    save_snapshot(db, "proj1", "p3_beatsheet", '{"v": 1}', counts)
    assert len(list_snapshots(db, "proj1")) == 1

    # stage 过滤与项目隔离
    save_snapshot(db, "proj1", "p5_dialogue", '{"v": 2}', counts)
    save_snapshot(db, "proj2", "p3_beatsheet", '{"v": 3}', counts)
    assert len(list_snapshots(db, "proj1")) == 2
    assert len(list_snapshots(db, "proj1", "p3_beatsheet")) == 1
    assert len(list_snapshots(db, "proj2")) == 1

    back = rollback_to(db, sid)
    assert back["ir_json"] == '{"v": 1}'
    assert back["stage"] == "p3_beatsheet"
    assert back["block"] == 2

    with pytest.raises(KeyError):
        rollback_to(db, "deadbeefdeadbeef")


def test_snapshot_best_block_dominates_warn(tmp_path) -> None:
    db = tmp_path / "state.db"
    # block=2 但 warn=0：仍输给任何 block=1 的快照（block 优先于 warn）
    save_snapshot(db, "p", "s", '{"v": 1}', Counts(block=2, warn=0, info=0, judge_score=0.99))
    save_snapshot(db, "p", "s", '{"v": 2}', Counts(block=1, warn=9, info=9, judge_score=0.1))
    best = best_snapshot(db, "p", "s")
    assert best is not None and best["ir_json"] == '{"v": 2}'


def test_snapshot_best_judge_ordering_and_null_last(tmp_path) -> None:
    db = tmp_path / "state.db"
    save_snapshot(db, "p", "s", '{"v": 1}', Counts(block=1, warn=1, info=0, judge_score=0.4))
    save_snapshot(db, "p", "s", '{"v": 2}', Counts(block=1, warn=1, info=0, judge_score=None))
    save_snapshot(db, "p", "s", '{"v": 3}', Counts(block=1, warn=1, info=0, judge_score=0.8))
    best = best_snapshot(db, "p", "s")
    assert best is not None and best["ir_json"] == '{"v": 3}'  # 分高者胜，NULL 视为 -inf


def test_snapshot_best_tie_takes_newest(tmp_path) -> None:
    db = tmp_path / "state.db"
    counts = Counts(block=1, warn=1, info=0)
    save_snapshot(db, "p", "s", '{"v": "old"}', counts)
    save_snapshot(db, "p", "s", '{"v": "new"}', counts)
    best = best_snapshot(db, "p", "s")
    assert best is not None and best["ir_json"] == '{"v": "new"}'


def test_snapshot_best_empty(tmp_path) -> None:
    assert best_snapshot(tmp_path / "state.db", "p", "s") is None


# ---------------------------------------------------------------------------
# idea_bank
# ---------------------------------------------------------------------------


def test_idea_bank_deposit_list_revive(tmp_path) -> None:
    db = tmp_path / "state.db"
    bid1 = deposit(db, "p1", "beat", "雨夜分手的 Beat", quality_note="情绪强")
    bid2 = deposit(
        db,
        "p1",
        "scene",
        "天台对峙",
        source_node_id="node_9",
        removed_run_id="run_1",
        reason="节奏拖",
    )
    deposit(db, "p2", "beat", "别的项目的素材")
    assert bid1 and bid2 and bid1 != bid2

    # 确定性：同参数 → 同 id（内容寻址，幂等）
    assert deposit(db, "p1", "beat", "雨夜分手的 Beat", quality_note="情绪强") == bid1

    ideas = list_ideas(db, "p1")
    assert len(ideas) == 2
    row2 = next(r for r in ideas if r["bank_id"] == bid2)
    assert row2["node_kind"] == "scene"
    assert row2["source_node_id"] == "node_9"
    assert row2["removed_run_id"] == "run_1"
    assert row2["reason"] == "节奏拖"
    assert row2["revived"] == 0

    revived_row = revive(db, bid1)
    assert revived_row["bank_id"] == bid1
    assert revived_row["revived"] == 1

    with pytest.raises(ValueError):
        revive(db, bid1)  # 重复复活报错
    with pytest.raises(ValueError):
        revive(db, "不存在的id")

    assert len(list_ideas(db, "p1")) == 1  # 默认不含已复活
    assert len(list_ideas(db, "p1", include_revived=True)) == 2


def test_render_for_prompt_empty_and_items() -> None:
    assert render_for_prompt([]) == ""
    ideas = [
        {"node_kind": "beat", "content": "雨夜分手的 Beat", "quality_note": "情绪强"},
        {"node_kind": "scene", "content": "天台对峙", "quality_note": ""},
        {"node_kind": "thread", "content": "第三条", "quality_note": ""},
    ]
    text = render_for_prompt(ideas, limit=2)
    assert "- (beat) 雨夜分手的 Beat [情绪强]" in text
    assert "- (scene) 天台对峙" in text  # 空 quality_note 不留空括号
    assert "第三条" not in text  # limit 生效
    assert text.strip()
