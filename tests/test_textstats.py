"""textstats 纯函数的单元测试（T-27）。先红后绿的 TDD 用例。"""

from __future__ import annotations

import pytest

from nsc.textstats import (
    chapter_ngram_repeats,
    density_exceeds,
    hanzi_ngrams,
    join_text,
    long_paras,
    max_consecutive_char_lines,
    max_word_count,
    para_cv,
    same_prefix_runs,
    sent_cv,
    split_paragraphs,
    split_sentences,
)

# chapter_ngram_repeats 用例的公共句子（纯汉字，长度刻意 ≥6 以产生 6-gram）
S1 = "她把那杯冷掉的茶端起来又放下"
S2 = "他把伞收起来靠在门边等着"
S3 = "窗外的雨下了一整个下午"


# ---------------------------------------------------------------- 切分与拼接


def test_split_paragraphs() -> None:
    assert split_paragraphs("") == []
    assert split_paragraphs("只有一段。") == ["只有一段。"]
    assert split_paragraphs("第一段。\n\n第二段。") == ["第一段。", "第二段。"]
    assert split_paragraphs("第一段。\n \n  第二段。\n\n\n第三段。") == [
        "第一段。",
        "第二段。",
        "第三段。",
    ]


def test_split_paragraphs_roundtrip_with_join_text() -> None:
    """split ∘ join 必须还原段落（PRS-001 / PRS-012 依赖）。"""
    paras = ["甲段落。", "乙段落。", "丙段落。"]
    assert split_paragraphs(join_text(paras)) == paras


def test_split_sentences() -> None:
    assert split_sentences("") == []
    assert split_sentences("他推开门。") == ["他推开门"]
    assert split_sentences("他推开门。她抬起头！茶凉了？灯灭了；") == [
        "他推开门",
        "她抬起头",
        "茶凉了",
        "灯灭了",
    ]


def test_split_sentences_drops_tiny_fragments() -> None:
    """≤2 字的碎片（语气词残句）丢弃。"""
    assert split_sentences("好。嗯？") == []
    assert split_sentences("好的。他推开门走了出去。") == ["他推开门走了出去"]


def test_join_text() -> None:
    assert join_text([]) == ""
    assert join_text(["甲", "乙"]) == "甲\n乙"


# ---------------------------------------------------------------- 变异系数


def test_para_cv_short_input_returns_one() -> None:
    assert para_cv("") == 1.0
    assert para_cv("只有一段，长短无所谓。") == 1.0
    assert para_cv("甲段。\n乙段。") == 1.0


def test_para_cv_uniform_is_zero() -> None:
    text = "一二三四五\n一二三四五\n一二三四五"
    assert para_cv(text) == 0.0


def test_para_cv_exact_value() -> None:
    # 段长 10/10/30：mean=50/3，总体 std=sqrt(800/9)/1 → cv=sqrt(800)/50
    text = "一二三四五六七八九十\n一二三四五六七八九十\n" + "一二三四五六七八九十" * 3
    assert para_cv(text) == pytest.approx(0.565685, rel=1e-4)


def test_sent_cv_short_input_returns_one() -> None:
    assert sent_cv("") == 1.0
    assert sent_cv("两句而已。也就两句。") == 1.0


def test_sent_cv_uniform_is_zero() -> None:
    assert sent_cv("一二三四五六。一二三四五六。一二三四五六。") == 0.0


def test_sent_cv_varied_is_high() -> None:
    assert sent_cv("一二三四五六七八九。一二三。一二三四五。") > 0.3


# ---------------------------------------------------------------- 连续与计数


def test_max_consecutive_char_lines() -> None:
    assert max_consecutive_char_lines("", "了") == 0
    assert max_consecutive_char_lines("他来了。天空放晴。她走了。没有声音。", "了") == 1
    assert (
        max_consecutive_char_lines(
            "他放下了杯子。她笑出了声。茶凉了半截。天暗了下来。他走了两步。灯灭了一瞬。", "了"
        )
        == 6
    )


