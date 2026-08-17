"""Narrative IR · 覆盖层（旁挂，引用主干 ID）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .nodes import ULID, ExpressionDNA, MentalModel, NonEmpty, Slug


class CharacterRole(StrEnum):
    protagonist = "protagonist"
    antagonist = "antagonist"
    ally = "ally"
    foil = "foil"
    customer_proxy = "customer_proxy"  # 目标人群代理，营销短剧核心角色
    expert = "expert"  # 权威/背书者
    bystander = "bystander"


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ULID
    name: NonEmpty
    role: CharacterRole
    age_range: str = ""
    want: NonEmpty = Field(description="外部目标")
    need: NonEmpty = Field(description="内在缺失")
    flaw: str = ""
    arc: str = Field(default="", description="从 X 到 Y")
    voice_notes: NonEmpty = Field(description="说话方式：语速/句长/句式偏好")
    voice_tics: list[str] = Field(default_factory=list, description="口头禅/标记词（DLG-004）")
    forbidden_words: list[str] = Field(default_factory=list, description="此角色不会说的词")
    persona_ref: str = Field(default="", description="→ brand.audience.personas[*].id")
    # --- ADR-0012 角色心智 OS（全部可选默认空，1.0 IR 无损迁移） ---
    # 注：default_factory 用类型化 list[MentalModel]（pyright strict 要求，裸 list 会解成 list[Unknown]）。
    mental_models: list[MentalModel] = Field(
        default_factory=list[MentalModel], max_length=5, description="心智模型，至多 5 个"
    )
    decision_heuristics: list[str] = Field(
        default_factory=list, max_length=7, description="决策启发式，至多 7 条"
    )
    honest_boundaries: list[str] = Field(
        default_factory=list, description="此角色绝不会做的事（诚实边界）"
    )
    expression_dna: ExpressionDNA | None = None


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ULID
    name: NonEmpty
    interior: bool = True
    description: str = ""
    cost_tier: Literal["free", "cheap", "medium", "expensive", "unavailable"] = "cheap"
    shoot_notes: str = ""


class Prop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ULID
    name: NonEmpty
    is_brand_product: bool = False
    sku_ref: str = Field(default="", description="→ brand.products[*].id")
    cost_tier: Literal["free", "cheap", "medium", "expensive", "unavailable"] = "cheap"


class BrandMomentType(StrEnum):
    scene = "scene"  # 场景背景出现
    usage = "usage"  # 角色使用产品
    dialogue = "dialogue"  # 台词提及
    prop = "prop"  # 作为道具推动情节
    testimonial = "testimonial"  # 角色口碑/见证
    before_after = "before_after"  # 前后对比


class BrandMoment(BaseModel):
    """植入时刻。modality / plot_connection 字段借鉴 Russell(2002) 的
    modality × plot-connection congruence 框架（见 docs/BORROW_MAP.md #15）。"""

    model_config = ConfigDict(extra="forbid")
    id: ULID
    anchor_beat_id: ULID
    type: BrandMomentType
    intensity: int = Field(ge=1, le=5, description="1 极隐性 … 5 硬广（Gupta&Lord prominence）")
    modality: Literal["visual", "verbal", "both"] = "visual"
    plot_connection: Literal["none", "low", "high"] = "low"
    selling_point_id: str = Field(description="→ brand.selling_points[*].id")
    proof_mode: Literal["demo", "reaction", "authority", "contrast", "none"] = "reaction"
    integration_note: NonEmpty = Field(description="这处植入怎么长在剧情里的一句话解释")
    prop_id: ULID | None = None


class SetupPayoff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ULID
    setup_beat_id: ULID
    payoff_beat_id: ULID
    kind: Literal["prop", "line", "promise", "secret", "skill"] = "promise"
    description: NonEmpty


