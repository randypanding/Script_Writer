# 借鉴地图 —— 别自己造

> **Agent 动手前必读这个文件。** 每一行都写明了：借什么、不借什么、落到哪个文件、哪个工单。
> ✅ = 我已核实来源；[待核] = 请你在首次引用时核对编号/作者年份后把标记改成 ✅。

## 一、生成架构

### #1 分层多趟生成 ← Dramatron ✅
- 来源：Mirowski, Mathewson, Pittman, Evans. *Co-Writing Screenplays and Theatre Scripts with Language Models*. CHI 2023. **arXiv:2209.14958**
- **借**：`log line → title → characters → plot(场景摘要+beats) → location descriptions → dialogue` 的层级切分；
  以及"作者可在任意层级重新生成/编辑"的交互模型 → 这正是我们的局部重编译。
- **不借**：它的 flat prompt 模板与无结构文本输出（我们用类型化 IR 片段）。
- 落地：`spec/passes/CONTRACTS.md`、`spec/passes/signatures.py`、`src/nsc/passes/`
- 工单：T-07

### #2 计划-草稿-重排-修订 ← Re3 ✅
- 来源：Yang, Peng, Tian, Klein. *Re3: Generating Longer Stories With Recursive Reprompting and Revision*. EMNLP 2022. **arXiv:2210.06774**
- **借**：四段式中的 **rerank**（多候选按连贯性/相关性择优）与 **edit**（事实一致性修订）
  → `p5_dialogue --rerank`（n=3 候选，L0 过滤 + 判官选优）与 p5 的自检子步。
- **不借**：rolling-window 递归续写（我们有显式 Beat 计划，不需要它）。
- 落地：`src/nsc/passes/p5_dialogue.py`
- 工单：T-07b（默认关闭，成本敏感）

### #3 细化大纲控制 ← DOC ✅
- 来源：Yang, Klein, Peng, Tian. *DOC: Improving Long Story Coherence With Detailed Outline Control*. ACL 2023. **arXiv:2212.10077**
- **借**：核心原则 —— **把创作负担从起草前移到规划**（detailed outliner）。
  我们的具体化：`p3_beatsheet` 必须细到"每个 Beat 可被独立判定通过/不通过"，
  `summary` 必须是"谁做了什么导致什么"而非抽象概括。
- **借（变体）**：detailed *controller* 的作用（保证起草不偏离大纲）→ 我们用 **L0 checker + p5 自检** 替代
  它的可微控制器（我们没有训练环境，也不需要）。
- 落地：`spec/passes/signatures.py::BeatSheet` 的硬约束、`spec/checks/structure/*`
- 工单：T-07

### #4 优化器 ← GEPA ✅
- 来源：Agrawal 等. *GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning*. ICLR 2026 (Oral). **arXiv:2507.19457**
- 实现：`dspy.GEPA`（引擎来自 `github.com/gepa-ai/gepa`）
- **借（关键）**：metric 的契约 `metric(gold, pred, trace=None, pred_name=None, pred_trace=None) -> dspy.Prediction(score=..., feedback=...)`。
  **feedback 字段是文本反馈通道**，会被直接读进反思提示；只返回 float 会让 GEPA 退化。
  还借：Pareto 候选池选择（`candidate_selection_strategy="pareto"`）、per-predictor 反思（用 `pred_name` 路由）、
  `auto` 预算档（light/medium/heavy）、`track_stats` 的审计轨迹、`use_merge` 合并互补经验。
- **不借**：默认 `instruction_proposer`（我们注入领域反射模板，让反思聚焦营销短剧的失败模式）。
- 落地：`src/nsc/optimize/gepa_metric.py`（**全系统最厚的文件**）、`gepa_run.py`、`docs/SOP_GEPA.md`
- 工单：T-12（metric）、T-13（编排）

### #5 声明式 LLM 程序 ← DSPy / MIPROv2 [待核编号]
- DSPy：Khattab 等. *DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines*. **arXiv:2310.03714**
- MIPROv2：Opsahl-Ong 等. **arXiv:2406.11695**
- **借**：Signature/Module 抽象（每趟一个 Module，类型化 IO）；MIPROv2 作为 GEPA 的**对照基线**（跑一次证明 GEPA 更好，别盲信）。
- 落地：`spec/passes/signatures.py`、`eval/baseline_mipro.py`
- 工单：T-07、T-13

### #6 多趟编译器纪律 ← Nanopass [待核]
- 来源：Sarkar, Waddell, Dybvig. *A Nanopass Infrastructure for Compiler Education*. ICFP 2004.
- **借**：每趟只做一件事、趟间是**显式类型化 IR**、每趟可独立测试。这是"对 AI 编码极度友好"的根源。
- 落地：`spec/passes/CONTRACTS.md` §0
- 工单：T-07

