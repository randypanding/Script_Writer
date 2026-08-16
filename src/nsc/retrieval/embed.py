"""检索池的向量侧：文本 → 稠密向量（T-16）。

模型是生成物（config/models.yaml::tiers.tier_embed = BAAI/bge-m3，dim 1024）。
BgeM3Embedder 惰性加载：首次 encode 才初始化模型，避免导入即下载十几 GB。
测试用 StubEmbedder（确定性词袋哈希），避免 CI 依赖 HF 下载。
"""

from __future__ import annotations

import hashlib
from typing import Protocol


class Embedder(Protocol):
    """统一嵌入接口。dim 由实现决定（BGE-M3 稠密 = 1024）。"""

    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class BgeM3Embedder:
    """sentence-transformers 的 BAAI/bge-m3 稠密编码，输出已归一化。"""

    dim = 1024

    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        self._model_name = model_name
        self._model = None

    def encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return [v.tolist() for v in vecs]


class StubEmbedder:
    """测试用确定性嵌入：按词袋哈希到固定维度（可复现、无网络）。"""

    dim = 32

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in str(t).split():
                h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
                v[h % self.dim] += 1.0
            out.append(v)
        return out