class Motif(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ULID
    name: NonEmpty
    description: str = ""
    occurrence_beat_ids: list[ULID] = Field(default_factory=list)


class Constraint(BaseModel):
    """从 BrandBrief / Profile / Client Pack 编译出的硬约束（D4）。
    `check_rule_id` 指向 spec/checks 中的规则；`params` 注入该规则的上下文。"""

    model_config = ConfigDict(extra="forbid")
    id: ULID
    source: Literal["brand_brief", "profile", "client_pack", "compliance"]
    check_rule_id: str = Field(description="→ spec/checks/**/<id>.yaml::id")
    params: dict[str, object] = Field(default_factory=dict)
    description: NonEmpty
    severity: Literal["block", "warn", "info"] = "block"


class ToneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone_words: list[str] = Field(min_length=1)
    banned_words: list[str] = Field(default_factory=list)
    register: Literal["colloquial", "neutral", "literary"] = "colloquial"
    humor: Literal["none", "light", "heavy"] = "light"
    reference_works: list[str] = Field(default_factory=list)


class NarrativeVoice(BaseModel):
    """小说渲染参数（D27）。不是 IR 主干的一部分。"""

    model_config = ConfigDict(extra="forbid")
    person: Literal["first", "third_limited", "third_omniscient"] = "third_limited"
    tense: Literal["past", "present"] = "past"
    pov_character_id: ULID | None = None
    style: Slug = Field(default="web_novel", description="→ profiles.*.novel.styles")
    paragraph_max_chars: int = Field(default=180, gt=0)
    interiority: Literal["low", "medium", "high"] = "medium"


# ======================================================================
# ADR-0012 · 运行时叙事状态层（IR 1.1）。以下四张表声明式存储，
# 派生量（current/current_stage/is_overdue）由 build_view 确定性计算，
# IR 本体永不被运行时改写（杜绝 FicForge ops 日志与磁盘漂移）。
# ======================================================================


class FactStatus(StrEnum):
    active = "active"  # 当前生效
    unresolved = "unresolved"  # 悬而未决（伏笔/悬念类核心状态）
    resolved = "resolved"  # 已被另一条 Fact 回收
    deprecated = "deprecated"  # 作废（不参与级联判定）


class FactType(StrEnum):
    character_detail = "character_detail"  # 角色细节
    relationship = "relationship"  # 关系
    backstory = "backstory"  # 前史
    plot_event = "plot_event"  # 情节事件
    foreshadowing = "foreshadowing"  # 伏笔（SetupPayoff 的泛化）
    world_rule = "world_rule"  # 世界规则


class SuspenseType(StrEnum):
    foreshadow = "foreshadow"  # 伏笔
    secret = "secret"  # 秘密
    misunderstanding = "misunderstanding"  # 误会


class Fact(BaseModel):
    """叙事事实：长篇一致性的显式长期记忆（FicForge 生命周期规格，ADR-0012）。

    线索（Thread）成员关系的唯一真相源在 Fact 侧（thread_ids），
    Thread 不存 fact_ids，防双向漂移。
    """

    model_config = ConfigDict(extra="forbid")
    id: ULID
    content: NonEmpty
    character_ids: list[ULID] = Field(default_factory=list)
    episode_no: int = Field(default=1, ge=1, description="首次成立的集号")
    status: FactStatus = FactStatus.active
    type: FactType = FactType.plot_event
    resolves: ULID | None = Field(default=None, description="本 fact 回收哪条伏笔（INV-17）")
    caused_by: list[ULID] = Field(default_factory=list, description="成因 Fact（INV-18）")
    known_to: Literal["all", "reader_only"] | list[ULID] | None = Field(
        default=None, description="知识边界：全员可知 / 仅读者可知 / 指定角色列表"
    )
    hidden_from: list[ULID] = Field(default_factory=list, description="对谁保密")
    suspense_type: SuspenseType | None = None
    narrative_weight: Literal["low", "medium", "high"] = "medium"
    thread_ids: list[ULID] = Field(default_factory=list)


class ThreadStatus(StrEnum):
    active = "active"
    resolved = "resolved"
    dormant = "dormant"  # 休眠（暂不推进但未关闭）


class Thread(BaseModel):
    """叙事线索。只存标题/摘要/状态；成员关系见 Fact.thread_ids。"""

    model_config = ConfigDict(extra="forbid")
    id: ULID
    title: NonEmpty
    state: str = ""
    status: ThreadStatus = ThreadStatus.active


class StateVariable(BaseModel):
    """数值/字符串叙事状态（novel-distiller 规格，ADR-0012）。

    当前值 = initial 按 episode_no 升序重放 `Episode.state_changes`（derive_state）。
    """

    model_config = ConfigDict(extra="forbid")
    key: Slug
    name: NonEmpty
    type: Literal["number", "string"] = "number"
    initial: float | str = 0
    description: str = ""


class DarkThread(BaseModel):
    """暗线：分阶段揭示的隐藏叙事线（novel-distiller 规格，ADR-0012）。

    current_stage = 按 episode_no 升序累加 key 匹配的 int delta（derive_stage），
    必须落在 [0, len(stages)-1]（INV-19）。
    """

    model_config = ConfigDict(extra="forbid")
    key: Slug
    name: NonEmpty
    stages: list[NonEmpty] = Field(min_length=2, description="揭示阶段，至少 2 段")
    description: str = ""
