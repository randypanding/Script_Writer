"""T-14 规则挖掘（L0→L1）测试。

验收（WORK_ORDERS T-14）：≥30 条观察下产出 ≥3 条候选，每条带 evidence_ids≥3、
counterexamples 非空、conflicts_with 已检查。这里用小规模合成数据验证机制正确性：
- 只聚类 confirmed_by 非空的观察（未确认的不进 L1）
- 同簇 ≥3 且 ≥2 个 case 才产出候选
- taste 维度强制 client scope
- 归纳产物落 L1_candidates/R1-*.yaml 且符合 _schema 关键字段
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import ClassVar

import yaml

from nsc.db import init_schema
from nsc.mining.cluster import Observation, _fallback_labels, cluster_observations
from nsc.mining.induce import load_observations, run_mine
from nsc.runtime.models import LLMResult

# 测试统一用确定性回退聚类（不依赖环境是否装 hdbscan，保证 CI 可复现）
FB = _fallback_labels


def _mk_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    return conn


def _insert_case(conn: sqlite3.Connection, case_id: str, brand: str = "demo_tea") -> None:
    conn.execute(
        "INSERT INTO cases (case_id, brand_id, profile_id, industry, title, source, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (case_id, brand, "p", "tea", case_id, "client", "delivered", "2026-01-01T00:00:00Z"),
    )


def _insert_obs(
    conn: sqlite3.Connection,
    obs_id: str,
    case_id: str,
    dimension: str,
    rationale: str,
    *,
    confirmed: bool = True,
    before: str = "原文",
    after: str = "改后",
) -> None:
    fid = f"fb_{obs_id}"
    conn.execute(
        """INSERT INTO feedback (feedback_id, case_id, target_node_id, anchor_level, anchor_conf,
           dimension, verdict, severity, rationale_nl, original_text, revised_text, edit_type,
           author, confirmed_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            fid,
            case_id,
            None,
            "bookmark",
            1.0,
            dimension,
            "revise",
            3,
            rationale,
            before,
            after,
            "replace",
            "客户",
            "op" if confirmed else "",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO observations_index (obs_id, feedback_id, cluster_id, yaml_path, created_at)"
        " VALUES (?,?,NULL,?,?)",
        (obs_id, fid, f"spec/rules/L0_observations/obs_{obs_id}.yaml", "2026-01-01T00:00:00Z"),
    )
    conn.commit()


def _similarity_embedder(similar_key: str):
    """把含 similar_key 的文本映到同一方向，否则映到各自正交方向（保证前者成簇）。"""

    def embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        ortho = 0
        for t in texts:
            if similar_key in t:
                out.append([1.0, 0.0])
            else:
                ortho += 1
                out.append([0.0, float(ortho)])
        return out

    return embed


class InduceStubRouter:
    """返回合法 RuleInduce 输出的 stub。"""

    tiers: ClassVar[dict] = {}

    def complete(self, tier, messages, *, json_mode=False, seed=None):
        text = json.dumps(
            {
                "statement": "植入卖点应由角色动作与后果承载，不得由角色直接宣读产品参数。",
                "form": "check",
                "scope_json": json.dumps({"kind": "global"}),
                "check_draft_yaml": "select: ...",
                "counterexamples": "品牌 explicitly 要求口播参数的广告片",
                "conflicts_with": "",
            },
            ensure_ascii=False,
        )
        return LLMResult(
            text=text, model_id="stub", tokens_in=1, tokens_out=1, cost_usd=0.0, wall_ms=1
        )


# ---------------------------------------------------------------- cluster.py 纯函数
def test_cluster_requires_min_size_and_cases():
    obs = [
        Observation(f"o{i}", "念参数 台词太假", "placement", "case:0001", "b", "p.yaml")
        for i in range(4)
    ]
    # 4 条同 case → 不满足 ≥2 case
    assert cluster_observations(obs, embedder=_similarity_embedder("念参数"), clusterer=FB) == []
    # 改成 2 个 case → 成簇
    obs[1].case_id = "case:0002"
    obs[2].case_id = "case:0002"
    clusters = cluster_observations(obs, embedder=_similarity_embedder("念参数"), clusterer=FB)
    assert len(clusters) == 1
    assert len(clusters[0].members) == 4


