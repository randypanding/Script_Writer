"""L1 规则归纳（L0→L1 的第二步）：把聚类得到的簇经 RuleInduce 归纳成候选规则。

归纳是语义判定，prompt 契约在 spec/passes/signatures.py::RuleInduce（资产），
本模块只做编排：拉观察 → 聚类 → 调 LLM → 校验 → 落 yaml + rules 台账。
落地产物是 L1 candidate（`spec/rules/L1_candidates/R1-*.yaml`），CI 只校验 schema，
不参与任何门禁（spec/rules/PROMOTION.md §目录）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from nsc.mining.cluster import Cluster, Observation, cluster_observations

L1_DIR = Path("spec/rules/L1_candidates")


class InduceError(RuntimeError):
    """RuleInduce 输出不合法。"""


class _Router(Protocol):
    def complete(
        self,
        tier: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        seed: int | None = None,
    ) -> Any: ...


@dataclass(slots=True)
class Candidate:
    rule_id: str
    path: Path
    dimension: str
    cluster_id: str


def load_observations(db_path: str | Path) -> list[Observation]:
    """从 db 拉取「已确认」反馈对应的观察，投影成可聚类的 Observation。

    只取 confirmed_by 非空的 feedback（PROMOTION 的隐含前提：未确认的 LLM 猜测不进聚类）。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """SELECT o.obs_id, o.yaml_path, f.dimension, f.case_id, c.brand_id,
                      f.rationale_nl, f.original_text, f.revised_text
               FROM observations_index o
               JOIN feedback f ON f.feedback_id = o.feedback_id
               JOIN cases c ON c.case_id = f.case_id
               WHERE f.confirmed_by <> '' AND o.cluster_id IS NULL"""
        ).fetchall()
    finally:
        conn.close()
    obs: list[Observation] = []
    for obs_id, yaml_path, dim, case_id, brand_id, rationale, before, after in rows:
        obs.append(
            Observation(
                obs_id=obs_id,
                text=f"{rationale} | {before} → {after}".strip(" |"),
                dimension=dim,
                case_id=case_id,
                brand_id=brand_id,
                yaml_path=yaml_path,
                evidence={"rationale_nl": rationale, "before": before, "after": after},
            )
        )
    return obs


def _next_rule_ids(l1_dir: Path, n: int) -> list[str]:
    top = 0
    if l1_dir.exists():
        for p in l1_dir.glob("R1-*.yaml"):
            try:
                top = max(top, int(p.stem.split("-")[1]))
            except (IndexError, ValueError):
                continue
    return [f"R1-{top + k + 1:04d}" for k in range(n)]


def _existing_rules(rules_root: Path, dimension: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sub in ("L2_validated", "L3_canonical"):
        d = rules_root / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.yaml")):
            data = yaml.safe_load(p.read_text("utf-8")) or {}
            if data.get("dimension") == dimension:
                out.append({"id": data.get("id"), "statement": data.get("statement")})
    return out


def induce_cluster(
    cluster: Cluster,
    observations: list[Observation],
    *,
    router: _Router,
    rules_root: Path = Path("spec/rules"),
) -> dict[str, Any]:
    """对一个簇调 RuleInduce，返回归纳出的规则字段（未落盘）。

    判定知识（怎么归纳、硬约束）在 signatures.RuleInduce 的 docstring（资产）。
    """
    members = [observations[i] for i in cluster.members]
    dim = cluster.dimension
    payload = {
        "observations_json": json.dumps(
            [
                {
                    "case_id": m.case_id,
                    "rationale_nl": m.evidence.get("rationale_nl", ""),
                    "before": m.evidence.get("before", ""),
                    "after": m.evidence.get("after", ""),
                }
                for m in members
            ],
            ensure_ascii=False,
        ),
        "existing_rules_json": json.dumps(_existing_rules(rules_root, dim), ensure_ascii=False),
    }
    from spec.passes.signatures import RuleInduce

    instructions = (RuleInduce.__doc__ or "").strip()
    system = (
        f"{instructions}\n\n只输出一个 JSON 对象，键为："
        "statement, form, scope_json, check_draft_yaml, counterexamples, conflicts_with。"
        "scope_json/check_draft_yaml 若是对象请序列化为 JSON 字符串。"
    )
    res = router.complete(
        "tier_plan",
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        json_mode=True,
    )
    try:
        data = json.loads(res.text)
    except json.JSONDecodeError as e:
        raise InduceError(f"RuleInduce 输出不是合法 JSON：{res.text[:200]!r}") from e

    statement = str(data.get("statement", "")).strip()
    if len(statement) < 10:
        raise InduceError("RuleInduce 的 statement 太短，不可判定（_schema 要求 minLength 10）")
    form = str(data.get("form", "")).strip()
    if form not in ("check", "rubric", "prompt", "profile_default"):
        raise InduceError(f"RuleInduce 的 form={form!r} 不在 (check/rubric/prompt/profile_default)")
    counterexamples = str(data.get("counterexamples", "")).strip()
    if not counterexamples:
        raise InduceError("RuleInduce 必须给出 counterexamples（防过度泛化）")

    scope = _parse_scope(data.get("scope_json"), members)
    # 硬约束：taste 维度只能产出 client scope（PROMOTION §scope 与口味性隔离，CI 也查）
    if dim == "taste":
        scope = {"kind": "client", "value": members[0].brand_id}

    return {
        "statement": statement,
        "form": form,
        "scope": scope,
        "check_draft_yaml": str(data.get("check_draft_yaml", "")).strip(),
        "counterexamples": counterexamples,
        "conflicts_with": str(data.get("conflicts_with", "")).strip(),
    }


def _parse_scope(raw: Any, members: list[Observation]) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict) or "kind" not in raw:
        return {"kind": "client", "value": members[0].brand_id}
    return {"kind": raw["kind"], "value": raw.get("value", "")}


