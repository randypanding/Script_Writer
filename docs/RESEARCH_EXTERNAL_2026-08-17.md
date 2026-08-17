# 外部方案调研决策依据（2026-08-17）

> **本文档的性质**：只做**事实记录与选项罗列**，**不做最终决策**。
> 调研者（初步探索）已核实基本事实：8 个外部方案已下载并逐一代码级精读。最终取舍由**强模型**依据本文件 + 仓库原文做决策。
> **证据来源**：全部外部仓库已克隆至 `/tmp/novel_research/<repo>`（沙箱临时目录，可能被清理；强模型决策前如需要可据 GitHub 地址重新克隆）。

---

## 0. 调研范围与结论速览

| # | 外部方案 | 来源 / 仓库 | 与 NSC 的关系 | 一句话本质价值 |
|---|---|---|---|---|
| 1 | **novel-studio** | github.com/Ddhjx-code/novel-studio（另有同名的 Openapps-free/ldblckrs-258 等，均为不同项目） | 竞品路线 A：多 Agent + RAG + 文件即记忆 | "以人为中心的创作工作台"：骨架→扩展→拼合 + 十维度审查 + 4000 字去 AI 味规则，但无 IR/无自动评测/无自改进 |
| 2 | **autonovel** | github.com/NousResearch/autonovel（另有 fork 分支） | 路线 B：modify-evaluate-keep/discard | 已产出 75k 字真小说，证明"评估-取舍"循环可行；三重评估（机械 slop + LLM 判官 + Opus 审校）+ 多源 brief 合成 |
| 3 | **inkos** | github.com/Narcooo/inkos（fork 众多） | 路线 C：多 Agent 流水线 + 真相文件 | 7 个"真相文件"长期记忆 + 37 维审计 + 定点修复（spot-fix），长篇不崩的工程化方案 |
| 4 | **StoryWriter** | github.com/THU-KEG/StoryWriter（论文 arXiv:2506.16445） | 论文对照：事件图大纲法 | 事件级大纲（Setting/Character/Action/Conflict/Twist）→ 跨章分配子事件 → 动态压缩历史；8000 词长故事验证 |
| 5 | **FicForge** | github.com/nbssdlkm/FicForge | 竞品路线 D：编辑器 + 四层记忆 | 把"AI 记不住设定"拆成 Facts/Summary/Thread/RAG 四层记忆 + P0-P5 预算竞争 + "AI 只建议人确认" |
| 6 | **NovelForge** | github.com/RhythmicWave/NovelForge（多同名项目，此为"卡片+知识图谱+雪花"版本） | 路线 E：Schema-first | 用户可定义动态输出模型（Pydantic 强校验）+ @DSL 声明式上下文检索 + 卡片树 + 知识图谱 |
| 7 | **Novel Distiller** | github.com/FutureFuzzy/novel-distiller | 路线 F：蒸馏方法论 | 角色 SKILL.md"思维操作系统" + 先推演再撰写 + 暗线数值状态跨章锚定 + 番茄/起点/知乎平台规则 |
| 8 | **One Sentence, One Drama** | arXiv:2605.22144（cs.CV，2026-05） | 论文：短剧生成系统（含视频） | 与 NSC **同业务域**（单句想法→短剧）：节奏显式化字段 + 检索注入 beat 库 + 多阶段 reviewer loop + patch 局部修订，含 3D 首帧/转场/BGM（NSC 不做视频） |

**一句话总结**：7 个开源项目 + 1 篇论文，在"分层多趟生成、事件级大纲、显式长期记忆、多重质量检查、局部定向修订、去 AI 味、反馈闭环"上形成压倒性共识——**这些 NSC 大多已具备或方向一致**；真正需要强模型决策的分歧在于：多智能体是否要碰、大纲细到什么程度、人类中心还是全自动、记忆用关系表还是向量、规则放 YAML 还是 prompt。

---

## 1. 现有项目（NSC）现状速览

- **定位**：把"写小说/写剧本"变成**编译**。业务 = 商家营销短剧，先出**小说**（商家确认物）→ 再出**剧本**（制作执行物），**不做视频生成**。
- **架构**：8 趟编译流水线 `p0_intake → p1_bible → p2_arc → p3_beatsheet → p4_scene → p5_dialogue(Line 戏剧真相层) → p6_prose(叙述编织+anchor_map) → p7_render(确定性 docx/fountain/分镜)`。
- **核心机制**：类型化 IR + 16 条不变量 + ULID 节点 ID（内容无关、永不复用）+ 局部重编译（`dep_graph.yaml` 依赖闭包 + `ir_io.py::merge_preserving_ids`）；声明式 YAML 检查规则（JMESPath select + simpleeval assert，34+ 条，禁止 Python 里写业务 if）；rubric 5 维 + 成对判官 + swap 消位置偏置 + 校准（κ）；GEPA 优化器（feedback 文本进反思）；规则挖掘 L0→L3（120 条硬上限）；sqlite-vec + BGE-M3 检索注入；docx 修订→反向对齐→8 类编辑分类→revision_pairs 反馈闭环；资产/生成物分层（spec/ 唯一真相；prompts/、src/ 生成物；out/ gitignored）。
- **硬约束**：禁止多智能体互评/辩论；禁止编排框架（LangGraph/CrewAI）；仅 SQLite+sqlite-vec；LLM 调用必须经 `runtime/models.py` 路由；每产物写 provenance。
- **已借鉴来源**（BORROW_MAP）：Dramatron、Re3、DOC、GEPA、DSPy、Nanopass、Salsa/Bazel、Constitutional AI、STORM、G-Eval/MT-Bench/Prometheus2/FLASK、HANNA、IteraTeR/CoEdIT、Learning from Language Feedback、ExpeL/AWM/Voyager/Generative Agents、CheckList、Reagan 情绪弧、产品植入理论、叙事传输、Save the Cat、story-craft 技能（ADR-0010）。

