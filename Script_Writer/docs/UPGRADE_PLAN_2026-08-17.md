# Script Writer（NSC）工程改造方案 · 最终版（2026-08-17）

> **本文档是最终工程决策，不是调研报告。** 依据 `docs/RESEARCH_EXTERNAL_2026-08-17.md`（事实层）+ 8 个外部方案的代码级精读规格做出全部裁决。
> **授权条款**：项目负责人 2026-08-17 指令——"不要有任何需要人类确认或者人类校准的东西，这些开源项目和论文就代表了先进的人类校准，直接拿来就用"。因此本方案涉及的 4 份 ADR（0011–0014）直接以 `status: accepted` 落盘，开发者按工单直接开工，无需等待任何确认。
> **设计准则**：AI 开发难度最低化——每个工单逻辑确定、输入输出封闭、验收命令可在 CI 跑；宁可多写工单，不留模糊地带。

---

## 0. 决策总则

1. **只吸收已被 ≥2 个独立外部方案验证的机制**；单一方案独有的花活（@DSL、KG 图库、动态 Schema、视频管线）一律不进。
2. **一切知识落 `spec/`，一切机制落 `src/`**。词表、阈值、红线全部参数化进 YAML；Python 里不出现业务词表/业务阈值（D21 精神不变）。
3. **不触碰现有硬约束**：无多智能体互评/辩论、无编排框架、仅 SQLite+sqlite-vec、LLM 全走 `runtime/models.py`、每产物写 provenance。
4. **向后兼容**：IR `schema_version 1.0 → 1.1` 纯新增可选字段，旧 IR 自动迁移；所有新 Pass 输出字段带默认值。
5. **全自动闭环**：人类品味注入点保持现状（交付后 docx 反馈 → 反向对齐），不在编译回路里加人审节点；用 Idea Bank + 快照回退替代"人审候选"。

---

## 1. 十四个决策问题的最终裁决

| # | 问题 | 裁决 | 一句话理由 |
|---|---|---|---|
| 1 | 多智能体边界 | **维持禁止**。不引入 N 路仲裁；保留 p5 现有可选 `--rerank`（单 Pass 多候选 + 确定性过滤，非互评） | 外部 4 个多 agent 项目全部付出 4-5 次 LLM/章的线性成本且无校准，NSC 的确定性 Pass + 判官路线被 autonovel 实测（绝对分塌缩）反向背书 |
| 2 | 大纲粒度 | **维持 Beat/Line 全类型化**；吸收 StoryWriter 事件模板作为 `Beat.summary` 的**写作格式引导**（改 p3 签名 docstring，不改 IR） | 营销短剧每拍要挂品牌约束与可判定性，事件级自由发挥不适用；但事件模板的信息密度值得抄进 prompt 引导 |
| 3 | 人类中心程度 | **维持全自动**。人确认保持"交付后 docx 反馈"单入口；编译回路内不加人审 | 业务 = 商家确认物在编译之后；回路内加人审破坏可缓存性与无人值守 |
| 4 | 记忆形态 | **类型化 IR + 显式 Fact/Thread 关系节点 + SQLite 快照**；向量检索降级为可整体丢弃的 P4 辅助层 | 5/8 方案共识"记忆必须显式化"；FicForge/inkos 证明关系型声明比纯向量更保一致性 |
| 5 | 动态用户 Schema | **否决** | spec/ 统一模式是 NSC 全部可测试性的根基；用户扩展走 profiles 元数据（现有机制） |
| 6 | 全量 keep/discard vs 局部重编译 | **维持局部重编译**，在其上叠加**内容哈希快照链 + revisionGate 门禁**（存 SQLite，不用 git） | dep_graph 闭包已是最精确的局部修订；autonovel 的 git 取舍粒度过粗，但其"退步即回滚"判定公式值得抄 |
| 7 | @DSL 注入 | **否决 DSL**；注入组装由新 `src/nsc/context/` 模块承担（机制在代码，参数在 profile） | jmespath/simpleeval 已覆盖规则侧；NovelForge 的 @DSL 依赖前端全量内存卡片，百万字级即崩（反模式 #8） |
| 8 | 视频边界 | **不做视频**；One-Sentence 只吸收文本级产物（节奏字段、知识状态线、Idea Bank、patch 语义） | 既定边界，无争议 |
| 9 | 模型路由 | **不变** | 统一路由 + 本地检索的正确性被外部闭源依赖反例背书 |
| 10 | 绝对分 vs 成对 | **维持成对判官**；新增 **Elo 锦标赛**作为评测模式（非门禁） | autonovel 实测 1-10 分塌缩到 2 分带宽；Elo 参数直接抄（1500/K32/4 轮 Swiss/无平局） |
| 11 | 节奏显式化 | **采纳**：Scene 增加 `opening_attractor / escalation_beats / ending_hook / knowledge_state`（ADR-0012） | One-Sentence 与 StoryWriter 共同验证；短剧节奏算法化的直接答案 |
| 12 | 运行时事实生命周期 | **采纳**：新增 Fact/Thread/StateVariable/DarkThread 覆盖层，**声明式存储 + 派生视图**（不改写 IR，build_view 计算现值） | 共识 C 的核心缺口；声明式方案避免 FicForge 的 ops 日志半拉子坑（反模式 #7） |
| 13 | 关系显式存储 | **部分采纳**：`Fact(type=relationship)` + `caused_by` 因果链覆盖；**不建 KG 图库** | NovelForge 的 KGRelation 唯一约束思路用 IR 不变量 INV-17/18 等价实现，零新依赖 |
| 14 | 反馈/预算/评测增强 | **全部采纳**：多源修订 brief、spot-fix patch、快照门禁、Idea Bank、P0-P5 上下文预算、plateau 停止、多视角判官、Elo | 这些是 NSC 相对外部最薄弱的三环（brief 合成、零成本统计检查、预算管理） |

