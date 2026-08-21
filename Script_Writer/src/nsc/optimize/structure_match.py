"""GEPA metric 的 structure_match 分量（确定性、无 LLM）。

度量预测产物与黄金 IR（教师强制下的标准答案）的结构一致度。
逐 pass 的定义见 gepa_metric.py::_compute_parts 的注释（资产级设计意图）。
本文件只实现可复现的纯函数；不得引入任何 LLM 调用（AGENTS.md §2）。

输入约定：gold/pred 的相关字段是 dspy.Example / dspy.Prediction 上的属性，
可能是已解析的 list/dict，也可能是 JSON 字符串（Signature 的输出字段都是 str）。
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Any


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _text_sim(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _seq_edit_sim(a: list[Any], b: list[Any]) -> float:
    """两个序列的归一化编辑相似度（1 - dist/max_len），元素按 str 比较。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    sa = [str(x) for x in a]
    sb = [str(x) for x in b]
    return SequenceMatcher(None, sa, sb).ratio()


def _jaccard(a: set[Any], b: set[Any]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _kl(p: list[float], q: list[float]) -> float:
    """两个分布的对称 KL（已平滑）。越小越像；用于长度分布。"""
    import math

    n = max(len(p), len(q))
    p = (p + [0.0] * n)[:n]
    q = (q + [0.0] * n)[:n]
    eps = 1e-9
    sp = sum(p) or 1.0
    sq = sum(q) or 1.0
    p = [(x / sp) + eps for x in p]
    q = [(x / sq) + eps for x in q]
    kl_pq = sum(pi * math.log(pi / qi) for pi, qi in zip(p, q, strict=True))
    kl_qp = sum(qi * math.log(qi / pi) for pi, qi in zip(p, q, strict=True))
    return (kl_pq + kl_qp) / 2


def _hist(values: list[float], bins: int = 8) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi <= lo:
        out = [0.0] * bins
        out[0] = float(len(values))
        return out
    width = (hi - lo) / bins
    out = [0.0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        out[idx] += 1.0
    return out


# ---------------------------------------------------------------- 逐 pass


def match_p3_beatsheet(gold: dict[str, Any], pred: dict[str, Any]) -> float:
    """Beat 序列结构一致度。

    - beat_kind 序列编辑相似度 × 0.5
    - hook 位置一致 × 0.15
    - brand_moment 下标集合 Jaccard × 0.2
    - setup_payoff 数量匹配 × 0.15
    """
    g_beats = _as_list(gold.get("beats_json"))
    p_beats = _as_list(pred.get("beats_json"))
    gk = [str(b.get("beat_kind", "")) for b in g_beats if isinstance(b, dict)]
    pk = [str(b.get("beat_kind", "")) for b in p_beats if isinstance(b, dict)]

    seq_sim = _seq_edit_sim(gk, pk)

    def hook_pos(kinds: list[str]) -> int:
        return kinds.index("hook") if "hook" in kinds else -1

    hook_match = 1.0 if hook_pos(gk) == hook_pos(pk) else 0.0

    g_bm = {i for i, k in enumerate(gk) if k == "brand_moment"}
    p_bm = {i for i, k in enumerate(pk) if k == "brand_moment"}
    bm_jac = _jaccard(g_bm, p_bm)

    g_sp = len(_as_list(gold.get("setup_payoffs_json")))
    p_sp = len(_as_list(pred.get("setup_payoffs_json")))
    sp_match = (
        1.0 if g_sp == p_sp else (min(g_sp, p_sp) / max(g_sp, p_sp) if max(g_sp, p_sp) else 1.0)
    )

    return 0.5 * seq_sim + 0.15 * hook_match + 0.2 * bm_jac + 0.15 * sp_match


def match_p5_dialogue(gold: dict[str, Any], pred: dict[str, Any]) -> float:
    """对白结构一致度。

    - 说话人序列一致度 × 0.4
    - 每条长度分布的对称 KL → 相似度 × 0.3
    - 必提台词命中率 × 0.3
    """
    g_lines = _as_list(gold.get("lines_json"))
    p_lines = _as_list(pred.get("lines_json"))
    g_spk = [str(ln.get("character_id", "")) for ln in g_lines if isinstance(ln, dict)]
    p_spk = [str(ln.get("character_id", "")) for ln in p_lines if isinstance(ln, dict)]
    speaker_sim = _seq_edit_sim(g_spk, p_spk)

    g_len = [float(len(str(ln.get("text", "")))) for ln in g_lines if isinstance(ln, dict)]
    p_len = [float(len(str(ln.get("text", "")))) for ln in p_lines if isinstance(ln, dict)]
    kl = _kl(_hist(g_len), _hist(p_len))
    len_sim = 1.0 / (1.0 + kl)

    g_must = [
        str(ln.get("text", ""))
        for ln in g_lines
        if isinstance(ln, dict) and ln.get("is_brand_line")
    ]
    p_texts = [str(ln.get("text", "")) for ln in p_lines if isinstance(ln, dict)]
    if g_must:
        hits = sum(1 for m in g_must if any(_text_sim(m, t) >= 0.9 for t in p_texts))
        must_sim = hits / len(g_must)
    else:
        must_sim = 1.0

    return 0.4 * speaker_sim + 0.3 * len_sim + 0.3 * must_sim


def match_p6_prose(gold: dict[str, Any], pred: dict[str, Any]) -> float:
    """小说章节结构一致度。

    - anchor_map 的 beat 覆盖率一致 × 0.5
    - 段落数比例 × 0.2
    - 对白相似度均值 × 0.3
    """
    g_anchor = _as_list(gold.get("anchor_map_json"))
    p_anchor = _as_list(pred.get("anchor_map_json"))
    g_beats = {str(a.get("beat_id")) for a in g_anchor if isinstance(a, dict)}
    p_beats = {str(a.get("beat_id")) for a in p_anchor if isinstance(a, dict)}
    anchor_sim = _jaccard(g_beats, p_beats)

    g_paras = _as_list(gold.get("paragraphs_json"))
    p_paras = _as_list(pred.get("paragraphs_json"))
    if g_paras and p_paras:
        para_ratio = min(len(g_paras), len(p_paras)) / max(len(g_paras), len(p_paras))
    else:
        para_ratio = 1.0 if not g_paras and not p_paras else 0.0

    g_text = "\n".join(str(x) for x in g_paras)
    p_text = "\n".join(str(x) for x in p_paras)
    text_sim = _text_sim(g_text, p_text)

    return 0.5 * anchor_sim + 0.2 * para_ratio + 0.3 * text_sim


def match_generic(gold: dict[str, Any], pred: dict[str, Any]) -> float:
    """其余 pass 的回退：共有输出字段的文本相似度均值。"""
    keys = [k for k in gold if not k.startswith("_") and k in pred]
    if not keys:
        return 0.0
    sims = []
    for k in keys:
        gv, pv = gold.get(k), pred.get(k)
        if isinstance(gv, (list, dict)) or isinstance(pv, (list, dict)):
            gv = json.dumps(gv, ensure_ascii=False, sort_keys=True)
            pv = json.dumps(pv, ensure_ascii=False, sort_keys=True)
        sims.append(_text_sim(str(gv), str(pv)))
    return sum(sims) / len(sims) if sims else 0.0


_MATCHERS = {
    "p3_beatsheet": match_p3_beatsheet,
    "p5_dialogue": match_p5_dialogue,
    "p6_prose": match_p6_prose,
}


def structure_match(pass_name: str, gold: dict[str, Any], pred: dict[str, Any]) -> float:
    """按 pass 路由到对应的一致度函数，未知 pass 走通用回退。结果裁剪到 [0,1]。"""
    fn = _MATCHERS.get(pass_name, match_generic)
    score = fn(gold, pred)
    return max(0.0, min(1.0, score))
