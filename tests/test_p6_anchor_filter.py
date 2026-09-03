"""p6_prose anchor_map 机械兜底测试（round14 方法论：结构性约束一律机械兜底）。

幻觉 line_id / beat_id 不抛 PassFailure，直接过滤。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from nsc.passes import PassContext
from nsc.passes.p6_prose import run as p6_run
from nsc.runtime.models import LLMResult
from nsc.runtime.provenance import RunsStore


class _Stub:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def resolve(self, tier: str) -> dict[str, Any]:
        return {"model": "stub", "temperature": 0.0, "max_tokens": 4000}

    def complete(self, tier: str, messages: list[dict[str, Any]], *, json_mode: bool = False, seed: int | None = None) -> LLMResult:
        return LLMResult(
            text=json.dumps(self.payload, ensure_ascii=False),
            model_id="stub",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            wall_ms=1,
        )


def _make_ctx(tmp_path: Path, payload: dict[str, Any]) -> PassContext:
    os.environ["NSC_NO_CACHE"] = "1"
    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        router=_Stub(payload),
        store=RunsStore(tmp_path / "runs.db"),
        ruleset_ver="test",
        spec_sha="test",
    )


def test_filters_hallucinated_line_ids(tmp_path: Path) -> None:
    """幻觉 line_id 应被过滤，不抛 PassFailure。"""
    beat_id = "01M04TVA5Z74ZZKYYJRFWXFC96"
    valid_line = "01M04TVA5Z74ZZKYYJRFWXFCA0"
    fake_line = "01M04TVA5Z74ZZKYYJRFWXFZZZ"

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps(["「台词」"], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            [
                {
                    "paragraph_index": 0,
                    "beat_id": beat_id,
                    "line_ids": [valid_line, fake_line],
                }
            ],
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = {
        "episode": {"id": "ep1", "order": 0},
        "beats": [
            {
                "id": beat_id,
                "_lines": [
                    {
                        "id": valid_line,
                        "line_type": "dialogue",
                        "text": "台词",
                    }
                ],
            }
        ],
        "scenes_with_lines": [
            {
                "id": "sc1",
                "location_name": "茶店",
                "time_of_day": "afternoon",
                "character_names": ["小满"],
                "goal": "g",
                "conflict": "c",
                "turn": "t",
                "summary": "s",
                "beats": [
                    {
                        "id": beat_id,
                        "lines": [
                            {
                                "id": valid_line,
                                "line_type": "dialogue",
                                "text": "台词",
                            }
                        ],
                    }
                ],
            }
        ],
        "bible": {"characters": [], "locations": []},
        "voice": {},
    }

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    assert chapter["anchor_map"] == [
        {"paragraph_index": 0, "beat_id": beat_id, "line_ids": [valid_line]}
    ]


def test_drops_entries_with_invalid_beat_id(tmp_path: Path) -> None:
    """beat_id 不存在的条目应整条丢弃。"""
    valid_beat = "01M04TVA5Z74ZZKYYJRFWXFC96"
    fake_beat = "01M04TVA5Z74ZZKYYJRFWXFCZZ"
    valid_line = "01M04TVA5Z74ZZKYYJRFWXFCA0"

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps(["p0", "「台词」"], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            [
                {"paragraph_index": 0, "beat_id": fake_beat, "line_ids": []},
                {"paragraph_index": 1, "beat_id": valid_beat, "line_ids": [valid_line]},
            ],
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = {
        "episode": {"id": "ep1", "order": 0},
        "beats": [
            {
                "id": valid_beat,
                "_lines": [
                    {
                        "id": valid_line,
                        "line_type": "dialogue",
                        "text": "台词",
                    }
                ],
            }
        ],
        "scenes_with_lines": [
            {
                "id": "sc1",
                "location_name": "茶店",
                "time_of_day": "afternoon",
                "character_names": ["小满"],
                "goal": "g",
                "conflict": "c",
                "turn": "t",
                "summary": "s",
                "beats": [
                    {
                        "id": valid_beat,
                        "lines": [
                            {
                                "id": valid_line,
                                "line_type": "dialogue",
                                "text": "台词",
                            }
                        ],
                    }
                ],
            }
        ],
        "bible": {"characters": [], "locations": []},
        "voice": {},
    }

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    assert len(chapter["anchor_map"]) == 1
    assert chapter["anchor_map"][0]["beat_id"] == valid_beat
    assert chapter["anchor_map"][0]["paragraph_index"] == 1


def test_all_entries_invalid_results_in_empty_anchor_map(tmp_path: Path) -> None:
    """所有条目都无效时，anchor_map 为空，不抛 PassFailure。"""
    fake_beat = "01M04TVA5Z74ZZKYYJRFWXFCZZ"
    fake_line = "01M04TVA5Z74ZZKYYJRFWXFZZZ"

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps(["「台词」"], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            [{"paragraph_index": 0, "beat_id": fake_beat, "line_ids": [fake_line]}],
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = {
        "episode": {"id": "ep1", "order": 0},
        "beats": [
            {
                "id": "01M04TVA5Z74ZZKYYJRFWXFC96",
                "_lines": [
                    {
                        "id": "01M04TVA5Z74ZZKYYJRFWXFCA0",
                        "line_type": "dialogue",
                        "text": "台词",
                    }
                ],
            }
        ],
        "scenes_with_lines": [
            {
                "id": "sc1",
                "location_name": "茶店",
                "time_of_day": "afternoon",
                "character_names": ["小满"],
                "goal": "g",
                "conflict": "c",
                "turn": "t",
                "summary": "s",
                "beats": [
                    {
                        "id": "01M04TVA5Z74ZZKYYJRFWXFC96",
                        "lines": [
                            {
                                "id": "01M04TVA5Z74ZZKYYJRFWXFCA0",
                                "line_type": "dialogue",
                                "text": "台词",
                            }
                        ],
                    }
                ],
            }
        ],
        "bible": {"characters": [], "locations": []},
        "voice": {},
    }

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    assert chapter["anchor_map"] == []
