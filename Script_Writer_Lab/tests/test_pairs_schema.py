"""L-06 · 偏好对 schema。实现目标: src/lab/pairs.py
契约: spec/schemas/pairs.schema.yaml(本文件在实现前必须为红)"""
from pathlib import Path

import jsonschema
import pytest
import yaml
from lab.pairs import build_pair

SCHEMA = yaml.safe_load(
    (Path(__file__).parents[1] / "spec/schemas/pairs.schema.yaml").read_text(encoding="utf-8")
)


def _pair(**kw):
    defaults = {
        "axis": "prose_craft",
        "a_text": "语料原文片段(构造上的优胜方)。",
        "b_text": "注入 AI 套话后的退化片段,按定义更差。",
        "label": "a_win",
        "construction": {"kind": "corpus_degraded", "op_id": "D05_inject_slop", "severity": 1,
                         "source_script_id": "scr:00000000000000000000000001"},
        "split": "exam",
    }
    defaults.update(kw)
    return build_pair(**defaults)


def test_pair_validates_against_schema():
    jsonschema.validate(_pair(), SCHEMA)


def test_illegal_label_rejected():
    with pytest.raises(ValueError):
        _pair(label="maybe_a")


def test_illegal_split_rejected():
    with pytest.raises(ValueError):
        _pair(split="test")


def test_degraded_pair_requires_op_id():
    with pytest.raises(ValueError):
        _pair(construction={"kind": "corpus_degraded"})
