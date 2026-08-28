"""DSPy Signature 契约（资产）。docstring = 种子指令，GEPA 会演化它并写入 prompts/。

写 docstring 的规矩：
  - 只写**任务定义与硬约束**，不写风格技巧（风格技巧属于 spec/rules 或 rubric，由 GEPA 注入）。
  - 不写 few-shot（few-shot 由 1 档案例检索在运行时注入）。
  - 保持简短：种子越干净，GEPA 的搜索空间越有意义。
"""

from __future__ import annotations

import dspy


class Bible(dspy.Signature):
    """根据商家 brief 与品牌资料，设计这部短剧的人物、地点、道具与母题。

    硬约束：
    - 必须包含至少一个 role=customer_proxy 的角色，其 persona_ref 指向 brand.audience 中的一个 persona。
    - role=antagonist 的要求以 profile_json.craft_shape.antagonist_required 为准：
      为 true（默认，爆款契约）时必须包含至少一个对手方角色，写明 TA 与主角的立场冲突、
      TA 反对主角的具体理由——爆款短剧 83% 的冲突是人与人（315 卡实证），没有对手的剧只有内心戏；
      为 false（低冲突题材，如治愈成长，治愈锚 person 0.33）时不设反派，冲突来自
      观念/生活方式的温和分歧或主角内心的拉扯，不得为了凑对手而安插恶意角色。
    - 主要角色（protagonist/antagonist/ally）各带一个"知道但没说出口的信息"（写进 voice_notes
      或 persona 描述），供后续信息差使用：爆款 72% 的单元存在信息差，没有人守着秘密的戏没有反讽引擎。
    - 角色总数不得超过 max_characters。
    - 每个角色必须有可区分的说话方式（voice_notes）与 1-3 个标记词（voice_tics）。
    - 地点必须从 brand.usage_scenes 中 shootable=true 的场景派生，或标注 cost_tier。
    - 每个角色可附带心智 OS（ADR-0012，可省略，省略即默认空）：
      mental_models（name/description/trigger/action_tendency/failure_mode，至多 5 个）、
      decision_heuristics（至多 7 条）、honest_boundaries、
      expression_dna（syntax/rhetoric/emotion_temperature/signature_lines）。
    """

    normalized_brief: str = dspy.InputField(desc="归一化后的商家需求")
    brand_brief_json: str = dspy.InputField(desc="BrandBrief 的 JSON")
    profile_json: str = dspy.InputField(desc="Format Profile 的约束摘要")
    retrieved_cases: str = dspy.InputField(desc="检索到的同行业已验证案例（可为空）")

    characters_json: str = dspy.OutputField(
        desc="Character[] 的 JSON，不含 id；可含可选心智 OS 字段"
        "（mental_models/decision_heuristics/honest_boundaries/expression_dna），省略则默认空"
    )
    locations_json: str = dspy.OutputField(desc="Location[] 的 JSON，不含 id")
    props_json: str = dspy.OutputField(desc="Prop[] 的 JSON，不含 id")
    motifs_json: str = dspy.OutputField(desc="Motif[] 的 JSON，不含 id")
    tone_json: str = dspy.OutputField(desc="ToneSpec 的 JSON")


