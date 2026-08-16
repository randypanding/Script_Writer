"""Provenance 落库（D20）与 spec 指纹。

每个产物必须可二分定位到某次运行：runs 表是唯一的执行台账。
真相仍在各 JSON/yaml（git），runs 表是可重建的工作副本（D28）。
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ulid import ULID

_MIGRATION = Path("db/migrations/0001_init.sql")


def spec_fingerprint(paths: list[Path]) -> str:
    """spec 相关文件内容的联合 sha256，进 cache key 与 provenance.spec_sha。"""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: str(x)):
        h.update(str(p).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


@dataclass(slots=True)
class RunRecord:
    """对应 runs 表的一行（D20）。"""

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
    cache_hit: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    wall_ms: int = 0
    langfuse_trace_id: str = ""
    case_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def new(cls, **kw: object) -> RunRecord:
        kw.setdefault("run_id", str(ULID()))
        return cls(**kw)  # type: ignore[arg-type]


class RunsStore:
    """runs 表的最小读写。db 不存在时按 0001_init.sql 初始化。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        vec_ok = False
        try:
            import sqlite_vec

            self._conn.enable_load_extension(True)  # type: ignore[attr-defined]
            sqlite_vec.load(self._conn)
            vec_ok = True
        except Exception:
            vec_ok = False
        if _MIGRATION.exists():
            sql = _MIGRATION.read_text("utf-8")
            if not vec_ok:
                # 无扩展加载能力的 Python 构建：跳过 vec0 虚拟表（仅检索用，T-16）
                sql = re.sub(r"CREATE VIRTUAL TABLE[^;]*vec0[^;]*;", "", sql, flags=re.IGNORECASE)
            self._conn.executescript(sql)
            self._conn.commit()

    def record(self, rec: RunRecord) -> str:
        self._conn.execute(
            """INSERT INTO runs (run_id, case_id, pass_name, spec_sha, profile_ver,
               brand_ver, ruleset_ver, promptset_ver, model_id, temperature, seed,
               input_hash, cache_hit, tokens_in, tokens_out, cost_usd, wall_ms,
               langfuse_trace_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.run_id,
                rec.case_id,
                rec.pass_name,
                rec.spec_sha,
                rec.profile_ver,
                rec.brand_ver,
                rec.ruleset_ver,
                rec.promptset_ver,
                rec.model_id,
                rec.temperature,
                rec.seed,
                rec.input_hash,
                rec.cache_hit,
                rec.tokens_in,
                rec.tokens_out,
                rec.cost_usd,
                rec.wall_ms,
                rec.langfuse_trace_id,
                rec.created_at,
            ),
        )
        self._conn.commit()
        return rec.run_id

    def runs(self, pass_name: str | None = None) -> list[dict[str, object]]:
        sql = "SELECT * FROM runs"
        args: tuple = ()
        if pass_name:
            sql += " WHERE pass_name = ?"
            args = (pass_name,)
        cur = self._conn.execute(sql, args)
        cols = [c[0] for c in cur.description or []]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
