# SOP · 反馈回收（D9/D10/D11）

> **这个流程的 ROI 高于任何生成质量优化。** 生成差可以靠人补；反馈收不回来是永久损失。

## 0. 前提：交付时就要埋锚点
`nsc render` 自动做三件事（D29）：
1. docx 每个段落起始插入书签 `NID_<ulid>`（不可见）
2. 文末追加「锚点索引」表（一列段落号，一列节点 ID），标题写"（此表可删除）"
3. 段落顺序与 IR 的 linear_index 严格一致

## 1. 回收（客户端零学习成本）
客户/制作团队用他们本来就在用的方式：
- docx 开修订模式改 → 发回来
- 微信发一段话吐槽 → 转发给你
- 会议里说 → 你录音后转写

**绝不要求他们打开你的系统。**

## 2. 摄入（你花 ≤5 分钟）
```bash
nsc ingest docx path/to/客户回稿.docx --case case:0142
# 或
nsc ingest text 微信记录.txt --case case:0142
```
输出：
- `feedback` 表条目（D9 五元组）
- `revision_pairs` / `preference_pairs`
- `spec/rules/L0_observations/obs_*.yaml`
- Langfuse annotation queue 条目

## 3. 确认（你花 30 秒/条，批量）
打开 Langfuse annotation queue：
- 确认 `dimension`（八类，见 `spec/feedback/TAXONOMY.md`）
- 确认 `severity`（1–5）
- 确认锚点对不对（若 `anchor_level==fuzzy` 且 `confidence<0.85`，重点看）
- **关键判断**：这条是通用规律还是个别偏好？后者一律标 `taste`（只进 Client Pack）

**未经人工确认的 feedback（`confirmed_by` 为空）不进 L1 聚类。**
理由：LLM 的分类错误会污染规则库，而规则库是永不丢弃的资产。

## 4. 对齐失败怎么办
`anchor_level == 'failed'` 的条目会进 `out/ingest/unaligned.md`。
处理顺序：
1. 检查客户是不是删了锚点索引表 → 下次交付把表放在更不显眼的位置
2. 检查是不是整章重写 → 这种情况锚到 Episode 级别即可，不必到 Line
3. 若失败率 > 10% → 这是 bug，开 issue，优先级最高

## 5. 每周节律（周一 30 分钟）
```bash
make db-export        # 确保 jsonl 是最新的
make mine             # L0→L1→L2，开 PR
make judge-cal        # 判官健康检查
make dash             # 六个数
```
然后：读 `rule-candidate` PR，approve 该晋升的，关掉不该晋升的。