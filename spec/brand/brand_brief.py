"""BrandBrief（D4）：跨项目复用的品牌资产。每个字段都要能编译成 checker 规则（见 mapping.md）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..ir.nodes import NonEmpty, Slug


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Slug
    name: NonEmpty
    canonical_name: NonEmpty = Field(description="唯一正确写法；其他写法一律 block（BM-009）")
    aliases: list[str] = Field(default_factory=list, description="允许出现的别名")
    category: str = ""
    price_cny: float | None = None
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="可引用的产品事实。剧本中出现的任何参数必须来自这里（FCT-001）",
    )


class SellingPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Slug
    claim: NonEmpty
    priority: int = Field(ge=1, le=5, description="1 最高")
    must_cover: bool = Field(default=False, description="true ⇒ 必须被至少一个 BrandMoment 覆盖（BM-006）")
    proof: str = Field(default="", description="可展示的证据；无证据的卖点禁止用 demo 形式")
    forbidden_phrasings: list[str] = Field(default_factory=list)


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Slug
    label: NonEmpty
    age_range: str = ""
    pains: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    language_notes: str = ""


class UsageScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Slug
    description: NonEmpty
    shootable: bool = True


class Legal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    banned_words: list[str] = Field(default_factory=list)
    competitor_names: list[str] = Field(default_factory=list, description="禁止出现（BM-011）")
    claim_whitelist: list[str] = Field(default_factory=list, description="仅这些功效表述可用")
    ip_assignment: str = "交付后著作权归甲方所有"
    legal_refs: list[str] = Field(default_factory=list)


class PlacementBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_moments_per_episode: int = Field(default=2, ge=0)
    min_gap_beats: int = Field(default=2, ge=0)
    max_high_intensity_per_episode: int = Field(default=1, ge=0)
    require_high_plot_connection: int = Field(
        default=1, ge=0, description="全季至少几处 plot_connection==high（BM-004）"
    )
    forbid_in_beat_kinds: list[str] = Field(default_factory=lambda: ["hook"])


class BrandBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    brand_id: Slug
    brand_name: NonEmpty
    version: str = Field(description="语义化版本，进 provenance.brand_ver")
    industry: Slug = Field(description="→ domain pack id，如 beverage / beauty / auto")

    products: list[Product] = Field(min_length=1)
    selling_points: list[SellingPoint] = Field(min_length=1)
    audience: list[Persona] = Field(min_length=1)
    usage_scenes: list[UsageScene] = Field(default_factory=list)

    tone_words: list[str] = Field(min_length=1)
    banned_words: list[str] = Field(default_factory=list)
    must_include_lines: list[str] = Field(
        default_factory=list, description="必须原文出现的台词（BM-007）"
    )
    must_include_visuals: list[str] = Field(default_factory=list)

    placement: PlacementBudget = Field(default_factory=PlacementBudget)
    legal: Legal = Field(default_factory=Legal)

    account_context: str = Field(default="", description="商家账号现状：粉丝画像、已有内容风格")
    business_goal: Literal["awareness", "consideration", "conversion", "retention"] = "consideration"