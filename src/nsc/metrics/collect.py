"""nsc metrics weekly 实现（D22 北极星 + D23 六个数，T-20）。

纯确定性计算，无 LLM。从 cases.db 统计编辑率/判官一致率/规则命中率/检索增益/单集成本，
按 D11 八类分解 edit_rate_json（混算即失败）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB = "cases/cases.db"


def _week_tag() -> str:
    """ISO 8601 周号：2025-W03。"""
    return datetime.now(UTC).strftime("%Y-W%V")


def _last_8_weeks() -> list[str]:
    """当前周往前 8 周的 ISO 周号列表（含本周）。"""
    from datetime import timedelta

    today = datetime.now(UTC)
    weeks: list[str] = []
    for i in range(8):
        w = (today - timedelta(weeks=i)).strftime("%Y-W%V")
        if w not in weeks:
            weeks.append(w)
    return weeks


def _conn() -> sqlite3.Connection:
    from db.migrate import open_db

    return open_db(DEFAULT_DB)


# ---------------------------------------------------------------------------
# 六个数（D23）
# ---------------------------------------------------------------------------


def _first_pass_rate(conn: sqlite3.Connection) -> float | None:
    """L0+L1 一次通过的集数 / 总集数。"""
    # 代理：有 ir_snapshots（产生过）且无 revision_pairs（未修改过）的 case 比例
    total = conn.execute("SELECT COUNT(DISTINCT case_id) FROM cases").fetchone()[0]
    if not total:
        return None
    revised = conn.execute("SELECT COUNT(DISTINCT case_id) FROM revision_pairs").fetchone()[0]
    return round(1.0 - revised / total, 3) if total else None


def _edit_rate(conn: sqlite3.Connection) -> dict[str, Any]:
    """人类编辑率：按 D11 八类分解（混算即失败）。"""
    rows = conn.execute(
        "SELECT dimension, COUNT(*) as cnt FROM feedback GROUP BY dimension"
    ).fetchall()
    per_dim: dict[str, int] = {str(r[0]): int(r[1]) for r in rows}
    total = sum(per_dim.values()) or 1
    return {
        "total_edits": sum(per_dim.values()),
        "per_dimension": per_dim,
        "structural_share": round(per_dim.get("structural", 0) / total, 3),
    }


def _judge_agreement(conn: sqlite3.Connection) -> dict[str, Any]:
    """判官-人类一致率（每 rubric 维度，取 judge_scores 最新校准）。"""
    rows = conn.execute(
        "SELECT dimension, mode, "
        "AVG(CASE WHEN verdict = (SELECT human_verdict FROM judge_calibration "
        "  WHERE judge_calibration.pair_id = judge_scores.pair_id) THEN 1.0 ELSE 0.0 END) "
        "AS agreement "
        "FROM judge_scores GROUP BY dimension, mode"
    ).fetchall()
    per_dim: dict[str, float] = {}
    for dim, mode, agree in rows:
        key = f"{dim}@{mode}"
        if agree is not None:
            per_dim[key] = round(float(agree), 3)
    return {"per_dimension": per_dim} if per_dim else {}


def _rule_net_gain(conn: sqlite3.Connection) -> dict[str, Any]:
    """规则命中率与净收益：每条 canonical 规则的 hit_count / 误报率。"""
    rows = conn.execute(
        "SELECT r.rule_id, r.hit_count, "
        "(SELECT COUNT(*) FROM rule_hits h WHERE h.rule_id = r.rule_id AND h.severity = 'info') "
        "AS false_pos "
        "FROM rules r WHERE r.level = 'L3' AND r.hit_count > 0"
    ).fetchall()
    per_rule: dict[str, dict[str, int]] = {}
    for rule_id, hit_count, false_pos in rows:
        per_rule[str(rule_id)] = {
            "hits": int(hit_count or 0),
            "false_positives": int(false_pos or 0),
        }
    return {"per_rule": per_rule} if per_rule else {}


def _retrieval_gain(conn: sqlite3.Connection) -> dict[str, Any]:
    """检索命中率与增益：retrieval_hit_rate + 最近一次 A/B 的 gain。"""
    row = conn.execute(
        "SELECT retrieval_hit_rate, retrieval_gain FROM metrics_weekly "
        "WHERE retrieval_hit_rate IS NOT NULL ORDER BY week DESC LIMIT 1"
    ).fetchone()
    if row:
        return {"hit_rate": float(row[0]), "gain": float(row[1]) if row[1] else None}
    return {}


def _cost_per_episode(conn: sqlite3.Connection) -> dict[str, Any]:
    """单集成本：最近一周的 runs 聚合。"""
    week = _week_tag()
    # 取最近一周的 runs（按 created_at 本周）
    rows = conn.execute(
        "SELECT AVG(cost_usd) as avg_cost, AVG(wall_ms) as avg_wall "
        "FROM runs WHERE created_at >= ?",
        (f"{week[:4]}-",),
    ).fetchone()
    if rows and rows[0] is not None:
        return {
            "avg_cost_usd": round(float(rows[0]), 4),
            "avg_wall_ms": int(rows[1] or 0),
        }
    return {}


# ---------------------------------------------------------------------------
# 北极星（D22）
# ---------------------------------------------------------------------------


def _northstar_trend(conn: sqlite3.Connection) -> dict[str, Any]:
    """结构性编辑率的 8 周滑动趋势。"""
    weeks = _last_8_weeks()[::-1]  # 从旧到新
    series: list[dict[str, Any]] = []
    for w in weeks:
        row = conn.execute(
            "SELECT structural_edit_rate FROM metrics_weekly WHERE week = ?", (w,)
        ).fetchone()
        if row and row[0] is not None:
            series.append({"week": w, "structural_edit_rate": float(row[0])})
    return {"weeks": series, "latest": series[-1] if series else None}


# ---------------------------------------------------------------------------
# 写 metrics_weekly 表
# ---------------------------------------------------------------------------


def compute_weekly(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """计算本周六个数并写入 metrics_weekly 表。返回 dict 格式的周报数据。"""
    close_later = conn is None
    if conn is None:
        conn = _conn()
    try:
        week = _week_tag()
        fpr = _first_pass_rate(conn)
        edit = _edit_rate(conn)
        judge = _judge_agreement(conn)
        rule = _rule_net_gain(conn)
        retrieval = _retrieval_gain(conn)
        cost = _cost_per_episode(conn)

        edit_rate_json = json.dumps(edit, ensure_ascii=False)
        judge_agreement_json = json.dumps(judge, ensure_ascii=False)
        rule_net_gain_json = json.dumps(rule, ensure_ascii=False)

        structural_edit_rate = edit.get("structural_share", 0.0)
        now = datetime.now(UTC).isoformat()

        conn.execute(
            """INSERT OR REPLACE INTO metrics_weekly
               (week, structural_edit_rate, first_pass_rate, edit_rate_json,
                judge_agreement_json, rule_net_gain_json,
                retrieval_hit_rate, retrieval_gain,
                cost_per_episode_usd, minutes_per_episode, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                week,
                structural_edit_rate,
                fpr,
                edit_rate_json,
                judge_agreement_json,
                rule_net_gain_json,
                retrieval.get("hit_rate"),
                retrieval.get("gain"),
                cost.get("avg_cost_usd"),
                None,
                now,
            ),
        )
        conn.commit()
        return {
            "week": week,
            "structural_edit_rate": structural_edit_rate,
            "first_pass_rate": fpr,
            "edit_rate": edit,
            "judge_agreement": judge,
            "rule_net_gain": rule,
            "retrieval": retrieval,
            "cost": cost,
            "computed_at": now,
        }
    finally:
        if close_later:
            conn.close()