def test_cluster_is_per_dimension():
    # placement 3 条相似 + dialogue 3 条相似 → 两个簇，不混
    obs = [
        Observation("p0", "念参数", "placement", "case:0001", "b", "x"),
        Observation("p1", "念参数", "placement", "case:0002", "b", "x"),
        Observation("p2", "念参数", "placement", "case:0002", "b", "x"),
        Observation("d0", "台词太长", "dialogue", "case:0001", "b", "x"),
        Observation("d1", "台词太长", "dialogue", "case:0002", "b", "x"),
        Observation("d2", "台词太长", "dialogue", "case:0002", "b", "x"),
    ]

    def embed(texts):
        return [[1.0, 0.0] if "念参数" in t else [0.0, 1.0] for t in texts]

    clusters = cluster_observations(obs, embedder=embed, clusterer=FB)
    dims = sorted(c.dimension for c in clusters)
    assert dims == ["dialogue", "placement"]


# ---------------------------------------------------------------- induce.py 端到端
def test_run_mine_end_to_end(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    for c in ("case:0001", "case:0002"):
        _insert_case(conn, c)
    # 4 条已确认 placement 观察（2 case）→ 应成簇
    for i, (cid, _) in enumerate(
        [("case:0001", 0), ("case:0001", 0), ("case:0002", 0), ("case:0002", 0)]
    ):
        _insert_obs(conn, f"01CONF{i:02d}", cid, "placement", "客户删掉参数宣读改成动作")
    # 1 条未确认观察 → 不进聚类
    _insert_obs(
        conn, "01UNCONF", "case:0001", "placement", "客户删掉参数宣读改成动作", confirmed=False
    )
    conn.close()

    obs = load_observations(db)
    assert len(obs) == 4  # 未确认的被挡在门外
    assert all(o.case_id.startswith("case:") for o in obs)

    cands = run_mine(
        db,
        router=InduceStubRouter(),
        rules_root=tmp_path / "rules",
        l1_dir=tmp_path / "rules" / "L1_candidates",
        embedder=_similarity_embedder("删掉参数"),
        clusterer=FB,
    )
    assert len(cands) == 1
    data = yaml.safe_load(cands[0].path.read_text("utf-8"))
    assert data["id"].startswith("R1-")
    assert data["level"] == "L1"
    assert data["dimension"] == "placement"
    assert data["form"] == "check"
    assert len(data["evidence_ids"]) >= 3  # 验收：evidence_ids ≥3
    assert data["extra"]["counterexamples"]  # 验收：counterexamples 非空
    assert "conflicts_with" in data["extra"]  # 验收：conflicts_with 已检查
    assert data["extra"]["n_cases"] >= 2

    # 回填 cluster_id + rules 台账
    conn = sqlite3.connect(db)
    try:
        assigned = conn.execute(
            "SELECT COUNT(*) FROM observations_index WHERE cluster_id IS NOT NULL"
        ).fetchone()[0]
        assert assigned == 4
        rules = conn.execute(
            "SELECT level, form FROM rules WHERE rule_id = ?", (cands[0].rule_id,)
        ).fetchone()
        assert rules == ("L1", "check")
    finally:
        conn.close()


def test_taste_forces_client_scope(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    for c in ("case:0001", "case:0002"):
        _insert_case(conn, c, brand="demo_tea")
    for i in range(3):
        _insert_obs(
            conn,
            f"01TASTE{i}",
            "case:0001" if i < 2 else "case:0002",
            "taste",
            "我们就喜欢这个名字",
        )
    conn.close()

    cands = run_mine(
        db,
        router=InduceStubRouter(),
        rules_root=tmp_path / "rules",
        l1_dir=tmp_path / "rules" / "L1_candidates",
        embedder=_similarity_embedder("喜欢这个名字"),
        clusterer=FB,
    )
    assert len(cands) == 1
    data = yaml.safe_load(cands[0].path.read_text("utf-8"))
    # 硬约束：taste 只能 client scope，即便 LLM 给了 global
    assert data["scope"]["kind"] == "client"
    assert data["scope"]["value"] == "demo_tea"


def test_run_mine_no_confirmed_returns_empty(tmp_path):
    db = tmp_path / "cases.db"
    conn = _mk_db(db)
    _insert_case(conn, "case:0001")
    _insert_obs(conn, "01U", "case:0001", "placement", "未确认", confirmed=False)
    conn.close()
    assert run_mine(db, router=InduceStubRouter(), l1_dir=tmp_path / "l1") == []