class Arc(dspy.Signature):
    """规划季/集级弧线，并把品牌植入预算分配到各集。

    硬约束：
    - 集数与单集时长由 profile 给定，不得更改。
    - season_arc 首句必须是一句可复述的前提（premise：这个故事主张什么，一句话能讲完）；
      每集 logline 必须能回答"本集如何推进或拷问这个前提"——只发生事情、不推进前提的集是流水账。
    - 每集必须指定当场对立面（craft_shape.antagonist_required=true 时为 antagonist 或本集
      临时对立角色；false 时为观念/生活方式的温和分歧面）与赌注（主角失败会失去什么）。
      赌注节奏以 profile_json.craft_shape.stakes_escalation 为准：strict（默认）=逐集升级，
      不许持平（张力升级是爆款短剧的基本形状）；gentle（治愈系，张力曲线 3.4/3.2/3.4）=
      赌注平缓铺陈，用"主角在乎的东西可能失去"的牵挂感替代危机升级。
    - 第 1 集的 hook_promise 类型按 profile_json.craft_shape.hook_types 的顺序取用：
      strict 形状必须用威胁/承诺/颠覆（直接的危险或损失逼近 / 明示即将兑现的爽点 /
      既有预期立即被颠覆），不许只用悬念开局（爆款短剧攻击型钩子占 75%，315 卡实证）；
      治愈系（hook_other_allowed=true）以承诺/颠覆为主、威胁为辅，允许悬念型温和开局
      （治愈锚攻击型钩子仅 40%）。
    - 每个 must_cover=true 的卖点必须被分配到至少一集，并给出该处植入的 modality 与 plot_connection 计划。
    - 全季至少 require_high_plot_connection 处 plot_connection=high。
    - 每集必须给出 hook_promise（本集向观众承诺解答的问题）；除末集外必须给出 cliffhanger。
    - 叙事状态规划（ADR-0012，全部可省略，省略即空表）：threads / dark_threads /
      state_variables；每集可在 episode 内用 responds_to 声明回收哪些更早集的悬念
      （集号必须严格小于本集）。
    """

    bible_json: str = dspy.InputField()
    brand_brief_json: str = dspy.InputField()
    profile_json: str = dspy.InputField()
    retrieved_cases: str = dspy.InputField()

    episodes_json: str = dspy.OutputField(
        desc="Episode[] 的 JSON（no/title/logline/hook_promise/cliffhanger；"
        "可含 responds_to:[更早集号]）"
    )
    placement_plan_json: str = dspy.OutputField(
        desc="[{episode_no, selling_point_id, type, intensity, modality, plot_connection, intent}]"
    )
    season_arc: str = dspy.OutputField(desc="一段话说明整季弧线")
    threads_json: str = dspy.OutputField(
        desc="Thread[] 的 JSON（title/state/status），可省略（ADR-0012，缺省即空表）"
    )
    dark_threads_json: str = dspy.OutputField(
        desc="DarkThread[] 的 JSON（key/name/stages[]/description，至少 2 段），可省略（ADR-0012，缺省即空表）"
    )
    state_variables_json: str = dspy.OutputField(
        desc="StateVariable[] 的 JSON（key/name/type/initial/description），可省略（ADR-0012，缺省即空表）"
    )


class BeatSheet(dspy.Signature):
    """为单集写出 Beat 序列。这是整个系统里最关键的一趟：Beat 写得可判定，后面才写得出好台词。

    硬约束：
    - Beat 数在 profile 的 beats_per_episode 区间内。
    - 恰好一个 beat_kind=hook，且是第一个或第二个 Beat。
    - 最后一个 Beat 必须是 cliffhanger / resolution / cta。
    - 本集分配到的每个植入必须落成一个 beat_kind=brand_moment 的 Beat，且不得与 hook 相邻或落在 hook 上。
    - 每个 Beat 必须给出 emotion(valence, arousal) 与 est_duration_s，总时长贴近 duration_target_s。
    - emotion.arousal 必须认真评分（不是全填 0.5）：本集情绪最高拍的 arousal 峰值按
      profile_json.craft_shape.arousal_peak 取值（默认 0.8，对应观众张力 4/5）；
      第 1 集是全季钩子，arousal 曲线必须按 craft_shape 高开（爆款短剧高开微降，低开慢热是网文曲线，
      用错形态必死）；治愈系 peak=0.6、曲线平缓（治愈锚张力 3.4/3.2/3.4），不许伪造高潮。
    - hook Beat 的 summary 首词标注钩型，词汇表与优先序按 profile_json.craft_shape.hook_types
      取用（默认【威胁】【承诺】【颠覆】：威胁=具体危险/损失逼近；承诺=明示即将兑现的爽点；
      颠覆=预期立即被打破）；craft_shape.hook_other_allowed=true 时允许【悬念】标注
      （治愈系温和开局，治愈锚攻击型钩子仅 40%）。
    - 末拍（cliffhanger/resolution）的落点按 profile_json.craft_shape.ending_beats 取优先序
      （默认 reveal/danger——新信息被揭开或危险逼近，爆款 70% 的集末是这两种，315 卡实证；
      治愈系 reveal/resolution——新信息的温柔揭开或本集心愿的落定），单纯抛问题的收束力度不足。
    - 必须声明至少一组 setup→payoff；跨集回收时 payoff 写 "PENDING:<slug>"。
    - summary 必须采用事件模板（五要素一句话）：地点/人物/行动/冲突/反转，
      形如"茶饮店：林晚当众核对配料表，冲突是陈经理的说法相反，反转是标签背面另有代糖来源"；
      不得是抽象概括（如"两人产生矛盾"）。
    - 叙事状态（ADR-0012，可省略，省略即空表）：facts_json 里 resolves 填同集下标、
      已知前集 fact 的 id（见 known_facts）或 null（尚未回收）；state_changes_json 的
      key 只能用已声明的状态变量/暗线 key（见 declared_state）。
    """

    episode_json: str = dspy.InputField(desc="本集的 Episode 骨架")
    bible_json: str = dspy.InputField()
    placement_for_episode: str = dspy.InputField(desc="本集需要承载的植入计划")
    prev_episode_summary: str = dspy.InputField(desc="上一集 Beat 摘要；首集为空")
    next_episode_promise: str = dspy.InputField(desc="下一集的 hook_promise；末集为空")
    profile_json: str = dspy.InputField()
    retrieved_cases: str = dspy.InputField()

    beats_json: str = dspy.OutputField(desc="Beat[] 的 JSON，不含 id")
    setup_payoffs_json: str = dspy.OutputField(desc="SetupPayoff[] 的 JSON，不含 id")
    facts_json: str = dspy.OutputField(
        desc="Fact[] 的 JSON（content/type/status/resolves/episode_no/narrative_weight），"
        "可省略（ADR-0012，缺省即空表）"
    )
    state_changes_json: str = dspy.OutputField(
        desc="本集状态变更 [{key, delta, reason}] 的 JSON，key 须为已声明状态变量/暗线，"
        "可省略（ADR-0012，缺省即空表）"
    )