### #7 增量重算与内容寻址 ← Salsa / Bazel / Nix（工程实践，非论文）
- **借**：`hash(输入) → 输出` 的内容寻址缓存 + 下游失效闭包（demand-driven invalidation）。
- **不借**：它们的框架本体（我们用 `diskcache` + 一个装饰器 + 一张 `dep_graph.yaml`）。
- 落地：`src/nsc/runtime/cache.py`、`spec/passes/dep_graph.yaml`
- 工单：T-04

### #28 原则驱动的自我修订 ← Constitutional AI [待核]
- 来源：Bai 等. *Constitutional AI: Harmlessness from AI Feedback*. **arXiv:2212.08073**
- **借**：critique → revise 的自修订循环，其原则以**显式清单**形式给出。
  我们的变体：原则**不手写**，而是从 `spec/rules/L3_canonical/` 中 `form: prompt` 的规则动态拼装。
- **不借**：RLAIF 部分（我们不训练）。
- 落地：`src/nsc/passes/p5_dialogue.py::self_revise`
- 工单：T-07b

### #27（可选）Brief 补全 ← STORM [待核]
- 来源：Shao 等. *Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models*. NAACL 2024. **arXiv:2402.14207**
- **借**：多视角提问以扩展信息收集 → 用于 `p0_intake` 的 `missing_fields` 生成（"从这三类人群视角看，还缺什么信息？"）。
- 优先级：低。P3 再看。

## 二、评测与判官

### #8 判官设计 ← G-Eval / MT-Bench / Prometheus 2 / FLASK [编号待核]
| 借什么 | 来源 | 落到哪 |
|---|---|---|
| rubric + CoT + form-filling 的打分范式 | G-Eval, **arXiv:2303.16634** | `spec/rubrics/rubric_v1.yaml` |
| **成对比较**优于绝对分；**位置偏置**必须通过交换顺序消除 | MT-Bench, **arXiv:2306.05685** | `pairwise_protocol.md` §3、`judge.position_debias: swap_and_average` |
| rubric **锚定样例**驱动的细粒度评分；开源判官可作备选 | Prometheus 2, **arXiv:2405.01535** | `spec/rubrics/anchors/*.yaml` |
| 把能力拆成细粒度技能维度分别评 | FLASK, **arXiv:2307.10928** | rubric 的 5 维分解 |
- **不借**：G-Eval 的 token-probability 加权（多数商用 API 拿不到 logprobs，且脆）。
- 工单：T-08

### #9 故事评测维度交叉验证 ← HANNA [待核]
- 来源：Chhun 等. *Of Human Criteria and Automatic Metrics: A Benchmark of Story Generation Models*. COLING 2022. **arXiv:2208.11646**
- **借**：其 6 个人评维度（relevance / coherence / empathy / surprise / engagement / complexity）作为**交叉检查表**：
  若我们的 5 维覆盖不了某类人类批注，说明维度设计漏了。
- **不借**：直接照搬 6 维（它是通用故事，我们要营销专用的 placement_integration）。
- 落地：`spec/rubrics/rubric_v1.yaml` 的评审注释
- 工单：T-08

## 三、反馈与知识沉淀

### #10 编辑意图分类 ← IteraTeR / CoEdIT [编号待核]
- IteraTeR：Du 等. *Understanding Iterative Revision from Human-Written Text*. ACL 2022. **arXiv:2203.03802**
- CoEdIT：Raheja 等. *CoEdIT: Text Editing by Task-Specific Instruction Tuning*. EMNLP 2023. **arXiv:2305.09857**
- **借（IteraTeR）**：① 编辑意图标注体系的做法（我们的 D11 八类是其领域化版本）
  ② **自动编辑意图分类器**的思路 → `EditClassify` Signature
  ③ 编辑抽取的对齐方法（原文↔修订文的 span 级对齐）
- **借（CoEdIT）**："编辑指令对"的数据形态 → 我们的 `revision_pairs`（before/after/dimension）。
- **不借**：CoEdIT 的指令微调（P3 前不微调）。
- 落地：`spec/feedback/TAXONOMY.md`、`src/nsc/feedback/classify.py`、`spec/passes/signatures.py::EditClassify`
- 工单：T-11

### #11 从自然语言反馈学习 ← Learning from Language Feedback [待核]
- 来源：Scheurer 等. *Training Language Models with Language Feedback* (**arXiv:2204.14146**) 与其 at-scale 版本 (**arXiv:2303.16755**)
- **借**：把人类批注形式化为可用的学习信号的框架（refinement → selection）。
  我们的具体化：批注 → `revision_pairs` → GEPA feedback，**不经过权重更新**。
