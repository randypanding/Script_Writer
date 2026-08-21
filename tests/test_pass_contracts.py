"""SW-03 Pass 契约文案资产化：p3/p5 内嵌的机械契约字符串真相搬到 spec/passes/contracts.yaml。

规则依据（AGENTS.md §2）：禁止在 prompt/代码里硬编码自然语言知识；
prompts/** 是 GEPA 生成物禁止手改，所以契约文案进 spec/ 资产层、编译时注入。
"""

from __future__ import annotations

from pathlib import Path

import yaml

_SPECS = {
    "p3_beatsheet": {
        "setup_payoffs": ["PENDING:", "下标", "slug"],
        "facts": ["resolves", "known_facts", "narrative_weight"],
        "state_changes": ["declared_state", "delta"],
    },
    "p5_dialogue": {
        "brand_must_base": ["逐字原文", "action"],
        "brand_must_example": ["${visual}", "示范动作行"],
        "product_naming": ["${canonical}", "${forbidden}"],
        "dialogue_length_target": ["${chars_lo}", "${chars_hi}", "DLG-006"],
    },
}


def test_contracts_yaml_exists_with_all_keys():
    data = yaml.safe_load(Path("spec/passes/contracts.yaml").read_text("utf-8"))
    for pass_name, keys in _SPECS.items():
        section = data.get(pass_name, {})
        for key, needles in keys.items():
            assert section.get(key), f"{pass_name}.{key} 缺失"
            for needle in needles:
                assert needle in section[key], f"{pass_name}.{key} 缺少关键片段 {needle!r}"


def test_p3_constants_sourced_from_spec():
    """p3 模块常量必须来自 spec 资产（代码里不得再各存一份漂移副本）。"""
    from nsc.passes import contract_text
    from nsc.passes import p3_beatsheet as p3

    assert contract_text("p3_beatsheet", "setup_payoffs") == p3._SP_CONTRACT
    assert contract_text("p3_beatsheet", "facts") == p3._FACT_CONTRACT
    assert contract_text("p3_beatsheet", "state_changes") == p3._SC_CONTRACT


def test_p5_contract_builders_use_spec_templates():
    from nsc.passes import p5_dialogue as p5

    base = p5._visual_contract([])
    assert "逐字原文" in base and "示范动作行" not in base
    with_visual = p5._visual_contract(["特写镜头"])
    assert '示范动作行："镜头拉近，特写镜头清晰可见。"' in with_visual

    naming = p5._naming_contract(
        {
            "products": [
                {"name": "元气茶", "canonical_name": "元气满满乌龙茶", "aliases": ["元气茶"]}
            ]
        }
    )
    assert "元气满满乌龙茶" in naming and "元气茶" in naming
    assert p5._naming_contract({"products": []}) == ""

    target = p5._dialogue_length_target(100, 200, 50, 4.5)
    assert "100-200 字" in target and "50s × 4.5" in target and "DLG-006" in target