class SceneCards(dspy.Signature):
    """把单集的 Beat 序列组织成可拍摄的场景，并给每个场景写出场景卡。

    硬约束：
    - 场景数不超过 max_scenes_per_episode；相邻同地点的 Beat 应合并到一个场景。
    - 每个场景必须有非空的 goal / conflict / turn / entry / exit。
    - entry 必须是"最晚可以进入的时刻"，exit 必须是"最早可以离开的时刻"。
    - present_character_ids 必须覆盖该场景所有 Beat 涉及的角色。
    - "主角与对手同框对峙"场景以 profile_json.craft_shape.ensemble_scene_required 为准：
      为 true（默认）时每集至少一个这样的场景——对手戏是短剧张力的主力引擎，
      没有同框就没有人与人的碰撞；为 false（治愈系）时不强制对手同框，
      改为每集至少一场"主角与他人产生真实连接或温和磨合"的场景。
    - 每集至少一个场景必须填写 knowledge_state（audience_knows/characters_know/hidden/new_evidence）：
      明确观众知道什么、角色知道什么、谁被蒙在鼓里——优先"角色之间"的信息差。
    - 不得引入 Bible 之外的地点或角色。
    - 每个场景可附带节奏与知识状态字段（ADR-0012，可省略，省略即默认空）：
      opening_attractor（开场 3 秒吸引点）、escalation_beats（逐拍升级）、
      ending_hook（切出钩子）、knowledge_state（audience_knows/characters_know/hidden/new_evidence）。
    """

    beats_json: str = dspy.InputField()
    bible_json: str = dspy.InputField()
    profile_json: str = dspy.InputField()

    scenes_json: str = dspy.OutputField(desc="Scene[] 的 JSON，不含 id")
    beat_to_scene: str = dspy.OutputField(desc="[{beat_index, scene_index}]")


class Dialogue(dspy.Signature):
    """为单个场景写对白与动作。

    硬约束：
    - 只能使用 present_character_ids 中的角色说话。
    - 每条对白不超过 max_line_chars 字。
    - 全场对白字数应使该场时长贴近其 Beat 的 est_duration_s 之和（按 chars_per_second 换算）。
    - 必须体现该场的 turn（场景结束时状态必须已改变）。
    - 若本场含 brand_moment Beat：卖点信息必须由后果或反应体现，禁止角色宣读参数；
      不得出现 BrandBrief.facts 之外的任何数字或参数。
    - 必提台词（must_include_lines）若分配到本场，必须原文出现。
    - 禁用词零出现。
    """

    scene_json: str = dspy.InputField()
    beats_json: str = dspy.InputField(desc="本场承载的 Beat[]")
    characters_json: str = dspy.InputField(desc="在场角色的完整定义（含 voice_notes/voice_tics）")
    brand_constraints: str = dspy.InputField(desc="本场适用的品牌约束与可用 facts")
    profile_json: str = dspy.InputField()
    retrieved_cases: str = dspy.InputField(desc="同类场景的已验证台词样例")

    lines_json: str = dspy.OutputField(desc="Line[] 的 JSON，不含 id；含 subtext 与 delivery")