def run_mine(
    db_path: str | Path,
    *,
    router: _Router,
    rules_root: Path = Path("spec/rules"),
    l1_dir: Path = L1_DIR,
    embedder: Any = None,
    clusterer: Any = None,
) -> list[Candidate]:
    """端到端：拉观察 → 聚类 → 逐簇归纳 → 落 L1 candidate + rules 台账 + 回填 cluster_id。"""
    observations = load_observations(db_path)
    clusters = cluster_observations(observations, embedder=embedder, clusterer=clusterer)
    if not clusters:
        return []
    l1_dir.mkdir(parents=True, exist_ok=True)
    ids = _next_rule_ids(l1_dir, len(clusters))
    now = datetime.now(UTC).isoformat()

    conn = sqlite3.connect(str(db_path))
    candidates: list[Candidate] = []
    try:
        for cluster, rule_id in zip(clusters, ids, strict=True):
            members = [observations[i] for i in cluster.members]
            induced = induce_cluster(cluster, observations, router=router, rules_root=rules_root)
            evidence_ids = sorted({m.case_id for m in members} | {m.obs_id for m in members})
            rule = {
                "id": rule_id,
                "level": "L1",
                "statement": induced["statement"],
                "rationale": f"由 {len(members)} 条观察（簇 {cluster.cluster_id}）归纳。",
                "scope": induced["scope"],
                "form": induced["form"],
                "dimension": cluster.dimension,
                "evidence_ids": evidence_ids,
                "hit_count": 0,
                "created_at": now,
                "extra": {
                    "counterexamples": induced["counterexamples"],
                    "conflicts_with": induced["conflicts_with"],
                    "check_draft_yaml": induced["check_draft_yaml"],
                    "cluster_id": cluster.cluster_id,
                    "n_observations": len(members),
                    "n_cases": len({m.case_id for m in members}),
                },
            }
            path = l1_dir / f"{rule_id}.yaml"
            path.write_text(yaml.safe_dump(rule, allow_unicode=True, sort_keys=False), "utf-8")
            conn.execute(
                """INSERT OR REPLACE INTO rules
                   (rule_id, level, statement, scope_kind, scope_value, form, target,
                    dimension, hit_count, effect_size, created_at, last_fired_at, superseded_by)
                   VALUES (?,?,?,?,?,?,?,?,0,NULL,?,NULL,NULL)""",
                (
                    rule_id,
                    "L1",
                    induced["statement"],
                    induced["scope"]["kind"],
                    str(induced["scope"].get("value", "")),
                    induced["form"],
                    "",
                    cluster.dimension,
                    now,
                ),
            )
            for m in members:
                conn.execute(
                    "UPDATE observations_index SET cluster_id = ? WHERE obs_id = ?",
                    (cluster.cluster_id, m.obs_id),
                )
            candidates.append(
                Candidate(
                    rule_id=rule_id,
                    path=path,
                    dimension=cluster.dimension,
                    cluster_id=cluster.cluster_id,
                )
            )
        conn.commit()
    finally:
        conn.close()
    return candidates
