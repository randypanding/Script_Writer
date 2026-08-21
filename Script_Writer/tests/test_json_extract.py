"""json_extract：推理模型输出容错提取（平衡括号扫描）。"""

from __future__ import annotations

from nsc.runtime.json_extract import extract_json


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
