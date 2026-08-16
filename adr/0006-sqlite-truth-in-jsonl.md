# ADR-0006：案例库的持久形态是 JSONL，SQLite 只是工作副本

- 状态：accepted · 日期：2025-01-01 · 影响层：A4

## 决定
`cases/export/*.jsonl` 进 git 且是真相；`cases/cases.db` gitignored，由 `make db-rebuild` 生成。
CLI 每次写库后自动 `db export`。

## 理由
A4 必须可 diff、可 code review、可被 AI 直接读取、可在换机/重写系统时零成本迁移。
二进制 SQLite 进 git 会膨胀且不可审。

## 对下游的约束
任何写库操作必须同时更新 jsonl，否则 `spec-guard` 的 `db_export_fresh` 检查失败。