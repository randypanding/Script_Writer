"""Format Profile 的可执行模式（D18）。新增 Profile 不得改本文件之外的内核代码。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spec.ir.nodes import Slug


class Layers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    season: bool = False
    episode: bool = True
    scene: bool = True
    beat: bool = True
    line: bool = True


class NovelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    default_voice: dict = Field(default_factory=dict, description="→ NarrativeVoice 的默认值")
    styles: list[Slug] = Field(default_factory=lambda: ["web_novel"])
    chars_per_episode: tuple[int, int] = (1200, 2200)


class BeatTemplate(BaseModel):
    """Beat 模板先验。来源标注为 craft（Save the Cat / Story Circle）或 mined（逆向标注统计）。"""

    model_config = ConfigDict(extra="forbid")
    id: Slug
    source: Literal["craft", "mined", "client"] = "mined"
    sequence: list[str] = Field(description="beat_kind 序列，允许 '?' 表示可选")
    note: str = ""


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    id: Slug
    version: str
    display_name: str

    layers: Layers = Field(default_factory=Layers)

    episode_count: tuple[int, int]
    duration_target_s: int
    duration_tolerance: float = Field(default=0.15, ge=0, le=1)
    beats_per_episode: tuple[int, int]
    max_scenes_per_episode: int
    max_characters: int
    max_line_chars: int
    chars_per_second: float = Field(default=4.5, gt=0, description="D26 中文对白语速")

    min_emotion_range: float = Field(default=0.6, ge=0, le=2)
    require_setup_payoff: bool = True
    max_payoff_span_episodes: int = 2
    min_voice_tic_ratio: float = 0.15
    location_cost_budget: float = 3.0

    beat_templates: list[BeatTemplate] = Field(default_factory=list)
    novel: NovelSettings = Field(default_factory=NovelSettings)

    render_targets: list[Slug] = Field(default_factory=lambda: ["novel_docx", "script_fountain"])
    enabled_check_domains: list[str] = Field(
        default_factory=lambda: [
            "structure",
            "brand",
            "dialogue",
            "novel",
            "compliance",
            "producibility",
            "fact",
        ]
    )
    model_tiers: dict[str, str] = Field(
        default_factory=dict, description="pass_name -> tier（→ config/models.yaml）"
    )
