# ADR-0014：判官三视角、Elo 锦标赛与 plateau 停止条件

- 状态：accepted（项目负责人 2026-08-17 指令授权，见 `docs/UPGRADE_PLAN_2026-08-17.md` §0）
- 日期：2026-08-17
- 影响层：A3 品味（`spec/rubrics/pairwise_protocol.md` 协议资产变更、anchors 增补）+ B2 生成物（judge/eval/optimize 三处）

## 背景

autonovel 实测：1-10 绝对评分塌缩到 2 分带宽，成对比较 + Elo 锦标赛才有区分度；其 reader_panel 证明多视角（编辑/类型读者/作者/普通读者）的分歧本身就是编辑决策点。NSC 已是成对判官 + 校准路线（正确），缺的是：① 判官视角单一；② 无章节间相对排序机制；③ 修订/优化循环无工程化停止条件（autonovel plateau Δ<0.3@≥3 轮、inkos 退步回滚均已验证）。

## 决定

1. **三视角判官**：`rubric_judge` 指令内嵌三视角——编辑（prose 工艺/声音一致性）、类型读者（节奏/钩子/翻页欲）、普通读者（情绪诚实、不用术语）。**同一判官调用**输出三视角注记 + 分歧标记；聚合逻辑不变（确定性）。分歧项写入 feedback"编辑决策点"节，不作门禁。**明文界定**：这是同一 LLM 的多视角注记，无 agent 间通信、无互评、无辩论，不触碰"禁止多智能体互评"红线。
2. **Elo 锦标赛**：`nsc eval l1 --tournament`，参数固定：初始 1500、K=32、4 轮 Swiss（Elo 降序相邻配对）、无平局（必须选胜方）、judge temperature=0.2、每章截断 3000 字、5 条比较轴（prose 锐度/对话口语感/真实张力/信任读者/AI 模式更少）。输出排名报告，仅作分析，不进门禁。
3. **plateau 停止条件**（revision 循环与 GEPA 通用）：归一化指标相邻两轮 Δ<0.03 且已跑 ≥3 轮即停；硬上限 6 轮；修订退步（门禁计数恶化）→ 回退到最佳快照。
4. **rubric 锚点增强**：autonovel 12 条结构性反模式逐条落 `spec/rubrics/anchors/prose_craft.yaml` 锚点描述与反例；平台 must_have 节奏项落 `hook_strength.yaml`/`naturalness.yaml`；不新增 rubric 维度（6 维上限不动）。
5. `eval/thresholds.yaml` **不改动**（plateau/Elo 参数为机制常量，不是校准阈值）。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 多判官并行 + 仲裁（One-Sentence 三裁判） | 触碰多智能体红线；三视角单调用获得同等信息量且零仲裁复杂度 |
| 绝对分门禁 | autonovel 实测塌缩；NSC 成对 + 校准已是更优解 |
| Elo 作交付门禁 | 相对排序依赖参赛集合，不可复现；仅作分析工具 |
| 新增 rubric 第 7 维 | `max_rubric_dimensions: 6` 是既有架构纪律；反模式知识进锚点而非新维度 |
| plateau 阈值进 thresholds.yaml | 它是循环控制常量，非判官校准阈值；改动 thresholds 需另行 ADR |

## 对下游的约束

- 三视角注记必须随判官结果持久化（Langfuse trace + DB），供 `make judge-cal` 统计视角分歧率。
- Elo 锦标赛不得用于 rule mining 的 evidence（相对序不构成绝对质量证据）。
- plateau 触发必须写运行日志（轮次、Δ、停止原因）。

## 迁移

判官协议资产变更 → 下次 `make judge-cal` 重跑校准报告（含视角分歧统计），κ 不降即通过。其余纯新增。

## 验证

- `tests`：Elo 配对/公式/无平局断言；plateau 合成序列停止断言；三视角输出结构断言。
- `nsc judge calibrate`：κ 相对基线不降；报告含视角分歧统计。
- `nsc eval l1 --tournament` 产出可复现排名（固定 seed）。