---

## 2. 强共识（≥3 个独立方案共同验证 → 建议视为"必须借鉴"）

### 共识 A：分层多趟生成（先规划/大纲，后写作）—— NSC 已具备 ✅
- 全部 8 个方案无一例外采用"多阶段递进"而非单次生成：StoryWriter（outline→planning→writing）、novel-studio（A 上下文→B 规划→C 写→D 审→E 润色→F 定稿）、autonovel（foundation→draft→revision）、inkos（architect→planner→composer→writer→auditor→reviser）、novel-distiller（创世蓝图→蒸馏→推演→撰写）、NovelForge（雪花逐层：梗概→大纲→分卷→章节）、One-Sentence（story core→scene plan→clip 脚本）。
- **结论**：NSC 的 8 趟流水线与全局共识一致，无需改动。此共识为"既有路线正确性"的独立背书。

### 共识 B：事件/节拍级细粒度大纲，且"大纲即可判定契约" —— NSC 基本具备，可补字段 ✅⚠️
- StoryWriter：事件模板 `Event n: Setting + Character + Action + Conflict + Plot Twist`，每事件再拆 3 个子事件，跨章分配（NLN 非线性）——**证据**：`/tmp/novel_research/StoryWriter/agent_try.py` L186、L293-302。
- One-Sentence：场级字段 `opening attractor / key progression steps / scene goal / escalation beats / ending hook`；beat 单元 `{opening action, conflict function, closing hook visual}`；5 条跨场推进线（外部压力/主角反应/解决机制/情绪/知识状态线）。
- novel-studio：承重 beat + 钩子链验证表 + 就绪判定 Green/Yellow/Red（plan-template）。
- inkos：建筑师章节骨架（分场景/叙事节拍/情感节奏）。
- **结论**：NSC 的 p3_beatsheet"细到每拍可独立判定"已符合共识。**可补强**（见 §4 建议 1-2）：① Beat 摘要采用"事件模板"更高信息密度；② 场级增加 `opening_attractor / escalation_beats / ending_hook` 显式字段；③ 引入"知识状态线"（观众知道/角色知道/隐藏/新证据）作为悬念管理结构基础。

### 共识 C：显式长期记忆/真相层（把记忆搬出上下文，不靠 LLM 上下文硬扛）—— NSC 有 IR/Bible/SetupPayoff，但缺"运行时事实生命周期" ⚠️
- inkos：7 个真相文件（世界状态/伏笔池/章节摘要/角色矩阵/支线板/情感弧线/资源账本）+ Settler 输出 JSON delta 增量更新 + SQLite 时序记忆库。
- FicForge：Facts（status: active/unresolved/resolved/deprecated + resolves 级联 + caused_by 因果链 + known_to/hidden_from 信息差）+ Thread 剧情线 + 章节摘要 + RAG 四层。
- novel-distiller：角色 SKILL.md 人设 OS + 暗线数值状态（`variables` + `dark_threads.stages`）+ 每章快照 `ch{NNN}_snapshot.md`。
- autonovel：canon.md（400+ 条硬事实数据库）+ 伏笔总账（foreshadowing ledger）。
- novel-studio：滚动 global_summary + character_state（ASCII 树）+ 显式 tracker 清单（foreshadow/suspense tracker）——**"伏笔不靠 RAG 找，靠 tracker 清单"**。
- NovelForge：知识图谱 KGRelation 表（source/target/kind/stance 等）。
- One-Sentence：知识状态线 + 道具连续性审计（prop_source_continuity）。
- **结论**：这是所有方案最一致的领域（5/8 都把它当核心卖点）。NSC 的 IR + Bible 已是"结构化真相层"，但**编译完成后 Setup/Payoff 之间没有运行时生命周期追踪**（没有"第 5 章埋的伏笔到第 100 章是否已回收"的运行时检查）。**可补**：Fact/Thread/Variable 类 IR 节点 + 生命周期状态机（见 §4 建议 3-4）。

