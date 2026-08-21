# AGENTS.md · Lab 开发 Agent 的唯一入口

## 0. 层与规矩

| 路径 | 层 | 规矩 |
|---|---|---|
| `contract/**` `spec/**` `adr/**` | **资产** | 改动需 ADR;`contract/` 另需人类确认(见 `contract/promotion.yaml`) |
| `mined/**` | **资产(聚合洞察)** | 只允许统计/规则候选/词典等聚合产物;禁止出现语料原文(CI 守卫拦) |
| `src/**` `tests/**` | **代码** | 自由重写,前提是 `make ci` 全绿 |
| `out/**` `dashboards/**` | **生成物** | gitignored |
| `corpus/**` `transcripts/**` | **禁地** | 永不提交;永不跨仓复制;优化 agent 无读权限 |

## 1. 工作循环(TDD,强制)

1. 读工单:`docs/WORK_ORDERS.md` 中的 `L-xx`,卡内写明**验收命令**。
2. 先写/取测试(部分卡已带红测试),**必须先见红**。
3. 最小实现转绿。
4. `make ci` 全绿。
5. 提交 PR 到 `feature/lab-bootstrap`,卡号写进提交信息。

## 2. 硬约束(CI 会拦)

- 禁止把 `../Script_Writer` 当 Python 依赖 import;一律 subprocess 调其 pinned checkout 的 `uv run nsc ...`(checkout 路径在 `lab.toml`)。
- 每个 LLM 调用必须经 `src/lab/models.py` 路由并写 transcript(表结构见 `adr/0001-lab-constitution.md` §接口)。禁止直接调 SDK。
- 禁止新增 agent 框架 / 编排框架(LangGraph/CrewAI/Prefect)/ 数据库。纯 Python 函数 + SQLite。
- 优化器可写面 = `spec/operators/surface.yaml` 的 M1/M2;M3 项只能产出 ADR 建议文本。
- `contract/sealed/` 任何改动必须使 `lab contract verify` 失败(哈希锁)。
- 规则/指标的"知识"写 `spec/` 或 `mined/`,禁止埋进 `src/` 的业务 `if`。

## 3. 你必须停下来问人类

改 `contract/**`;新增模型家族;提高 sealed 提交配额;把任何 `corpus/` 内容移出本机;跨仓库改动 `../Script_Writer`(那是对面仓库的 PR 流程)。

## 4. 上下文导航(按需读)

| 我要做的事 | 先读 |
|---|---|
| 任何卡 | `adr/0001-lab-constitution.md` §接口(函数签名以它为准) |
| 语料相关卡 | `spec/schemas/corpus_card.schema.yaml` |
| 退化/偏好对卡 | `spec/degradation/operators.yaml` `spec/schemas/pairs.schema.yaml` |
| 判官卡 | `contract/judges.yaml` |
| 运行器卡 | `contract/objective.yaml` `contract/promotion.yaml` |