---

## 2. 目标架构总览

```
                        ┌──────────── 新增（本方案） ────────────┐
spec/ir/                overlays.py  + Fact/Thread/StateVariable/DarkThread/KnowledgeState
                        nodes.py     + Scene 节奏字段、Episode.responds_to/state_changes、Character 心智 OS
                        invariants   + INV-17..20；schema_version 1.1
spec/checks/            prose/       新域 16 条（PRS-001..016 + _wordlists.yaml）
                        structure/   + STR-014/015（Wave A），+ STR-016/017/018（Wave B）
                        compliance/  + CMP-003..007（平台合规）+ _platform_terms.yaml
                        fact/        + FCT-003/006/007（Wave B）
                        dialogue/    + DLG-008（Wave B）
spec/rubrics/           anchors/prose_craft.yaml  + 12 反模式锚点（A 层品味资产）
                        pairwise_protocol.md      + 三视角判官协议（ADR-0014）
src/nsc/textstats/      【新模块】确定性文本统计（段长CV/句长CV/n-gram/前缀run…），纯函数无业务参数
src/nsc/revise/         【新模块】snapshot.py（快照链）/ gate.py（revisionGate）/ patch.py（spot-fix）
                                 / idea_bank.py（Idea Bank）/ revision_brief.py（多源 brief 合成）
src/nsc/context/        【新模块】assembler.py（P0-P5 预算竞争）/ compress.py（历史压缩）
src/nsc/checker/        registry.py  + textstats 薄注册（≤40 行）
src/nsc/passes/         p1/p2/p3/p4 签名扩展；p3 输出 Facts+state_changes；p6 吃压缩上下文
src/nsc/judge/          rubric_judge.py + 三视角；eval/l1.py + --tournament（Elo）
src/nsc/optimize/       gepa_metric.py 接入 revision_brief；gepa_run.py + plateau 停止
```

---

## 3. ADR 清单（均已落盘 `adr/`，status: accepted）

| ADR | 标题 | 覆盖范围 |
|---|---|---|
| ADR-0011 | 确定性文本统计检查与 prose 检查域 | 新域 prose、16 条规则、textstats 模块、含 3 条 block 级（PRS-009/010、STR-014/015、CMP-003/004/005）授权 |
| ADR-0012 | IR 1.1：运行时叙事状态层 | Fact/Thread/StateVariable/DarkThread、Scene/Episode/Character 字段扩展、INV-17..20、schema 迁移 |
| ADR-0013 | 新模块 src/nsc/{textstats,revise,context} 与 BUDGETS 调整 | 三个新模块预算条目、runtime+checker 1500→1600、总量 6500→7800 |
| ADR-0014 | 判官三视角、Elo 锦标赛、plateau 停止条件 | pairwise_protocol 资产变更、eval 新增模式、GEPA/revision 循环停止条件 |

---

## 4. IR 1.1 完整规格（ADR-0012；Wave B 实施）

### 4.1 `spec/ir/overlays.py` 新增

