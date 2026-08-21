# ADR-0017：p3 fragment 组成数据化（profile.context 段）

- 状态：proposed
- 日期：2026-08-22
- 影响层：A 资产层（profiles/_schema.py + profile yaml）；B 层仅消费

## 背景

SW-05（上游依赖卡）：p3 的跨集上下文组成硬编码在 `pipeline.py`——
`prev_episode_summary` 窗口恒为 1（只看上一集）、`known_facts` 投影恒为五字段、
p2 规划的 `threads` 表永不注入 p3。弱模型需要更长的历史窗口与更窄的投影面，
强模型可以相反；这些是 profile 级策略，不是代码常量。

## 决定

Profile 新增 `context` 段（缺省 = 原行为，零变化）：

| 键 | 语义 | 缺省 | 消费点 |
|---|---|---|---|
| `context.prev_summary_window` | p3 `prev_episode_summary` 看近端 N 集（0=恒空） | 1 | `run_pipeline` p3 循环 + `recompile_episode`（`_window_join`：按时间序逐行拼接，远端在前、近端在后，与 compress_history 的【前情】→【上一集】布局一致） |
| `context.known_fact_fields` | `known_facts` 投影字段（白名单子集） | `[id, content, episode_no, status, type]` | `_known_facts` |
| `context.inject_threads` | 是否把 p2 的 Thread 表注入 p3（投影 `{id,title,status,state}`） | false | `run_pipeline`/`recompile_episode` 组装 fragment，p3 转发进 LLM 输入 |

`profiles/_schema.py` 新增 `ContextSettings`（`extra="forbid"`；`known_fact_fields`
经校验器限制在白名单内）。后续上下文预算旋钮（SW-06）并入同段。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 环境变量 | 与 SW-04 同理：策略被运行时稀释，不进缓存键 |
| 每集覆盖（brief 级） | 组成策略是 profile 资产，逐 brief 覆盖会让缓存键粒度爆炸 |
| 直接注入全量 threads/facts | p3 输入预算失控；投影面必须显式声明 |

## 对下游的约束

- 改窗口/投影只动 profile yaml；`_KNOWN_FACT_FIELDS` 白名单新增字段需同步本 ADR 的表。
- window=1 时 `prev_episode_summary` 与原实现逐字节一致（既有快照/桩测试守护）。
- `known_fact_fields: []` 是合法的显式空投影（有意隐藏全部字段），不等同于未配置（review 修正）。
- 窗口内多集按时间序排列（远端在前），与 compress_history 输出布局一致（review 澄清，初稿表述有误）。

## 迁移

非 breaking：三键全有缺省；在库 profile（short_drama_v1 / short_video_v1）显式
写入缺省值以便发现。

## 验证

`tests/test_p3_context_config.py`：投影字段与缺省回退、窗口=1 回归、窗口=2 含
祖父集摘要且近端在前、threads 开关注入/缺省不注入；全量 `pytest -m "not llm"` 绿。
