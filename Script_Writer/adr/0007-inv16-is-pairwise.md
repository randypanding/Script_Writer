# ADR-0007：INV-16 是成对不变量，单 IR 的 check_all 跳过它

- 状态：proposed
- 日期：2026-08-16
- 影响层：A1 本体（`spec/ir/invariants.py`，无 schema 变化）

## 背景
T-06 黄金 IR 落地后，`check_all(ir, profile, stage="final")` 会遍历全部 16 条不变量，
其中 `inv_16_id_stability(old, new)` 需要**两份** IR（重编译前/后）才能判定，
单 IR 调用必然 `TypeError`。`tests/test_invariants.py::test_golden_ir_passes_all`
以 `stage="final"` 调用 `check_all`，黄金 IR 一提交即触发该崩溃。

## 决定
`check_all` 把 INV-16 归入"成对不变量"集合（与 `_SCHEMA_GUARANTEED` 并列的跳过表），
单 IR 检查不执行它；INV-16 的执法点是 `merge_preserving_ids` 的调用方与
`tests/test_recompile.py` / `test_id_stability`。

## 被否决的替代
| 替代 | 为什么否决 |
|---|---|
| 给 `inv_16` 加默认参数 `new=None` 并静默通过 | 静默通过 = 假绿，违反"失败必须抛诊断"的精神 |
| 把 INV-16 移出 `ALL_INVARIANTS` | 破坏 `test_all_invariants_have_implementation` 的 16 条计数契约 |

## 对下游的约束
任何"局部重编译"实现（T-07）必须显式调用 `inv_16_id_stability(old, new)` 做断言，
不得依赖 `check_all` 兜底。

## 迁移
无（无 schema / 无数据变化）。

## 验证
`pytest tests/test_invariants.py` 在黄金 IR 存在时全绿；
`tests/test_recompile.py` 直接断言 `inv_16_id_stability`。
