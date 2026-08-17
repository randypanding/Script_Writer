# ADR-0013：新模块 src/nsc/{textstats,revise,context} 与 BUDGETS 调整

- 状态：accepted（项目负责人 2026-08-17 指令授权，见 `docs/UPGRADE_PLAN_2026-08-17.md` §0）
- 日期：2026-08-17
- 影响层：B2 生成物（三个新模块）+ A2 约束（`spec/BUDGETS.yaml` 预算条目）

## 背景

外部方案吸收带来三类新机制代码：① 确定性文本统计（ADR-0011）；② 修订基础设施（spot-fix patch、revisionGate、快照链、Idea Bank、修订 brief 合成——inkos/autonovel/One-Sentence 三源验证）；③ 上下文预算竞争与历史压缩（FicForge P0-P5 + StoryWriter MessageRedact）。现状约束：`src/nsc/runtime + src/nsc/checker` 已 1433/1500 行，余量不足以容纳这些机制；D21 要求"知识抽回 spec/"，而这些是**机制**不是知识，正确解法是独立模块 + 独立预算。

## 决定

1. 新增三个模块与预算条目：
   - `src/nsc/textstats/`：**300 行**。纯函数文本统计，零业务参数（词表/阈值全由 YAML 规则传入），零 LLM。
   - `src/nsc/revise/`：**500 行**。`patch.py`（两级匹配 spot-fix，≥50% 落位门槛）/ `gate.py`（strict/lenient/always 三档）/ `snapshot.py`（SQLite 内容哈希快照链 + 回退）/ `idea_bank.py` / `revision_brief.py`（五节 brief：PROBLEM/KEEP/CHANGE/VOICE/TARGET）。
   - `src/nsc/context/`：**500 行**。`assembler.py`（P0-P5 预算竞争 + core_guarantee=400 token 低保）/ `compress.py`（中间历史压至 ~10%，走内容寻址缓存）。
2. `BUDGETS.yaml` 调整：`src/nsc/runtime,src/nsc/checker` 1500→**1600**（registry 薄注册 ≈40 行 + ir_io 视图派生 ≈60 行，均为机制）；`src/nsc` 总量警戒线 6500→**7800**。
3. T-27 前置任务：核对 `guards/budgets.py` 计数口径与 `wc -l` 的差异（账面 10166 已超旧警戒线但 guard 未红），把口径写进 BUDGETS.yaml 注释。
4. 修订门禁与快照**不用 git**：快照存 SQLite（项目单一数据存储约束不变），内容哈希寻址。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 机制塞进 runtime/checker 现有文件 | 必然击穿 1500 硬预算；且三类机制职责独立，应独立测试 |
| 快照用 git commit/reset（autonovel 路线） | 粒度过粗（整文件取舍），与 ULID 节点级局部重编译冲突 |
| brief 合成放 optimize/ | optimize 账面已超 700 预算；brief 与 patch/gate 同属修订闭环，内聚放 revise/ |
| 预算不调整硬塞 | 会导致 spec-guard 红或倒逼代码里埋业务知识，两头都违反 D21 |

## 对下游的约束

- 三个新模块禁止出现业务词表/业务阈值/业务 if；参数一律来自 spec 或 profile。
- revise 与 context 的公开接口以 `docs/UPGRADE_PLAN_2026-08-17.md` §6 的签名为准；改签名不需 ADR，改语义需要。
- 每层上下文 token 消耗写入 DB `runs` 表扩展字段（不动 IR Provenance 冻结模式）。

## 迁移

纯新增。回滚 = 删除三个模块、还原 BUDGETS.yaml。

## 验证

- `make spec-guard`（budgets 守卫）绿。
- textstats 每函数 ≥3 边界 case；patch 两级匹配/唯一性/50% 门槛、gate 三档公式、快照回退往返均有测试。
