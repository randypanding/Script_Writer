# 工单（可独立派给 Agent，可独立验收）

约定：每张工单 = 一个 PR。标签 `agent-task`。**验收命令必须能在 CI 里跑。**
依赖用 `⇐` 表示。⭐ = 关键路径。

---
## P0 · 地基（~2 周）

### T-01 ⭐ 项目骨架与工具链
**做**：落盘 `pyproject.toml` / `Makefile` / `.pre-commit-config.yaml` / 目录树 / `config/models.yaml`（核对模型 ID）/ Langfuse docker-compose（`ops/langfuse/`）。
**产出**：`uv sync` 成功；`make lint typecheck` 通过（空实现允许）。
**验收**：`make ci-local` 除未实现的测试外全绿；`nsc --help` 输出全部子命令。
**注意**：`config/models.yaml` 里的模型 ID 是我凭记忆写的，**必须核对后修正**。

### T-02 ⭐ IR 模式与 16 条不变量  ⇐ T-01
**做**：落盘 `spec/ir/{nodes,overlays,container}.py`；实现 `spec/ir/invariants.py` 全部函数；
写 `tests/strategies.py`（Hypothesis 的 IR 构造策略）；造 `tests/fixtures/broken/INV-*.json`。
**验收**：`pytest tests/test_invariants.py` 全绿，含 `test_all_invariants_have_implementation`。
**禁止**：往 `invariants.py` 里加业务约束（去 `spec/checks/`）。

### T-03 ⭐ IR IO 与视图  ⇐ T-02
**做**：`src/nsc/runtime/ir_io.py`：`build_view()`（嵌套视图 + `linear_index` + `__` 前缀的派生字段）、
`emotion_curve()`、`merge_preserving_ids()`（INV-16！）、`load/save` + schema 版本迁移入口。
**验收**：`tests/test_invariants.py::test_id_stability` 绿；`build_view` 的 snapshot 测试绿。
**这是全项目风险最高的函数**（`merge_preserving_ids`）：ID 不稳 = 资产归零。写 ≥6 个 case。

### T-04 内容寻址缓存与 Provenance  ⇐ T-03
**做**：`runtime/cache.py`、`runtime/provenance.py`、`runtime/models.py`（LiteLLM 路由 + 成本统计 + Langfuse trace）。
**验收**：`tests/test_cache.py`：同输入二次调用不产生 LLM 调用；改任一版本号即失效；`NSC_NO_CACHE=1` 生效。

### T-05 ⭐ Checker 解释器 + 34 条规则  ⇐ T-03
**做**：`checker/{interpreter,registry,report}.py`；`nsc dev split-checks` 拆分 `_BATCH_1.yaml`；
为**每条规则**造 `pass.json`/`fail.json`。
**验收**：`pytest tests/test_checker_dsl.py` 全绿（含 `test_message_quality`）；`nsc check` 三种 exit code 正确；
`interpreter.py + registry.py` ≤ 400 行。

### T-06 ⭐ 黄金 IR fixture  ⇐ T-02
**做**：手工（可借 LLM 起草后你审）产出 `tests/fixtures/golden/demo_tea_ir.json`：
基于 `examples/demo_tea/brief.yaml` 的完整 6 集 IR，含 Line 与 2 章小说，**通过全部 L0**。
**验收**：`nsc check tests/fixtures/golden/demo_tea_ir.json` 全绿。
**这是后面一切回归测试的地基**，值得花时间。

### T-07 ⭐ 8 个编译 Pass  ⇐ T-04, T-05
**做**：`src/nsc/passes/p0..p7`；`spec/passes/signatures.py` 落盘；实现依赖闭包重编译（读 `dep_graph.yaml`）。
**验收**：`nsc run --brief examples/demo_tea/brief.yaml` 端到端产出 6 集，L0 全绿（标 `llm`）；
`nsc recompile --episode 5` 只触发第 5 集的 p3–p7（用 `runs` 表断言）；
`tests/test_recompile.py::test_voice_change_only_invalidates_prose` 绿。

### T-07b Pass5 增强（rerank + 自检）  ⇐ T-07
默认关闭。`--rerank` 与 `--self-revise` 开关；成本与质量的 A/B 报告进 `out/eval/`。

