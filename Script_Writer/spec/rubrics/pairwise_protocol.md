# 判官成对比较协议

## 1. 为什么以成对为主 `[[form:non-normative]]`
绝对分会随模型版本漂移；成对偏好在同一次调用内比较，漂移大幅减小，且直接对应人类的"我更喜欢改后那版"这一最常见反馈形态（D9 的 `revision_pairs` 天然是成对数据）。

## 2. 输入
```
{unit_kind: line|beat|scene|episode|chapter,
 context: {上游 IR 摘要, 相关 BrandBrief 片段, 相关 canonical 规则},
 A: <文本或 IR 片段>, B: <同上>,
 dimensions: [要判的维度 id 列表]}
```

## 3. 流程 `[[form:check]]` → `spec/checks/../JDG-001.yaml`（判官输出格式校验）
1. 调用 1：顺序 (A, B)。
2. 调用 2：顺序 (B, A)。
3. 若两次结论相反 → 判为 `tie`，并把该样本自动加入 `judge_calibration` 待人工裁决队列。
4. 每维度输出 `{winner: A|B|tie, margin: 1|2|3, rationale, cited_spans: [...]}`。
5. `cited_spans` 为空 → 该次判定作废并重试一次；再次为空 → 记为 `invalid`，计入判官健康度指标。

## 4. 校准门槛（`eval/thresholds.yaml` 中可调，改动需 ADR）
| 用途 | 指标 | 门槛 |
|---|---|---|
| 允许出报告 | 与人类成对一致率 | ≥ 0.65 |
| 允许参与门禁 | 与人类成对一致率 | ≥ 0.78 |
| 允许参与门禁 | Cohen κ（5 分制，与人类） | ≥ 0.60 |
| 健康度 | `invalid` 比例 | ≤ 0.05 |
| 健康度 | 位置偏置（A 位胜率偏离 0.5） | ≤ 0.08 |

未达门槛 → `judge-calibration.yml` 自动把仓库变量 `JUDGE_GATE_ENABLED` 置为 `false` 并开 Issue。

## 5. 校准集构建（≥50 条起步）
- 40% 来自 `revision_pairs`（原文 vs 人类改后 → 人类偏好已知，是免费的校准数据）
- 30% 来自 `preference_pairs`（同一 Beat 的两次生成，你人工选）
- 30% 来自 `counterexamples`（已知坏样本 vs 已知好样本，锚定极端）

## 6. 三视角注记（ADR-0014）`[[form:non-normative]]`

判官在**同一次 LLM 调用**的指令内额外输出三个视角的注记，不改变该次调用的分数/判定：

| 视角 id | 角色 | 关注 |
|---|---|---|
| `editor` | 编辑 | prose 工艺、声音一致性 |
| `genre_reader` | 类型读者 | 节奏、钩子、翻页欲 |
| `lay_reader` | 普通读者 | 情绪是否诚实、像不像真人反应（不用行话术语） |

- 输出结构：在既有 JSON 上新增 `perspectives: {editor: {note}, genre_reader: {note}, lay_reader: {note}}` 与 `perspective_disagreement: bool`（三视角注记对同一文本出现方向相反的判断时由判官自报）。
- 解析防御：LLM 省略 `perspectives` → 空 dict，不判 `invalid`、不触发重试。
- disagreement 语义：**分歧项 = 编辑决策点**。写入 feedback 供人工裁决，**不作门禁**、不进 §4 的任何门槛指标；校准报告仅统计"带 perspectives 的样本中 disagreement 占比"（一行报告项）。
- 聚合不变：分数聚合与成对归并保持确定性；perspectives 仅随判官结果透传持久化（trace / 结果 dict），不参与任何聚合公式。
- 边界声明：这是**同一判官调用内的多视角注记**（单次 LLM 调用的结构化输出扩展），不是多智能体互评/辩论，无 agent 间通信，不触碰 AGENTS.md §2"禁止多智能体互评"红线。

## 7. Elo 锦标赛（ADR-0014）`[[form:non-normative]]`

章节间相对排序用 Elo 锦标赛（`nsc eval l1 --tournament`）：初始 1500、K=32、4 轮 Swiss（Elo 降序相邻配对）、无平局（judge_fn 必须返回 1.0/0.0）、每章截断 3000 字。输出排名报告**仅作分析**，不进门禁，也不得作为 rule mining 的 evidence（相对序不构成绝对质量证据）。