### 共识 D：多重/确定性质量检查 + 红线门禁 —— NSC 有 checker+判官，可补"零成本确定性检查" ✅⚠️
- 零 LLM 成本确定性检查（NSC 目前偏 LLM 判官+YAML 规则，缺少统计型规则）：
  - inkos：`post-write-validator.ts`（禁句式/疲劳词密度/段落长度/转折词密度/跨章重复/章节号指称）+ `ai-tells.ts`（段落长度变异系数/套话密度）。
  - autonovel：`evaluate.py` 机械 slop 检测（3 档禁用词表 + show-don't-tell 违规 + 破折号密度 + 句长变异系数）。
  - novel-studio：十维度审查 + 每维 5→1 行为化定义 + 6 条红线（角色知道不该知道的、因果链断裂、承重 beat 缺失、情感弧未执行、上章钩子未回应、大纲语言残留）。
- 分级评分锚定：inkos 0-100 分有档位描述；novel-studio 有行为化质量标准。
- **结论**：NSC 已有声明式 YAML 规则 + 成对判官 + 校准（比多数方案先进）。**可补**：统计型"AI 味/一致性"规则（段落长度变异、疲劳词密度、跨章重复、大纲语言残留检测）写成 YAML；把"承重 beat 在场、钩子链完整性"作为硬检查。

### 共识 E：局部/定向修订而非整稿重写 —— NSC 已有局部重编译，可补"分片改写/快照回退/Idea Bank" ✅
- inkos：spot-fix（`TARGET_TEXT → REPLACEMENT_TEXT` 精确/模糊替换）+ 多快照 + 自动回退到最佳版本 + `revisionGate` 三档。
- One-Sentence：patch-based 局部改写（只换目标场景 plan）+ **分片改写**（hook 只改首 clip、ending 只改末 clip、twist 只改中间 clip）+ Idea Bank 终局 revival（防过度修正）。
- autonovel：git commit=keep / git reset=discard 的全量版本控制 + plateau 检测停止条件。
- novel-studio：问题分级 [骨架层]/[扩展层]/[表达层] → 分别派 writer 重走骨架 / 定点改 / polisher。
- **结论**：NSC 的 dep_graph 闭包 + merge_preserving_ids 已是局部修订的最工程化版本（比上述都精确）。**可补**：① "分片改写"语义（评审只改首节/末节/中段）；② 修订快照链 + 回退；③ Idea Bank（被删但精彩的点子记录，终局可选恢复，防 GEPA 过度修正）。

### 共识 F：反馈闭环 / 从反馈学习 —— NSC 最领先，可补"多源修订 brief 合成" ✅
- autonovel：`gen_brief.py` 把 reader panel + eval JSON + adversarial cuts 三源合成一份 `PROBLEM / WHAT TO KEEP / WHAT TO CHANGE / VOICE RULES / TARGET` 的修订 brief——**这是 NSC 目前完全缺失的一环**（GEPA 只吃纯文本 feedback）。
- novel-studio：手工把反馈追加为 deai-rules（无自动闭环，恰印证 NSC L0→L3 更有价值）。
- One-Sentence：reviewer 输出 `issue list + root-cause + 定向修订建议` 三件套，且内部 reviewer 与外部评测 judge 严格分离。
- **结论**：NSC 的 GEPA + 规则挖掘 + 反向对齐是全场最强闭环。**可补**：多源修订 brief 合成层（把判官分 + 规则发现 + 检索结果合成结构化修订指令），以及把 checker 报错统一为"诊断句三件套"（NSC 反模式清单已要求）。

### 共识 G：上下文预算/注入管理（有限窗口装最有价值信息）—— NSC 有 1 档检索，可补"预算竞争 + 低保保护" ⚠️
- FicForge：P0-P5 六层预算竞争（system/pinned/focus/facts/thread/RAG/settings）+ `core_guarantee_budget=400` token 低保（主角人设不可被裁）+ 超预算降级链 + 时间衰减检索。
- novel-studio：bible 每段截断 6000 字符 + 上一章尾 2000 字 + RAG top-8（排除当前章）。
- StoryWriter：MessageRedact 把中间历史压缩到 10%（滑动窗口 [2, k-1] 最优）。
- inkos：composer 按本章意图选上下文 + 编译 rule-stack。
- autonovel：分层加载（voice/characters/world 常驻 ~8k，目标+相邻章 ~20-30k）。
- **结论**：NSC 依赖 LLM 窗口上限、预算管理隐式。**可补**：Pass 级 token 预算 + 降级链；对"核心设定/Bible 关键字段"做低保保护；历史摘要压缩注入。