```python
class FactStatus(StrEnum):
    active = "active"
    unresolved = "unresolved"
    resolved = "resolved"
    deprecated = "deprecated"


class FactType(StrEnum):
    character_detail = "character_detail"
    relationship = "relationship"
    backstory = "backstory"
    plot_event = "plot_event"
    foreshadowing = "foreshadowing"
    world_rule = "world_rule"


class SuspenseType(StrEnum):
    foreshadow = "foreshadow"
    secret = "secret"
    misunderstanding = "misunderstanding"
    setup = "setup"


class Fact(BaseModel):
    """叙事事实。声明式：p3 按集声明；resolves 级联由不变量校验，不由代码改写。"""

    model_config = ConfigDict(extra="forbid")
    id: ULID
    content: NonEmpty  # 纯叙事描述，注入 prompt 用
    character_ids: list[ULID] = []  # 涉及角色（INV-09 同款跨引用校验）
    episode_no: int = Field(ge=1)  # 声明于第几集
    status: FactStatus = FactStatus.active
    type: FactType = FactType.plot_event
    resolves: ULID | None = None  # 本 fact 回收了哪条伏笔（INV-17）
    caused_by: list[ULID] = []  # 直接因（INV-18：因必须在更早或同集）
    known_to: Literal["all", "reader_only"] | list[ULID] | None = None
    hidden_from: list[ULID] = []
    suspense_type: SuspenseType | None = None
    narrative_weight: Literal["low", "medium", "high"] = "medium"
    thread_ids: list[ULID] = []  # 成员关系唯一真相源在 Fact 侧（Thread 不存 fact_ids）


class ThreadStatus(StrEnum):
    active = "active"
    resolved = "resolved"
    dormant = "dormant"


class Thread(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ULID
    title: NonEmpty  # 剧情线名
    state: str = ""  # 当前进展一句话（注入用）
    status: ThreadStatus = ThreadStatus.active


class StateVariable(BaseModel):
    """数值/字符串锚点（暗线数值状态）。initial 存储，current 由 build_view 派生。"""

    model_config = ConfigDict(extra="forbid")
    key: Slug
    name: NonEmpty
    type: Literal["number", "string"] = "number"
    initial: float | str = 0
    description: str = ""


class DarkThread(BaseModel):
    """阶段机暗线。stages 为有序阶段名；current_stage 由 build_view 派生。"""

    model_config = ConfigDict(extra="forbid")
    key: Slug
    name: NonEmpty
    stages: list[NonEmpty] = Field(min_length=2)
    description: str = ""


class StateChange(BaseModel):
    """p3 按集声明的状态增量。确定性应用规则（build_view 派生时执行）：
    number 变量 → 累加；string 变量 → 覆盖；dark_thread → current_stage 累加。"""

    model_config = ConfigDict(extra="forbid")
    key: Slug  # → StateVariable.key 或 DarkThread.key
    delta: float | int | str  # number→数值增量；dark_thread→int 阶段步进；string→新值
    reason: NonEmpty  # 变化原因（FCT-007）


class MentalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: NonEmpty
    description: str = ""
    trigger: str = ""  # 触发条件
    action_tendency: str = ""  # 行动倾向
    failure_mode: str = ""  # 局限·失败模式


class ExpressionDNA(BaseModel):
    model_config = ConfigDict(extra="forbid")
    syntax: str = ""  # 句法特征
    rhetoric: str = ""  # 修辞偏好
    emotion_temperature: str = ""  # 情感温度（怒/悲/喜/惧的行为模式）
    signature_lines: list[str] = []  # 典型句式示例


class KnowledgeState(BaseModel):
    """场末知识状态线（悬念管理的结构基础）。"""

    model_config = ConfigDict(extra="forbid")
    audience_knows: str = ""  # 观众知道
    characters_know: str = ""  # 角色知道
    hidden: str = ""  # 仍隐藏
    new_evidence: str = ""  # 本场新证据
```

### 4.2 既有节点字段扩展（全部可选，默认空 → 1.0 IR 无损迁移）

```python
class Scene(_Node):  # 追加
    opening_attractor: str = ""  # 开场吸引子（首 Beat 如何 3 秒内抓人）
    escalation_beats: list[str] = []  # 场内升级阶梯（2-4 个递进步）
    ending_hook: str = ""  # 切出钩子（与 Episode.cliffhanger 呼应）
    knowledge_state: KnowledgeState | None = None


class Episode(_Node):  # 追加
    responds_to: list[int] = []  # 本集回应了哪些前集的 cliffhanger（集号，STR-016）
    state_changes: list[StateChange] = []  # 本集状态增量（FCT-006/007）


class Character:  # 追加（心智操作系统，novel-distiller SKILL.md 的结构化子集）
    mental_models: list[MentalModel] = Field(default_factory=list, max_length=5)
    decision_heuristics: list[str] = Field(default_factory=list, max_length=7)
    honest_boundaries: list[str] = Field(default_factory=list)  # 该角色绝不做的判断/事
    expression_dna: ExpressionDNA | None = None
```

### 4.3 `container.py`：`NarrativeIR` 追加四张表 + `schema_version: Literal["1.1"]`

```python
facts: list[Fact] = []
threads: list[Thread] = []
state_variables: list[StateVariable] = []
dark_threads: list[DarkThread] = []
```

`build_view` 派生（机制，落 `ir_io.py`）：`state_variables[*].current`（initial + Σdelta）、`dark_threads[*].current_stage`（Σ阶段步进，越界即 INV-19 失败）、`facts[*].is_overdue`（供 FCT-003）。

### 4.4 新不变量（`spec/ir/invariants.{md,py}`，全部 `severity: block`）

