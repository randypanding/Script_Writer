from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

# 让 `spec/`（资产层，非 pip 包）可被 `import spec` 使用。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def profiles() -> dict:
    return {
        p.stem: yaml.safe_load(p.read_text("utf-8"))
        for p in Path("profiles").glob("*.yaml")
        if not p.stem.startswith("_")
    }


@pytest.fixture(scope="session")
def demo_brand() -> dict:
    return yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))


@pytest.fixture(scope="session")
def golden_ir() -> dict:
    """一份人工审定的完整 IR（6 集）。P0 的核心 fixture。
    T-06 的任务之一就是产出它并提交到 tests/fixtures/golden/demo_tea_ir.json。
    脚手架阶段尚未生成 → 跳过依赖它的用例（交给强模型/人工审定填坑）。"""
    p = FIXTURES / "golden" / "demo_tea_ir.json"
    if not p.exists():
        pytest.skip(f"golden IR 尚未生成：{p}（T-06 强模型任务）")
    return json.loads(p.read_text("utf-8"))


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m") and "llm" in str(config.getoption("-m")):
        return
    skip_llm = pytest.mark.skip(reason="需要 LLM；用 -m llm 或 nightly 运行")
    for item in items:
        if "llm" in item.keywords and not config.getoption("--run-llm", default=False):
            item.add_marker(skip_llm)


def pytest_addoption(parser):
    parser.addoption("--run-llm", action="store_true", default=False)
