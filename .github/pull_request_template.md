## 这个 PR 改的是哪一层？（必选其一）
- [ ] **A 资产层**（`spec/` `profiles/` `brands/` `cases/export/`）→ 必须打标签 `asset-change` 并附 ADR
- [ ] **B 生成物层**（`src/` `tests/`）→ 无需 ADR
- [ ] 文档 / CI

## 工单
Closes #  ·  工单号：T-

## 验收命令（贴出你本地跑通的输出）
```
make ci-local
```

## 检查表
- [ ] 测试先红后绿（贴出先失败的证据或说明为什么不适用）
- [ ] 没有在 Python 里写业务规则（新增业务约束都进了 `spec/checks/`）
- [ ] 新增/修改的每条 check 规则都有 `pass.json` / `fail.json` fixture
- [ ] 新增 check 规则的 `message` 是完整诊断句（DSL §5），而不是日志
- [ ] 没有手改 `prompts/`
- [ ] 手写行数仍在 `spec/BUDGETS.yaml` 预算内
- [ ] 若改了 IR：附了 `db/migrations/` 或 `migrations/ir/` 脚本与 ADR
- [ ] 若改了 rubric：重跑了 `make judge-cal` 并贴出一致率

## 影响生成结果吗？
- [ ] 是 → 请打标签 `affects-generation`（会触发 L1 判官评测，约 $1–3）
- [ ] 否