"""Narrative IR · 主干节点（D3）。

主干是层级、有序的：Project → Season → Episode → Scene → Beat → Line。
所有节点携带内容无关的稳定 ULID，`provenance_id` 指向一次编译记录。
剧本/小说文本只是本 IR 的渲染视图（D24）。
"""

# pyright: reportIncompatibleVariableOverride=false
# 原因：子类用 Literal 收窄 kind/parent_id/order 是 Pydantic 的标准惯用法，
# pyright 的"覆写类型不兼容"告警在此是误报，本文件统一豁免。

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ULID = Annotated[str, StringConstraints(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,48}$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class NodeKind(StrEnum):
    project = "project"
    season = "season"
    episode = "episode"
    scene = "scene"
    beat = "beat"
    line = "line"


#: 合法父子关系（INV-02 使用）
HIERARCHY: dict[NodeKind, NodeKind | None] = {
    NodeKind.project: None,
    NodeKind.season: NodeKind.project,
    NodeKind.episode: NodeKind.season,
    NodeKind.scene: NodeKind.episode,
    NodeKind.beat: NodeKind.scene,
    NodeKind.line: NodeKind.beat,
}


class BeatKind(StrEnum):
    """Beat 功能受控词表。营销短剧专用词表，扩展需 ADR。"""

    hook = "hook"  # 开场钩子
    setup = "setup"  # 铺垫/伏笔埋设
    inciting = "inciting"  # 引爆事件
    escalation = "escalation"  # 升级
    complication = "complication"  # 意外阻碍
    reversal = "reversal"  # 反转
    crisis = "crisis"  # 至暗
    climax = "climax"  # 高潮
    brand_moment = "brand_moment"  # 品牌植入（必须关联 BrandMoment）
    payoff = "payoff"  # 伏笔回收
    resolution = "resolution"  # 收束
    cliffhanger = "cliffhanger"  # 集末悬念
    cta = "cta"  # 行动号召（短视频常用）


class LineType(StrEnum):
    dialogue = "dialogue"
    action = "action"
    voiceover = "voiceover"
    caption = "caption"  # 屏幕字幕/花字
    sfx = "sfx"


class Emotion(BaseModel):
    """单 Beat 的情绪坐标。曲线是计算视图，不单独存储（见 container.emotion_curve）。"""

    model_config = ConfigDict(extra="forbid")
    valence: float = Field(ge=-1.0, le=1.0, description="情绪效价：-1 极负，+1 极正")
    arousal: float = Field(ge=0.0, le=1.0, description="唤醒度：0 平静，1 强烈")


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)
    id: ULID
    kind: NodeKind
    parent_id: ULID | None = None
    order: int = Field(ge=0, description="同 parent 下从 0 连续（INV-03）")
    provenance_id: str = Field(description="→ container.provenance[*].run_id（INV-14）")
    locked: bool = Field(default=False, description="人类锁定：局部重编译不得覆盖")


class Project(_Node):
    kind: Literal[NodeKind.project] = NodeKind.project
    parent_id: None = None
    order: Literal[0] = 0
    title: NonEmpty
    logline: NonEmpty = Field(description="一句话核心戏剧冲突（Dramatron 的 log line）")
    profile_id: Slug
    brand_id: Slug
    client_note: str = ""


class Season(_Node):
    kind: Literal[NodeKind.season] = NodeKind.season
    title: str = ""
    arc_summary: NonEmpty
    theme: str = ""


class Episode(_Node):
    kind: Literal[NodeKind.episode] = NodeKind.episode
    no: int = Field(ge=1, description="人类可见集号，从 1 连续（INV-12）")
    title: NonEmpty
    logline: NonEmpty
    duration_target_s: int = Field(gt=0)
    hook_promise: NonEmpty = Field(description="本集开场承诺给观众的问题（用于 STR-011）")
    cliffhanger: str = Field(default="", description="集末悬念；末集可为空")


class Scene(_Node):
    kind: Literal[NodeKind.scene] = NodeKind.scene
    location_id: ULID
    time_of_day: Literal["day", "night", "dawn", "dusk", "unspecified"] = "unspecified"
    interior: bool = True
    present_character_ids: list[ULID] = Field(min_length=1)
    goal: NonEmpty = Field(description="本场谁要什么")
    conflict: NonEmpty = Field(description="什么挡着")
    turn: NonEmpty = Field(description="场内发生的不可逆变化")
    entry: NonEmpty = Field(description="切入点：最晚进入的时刻")
    exit: NonEmpty = Field(description="切出点：最早离开的时刻")
    summary: str = ""


class Beat(_Node):
    kind: Literal[NodeKind.beat] = NodeKind.beat
    beat_kind: BeatKind
    summary: NonEmpty
    function: str = Field(default="", description="这个 Beat 对整体弧线的作用")
    emotion: Emotion
    est_duration_s: float = Field(gt=0)
    brand_moment_id: ULID | None = Field(
        default=None, description="beat_kind==brand_moment 时必填（INV-06）"
    )


class Line(_Node):
    """戏剧真相层（D24）。小说与剧本都从这里派生。"""

    kind: Literal[NodeKind.line] = NodeKind.line
    line_type: LineType
    character_id: ULID | None = Field(default=None, description="dialogue/voiceover 必填")
    text: NonEmpty
    subtext: str = Field(default="", description="潜台词；不进交付物，供演员/判官")
    delivery: str = Field(default="", description="表演提示，如 '压低声音'")
    is_brand_line: bool = Field(default=False, description="必提台词命中标记（BM-007）")
