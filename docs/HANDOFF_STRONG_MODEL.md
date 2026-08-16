# 强模型交接书（Strong-Model Handoff）

> 由脚手架 Agent 交接。**读到这份文件 = 强模型（tier_plan / tier_draft）的开工指令。**
> 当前分支：`main`，已 `make ci-local` 全绿（135 passed, 10 skipped）。交接时未 commit 的部分已由接手方先 commit。

---

## 1. 当前状态（脚手架已完成）

已落地并全绿：
- 工具链：`pyproject.toml` / `Makefile` / `.pre-commit-config.yaml` / `config/models.yaml` / Langfuse
- IR 模式与 16 条不变量：`spec/ir/{nodes,overlays,container}.py` + `spec/ir/invariants.py`
- IR IO 与视图：`src/nsc/runtime/ir_io.py`（`build_view` / `emotion_curve` / `__` 派生字段）
- Checker 解释器 + 48 条规则：`src/nsc/checker/` + `spec/checks/**`（每条有 pass/fail fixture）
- Spec 守卫：`src/nsc/guards/*`（spec_reduction / checks_schema / prompts_untouched / ir_schema_diff / budgets / rules_conflict）
- `make ci-local`（lint + typecheck + spec-guard + test-fast）全绿

**尚未实现**（= 强模型边界）：
| 工单 | 内容 | 为什么必须强模型 |
|---|---|---|
| T-06 ⭐ | 黄金 IR fixture（`tests/fixtures/golden/demo_tea_ir.json`） | 需要品味：把 6 集短剧落到可判定的 IR，且通过全部 L0。这是后面一切回归的地基。 |
| T-07 ⭐ | 8 个编译 Pass（`src/nsc/passes/p0..p7`）+ LLM 路由 + 依赖闭包重编译 | p1–p6 是叙事生成，路由到 `tier_plan`/`tier_draft`；种子指令在 `spec/passes/signatures.py`。 |

---

## 2. 强模型边界与模型路由

`config/models.yaml` 的 tier → Pass：
- `tier_plan`（gpt-5.1，昂贵强模型）：`p1_bible`、`p2_arc`、`p3_beatsheet`
- `tier_draft`（gpt-5.1-mini→**用前必核对**，见 models.yaml 注释）：`p4_scene`、`p5_dialogue`、`p6_prose`
- `tier_bulk`：纯机械批量（本阶段不用）
- `tier_reflect`（claude-opus-4.5）：GEPA reflection（P2 阶段，本阶段不实现）
- `p0_intake` 轻量补全：小模型即可；`p7_render`：**零 LLM**（纯工交，不属于强模型）

**所有 LLM 调用必须经 `src/nsc/runtime/models.py` 的路由**（T-04，尚未实现，见 §4 阻塞项）。禁止直接 `openai.` / `litellm.completion`。

---

## 3. T-06 黄金 IR（先做，越早越稳）

**目标**：`tests/fixtures/golden/demo_tea_ir.json` —— 基于 `examples/demo_tea/brief.yaml` 的完整 6 集 IR，含 Line 与 **2 章小说**，`nsc check tests/fixtures/golden/demo_tea_ir.json` 全绿。

**硬要求**：
- IR 结构必须完全符合 `spec/ir/nodes.py` 与 `spec/ir/container.py`（`NarrativeIR.container()` 的 schema）。
- 节点 ID：ULID（`python-ulid`），内容无关、永不与别处冲突。
- 每集：`episode`(hook_promise/cliffhanger) → `scene`(goal/conflict/turn/entry/exit) → `beat`(beat_kind/emotion/est_duration_s) → `line`。
- 植入：`must_cover` 卖点（no_sucrose）必须落成一个 `brand_moment` Beat，且不与 hook 相邻。
- 品牌红线零出现：禁用词（`最好喝`/`第一名`/`唯一`/`治疗`）、竞品名（`茗香茶语`）、`facts` 之外的数字参数。
- **2 章小说**：`chapters` 必须覆盖各自所属集**全部** Beat（`NOV-001`：`__beat_coverage == 1.0`）。
- 全部 L0 规则（`spec/checks/**`）通过。用 `scripts/verify_fixture.py` 或 `nsc check` 自验。

