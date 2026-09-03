# ADR-0020：Q1 判官轴重构——新增 reading_attraction 轴与权重再平衡

- 状态：proposed
- 日期：2026-09-01
- 影响层：A3 品味（rubric 新增第 7 维 + 权重再平衡 + placement 锚例微调）+ B2 测试（判分聚合期望值更新）

## 背景

Lab 侧质量进攻路线图（`/root/workspace/Script_Writer_Lab/adr/0004-quality-offensive-roadmap.md`，状态 accepted）于 2026-09-01 由 owner 裁决按 Q1 路线执行。Q1 指认的根因是：rubric_v1 六轴中品牌/合规向（naturalness+placement+transportation）合计 0.60，文笔（prose_craft）仅 0.10，且无"追读性"维度，导致判官奖励"广告式顺滑"而非"好读"。

Lab 侧地基已落地：`criteria/reading_attraction.md` 定义了第七轴的问题与信号。SW 侧需将 Lab 裁决落地为可评测资产。

## 决定

在 `spec/rubrics/rubric_v1.yaml` 中执行 Q1 判官轴重构：

1. **新增第七轴 `reading_attraction`（追读性）**
   - `applies_to: [chapter, episode]`
   - question / positive_signals / negative_signals 从 Lab `criteria/reading_attraction.md` 转写
   - 锚例文件 `spec/rubrics/anchors/reading_attraction.yaml` 同步建立（≥2 锚，含低分/满分）

2. **权重再平衡**
   - `prose_craft` 0.10 → 0.25
   - `reading_attraction` 新增 0.15
   - `naturalness` 0.25 → 0.15
   - `placement_integration` 0.20 → 0.15
   - `hook_strength`、`transportation`、`producibility` 权重不变
   - **注**：权重总和变为 1.15。`aggregate_l1` 使用加权均值公式 `sum(w*x)/sum(w)`，不要求权重归一化，因此不影响聚合计算。

3. **placement 轴锚文本從「顺滑展示」改为「戏剧化融入」**
   - 更新 `spec/rubrics/anchors/placement_integration.yaml` score 3 锚例标签与 why，强调"删掉产品剧情依然完整"的戏剧化缺失
   - score 5 锚例已体现"产品是冲突的解法"，保留并补充戏剧化融入说明

4. **实物产品 brief 恢复 placement_integration 0.20 的机制**
   - 当前 `aggregate_l1` 无条件权重逻辑。在 rubric YAML 中以注释形式保留该机制，待后续 `aggregate_l1` 支持 `weight_profile` 或 brief 级权重覆写时落地。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 在 `aggregate_l1` 里硬编码 brief 类型条件权重 | 超出本次 rubric 资产重构范围；注释说明已足够，具体实现可在后续 PR 独立推进 |
| 为保持权重和为 1.0 而再削减另一轴 | ADR-0004 已明确各轴目标权重，不应再压缩 prose_craft 或 reading_attraction |
| 将 reading_attraction 设为 block 规则 | 追读性是主观品味，应归 rubric 度量，不作交付门禁（与 prose_craft 同级） |

## 对下游的约束

- 判官 L1 聚合公式不变，`test_aggregate_l1_weighted` 的期望值需从 4.111 更新为 3.857（naturalness 权重从 0.25 降至 0.15）。
- `test_run_l1_judge_stub` 的判分样本计数需从 9 更新为 10（episode 新增 reading_attraction 适用维度）。
- `make judge-cal` 必须重跑（GATES.md 纪律），但因 `config/models.yaml` 的 tier_judge 指向已枯竭的 LongCat 端点，本地 judge-cal 会失败。本次 PR 仅验证 `make spec-guard` + 全量非 LLM 测试；judge-cal 待 models.yaml failover PR 合并后补跑。
- 新增 `reading_attraction` 轴后，`p6_prose` 的 `FEEDBACK_ROUTING.rubric_dims` 理论上应纳入该轴，但本次保持路由不变，待 owner 评估后单独迭代。

## 验证

- `make spec-guard` 全过（维度数、锚例存在性、schema 合规）。
- `uv run pytest -m "not llm" -n auto -q` 全绿。
- `tests/test_judge.py::test_all_dimensions_have_anchors` 自动覆盖 reading_attraction 锚例 ≥2 校验。

## 迁移

非 breaking：纯新增资产 + 权重数字调整 + 锚例文本微调。回滚方式：删除 reading_attraction 维度与锚例、回滚 rubric 权重、回滚 placement score 3 锚例。
