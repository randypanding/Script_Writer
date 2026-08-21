"""声明式规则解释器（D7）。目标 ≤300 行。

不要在这里写任何业务判断。业务判断在 spec/checks/**.yaml。
借鉴：JMESPath 做 select、simpleeval 做 assert（docs/BORROW_MAP.md #22）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import jmespath

from . import registry
from .registry import FUNCS, SafeEval

Severity = Literal["block", "warn", "info"]

#: `@.__ctx.a.b.c` → 名字 `__ctxN`，值从 ctx 解析。避免在 assert 里写 dict 下标。
_CTX_RE = re.compile(r"@\.__ctx\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")
_STAGE_ORDER = ["after_p2", "after_p3", "after_p4", "after_p5", "after_p6", "final"]


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str  # 已渲染，遵循 DSL §5，可直接进 GEPA feedback
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
    errors: list[str] = field(default_factory=list)  # 规则本身写错了（select/assert 报错）

    @property
    def blocked(self) -> bool:
        return any(f.severity == "block" for f in self.findings)

    def as_feedback_text(self, max_chars: int = 2400) -> str:
        """给 GEPA / 给 Pass 自检用。block 优先，同级按 domain 分组。见 gepa_metric.py。"""
        blocks = [f for f in self.findings if f.severity == "block"]
        warns = [f for f in self.findings if f.severity == "warn"]
        infos = [f for f in self.findings if f.severity == "info"]
        parts = []
        for group in (blocks, warns, infos):
            if not group:
                continue
            header = (
                "【必须修正】"
                if group is blocks
                else ("【建议】" if group is warns else "【说明】")
            )
            group = sorted(group, key=lambda f: f.domain)
            lines = [f"- [{f.rule_id}] {f.message}" for f in group]
            parts.append(header + "\n" + "\n".join(lines))
        text = "\n\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(截断)"
        return text


class RuleSet:
    """加载 spec/checks/**.yaml，按 profile/industry/brand 过滤。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.rules: list[dict[str, Any]] = []
        self.rules_skipped = 0

    @classmethod
    def load(
        cls,
        root: Path = Path("spec/checks"),
        *,
        profile_id: str,
        industry: str,
        brand_id: str,
        stage: str,
        enabled_domains: list[str],
    ) -> RuleSet:

        rs = cls(root)
        req_stage = _STAGE_ORDER.index(stage) if stage in _STAGE_ORDER else len(_STAGE_ORDER)
        files = sorted(p for p in root.rglob("*.yaml") if not p.name.startswith("_"))
        for p in files:
            for doc in _load_docs(p):
                r = doc
                if not r.get("id"):
                    continue
                if r.get("status", "active") != "active":
                    rs.rules_skipped += 1
                    continue
                if r.get("domain") not in enabled_domains:
                    continue
                if r.get("stage") in _STAGE_ORDER and _STAGE_ORDER.index(r["stage"]) > req_stage:
                    continue
                scope = r.get("scope") or {}
                if scope.get("profiles") and profile_id not in scope["profiles"]:
                    continue
                if scope.get("industries") and industry not in scope["industries"]:
                    continue
                if scope.get("brands") and brand_id not in scope["brands"]:
                    continue
                rs.rules.append(r)
        rs.rules.sort(key=lambda r: r["id"])
        return rs

    @property
    def version(self) -> str:
        """ruleset_ver = 所有生效规则文件内容的 sha256 前 12 位。进 provenance。"""
        h = hashlib.sha256()
        for p in sorted(self.root.rglob("*.yaml")):
            if not p.name.startswith("_"):
                h.update(p.read_bytes())
        return h.hexdigest()[:12]


def _load_docs(p: Path) -> list[dict]:
    import yaml

    text = p.read_text("utf-8")
    if text.lstrip().startswith("---"):
        return [d for d in yaml.safe_load_all(text) if d]
    return [yaml.safe_load(text)]


def _resolve_ctx(expr: str, ctx: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """把 `@.__ctx.a.b.c` 替换成 `__ctxN`，并集出对应值。"""
    extra: dict[str, Any] = {}
    counter = [0]

    def _sub(m: re.Match) -> str:
        path = m.group(1).split(".")
        val: Any = ctx
        for key in path:
            val = val.get(key) if isinstance(val, dict) else getattr(val, key, None)
        name = f"__ctx{counter[0]}"
        counter[0] += 1
        extra[name] = val
        return name

    return _CTX_RE.sub(_sub, expr), extra


def evaluate(ruleset: RuleSet, view: dict[str, Any], ctx: dict[str, Any]) -> CheckReport:
    """对 ir.view() 执行全部规则。

    实现要点：
      1. select: jmespath.search(rule["select"], view)。结果非 list 时包成单元素 list。
      2. group_by: 对 select 结果按 jmespath 分组，每组作为一个 item。
      3. bind: 对每个 item，逐个 jmespath.search(expr, item)；以 "@.__ctx." 开头时在 ctx 上求值。
      4. assert: simpleeval，names = {item, ctx, **bind, **ctx 解析}，functions = FUNCS。
      message 用同一环境渲染 {…} 占位。
    """
    report = CheckReport(rules_evaluated=0)
    order_of_fn = _build_order_of(view)

    # `@.__ctx.*` 的解析根：规则里既引用 `@.__ctx.brand`/`compliance`（view 已注入计算好的
    # 派生字段），也引用 `@.__ctx.ir.__xxx`（view 的 `__` 计算量）。view 必须后合并，
    # 否则会被外部 ctx 的原始 brand 覆盖掉 __ 派生字段。
    root = {"ir": view, **ctx, **view}

    for rule in ruleset.rules:
        report.rules_evaluated += 1
        assert_expr = rule.get("assert", "")
        try:
            items = jmespath.search(rule.get("select", ""), view)
        except Exception as e:  # 规则写错
            report.errors.append(f"{rule['id']}: select 报错 {e}")
            continue
        if items is None:
            items = []
        if not isinstance(items, list):
            items = [items]
        # jmespath `[*].x[*].y[*]` 会层层嵌套（[[[leaf]]]），递归拍平为 leaf 项。
        items = _flatten(items)
        if rule.get("group_by"):
            try:
                items = _group_by(items, rule["group_by"])
            except Exception as e:
                report.errors.append(f"{rule['id']}: group_by 报错 {e}")
                continue
        for item in items:
            bind: dict[str, Any] = {}
            try:
                for key, expr in (rule.get("bind") or {}).items():
                    if expr.startswith("@.__ctx."):
                        bind[key] = jmespath.search(expr[len("@.__ctx.") :], root)
                    else:
                        bind[key] = jmespath.search(expr, item)
            except Exception as e:
                report.errors.append(f"{rule['id']}: bind 报错 {e}")
                continue
            names = {"item": item, "ctx": root, **bind}
            try:
                resolved_assert, extra = _resolve_ctx(assert_expr, root)
            except Exception as e:
                report.errors.append(f"{rule['id']}: ctx 解析报错 {e}")
                continue
            names.update(extra)
            registry.set_runtime(names, order_of_fn)
            try:
                passed = bool(SafeEval(names=names, functions=FUNCS).eval(resolved_assert))
            except Exception as e:
                report.errors.append(f"{rule['id']}: assert 报错 {e}")
                continue
            if passed:
                continue
            node_id = _node_id_of(item)
            finding = Finding(
                rule_id=rule["id"],
                severity=rule.get("severity", "block"),
                message=_render_message(rule.get("message", ""), names, root),
                fix_hint=rule.get("fix_hint", ""),
                node_id=node_id,
                domain=rule.get("domain", ""),
                tags=tuple(rule.get("tags", [])),
                rule_ref=rule.get("rule_ref", ""),
            )
            report.findings.append(finding)
    return report


def _flatten(xs: list[Any]) -> list[Any]:
    out: list[Any] = []
    for x in xs:
        if isinstance(x, list):
            out.extend(_flatten(x))
        else:
            out.append(x)
    return out


def _group_by(items: list[Any], expr: str) -> list[Any]:
    groups: dict[Any, list[Any]] = {}
    for it in items:
        key = jmespath.search(expr, it)
        groups.setdefault(key, []).append(it)
    return list(groups.values())


def _render_message(msg: str, names: dict[str, Any], ctx: dict[str, Any]) -> str:
    resolved, extra = _resolve_ctx(msg, ctx)
    names = {**names, **extra}

    def _sub(m: re.Match) -> str:
        expr = m.group(1)
        try:
            val = SafeEval(names=names, functions=FUNCS).eval(expr)
            return str(val)
        except Exception:
            return m.group(0)

    return re.sub(r"\{([^{}]+)\}", _sub, resolved)


def _node_id_of(item: Any) -> str | None:
    if isinstance(item, dict):
        return item.get("id")
    return getattr(item, "id", None)


def _build_order_of(view: dict[str, Any]) -> Any:
    index: dict[str, int] = {}
    for ep in view.get("episodes", []):
        for sc in ep.get("scenes", []):
            for b in sc.get("beats", []):
                if b.get("id") is not None:
                    index[b["id"]] = b.get("linear_index", -1)
    return lambda node_id: index.get(node_id, -1)
