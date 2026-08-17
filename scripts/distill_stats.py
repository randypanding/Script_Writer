# -*- coding: utf-8 -*-
"""确定性风格统计：把语料炼成可复现的数字，映射到 NSC 的 Pass/规则旋钮。无 LLM。

用法：
    python -m scripts.distill_stats --corpus /tmp/distill/raw/example.jsonl \
        --corpus /tmp/distill/raw/pb_0.part ... [--out spec/distill/webnovel_avg.yaml]

每个 --corpus 文件为 jsonl，每行 {title, chapter, text}。
产出统计 priors 到 --out，或打印。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics

CN_QUOTE_OPEN = ["“", "「"]
CN_QUOTE_CLOSE = ["”", "」"]


def load(corpus_paths: list[str]) -> list[tuple[str, str]]:
    """返回 (title, text)，跳过截断坏行。"""
    out: list[tuple[str, str]] = []
    for p in corpus_paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = r.get("text", "")
                if len(text) >= 40:
                    out.append((r.get("title", "?"), text))
    return out


def utterances(text: str) -> tuple[list[str], int]:
    """返回 (对白列表, 对白总字符)。对白=中文引号内。"""
    pairs = list(re.finditer(r"[“「](.*?)[”」]", text, re.S))
    utts = [m.group(1).strip() for m in pairs if 0 < len(m.group(1).strip()) <= 300]
    qchars = sum(len(m.group(0)) for m in pairs)
    return utts, qchars


def sentences(text: str) -> list[str]:
    return [x for x in (y.strip() for y in re.split(r"[。！？；…!?;]", text)) if x]


def pct(vals: list[int], q: int) -> int:
    if not vals:
        return 0
    vals = sorted(vals)
    idx = int(q / 100 * (len(vals) - 1))
    return int(vals[idx])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()

    data = load(args.corpus)
    n = len(data)
    utt_lens: list[int] = []
    sent_lens: list[int] = []
    sent_per_para: list[int] = []
    chap_sizes: list[int] = []
    first_offset: list[int] = []
    n_first_dial = n_end_dial = n_end_q = 0
    dial_chars = narr_chars = 0

    for _t, c in data:
        c = " ".join(c.split())
        chap_sizes.append(len(c))
        utts, qchars = utterances(c)
        dial_chars += qchars
        narr_chars += len(c) - qchars
        utt_lens.extend(len(u) for u in utts)
        sent_lens.extend(len(s) for s in sentences(c))
        sent_per_para.append(len(sentences(c)))

        if any(o in c[:60] for o in CN_QUOTE_OPEN):
            n_first_dial += 1
        tail = c[-80:]
        if any(q in tail for q in CN_QUOTE_CLOSE):
            n_end_dial += 1
            if "？" in tail[-6:]:
                n_end_q += 1
        m = re.search(r"[“「]", c)
        first_offset.append(m.start() if m else -1)

    res = {
        "source": "webnovel-chinese(qqceqqq, apache-2.0) 抽样",
        "evidence": {"chapters": n},
        "opening": {
            "first_line_is_dialogue_ratio": round(n_first_dial / n, 3),
            "ending_line_is_dialogue_ratio": round(n_end_dial / n, 3),
            "ending_question_ratio": round(n_end_q / n, 3),
            "median_first_utterance_offset_chars": pct([x for x in first_offset if x >= 0], 50),
        },
        "dialogue": {
            "chars_ratio": round(dial_chars / max(1, dial_chars + narr_chars), 3),
            "utterance_len_chars": {
                "p25": pct(utt_lens, 25),
                "p50": pct(utt_lens, 50),
                "p85": pct(utt_lens, 85),
                "p98": pct(utt_lens, 98),
            },
        },
        "narration": {
            "sentence_len_chars": {
                "p25": pct(sent_lens, 25),
                "p50": pct(sent_lens, 50),
                "p90": pct(sent_lens, 90),
            },
        },
        "chapter": {"median_chars": pct(chap_sizes, 50)},
    }

    out = json.dumps(res, ensure_ascii=False, indent=2)
    if args.out:
        import yaml

        with open(args.out, "w", encoding="utf-8") as f:
            yaml.safe_dump(res, f, allow_unicode=True, sort_keys=False)
        print(f"written {args.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()