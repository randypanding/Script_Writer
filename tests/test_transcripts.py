"""SW-01 transcript 持久化：ModelRouter 每次 LLM 调用的 prompt/response 落 SQLite。

表结构对齐 Lab 仓 ADR-0001 §接口：(ts, caller, model, prompt, response,
tokens_in, tokens_out, cost_usd, experiment_id)。库位置默认 out/transcripts.db，
可用 NSC_TRANSCRIPT_DB / 构造参数改道（Lab 经 subprocess 调 SW 时靠环境变量接线）。
"""

from __future__ import annotations

import json
import sqlite3
import types
from pathlib import Path

import pytest


class _FakeResp:
    """litellm.completion 的最小桩（无网络）。"""

    def __init__(self) -> None:
        msg = types.SimpleNamespace(content='{"ok": 1}', reasoning_content="")
        self.choices = [types.SimpleNamespace(message=msg)]
        self.usage = types.SimpleNamespace(prompt_tokens=11, completion_tokens=7)


@pytest.fixture()
def fake_litellm(monkeypatch):
    calls: list[dict] = []

    def _completion(**kwargs):
        calls.append(kwargs)
        return _FakeResp()

    import litellm

    monkeypatch.setattr(litellm, "completion", _completion)
    return calls


def _rows(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT ts, caller, model, prompt, response, tokens_in, tokens_out,"
            " cost_usd, experiment_id FROM transcripts"
        )
        cols = [c[0] for c in cur.description or []]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        conn.close()


def test_complete_writes_transcript_row(tmp_path, fake_litellm, monkeypatch):
    from nsc.runtime.models import ModelRouter

    db = tmp_path / "t.db"
    monkeypatch.setenv("NSC_TRANSCRIPT_DB", str(db))
    router = ModelRouter(experiment_id="exp-42")
    res = router.complete(
        "tier_bulk",
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        json_mode=True,
        seed=1,
    )
    assert res.text == '{"ok": 1}'

    rows = _rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["caller"] == "tier_bulk"
    assert row["model"] == "openai/LongCat-2.0"
    assert json.loads(row["prompt"]) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert row["response"] == '{"ok": 1}'
    assert row["tokens_in"] == 11
    assert row["tokens_out"] == 7
    assert row["experiment_id"] == "exp-42"
    assert row["cost_usd"] > 0  # cost_per_mtok 兜底价


def test_transcript_db_via_constructor(tmp_path, fake_litellm, monkeypatch):
    from nsc.runtime.models import ModelRouter

    monkeypatch.delenv("NSC_TRANSCRIPT_DB", raising=False)
    db = tmp_path / "ctor.db"
    router = ModelRouter(transcript_db=db)
    router.complete("tier_bulk", [{"role": "user", "content": "hi"}])
    assert len(_rows(db)) == 1


def test_transcript_failure_never_breaks_routing(tmp_path, fake_litellm, monkeypatch):
    """transcript 是 best-effort 台账：写库失败不得影响 LLM 路由本身。"""
    from nsc.runtime.models import ModelRouter

    router = ModelRouter(transcript_db=tmp_path)  # 目录当 db 路径 → 打不开
    res = router.complete("tier_bulk", [{"role": "user", "content": "hi"}])
    assert res.text == '{"ok": 1}'
