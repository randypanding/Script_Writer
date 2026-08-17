"""T-31 多源修订 brief 合成器测试（方案 §6.2 五节规格）。

全确定性，无 LLM 调用。VOICE RULES 用 monkeypatch 隔离 spec/rules/L3_canonical，
不依赖仓库当前资产状态。
"""

from __future__ import annotations

import re

import yaml

import nsc.revise.revision_brief as rb
from nsc.revise.revision_brief import BriefSources, brief_sections, brief_type, build_brief

_SECTIONS = ["## PROBLEM", "## WHAT TO KEEP", "## WHAT TO CHANGE", "## VOICE RULES", "## TARGET"]


def _f(
    rule_id: str = "DLG-007",
    severity: str = "warn",
    message: str = "场景 S1 有 6 条对白却没有任何动作行。",
    fix_hint: str = "把其中一条'他说'改写成动作节拍",
    domain: str = "dialogue",
    tags: tuple[str, ...] = (),
) -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "fix_hint": fix_hint,
        "domain": domain,
        "tags": list(tags),
    }


def _body(brief: str, title: str) -> str:
    """标题行与下一节标题之间的正文（空节返回 ''）。"""
    start = brief.index(title) + len(title)
    rest = [brief.index(s) for s in _SECTIONS if brief.index(s) > start]
    return brief[start : min(rest) if rest else len(brief)].strip("\n")


# ---------------------------------------------------------------- 五节结构顺序
def test_five_sections_in_fixed_order() -> None:
    brief = build_brief(BriefSources(checker_findings=[_f()]))
    assert brief.startswith("# Revision Brief (FIX)\n\n## PROBLEM")
    pos = [brief.index(s) for s in _SECTIONS]
    assert pos == sorted(pos), "五节顺序必须固定：PROBLEM→KEEP→CHANGE→VOICE→TARGET"


def test_block_finding_is_first_line_of_problem() -> None:
    findings = [
        _f(rule_id="DLG-007", severity="warn"),
        _f(rule_id="BM-001", severity="block", message="第 3 集有 4 处品牌植入，超过预算 2 处。"),
    ]
    brief = build_brief(BriefSources(checker_findings=findings))
    problem = _body(brief, "## PROBLEM")
    assert problem.splitlines()[0] == "- [BM-001] 第 3 集有 4 处品牌植入，超过预算 2 处。"
    assert "DLG-007" not in problem, "warn 不得进 PROBLEM（去 WHAT TO CHANGE）"


def test_empty_findings_gives_empty_problem_and_no_error() -> None:
    brief = build_brief(BriefSources(checker_findings=[]))
    assert _body(brief, "## PROBLEM") == ""
    assert brief.startswith("# Revision Brief (FIX)")


# ---------------------------------------------------------------- brief_type 判定表
def test_brief_type_score_thresholds() -> None:
    assert brief_type(0.4, []) == "REWRITE"
    assert brief_type(0.5, []) == "REWRITE"  # 边界：<=0.5
    assert brief_type(0.6, []) == "FIX"
    assert brief_type(0.7, []) == "FIX"  # 边界：<=0.7
    assert brief_type(0.71, []) == "POLISH"
    assert brief_type(0.9, []) == "POLISH"


def test_brief_type_rule_driven_when_score_none() -> None:
    for rid in ("PRS-003", "PRS-004", "PRS-015"):
        assert brief_type(None, [_f(rule_id=rid)]) == "COMPRESS", rid
    assert brief_type(None, [_f(rule_id="X-999", tags=("density",))]) == "COMPRESS"
    for rid in ("PRS-001", "PRS-002", "PRS-012"):
        assert brief_type(None, [_f(rule_id=rid)]) == "TIGHTEN", rid
    assert brief_type(None, []) == "FIX"
    assert brief_type(None, [_f(rule_id="DLG-007")]) == "FIX"


def test_brief_type_score_takes_precedence_over_rules() -> None:
    assert brief_type(0.3, [_f(rule_id="PRS-003")]) == "REWRITE"
    assert brief_type(0.9, [_f(rule_id="PRS-003")]) == "POLISH"


# ---------------------------------------------------------------- TARGET 字数公式
def test_target_compress_is_0_55x() -> None:
    brief = build_brief(
        BriefSources(checker_findings=[_f(rule_id="PRS-003")], target_text_chars=1200)
    )
    assert brief.startswith("# Revision Brief (COMPRESS)")
    assert "660 字" in _body(brief, "## TARGET")  # int(1200*0.55)


def test_target_tighten_is_0_85x() -> None:
    brief = build_brief(
        BriefSources(checker_findings=[_f(rule_id="PRS-001")], target_text_chars=1200)
    )
    assert brief.startswith("# Revision Brief (TIGHTEN)")
    assert "1020 字" in _body(brief, "## TARGET")  # int(1200*0.85)


def test_target_plain_types_keep_chars() -> None:
    for score, kind in ((0.4, "REWRITE"), (0.6, "FIX"), (0.9, "POLISH")):
        brief = build_brief(
            BriefSources(checker_findings=[], judge={"score": score}, target_text_chars=1200)
        )
        assert brief.startswith(f"# Revision Brief ({kind})")
        assert "约 1200 字" in _body(brief, "## TARGET")


