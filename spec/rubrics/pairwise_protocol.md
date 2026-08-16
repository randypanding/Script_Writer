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