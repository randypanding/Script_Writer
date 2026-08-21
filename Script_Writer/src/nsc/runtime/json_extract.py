"""容错 JSON 提取（推理模型输出适配）。

推理模型（LongCat-2.0）有时把最终 JSON 写进思考内容、或在答案前后夹杂自然语言。
贪心正则 ``\\{.*\\}`` 在多花括号文本上会跨块匹配而失败，这里用**平衡括号扫描**
逐候选提取（感知字符串内的花括号与转义），返回第一个能解析的 dict/list。
纯机械解析，不含任何业务判断。
"""

from __future__ import annotations

from typing import Any


def _balanced_candidates(text: str) -> list[str]:
    """按出现顺序产出所有平衡的 {...} 候选（最长优先于嵌套子块）。"""
    out: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        j = i
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[i : j + 1])
                    i = j  # 外层匹配完后从该位置继续找兄弟块
                    break
            j += 1
        i += 1
    return out


def extract_json(text: str) -> Any:
    """从任意文本提取首个合法 JSON 对象/数组；失败返回 None。"""
    import json

    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for cand in _balanced_candidates(t):
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, (dict, list)):
            return data
    return None
