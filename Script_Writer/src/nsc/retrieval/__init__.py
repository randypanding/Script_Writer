"""1 档案例检索（T-16）：检索池 + 向量检索 + 注入 Pass 的 few-shot 服务。

pipeline 通过 `RetrievalService.fetch()` 把命中案例格式化成 Pass 的
`retrieved_cases` 输入。`--no-retrieval`（enabled=False）即 A/B 的对照组。
"""

from __future__ import annotations

from pathlib import Path

from . import builder, embed, pool
from .embed import BgeM3Embedder, Embedder, StubEmbedder
from .pool import RetrievalItem, format_examples, search, upsert_items

__all__ = [
    "BgeM3Embedder",
    "Embedder",
    "RetrievalItem",
    "RetrievalService",
    "StubEmbedder",
    "builder",
    "embed",
    "format_examples",
    "pool",
    "search",
    "upsert_items",
]

#: Pass → unit_kind（检索注入的口径）。
PASS_UNIT_KIND = {
    "p1_bible": "chapter",
    "p2_arc": "scene_card",
    "p3_beatsheet": "beat_sequence",
    "p5_dialogue": "dialogue_block",
}


class RetrievalService:
    """pipeline 的检索入口。查询为空 / 池不存在 / 被禁用时返回空串（幂等降级）。"""

    def __init__(
        self,
        db_path: str | Path = "cases/cases.db",
        *,
        embedder: Embedder | None = None,
        k: int = 3,
        enabled: bool = True,
        prefer_vec: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.embedder = embedder
        self.k = k
        self.enabled = enabled
        self.prefer_vec = prefer_vec

    def fetch(
        self,
        query: str,
        *,
        unit_kind: str,
        profile_id: str = "",
        industry: str = "",
        brand_id: str = "",
    ) -> str:
        """按 unit_kind/industry/profile/quality 检索并格式化为 retrieved_cases 文本。"""
        if not self.enabled or not query or not self.db_path.exists():
            return ""
        conn = pool.connect(self.db_path)
        try:
            hits = search(
                conn,
                query,
                self.embedder,
                k=self.k,
                unit_kind=unit_kind,
                industry=industry or None,
                profile_id=profile_id or None,
                prefer_vec=self.prefer_vec,
            )
        finally:
            conn.close()
        return format_examples(hits)