### 共识 H：去 AI 味/反模式知识显式化 —— NSC 有 story-craft 基础，可吸收 12 条反模式清单 ✅
- autonovel：ANTI-PATTERNS.md 12 条结构性反模式（OVER-EXPLAIN ~32%、TRIADIC LISTING、NEGATIVE-ASSERTION REPETITION、SIMILE CRUTCH、PARAGRAPH LENGTH UNIFORMITY、PREDICTABLE EMOTIONAL ARCS、DIALOGUE AS WRITTEN PROSE 等）+ ANTI-SLOP.md 三档词表（18/24/18 词）。
- inkos：禁句式/疲劳词表/文风指纹注入 prompt 层 + 审计层检测 + 确定性层校验三层。
- novel-studio：deai-rules 4000 字（每条"AI 味 vs 人味"对比示例），writer 预防 + polisher 修复双层。
- **结论**：NSC 的 NOV-004…009/DLG-007 已覆盖方向。**可补**：把 12 条反模式与三档词表作为 `spec/rubrics` prose 锚点样例与 L3 反例库素材（注意：NSC 禁止 prompt 硬编码自然语言知识，需落 spec/）。

---

## 3. 分歧与路线之争（各方案做法不同 → 需强模型定夺）

### 分歧 1：多智能体（互评/辩论） vs 编译式单步 LLM
- **多智能体阵营**：inkos（writer→observer→settler→auditor→reviser 流水线）、novel-studio（5 agent 分工，靠工具权限而非提示词强制边界）、StoryWriter（AutoGen 6 agent 对话）、One-Sentence（三裁判并行评审 + Final Decider 仲裁）。
- **NSC**：明确禁止多智能体互评/辩论，用确定性 Pass + 规则 + GEPA 替代。
- **可兼容路线（One-Sentence 提供的）**："多视角候选生成 + 确定性聚合 + 仅争议项仲裁"——同一节点 N 路候选，确定性规则选优，避免 agent 间辩论。**决策点**：是否在 NSC 的某个 Pass 引入 N 路候选（成本↑），还是维持单路 + 判官。

### 分歧 2：大纲粒度：事件级 vs Beat/Line 级 vs 让写作自由发挥
- StoryWriter：大纲到**事件粒度**即可（8 字段模板），细节由写作 agent 自由发挥 → 8000 词质量验证 OK。这**挑战** NSC"细到 Line 类型/性格归属"的过度细化。
- One-Sentence：大纲到 **clip 级**（每 clip 带初始/结束状态），但细节（prompt）仍在视觉层细化。
- NSC：细到 Beat/Line/Scene 全类型化。
- **决策点**：NSC 是否需要把"大纲细到什么程度"作为 Profile 参数（不同场景/成本档位不同），还是坚持统一细化。

### 分歧 3：人类中心（编辑器/人确认/多稿对比） vs 全自动无人值守编译
- **人类中心**：FicForge（AI 设定助手"只建议不擅自动手" D-0029 + 事实提取人审 + 多稿对比 + 手动建剧情线）、novel-studio（明确"不是自动写作机器，作者控制节奏"）、NovelForge（灵感助手 + 确认请求机制）。
- **全自动**：NSC（无人值守编译）、autonovel、One-Sentence（纯自动，作者自承未来应向"高低分分级路由人工"演进）。
- **决策点**：NSC 是否要引入"AI 建议→人确认"的中间档（例如 GEPA 优化方案先出建议卡片、商家确认后生效），还是保持全自动 + 门禁。

### 分歧 4：记忆形态：Markdown 真相文件 vs 类型化 IR vs 关系表（KG） vs 纯向量 RAG
- inkos/novel-distiller/novel-studio：人类可读 Markdown 文件即记忆（可 diff、可 review）。
- NSC/FicForge/autonovel：结构化数据（IR / facts 表 / canon）。
- NovelForge：知识图谱关系表 `KGRelation`（source/target/kind），显式存储"关系"而非靠检索发现——**关系显式存储比隐式检索更能保证一致性**（UniqueConstraint 保证唯一）。
- **决策点**：NSC 是否在 IR 中增加显式"关系断言"层（如"A 与 B 是同盟"在 spec/checks 声明、编译时校验 IR 与关系表一致），替代部分纯向量检索；是否用 SQLite 关系表（不违反"仅 SQLite"）落地。

### 分歧 5：动态用户自定义 Schema vs spec/ 统一模式
- NovelForge：可视化 Schema Studio + 动态输出模型（用户定义任意创作元素结构，Pydantic 强校验）+ 指令流生成（LLM 输出 `{"op":"set","path":"/name","value":...}` 逐步填充、逐条校验）。
- NSC：固定 IR 类型 + Profile schema。
- **决策点**：是否在**边界层**（profiles/ 自定义元数据字段，注入 prompt 但 Pass 不做业务变换）借鉴 Schema Studio，而非推翻统一模式。

### 分歧 6：全量 keep/discard（git reset） vs 局部重编译（dep_graph）
- autonovel：git commit=keep / git reset=discard（整章/整文档二进制取舍）。
- NSC：ULID 节点级 + 依赖闭包局部重编译。
- **决策点**：autonovel 的全量取舍 + plateau 停止条件是否值得在 NSC 增加"候选取舍层"（在局部重编译之上的策略层），还是维持现状。

