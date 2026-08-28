"""编译 Pass（p0..p7）。编排 = 纯 Python 函数 + @cached_pass（AGENTS.md §2）。

每个 Pass 是一个 DSPy Module（GEPA 的优化对象），但其 LLM 出口必须经
`src/nsc/runtime/models.py` 的路由（AGENTS.md §2 硬约束）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import dspy
import yaml
from ulid import ULID

from nsc.runtime.cache import cached_pass
from nsc.runtime.provenance import RunRecord, RunsStore

__all__ = [
    "PassContext",
    "PassFailure",
    "assemble_context",
    "cached_pass",
    "contract_text",
    "generate_json",
    "new_id",
    "optional_json",
    "with_diag",
]

_CONTRACTS_PATH = Path("spec/passes/contracts.yaml")


def _contracts() -> dict[str, Any]:
    """SW-03 / ADR-0015：Pass 契约文案真相在 spec/passes/contracts.yaml（资产层）。

    每次调用重读（文件小、调用频率低）：进程内缓存会让同进程的 spec 编辑
    读到陈旧契约（review 修正）。
    """
    try:
        return yaml.safe_load(_CONTRACTS_PATH.read_text("utf-8")) or {}
    except OSError as e:
        raise PassFailure(None, f"契约资产不可读：{_CONTRACTS_PATH}（{e}）") from e


def contract_text(pass_name: str, key: str) -> str:
    """读一个 Pass 的契约文案；含 ${name} 占位（string.Template），由调用方填充。

    文件或键缺失即 PassFailure（fail fast，review 修正）：契约缺失意味着资产
    打包/键名损坏，静默降级为空串会把格式约束整个丢给模型。
    """
    section = _contracts().get(pass_name)
    if section is None or key not in section:
        raise PassFailure(
            None,
            f"spec/passes/contracts.yaml 缺少 {pass_name}.{key}；契约资产不完整，"
            "请检查文件是否被截断或键名拼写。",
        )
    return str(section[key])


def with_diag(inputs: dict[str, Any], fragment: dict[str, Any]) -> dict[str, Any]:
    """把重试诊断（_previous_failure）从 fragment 转发进 LLM 输入（D13 反馈驱动再生成）。"""
    diag = str(fragment.get("_previous_failure", "") or "")
    return {**inputs, "_previous_failure": diag} if diag else inputs


def assemble_context(
    ctx: Any,
    *,
    p1_current: str,
    prev_summary: str,
    facts: list[str],
    rag: list[str],
    refs: list[tuple[str, str]],
) -> tuple[str, int, str, list[str]]:
    """SW-06 / ADR-0018：把 P2-P4 层与 P5 参考层过 nsc.context.assemble 预算装配。

    - p1_current：不可裁剪的"当前内容"锚（P1）；
    - facts：逐条序列化后的 fact 串（P3），返回存活条数（前缀式）；
    - rag：检索参考（P4 整层一次判定），返回存活文本（丢弃则空串）；
    - refs：(输入键, 文本) 参考层（P5 低保），返回存活键列表（前缀式）。
    预算缺省 32768 足够大 → 全存活，输出与输入逐字节等价（原行为）。
    """
    from nsc.context import assemble

    cfg = (ctx.profile.get("context") or {}) if isinstance(ctx.profile, dict) else {}
    res = assemble(
        p0_system="",
        p1_current=p1_current,
        p2_prev_summary=prev_summary,
        p3_facts=facts,
        p4_rag=rag,
        p5_bible=[text for _key, text in refs],
        budget=int(cfg.get("budget", 32768)),
        core_guarantee=int(cfg.get("core_guarantee", 400)),
    )
    layers = {lay.name: lay.text for lay in res.layers}

    n_facts = 0
    acc = ""
    p3_text = layers.get("P3", "")
    for fs in facts:
        cand = fs if not acc else acc + "\n" + fs
        if p3_text.startswith(cand):
            acc, n_facts = cand, n_facts + 1
        else:
            break

    kept_keys: list[str] = []
    tail = layers.get("P5", "")
    for key, text in refs:
        if text and tail.startswith(text):
            kept_keys.append(key)
            tail = tail[len(text) + 1 :]  # 跳过层内 join 分隔符 "\n"
        else:
            break

    return layers.get("P2", ""), n_facts, layers.get("P4", ""), kept_keys


class PassFailure(Exception):  # noqa: N818  名字由 docs/HANDOFF_STRONG_MODEL.md 约定
    """结构性失败：禁止静默降级（AGENTS.md §7）。携带 node_id 供二分定位。"""

    def __init__(self, node_id: str | None, reason: str) -> None:
        self.node_id = node_id
        self.reason = reason
        super().__init__(f"[{node_id or '-'}] {reason}")


def new_id() -> str:
    return str(ULID())


#: 进缓存键的 spec 域（SW-02）：只含影响生成结构的域；checks 由 ruleset_ver 覆盖。
CACHE_SPEC_DOMAINS = ("ir", "passes")
#: 个别 Pass 的额外缓存依赖域（review 修正）：p5 的 self-check 经
#: nsc.revise.revision_brief 读 spec/rules/L3_canonical（VOICE RULES 五节），
#: 该域编辑必须使 p5 缓存失效（ruleset_ver 只覆盖 spec/checks，管不到这里）。
PASS_EXTRA_SPEC_DOMAINS: dict[str, tuple[str, ...]] = {"p5_dialogue": ("rules",)}


@dataclass
class PassContext:
    """一次编译的运行上下文。所有版本号集中在这里，缓存键由 cache_versions 给出。"""

    profile: dict[str, Any]
    brand: dict[str, Any]
    router: Any
    store: RunsStore
    ruleset_ver: str
    spec_sha: str
    brief: dict[str, Any] = field(default_factory=dict)
    promptset_ver: str = "seed"
    seed: int | None = 1
    out_dir: Path = Path("out")
    run_id: str = ""
    #: SW-02 分域 spec 指纹（domain → sha12）。空 = 旧语义（缓存键用全量 spec_sha）。
    spec_shas: dict[str, str] = field(default_factory=dict)
    #: T-16 检索服务（None = 禁用检索；set 后 pipeline 会往 p1/p2/p3/p5 注入 retrieved_cases）
    retrieval: Any = None

    def tier_of(self, pass_name: str) -> str:
        return self.profile.get("model_tiers", {}).get(pass_name, "tier_bulk")

    def _model_cfg(self, pass_name: str) -> dict[str, Any]:
        if self.router is None:
            return {}
        return self.router.resolve(self.tier_of(pass_name))

    def scoped_spec_sha(self, pass_name: str = "") -> str:
        """缓存键用 spec 指纹：分域只取相关域（含该 Pass 的额外依赖域）。

        任一必需域缺失（半套指纹）时回退全量 spec_sha——宁可多失效，不可少失效
        （review 修正：空域拼出的 "ir:|passes:" 会静默削弱缓存失效条件）。
        """
        domains = CACHE_SPEC_DOMAINS + PASS_EXTRA_SPEC_DOMAINS.get(pass_name, ())
        if not self.spec_shas or any(d not in self.spec_shas for d in domains):
            return self.spec_sha
        return "|".join(f"{d}:{self.spec_shas[d]}" for d in domains)

    def cache_versions(self, pass_name: str) -> dict[str, Any]:
        cfg = self._model_cfg(pass_name)
        return {
            "promptset_ver": self.promptset_ver,
            "profile_ver": str(self.profile.get("version", "")),
            "brand_ver": str(self.brand.get("version", "")),
            "ruleset_ver": self.ruleset_ver,
            "model_id": str(cfg.get("model", "none")),
            "temperature": float(cfg.get("temperature", 0.0)),
            "seed": self.seed,
            "spec_sha": self.scoped_spec_sha(pass_name),
        }

    def record_run(
        self,
        pass_name: str,
        input_hash: str,
        cache_hit: int,
        usage: dict[str, Any],
        wall_ms: int,
    ) -> str:
        cfg = self._model_cfg(pass_name)
        self.store.record(
            RunRecord.new(
                run_id=self.run_id or new_id(),
                pass_name=pass_name,
                spec_sha=self.spec_sha,
                profile_ver=str(self.profile.get("version", "")),
                brand_ver=str(self.brand.get("version", "")),
                ruleset_ver=self.ruleset_ver,
                promptset_ver=self.promptset_ver,
                model_id=str(cfg.get("model", "none")),
                temperature=float(cfg.get("temperature", 0.0)),
                seed=self.seed,
                input_hash=input_hash,
                cache_hit=cache_hit,
                tokens_in=int(usage.get("tokens_in", 0)),
                tokens_out=int(usage.get("tokens_out", 0)),
                cost_usd=float(usage.get("cost_usd", 0.0)),
                wall_ms=wall_ms,
                langfuse_trace_id=str(usage.get("trace_id", "")),
            )
        )
        return self.run_id


class DSPyPass(dspy.Module):
    """把一个 dspy.Signature 落实为可运行 Module 的基类。

    指令来源优先级：prompts/<pass>.json（GEPA 产物） > signature docstring（种子）。
    """

    signature: type[dspy.Signature]
    pass_name: str = ""
    #: IR 1.1（ADR-0012）可缺省输出字段：旧 prompt/桩未返回时不判缺失，由 Pass 落默认空。
    optional_outputs: tuple[str, ...] = ()

    def forward(self, ctx: PassContext, fragment: dict[str, Any]) -> dict[str, Any]:
        return generate_json(ctx, self.pass_name, self.signature, fragment, self.optional_outputs)


def _load_prompt(pass_name: str) -> str:
    p = Path("prompts") / f"{pass_name}.json"
    if p.exists():
        data = json.loads(p.read_text("utf-8"))
        return str(data.get("instructions", ""))
    return ""


def parse_json_loose(text: str, pass_name: str) -> dict[str, Any]:
    """容错解析模型输出：平衡括号扫描提取 JSON 对象（兼容推理内容夹带）。失败即 PassFailure。"""
    from nsc.runtime.json_extract import extract_json

    data = extract_json(text)
    if not isinstance(data, dict):
        raise PassFailure(None, f"{pass_name} 输出不是合法 JSON 对象")
    return data


def parse_winner(text: str, n: int) -> int:
    """从重排回复提取 winner 下标（R3/R4 监制重排共用）；解析失败/越界 → 0（保首候选，不退化）。"""
    import re as _re

    m = _re.search(r"\{[^{}]*\}", text or "", _re.DOTALL)
    if not m:
        return 0
    try:
        w = int(json.loads(m.group(0)).get("winner", 0))
    except (ValueError, TypeError, AttributeError):
        return 0
    return w if 0 <= w < n else 0


def generate_json(
    ctx: PassContext,
    pass_name: str,
    signature: type[dspy.Signature],
    inputs: dict[str, Any],
    optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    """经路由调用 LLM，按 signature 的输出字段解析 JSON。结构性失败抛 PassFailure。

    `optional` 里的输出字段可缺省（ADR-0012）：旧 prompt/桩不返回时不判失败，
    由调用方用 optional_json 读取并落默认空。
    """
    instructions = _load_prompt(pass_name) or (signature.__doc__ or "").strip()
    out_fields: dict[str, str] = {}
    for name, f in signature.output_fields.items():
        extra: Any = getattr(f, "json_schema_extra", None) or {}
        out_fields[name] = str(extra.get("desc", ""))
    _inner_example = json.dumps({"items_json": json.dumps([{"name": "甲"}], ensure_ascii=False)})
    system = (
        f"{instructions}\n\n"
        "只输出一个 JSON 对象，键与含义如下（值为字符串，列表/对象请序列化为 JSON 字符串）：\n"
        + json.dumps(out_fields, ensure_ascii=False, indent=2)
        + "\n嵌套序列化必须保证整体可被 json.loads 解析，内层引号要转义。正确示例："
        + _inner_example
    )
    user = json.dumps(inputs, ensure_ascii=False)
    res = ctx.router.complete(
        ctx.tier_of(pass_name),
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        json_mode=True,
        seed=ctx.seed,
    )
    data = parse_json_loose(res.text, pass_name)
    missing = [k for k in out_fields if k not in data and k not in optional]
    if missing:
        raise PassFailure(None, f"{pass_name} 输出缺少字段 {missing}")
    data["_usage"] = {
        "tokens_in": res.tokens_in,
        "tokens_out": res.tokens_out,
        "cost_usd": res.cost_usd,
        "trace_id": res.trace_id,
    }
    return data


def inner_json(value: Any, pass_name: str, field_name: str) -> Any:
    """输出字段里的嵌套 JSON 字符串 → Python 对象。坏串先试平衡扫描修复；失败诊断可直接喂重试。"""
    if isinstance(value, (list, dict)):
        return value
    text = str(value or "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        from nsc.runtime.json_extract import extract_json

        repaired = extract_json(text)
        if isinstance(repaired, (list, dict)):
            return repaired
        raise PassFailure(
            None,
            f"{pass_name}.{field_name} 不是合法 JSON：{e}；原始开头：{text[:100]!r}。"
            f"请重新输出完整且转义正确的 {field_name}。",
        ) from e


def optional_json(out: Any, key: str, pass_name: str) -> Any:
    """可缺省输出字段的安全读取（ADR-0012）：缺省/空串 → None，其余按 inner_json 解析。

    `out` 是 Module 调用产物（dspy Prediction，鸭子类型 dict）；返回 None 时调用方落
    默认空表，这样旧 prompt/桩的省略路径不会被判失败。
    """
    v = out.get(key)
    return inner_json(v, pass_name, key) if v else None
