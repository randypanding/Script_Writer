# 门禁全景（谁能拦你，拦多久）

## 三层校验（D6）与 CI 的对应
| 层 | 内容 | CI job | 阻塞 | 典型耗时 | 成本 |
|---|---|---|---|---|---|
| **L0-a 结构** | Pydantic + 16 条不变量 | `tests (no LLM)` | ✅ | 20s | $0 |
| **L0-b 约束** | 34+ 条声明式规则 | `tests (no LLM)` | ✅ | 30s | $0 |
| **L0-c 资产纪律** | D2 归约 / prompts 未手改 / 行数预算 / 规则冲突 | `spec guard` | ✅ | 15s | $0 |
| **L0-d 黄金回归** | 渲染快照 + 锚点往返 | `golden regression` | ✅ | 40s | $0 |
| **L1 判官** | 5 维 rubric，成对为主 | `LLM Eval` | ⚠️ **仅聚合分 < 阈值且 `JUDGE_GATE_ENABLED==true`** | 5–15min | $1–3 |
| **L2 人类** | 抽样评审 → 结构化 diff | 不在 CI | ❌ 不阻塞，产出资产 | 天 | 你的时间 |

## 为什么判官门禁可以被自动关闭
判官分会漂移。`judge-calibration.yml` 每周测量判官与人类的一致率，
低于 `pairwise_gate: 0.78` 时把仓库变量 `JUDGE_GATE_ENABLED` 置 false 并开 Issue。
**用一个未校准的仪器做质量决策，比不做决策更糟。**（D8）

## 成本护栏
- `nsc eval l1 --max-cost-usd` 是**硬停机**，不是事后报告。
- PR 不打 `affects-generation` 标签 → 不跑 LLM → 单个 PR 成本 $0。
- nightly 抽 40 条，日成本上限约 $3；`config/models.yaml::budgets` 是唯一真相。

## 本地必须跑通才提 PR
```bash
make ci-local     # = lint + typecheck + spec-guard + test-fast
```

## 逃生阀
只有仓库 admin 可以 bypass（`bypass_actors`），且必须在 PR 描述里写明原因。
每次 bypass 会被 `metrics.yml` 统计并进周报——**bypass 次数上升是架构在腐烂的第一信号。**