"""json_extract：推理模型输出容错提取（平衡括号扫描）。"""

from __future__ import annotations

import json

from nsc.runtime.json_extract import extract_json, repair_json_quotes


def test_pure_json():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json("[1, 2]") == [1, 2]


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_with_surrounding_prose():
    text = '好的，答案如下：\n{"winner": "a", "margin": 2}\n以上是判定。'
    assert extract_json(text) == {"winner": "a", "margin": 2}


def test_nested_and_sibling_blocks():
    text = '思考 {"x": {"y": [1,2]}} 以及另一个 {"z": 3}'
    assert extract_json(text) == {"x": {"y": [1, 2]}}


def test_braces_inside_strings():
    text = '{"t": "含 {花括号} 的文本", "n": 1}'
    assert extract_json(text) == {"t": "含 {花括号} 的文本", "n": 1}


def test_reasoning_then_answer():
    text = '我需要先分析…结论是 {"score": 4.0, "cited_spans": ["原文"]}'
    assert extract_json(text) == {"score": 4.0, "cited_spans": ["原文"]}


def test_invalid_returns_none():
    assert extract_json("完全没有 JSON") is None
    assert extract_json("") is None
    assert extract_json('{"broken": ') is None


def test_repair_json_quotes_glm_r6_dialogue():
    """R6 真实故障：模型在 JSON 字符串值内直接写对白引号，未转义。"""
    raw = (
        '["三点二十，开放工位区。茶水台摆满成排大杯，甜单人数条在两块屏幕上狂跳。'
        '曹姐一巴掌拍在茶水台上，大嗓门劈开键盘声："都别敲键盘了！全楼快乐日，姐请！'
        '姐还能害你？快乐最重要！"田甜的手一抖——她屏上试喝接龙只挂两个名字，旁边甜单人数疯...姐？'
        '"小满迟疑地开口，近乎气声。半晌，那个背对着所有人的声音低得不像她："复查……约的哪天？"'
        '说完，没回头。", "没人接话。电梯门缓缓合上，只剩她半个背影，那句问话悬在电梯厅。'
        '田甜捧着试喝杯愣在原地，小满张了张嘴，一个字也没接上。"]'
    )
    repaired = repair_json_quotes(raw)
    assert repaired != raw
    data = json.loads(repaired)
    assert isinstance(data, list)
    assert len(data) == 2
    assert "都别敲键盘了" in data[0]
    assert "复查……约的哪天？" in data[0]


def test_repair_json_quotes_already_valid_passthrough():
    valid = '{"a": "hello", "b": "world"}'
    assert repair_json_quotes(valid) == valid


def test_repair_json_quotes_escaped_quotes_not_double_escaped():
    text = '{"a": "b\\"c"}'
    assert repair_json_quotes(text) == text


def test_repair_json_quotes_multiple_stray_in_one_string():
    text = '["a"b"c"]'
    repaired = repair_json_quotes(text)
    assert json.loads(repaired) == ['a"b"c']


def test_repair_json_quotes_string_terminators_not_escaped():
    text = '{"a": "b", "c": "d"}'
    assert repair_json_quotes(text) == text


def test_repair_json_quotes_empty_string():
    text = '{"a": ""}'
    assert repair_json_quotes(text) == text
