# ADR-0004：检查规则是数据，解释器是代码

- 状态：accepted · 日期：2025-01-01 · 影响层：A2

## 决定
所有叙事/品牌/合规约束写成 `spec/checks/**.yaml`（JMESPath select + simpleeval assert）。
解释器 `src/nsc/checker/interpreter.py` ≤300 行，不含任何业务判断。

## 被否决
| 替代 | 否决理由 |
|---|---|
| Python if | 规则被埋进可丢弃层，换语言重写即归零 |
| 自研 DSL 解析器 | 无收益的复杂度；JMESPath + simpleeval 已够（BORROW_MAP #22） |
| OPA/Rego | 引入非 Python 运行时，1 人维护不了 |

## 对下游的约束
- `message` 必须是完整诊断句（DSL §5）。它同时是 GEPA 的 feedback 输入。
- 每条规则必须有 pass/fail fixture，否则 CI 失败。