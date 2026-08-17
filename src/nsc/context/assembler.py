"""P0-P5 上下文预算竞争装配（T-33 / ADR-0013；机制来源 FicForge context_assembler/budget）。

纯确定性机制，零 LLM、零业务阈值：预算与低保额由调用方注入（profile.context.*），
本模块只实现配额公式与降级顺序。

层语义与装入/降级顺序（处理顺序 P3→P4→P2→P5，即降级牺牲顺序）：
  P0 system 指令、P1 当前集内容 —— 永不裁剪；二者装不下预算即 PassFailure。
  P3 unresolved 事实、P4 检索参考、P2 上一集摘要 —— 依次竞争剩余预算，
  每层配额 = max(0, 当前剩余 − core_guarantee)（给 P5 留低保）。
  P5 bible —— 配额 = max(core_guarantee, 当前剩余)：预算耗尽也保底 core_guarantee。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nsc.passes import PassFailure

__all__ = ["AssembleResult", "Layer", "assemble", "count_tokens"]

_LAYER_ORDER = ("P0", "P1", "P2", "P3", "P4", "P5")


def count_tokens(text: str) -> int:
    """确定性 token 估算：max(1, len(text) // 2)。

    机制常量而非业务参数：按中文 ≈2 字符/token 的保守上估，只用于预算竞争的
    相对比较，不与任何 tokenizer 对齐；空串计 1，保证层永远有非零成本。
    """
    return max(1, len(text) // 2)


@dataclass(slots=True)
class Layer:
    name: str
    text: str
    tokens: int


@dataclass(slots=True)
class AssembleResult:
    layers: list[Layer]
    used: int
    dropped: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)


def assemble(
    p0_system: str,
    p1_current: str,
    p2_prev_summary: str,
    p3_facts: list[str],
    p4_rag: list[str],
    p5_bible: list[str],
    budget: int,
    core_guarantee: int = 400,
) -> AssembleResult:
    """按预算把六层上下文装配为 Layer 列表（确定性、无 LLM）。

    规则：
      1. tokens(P0)+tokens(P1) > budget → PassFailure（不可裁剪层装不下）。
      2. P3：按序逐条装入，首条装不下即停；溢出条数记 degraded
         （"P3:丢弃N条unresolved事实"），该诊断行追加到输出尾部层文本。
      3. P4：整层一次判定，超配额即整层丢弃，dropped 记 "P4"。
      4. P2：超配额且配额>0 → 保留末尾 2*配额 字符（≈配额 token）并记 degraded；
         配额为 0 → 整层丢弃，dropped 记 "P2"。
      5. P5：配额 = max(core_guarantee, 当前剩余)；逐条装入，首条装不下即停
         （静默）。预算不足时 P5 可超出 budget——这是低保的设计语义。
      6. 输出恒按 P0→P1→P2→P3→P4→P5 排序，空文本层不输出；
         used = Σ layer.tokens。正常路径 used ≤ budget，例外仅两类：
         P5 触发低保超额、P3 溢出诊断行（≤1 行，不参与竞争）。
    """
    t0, t1 = count_tokens(p0_system), count_tokens(p1_current)
    if t0 + t1 > budget:
        raise PassFailure(
            None,
            f"P0+P1（{t0}+{t1} token）超出上下文预算 {budget}，不可裁剪层装不下；"
            "请提高 profile 的 context.budget 或缩小 P0/P1 输入。",
        )
    rem = budget - t0 - t1

    texts: dict[str, str] = {}
    if p0_system:
        texts["P0"] = p0_system
    if p1_current:
        texts["P1"] = p1_current

    dropped: list[str] = []
    degraded: list[str] = []

    # P3：unresolved 事实，按序装入直到配额（计入 join 分隔符的真实文本成本）。
    quota3 = max(0, rem - core_guarantee)
    kept3: list[str] = []
    for fact in p3_facts:
        if count_tokens("\n".join([*kept3, fact])) > quota3:
            break
        kept3.append(fact)
    if kept3:
        texts["P3"] = "\n".join(kept3)
        rem -= count_tokens(texts["P3"])
    p3_hint = ""
    if len(kept3) < len(p3_facts):
        p3_hint = f"P3:丢弃{len(p3_facts) - len(kept3)}条unresolved事实"
        degraded.append(p3_hint)

    # P4：检索参考，整层一次判定。
    if p4_rag:
        p4_text = "\n".join(p4_rag)
        if count_tokens(p4_text) > max(0, rem - core_guarantee):
            dropped.append("P4")
        else:
            texts["P4"] = p4_text
            rem -= count_tokens(p4_text)

    # P2：上一集摘要，可截尾。
    if p2_prev_summary:
        quota2 = max(0, rem - core_guarantee)
        t2 = count_tokens(p2_prev_summary)
        if t2 <= quota2:
            texts["P2"] = p2_prev_summary
            rem -= t2
        elif quota2 > 0:
            texts["P2"] = p2_prev_summary[-(quota2 * 2) :]  # 保留末尾 ≈quota2 token
            degraded.append(f"P2:截断至{quota2}token保留末尾")
            rem -= quota2
        else:
            dropped.append("P2")

    # P5：bible，低保优先于预算。
    quota5 = max(core_guarantee, rem)
    kept5: list[str] = []
    for item in p5_bible:
        if count_tokens("\n".join([*kept5, item])) > quota5:
            break
        kept5.append(item)
    if kept5:
        texts["P5"] = "\n".join(kept5)

    layers = [
        Layer(name, texts[name], count_tokens(texts[name]))
        for name in _LAYER_ORDER
        if texts.get(name)
    ]
    if p3_hint:
        if layers:
            tail = layers[-1]
            merged = tail.text + "\n" + p3_hint
            layers[-1] = Layer(tail.name, merged, count_tokens(merged))
        else:
            layers.append(Layer("P3", p3_hint, count_tokens(p3_hint)))
    return AssembleResult(layers, sum(lay.tokens for lay in layers), dropped, degraded)