### T-08 渲染器 + 锚点  ⇐ T-06
**做**：`render/{fountain,novel,docx,storyboard,anchors}.py`；D29 三重锚点；`out/*/manifest.json`。
**验收**：`pytest -m golden`（syrupy 快照）；`tests/test_anchor_roundtrip.py`：
渲染 → 解析回来 → **100%** 恢复 node_id。

### T-09 Spec 守卫（CI 的牙齿）  ⇐ T-05
**做**：`src/nsc/guards/{spec_reduction,checks_schema,prompts_untouched,ir_schema_diff,budgets,rules_conflict}.py`。
**验收**：`pytest tests/test_spec_guard.py` 绿；故意手改一个 `prompts/*.json` 后 `make spec-guard` 必须失败。

**P0 退出条件（一起验收）**：`nsc run` 端到端出 6 集小说 + 剧本，L0 全绿，可局部重编译单集，锚点往返 100%。

---
## P1 · 冷启动与反馈闭环（~3 周）

### T-10 ⭐⭐ 反向对齐器（最高优先级，高于生成质量）  ⇐ T-08
**做**：`feedback/{docx_revisions,align}.py`：OOXML 修订解析（`w:ins`/`w:del`/`w:comment` + 作者 + 时间戳）；
pandoc 兜底；三级锚点恢复；**单调 DP 段落对齐**（禁止贪心）。
**验收**：`tests/test_align.py` 覆盖 5 类编辑（整段删/增/重排/大幅重写/仅标点），
对 `fixtures/ingest/demo_tea_round1.docx` 恢复率 ≥90% 且 node_id 正确率 100%（在恢复成功的条目上）。

### T-11 ⭐ 反馈摄入流水线  ⇐ T-10
**做**：`feedback/{classify,ingest}.py`；`EditClassify` 实现；写 `feedback`/`revision_pairs`/`preference_pairs`/`L0_observations`；
推 Langfuse annotation queue；`nsc ingest docx|text`。
**验收**：一份带修订 docx → 60s 内产出结构化条目；`confirmed_by` 为空的条目不进 L1 聚类（测试断言）。

### T-16 1 档案例检索（最先见效的积累机制）  ⇐ T-07
**做**：`retrieval_items` + `retrieval_vec`（BGE-M3）；按 `unit_kind/industry/profile/quality` 检索 k 条注入 Pass；
`--no-retrieval` 开关做 A/B。
**验收**：`nsc eval l1 --ab retrieval` 报告检索增益；`usable_as_example=0` 的条目**绝不**作为示例注入（测试断言，COMPLIANCE §1）。

### T-08b 判官 v1  ⇐ T-05
**做**：`judge/{rubric_judge,pairwise,calibration}.py`；成对协议（含 swap）；`nsc judge calibrate` 报告；
`spec/rubrics/anchors/*` 补全 5 维 × ≥2 锚例。
**验收**：≥50 条校准集下产出一致率/κ/位置偏置报告；`nsc eval l1` 可跑；`nsc.eval.gate` 尊重 `JUDGE_GATE_ENABLED`。

### T-21 逆向标注 + 往返重建  ⇐ T-05
**做**：`annotate/{reverse_annotate,priors,roundtrip}.py`；200–500 条样本；30–50 条人工种子核验；
产出 `profiles/_mined_priors.yaml` 并**替换** craft 模板；跑往返重建报告。
**验收**：标注器一致率达 `eval/thresholds.yaml::annotation` 门槛；`nsc annotate roundtrip` 产出结构相似度与 KL；
若低于 `roundtrip` 门槛 → **开 ADR 提议改 IR**（这是正确结果，不是失败）。

### T-17 SQLite 与 JSONL 双向（D28）  ⇐ T-01
**做**：`db/migrations/0001_init.sql`、`db/migrate.py`、`nsc db rebuild|export|next-case-id`；
`spec-guard` 增加 `db_export_fresh` 检查。
**验收**：`make db-rebuild && make db-export` 后 git 无 diff（幂等）。

**P1 退出条件**：一次真实反馈 1 小时内变成 `revision_pairs` 入库；检索复用可测出正增益；往返重建有基线数字。

---
## P2 · 飞轮启动（~3 周）

