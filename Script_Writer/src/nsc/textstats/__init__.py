"""确定性文本统计（T-27 / ADR-0011）：纯函数、零业务参数、零 LLM、零 IO。

被 `nsc.checker.registry` 薄注册进 assert 白名单；阈值全部在 spec/checks/prose/。
"""

from .stats import (
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

__all__ = [
    "chapter_ngram_repeats",
    "density_exceeds",
    "hanzi_ngrams",
    "join_text",
    "long_paras",
    "max_consecutive_char_lines",
    "max_word_count",
    "para_cv",
    "same_prefix_runs",
    "sent_cv",
    "split_paragraphs",
    "split_sentences",
]
