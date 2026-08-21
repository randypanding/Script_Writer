# SOP · 判官校准（D8）

## 为什么必须做
不校准的 LLM judge = 用一个未测量的仪器做质量决策。这是"效果预测"从玄学变工程的唯一路径。

## 校准集怎么攒（≥50 条起，目标 200 条）
| 来源 | 占比 | 怎么来 | 成本 |
|---|---|---|---|
| `revision_pairs` | 40% | **免费**：人类改了 = 人类偏好改后 | 0 |
| `preference_pairs`（重生成） | 30% | 同一 Beat 跑两次，你选一个 | 30s/条 |
| `counterexamples` | 30% | 已知坏 vs 已知好，锚定极端 | 20s/条 |

## 流程
```bash
nsc judge calibrate --report out/judge_calibration.md
```
报告包含：
1. 每维度的**成对一致率**（判官选的 = 人类选的 / 总数）
2. 每维度的 **Cohen κ**（5 分制绝对分）
3. **位置偏置**：A 位胜率偏离 0.5 的幅度
4. **invalid 率**：未引用具体 span 的判定占比
5. **分歧样本 top 10**（这些是最有信息量的，读它们）

## 门槛（`eval/thresholds.yaml`）
见 `spec/rubrics/pairwise_protocol.md` §4。

## 改判官 prompt 的正确顺序
1. 先读分歧样本 top 10 → 判官到底误解了什么
2. 改 `spec/rubrics/anchors/*.yaml`（**优先改锚定样例，不要改指令**）
   —— 锚定样例是 A3 资产，指令是 B1 生成物
3. `make judge-cal` 看一致率是否上升
4. 若锚例改完还不行 → 用 GEPA 优化判官指令（目标 = 与人类一致率）
5. **绝不**为了让判官同意某个特定样本而改锚例（那是过拟合到一条数据）

## 判官漂了怎么办
`judge-calibration.yml` 会自动关闸并开 Issue。你的选项：
- 换 `tier_judge` 模型 → 重跑校准
- 补校准集（一致率低通常是校准集覆盖不足，不是判官坏）
- 收缩维度（`max_rubric_dimensions: 6` 是上限，但 3 个可靠维度好过 5 个不可靠维度）