### T-12 ⭐⭐ GEPA metric + feedback function（胜负手）  ⇐ T-11, T-08b
**做**：`optimize/{gepa_metric,structure_match,feedback_router}.py` 全部实现。
**验收**：`tests/test_gepa_metric.py` 断言：
① `pred_name` 路由生效（p3 的 feedback 不含 DLG-002）
② `split="val"` 时不泄漏 `revised_text`
③ 长度 ≤ budget
④ 有 block finding 时 score==0.0
⑤ `WEIGHTS` 求和为 1
⑥ feedback 文本包含五节结构且 block 在第一节

### T-13 GEPA 编排  ⇐ T-12
**做**：`optimize/gepa_run.py`；`nsc eval build-dataset`（**按 case 分层切分**）；回归闸；写 `prompts/*.json` 含 `content_hash`。
**验收**：`nsc optimize --pass p3_beatsheet --auto light` 跑通并产出可审计的 `detailed_results.json`；
回归闸生效（人为构造退化时不写入 `prompts/`）；`make prompts-verify` 绿。

### T-14 规则挖掘（L0→L1）  ⇐ T-11
**做**：`mining/{cluster,induce}.py`：BGE-M3 + HDBSCAN 聚类；`RuleInduce` 归纳；写 `L1_candidates/`。
**验收**：≥30 条观察下产出 ≥3 条候选，每条带 `evidence_ids ≥3`、`counterexamples` 非空、`conflicts_with` 已检查。

### T-15 规则验证与退役（L1→L2→L3, →deprecated）  ⇐ T-14
**做**：`mining/{validate,retire}.py`；留出集协议；`rule_hits` 统计；`nsc mine retire`。
**验收**：`tests/test_mining.py`：验证协议在合成数据上可复现；120 条上限强制生效；
`taste` 类只能产出 `scope: client` 规则（测试断言）。

### T-18 `short_video_v1` 接入（泛化压测）  ⇐ T-07
**做**：只改 `profiles/short_video_v1.yaml` + 至多 1 个新 Pass + 规则的 `scope`。
**验收（关键）**：`git diff --stat` 显示 **`src/nsc/runtime/` 与 `src/nsc/checker/` 零改动**；
`nsc run --profile short_video_v1` 端到端通过 L0。
**若做不到零改动 → 说明 IR 抽象漏了，开 ADR 改 IR，不要 fork 内核（D18）。**

### T-19 CI 全套  ⇐ T-09
**做**：4 个 workflow + 标签 + ruleset + PR/Issue 模板；`nsc.eval.gate`；`nsc.metrics.northstar_alert`。
**验收**：故意提一个手改 `prompts/` 的 PR → CI 红；不打 `affects-generation` 的 PR → 无 LLM 调用（成本 $0）。

### T-20 指标仪表盘  ⇐ T-17
**做**：`nsc metrics weekly`；`docs/metrics/latest.md`；北极星趋势告警。
**验收**：产出六个数 + 北极星；`edit_rate_json` 按 D11 八类分解（混算即失败）。

**P2 退出条件**：第 3 次 GEPA 迭代仍正增益且无回归；`short_video_v1` 接入 PR 未改内核。

---
## P3 · 商业加固（持续，不排期）
T-22 Client Pack 化与品牌资产复用 · T-23 分镜与可拍性检查 · T-24 交付模板与品牌化 docx ·
T-25 成本优化（低层 Pass 换小模型 + 缓存命中率优化） · T-26 `mid_drama_v1` Profile

---

## P1.5 · 外部方案吸收（依据 `docs/UPGRADE_PLAN_2026-08-17.md`，ADR-0011..0014 已 accepted）

> 三波实施：Wave A 零 IR 改动纯增量 → Wave B IR 1.1 → Wave C 评测增强。全部规格的权威来源是方案文档 §4–§8，本处只列做/验收。

### Wave A · 零 IR 改动（纯增量，先做）

#### T-27 ⭐ textstats 模块 + prose 域 16 条规则
**做**：① 核对 `guards/budgets.py` 计数口径并写进 BUDGETS.yaml 注释（前置）；② 新建 `src/nsc/textstats/`（方案 §6.1 签名）；③ checker `__ctx` 加载器从 compliance 专用泛化为按域自动加载 `_*.yaml`；④ registry 薄注册 ≤40 行；⑤ 落盘 `spec/checks/prose/_wordlists.yaml` + PRS-001..016 及各自 fixtures。
**验收**：`pytest tests/test_checker_dsl.py` 全绿（16 条 pass/fail/expected）；`nsc check tests/fixtures/golden/demo_tea_ir.json` 零新增 block；`make spec-guard` 绿。

