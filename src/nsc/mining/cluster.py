"""L0 观察聚类（L0→L1 的第一步）。

晋升门槛（spec/rules/PROMOTION.md）：同簇观察 ≥3 条且来自 ≥2 个不同 case。
聚类只用 confirmed_by 非空的反馈对应的观察（T-11 已把未确认条目挡在门外）。

嵌入后端可注入（默认 char-ngram TF-IDF，零外部模型依赖，CI 可跑）；
生产可换成 BGE-M3（docs/BORROW_MAP.md #20）。HDBSCAN 懒加载，缺失时回退到
基于余弦相似度阈值的连通分量聚类——两者都是确定性、无 LLM。
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: 晋升门槛（spec/rules/PROMOTION.md §晋升门槛，勿在此硬编码业务规则之外的魔法数）
MIN_CLUSTER_SIZE = 3
MIN_DISTINCT_CASES = 2
#: 纯 Python 回退聚类的余弦相似度阈值（HDBSCAN 缺失时）
_FALLBACK_SIM_THRESHOLD = 0.45

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(slots=True)
class Observation:
    """一条参与聚类的观察（从 L0 yaml + feedback 投影出来）。"""

    obs_id: str
    text: str  # 聚类用文本：rationale_nl + before→after
    dimension: str
    case_id: str
    brand_id: str
    yaml_path: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Cluster:
    """一个候选簇。members 为 Observation 下标。"""

    cluster_id: str
    members: list[int]
    dimension: str

    def case_ids(self, obs: list[Observation]) -> set[str]:
        return {obs[i].case_id for i in self.members}


def _char_ngrams(text: str, n: int = 2) -> Counter[str]:
    t = " ".join(text.split())
    if len(t) <= n:
        return Counter({t: 1})
    return Counter(t[i : i + n] for i in range(len(t) - n + 1))


def tfidf_embed(texts: list[str]) -> list[list[float]]:
    """确定性 char-bigram TF-IDF。默认嵌入后端（无外部依赖，CI 可跑）。"""
    docs = [_char_ngrams(t) for t in texts]
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.keys())
    n_docs = max(len(texts), 1)
    vocab = sorted(df)
    idf = {t: math.log((1 + n_docs) / (1 + df[t])) + 1.0 for t in vocab}
    vectors: list[list[float]] = []
    for d in docs:
        total = sum(d.values()) or 1
        vec = [(d.get(t, 0) / total) * idf[t] for t in vocab]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        vectors.append([x / norm for x in vec])
    return vectors


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=True))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(x * x for x in b)) or 1.0
    return num / (da * db)


def _fallback_labels(vectors: list[list[float]]) -> list[int]:
    """确定性回退（HDBSCAN 缺失时）：贪心按质心余弦相似度归组。

    处理顺序按「当前质心」对齐：以未分组点 i 为种子，吸收所有与 i 质心
    相似度 ≥ 阈值的点（每吸收一个就更新质心），保证小样本下最近邻优先、
    结果可复现。不足 min_cluster_size 的组判为噪声（-1）。
    """

    def centroid(idxs: list[int]) -> list[float]:
        d = len(vectors[0])
        return [sum(vectors[i][k] for i in idxs) / len(idxs) for k in range(d)]

    n = len(vectors)
    assigned = [False] * n
    groups: list[list[int]] = []
    for i in range(n):
        if assigned[i]:
            continue
        seed = [i]
        assigned[i] = True
        c = centroid(seed)
        changed = True
        while changed:
            changed = False
            for j in range(n):
                if not assigned[j] and _cosine(c, vectors[j]) >= _FALLBACK_SIM_THRESHOLD:
                    seed.append(j)
                    assigned[j] = True
                    c = centroid(seed)
                    changed = True
        groups.append(seed)
    labels = [-1] * n
    cid = 0
    for members in groups:
        if len(members) >= MIN_CLUSTER_SIZE:
            for m in members:
                labels[m] = cid
            cid += 1
    return labels


def _hdbscan_labels(vectors: list[list[float]]) -> list[int]:
    try:
        import hdbscan  # type: ignore[import-not-found]
    except Exception:
        return _fallback_labels(vectors)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        min_samples=1,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    return [int(x) for x in clusterer.fit_predict(vectors)]


def cluster_observations(
    observations: list[Observation],
    *,
    embedder: Embedder | None = None,
    clusterer: Callable[[list[list[float]]], list[int]] | None = None,
) -> list[Cluster]:
    """把 L0 观察按维度分组后在组内聚类，返回满足晋升门槛的候选簇。

    - 维度分组先于聚类：跨维度的相似是噪声（placement 的修改不该和 dialogue 同簇）。
    - 只产出满足「同簇 ≥3 且 ≥2 个 case」的簇；其余作为噪声丢弃。
    - taste 维度永远成簇但标 client scope（由 induce 决定），聚类不拦。
    """
    embed = embedder or tfidf_embed
    labeler = clusterer or _hdbscan_labels
    out: list[Cluster] = []
    by_dim: dict[str, list[int]] = {}
    for i, o in enumerate(observations):
        by_dim.setdefault(o.dimension, []).append(i)

    for dim, idxs in sorted(by_dim.items()):
        if len(idxs) < MIN_CLUSTER_SIZE:
            continue
        vectors = embed([observations[i].text for i in idxs])
        labels = labeler(vectors)
        groups: dict[int, list[int]] = {}
        for local_i, lab in enumerate(labels):
            if lab < 0:
                continue
            groups.setdefault(lab, []).append(idxs[local_i])
        for lab in sorted(groups):
            members = groups[lab]
            cases = {observations[m].case_id for m in members}
            if len(members) >= MIN_CLUSTER_SIZE and len(cases) >= MIN_DISTINCT_CASES:
                out.append(Cluster(cluster_id=f"{dim}-c{lab}", members=members, dimension=dim))
    return out
