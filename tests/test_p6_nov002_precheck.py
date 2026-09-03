"""p6_prose NOV-002 段落长度机械预检（生成侧，不触 checker）。

长段落包含对白原文时，fuzz.ratio(line, para) 会因长度偏差被拉低；
在 NOV-001 逐字覆盖之后，额外约束段落长度 ≤ 5 × 对白长度，
给 fuzz.ratio 留出安全余量（阈值 0.7 → 理论极限 ~1.43×）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from nsc.passes import PassContext
from nsc.passes.p6_prose import run as p6_run
from nsc.runtime.models import LLMResult
from nsc.runtime.provenance import RunsStore


class _Stub:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def resolve(self, tier: str) -> dict[str, object]:
        return {"model": "stub", "temperature": 0.0, "max_tokens": 4000}

    def complete(
        self,
        tier: str,
        messages: list[dict[str, object]],
        *,
        json_mode: bool = False,
        seed: int | None = None,
    ) -> LLMResult:
        return LLMResult(
            text=json.dumps(self.payload, ensure_ascii=False),
            model_id="stub",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            wall_ms=1,
        )


def _make_ctx(tmp_path: str, payload: dict[str, object]) -> PassContext:
    os.environ["NSC_NO_CACHE"] = "1"
    profile = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    return PassContext(
        profile=profile,
        brand=brand,
        router=_Stub(payload),
        store=RunsStore(f"{tmp_path}/runs.db"),
        ruleset_ver="test",
        spec_sha="test",
    )


def _fragment(line_text: str, paragraph: str) -> dict[str, object]:
    beat_id = "01M04TVA5Z74ZZKYYJRFWXFC96"
    line_id = "01M04TVA5Z74ZZKYYJRFWXFCA0"
    return {
        "episode": {"id": "ep1", "order": 0},
        "beats": [
            {
                "id": beat_id,
                "_lines": [
                    {
                        "id": line_id,
                        "line_type": "dialogue",
                        "text": line_text,
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
                                "id": line_id,
                                "line_type": "dialogue",
                                "text": line_text,
                            }
                        ],
                    }
                ],
            }
        ],
        "bible": {"characters": [], "locations": []},
        "voice": {},
    }


def test_long_paragraph_containing_dialogue_triggers_passfailure(tmp_path: str) -> None:
    """段落超过对白 5 倍时应触发 PassFailure，给 phase retry 可操作的诊断。"""
    line_text = "这茶真好喝"
    paragraph = "小满轻轻放下茶杯，眼神里带着一种久违的安宁，嘴角笑意很淡，"
    paragraph += "她环顾四周，看见茶室的木格窗透进午后阳光，尘埃在光线里跳舞，"
    paragraph += "听见自己的声音很轻却很稳，她说："
    paragraph += "「这茶真好喝」"
    paragraph += "，然后低下头，继续用指腹摩挲温热的杯壁，似乎想把这瞬间的质感多留一秒是一秒。"

    payload: dict[str, object] = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps([paragraph], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            [
                {
                    "paragraph_index": 0,
                    "beat_id": "01M04TVA5Z74ZZKYYJRFWXFC96",
                    "line_ids": ["01M04TVA5Z74ZZKYYJRFWXFCA0"],
                }
            ],
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = _fragment(line_text, paragraph)

    try:
        p6_run(ctx, fragment)
    except Exception as e:
        assert "段落" in str(e) and "对白" in str(e), f"诊断文案应指向段落/对白：{e}"
        return

    raise AssertionError("超长段落未触发 PassFailure")


def test_short_paragraph_containing_dialogue_passes(tmp_path: str) -> None:
    """段落在对白 5 倍以内时应通过 p6_prose 机械预检。"""
    line_text = "这茶真好喝"
    paragraph = "小满说：「这茶真好喝。」"

    payload: dict[str, object] = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps([paragraph], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            [
                {
                    "paragraph_index": 0,
                    "beat_id": "01M04TVA5Z74ZZKYYJRFWXFC96",
                    "line_ids": ["01M04TVA5Z74ZZKYYJRFWXFCA0"],
                }
            ],
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = _fragment(line_text, paragraph)
    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    assert chapter["anchor_map"] == [
        {
            "paragraph_index": 0,
            "beat_id": "01M04TVA5Z74ZZKYYJRFWXFC96",
            "line_ids": ["01M04TVA5Z74ZZKYYJRFWXFCA0"],
        }
    ]