| ID | 不变量 | 形态 |
|---|---|---|
| INV-17 | `Fact.resolves` 指向存在的 Fact；`status==resolved` ⇔ 存在非 deprecated 的 resolver（级联一致） | `[[form:check]]` |
| INV-18 | `caused_by` 引用存在的 Fact 且其 `episode_no ≤` 本 fact 的 `episode_no` | `[[form:check]]` |
| INV-19 | DarkThread 派生 `current_stage ∈ [0, len(stages)-1]`；number 型 StateVariable 的全部 delta 为数值 | `[[form:check]]` |
| INV-20 | `Episode.responds_to` 元素均为存在的、严格更小的集号 | `[[form:check]]` |

### 4.5 迁移

`ir_io.py` schema 迁移入口：`1.0 → 1.1` 纯新增默认空字段，旧 JSON 加载即升级；`merge_preserving_ids` 不受影响（主干节点零改动）。回滚 = 忽略新字段重序列化。

---

## 5. 新检查规则完整规格

> 词表/阈值统一放 `spec/checks/prose/_wordlists.yaml` 与 `spec/checks/compliance/_platform_terms.yaml`（仿 `_absolute_terms.yaml` 加载机制；T-27 含把 `__ctx` 加载器从 compliance 专用泛化为按域自动加载 `_*.yaml`）。
> 每条规则必须配 `tests/fixtures/checks/<ID>/{pass,fail}.json + expected.txt`（DSL §6，CI 强制）。
> **新增 registry 白名单函数**（实现落 `src/nsc/textstats/`，registry 仅注册；全部为无业务参数的纯机制函数）：
> `para_cv(s)` `sent_cv(s)` `max_consecutive_char_lines(s,ch)` `long_paras(s,n)` `density_exceeds(s,words,unit)` `max_word_count(s,words)` `same_prefix_runs(s)` `join_text(paras)` `chapter_ngram_repeats(chapters,order,n)` `chapter_para_drift(chapters,order)`

### 5.1 prose 域（Wave A，16 条；stage 均 `after_p6`）

| ID | severity | select | assert（参数来自 `_wordlists.yaml`，经 `@.__ctx.prose.*` 绑定） | 检查含义（来源） |
|---|---|---|---|---|
| PRS-001 | warn | `chapters[*]` | `para_cv(join_text(item.paragraphs)) >= 0.15` | 段落长度变异系数（inkos dim20） |
| PRS-002 | warn | `chapters[*]` | `sent_cv(join_text(item.paragraphs)) >= 0.3` | 句长变异系数（autonovel） |
| PRS-003 | warn | `chapters[*]` | `max_word_count(text, fatigue_words) <= 1` | 疲劳词每词每章≤1次（inkos；词表默认 urban 档，profile 可覆盖） |
| PRS-004 | warn | `chapters[*]` | `not density_exceeds(text, hedge_words, 333)` | 对冲套话密度>3/千字（似乎/可能/或许/大概/某种程度上/一定程度上/在某种意义上） |
| PRS-005 | warn | `chapters[*]` | `max_word_count(text, transition_words) < 3` | 公式化转折词复用（然而/不过/与此同时/另一方面/尽管如此/话虽如此/但值得注意的是） |
| PRS-006 | warn | `chapters[*]` | `not density_exceeds(text, surprise_markers, 3000)` | 惊讶标记词密度（仿佛/忽然/竟然/猛地/猛然/不禁/宛如；上限 max(1,字数/3000)） |
| PRS-007 | warn | `chapters[*].paragraphs[*]` | `not regex_any(item, banned_sentence_patterns)` | 禁句式「不是…而是…」（inkos 正则原文） |
| PRS-008 | warn | `chapters[*].paragraphs[*]` | `not regex_any(item, meta_narration_patterns)` | 元叙事编剧旁白（6 条正则，inkos 原文） |
| PRS-009 | **block** | `chapters[*].paragraphs[*]` | `not contains_any(item, report_terms)` | 报告术语入正文=大纲语言残留（核心动机/信息边界/信息落差/核心风险/利益最大化/当前处境/行为约束/性格过滤/情绪外化/锚定效应/沉没成本/认知共鸣） |
| PRS-010 | **block** | `chapters[*]` | `not regex_any(text, chapter_ref_patterns)` | 章节号指称（`第\s*\d+\s*章` / `Chapter\s+\d+`） |
| PRS-011 | info | `chapters[*]` | `max_consecutive_char_lines(text, '了') < 6` | 连续「了」字句（inkos 实际阈值 6） |
| PRS-012 | info | `chapters[*]` | `long_paras(text, 300) < 2` | 段落过长（>300字段≥2） |
| PRS-013 | warn | `chapters[*].paragraphs[*]` | `not regex_any(item, collective_shock_patterns)` | 全场震惊集体反应（2 条正则，inkos 原文） |
| PRS-014 | warn | `chapters[*].paragraphs[*]` | `not contains_any(item, sermon_words)` | 作者说教词（显然/毋庸置疑/不言而喻/众所周知/不难看出） |
| PRS-015 | warn | `chapters[*]` | `chapter_ngram_repeats(all_chapters, item.order, 6) < 3` | 跨章重复：纯汉字 6-gram 与更早章节重复≥3 个（inkos） |
| PRS-016 | warn | `chapters[*].paragraphs[*]` | `not contains_any(item, ['——'])` | 破折号「——」（中文叙述建议逗号/句号替代，inkos 规范化规则） |