# ---------------------------------------------------------------- WHAT TO CHANGE / KEEP
def test_change_numbered_list_with_message_and_fix_hint() -> None:
    findings = [
        _f(),
        _f(rule_id="DLG-005", severity="info", message="重复台词 2 条。", fix_hint=""),
    ]
    brief = build_brief(BriefSources(checker_findings=findings))
    change = _body(brief, "## WHAT TO CHANGE")
    assert (
        change.splitlines()[0]
        == "1. [DLG-007] 场景 S1 有 6 条对白却没有任何动作行。（把其中一条'他说'改写成动作节拍）"
    )
    assert "2. [DLG-005] 重复台词 2 条。" in change


def test_keep_holds_judge_strongest_and_zero_finding_note() -> None:
    judge = {
        "weakest_dimension": "naturalness",
        "strongest_sentence": "（把杯子推过去）不加糖的。",
        "score": 0.4,
    }
    brief = build_brief(BriefSources(checker_findings=[_f()], judge=judge))
    assert "把杯子推过去" in _body(brief, "## WHAT TO KEEP")
    assert "naturalness" in _body(brief, "## PROBLEM")
    # 无 findings 时 KEEP 有说明行
    zero = build_brief(BriefSources(checker_findings=[], judge=judge))
    assert "零 findings" in _body(zero, "## WHAT TO KEEP")


# ---------------------------------------------------------------- 截断行为
def test_truncation_respects_budget_keeps_block_and_marks() -> None:
    findings = [_f(rule_id="BM-001", severity="block", message="植入超预算" * 5, fix_hint="")]
    findings += [
        _f(
            rule_id=f"W-{i:03d}",
            severity="warn",
            message="很长的诊断信息" * 30,
            fix_hint="很长的修复提示" * 20,
        )
        for i in range(20)
    ]
    findings += [
        _f(rule_id=f"I-{i:03d}", severity="info", message="说明性信息" * 20, fix_hint="")
        for i in range(10)
    ]
    brief = build_brief(BriefSources(checker_findings=findings), max_chars=1500)
    assert len(brief) <= 1500
    assert "[BM-001]" in brief, "截断不得删 PROBLEM 的 block"
    m = re.search(r"已截断 (\d+) 条", brief)
    assert m and int(m.group(1)) >= 1
    assert "…(已截断" in brief


def test_no_truncation_marker_when_within_budget() -> None:
    brief = build_brief(BriefSources(checker_findings=[_f()]))
    assert "已截断" not in brief


# ---------------------------------------------------------------- VOICE RULES
def test_voice_rules_empty_dir_renders_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rb, "_L3_DIR", tmp_path)
    brief = build_brief(BriefSources(checker_findings=[_f()]))
    assert _body(brief, "## VOICE RULES") == "无"


def test_voice_rules_load_form_prompt_rules(tmp_path, monkeypatch) -> None:
    (tmp_path / "R3-0001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "R3-0001",
                "form": "check",
                "target": "spec/checks/x.yaml",
                "rationale": "理由甲",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "R3-0002.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "R3-0002",
                "form": "prompt",
                "target": "台词要口语化，禁止宣读参数。",
                "rationale": "念参数太假",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rb, "_L3_DIR", tmp_path)
    brief = build_brief(BriefSources(checker_findings=[_f()]))
    voice = _body(brief, "## VOICE RULES")
    assert "台词要口语化，禁止宣读参数。" in voice
    assert "念参数太假" in voice
    assert "spec/checks/x.yaml" not in voice, "form==check 的 target 是文件路径，不得混入"
    assert "理由甲" not in voice


def test_voice_rules_fallback_to_rationales_without_form_field(tmp_path, monkeypatch) -> None:
    (tmp_path / "R3-0001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "R3-0001",
                "rationale": "开场 3 秒内必须给出具体冲突。",
                "target": "spec/checks/y.yaml",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rb, "_L3_DIR", tmp_path)
    brief = build_brief(BriefSources(checker_findings=[_f()]))
    voice = _body(brief, "## VOICE RULES")
    assert "开场 3 秒内必须给出具体冲突。" in voice
    assert "spec/checks/y.yaml" not in voice


def test_voice_rules_broken_yaml_renders_none(tmp_path, monkeypatch) -> None:
    (tmp_path / "R3-0001.yaml").write_text("id: [unclosed", encoding="utf-8")
    monkeypatch.setattr(rb, "_L3_DIR", tmp_path)
    brief = build_brief(BriefSources(checker_findings=[_f()]))
    assert _body(brief, "## VOICE RULES") == "无"


# ---------------------------------------------------------------- brief_sections（gepa 消费口径）
def test_brief_sections_exposes_problem_and_change_bodies() -> None:
    findings = [
        _f(rule_id="BM-001", severity="block", message="植入超预算"),
        _f(rule_id="DLG-007", severity="warn", message="对白墙"),
    ]
    secs = brief_sections(BriefSources(checker_findings=findings))
    assert secs["PROBLEM"] == "- [BM-001] 植入超预算"
    assert secs["WHAT TO CHANGE"] == "1. [DLG-007] 对白墙（把其中一条'他说'改写成动作节拍）"
    assert "## PROBLEM" not in secs["PROBLEM"], "sections 返回正文，不带节标题"