### 分歧 7：@DSL 声明式上下文检索 vs 代码内 jmespath/simpleeval
- NovelForge：`@type:角色卡[previous:global:3].content.{name,description}` 一行表达式做跨节点、跨类型、带过滤器的声明式检索（前端解析，功能惊艳）。
- NSC：jmespath/simpleeval 局限在"当前 IR 节点"内。
- **决策点**：是否在 NSC 的 prompt 注入系统引入类似 `@ref{type=..., filter=..., limit=...}` 的声明式注入 DSL（落 backend，不落前端）。

### 分歧 8：视频/成片 vs 只出剧本（NSC 明确不做视频）
- One-Sentence 的视频/3D/BGM/转场部分（Marble/VGGT/CUT3R/SAM3D、8 大类 BGM、转场四选一）**不进入 NSC**；但其文本级约束（prop_source_continuity、character_presence、空间连续）可翻译成 NSC 的 PRD/PROD 类规则。
- **决策点**：无需纠结——保持"不做视频"边界，只吸收文本级连续约束。

### 分歧 9：模型/部署：闭源多模型生态 vs 统一路由
- autonovel/One-Sentence：重度依赖 Opus/GPT 闭源 + 专用 API，不可复现不可本地化。
- NSC：models.py 统一路由 + 本地 sqlite-vec 检索。
- **决策点**：无实质争议，NSC 维持现状（所有"借用"必须映射到已允许的模型/本地推理）。

### 分歧 10：绝对分 vs 成对比较
- autonovel 实测发现"1-10 绝对分被压缩到 2 分区间"、ElO 成对比较更可靠（compare_chapters.py）——**支持** NSC 已采用的成对判官路线。
- **决策点**：NSC 继续成对判官；可考虑对"章节间排序"引入 Elo 锦标赛（低优先级）。

---

## 4. 可落地的借鉴点清单（映射到 NSC 模块 + 决策难度）

> 决策难度：🟢 低（加 YAML 规则 / 加 src 代码即可，无需 ADR）｜🟡 中（改 IR 节点字段或加轻量节点，按 AGENTS.md 需开 ADR status:proposed）｜🔴 高（架构级 / 触及硬约束，需强模型拍板）

