# ADR-0016：管线策略 profile 化（pipeline/retrieval/revise 三段）

- 状态：accepted
- 日期：2026-08-22
- 影响层：A 资产层（profiles/_schema.py + 两个 profile yaml）；B 层仅消费

## 背景

SW-07（上游依赖卡）：各 phase 重试次数、定向重生成策略、self-check 子步骤开关、
检索注入条数（rerank n）此前是 `pipeline.py` / `p5_dialogue.py` / `cli.py` 里的
代码常量（`attempts=2`、`range(3)`、`"lenient"`、`k=3`）。弱模型与强模型需要
不同的重试预算，改常量就要动代码层，无法按 profile 分道调参。

## 决定

Profile 新增三段（缺省值 = 原代码常量，既有 profile 行为零变化）：

| 段.键 | 语义 | 缺省 | 消费点 |
|---|---|---|---|
| `pipeline.pass_attempts` | 单 Pass 输出波动重试（D13） | 2 | `pipeline._retry_pass` |
| `pipeline.phase_attempts` | p3/p4、p5、p6 相位级定向重生成 | 3 | `run_pipeline` 三个相位循环 |
| `retrieval.top_k` | 每命中的案例注入条数（rerank top-n） | 3 | `cli._make_retrieval` → `RetrievalService.k` |
| `revise.self_check` | p5 自检子步骤开关（T-31，既有键，入 schema 正名） | true | `p5_dialogue._self_check` |
| `revise.gate_mode` | 定向重生成采纳门槛（`nsc.revise.gate.MODES`） | lenient | `p5_dialogue._self_check` |

`profiles/_schema.py` 相应新增 `PipelineSettings` / `RetrievalSettings` /
`ReviseSettings`（`extra="forbid"`，与既有段一致）。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 环境变量（NSC_PASS_ATTEMPTS 等） | 与 SW-04 同理：策略被运行时环境稀释，且不可进 provenance/缓存键 |
| config/models.yaml 侧配置 | 那是模型路由的生成物配置；策略属于 profile 资产 |
| 每相位独立键（phase_p3_attempts...） | 现实中三个相位同预算；先给粗粒度，需要时再加 |

## 对下游的约束

- 调参只改 profile yaml，不改 `src/`；`_retry_pass(attempts=...)` 显式参数保留
  （测试/特殊路径用），优先级：显式参数 > profile > 代码缺省。
- `revise.gate_mode` 只允许 `nsc.revise.gate.MODES` 里的值（schema Literal 约束）。

## 迁移

非 breaking：新段全部有缺省，旧 profile（无三段）行为不变。两个在库 profile
（short_drama_v1 / short_video_v1）显式写入了缺省值以便发现。

## 验证

`tests/test_profile_strategy.py`：pass_attempts/phase_attempts 生效性与缺省回退、
phase_attempts=1 时 BM-007 拦截即抛、gate_mode/top_k 读取；全量 `pytest -m "not llm"` 绿。
