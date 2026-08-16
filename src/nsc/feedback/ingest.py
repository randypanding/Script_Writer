"""T-11 反馈摄入流水线：EditRecord → 结构化资产。

产出（D9/D10/D11，SOP_FEEDBACK_INGEST §2）：
  - feedback 表（confirmed_by 一律留空：LLM 猜测未经人工确认，不进 L1 聚类）
  - revision_pairs / preference_pairs
  - spec/rules/L0_observations/obs_*.yaml + observations_index
  - Langfuse annotation queue（离线 jsonl 兜底 + Langfuse best-effort）
  - out/ingest/unaligned.md（anchor_level=failed 条目）

锚点恢复顺序（D29）：L1 书签（extract_paragraph_states 直接给出 node_id）
→ L3 模糊对齐（无书签段落对 delivered 做单调 DP）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from nsc.db.feedback_store import FeedbackStore
from nsc.feedback.align import EditRecord, recover_anchors
from nsc.feedback.classify import EditClassify
from nsc.feedback.docx_revisions import ParaState, extract_paragraph_states
from nsc.render import load_delivered_paragraphs
from nsc.render.anchors import Paragraph
from nsc.runtime.provenance import RunRecord, RunsStore

DEFAULT_OBS_DIR = Path("spec/rules/L0_observations")
# 叙事功能判据在 rubric（资产）；这里只做结构判断：删除段带 node_id 且紧随其后的新段无 node_id
RewriteJudge = Callable[[list[dict[str, str]]], list[bool]]


@dataclass(slots=True)
class IngestReport:
    case_id: str
    feedback_ids: list[str]
    records: list[EditRecord]
    unaligned: list[EditRecord]
    run_id: str
    queue_path: Path | None
    dry_run: bool = False


# ---------------------------------------------------------------- 重写归并（T-11 语义分支）
def find_rewrite_candidates(records: list[EditRecord]) -> list[tuple[int, int]]:
    """确定层停住的边缘点：相邻的 delete(带 node_id) + insert(无 node_id) 对。

    只收 fuzzy 路径的对（DP 因相似度 < _MIN_MATCH 无法配成 replace 的"完全重写"段）。
    bookmark 路径的 delete 是客户显式删除的锚定段落，把别的新段并到它的 node_id
    上会伪造节点历史，不在此归并。
    """
    pairs: list[tuple[int, int]] = []
    for i in range(len(records) - 1):
        a, b = records[i], records[i + 1]
        if a.edit_type == "delete" and b.edit_type == "insert":
            d, ins = i, i + 1
        elif a.edit_type == "insert" and b.edit_type == "delete":
            d, ins = i + 1, i
        else:
            continue
        if (
            a.anchor_level == b.anchor_level == "fuzzy"
            and records[d].node_id
            and not records[ins].node_id
        ):
            pairs.append((d, ins))
    return pairs


def resolve_rewrites(records: list[EditRecord], judge: RewriteJudge) -> list[EditRecord]:
    """用语义裁决合并"完全重写"段：同一节点 → replace（保留 node_id）；否则维持 delete+insert。

    judge 返回 None 元素表示"判不了"→ 保守维持 delete+insert（宁可漏并，不可错并）。
    """
    candidates = find_rewrite_candidates(records)
    if not candidates:
        return records
    verdicts = judge(
        [{"before": records[d].before, "after": records[i].after} for d, i in candidates]
    )
    dropped: set[int] = set()
    for (d, i), same_node in zip(candidates, verdicts, strict=True):
        if not same_node:
            continue
        delete_rec, insert_rec = records[d], records[i]
        records[d] = EditRecord(
            node_id=delete_rec.node_id,
            anchor_level=delete_rec.anchor_level,
            anchor_confidence=fuzz.ratio(delete_rec.before, insert_rec.after) / 100.0,
            edit_type="replace",
            before=delete_rec.before,
            after=insert_rec.after,
            human_comment=insert_rec.human_comment or delete_rec.human_comment,
            author=insert_rec.author or delete_rec.author,
            ts=insert_rec.ts or delete_rec.ts,
        )
        dropped.add(i)
    return [r for idx, r in enumerate(records) if idx not in dropped]


# ---------------------------------------------------------------- 段落状态 → EditRecord
def _state_meta(s: ParaState) -> tuple[str, str, str]:
    """(human_comment, author, ts)：批注文本与首个修订的作者/时间戳。"""
    comment = "；".join(c.after for c in s.comments if c.after)
    author = ""
    ts = ""
    for op in s.ops + s.comments:
        author = author or op.author
        ts = ts or op.ts
    return comment, author, ts


def _records_from_states(
    states: list[ParaState], delivered: list[Paragraph] | None
) -> list[EditRecord]:
    """L1 书签优先；无书签段落交给 L3 模糊对齐（需要 delivered）。"""
    positioned: list[tuple[float, EditRecord]] = []
    unanchored: list[tuple[int, ParaState]] = []
    covered: set[str] = set()

    for pos, s in enumerate(states):
        comment, author, ts = _state_meta(s)
        if not s.node_id:
            unanchored.append((pos, s))
            continue
        covered.add(s.node_id)
        if not s.after.strip() and s.before.strip():
            rec = EditRecord(s.node_id, "bookmark", 1.0, "delete", s.before, "")
        elif s.before != s.after:
            rec = EditRecord(s.node_id, "bookmark", 1.0, "replace", s.before, s.after)
        elif comment:
            rec = EditRecord(s.node_id, "bookmark", 1.0, "comment", s.after, s.after)
        else:
            continue
        rec.human_comment, rec.author, rec.ts = comment, author, ts
        positioned.append((float(pos), rec))

    if delivered is not None and unanchored:
        delivered_rest = [p for p in delivered if p.node_id not in covered]
        fuzzy = recover_anchors([s.after for _, s in unanchored], delivered_rest)
        r_pos = 0
        for rec in fuzzy:
            if rec.edit_type in ("replace", "insert"):
                pos, s = unanchored[r_pos]
                r_pos += 1
                comment, author, ts = _state_meta(s)
                rec.human_comment = rec.human_comment or comment
                rec.author = rec.author or author
                rec.ts = rec.ts or ts
                positioned.append((float(pos), rec))
            else:  # delete：定位到下一个回收段之前
                next_pos = unanchored[min(r_pos, len(unanchored) - 1)][0]
                positioned.append((next_pos - 0.5, rec))
    else:
        for pos, s in unanchored:
            comment, author, ts = _state_meta(s)
            if not s.after.strip() and s.before.strip():
                rec = EditRecord(None, "failed", 0.0, "delete", s.before, "")
            elif not s.before.strip() and s.after.strip():
                rec = EditRecord(None, "failed", 0.0, "insert", "", s.after)
            elif s.before != s.after:
                rec = EditRecord(None, "failed", 0.0, "replace", s.before, s.after)
            elif comment:
                rec = EditRecord(None, "failed", 0.0, "comment", s.after, s.after)
            else:
                continue
            rec.human_comment, rec.author, rec.ts = comment, author, ts
            positioned.append((float(pos), rec))

    return [rec for _, rec in sorted(positioned, key=lambda t: t[0])]


# ---------------------------------------------------------------- 观测与队列
def _next_obs_ids(obs_dir: Path, n: int) -> list[str]:
    top = 0
    if obs_dir.exists():
        for p in obs_dir.glob("*.yaml"):
            m = re.search(r"R0-(\d{4})", p.read_text("utf-8"))
            if m:
                top = max(top, int(m.group(1)))
    return [f"R0-{top + k + 1:04d}" for k in range(n)]


def _write_observations(
    records: list[EditRecord],
    feedback_ids: list[str],
    case_id: str,
    brand_id: str,
    obs_dir: Path,
) -> list[tuple[str, str, Path]]:
    """每条 feedback 一条 L0 observation（格式对齐 _EXAMPLE_obs.yaml）。返回 (obs_id, feedback_id, path)。"""
    obs_dir.mkdir(parents=True, exist_ok=True)
    ids = _next_obs_ids(obs_dir, len(records))
    now = datetime.now(UTC).isoformat()
    out: list[tuple[str, str, Path]] = []
    for obs_id, fid, rec in zip(ids, feedback_ids, records, strict=True):
        statement = rec.rationale_nl.strip()
        if len(statement) < 10:
            statement = f"{rec.edit_type}: {rec.before[:40]} → {rec.after[:40]}"
        obs = {
            "id": obs_id,
            "level": "L0",
            "statement": statement,
            "scope": {"kind": "client", "value": brand_id},
            "form": "non-normative",
            "dimension": rec.dimension,
            "evidence_ids": [case_id],
            "created_at": now,
            "extra": {
                "target_node_id": rec.node_id or "",
                "verdict": rec.verdict,
                "severity": rec.severity,
                "rationale_nl": rec.rationale_nl,
                "revised_text": rec.after,
                "original_text": rec.before,
            },
        }
        path = obs_dir / f"obs_{obs_id}.yaml"
        path.write_text(yaml.safe_dump(obs, allow_unicode=True, sort_keys=False), "utf-8")
        out.append((obs_id, fid, path))
    return out


def _write_unaligned(records: list[EditRecord], out_dir: Path) -> Path:
    failed = [r for r in records if r.anchor_level == "failed"]
    path = out_dir / "ingest" / "unaligned.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 对齐失败条目（SOP_FEEDBACK_INGEST §4）", ""]
    for r in failed:
        lines.append(f"- [{r.edit_type}] before={r.before[:60]!r} after={r.after[:60]!r}")
    if not failed:
        lines.append("（无）")
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


def push_annotation_queue(items: list[dict[str, Any]], *, run_id: str, out_dir: Path) -> Path:
    """推进待人工确认队列：离线 jsonl 是兜底真相，Langfuse best-effort。"""
    path = out_dir / "ingest" / "annotation_queue.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps({"run_id": run_id, **it}, ensure_ascii=False) + "\n")
    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        try:
            from langfuse import Langfuse

            lf = Langfuse()
            trace_fn = getattr(lf, "trace", None)  # langfuse 2.x API；3.x 改名则静默跳过
            if trace_fn is not None:
                trace = trace_fn(
                    name="nsc.ingest.annotation_queue",
                    metadata={"run_id": run_id, "items": len(items)},
                )
                for it in items:
                    trace.event(name="feedback.confirm", metadata=it)
        except Exception:
            pass  # Langfuse 未就绪不阻塞摄入（SOP：反馈收不回来是永久损失）
    return path


# ---------------------------------------------------------------- 端到端
def _finalize(
    records: list[EditRecord],
    *,
    case_id: str,
    db_path: str | Path,
    router: Any,
    obs_dir: Path,
    out_dir: Path,
    unit_kind: str,
    versions: dict[str, str] | None,
) -> IngestReport:
    store = FeedbackStore(db_path)
    try:
        brand_id = store.ensure_case(case_id)
        run_store = RunsStore(db_path)
        if router is None:
            # 干跑：dimension 是 NOT NULL，未分类的记录诚实落不了库，只出对齐报告
            _write_unaligned(records, out_dir)
            return IngestReport(
                case_id=case_id,
                feedback_ids=[],
                records=records,
                unaligned=[r for r in records if r.anchor_level == "failed"],
                run_id="",
                queue_path=None,
                dry_run=True,
            )

        classify = EditClassify(router, store=run_store, versions=versions)
        records = resolve_rewrites(records, classify.judge_rewrite_pairs)
        records = classify.classify(records)

        input_hash = hashlib.sha256(
            json.dumps(
                [(r.node_id, r.edit_type, r.before, r.after) for r in records],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        run_id = run_store.record(
            RunRecord.new(
                case_id=case_id,
                pass_name="ingest",
                spec_sha=(versions or {}).get("spec_sha", ""),
                profile_ver=(versions or {}).get("profile_ver", ""),
                brand_ver=(versions or {}).get("brand_ver", ""),
                ruleset_ver=(versions or {}).get("ruleset_ver", ""),
                promptset_ver=(versions or {}).get("promptset_ver", ""),
                model_id="deterministic+edit_classify",
                temperature=0.0,
                seed=None,
                input_hash=input_hash,
            )
        )

        feedback_ids: list[str] = []
        for rec in records:
            fid = store.insert_feedback(case_id, rec)
            feedback_ids.append(fid)
            if rec.edit_type in ("replace", "delete") and rec.before.strip():
                store.insert_revision_pair(fid, rec, unit_kind)
            if rec.edit_type == "replace" and rec.before.strip() and rec.after.strip():
                store.insert_preference_pair(case_id, rec, unit_kind)

        for obs_id, fid, obs_path in _write_observations(
            records, feedback_ids, case_id, brand_id, obs_dir
        ):
            store.insert_observation_index(obs_id, fid, obs_path)

        unaligned = [r for r in records if r.anchor_level == "failed"]
        _write_unaligned(records, out_dir)
        queue_path = push_annotation_queue(
            [
                {
                    "feedback_id": fid,
                    "case_id": case_id,
                    "dimension": r.dimension,
                    "verdict": r.verdict,
                    "severity": r.severity,
                    "anchor_level": r.anchor_level,
                    "anchor_conf": r.anchor_confidence,
                    "before": r.before,
                    "after": r.after,
                    "rationale_nl": r.rationale_nl,
                    "confirmed_by": "",
                }
                for fid, r in zip(feedback_ids, records, strict=True)
            ],
            run_id=run_id,
            out_dir=out_dir,
        )
        return IngestReport(case_id, feedback_ids, records, unaligned, run_id, queue_path)
    finally:
        store.close()


def ingest_docx(
    path: str | Path,
    *,
    case_id: str,
    db_path: str | Path,
    delivered_path: str | Path | None = None,
    router: Any = None,
    obs_dir: str | Path = DEFAULT_OBS_DIR,
    out_dir: str | Path = "out",
    unit_kind: str = "novel_paragraph",
    versions: dict[str, str] | None = None,
) -> IngestReport:
    """带修订 docx → 结构化反馈条目（验收：≤60s）。"""
    states = extract_paragraph_states(Path(path))
    delivered = load_delivered_paragraphs(delivered_path) if delivered_path else None
    records = _records_from_states(states, delivered)
    return _finalize(
        records,
        case_id=case_id,
        db_path=db_path,
        router=router,
        obs_dir=Path(obs_dir),
        out_dir=Path(out_dir),
        unit_kind=unit_kind,
        versions=versions,
    )


def ingest_text(
    path: str | Path,
    *,
    case_id: str,
    db_path: str | Path,
    router: Any = None,
    obs_dir: str | Path = DEFAULT_OBS_DIR,
    out_dir: str | Path = "out",
    versions: dict[str, str] | None = None,
) -> IngestReport:
    """纯文本/微信消息摄入：每行一条 comment 型反馈，锚点必然 failed。"""
    lines = [line.strip() for line in Path(path).read_text("utf-8").splitlines() if line.strip()]
    records = [
        EditRecord(
            node_id=None,
            anchor_level="failed",
            anchor_confidence=0.0,
            edit_type="comment",
            before="",
            after=line,
        )
        for line in lines
    ]
    return _finalize(
        records,
        case_id=case_id,
        db_path=db_path,
        router=router,
        obs_dir=Path(obs_dir),
        out_dir=Path(out_dir),
        unit_kind="message",
        versions=versions,
    )