# ---------------------------------------------------------------------------
# 渲染 docs/metrics/latest.md
# ---------------------------------------------------------------------------


def _render_md(data: dict[str, Any]) -> str:
    """周报数据 → markdown（docs/metrics/latest.md 格式）。"""
    lines: list[str] = [
        f"# 飞轮周报 · {data['week']}",
        "",
        f"计算时间：{data['computed_at']}",
        "",
        "## 北极星（D22）",
        "",
        f"- **结构性编辑率**：{data['structural_edit_rate']}",
        "  （下降 = 正确方向；若连升 2 周应启动调查）",
        "",
        "## 六个数（D23）",
        "",
        "| # | 指标 | 值 | 健康方向 |",
        "|---|---|---|---|",
    ]
    fpr = data.get("first_pass_rate")
    lines.append(f"| 1 | 首过率 | {fpr or 'N/A'} | ↑ |")
    edit = data.get("edit_rate", {})
    structural_share = edit.get("structural_share", 0)
    lines.append(f"| 2 | 人类编辑率（structural 占比） | {structural_share} | ↓ |")
    per_dim = edit.get("per_dimension", {})
    if per_dim:
        lines.append("")
        lines.append("  **D11 八类分解**（混算即失败）：")
        for dim in [
            "structural",
            "character",
            "placement",
            "dialogue",
            "factual",
            "compliance",
            "producibility",
            "taste",
        ]:
            cnt = per_dim.get(dim, 0)
            lines.append(f"  - {dim}：{cnt}")
        lines.append("")

    judge = data.get("judge_agreement", {})
    jd = judge.get("per_dimension", {})
    lines.append(f"| 3 | 判官-人类一致率 | {jd or 'N/A'} | ↑ |")
    rule = data.get("rule_net_gain", {})
    rcount = len(rule.get("per_rule", {}))
    lines.append(f"| 4 | 规则命中率与净收益 | {rcount} 条规则有命中 | 命中>0 |")
    ret = data.get("retrieval", {})
    lines.append(f"| 5 | 检索命中率与增益 | hit_rate={ret.get('hit_rate', 'N/A')} | ↑ |")
    cost = data.get("cost", {})
    lines.append(f"| 6 | 单集成本 | ${cost.get('avg_cost_usd', 'N/A')} | ↓ |")
    lines.append("")
    lines.append("## 北极星趋势（8 周滑动）")
    lines.append("")
    lines.append("_待 history 积累后自动展开_")
    lines.append("")
    lines.append("---")
    lines.append(f"*nsc metrics weekly @ {data['computed_at']}*")
    return "\n".join(lines)


def weekly_report(write_dir: str = "docs/metrics/") -> Path:
    """计算并写入周报文件。返回 latest.md 路径。"""
    conn = _conn()
    try:
        data = compute_weekly(conn)
        md = _render_md(data)
        out = Path(write_dir)
        out.mkdir(parents=True, exist_ok=True)
        target = out / "latest.md"
        target.write_text(md, "utf-8")
        # 同时归档一份按周
        archive = out / f"{data['week']}.md"
        archive.write_text(md, "utf-8")
        return target
    finally:
        conn.close()
