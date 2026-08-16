# SOP · GEPA 优化（D13 3 档）

## 什么时候跑
- 每月一次；或分数停滞（连续 2 周北极星无改善）；或换主模型后
- 攒够 ~30 条新 `revision_pairs` 之后（少于这个数不值得跑）

## 顺序（先结构后文字）
```bash
nsc optimize --pass p3_beatsheet --auto light   # 最重要，先跑这个
nsc optimize --pass p2_arc       --auto light
nsc optimize --pass p5_dialogue  --auto medium
nsc optimize --pass p6_prose     --auto light
```
理由：结构错了优化台词是浪费。BeatSheet 是整个系统的杠杆点。

## 数据切分（会泄漏的地方）
**按 case 切分，绝不按节点切分。** 同一个项目的第 2 集在 train、第 5 集在 val = 泄漏
（人物、调性、品牌约束全都一样）。
```bash
nsc eval build-dataset --pass p3_beatsheet   # 自动按 case_id 分层切分
```

## metric 的两个 split
- `train`：暴露人类修订（`revised_text`）→ 反馈信息量最大
- `val`：**只**用 checker + 判官 → 防止 GEPA 背答案
实现见 `gepa_metric.py::make_metric` 的 `expose_human_edits`。

## 回归闸（不许绕过）
写入 `prompts/` 的条件：
1. `score_after > score_before + 0.02`（valset）
2. 其他 pass 在 holdout 上不退化（`make golden` + 抽样 L1）
3. 成本未超 `budgets.per_gepa_run_usd`
不满足 → 结果进 `out/gepa/rejected/`，`prompts/` 不动。

## 读 GEPA 的产出
`out/gepa/<pass>/<ts>/detailed_results.json` 里有演化轨迹。
**读演化出的指令**，问自己：
- 它学到的东西，是不是应该被提升为 `spec/rules/L3_canonical/` 的一条规则？
- 若是 → 手工把它写成规则（`form: prompt` 或 `form: check`），下次 GEPA 从更高的起点开始。
这就是"优化结果可以被反向写回 Spec"的具体操作（D13 为什么选 GEPA 的第 3 条理由）。

## 反面清单
- ❌ 端到端优化 8 趟（rollout 爆炸、归因不可能）
- ❌ 用 float metric（丢掉 feedback 通道 = 白用 GEPA）
- ❌ 用弱模型做 reflection_lm（反思质量决定一切，这里不要省钱）
- ❌ auto="heavy" 起步（先 light 看有没有信号）