message 写作一律遵守 DSL §5 三件套（违反什么+为什么+怎么改），示例（PRS-009）：
`"段落出现大纲/分析报告用语（如"核心动机""信息边界"）。这是规划层语言残留进正文，读者会立刻出戏，是最典型的 AI 味之一。请删除或改写为角色的自然言行。"`

### 5.2 structure 域（Wave A 2 条）

| ID | severity | stage | select | assert | 含义 |
|---|---|---|---|---|---|
| STR-014 | **block** | after_p3 | `episodes[*]` | `any_of(item.beats, "x.beat_kind == 'inciting'") and any_of(item.beats, "x.beat_kind == 'climax'")` | 承重 beat 在场（每集≥1 引爆 + ≥1 高潮；novel-studio 红线） |
| STR-015 | **block** | after_p3 | `episodes[*]` | `emotion_range(item.beats) > 0` | 情感弧零振幅即失败（入口=出口红线；registry 已有 `emotion_range`） |

### 5.3 compliance 域（Wave A 5 条；legal_ref 指向 `_legal_sources.md` 新增 `#platform-rules` 节，stage 均 `final`，文本源 `@.__ctx.ir.__all_text`）

| ID | severity | assert（词表在 `_platform_terms.yaml`） | 对应平台规则 |
|---|---|---|---|
| CMP-003 | **block** | `not contains_any(all_text, violent_terms)` | 番茄 must_avoid：暴恐/血腥（碎尸/酷刑/分尸/制毒/爆炸物制作 等高精度词） |
| CMP-004 | **block** | `not contains_any(all_text, explicit_terms)` | 番茄 must_avoid：露骨性描写 |
| CMP-005 | **block** | `not contains_any(all_text, political_terms)` | 番茄 must_avoid：现实政治影射 |
| CMP-006 | warn | `not contains_any(all_text, superstition_terms)` | 番茄 must_avoid：现实迷信仪式宣扬（奇幻设定不禁） |
| CMP-007 | warn | `not contains_any(all_text, bullying_terms)` | 番茄 must_avoid：校园霸凌详细描写/美化 |

平台 must_have 节奏项（每 1000 字爽点、压抑释放比 3:7、前 100 字钩子等）**不进 checker**（语义判断），落 `spec/rubrics/anchors/hook_strength.yaml` 与 `naturalness.yaml` 的锚点描述。

### 5.4 Wave B 规则（⇐ ADR-0012 落地后）

| ID | 域 | severity | stage | assert 要点 |
|---|---|---|---|---|
| FCT-003 | fact | warn | after_p3 | 高权重伏笔逾期：`facts[?status=='unresolved' && narrative_weight=='high']` 的 `is_overdue`（当前最大集号−声明集号 > `ctx.profile.fact.overdue_episodes`，默认 3）全为 false |
| FCT-006 | fact | warn | after_p3 | 每集至少一条状态推进：`count(item.state_changes) >= 1`（select `episodes[*]`，末集豁免由 profile 开关） |
| FCT-007 | fact | warn | after_p3 | 状态变化必有原因：`all_of(item.state_changes, "chars(x.reason) >= 2")` |
| STR-016 | structure | warn | after_p3 | 悬念闭环：`episodes[?chars(cliffhanger) > 0]` 的集号均被其后 ≤3 集内某集 `responds_to` 包含（registry 加一个 `covered_by_responds(episodes, no, window)` 纯函数） |
| STR-017 | structure | warn | after_p4 | 首场 `opening_attractor` 非空 且 末场 `ending_hook` 非空（select `episodes[*]`，经 view 嵌套取 scenes 首末） |
| STR-018 | structure | info | after_p3 | 每集 ≥1 个 `{reversal, complication, escalation}` beat |
| DLG-008 | dialogue | warn | after_p5 | 对白行禁对仗平衡句式：`not regex_any(item.text, ['不是[^，。！？\n]{3,40}[，,]?\s*而是'])`（select `lines[?line_type=='dialogue']`；两个角色共用该句式=角色不区分） |

**规则预算核算**：现有 48 + Wave A 23 + Wave B 7 = **78 ≤ 90**（`max_active_check_rules`）。余量 12 条留给反馈管道挖掘的 L3 晋升。

---

## 6. 新 src 模块规格（函数签名级，ADR-0013）

### 6.1 `src/nsc/textstats/`（预算 300 行；纯函数，零业务参数，零 LLM）

