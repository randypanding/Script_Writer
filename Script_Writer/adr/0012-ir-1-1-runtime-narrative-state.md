# ADR-0012：IR 1.1 · 运行时叙事状态层

- 状态：accepted（项目负责人 2026-08-17 指令授权，见 `docs/UPGRADE_PLAN_2026-08-17.md` §0）
- 日期：2026-08-17
- 影响层：A1 IR 模式（`spec/ir/**`，schema_version 1.0→1.1）+ A2 约束（INV-17..20 + Wave B 规则 7 条）+ B2 生成物（视图派生、Pass 签名扩展）

## 背景

共识 C（5/8 外部方案）：长篇一致性的答案是**显式长期记忆/真相层**，且要有运行时生命周期。NSC 的 IR + Bible + SetupPayoff 只覆盖"编译期声明"：第 5 集埋的伏笔到第 40 集是否回收、角色关系何时反转、数值状态（暗线进度）跨集是否连贯，编译完成后无任何结构追踪。外部给出两套已验证规格：FicForge 的 Fact 生命周期（status/resolves 级联/caused_by/known_to-hidden_from）与 novel-distiller 的暗线数值状态（variables + dark_threads.stages + 每集快照）。同时 One-Sentence/StoryWriter 验证了场级节奏显式化字段与知识状态线。

## 决定

1. **新增四个覆盖层**（声明式存储，规格全文见方案 §4.1）：
   - `Fact`：status(active/unresolved/resolved/deprecated)、type 六类、resolves、caused_by、known_to/hidden_from、suspense_type、narrative_weight、thread_ids（成员关系唯一真相源在 Fact 侧）。
   - `Thread`：title/state/status(active/resolved/dormant)，不存 fact_ids（防双向漂移）。
   - `StateVariable`（key/type/initial）与 `DarkThread`（key/stages[]）。
2. **状态变更是声明不是改写**：`Episode.state_changes: list[StateChange]` 由 p3 声明；`build_view` 确定性派生 current 值（number 累加 / string 覆盖 / 阶段步进累加）。IR 不被运行时改写，杜绝 FicForge ops 日志与磁盘漂移的坑。
3. **既有节点扩展**（全部可选默认空）：Scene += `opening_attractor/escalation_beats/ending_hook/knowledge_state`；Episode += `responds_to/state_changes`；Character += 心智 OS 四字段（mental_models ≤5、decision_heuristics ≤7、honest_boundaries、expression_dna，novel-distiller SKILL.md 的结构化子集）。
4. **新不变量**：INV-17（resolves 引用与级联一致）、INV-18（caused_by 时序）、INV-19（阶段/数值界内）、INV-20（responds_to 引用合法）。
5. **Wave B 检查规则 7 条**：FCT-003（高权重伏笔逾期）、FCT-006/007（每集状态推进与原因）、STR-016（悬念 ≤3 集闭环）、STR-017（首末场节奏字段）、STR-018（反转密度）、DLG-008（对白对仗句式），全部 warn/info。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| KG 图库 / 独立关系表 | NovelForge 的 KGRelation 用 Fact(type=relationship)+INV-17/18 等价覆盖，零新依赖（仅 SQLite 约束不变） |
| 运行时直接改写 IR 状态 | 破坏"IR 是唯一真相 + 确定性重编译"；派生视图等价且可重放 |
| Markdown 真相文件（inkos 路线） | 不可校验、100 章后读写膨胀（反模式 #3）；IR 节点可 diff 可校验 |
| SetupPayoff 拆除重建 | 向后兼容：SetupPayoff 保留，Fact(type=foreshadowing) 是其泛化，二者并存 |

## 对下游的约束

- p1/p2/p3/p4 签名扩展后，`prompts/` 由 `nsc compile-prompts`/GEPA 重新生成，禁止手改。
- Facts 的跨集前向引用复用 `PENDING:<slug>` 既有解引用机制，不得新造。
- `merge_preserving_ids` 行为不变：主干节点零改动，ID 稳定性测试必须全绿。

## 迁移

`schema_version 1.0→1.1`：旧 JSON 加载时自动补默认空字段；新字段全部可选；回滚 = 忽略新字段重序列化。

## 验证

- `tests/test_invariants.py`：INV-17..20 全绿 + `test_id_stability` 回归绿。
- 旧 golden IR 自动迁移后 `nsc check` 结果与迁移前一致。
- Wave B 7 条规则 fixtures 全绿。
