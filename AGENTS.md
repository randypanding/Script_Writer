# AGENTS.md · 开发 Agent 的唯一入口

## 0. 你在改什么？（每次动手前必答）

| 你要改的路径 | 层 | 规矩 |
|---|---|---|
| `spec/**` `profiles/**` `brands/**` `cases/export/**` | **资产 A**（永不丢弃） | 必须开 ADR；必须有 evidence；必须过 `make spec-guard` |
| `src/**` `tests/**` | **代码 B2**（可丢弃） | 自由重写，但必须让 `tests/` 全绿；受行数预算约束 |
| `prompts/**` | **生成物 B1** | **禁止手改。** 只能由 `nsc optimize` / `nsc compile-prompts` 写入 |
| `out/**` | **生成物 B3** | gitignored |

## 1. 工作循环（TDD，强制）
1. 读工单：`docs/WORK_ORDERS.md` 中的 `T-xx`。工单里写明了**验收命令**。
2. 先写/取测试：`tests/` 下对应文件。**测试必须先红。**
3. 实现最小代码让测试绿。
4. `make ci-local` 全绿。
5. 提 PR，填 `.github/pull_request_template.md`。若改了资产层，附 ADR 链接。

## 2. 硬约束（CI 会拦）
- `src/nsc/runtime/` + `src/nsc/checker/` 手写行数 **≤ 1500**（`spec/BUDGETS.yaml`）。超了说明知识被埋进代码，**把它抽回 `spec/`**。
- 禁止在 Python 里写业务规则 `if`。规则一律写进 `spec/checks/**.yaml`。
  - 反例：`if len(brand_moments) > 2: raise`
  - 正例：新增 `spec/checks/brand/BM-001.yaml`
- 禁止在 prompt/代码里硬编码自然语言知识（"台词要口语化"）。这类知识去 `spec/rubrics/` 或 `spec/rules/L3_canonical/`。
- 禁止新增编排框架（LangGraph/CrewAI/Prefect/Airflow）。编排 = 纯 Python 函数 + `@cached_pass` 装饰器。
- 禁止新增数据库（Postgres/Neo4j/Milvus）。只有 SQLite + sqlite-vec。
- 禁止多智能体互评/辩论。
- 每个 LLM 调用必须经 `src/nsc/runtime/models.py` 的路由，不得直接 `openai.` / `litellm.completion`。
- 每个产物必须写 `provenance`（`src/nsc/runtime/provenance.py`）。

## 3. 命名与 ID
- 节点 ID：ULID（`python-ulid`），**内容无关、永不复用**。生成后不可变。
- 规则 ID：`<域>-<序号>`，如 `BM-001` `STR-007`。永不复用，退役只改 `status`。
- 案例 ID：`case:NNNN`，四位零填充。

## 4. 你不需要问我就可以做的决定
选库（在已定栈内）、拆文件、改函数签名、重写 `src/`、补测试、改注释。

## 5. 你必须停下来问我的决定
改 `spec/ir/**`（IR 模式）、改 `spec/checks/**` 的 `severity: block`、改 `eval/thresholds.yaml`、引入新第三方服务、改 `profiles/_schema.py`。
这些一律先写 ADR（`adr/`），标 `status: proposed`，在 PR 里等确认。

## 6. 上下文导航（按需读，不要全读）
| 我要做的事 | 先读 |
|---|---|
| 改/加编译 Pass | `spec/passes/CONTRACTS.md` → `spec/passes/signatures.py` → `spec/passes/dep_graph.yaml` |
| 改/加检查规则 | `spec/checks/DSL.md` → `spec/checks/_schema.yaml` |
| 改判官 | `spec/rubrics/rubric_v1.yaml` → `spec/rubrics/pairwise_protocol.md` → `docs/SOP_JUDGE_CALIBRATION.md` |
| 做反向对齐 | `docs/SOP_FEEDBACK_INGEST.md` → `src/nsc/feedback/` |
| 跑 GEPA | `docs/SOP_GEPA.md` → `src/nsc/optimize/gepa_metric.py` |
| 逆向标注 | `docs/SOP_REVERSE_ANNOTATION.md` |
| 找现成方案别自己造 | **`docs/BORROW_MAP.md`（先读这个！）** |

## 7. 反模式清单（见到就重构）
- 把 checker 报错信息写成 `"invalid"` → 必须写成可直接喂给 GEPA 的诊断句（见 `spec/checks/DSL.md` §5）。
- 在 Pass 里 `try/except: pass` 吞掉结构错误 → Pass 必须抛 `PassFailure` 并带 `node_id`。
- 生成新 ULID 覆盖已有节点 → 局部重编译必须**保留未变节点的 ID**（`src/nsc/runtime/ir_io.py::merge_preserving_ids`）。
- 判官分直接当门禁而未校准 → 见 D8，未过校准门槛的判官只能出报告。