---
name: Agent 工单
about: 派给 AI Agent 的独立可验收任务
labels: [agent-task]
---
## 工单号
T-

## 目标（一句话）

## 必读上下文（不要读整个仓库）
- [ ] `AGENTS.md`
- [ ] `docs/BORROW_MAP.md` 第 __ 条
- [ ] 其他：

## 依赖
⇐ T-

## 交付物（文件清单）

## 验收命令（必须能在 CI 跑）
```bash
```

## 硬约束
- [ ] 不在 Python 里写业务规则
- [ ] 不手改 `prompts/`
- [ ] 行数在 `spec/BUDGETS.yaml` 预算内
- [ ] 新增 check 规则有 pass/fail fixture 且 message 是完整诊断句

## 如果你发现需要改 `spec/ir/**`
**停下来**，写 ADR（`adr/`，status: proposed），在 PR 里等人工确认（AGENTS.md §5）。