```python
def split_paragraphs(text: str) -> list[str]          # \n\s*\n 切段
def split_sentences(text: str) -> list[str]           # [。！？!?] 切句，弃 ≤2 字碎片
def para_cv(text: str) -> float                       # 段长(字符)总体变异系数；<3 段返回 1.0（免检）
def sent_cv(text: str) -> float                       # 句长(字数)CV；≤2 句返回 1.0
def max_consecutive_char_lines(text: str, ch: str) -> int
def long_paras(text: str, n: int) -> int
def density_exceeds(text: str, words: list[str], unit: int) -> bool   # count > max(1, len//unit)
def max_word_count(text: str, words: list[str]) -> int
def same_prefix_runs(text: str) -> int                # 相邻句相同前2字前缀的最长连续数
def join_text(paras: list[str]) -> str
def hanzi_ngrams(text: str, n: int) -> set[str]       # 纯汉字 n-gram
def chapter_ngram_repeats(chapters: list[dict], order: int, n: int) -> int
def chapter_para_drift(chapters: list[dict], order: int) -> bool      # shrinkRatio<0.6 且 shortRatio≥0.5 且 Δ≥0.25
def covered_by_responds(episodes: list[dict], no: int, window: int) -> bool
```
测试：每函数 ≥3 case（边界：空文本/单段/恰好阈值）。

### 6.2 `src/nsc/revise/`（预算 500 行）

**`patch.py` — spot-fix 引擎**（语义照抄 inkos，全部确定性）：
```python
@dataclass class Patch: target: str; replacement: str
def parse_patches(llm_output: str) -> list[Patch]     # --- PATCH n --- TARGET_TEXT:/REPLACEMENT_TEXT:/--- END PATCH ---
def apply_patches(content: str, patches: list[Patch]) -> PatchResult
# 匹配两级：① 精确 indexOf，要求唯一（两处以上判失败）② 空白归一化匹配（target<10 字放弃），坐标线性映射回原文
# 单 patch 失败仅跳过；applied_count/len(patches) >= 0.5 才整体采用，否则保留原文
# PatchResult{applied, content, applied_count, skipped_count, touched_chars, rejected_reason}
```

**`gate.py` — revisionGate**（计数来自 checker report + 可选 judge 分）：
```python
def decide(before: Counts, after: Counts, mode: Literal["strict","lenient","always"]="strict") -> bool
# Counts{block, warn, info, judge_score: float|None}
# strict : did_not_worsen(block,warn,judge) and (block<a.block or warn<a.warn or judge 提升)
# lenient: did_not_worsen 即可；always: True
```

**`snapshot.py` — 快照链**（SQLite 表 `snapshots`，不用 git）：
```python
def save_snapshot(project_id, stage, ir_json, counts, judge_score) -> str   # snapshot_id=内容哈希
def best_snapshot(project_id, stage) -> Snapshot | None                     # 门禁判定用
def rollback_to(snapshot_id) -> dict                                        # 返回 IR JSON
```

**`idea_bank.py` — Idea Bank**（One-Sentence 附录 G；防 GEPA/修订过度修正）：
SQLite 表 `idea_bank(bank_id, project_id, node_kind, content, source_node_id, removed_run_id, reason, quality_note, revived, created_at)`。
修订/重编译删除内容时由 revise 模块写入；p2/p3 的上下文组装可选注入"可复活素材"层；CLI `nsc bank list|revive <bank_id>`（revive 只把素材注入下次编译上下文，由 LLM 决定是否采用——不直接改 IR）。

**`revision_brief.py` — 多源修订 brief 合成**（autonovel gen_brief 的 NSC 版，NSC 当前完全缺失的一环）：
```python
def build_brief(target: str, checker_report: dict, judge_result: dict|None, elo_result: dict|None) -> str
# 输入三源：checker findings（按规则分组，block 优先）/ 判官成对结果与维度注记 / Elo 排名（可选）
# 输出固定五节（≤ gepa_feedback_chars=2600，超出按 block→warn→info 优先级截断）：
#   ## PROBLEM    block findings 全文 + 判官指出的最弱维度/最弱时刻
#   ## WHAT TO KEEP  判官标注的最强句/最强场 + 零 findings 的节点 ID 清单（禁止动）
#   ## WHAT TO CHANGE  编号清单：每条 finding 的 message + fix_hint（诊断句三件套直接复用）
#   ## VOICE RULES   从 spec/rules/L3_canonical 中 form==prompt 的规则抽取（不硬编码）
#   ## TARGET      brief_type 判定：judge≤0.5→REWRITE；≤0.7→FIX；>0.7→POLISH；
#                  含密度类 finding→COMPRESS(0.55×字数)；含堆叠/冗长类→TIGHTEN(0.85×字数)
# 消费方：gepa_metric.py 的 feedback 通道（brief 作为 PROBLEM 节来源）+ p5 自检子步
```

### 6.3 `src/nsc/context/`（预算 500 行；机制在代码，全部参数在 profile）

**`assembler.py` — P0-P5 预算竞争**（FicForge 规格的 NSC 映射）：