#### T-28 结构红线 STR-014/015  ⇐ 无
**做**：落盘 2 条 block 规则（每集承重 beat inciting+climax 在场；情感弧零振幅）+ fixtures。
**验收**：`pytest tests/test_checker_dsl.py -k "STR-014 or STR-015"` 绿；golden IR 不误报。

#### T-29 平台合规 CMP-003..007  ⇐ 无
**做**：落盘 `spec/checks/compliance/_platform_terms.yaml` + 5 条规则（003/004/005 block，006/007 warn）+ fixtures；`_legal_sources.md` 新增 `#platform-rules` 节（番茄 must_avoid 清单来源）。
**验收**：规则 fixtures 全绿；`make spec-guard` 的 checks_schema 对 compliance 域 legal_ref 校验通过。

#### T-30 反模式锚点入 rubric  ⇐ 无
**做**：autonovel 12 条结构性反模式逐条落 `spec/rubrics/anchors/prose_craft.yaml` 锚点描述+反例；平台 must_have 节奏项（每 1000 字爽点、压抑释放比、前 100 字钩子）落 `hook_strength.yaml`/`naturalness.yaml`。不新增维度。
**验收**：`tests/test_judge.py::test_all_dimensions_have_anchors` 绿；`make spec-guard` 绿。

#### T-31 ⭐ 修订 brief 合成器  ⇐ T-27
**做**：`src/nsc/revise/revision_brief.py`（方案 §6.2 五节规格：PROBLEM/KEEP/CHANGE/VOICE/TARGET，≤2600 字按 block→warn→info 截断）；接入 `gepa_metric.py` feedback 的 PROBLEM 节与 p5 自检子步。
**验收**：`tests/test_revision_brief.py`（五节结构、block 在 PROBLEM 首、KEEP 含判官最强句、TARGET 字数公式 REWRITE/FIX/POLISH/COMPRESS 0.55×/TIGHTEN 0.85×）；`test_gepa_metric.py` 原六条断言不破。

#### T-32 ⭐ revise 模块（patch/gate/snapshot/idea_bank）  ⇐ 无
**做**：`src/nsc/revise/{patch,gate,snapshot,idea_bank}.py`（方案 §6.2：两级匹配唯一性 + ≥50% 落位门槛；strict/lenient/always 三档公式；SQLite 内容哈希快照链 + `rollback_to`；idea_bank 表 + 写入钩子）。
**验收**：`tests/test_revise.py`：精确匹配歧义判败、归一化坐标映射、49% vs 51% 落位分野、三档门禁真值表、快照回退往返一致。

#### T-33 context 模块（P0-P5 预算 + 历史压缩）+ p6 接入  ⇐ T-27
**做**：`src/nsc/context/{assembler,compress}.py`（方案 §6.3：P0 低保 400 token 不可裁、降级顺序 P3→P4→P2→P5、P4 整层可弃、每层 token 写 runs 表；中间历史压至 ~10% 走内容寻址缓存）；p6_prose 输入组装切换到 assembler；profile 增加 `context.*` 参数节。
**验收**：`tests/test_context_budget.py`（低保不可裁、降级链顺序、超预算 P4 整层丢弃、压缩比与缓存命中）；`nsc run` 端到端 L0 全绿且 runs 表含分层 token 记录。

### Wave B · IR 1.1（⇐ ADR-0012）

#### T-34 ⭐ IR 1.1 落地  ⇐ T-27
**做**：`spec/ir/overlays.py` 新增 Fact/Thread/StateVariable/DarkThread/StateChange/MentalModel/ExpressionDNA/KnowledgeState；Scene/Episode/Character 字段扩展；container 加四张表 + `schema_version "1.1"`；invariants.py 加 INV-17..20；`ir_io.py` 加 1.0→1.1 迁移与视图派生（current/current_stage/is_overdue）。
**验收**：`pytest tests/test_invariants.py` 全绿（含 INV-17..20 与 `test_id_stability` 回归）；旧 golden IR 迁移后 `nsc check` 结果不变。

