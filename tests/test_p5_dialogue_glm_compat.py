"""P5 Dialogue 对 glm-5.3-flash 占位符输出的兼容测试（T-07 回归）。

离线回放 transcript：模型输出 reasoning prose + {"lines_json": "[{...}, ...]"}。
占位符必须被检出并触发明确的 PassFailure（可诊断），不能静默接受。
"""

from __future__ import annotations

import json

import pytest

from nsc.passes import PassFailure, inner_json


def test_inner_json_accepts_real_json():
    """真实 JSON 数组/对象应正常返回。"""
    assert inner_json([{"a": 1}], "p5", "lines_json") == [{"a": 1}]
    assert inner_json({"a": 1}, "p5", "lines_json") == {"a": 1}


def test_inner_json_detects_placeholder_array():
    """占位符 `[{...}, ...]` 应被检出为非法 JSON 并给出明确诊断。"""
    with pytest.raises(PassFailure) as excinfo:
        inner_json("[{...}, ...]", "p5_dialogue", "lines_json")
    msg = str(excinfo.value)
    assert "lines_json" in msg
    assert any(kw in msg for kw in ["占位符", "骨架", "..."])


def test_inner_json_detects_placeholder_with_text():
    """`{...}` / `[...]` 骨架占位符应被检出。"""
    with pytest.raises(PassFailure) as excinfo:
        inner_json("[{...}, ...]", "p5_dialogue", "lines_json")
    msg = str(excinfo.value)
    assert "lines_json" in msg

    with pytest.raises(PassFailure) as excinfo:
        inner_json("{...}", "p5_dialogue", "lines_json")
    msg = str(excinfo.value)
    assert "lines_json" in msg


def test_inner_json_accepts_valid_json_string():
    """合法 JSON 字符串应正常解析。"""
    data = inner_json(
        json.dumps([{"beat_index": 0, "text": "测试"}], ensure_ascii=False),
        "p5_dialogue",
        "lines_json",
    )
    assert isinstance(data, list)
    assert data[0]["text"] == "测试"


def test_inner_json_detects_truncated_json():
    """被截断的 JSON 应给出截断诊断。"""
    with pytest.raises(PassFailure) as excinfo:
        inner_json('[{"beat_index": 0, "text": "', "p5_dialogue", "lines_json")
    msg = str(excinfo.value)
    assert "lines_json" in msg
