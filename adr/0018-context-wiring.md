# ADR-0018：接线上下文预算装配与历史压缩（context.assembler / context.compress）

- 状态：proposed
- 日期：2026-08-22
- 影响层：A 资产层（profiles/_schema.py + profile yaml）；B 层消费

## 背景

SW-06（上游依赖卡）：`nsc.context.assemble`（T-33）与 `compress_history` 在 main 上
已实现但未接线——没有任何 Pass 的输入过预算装配，p3 的远端历史永远走原文窗口。

## 决定

1. **P2-P4 层接入 p3/p5**（`nsc.passes.assemble_context` 统一入口）：
   - p3：P1=episode_json（不可裁剪锚）；P2=prev_episode_summary（SW-05 窗口文本）；
     P3=known_facts 逐条；P4=retrieved_cases；P5=bible/profile 参考层（低保）。
   - p5：P1=scene_json+beats_json；P4=retrieved_cases；P5=characters/profile 参考层。
   - 预算读 `context.budget` / `context.core_guarantee`；降级顺序由 assembler 既定
     语义决定（P4 整层丢 → P2 截尾 → P3 截断 → P5 低保）。
2. **compress_history 接入 p3 远端历史**（`pipeline._history_text`）：
   `context.history_compress: true` 且窗口宽于 `history_keep_recent` 时，窗口内远端集
   经 `make_llm_summarizer`（LLM 出口走 models 路由）压缩成"【前情】"，近端集保
   原文"【上一集】"；否则退回 SW-05 的原文窗口。

## 缺省零变化（关键设计约束）

- `budget=32768` 足够大 → 装配全存活，p3/p5 输入与接线前逐字节等价；
- `history_compress=false` → 永不产生压缩 LLM 调用，前情文本 = SW-05 `_window_join`。
- 压缩不设缺省开启的原因：compress_history 的输出带"【前情】/【上一集】"标记，
  默认开启会改变既有 prompt 字节内容（缓存键漂移）；开关交给 profile 显式打开。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 默认开启压缩 | 改变缺省 prompt 字节内容，违背"缺省零变化"约束 |
| 在 pipeline 组装层做预算 | 装配是 Pass 输入语义（p6 先例在 Pass 内），pipeline 只管历史文本来源 |
| p5 也接 P2/P3 | p5 输入无前情/事实层（场景级编译）；接了也是空层 |

## 对下游的约束

- 降级诊断（degraded/dropped）目前只进 assembler 返回值；若要进 runs 表需另卡。
- `assemble_context` 的 P3/P5 存活重建是前缀式的：条目顺序即优先级，不得乱序。

## 迁移

非 breaking；在库 profile 写入缺省值。依赖 SW-05 的 `context` 段（本 ADR 与
ADR-0017 同段扩容），本卡分支基于 sw/sw-05-p3-context-config。

## 验证

`tests/test_context_wiring.py`：缺省全存活/紧预算按序降级、p5 装配、压缩接线
（远端 SUM / 近端原文 / 缺省零压缩调用）；全量 `pytest -m "not llm"` 绿。
