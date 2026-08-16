# 规则晋升流水线（D12）

```
L0 observation  ──聚类≥3──▶ L1 candidate ──留出集验证──▶ L2 validated ──人工 approve──▶ L3 canonical
                                                                              │
                                                                    hit_count=0 90天 / 冲突
                                                                              ▼
                                                                        deprecated
```

## 目录
- `L0_observations/` 自动写入，一条一文件，`obs_<ulid>.yaml`。**不参与任何门禁。**
- `L1_candidates/` 由 `nsc mine run` 生成，`cand_<slug>.yaml`。CI 只校验 schema。
- `L2_validated/` 通过留出集验证，附验证报告。**仍不参与门禁**（避免过早锁死）。
- `L3_canonical/` 人工 approve。**此时才允许**：① 生成 `spec/checks/**.yaml` ② 进 rubric ③ 进 prompt 拼装 ④ 进 Profile 默认值。

## 晋升门槛
| 跃迁 | 条件 | 执行者 |
|---|---|---|
| L0→L1 | 同簇观察 ≥3 条，且来自 ≥2 个不同 case | `nsc mine cluster`（HDBSCAN，见 BORROW_MAP #20） |
| L1→L2 | **checker 型**：在留出集上 precision ≥0.80、在人类已接受交付物上误报率 ≤0.05、recall ≥0.30<br>**rubric/prompt 型**：目标维度 Δ ≥ +0.15（成对胜率），其余维度非劣（下降 ≤0.05） | `nsc mine validate`（CI 可复现） |
| L2→L3 | 人工 approve（PR 标签 `rule-promote` + 你 approve） | 你 |
| →deprecated | `hit_count == 0` 且 `last_fired_at` 超 90 天；或与新规则判定冲突且新规则胜出 | `nsc mine retire`（每周 cron） |

## 反膨胀
`L3_canonical/` 上限 **120 条**（`spec/BUDGETS.yaml::max_canonical_rules`）。达到上限后新增必须先合并或退役同域旧规则。CI 强制。
理由：规则库的价值在精不在多；ExpeL/Voyager 的经验是无门禁的经验池会自我矛盾（BORROW_MAP #12）。

## scope 与"口味性"隔离
`scope: client:<brand_id>` 的规则**只**加载到该 Client Pack，永不进全局。
`D11` 分类为 `口味性` 的反馈**只能**产出 `scope: client:*` 的规则。CI 检查此约束（`nsc.guards.rules_conflict`）。