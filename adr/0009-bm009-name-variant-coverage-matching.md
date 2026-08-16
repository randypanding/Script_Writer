# ADR-0009：BM-009 用覆盖感知匹配判定产品名违规

- 状态：accepted
- 日期：2026-08-16
- 影响层：A2 约束（spec/checks/brand/BM-009.yaml）+ B2（checker DSL 新增函数）

## 背景

BM-009 原判式 `not contains_any(item.text, bad)` 是纯子串匹配。当品牌的别名是
规范名的子串时（demo_tea：别名"轻乳茶" ⊂ 规范名"清野轻乳茶"），任何正确使用
规范名的台词都会被误判为违规——系统在 T-18 泛化压测（LongCat-2.0 真实编译）中
每条含"清野轻乳茶"的台词都被 block，交付物无法通过 L0，规则事实上不可满足。

## 决定

BM-009 改用 `contains_name_variant(text, bad, canon)`：先标记规范名在文本中的
出现区间为"已覆盖"，bad 变体只有出现在覆盖区间之外才计违规。规范名内的合法
子串不再误报；单独误用别名（如只说"轻乳茶"不带品牌前缀）仍然被拦。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 从禁用集剔除"是规范名子串"的别名 | 别名单独误用（丢品牌前缀）将永远无法拦截，规则失效面更大 |
| 改 brand.yaml 删除别名 | 别名服务检索/归一化，删数据治标不治本，且问题在任何"别名⊂规范名"的品牌上复现 |
| 忽略 BM-009（降级 severity） | 触碰 severity: block 红线（AGENTS.md §5），且放弃命名管控这一品牌合同要求 |

## 对下游的约束

- 产品名类规则必须用 `contains_name_variant`，不得退回纯 `contains_any` 子串匹配。
- `__forbidden_name_variants` 的派生（ir_io._brand_view）不得把与规范名完全相同
  的字符串加入禁用集（去空格变体仅在不同于规范名时成立）。

## 迁移

非 breaking：规则语义收紧（减少误报），既有 pass/fail fixture 全部保持原判定
（fail.json 的单独"轻乳茶"仍 fire）。回滚方式：把 BM-009 assert 改回
`not contains_any(item.text, bad)`（误报会一并回来）。

## 验证

- `tests/test_checker_dsl.py::test_rule_pass_and_fail[BM-009]`（fail 仍 fire、pass 不 fire）
- `tests/test_brand_view.py`（覆盖语义与派生回归）
- T-18 真实压测：含规范名的台词不再被 BM-009 误拦（out/stress*/report.md）
