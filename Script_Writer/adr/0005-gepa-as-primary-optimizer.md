# ADR-0005：GEPA 是主优化器；P3 前不微调

- 状态：accepted · 日期：2025-01-01 · 影响层：B1

## 决定
用 `dspy.GEPA`（GEPA: Reflective Prompt Evolution，arXiv:2507.19457，ICLR 2026 Oral）优化全部 prompt。
metric 返回 `dspy.Prediction(score=..., feedback=...)`，feedback 由 checker message + 人类修订 + 判官理由构成。
**分趟优化 + 教师强制**，不端到端优化 8 趟。

## 理由
1. GEPA 吃自然语言反馈，而我们的输入天然就是自然语言批注——这是我们最贵的信息，标量分会把它扔掉。
2. 样本效率：论文报告在 4 个基准上平均超过 GRPO 约 10%、最高约 20%，rollout 少至 1/35；超 MIPROv2 10%+。
   一年攒不出几千条剧本反馈，RL 不可用。
3. 产出物是可读指令，可被人审阅、可反向写回 Spec。权重不行。
4. 零 GPU、零训练基建。

## 被否决
RLHF/DPO/GRPO（数据量差两个数量级 + 基建成本）；纯手工调 prompt（不可积累，换模型归零）。

## 对下游的约束
- `prompts/` 是 GEPA 产物，手改 = CI 失败。
- 每次 GEPA 写入必须过回归闸：`score_after > score_before + 0.02` 且其他 pass 不退化。
- `src/nsc/optimize/gepa_metric.py` 是全系统最厚的一个文件，改它需要 ADR。