# ADR-0001：Narrative IR 是唯一真相，剧本与小说都是渲染视图

- 状态：accepted
- 日期：2025-01-01
- 影响层：A1

## 背景
商业营销短剧需要在多轮客户反馈中积累经验。若交付物是散文，客户说"第 3 集那句太硬"无法变成训练信号。

## 决定
采用带稳定 ULID 的分层叙事 IR（`spec/ir/`）。剧本（Fountain）、小说（docx/md）、分镜表全部是 IR 的渲染视图。

## 被否决的替代
| 替代 | 为什么否决 |
|---|---|
| 直接用 Fountain 作为主表示 | 无法锚定、无法机检、无法差分 |
| 自由 JSON 不带稳定 ID | 客户第二轮反馈就对不上号 |
| 图数据库（Neo4j） | 1 人运维的过度工程；SQLite + 邻接表足够 |

## 对下游的约束
- 任何交付格式的新增 = 新增一个 renderer，不得新增主表示。
- 局部重编译必须保留未变节点的 ID（INV-16），这是最高优先级测试。

## 验证
`tests/test_invariants.py::test_id_stability`、`tests/test_anchor_roundtrip.py`