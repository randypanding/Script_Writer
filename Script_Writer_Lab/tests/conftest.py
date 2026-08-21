"""pytest 全局配置:--run-llm 开关(默认跳过真实 API 测试)。"""
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-llm", action="store_true", default=False, help="运行需要真实 API 的测试")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-llm"):
        return
    skip = pytest.mark.skip(reason="需要 --run-llm")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)