| # | 借鉴点 | 来源（证据文件） | NSC 落点 | 难度 |
|---|---|---|---|---|
| 1 | **场级节奏字段显式化**：`opening_attractor / scene_goal / escalation_beats / ending_hook` | One-Sentence §2.1；StoryWriter 事件模板 | `spec/ir` Scene 节点扩展字段 + p4_scene 产出 + STR-0xx 规则（首节含 attractor、末节含 ending_hook、中段反转密度） | 🟡（改 IR，需 ADR） |
| 2 | **知识状态线**（每场后：观众知道/角色知道/隐藏/新证据） | One-Sentence §2.1；FicForge facts `known_to/hidden_from` | p3_beatsheet 增加可选状态线字段 + STR 悬念密度规则 | 🟡（改 IR，需 ADR） |
| 3 | **伏笔/事实运行时生命周期**：`status(active/unresolved/resolved) + resolves 级联 + caused_by` | FicForge `domain/fact.ts`、`facts_lifecycle.ts`；inkos `pending_hooks.md` | 新增 Fact 节点（或扩展 SetupPayoff）+ 运行时检查规则"未回收伏笔超阈值/跨章因果链断裂" | 🟡（新增 IR 节点，需 ADR） |
| 4 | **暗线/数值状态跨章锚定**：`variables + dark_threads.stages + 每章快照` | novel-distiller `darkthread.py`、`demo/dark-threads/config.yaml` | 新增 Thread/Variable 节点 + "锚定检查 Pass"（Render 前校验） | 🟡（新增 IR 节点，需 ADR） |
| 5 | **角色思维操作系统字段**：`mental_models + decision_heuristics + honest_boundaries + 表达 DNA` | novel-distiller `demo/souls/孙悟空/SKILL.md` | Character 节点扩展字段；6 路 Probe 蒸馏思路 → 角色深度分析 Pass | 🟡（改 IR + 新 Pass） |
| 6 | **确定性零成本检查规则**：段落长度变异、疲劳词密度、跨章重复、大纲语言残留、章节号指称 | inkos `post-write-validator.ts`、`ai-tells.ts`；autonovel `evaluate.py` L47-239 | 写成 `spec/checks/` YAML 规则（prose/结构域），零 LLM | 🟢 |
| 7 | **12 条反模式清单 + 三档 AI 词表**（作 rubric 锚点/L3 反例） | autonovel ANTI-PATTERNS.md / ANTI-SLOP.md | `spec/rubrics/anchors/prose_craft.yaml` + L3_canonical 反例库 | 🟢 |
| 8 | **钩子链完整性 + 承重 beat 在场性红线** | novel-studio `planner-skill/templates/plan-template.md`、`reviewer-skill/review-checklist.md` | 扩展 16 不变量或新增 STR 规则（ch(N-1) 出口钩必须在 ch(N) 响应 ≤3 章） | 🟢（新增规则） |
| 9 | **多源修订 brief 合成**（PROBLEM/KEEP/CHANGE/VOICE/TARGET） | autonovel `gen_brief.py` | `src/nsc/optimize/` 新增 `gen_revision_brief.py`，喂给 GEPA 反思 | 🟢（新 src 模块） |
| 10 | **分片改写语义 + 快照回退 + Idea Bank** | One-Sentence §2.1、附录 G；inkos spot-fix + 快照；autonovel review.py 停止条件 | p5 自检/局部重编译增加"只改首节/末节"选项；修订快照链；被删点子表 | 🟢~🟡 |
| 11 | **上下文预算竞争 + 低保保护**（core_guarantee） | FicForge `context_budget.ts`、`context_assembler.ts` | `src/nsc/runtime/` 引入 Pass 级预算报告；Bible 核心字段低保注入 | 🟢（新 src + CONTRACTS.md 文档） |
| 12 | **跨章历史摘要压缩注入**（中间历史压到 10%） | StoryWriter `agent_try.py::MessageRedact` L69-139 | p6_prose 输入对非本集历史用摘要替代（降低窗口压力） | 🟢~🟡 |
| 13 | **关系显式断言层**（A 与 B 是 X 关系，编译校验） | NovelForge `kg_provider.py` SQLModelKGProvider、`db/models.py` KGRelation | `spec/checks/` 声明关系断言 + IR 校验；SQLite 关系表（不违约束） | 🟡（新机制） |
| 14 | **@ref 声明式注入 DSL**（跨节点/过滤器/limit） | NovelForge `contextResolver.ts` L437-765 | prompts 注入系统（backend）引入 `@ref{type,filter,limit}`，替代字符串拼接 | 🟡（新机制） |
| 15 | **平台审核规则叠加**（番茄/起点/知乎 must_avoid/must_have） | novel-distiller `platform.py` L30-160 | 移植为 `spec/checks/compliance/CMP-00x` YAML 规则（severity 分级） | 🟢 |
| 16 | **读者 Panel 多角色评估 + 分歧=编辑决策点** | autonovel `reader_panel.py` | 判官 prompt 注入 2-3 个角色视角（编辑/类型读者/普通读者），分歧检测——**注意与禁多智能体互评的关系：这是同一 LLM 多角色，非多 agent 辩论，需强模型确认** | 🟡（触及边界） |
| 17 | **ElO 锦标赛章节排序** | autonovel `compare_chapters.py` | eval 增加成对排序模式（低优先级） | 🟢 |
| 18 | **"AI 建议→人确认"中间档**（GEPA 方案先出建议卡片） | FicForge D-0029 settings_chat；One-Sentence 附录 I 分级路由人工 | `src/nsc/optimize/` 建议模式 + 可选"可接受度"判官维度 | 🟡（产品/流程级） |

---

## 5. 反模式警示（外部项目自己踩过的坑，NSC 避免/已覆盖）

1. **无输出质量校验**：novel-studio dev log §5.3 自承"LLM 输出一段话也存盘"。→ NSC 的 checks + 门禁是对的。
2. **判官分直接当门禁而未校准**：novel-studio reviewer 分数直接当结论、无阈值文件。→ 正是 NSC 反模式清单已禁止的；NSC 校准门槛正确。
3. **真相文件全量读写膨胀**：inkos 每章读写全部 7 文件，100 章后 summaries 数万行，上下文压力大。→ NSC 局部重编译 + 检索按需注入更优。
4. **论文比代码多**：StoryWriter 论文声称 event graph（节点+边+角色结构化）但代码里只是纯文本段落 + 正则提取，无显式边。→ 警惕"以文档/README 为准"的过度承诺，NSC 以可测试代码为准。
5. **绝对评分压缩**：autonovel 实测 1-10 分压缩到 2 分区间。→ 支持 NSC 成对判官。
6. **规则硬编码在 prompt 导致遵从度衰减**：novel-studio 4000 字 deai-rules 压 prompt 尾部后遵从度下降（dev log §12.3）。→ 支持 NSC "知识进 spec/，禁止 prompt 硬编码"。
7. **ops 审计日志半拉子**：FicForge ops.jsonl"纯审计不重建"从未完全落地、与磁盘有偏差。→ NSC 坚持 git + 确定性重编译，不引入 ops 体系。
8. **@DSL 前端全量内存卡片**：NovelForge @DSL 依赖前端加载全部卡片，百万字级成瓶颈。→ 若 NSC 引入注入 DSL 必须落 backend。
9. **多 agent 每章 4-5 次 LLM 调用**：inkos 单章成本线性高企。→ NSC 局部重编译 + 缓存 + 确定性规则控成本。
10. **视频管线不可本地化**：One-Sentence 全闭源 API（GPT-5.4 Pro/Marble/Kling），不可复现。→ NSC 统一路由 + 本地检索的约束正确。

