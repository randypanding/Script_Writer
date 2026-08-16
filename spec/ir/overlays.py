"""Narrative IR · 覆盖层（旁挂，引用主干 ID）。"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .nodes import ULID, NonEmpty, Slug


class CharacterRole(StrEnum):
    protagonist = "protagonist"
    antagonist = "antagonist"
    ally = "ally"
    foil = "foil"
    customer_proxy = "customer_proxy"   # 目标人群代理，营销短剧核心角色
    expert = "expert"                   # 权威/背书者
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
    scene = "scene"            # 场景背景出现
    usage = "usage"            # 角色使用产品
    dialogue = "dialogue"      # 台词提及
    prop = "prop"              # 作为道具推动情节
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