- 落地：`gepa_metric.py::build_feedback` 的"人类是怎么改的"一节
- 工单：T-12

### #12 经验 → 可复用规则 ← ExpeL / AWM / Voyager / Generative Agents [编号待核]
| 借什么 | 来源 | 落到哪 |
|---|---|---|
| 从经验池抽取 insight，并用 **ADD / UPVOTE / DOWNVOTE / EDIT** 四种操作维护规则集 | ExpeL, AAAI 2024, **arXiv:2308.10144** | `src/nsc/mining/induce.py` 的操作集、`rules.hit_count` |
| 从轨迹**归纳可复用 workflow**并按需检索 | Agent Workflow Memory, **arXiv:2409.07429** | `beat_templates`（mined）与 1 档检索的 `unit_kind=beat_sequence` |
| **skill library：验证通过才入库** | Voyager, **arXiv:2305.16291** | `spec/rules/PROMOTION.md` 的 L1→L2 门禁 |
| reflection：从多条底层观察合成高层洞察 | Generative Agents, **arXiv:2304.03442** | `RuleInduce` Signature |
- **关键改造**：以上工作**都没有晋升门禁**，经验池会自我矛盾并膨胀。我们加了 L0→L3 四级 + 120 条硬上限 + 退役机制。
- 落地：`spec/rules/`、`src/nsc/mining/`
- 工单：T-14、T-15

### #13 行为测试套件 ← CheckList [待核]
- 来源：Ribeiro 等. *Beyond Accuracy: Behavioral Testing of NLP Models with CheckList*. ACL 2020. **arXiv:2005.04118**
- **借**：MFT（最小功能测试）/ INV（不变性）/ DIR（定向期望）三类测试的组织方式
  → 每条 check 规则的 `pass.json`（INV）+ `fail.json`（MFT）；`counterexamples` 集用 DIR 组织。
- 落地：`tests/fixtures/checks/<RULE-ID>/`、`tests/test_checker_dsl.py`
- 工单：T-05

## 四、领域知识（营销 / 叙事）

### #14 情绪弧形状 ← Reagan et al. 2016 [待核]
- 来源：Reagan, Mitchell, Kiley, Danforth, Dodds. *The emotional arcs of stories are dominated by six basic shapes*. EPJ Data Science, 2016.
- **借**：六种基本情绪弧形状作为 `EmotionCurve` 的**先验与检查依据**（我们的短剧应落在其中某几种上；全平的曲线是坏味道）。
- **不借**：他们的 labMT 英文情感词典（中文不适用；我们让 LLM 直接标 valence/arousal）。
- 落地：`spec/checks/structure/STR-006.yaml`、`nsc annotate priors` 的弧形聚类
- 工单：T-21

### #15 植入设计理论 ← Russell 2002 / Gupta & Lord 1998 / Balasubramanian 2006 [全部待核]
| 借什么 | 来源 |
|---|---|
| **modality（视觉/听觉）× plot connection（情节关联度）的一致性**决定品牌记忆与态度 → 我们的 `BrandMoment.modality` 与 `plot_connection` 字段，以及 `BM-004`（全季必须有 high plot_connection）、`BM-010`（modality 不得单一） | Russell, C.A. (2002), *JCR* |
| **prominent vs subtle placement** 的显著性分级 → `BrandMoment.intensity` 1–5 与 `BM-005`（高强度每集 ≤1） | Gupta & Lord (1998), *J. Current Issues & Research in Advertising* |
| hybrid message 的分类框架 | Balasubramanian, Karrh, Patwardhan (2006), *J. Advertising* |
- ⚠️ **这三条是我们与通用故事生成器的核心差异点。** 不要把它们当成可选装饰。
- 落地：`spec/ir/overlays.py::BrandMoment`、`spec/checks/brand/*`、`spec/rubrics/rubric_v1.yaml#placement_integration`

### #16 叙事传输 ← Green & Brock 2000 / Escalas 2004 [待核]
- Green & Brock (2000), *The role of transportation in the persuasiveness of public narratives*, JPSP —— transportation-imagery model
- Escalas (2004), narrative transportation 在广告中的作用
- **借**：`transportation` 这个 rubric 维度的**构念定义与题项**（沉浸 → 情绪 → 品牌态度的因果链），
  以及它的 positive/negative signals（"情绪先到品牌后到" vs "先讲产品后补情绪"）。
- 落地：`spec/rubrics/rubric_v1.yaml#transportation`、`anchors/transportation.yaml`