| 层 | 内容 | 规则 |
|---|---|---|
| P0 | system：profile 的 voice/tone + 角色 voice_notes/voice_tics/forbidden_words | **core_guarantee=400 token 低保，永不裁剪**；超预算裁 custom 部分后仍超 → 抛 `PassFailure` |
| P1 | 当前集 beats/scenes 等 Pass 输入本体 | 必须完整保留，最先计入 used |
| P2 | 上一集摘要 + 上集 cliffhanger/本集 hook_promise | 超预算保留末尾，下限 500 字 |
| P3 | active+unresolved Facts + active Threads | 软降级：权重 high→low、近集优先逐条取舍；被丢条数写成 hint 行注入 |
| P4 | retrieval 命中条目 | 超预算**整层丢弃** |
| P5 | bible 其余（locations/props/motifs/角色详情） | 超预算静默跳尾部 |

每层预算 = `max(0, base − used − guarantee)`；降级顺序 P3→P4→P2→P5（P0/P1 不动）。每层实际 token 写入 pass 运行记录（DB `runs` 表扩展字段，不动 IR Provenance 冻结模式）。

**`compress.py` — 历史压缩**（StoryWriter MessageRedact 的 NSC 版）：
p3/p6 组装上下文时，对 `current_no − 2` 及更早的集：注入 LLM 压缩摘要（压至 ~10%，保留关键情节/角色冲突/结尾反转，舍弃环境描写与次要对话）替代 beats 细节；保留首部（bible）与末两条（上一集摘要 + 本集计划）原样。压缩走 `runtime/cache.py` 内容寻址缓存（同内容不重复调 LLM）。

---

## 7. Pass / 签名 / dep_graph 变更

| Pass | 变更 | 阶段 |
|---|---|---|
| p1_bible | 输出 Character 心智 OS 字段（mental_models ≤5 / decision_heuristics ≤7 / honest_boundaries / expression_dna） | Wave B |
| p2_arc | 输出 Thread[]/DarkThread[]/StateVariable[] + `Episode.responds_to` 规划 | Wave B |
| p3_beatsheet | ① `Beat.summary` 按事件模板格式书写（Setting/Character/Action/Conflict/Twist，签名 docstring 引导）② 输出 Facts[]（含 resolves 的 `PENDING:<slug>` 前向引用，复用 SetupPayoff 解引用机制）③ 输出 `Episode.state_changes` | Wave B |
| p4_scene | 输出 Scene 节奏字段 + knowledge_state | Wave B |
| p5_dialogue | 自检子步的输入从"L3 prompt 规则"升级为 revision_brief 五节（T-31 接入） | Wave A 后 |
| p6_prose | 输入改经 context/assembler + compress（签名不变，输入组装变） | Wave A |
| p7_render | 不变（零 LLM 铁律不动） | — |

`spec/passes/CONTRACTS.md`、`signatures.py`、`dep_graph.yaml` 同步更新。dep_graph 新增：`facts/threads/state_variables/dark_threads` 变更 → 失效相关集 p3–p7；`Episode.state_changes` 属 Episode 节点，失效闭包与 Episode.logline 相同。**快照落盘**是 pipeline 机制（p3 全季后处理之后调用 `revise/snapshot.py`），不是新 Pass。

---

## 8. 评测与优化变更（ADR-0014，Wave C）

1. **三视角判官**：`rubric_judge` 指令内嵌三视角——编辑（prose 工艺/声音一致性）、类型读者（节奏/钩子/翻页欲）、普通读者（情绪诚实、不用术语）。同一判官调用输出三视角注记 + 分歧标记；聚合逻辑不变（确定性）。分歧项写入 feedback 的"编辑决策点"节，**不作门禁**。（这是同一 LLM 的多视角，不是多 agent 互评，不触红线。）
2. **Elo 锦标赛**：`nsc eval l1 --tournament`。参数固定：初始 1500、K=32、4 轮 Swiss（按 Elo 降序相邻配对）、无平局（必须选胜方）、judge temperature=0.2、每章截断 3000 字、5 条比较轴（prose 锐度/对话口语感/真实张力/信任读者/AI 模式更少）。输出排名报告，仅作分析。
3. **plateau 停止**（revision 循环与 GEPA 通用）：归一化指标相邻两轮 Δ<0.03 且已跑 ≥3 轮 → 停；硬上限 6 轮。修订退步（门禁后计数恶化）→ `snapshot.rollback_to(best)`。
4. **GEPA feedback 升级**：`gepa_metric.py` 的 feedback 五节中 PROBLEM 节改由 `revision_brief.build_brief` 生成（checker 三源合一），其余节不变；`test_gepa_metric.py` 六条断言相应扩展。
5. **rubric 锚点增强**：autonovel 12 条结构性反模式（OVER-EXPLAIN/TRIADIC LISTING/NEGATIVE-ASSERTION/CATALOGING-BY-THINKING/SIMILE CRUTCH/SECTION-BREAK CRUTCH/PARAGRAPH UNIFORMITY/PREDICTABLE ARCS/REPETITIVE ENDINGS/BALANCED ANTITHESIS/DIALOGUE-AS-PROSE/SCENE-SUMMARY IMBALANCE）逐条落成 `prose_craft.yaml` 的锚点描述与反例；不新增 rubric 维度（6 维上限）。

