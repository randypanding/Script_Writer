"""Narrative IR 容器：扁平表 + 邻接（parent_id），计算式嵌套视图供 checker/renderer 使用。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .nodes import ULID, Beat, Episode, Line, Project, Scene, Season
from .overlays import (
    BrandMoment,
    Character,
    Constraint,
    DarkThread,
    Fact,
    Location,
    Motif,
    NarrativeVoice,
    Prop,
    SetupPayoff,
    StateVariable,
    Thread,
    ToneSpec,
)


class Provenance(BaseModel):
    """D20 全链路溯源清单。每个产物必须可二分定位到某次运行。"""

    model_config = ConfigDict(extra="forbid")
    run_id: str
    pass_name: str
    spec_sha: str
    profile_ver: str
    brand_ver: str
    ruleset_ver: str
    promptset_ver: str
    model_id: str
    temperature: float
    seed: int | None
    input_hash: str
    case_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class NovelChapter(BaseModel):
    """Pass6 产物：小说章节。anchor_map 把每个段落映射回 Beat/Line（反馈锚定的命脉）。"""

    model_config = ConfigDict(extra="forbid")
    id: ULID
    episode_id: ULID
    order: int
    title: str = ""
    paragraphs: list[str] = Field(min_length=1)
    anchor_map: list[dict[str, Any]] = Field(
        description="[{paragraph_index, beat_id, line_ids:[...]}]；覆盖率必须 100%（NOV-001）"
    )
    provenance_id: str
    word_chars: int = 0


class NarrativeIR(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.1"] = "1.1"

    @field_validator("schema_version", mode="before")
    @classmethod
    def _migrate_1_0(cls, v: object) -> object:
        """ADR-0012：1.0→1.1 无损迁移。新字段全部可选默认空，
        迁移 = 纯字段默认 + 版本号提升，故 1.0 dict 在校验入口原地升级。"""
        return "1.1" if v == "1.0" else v

    project: Project
    seasons: list[Season] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)

    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)
    brand_moments: list[BrandMoment] = Field(default_factory=list)
    setup_payoffs: list[SetupPayoff] = Field(default_factory=list)
    motifs: list[Motif] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    tone: ToneSpec | None = None
    voice: NarrativeVoice | None = None

    # --- ADR-0012 运行时叙事状态层（IR 1.1，全部默认空表） ---
    facts: list[Fact] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    state_variables: list[StateVariable] = Field(default_factory=list)
    dark_threads: list[DarkThread] = Field(default_factory=list)

    chapters: list[NovelChapter] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    # --- 计算视图（不序列化进 JSON 真相，由 runtime 生成） ---
    def view(
        self, profile: dict[str, Any] | None = None, brand: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """产出嵌套文档，供 JMESPath 规则查询。实现见 src/nsc/runtime/ir_io.py::build_view。

        形如：
        {"project": {...},
         "episodes": [{..., "scenes":[{..., "beats":[{..., "lines":[...],
                       "brand_moment": {...}|null, "linear_index": int}]}]}],
         "characters": [...], "brand_moments":[...], "setup_payoffs":[...],
         "profile": {...}, "brand": {...}}
        """
        from nsc.runtime.ir_io import build_view

        return build_view(self.model_dump(), profile or {}, brand or {})

    def emotion_curve(self, episode_id: ULID) -> list[tuple[int, float, float]]:
        """[(linear_index, valence, arousal)]。曲线是计算量，绝不存储。"""
        from nsc.runtime.ir_io import emotion_curve

        return emotion_curve(self, episode_id)