---

## 6. 强模型需要拍板的问题清单（建议逐条决策）

1. **多智能体边界**：维持"禁止多智能体互评/辩论"，还是引入"多视角候选生成 + 确定性聚合 + 仅争议仲裁"（One-Sentence 兼容路线）？若引入，落在哪个 Pass、N 取几、成本上限？
2. **大纲粒度**：是否把"大纲细到什么程度"做成 Profile 参数（成本/质量档位），回应 StoryWriter"事件级已够用"的挑战？
3. **节奏显式化**（建议 1-2）：是否开 ADR 给 `spec/ir` 增加场级 `opening_attractor / escalation_beats / ending_hook` 与知识状态线？这直接回答"短剧节奏怎么算法化"。
4. **运行时事实生命周期**（建议 3-4）：是否新增 Fact/Thread/Variable IR 节点，把 SetupPayoff 从"编译期声明"升级为"运行时状态机"？
5. **角色思维 OS**（建议 5）：Character 节点是否增加 mental_models/decision_heuristics？是否需要 6 路 Probe 角色蒸馏 Pass（成本？）
6. **人类中心程度**：是否引入"AI 建议→人确认"中间档（GEPA 建议卡片 / 低分路由人工）？还是保持全自动？
7. **关系显式存储**（建议 13）：是否用 SQLite 关系表 + 声明式关系断言替代部分纯向量一致性检索？
8. **注入 DSL**（建议 14）：是否引入 `@ref{type,filter,limit}` 声明式注入？落 backend 还是维持 jmespath？
9. **平台规则**（建议 15）：番茄/起点/知乎合规规则是否作为 CMP-00x 入 spec（需先人工核对法务边界，参考 `_legal_sources.md` 机制）？
10. **多角色判官**（建议 16）：同模型多角色视角（编辑/读者）是否触碰"禁多智能体互评"红线？若视为同一判官的多视角则可行。
11. **预算与低保**（建议 11-12）：是否在 runtime 加 Pass 级 token 预算 + 核心设定低保保护 + 历史摘要压缩？
12. **反馈增强**（建议 9-10）：是否新增多源修订 brief 合成 + 分片改写 + Idea Bank + 快照回退（成本与收益评估）？
13. **评测增强**（建议 17）：是否引入 ElO 章节排序？
14. **优先级与分期**：上述 18 条借鉴点按"解决当前最大痛点的程度 / 实现成本"排序，哪些进 P1、哪些 P2/P3？（NSC 已有 WORK_ORDERS.md 工单体系）

---

## 7. 每项目深度要点速览（供强模型按需深入；完整报告见对话记录，代码在克隆仓库）

### 7.1 novel-studio（Ddhjx-code）—— 多 Agent 工作台，人类主导
- 5 Agent（coordinator/planner/writer/reviewer/polisher），边界用工具权限硬约束（reviewer `disallowed_tools: [Write, Edit, Bash]`）。
- 单章管线 A→F；骨架→扩展→拼合三阶段自检；plan-template 钩子链验证表；十维度审查 + 行为化分级 + 6 红线。
- **核心弱点**：无输出质量校验、reviewer 分无校准直接当结论、deai-rules 硬编码 prompt。
- **给 NSC**：承重 beat/钩子链/大纲语言残留检查、去 AI 味对比语料、滚动记忆三件套。
- 证据目录：`/tmp/novel_research/novel-studio/backend/{agents,skills,orchestrator}`。

### 7.2 autonovel（NousResearch）—— keep/discard 取舍循环
- 四阶段（foundation→draft→automated revision 6 轮→Opus review）；git commit/reset 实现 keep/discard；plateau 检测停止。
- 三重评估：机械 slop（零成本）→ LLM 判官（13/9/7 维）→ Opus 审校；reader panel 4 角色 + 分歧=编辑决策点；ElO 章节排序。
- `gen_brief.py` 多源修订 brief 是 NSC 最缺的衔接件。
- **给 NSC**：多源 brief 合成、多角色 panel、对抗性编辑（砍字分类统计）、停止条件工程化、12 条反模式。
- 证据目录：`/tmp/novel_research/autonovel/*.py`。

### 7.3 inkos（Narcooo）—— 真相文件 + 37 维审计
- 7 个真相文件（Markdown 人类可读 + JSON Zod 机器可校验双写）；Settler 输出 JSON delta 增量更新（不整文件重写，防幻觉覆盖）。
- draft→audit→revise 循环：LLM 37 维审计 + 确定性 post-write-validator + ai-tells，score<85 触发 Reviser spot-fix（文本 patch 替换）；revisionGate 三档；多快照回退。
- **给 NSC**：零成本确定性检查清单、spot-fix 语义、控制面文档（author_intent/current_focus）、去 AI 味三层。
- 证据目录：`/tmp/novel_research/inkos/packages/core/src/{agents,state,pipeline,utils}`。