**自己动手写，不要外包**：这是"品味"的注入口（WORK_ORDERS §派单建议）。

---

## 4. T-07 8 个编译 Pass

**前置阻塞（必须先补，否则 Pass 无法跑）**：
1. `src/nsc/runtime/models.py`（LiteLLM 路由 + 成本统计 + Langfuse trace）+ `src/nsc/runtime/provenance.py` + `src/nsc/runtime/cache.py`（T-04）。
2. `src/nsc/passes/__init__.py` 的 `@cached_pass` 装饰器与 `PassFailure(node_id, reason)` 异常。

**实现范围**（每 Pass 一个 DSPy Module）：
- 种子指令 = `spec/passes/signatures.py` 的 docstring（资产，**不要手改**；GEPA 演化后写 `prompts/`）。
- 输入/输出/粒度读 `spec/passes/dep_graph.yaml`（`passes.*.reads/writes/granularity`）。
- 失败语义：结构性失败抛 `PassFailure` 带 `node_id`，禁止静默降级。
- 局部重编译：依赖闭包 + `merge_preserving_ids`（INV-16，`IR 未变节点 ID 必须保留`）。

**验收命令（CI 里可跑）**：
- `nsc run --brief examples/demo_tea/brief.yaml` 端到端产出 6 集，L0 全绿（标 `llm`）。
- `nsc recompile --episode 5` 只触发第 5 集的 p3–p7（用 `runs` 表断言）。
- `tests/test_recompile.py::test_voice_change_only_invalidates_prose` 绿（改 `NarrativeVoice` 只重跑 p6/p7）。

---

## 5. 给强模型的生成提示词（种子）

> 规则：**提示词不允许写在 `prompts/*.json` 里手工改**（B1，只能由 `nsc optimize`/`nsc compile-prompts` 写入）。
> 因此强模型只负责把 `signatures.py` 的 docstring 落实为可运行的 DSPy Module，并手写黄金 IR 验证。

每趟生成的核心不可违背约束（浓缩自 signatures.py）：

- **p1_bible**：至少一个 `role=customer_proxy`（persona_ref 指向 `brand.audience`）；角色总数 ≤ `max_characters`；每角色 voice_notes + 1–3 voice_tics；地点从 `usage_scenes[shootable=true]` 派生或标 cost_tier。
- **p2_arc**：集数/时长照 profile；每个 `must_cover` 卖点分配 ≥1 槽位并写 modality/plot_connection；每集 hook_promise，非末集 cliffhanger。
- **p3_beatsheet**（系统命门）：Beat 细到可独立判定；恰好一个 hook 且在 1–2 位；末 Beat 为 cliffhanger/resolution/cta；每个植入落成 brand_moment 且不邻 hook；总时长贴 `duration_target_s`；声明 ≥1 组 setup→payoff（跨集 payoff 写 `PENDING:<slug>`）；summary 必须是"谁做什么导致什么"。
- **p4_scene**：相邻同地 Beat 合并；场景数 ≤ `max_scenes_per_episode`；每场 goal/conflict/turn/entry/exit 非空；entry=最晚可进、exit=最早可离；不引入 bible 外角色/地点。
- **p5_dialogue**：只用在场角色；对白 ≤ `max_line_chars`；体现 turn；brand_moment 场禁止角色宣读参数、只用 `facts` 内数字；`must_include_lines` 原文出现；禁用词零出现。
- **p6_prose**：只编织叙述层，禁止发明事件/角色/对白语义（`NOV-002` 相似度 ≥0.7）；输出完整 `anchor_map` 覆盖 100%（`NOV-001`）；单段 ≤ `paragraph_max_chars`；视角/时态照 NarrativeVoice。

---

## 6. 完成定义（DoD）

- `make ci-local` 全绿。
- `nsc run --brief examples/demo_tea/brief.yaml` 端到端出 6 集小说 + 剧本，L0 全绿。
- 黄金 IR 通过 `nsc check`。
- 局部重编译单集 + 锚点往返 100%（P0 退出条件）。
- 若改了 `spec/ir/**` / `spec/checks/**` 的 `severity: block` / `eval/thresholds.yaml` / 引入新第三方服务 → 先写 ADR（`adr/`）标 `status: proposed`，随 PR 等确认。