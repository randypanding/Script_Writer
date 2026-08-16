# SOP · 逆向标注与往返重建（D15/D16）

> 目的：不花标注钱建起黄金集，并**验证 IR 设计对不对**（这是返工成本最高的错误）。
> 法务边界见 `COMPLIANCE.md §1` —— 先读它。

## 1. 采集
公开的营销短剧 / 广告片 / 带货短视频。优先选：
- 有明确品牌植入的
- 有完整叙事的（不是纯口播）
- 覆盖 ≥3 个行业（否则先验会偏）

## 2. 转写
```bash
nsc annotate ingest <source_dir>
```
内部：字幕优先；无字幕用 faster-whisper（带时间戳）；可选 PySceneDetect 做镜头切分辅助 Scene 边界。
见 `docs/BORROW_MAP.md #21`。

## 3. LLM 标注 → IR
标注器输出：Beat 切分与 beat_kind、BrandMoment（type/intensity/modality/plot_connection/位置）、
每 Beat 的 emotion、SetupPayoff、角色与地点。

## 4. 人工只标 30–50 条种子
用于**验证标注器**，不是用于训练。测量：
| 字段 | 指标 | 门槛 |
|---|---|---|
| beat_kind | 逐 Beat κ | ≥0.60 |
| Beat 边界 | 边界 F1（±1 秒容差） | ≥0.70 |
| BrandMoment 位置 | 归一化位置 MAE | ≤0.08 |
| plot_connection | κ | ≥0.50 |
不达标 → 改标注器 prompt，**不要**用不可靠标注去生成先验。

## 5. 三样产出
```bash
nsc annotate priors --out profiles/_mined_priors.yaml
```
1. **结构统计先验** → 写进 `profiles/*.yaml` 的 `beat_templates`（source: mined）与默认预算
   （Beat 数分布、植入归一化位置直方图、密度、钩子长度、情绪弧形状聚类）
2. **检索池** → `retrieval_items`（`usable_as_example=0`，只用于结构学习，见 COMPLIANCE §1）
3. **反例集** → 明显失败的植入 → 变成 `spec/checks/` 规则 + `counterexamples`

## 6. 往返重建（D16）—— 最重要的一步
```bash
nsc annotate roundtrip --case case:0301
```
`原片 → IR → 用我们的 p3–p6 重新生成 → 与原片对比`
| 指标 | 含义 |
|---|---|
| beat_kind 序列归一化编辑距离 | IR 是否抓住了结构 |
| BrandMoment 位置分布 KL | IR 是否抓住了植入节奏 |
| 判官成对（重建 vs 原片） | IR 是否抓住了"好在哪" |

**重建保真度低 = IR 丢了关键信息 = 必须改 IR 模式（开 ADR）。**
这是唯一不需要人类标注就能检验本体设计的方法。**P1 阶段必须跑，不要拖到 P2。**