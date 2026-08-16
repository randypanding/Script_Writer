"""声明式规则解释器（D7）。目标 ≤300 行。

不要在这里写任何业务判断。业务判断在 spec/checks/**.yaml。
借鉴：JMESPath 做 select、simpleeval 做 assert（docs/BORROW_MAP.md #22）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Severity = Literal["block", "warn", "info"]


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str            # 已渲染，遵循 DSL §5，可直接进 GEPA feedback
    fix_hint: str = ""
    node_id: str | None = None
    domain: str = ""
    tags: tuple[str, ...] = ()
    rule_ref: str = ""


@dataclass(slots=True)
class CheckReport:
    findings: list[Finding] = field(default_factory=list)
    rules_evaluated: int = 0
    rules_skipped: int = 0
    errors: list[str] = field(default_factory=list)   # 规则本身写错了（select/assert 报错）

    @property
    def blocked(self) -> bool:
        return any(f.severity == "block" for f in self.findings)

    def as_feedback_text(self, max_chars: int = 2400) -> str:
        """给 GEPA / 给 Pass 自检用。block 优先，同级按 domain 分组。见 gepa_metric.py。"""
        raise NotImplementedError("T-05")


class RuleSet:
    """加载 spec/checks/**.yaml，按 profile/industry/brand 过滤。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.rules: list[dict[str, Any]] = []

    @classmethod
    def load(
        cls, root: Path = Path("spec/checks"), *, profile_id: str, industry: str, brand_id: str,
        stage: str, enabled_domains: list[str],
    ) -> RuleSet:
        raise NotImplementedError("T-05")

    @property
    def version(self) -> str:
        """ruleset_ver = 所有生效规则文件内容的 sha256 前 12 位。进 provenance。"""
        raise NotImplementedError("T-05")


def evaluate(ruleset: RuleSet, view: dict[str, Any], ctx: dict[str, Any]) -> CheckReport:
    """对 ir.view() 执行全部规则。

    实现要点（agent 必读）：
      1. select: jmespath.search(rule["select"], view)。结果非 list 时包成单元素 list。
      2. group_by: 对 select 结果按 jmespath 求值分组，每组作为一个 item（item 为 list）。
      3. bind: 对每个 item，逐个 jmespath.search(expr, item)；expr 以 "@.__ctx." 开头时改在 ctx 上求值。
      4. assert: simpleeval.EvalWithCompoundTypes，names = {item, ctx, **bind}，functions = registry.FUNCS。
      5. message: 用与 assert 相同的求值环境渲染 {…} 占位（自实现 mini-formatter，禁止 str.format 的属性访问漏洞）。
      6. 规则自身报错 → 记入 report.errors，**不算 finding**，但 CI 视 errors 非空为失败。
      7. 每条 finding 命中时写 rule_hits 表（供 D23 指标 4 与规则退役）。
    """
    raise NotImplementedError("T-05")