---

## 9. 预算与护栏影响（ADR-0013）

| 项 | 现状 | 变更后 |
|---|---|---|
| `src/nsc/runtime,src/nsc/checker` | 1433/1500 | 预算 1500→**1600**（registry 薄注册 +40、ir_io 视图派生 +60；均为机制非业务知识，D21 精神不变） |
| `src/nsc/textstats` | — | **300** |
| `src/nsc/revise` | — | **500** |
| `src/nsc/context` | — | **500** |
| `src/nsc` 总量 | 10166（账面已超 6500 警戒线，见下注） | 警戒线 6500→**7800** |
| `max_active_check_rules` | 48/90 | 78/90（余量 12） |

> 注：实测 `src/nsc` 10166 行已超过 6500 警戒线但 spec-guard 未红，说明 guard 计数口径与 `wc -l` 不同（可能排除空行/注释/测试）。T-27 前置任务：**核对 `guards/budgets.py` 计数口径并在 BUDGETS.yaml 注释中写清**，避免新模块把账面推过真实口径。

---

## 10. 工单索引（完整版见 `docs/WORK_ORDERS.md`）

**Wave A · 零 IR 改动（先做，纯增量，立见效）**
- T-27 ⭐ textstats 模块 + prose 域 16 条规则 + `__ctx` 加载器泛化
- T-28 结构红线 STR-014/015
- T-29 平台合规 CMP-003..007 + `_legal_sources.md` 更新
- T-30 12 反模式锚点入 rubric + 平台 must_have 节奏锚点
- T-31 ⭐ revision_brief 合成器 + 接入 gepa_metric/p5 自检
- T-32 ⭐ revise 模块（patch/gate/snapshot/idea_bank）
- T-33 context 模块（P0-P5 预算 + 历史压缩）+ p6 接入

**Wave B · IR 1.1（⇐ ADR-0012，T-34 是其余工单的地基）**
- T-34 ⭐ IR 1.1 落地：overlays/字段扩展/INV-17..20/schema 迁移/视图派生
- T-35 p1/p2 签名扩展（心智 OS + Thread/暗线/变量声明）
- T-36 p3/p4 签名扩展（Facts + state_changes + 节奏字段 + 事件模板格式）
- T-37 Wave B 规则 7 条（FCT-003/006/007、STR-016/017/018、DLG-008）
- T-38 CONTRACTS/dep_graph/快照接线 + 重编译闭包测试

**Wave C · 评测与优化增强**
- T-39 三视角判官 + 校准报告含视角分歧统计
- T-40 Elo 锦标赛模式
- T-41 plateau 停止 + Idea Bank 接线 + `nsc bank` CLI
- T-42 端到端回归验收 + BORROW_MAP 增补（#29–#36）

**整体退出条件**：`make ci-local` 全绿；`nsc run` 端到端产物经新 78 条规则检查零 block；`nsc eval l1` 基线对比报告（含 Elo）进 `out/eval/`；`nsc recompile --episode N` 快照链可回退；`git diff` 显示 `prompts/` 零手改。

---

## 11. 不做清单（明确排除，防止后续漂移）

1. 多智能体互评/辩论/仲裁（含"三裁判并行"）——硬约束不变
2. 视频/3D/BGM/转场——业务边界不变
3. 动态用户 Schema / Schema Studio——spec 统一模式不动
4. @DSL 声明式注入语法——jmespath 已够，且前端全量加载是已知坑
5. KG 图库/Neo4j——仅 SQLite；关系用 Fact 节点表达
6. git 全量 keep/discard——局部重编译 + SQLite 快照替代
7. ops.jsonl 式审计日志——git + 确定性重编译已覆盖
8. 编译回路内的人审节点——全自动闭环不变
9. 绝对评分门禁——成对判官 + 已校准门槛不变
10. 编排框架（LangGraph/CrewAI/AutoGen）——纯 Python 函数不变

---

## 12. 风险与缓释

| 风险 | 缓释 |
|---|---|
| prose 统计规则在 golden IR 上误报 | T-27 验收强制"golden IR 零新增 block"；阈值全部取自外部生产项目实测值，不自行发明 |
| runtime+checker 预算顶格 | ADR-0013 已授权 1600；实现时 textstats 不放进 checker 目录 |
| IR 1.1 迁移破坏 ID 稳定性 | T-34 验收含 `test_id_stability` 回归；主干节点零改动，新字段全可选 |
| Facts 前向引用解析失败 | 复用 SetupPayoff 的 `PENDING:<slug>` 既有机制，不新造 |
| 三视角判官被误读为多 agent | ADR-0014 明文界定：同一判官调用内的视角注记，聚合确定性，无 agent 间通信 |
| 外部词表与营销短剧语境不完全匹配 | 词表全部参数化在 `_wordlists.yaml`，反馈管道产出真实案例后按 PROMOTION.md 修订，代码零改动 |