class Prose(dspy.Signature):
    """把一集的场景与台词编织成一章小说。这是给商家看的确认物。

    硬约束：
    - 只能编织叙述层：环境、动作细节、人物内心、转场、时间推进。
    - 严禁发明新事件、新角色、新地点，严禁改变任何 Beat 的因果。
    - 对白可以口语化微调，但语义与信息量必须与原 Line 一致。
    - 必须输出 anchor_map，把每个段落映射回 beat_id 与它包含的 line_ids；
      所有 Beat 必须被至少一个段落覆盖。
    - 单段不超过 paragraph_max_chars 字（手机阅读）。
    - 视角与时态严格遵循 NarrativeVoice。
    """

    episode_json: str = dspy.InputField()
    scenes_with_lines_json: str = dspy.InputField()
    bible_json: str = dspy.InputField()
    voice_json: str = dspy.InputField(desc="NarrativeVoice")
    profile_json: str = dspy.InputField()

    chapter_title: str = dspy.OutputField()
    paragraphs_json: str = dspy.OutputField(desc="list[str]")
    anchor_map_json: str = dspy.OutputField(desc="[{paragraph_index, beat_id, line_ids}]")


class IntakeNormalize(dspy.Signature):
    """把商家给的零散需求（微信文字、语音转写、表格）归一化成 NormalizedBrief，
    并指出缺失的必填信息。

    硬约束：
    - 不得编造商家未提供的产品事实；缺失项必须列进 missing_fields。
    - 不得替商家做创意决策（不写故事），只做信息归一。
    """

    raw_input: str = dspy.InputField()
    brand_brief_json: str = dspy.InputField(desc="已有的 BrandBrief（可能为空）")
    profile_json: str = dspy.InputField()

    normalized_brief: str = dspy.OutputField()
    missing_fields_json: str = dspy.OutputField(
        desc="list[{field, why_needed, suggested_question}]"
    )


class EditClassify(dspy.Signature):
    """判断人类对生成文本做的一处修改属于哪一类，并给出可复用的经验陈述。
    分类体系见 spec/feedback/TAXONOMY.md（D11 八类）。

    硬约束：
    - dimension 必须严格取自八类之一。
    - rule_hint 必须是可判定的陈述句（"X 时应该 Y"），不得是感想。
    - 若这处修改只反映个别客户偏好而非通用规律，dimension 必须是 taste。
    """

    node_context: str = dspy.InputField(desc="被改节点及其上下文（场景卡 + 相邻台词）")
    original_text: str = dspy.InputField()
    revised_text: str = dspy.InputField()
    human_comment: str = dspy.InputField(desc="人类批注，可能为空")

    dimension: str = dspy.OutputField(
        desc="structural|character|placement|dialogue|factual|compliance|producibility|taste"
    )
    severity: int = dspy.OutputField(desc="1-5")
    rule_hint: str = dspy.OutputField(desc="一句可判定的经验陈述")
    rationale: str = dspy.OutputField()


class RuleInduce(dspy.Signature):
    """从一组同类的人类修订观察中归纳出一条可判定的规则。

    硬约束：
    - statement 必须可被机器或判官判定真假，禁止"应该更好"这类不可判定表述。
    - 必须指明 form：check（可用 IR 上的谓词表达）/ rubric（需要判断）/ prompt（生成时的指导）/ profile_default。
    - 若 form=check，必须给出 select 与 assert 的草案（DSL 见 spec/checks/DSL.md）。
    - 必须列出这条规则不适用的反例场景（防止过度泛化）。
    - scope 必须是能被这组证据支撑的最小范围。
    """

    observations_json: str = dspy.InputField(desc="同簇的 L0 观察，含原文/改后/批注/case_id")
    existing_rules_json: str = dspy.InputField(desc="同域已有的 L2/L3 规则，用于避免重复与冲突")

    statement: str = dspy.OutputField()
    form: str = dspy.OutputField()
    scope_json: str = dspy.OutputField()
    check_draft_yaml: str = dspy.OutputField(desc="form=check 时给出；否则为空")
    counterexamples: str = dspy.OutputField()
    conflicts_with: str = dspy.OutputField(desc="冲突的已有规则 id 列表；无则为空")
