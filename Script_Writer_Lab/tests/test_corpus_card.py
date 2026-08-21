"""L-01/L-02 · 语料解析与统计卡。实现目标: src/lab/corpus.py
契约: spec/schemas/corpus_card.schema.yaml(本文件在实现前必须为红)"""
from pathlib import Path

import jsonschema
import pytest
import yaml
from lab.corpus import ingest, parse_script, stats_card

FIX = Path(__file__).parent / "fixtures" / "corpus"
SCHEMA = yaml.safe_load(
    (Path(__file__).parents[1] / "spec/schemas/corpus_card.schema.yaml").read_text(encoding="utf-8")
)


def test_drama_card_validates_against_schema():
    card = stats_card(parse_script(FIX / "mini_drama.txt"))
    jsonschema.validate(card, SCHEMA)
    assert card["kind"] == "drama_script"
    assert card["n_lines"] > 0
    assert 0.0 < card["dialogue_ratio"] <= 1.0


def test_novel_kind_detection():
    card = stats_card(parse_script(FIX / "mini_novel.txt"))
    jsonschema.validate(card, SCHEMA)
    assert card["kind"] == "novel"


def test_ingest_dedup_by_simhash(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text((FIX / "mini_drama.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (inbox / "a_copy.txt").write_text((FIX / "mini_drama.txt").read_text(encoding="utf-8"), encoding="utf-8")
    report = ingest(inbox, tmp_path / "store")
    assert report["ingested"] == 1
    assert report["duplicates"] == 1


def test_hook_positions_are_normalized():
    card = stats_card(parse_script(FIX / "mini_drama.txt"))
    assert all(0.0 <= p <= 1.0 for p in card["hook_positions"])


@pytest.mark.llm
def test_ingest_real_corpus_smoke():
    inbox = Path(__file__).parents[1] / "corpus" / "inbox"
    if not any(inbox.iterdir()):
        pytest.skip("corpus/inbox 为空")
    report = ingest(inbox, Path(__file__).parents[1] / "corpus" / "store")
    assert report["ingested"] > 0