def test_max_consecutive_char_lines_absent_char() -> None:
    assert max_consecutive_char_lines("他来了。她走了。", "伞") == 0


def test_long_paras() -> None:
    assert long_paras("", 300) == 0
    assert long_paras("字" * 300, 300) == 0  # 恰好等于阈值不计
    assert long_paras("字" * 301, 300) == 1
    assert long_paras(join_text(["字" * 320, "字" * 320, "短段"]), 300) == 2


def test_density_exceeds() -> None:
    assert density_exceeds("", ["似乎"], 333) is False
    assert density_exceeds("他似乎迟疑了。", ["似乎"], 333) is False  # 1 <= max(1, 0)
    assert density_exceeds("他似乎迟疑，她可能同意。", ["似乎", "可能"], 333) is True


def test_density_exceeds_long_text_threshold_scales() -> None:
    # chars≈704 → 704//333=2：2 次不超、3 次超
    body = "字" * 700
    assert density_exceeds(body + "似乎可能", ["似乎", "可能", "或许"], 333) is False
    assert density_exceeds(body + "似乎可能或许", ["似乎", "可能", "或许"], 333) is True


def test_max_word_count() -> None:
    assert max_word_count("", ["仿佛"]) == 0
    assert max_word_count("没有目标词。", ["仿佛"]) == 0
    assert max_word_count("仿佛仿佛宛如", ["仿佛", "宛如"]) == 2
    assert max_word_count("任意文本", []) == 0


def test_same_prefix_runs() -> None:
    assert same_prefix_runs("") == 0
    assert same_prefix_runs("他来了。她走了。天亮了。") == 1
    assert same_prefix_runs("他来了。他来过。她走了。") == 2
    assert same_prefix_runs("他来了。他来过。他来迟。他来早。") == 4


# ---------------------------------------------------------------- n-gram


def test_hanzi_ngrams() -> None:
    assert hanzi_ngrams("", 6) == set()
    assert hanzi_ngrams("abc123", 2) == set()
    assert hanzi_ngrams("他来到窗边", 6) == set()  # 5 个汉字不足 6
    assert hanzi_ngrams("他来到窗边前", 6) == {"他来到窗边前"}
    assert hanzi_ngrams("他来到窗边前", 2) == {"他来", "到窗", "边前"}
    assert hanzi_ngrams("他来到，窗边前", 6) == set()  # 标点打断连续段
    assert hanzi_ngrams("任意文本", 0) == set()


def test_chapter_ngram_repeats_edges() -> None:
    assert chapter_ngram_repeats([], 0, 6) == 0
    only_first = [{"order": 0, "paragraphs": [S1, S2, S3]}]
    assert chapter_ngram_repeats(only_first, 0, 6) == 0  # 没有更早章节
    assert chapter_ngram_repeats(only_first, 99, 6) == 0  # 找不到当前章


def test_chapter_ngram_repeats_counts() -> None:
    fail = [
        {"order": 0, "paragraphs": [S1, S2, S3]},
        {"order": 1, "paragraphs": [S1, S1, S2, S2, S3, S3, "新的一句没有重复"]},
    ]
    assert chapter_ngram_repeats(fail, 0, 6) == 0
    # S1×2 贡献 2 个 6-gram、S2×2 贡献 2 个、S3×2 贡献 1 个
    assert chapter_ngram_repeats(fail, 1, 6) == 5


def test_chapter_ngram_repeats_pass_shapes() -> None:
    # 早章出现过、本章只出现 1 次 → 不计
    once = [
        {"order": 0, "paragraphs": [S1]},
        {"order": 1, "paragraphs": [S1, "全新的句子"]},
    ]
    assert chapter_ngram_repeats(once, 1, 6) == 0
    # 本章重复但早章没有 → 不计
    not_in_prev = [
        {"order": 0, "paragraphs": [S3]},
        {"order": 1, "paragraphs": [S1, S1]},
    ]
    assert chapter_ngram_repeats(not_in_prev, 1, 6) == 0
