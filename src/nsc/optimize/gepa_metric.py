"""GEPA metric + feedback function —— 全系统的胜负手（决策文档第十五章第 3 条）。

GEPA 契约（已核实 dspy 3.x）：
    def metric(gold, pred, trace=None, pred_name=None, pred_trace=None) -> dspy.Prediction(score=..., feedback=...)
若只返回 float，GEPA 的反思提示只能看到 "This trajectory got a score of N"，
最贵的信息（**为什么不好**）会被丢掉。所以本文件的核心产物是 `feedback` 字符串。
参考：GEPA 论文 arXiv:2507.19457 与 dspy.ai/api/optimizers/GEPA。

## 设计原则（改本文件前必读）
1. **feedback 的信息密度 > score 的精度。** 宁可 score 粗糙，也要 feedback 具体到"哪句台词、为什么、往哪改"。
2. **checker 的 message 就是最好的 feedback。** 它是确定性的、可复现的、领域专用的自然语言诊断。
   这就是为什么 DSL §5 强制 message 写成完整诊断句——那不是给人看的日志，是给优化器看的训练信号。
3. **人类修订是最高价值的 feedback。** 但只在 trainset 上暴露，valset 只用 checker + 判官，
   否则 GEPA 会学到"背下这些改法"而不是"学会这类判断"。
4. **per-predictor 路由。** 给 p3_beatsheet 的 predictor 喂"台词太长"是噪声。见 FEEDBACK_ROUTING。
5. **分趟优化 + 教师强制。** 不要端到端优化 8 趟（rollout 太贵、归因太难）。
   优化 p3 时，p0-p2 用黄金 IR 教师强制；优化 p5 时，p0-p4 用黄金 IR。见 gepa_run.py。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import dspy

# ---------------------------------------------------------------- 路由表

#: 每个 predictor 关心哪些反馈来源。改这个表 = 改 GEPA 的学习目标。
FEEDBACK_ROUTING: dict[str, dict[str, Any]] = {
    "p1_bible": {
        "check_domains": ["structure", "producibility"],
        "check_tags": ["character", "voice"],
        "rubric_dims": ["producibility"],
        "edit_dims": ["character", "producibility"],
    },
    "p2_arc": {
        "check_domains": ["structure", "brand"],
        "check_tags": ["coverage", "plot_connection", "hook", "placement_position"],
        "rubric_dims": ["hook_strength", "transportation"],
        "edit_dims": ["structural", "placement"],
    },
    "p3_beatsheet": {
        "check_domains": ["structure", "brand"],
        "check_tags": ["hook", "pacing", "setup_payoff", "emotion", "density", "intensity"],
        "rubric_dims": ["hook_strength", "transportation", "placement_integration"],
        "edit_dims": ["structural", "placement"],
    },
    "p4_scene": {
        "check_domains": ["structure", "producibility"],
        "check_tags": ["scene", "producibility"],
        "rubric_dims": ["producibility"],
        "edit_dims": ["structural", "producibility"],
    },
    "p5_dialogue": {
        "check_domains": ["dialogue", "brand", "compliance", "fact"],
        "check_tags": ["length", "banned", "naming", "voice", "must_include", "duration"],
        "rubric_dims": ["naturalness", "placement_integration"],
        "edit_dims": ["dialogue", "character", "placement", "factual", "compliance"],
    },
    "p6_prose": {
        "check_domains": ["novel", "compliance", "fact"],
        "check_tags": ["novel", "anchor", "readability", "consistency"],
        "rubric_dims": ["naturalness", "transportation"],
        "edit_dims": ["dialogue", "taste"],
    },
}

#: score 的权重。sum == 1.0（测试会检查）
WEIGHTS: dict[str, float] = {
    "structure_match": 0.30,   # 与黄金 IR 的结构一致度（可算，稳定）
    "checker": 0.30,           # L0 通过率（可算，稳定）
    "rubric": 0.25,            # 判官（会漂，权重刻意压低）
    "edit_distance": 0.15,     # 与人类改后文本的接近度（仅 trainset 有）
}

FEEDBACK_BUDGET_CHARS = 2600


# ---------------------------------------------------------------- 数据结构

@dataclass(slots=True)
class MetricParts:
    structure_match: float
    checker: float
    rubric: float
    edit_distance: float | None
    findings: list[Any]                 # list[Finding]
    rubric_detail: dict[str, float]
    human_edits: list[dict[str, Any]]
    notes: list[str]


# ---------------------------------------------------------------- 主入口

def make_metric(
    *,
    split: Literal["train", "val"],
    ruleset_root: str = "spec/checks",
    judge_enabled: bool = True,
    expose_human_edits: bool | None = None,
) -> Any:
    """构造 GEPA metric。

    `expose_human_edits` 缺省 = (split == "train")。原则 3。
    """
    reveal = (split == "train") if expose_human_edits is None else expose_human_edits

    def metric(
        gold: dspy.Example,
        pred: dspy.Prediction,
        trace: Any = None,
        pred_name: str | None = None,
        pred_trace: Any = None,
    ) -> dspy.Prediction:
        parts = _compute_parts(gold, pred, judge_enabled=judge_enabled)
        score = _aggregate(parts, has_edits=reveal and bool(parts.human_edits))
        feedback = build_feedback(
            parts, pred_name=pred_name, reveal_human_edits=reveal, budget=FEEDBACK_BUDGET_CHARS
        )
        return dspy.Prediction(score=score, feedback=feedback)

    return metric


def _aggregate(parts: MetricParts, *, has_edits: bool) -> float:
    """硬地板：存在 block 级 finding 时直接给 failure_score(0.0)。

    理由：GEPA 的 skip_perfect_score / failure_score 机制依赖分数的语义清晰。
    一个结构违规的输出不该因为台词漂亮而拿到 0.6——那会教会优化器"用文采换合规"。
    """
    if any(getattr(f, "severity", "") == "block" for f in parts.findings):
        return 0.0
    w = dict(WEIGHTS)
    if not has_edits:
        # 重新归一化，避免 valset 天然吃亏
        redistribute = w.pop("edit_distance")
        total = sum(w.values())
        w = {k: v + redistribute * v / total for k, v in w.items()}
    s = (
        w["structure_match"] * parts.structure_match
        + w["checker"] * parts.checker
        + w["rubric"] * parts.rubric
        + w.get("edit_distance", 0.0) * (parts.edit_distance or 0.0)
    )
    return max(0.0, min(1.0, s))


# ---------------------------------------------------------------- feedback 构造

def build_feedback(
    parts: MetricParts,
    *,
    pred_name: str | None,
    reveal_human_edits: bool,
    budget: int = FEEDBACK_BUDGET_CHARS,
) -> str:
    """把诊断信息压缩成一段高信息密度的中文反馈。

    ## 优先级（预算耗尽时按此截断）
    1. **block 级 checker findings**（最确定、最可操作）
    2. **人类修订对**（最高价值，仅 trainset）：原文 → 改后 → 人类理由
    3. **最低分的 rubric 维度**（含判官引用的具体 span）
    4. **warn 级 findings**（同域最多 2 条）
    5. **一条正面确认**（做对了什么，防止优化器把好的一起改掉 —— 这条经验上很重要）

    ## 格式（GEPA 的反思 LM 要读的，所以要结构化但不要 JSON）
    ```
    【必须修正】
    - [BM-001] 第 3 集有 4 处品牌植入，超过预算 2 处；…请合并第 2、3 处。
    【人类是怎么改的】
    - 原文：这款茶用的是进口茶基，热量只有三分之一。
      改后：（把杯子推过去）不加糖的。
      理由：念参数太假了，我们客户不会这么说话。
      → 这类修改反复出现（本类共 5 次）：卖点应由动作与后果承载，不由台词宣称。
    【判官打分最低的维度】
    - placement_integration 2/5：判官引用「林姐：这款0蔗糖…」——角色变成播音员，删掉这段剧情不变。
    【做对了的地方（保持）】
    - 第 1 集 hook 用"体检报告"起手，3 秒内给出具体冲突。
    ```

    ## 禁止
    - 禁止输出黄金答案全文（只给被修改的 span 对照）。
    - 禁止只写规则 ID 不写内容。
    - 禁止把 8 个维度全塞进来（反思 LM 会被淹没，GEPA 论文的教训是反馈要聚焦）。

    TODO(agent, T-12): 实现。必须有单元测试验证：
      - pred_name 路由生效（p3 的反馈里不出现 DLG-002）
      - reveal_human_edits=False 时输出不含 revised_text
      - 输出长度 <= budget
      - block finding 一定出现在第一节
    """
    raise NotImplementedError("T-12")


def _compute_parts(gold: dspy.Example, pred: dspy.Prediction, *, judge_enabled: bool) -> MetricParts:
    """计算四个分量。

    structure_match 的定义（p3 为例）：
      - beat_kind 序列的归一化编辑距离（1 - dist/max_len）× 0.5
      - hook 位置一致 × 0.15
      - brand_moment 位置集合的 Jaccard × 0.2
      - setup_payoff 数量与跨度匹配 × 0.15
    对 p5：
      - 说话人序列一致度 × 0.4；每条长度分布 KL × 0.3；必提台词命中 × 0.3
    对 p6：
      - anchor 覆盖率 × 0.5；段落数比例 × 0.2；对白相似度均值 × 0.3
    定义写在 src/nsc/optimize/structure_match.py，**必须是确定性的、无 LLM 的**。

    TODO(agent, T-12)
    """
    raise NotImplementedError("T-12")