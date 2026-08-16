# Checker 规则 DSL 规范（D7）

## 0. 设计原则
**不自己写解析器。** `select` 用 [JMESPath](https://jmespath.org/)，`assert` 用 `simpleeval` + 白名单函数表。
解释器（`src/nsc/checker/interpreter.py`）目标 ≤300 行。见 `docs/BORROW_MAP.md #22`。

## 1. 文件布局
`spec/checks/<域>/<RULE-ID>.yaml`，一文件一规则。域：`structure` `brand` `dialogue` `novel` `compliance` `producibility` `fact`。

## 2. 字段
```yaml
id: BM-001                       # 必填，全局唯一，永不复用
title: 单集品牌植入数不超过预算    # 必填，中文一句话
domain: brand                    # 必填
severity: block                  # block | warn | info
stage: after_p3                  # 最早可检查阶段：after_p2|after_p3|after_p4|after_p5|after_p6|final
scope:                           # 生效范围；缺省 = 全部
  profiles: [short_drama_v1, short_video_v1]
  industries: []                 # 空 = 全行业
select: "episodes[*]"            # JMESPath，作用于 ir.view()
group_by: null                   # 可选 JMESPath，对 select 结果再分组
bind:                            # 把 JMESPath 求值结果绑成变量给 assert 用
  moments: "beats[?beat_kind=='brand_moment']"
  limit: "@.__ctx.brand.placement.max_moments_per_episode"
assert: "count(moments) <= limit"     # simpleeval 表达式，返回 bool
message: "第 {item.no} 集有 {count(moments)} 处品牌植入，超过预算 {limit} 处。请合并或删除强度最低的一处。"
fix_hint: "优先删除 intensity<=2 且 plot_connection=='none' 的植入。"
evidence: [case:0142, case:0177]  # canonical 规则必填（spec-guard 检查）
rule_ref: R3-0031                 # 可选，指向 spec/rules/L3_canonical/
legal_ref: ""                     # compliance 域必填
tags: [density, budget]
```

## 3. `assert` 可用函数表（白名单，实现在 `src/nsc/checker/registry.py`）
| 函数 | 说明 |
|---|---|
| `count(xs)` | 长度 |
| `min_gap(xs, key='linear_index')` | 相邻元素在 key 上的最小差值；<2 元素返回 `inf` |
| `spread(xs, key)` | 最大值-最小值 |
| `positions(xs, total)` | 归一化位置列表 `[0,1]` |
| `distinct(xs, key)` | 去重后数量 |
| `any_of(xs, pred)` / `all_of(xs, pred)` | pred 为字符串表达式，变量名 `x` |
| `chars(s)` | 中文字符数（去空白与标点，实现见 registry） |
| `regex_any(s, patterns)` | 任一命中 |
| `contains_any(s, words)` | 任一子串命中 |
| `contains_name_variant(s, bad, canon)` | bad 变体出现且不被任何 canon 规范名的出现区间覆盖（ADR-0009，产品名判定专用） |
| `lcs_len(a, b)` | 最长公共子串长度（FCT-002 用） |
| `sim(a, b)` | rapidfuzz 归一化相似度 0–1 |
| `emotion_range(beats)` | max(valence)-min(valence) |
| `monotone_runs(beats)` | 情绪单调连续段的最大长度 |
| `exists(path)` | JMESPath 在当前 item 下非空 |
| `order_of(node_id)` | 全局 linear_index |
| `sum_of(xs, key)` | 求和 |
| `pct(a, b)` | a/b，b==0 返回 0 |

**禁止**：`__`、`import`、属性链超过 3 级、任何 IO。`simpleeval` 已限制，但 `registry` 需二次白名单。

## 4. 求值上下文
`select` 的每个结果为 `item`。表达式内可用：
- `item`：当前对象（dict）
- `ctx.profile` / `ctx.brand` / `ctx.ir`：全局上下文
- `bind` 中声明的变量
- `count(...)` 等白名单函数

## 5. `message` 写作规范（**这条决定 GEPA 的效果，见 D13/胜负手**）
message 会**原样**进入 GEPA 的 feedback 通道。必须满足：
1. **说清违反了什么**（含具体数值/节点）
2. **说清为什么这是问题**（一句业务理由）
3. **给出可操作方向**（`fix_hint` 或 message 内含）

- ❌ `"brand moment density violation"`
- ❌ `"植入太多了"`
- ✅ `"第 3 集有 4 处品牌植入，超过预算 2 处；植入密度过高会打断叙事沉浸、显著降低观众看完率。请合并第 2、3 处（都在讲同一个卖点 '0 蔗糖'），并删除 intensity=1 的背景出现。"`

## 6. 测试要求
每条规则必须在 `tests/fixtures/checks/<RULE-ID>/` 下提供：
- `pass.json`：一个应通过的最小 IR 片段
- `fail.json`：一个应触发的最小 IR 片段
- `expected.txt`：期望 message（允许 `{{...}}` 通配）
`tests/test_checker_dsl.py` 会自动发现并跑全部规则。**无 fixture 的规则 CI 失败。**
（此结构借鉴 CheckList 的 MFT 组织方式，见 `docs/BORROW_MAP.md #13`）