# 编译 Pass 契约（D5 + D24）

## 0. 共同语义
- 每个 Pass 是**纯函数**：`(IR片段, ctx) → IR片段`。禁止读写全局状态、禁止网络（除 LLM 路由）。
- 每个 Pass 是**一个 DSPy Module**，其 Signature 定义在 `spec/passes/signatures.py`（资产），实现在 `src/nsc/passes/`（可丢弃）。
- **Signature 的 docstring 是"种子指令"**，GEPA 优化后的指令写入 `prompts/<pass>.json`，运行时优先加载。
- 失败语义：结构性失败抛 `PassFailure(node_id, reason)`；不得静默降级。
- 缓存键（D5）：
  `sha256(canonical_json(input_fragment) || pass_name || promptset_ver || profile_ver || brand_ver || ruleset_ver || model_id || temperature || seed || spec_sha_of(relevant_files))`

## 1. Pass 清单

| Pass | 输入 | 输出 | LLM | 检查阶段 |
|---|---|---|---|---|
| `p0_intake` | RawBrief(yaml) + RawBrandBrief + Profile | NormalizedBrief, BrandBrief, Constraint[] | 轻（补全/归一） | — |
| `p1_bible` | NormalizedBrief, BrandBrief, Profile | Character[], Location[], Prop[], Motif[], ToneSpec | 是 | `after_p1` |
| `p2_arc` | Bible, BrandBrief, Profile | Season, Episode[], BrandMoment 预算分配草案 | 是 | `after_p2` |
| `p3_beatsheet` | Episode(单集), Bible, 预算, 邻集摘要 | Beat[](含 brand_moment 占位 + emotion + SetupPayoff 声明) | 是 | `after_p3` |
| `p4_scene` | Beat[](单集), Bible | Scene[] + Beat→Scene 归属 | 是 | `after_p4` |
| `p5_dialogue` | Scene(单场), Bible, 该场 Beat[], 品牌约束 | Line[] | 是 | `after_p5` |
| `p6_prose` | Episode 的 Scene[]+Line[], Bible, NarrativeVoice | NovelChapter(段落 + anchor_map) | 是 | `after_p6` |
| `p7_render` | 完整 IR | Fountain / novel.docx / script.docx / storyboard.csv | **否** | `final` |

## 2. 逐 Pass 关键约束

### p2_arc
- 必须为每个 `must_cover` 卖点分配 ≥1 个 BrandMoment 槽位，并写明 `modality` 与 `plot_connection` 计划。
- 必须输出 `hook_promise` 与 `cliffhanger`（末集除外）。
- 借鉴：Dramatron 的 log line → plot 层级（BORROW_MAP #1）；DOC 的"创作负担前移"（#3）。

### p3_beatsheet
- **最重要的一趟**。BeatSheet 必须细到"每个 Beat 可被独立判定通过/不通过"（DOC 的 detailed outliner 原则）。
- 单集生成，输入含 `prev_episode_summary` 与 `next_episode_promise`，不含全季全文（可缓存、可局部重编译）。
- 必须声明 `SetupPayoff`（可跨集，跨集则 payoff_beat_id 留 `PENDING:<slug>`，由 p3 的全季后处理解引用）。

### p5_dialogue
- 单场生成。输入必须包含该场的 `goal/conflict/turn` 与在场角色的 `voice_notes/voice_tics`。
- **内置自检子步（可选，默认开）**：生成后按 `spec/rules/L3_canonical/` 中 `form: prompt` 的规则做一次自我修订。
  借鉴 Constitutional AI 的原则驱动自修订（BORROW_MAP #28），但原则来自 A2/A3 而非手写。
- **候选重排（可选）**：`n=3` 候选，用 L0 checker 过滤 + rubric 判官选优。借鉴 Re3 的 rerank（#2）。默认关闭（成本），`--rerank` 开启。

### p6_prose
- **只允许编织叙述层**：环境、动作细节、内心、转场。
- **不允许发明新事件、新角色、新对白语义**。对白允许口语化微调，但 `NOV-002` 会检查相似度 ≥0.7。
- 必须输出完整 `anchor_map`，覆盖率 100%（`NOV-001`）。这是反馈能回流的唯一保障。

### p7_render
- **零 LLM**。纯 Jinja2 + python-docx。
- 必须写入锚点（D29 三重方案）：docx bookmark `NID_<ulid>` + 文末锚点索引表 + 段落顺序稳定。
- 输出 `out/<project>/manifest.json`（Provenance，D20）。

## 3. 局部重编译
依赖与失效闭包定义在 `dep_graph.yaml`。契约：
- 改 `Episode.logline` → 失效该集 p3/p4/p5/p6/p7
- 改单个 `Scene.goal` → 失效该场 p5、该集 p6、p7
- 改 `BrandBrief.placement` → 失效全部 p2 之后（因为预算分配变了）
- 改 `NarrativeVoice` → **只**失效 p6/p7（这是 D27 的收益）
- 人类 `locked: true` 的节点：重编译必须保留原内容与原 ID。