#### T-35 p1/p2 签名扩展  ⇐ T-34
**做**：p1_bible 输出角色心智 OS 字段；p2_arc 输出 Thread/DarkThread/StateVariable + `Episode.responds_to`；`signatures.py` 与 CONTRACTS.md 同步。
**验收**：`nsc run` 端到端产物含新字段且 after_p1/after_p2 检查绿；`prompts/` 由 `nsc compile-prompts` 重新生成（git diff 无手改）。

#### T-36 p3/p4 签名扩展  ⇐ T-35
**做**：p3 输出 Facts[]（含 `PENDING:<slug>` 前向引用解引用）+ `Episode.state_changes`；Beat.summary 改事件模板格式（签名 docstring 引导）；p4 输出 Scene 节奏字段 + knowledge_state。
**验收**：新 fixtures 端到端绿；p3 后处理解引用有单测（跨集 resolves 闭环）。

#### T-37 Wave B 规则 7 条  ⇐ T-36
**做**：FCT-003/006/007、STR-016/017/018、DLG-008 + fixtures（registry 加 `covered_by_responds` 纯函数）。
**验收**：`pytest tests/test_checker_dsl.py` 全绿；规则总数 ≤90（budgets 守卫断言）。

#### T-38 dep_graph/快照接线 + 重编译闭包测试  ⇐ T-36, T-32
**做**：`dep_graph.yaml` 新增 facts/threads/state_variables/dark_threads 失效闭包；pipeline 在 p3 全季后处理之后调 `snapshot.save_snapshot`；CONTRACTS.md §3 更新。
**验收**：`tests/test_recompile.py` 新增 case（改 Fact.resolves 只重跑相关集检查、不重生成）；快照在重编译后落盘可查。

### Wave C · 评测与优化增强

#### T-39 三视角判官  ⇐ T-30
**做**：`rubric_judge` 指令内嵌编辑/类型读者/普通读者三视角 + 分歧标记（单一调用，确定性聚合）；`pairwise_protocol.md` 更新；分歧注记持久化。
**验收**：`nsc judge calibrate` 报告含视角分歧统计且 κ 相对基线不降；测试断言三视角输出结构。

#### T-40 Elo 锦标赛模式  ⇐ 无
**做**：`nsc eval l1 --tournament`（1500/K32/4 轮 Swiss 相邻配对/无平局/temperature 0.2/3000 字截断/5 比较轴）。
**验收**：测试断言配对算法与 Elo 公式；固定 seed 排名可复现。

#### T-41 plateau 停止 + Idea Bank 接线  ⇐ T-32
**做**：revision 循环与 `gepa_run.py` 加 plateau（Δ<0.03@≥3 轮、上限 6 轮、退步回滚快照）；p2/p3 上下文注入"可复活素材"层；CLI `nsc bank list|revive`。
**验收**：合成指标序列测试停止/回滚；bank 写入→注入→revive 往返测试。

#### T-42 端到端回归验收 + BORROW_MAP 增补  ⇐ T-37, T-38, T-39
**做**：demo_tea 全量回归（78 条规则零 block）；`nsc eval l1`（含 --tournament）基线对比报告进 `out/eval/`；`docs/BORROW_MAP.md` 增补 #29–#36（novel-studio/autonovel/inkos/StoryWriter/FicForge/NovelForge/novel-distiller/One-Sentence-One-Drama）。
**验收**：`make ci-local` 全绿；P1.5 整体退出条件（方案 §10）逐项勾选。

---

## 派单建议（单人 + AI Agent）
- **你必须亲自做**：T-06（黄金 IR）、T-21 的人工种子核验、判官校准的分歧样本阅读、规则 L2→L3 approve。
  这四件事是"品味"的注入口，外包给 Agent 等于放弃资产。
- **可全权交 Agent**：T-01, T-04, T-05, T-08, T-09, T-17, T-19, T-20
- **交 Agent 但你必须 review 设计**：T-02, T-03, T-07, T-10, T-12, T-14, T-15
- **并行**：T-02/T-03 完成后，T-05 与 T-07 可并行；T-10 与 T-08b 可并行。