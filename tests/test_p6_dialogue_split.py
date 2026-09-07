"""p6_prose 对白机械拆段（TDD：先红后绿）。

合成 IR 夹具：含对白+叙事混排段落的 p6 输出 → 机械拆段后对白独立成段、
anchor_map 索引正确、NOV-001/NOV-002 检查都过。
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


def _fragment(
    line_texts: list[tuple[str, str]],
    paragraph: str,
) -> dict[str, object]:
    """构建含对白+叙事混排段落的 fragment。line_texts: [(line_id, text)]"""
    beat_id = "01M04TVA5Z74ZZKYYJRFWXFC96"
    lines = []
    for lid, txt in line_texts:
        lines.append(
            {
                "id": lid,
                "line_type": "dialogue",
                "text": txt,
                "character_id": "c1",
            }
        )
    return {
        "episode": {"id": "ep1", "order": 0},
        "beats": [
            {
                "id": beat_id,
                "_lines": lines,
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
                        "lines": lines,
                    }
                ],
            }
        ],
        "bible": {"characters": [], "locations": []},
        "voice": {},
    }


def _anchor_map(paragraph_index: int, line_ids: list[str]) -> list[dict[str, object]]:
    beat_id = "01M04TVA5Z74ZZKYYJRFWXFC96"
    return [
        {
            "paragraph_index": paragraph_index,
            "beat_id": beat_id,
            "line_ids": line_ids,
        }
    ]


def test_dialogue_in_middle_is_split_into_own_paragraph(tmp_path: Path) -> None:
    """对白埋在叙事长段中间时，应对白独立成段，anchor_map 同步更新。"""
    line_text = "这茶真好喝"
    line_id = "01M04TVA5Z74ZZKYYJRFWXFCA0"
    paragraph = (
        "小满轻轻放下茶杯，眼神里带着一种久违的安宁，嘴角笑意很淡，"
        "她环顾四周，看见茶室的木格窗透进午后阳光，尘埃在光线里跳舞，"
        "听见自己的声音很轻却很稳，她说："
        "「这茶真好喝」"
        "，然后低下头，继续用指腹摩挲温热的杯壁，似乎想把这瞬间的质感多留一秒是一秒。"
    )

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps([paragraph], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            _anchor_map(0, [line_id]),
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = _fragment([(line_id, line_text)], paragraph)

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    paras = chapter["paragraphs"]

    # 对白原文必须单独成段且 ratio ≈ 1
    assert line_text in paras, f"对白原文 {line_text!r} 应在独立段中"
    dialogue_para = next(p for p in paras if line_text in p)
    assert dialogue_para == line_text, f"对白段应为原文 {line_text!r}，实际为 {dialogue_para!r}"

    # anchor_map 必须指向新索引
    am = next(am for am in chapter["anchor_map"] if line_id in am.get("line_ids", []))
    assert am["paragraph_index"] == paras.index(dialogue_para)
    assert am["line_ids"] == [line_id]

    # 叙事段不能仍含对白原文（否则 NOV-002 仍可能被拉穿）
    for p in paras:
        if p is not dialogue_para:
            assert line_text not in p


def test_multiple_dialogues_in_one_paragraph(tmp_path: Path) -> None:
    """一段含多条对白时，每条对白都应独立成段。"""
    l1, l1id = "这茶真好喝", "01M04TVA5Z74ZZKYYJRFWXFCA0"
    l2, l2id = "苦死了", "01M04TVA5Z74ZZKYYJRFWXFCA1"
    paragraph = f"小满说：「{l1}」。阿茶摇头：「{l2}」。服务员站在一旁没说话。"

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps([paragraph], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            _anchor_map(0, [l1id, l2id]),
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = _fragment([(l1id, l1), (l2id, l2)], paragraph)

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    paras = chapter["paragraphs"]

    assert l1 in paras
    assert l2 in paras
    assert paras.count(l1) == 1
    assert paras.count(l2) == 1

    am1 = next(am for am in chapter["anchor_map"] if l1id in am.get("line_ids", []))
    am2 = next(am for am in chapter["anchor_map"] if l2id in am.get("line_ids", []))
    assert paras[am1["paragraph_index"]] == l1
    assert paras[am2["paragraph_index"]] == l2


def test_dialogue_at_start_of_paragraph(tmp_path: Path) -> None:
    """对白在段首且仅被标点包围时，对白应为首段，标点被丢弃。"""
    line_text = "这茶真好喝"
    line_id = "01M04TVA5Z74ZZKYYJRFWXFCA0"
    paragraph = f"「{line_text}」，小满抬头看向窗外。"

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps([paragraph], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            _anchor_map(0, [line_id]),
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = _fragment([(line_id, line_text)], paragraph)

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    paras = chapter["paragraphs"]

    assert paras[0] == line_text
    assert paras[1] == "」，小满抬头看向窗外。"


def test_dialogue_at_end_of_paragraph(tmp_path: Path) -> None:
    """对白在段尾且仅被标点包围时，对白应为末段，标点被丢弃。"""
    line_text = "这茶真好喝"
    line_id = "01M04TVA5Z74ZZKYYJRFWXFCA0"
    paragraph = f"小满放下杯子，轻声说：「{line_text}」"

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps([paragraph], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            _anchor_map(0, [line_id]),
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = _fragment([(line_id, line_text)], paragraph)

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    paras = chapter["paragraphs"]

    assert paras[-1] == line_text
    assert paras[-2] == "小满放下杯子，轻声说：「"


def test_paragraph_exactly_matching_dialogue_is_unchanged(tmp_path: Path) -> None:
    """段落恰好是对白原文时，不应产生空段。"""
    line_text = "这茶真好喝"
    line_id = "01M04TVA5Z74ZZKYYJRFWXFCA0"
    paragraph = line_text

    payload = {
        "chapter_title": "章",
        "paragraphs_json": json.dumps([paragraph], ensure_ascii=False),
        "anchor_map_json": json.dumps(
            _anchor_map(0, [line_id]),
            ensure_ascii=False,
        ),
    }

    ctx = _make_ctx(tmp_path, payload)
    fragment = _fragment([(line_id, line_text)], paragraph)

    result = p6_run(ctx, fragment)
    chapter = result["chapter"]
    assert chapter["paragraphs"] == [paragraph]
    assert chapter["anchor_map"][0]["paragraph_index"] == 0
