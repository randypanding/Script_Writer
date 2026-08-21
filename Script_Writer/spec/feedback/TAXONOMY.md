# 编辑分类学（D11）

每处人类编辑必须且只能归入一类。`nsc ingest` 的自动分类器输出候选，你在 Langfuse 队列确认。
分类体系与自动分类的做法借鉴 IteraTeR 的编辑意图标注（`docs/BORROW_MAP.md #10`）。

| dimension | 定义 | 典型信号 | 它应该改进什么 |
|---|---|---|---|
| `structural` | Beat 序列/弧线/伏笔错 | 整段搬移、删除整个 Beat、补一个转折 | **北极星指标的分子**；改 p2/p3 的 prompt 与 STR-* 规则 |
| `character` | 动机不成立、角色声音不一致 | 改动机说明、换说话人、改语气 | p1 的 voice_notes 设计、DLG-004 |
| `placement` | 植入生硬/位置错/次数错 | 删除夸产品的台词、后移植入、改成动作 | p2/p3 的植入规划、BM-* 规则、rubric#placement_integration |
| `dialogue` | 腔调、口语度、长度、节奏 | 缩短长句、去掉解释性台词、加打断 | p5 的 prompt、DLG-002/005、rubric#naturalness |
| `factual` | 产品信息错、参数错 | 改数字、改产品名 | FCT-001、BrandBrief 补全 |
| `compliance` | 合规/法律风险 | 删绝对化用语、删功效断言 | CMP-* 规则、`_legal_sources.md` |
| `producibility` | 超预算、场景不可得、演员不够 | 删场景、合并地点、减角色 | PRD-* 规则、Profile 预算 |
| `taste` | 无可归纳理由的个别偏好 | "我们不喜欢这个名字" | **只能进该客户的 Client Pack** |

## 硬约束 `[[form:check]]` → `nsc.guards.rules_conflict`
- `taste` 类观察**不得**参与 L0→L1 的全局聚类，只能产出 `scope: {kind: client}` 的规则。
- 分类为 `structural` 的编辑数是北极星指标（D22）的分子，**统计必须按此分类分解**，混算等于没算。