### 7.4 StoryWriter（THU-KEG，论文）—— 事件图大纲法
- 事件模板 8 字段 → 拆 3 子事件 → 跨章分配（NLN 非线性）→ 逐子事件写作；MessageRedact 中间历史压缩 10%（滑动窗口 [2,k-1] 最优）。
- 评测用 HANNA 6 维，人工 4.2 vs DOC 3.7；消融：去事件大纲降幅最大。
- **警告**：论文>代码，事件图在代码里只是文本，无显式边；无评测代码、无反馈闭环。
- **给 NSC**：事件级大纲模板、跨章事件分配（与 SetupPayoff 互补）、历史压缩工程数据。
- 证据目录：`/tmp/novel_research/StoryWriter/agent_try.py`。

### 7.5 FicForge（nbssdlkm）—— 四层记忆 + 预算竞争
- Facts（unresolved/resolved + resolves 级联 + caused_by + known_to/hidden_from）+ Thread 剧情线 + 章节摘要 + RAG 四层；P0-P5 六层预算竞争 + core_guarantee 400 token 低保。
- "AI 只建议、人确认"（D-0029）；多稿对比（DraftNavigator）；别名归一化表。
- **给 NSC**：运行时事实生命周期、预算竞争与低保、人确认交互档、别名管理、多 collection 检索分区。
- 证据目录：`/tmp/novel_research/FicForge/src-engine/{domain,services,vector}`。

### 7.6 NovelForge（RhythmicWave）—— Schema-first + @DSL
- 卡片体系（通用表 + 类型 schema + 树）；动态输出模型（可视化定义 JSON Schema + Pydantic 强校验 + 指令流生成 `{"op":"set",...}` 逐条校验）；@DSL 声明式上下文检索（跨节点/过滤器/索引表达式）；知识图谱 KGRelation（SQLite 默认，Neo4j 可选）。
- **给 NSC**：@DSL 声明式注入、Schema Studio 用户可扩展边界、指令流生成（探索阶段可用）、关系显式存储。
- 证据目录：`/tmp/novel_research/NovelForge/{backend/app/services,frontend/src/renderer/src/services}`。

### 7.7 Novel Distiller（FutureFuzzy）—— 蒸馏方法论
- 角色 SKILL.md"思维操作系统"（心智模型/决策启发式/表达 DNA/诚实边界，6 路 Probe 蒸馏 + 三重验证 + 失败重试）；先推演再撰写（ReACT 协议，意外发现最有价值）；暗线数值状态 + 每章快照；8 维锚定自检 + 番茄/起点/知乎平台规则。
- **给 NSC**：角色心智模型字段、场景推演 Pass、暗线数值锚定、平台合规规则。
- 证据目录：`/tmp/novel_research/novel-distiller/novel_distiller/`、`demo/`。

### 7.8 One Sentence, One Drama（arXiv:2605.22144）—— 短剧生成系统（含视频）
- 三组件：① 多智能体辩论式故事生成（300 部短剧 → 2,923 beat 原子库 + 6,984 因果块；三裁判并行评审 + 确定性聚合 + 仅争议仲裁 + patch 修订 + Idea Bank）；② 3D 接地首帧（panorama→3D 世界→相机注册，保跨镜空间一致）；③ 多阶段 reviewer loop（文本/图像/视频/音频 + 硬 gate）。
- 评测：Short-Drama-Bench（50 提示词 7 大类 + 8 个短剧专属指标），消融证明"每个组件治一种失败模式、review 全局兜底"。
- **给 NSC（不含视频）**：节奏显式化字段、知识状态线、beat/pattern 检索库（sqlite-vec 落地）、issue list+root-cause+定向修订三件套、多视角候选不互评、Idea Bank、道具/空间连续文本级约束。
- 证据：arxiv.org/html/2605.22144v1（HTML 已抓取暂存 /tmp/paper/）。

---

## 8. 未尽事项 / 局限说明

- 同名项目歧义：`novel-studio`、`NovelForge`、`StoryWriter`、`FicForge` 均存在多个同名仓库，本调研各选了一个最贴合"小说/剧本生成管线"的代表（详见 §0 链接）。若强模型指代的不是所选仓库，需重新克隆。
- 克隆仓库在 `/tmp/novel_research/`（沙箱临时目录，可能被清），强模型如需深挖请据 §0 链接重新 `git clone --depth 1`。
- 本文件基于子代理对克隆仓库的精读 + 论文全文抓取，引用路径均为当时克隆内的真实路径；外部项目后续可能有更新，以决策时点最新 commit 为准。
- 涉及 `spec/ir/**` 改动（建议 1-5、13）按 AGENTS.md §5 必须先开 ADR（status: proposed）并经确认；涉及 `spec/checks/**` 的 `severity: block`、`eval/thresholds.yaml`、新第三方服务同样必须停下问。