### #26 Beat 模板先验 ← Save the Cat / Story Circle（craft 来源，非论文）
- **借**：节拍表的**形式**（有名字的功能序列）。
- **明确标注为可替换**：`beat_templates[].source: craft` 的模板在 `nsc annotate priors` 产出 `source: mined` 的统计模板后
  应被替换或至少并列。**中国短视频平台的营销短剧节奏与好莱坞三幕剧不同，不要迷信 craft 模板。**
- 落地：`profiles/*.yaml::beat_templates`

### #25 广告合规词表（法规来源，需人工核对）
- 见 `spec/checks/compliance/_legal_sources.md`。**未经人工核对的合规规则自动降级为 warn**（`eval/thresholds.yaml`）。

### #29 小说文笔工艺 ← story-craft 技能 ✅（已吸收，见 ADR-0010）
- 来源：内部创意写作技能 `story-craft-skill.md`（已删除并并入项目资产）。
- **借**：show-don't-tell、感官锚点、对白动作节拍、反 AI 指纹、风格温度五档、3:1 节奏、角色 Soul Field（五维角色卡）。
- **不借**：同人/CP/连载站运营/世界观设定书等模块——本项目为营销短剧（先小说确认物、再剧本执行物），不需要。
- 落地：`spec/checks/novel/NOV-004…009`、`spec/checks/dialogue/DLG-007`、`spec/rubrics/rubric_v1.yaml#prose_craft`、`spec/rules/L3_canonical/R3-0002…0007`、`docs/SOP_PROSE_CRAFT.md`
- 注意：canonical 规则按"借入知识"落库，`evidence_ids` 为占位；真实反馈管道（T-11/T-14）产出案例后需复核/替换。

## 五、工程与工具（直接用，别造）

| # | 需求 | 用什么 | 借什么 / 注意 |
|---|---|---|---|
| #17 | Spec 驱动开发的目录与流程 | **GitHub spec-kit** 约定 + **AGENTS.md** 约定 + **ADR**（Nygard） | 借目录布局与"spec 先行"的流程纪律；不引入其 CLI 的强制流程 |
| #18 | Fountain 解析/渲染 | **Fountain 格式标准**（fountain.io）；`screenplain` / `jouvence`（Python 解析）；`pandoc` | 剧本渲染与 docx↔md 转换；**pandoc `--track-changes=all` 作为修订提取的兜底**，主路径直接解析 OOXML `w:ins`/`w:del` |
| #19 | trace / 打分 / **人工标注队列** / dataset / prompt 管理 | **Langfuse（自托管）** | 借 annotation queue → 省掉自建标注 UI（至少 3 周）。**这是本项目最大的一笔"不造轮子"** |
| #20 | 向量检索 / 中文 embedding / 聚类 | **sqlite-vec**；**BGE-M3**（BAAI，arXiv:2402.03216 [待核]）；**HDBSCAN** | 单文件向量库零运维；BGE-M3 多语言且中文强；HDBSCAN 不需要预设簇数（规则挖掘的簇数未知） |
| #21 | ASR 时间戳 / 镜头切分 | **faster-whisper**（或 WhisperX 做对齐）；**PySceneDetect** | 逆向标注的转写与 Scene 边界辅助 |
| #22 | **checker DSL 的求值** | **JMESPath**（select）+ **simpleeval**（assert） | **不要自己写解析器。** 这一条直接把 D7 的实现难度从"写编译器"降到"写 300 行胶水" |
| #23 | 不变量测试 / 渲染快照 | **Hypothesis**（property-based）；**syrupy**（snapshot） | IR 不变量天然适合 property-based；渲染器适合 snapshot |
| #24 | 模型路由与成本统计 | **LiteLLM** | 换模型不改代码；`completion_cost` 直接进 provenance |
| — | 缓存 | **diskcache** | 内容寻址缓存的存储层 |
| — | 文本对齐 | **rapidfuzz** | 模糊回退对齐的打分函数；DP 骨架自己写（20 行） |
| — | 一致性统计 | **statsmodels**（Cohen κ）+ **krippendorff** | 判官校准 |

## 六、明确不借（避免注意力被吞）
- ❌ 多智能体框架（AutoGen / CrewAI / LangGraph）—— 6–8 趟线性 DAG 用不上，1 人维护不了
- ❌ "Agents' Room" 类多角色协作写作 —— 与 D6"多智能体互评"否决一致
- ❌ 向量数据库服务（Milvus / Qdrant / Weaviate）—— sqlite-vec 够
- ❌ 工作流引擎（Prefect / Airflow / Temporal）
- ❌ 微调框架（PEFT / TRL）—— P3 前不做
- ❌ 视频/TTS/剪辑（AnimateDiff / SadTalker / …）—— 另一个业务