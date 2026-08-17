"""判官引擎（T-08b）：rubric + anchors → prompt → LLM → 判定。

判官是可优化产物（D8）：锚例在 spec/rubrics/anchors/（A3 资产），指令种子在本模块内，
优化后由 `nsc optimize` 写入 prompts/judge_*.json。所有 LLM 调用必须经
models.ModelRouter（AGENTS.md §2 唯一出口）。绝对分仅用于报告与趋势，门禁用成对（D6/D8）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nsc.runtime.models import ModelRouter

_SEED_PAIRWISE = """你是短视频营销短剧的剧本评审。成对比较 A、B 两段文本，判断哪个更符合维度「{dimension}」。

定义：{question}
正面信号：{positive}
负面信号：{negative}

参考锚例（锚定尺度，score 越高越好）：
{anchors}

规则：
- 只依据给定维度判定，不比较其他方面。
- 必须引用 A 或 B 的具体原文作为证据，否则该次判定无效（invalid=true）。
- winner 只能是 "a" 或 "b"（按本对话给的顺序）；margin=1|2|3（1=略好，3=明显更好）。
- 若两段在同一水平，winner="tie"，margin=0。
- 另从三个视角对你更偏好的那一版各写一句注记（不打分，不影响上面的判定）：
  编辑（prose 工艺、声音一致性）、类型读者（节奏、钩子、翻页欲）、普通读者（情绪是否诚实、像不像真人反应，不用行话术语）。
- 若三视角注记对同一文本出现方向相反的判断（一处明显好、另一处明显差），perspective_disagreement=true。
- 只输出一个 JSON 对象，不要多余文字。

JSON 格式：{{"winner": "a|b|tie", "margin": 0|1|2|3, "rationale": "…", "cited_spans": ["原文片段"], "invalid": false, "perspectives": {{"editor": {{"note": "…"}}, "genre_reader": {{"note": "…"}}, "lay_reader": {{"note": "…"}}}}, "perspective_disagreement": false}}
"""

_SEED_ABSOLUTE = """你是短视频营销短剧的剧本评审。按维度「{dimension}」给下面文本打 1–5 分（1=最差，5=最好，允许 0.5）。

定义：{question}
正面信号：{positive}
负面信号：{negative}

参考锚例（锚定尺度）：
{anchors}

规则：
- 必须引用具体原文作为证据，否则该次判定无效（invalid=true）。
- 另从三个视角对文本各写一句注记（不打分，不影响上面的打分）：
  编辑（prose 工艺、声音一致性）、类型读者（节奏、钩子、翻页欲）、普通读者（情绪是否诚实、像不像真人反应，不用行话术语）。
- 若三视角注记对同一文本出现方向相反的判断（一处明显好、另一处明显差），perspective_disagreement=true。
- 只输出一个 JSON 对象，不要多余文字。

JSON 格式：{{"score": 3.0, "rationale": "…", "cited_spans": ["原文片段"], "invalid": false, "perspectives": {{"editor": {{"note": "…"}}, "genre_reader": {{"note": "…"}}, "lay_reader": {{"note": "…"}}}}, "perspective_disagreement": false}}
"""


@dataclass(slots=True)
class JudgeDecision:
    winner: str = "tie"  # 'a' | 'b' | 'tie'
    margin: int = 0
    rationale: str = ""
    cited_spans: list[str] = field(default_factory=list)
    invalid: bool = False
    # 三视角注记（ADR-0014）：仅随结果透传持久化，不参与归并/聚合。
    perspectives: dict[str, Any] = field(default_factory=dict)
    perspective_disagreement: bool = False


@dataclass(slots=True)
class JudgeScore:
    score: float = 3.0
    rationale: str = ""
    cited_spans: list[str] = field(default_factory=list)
    invalid: bool = False
    # 三视角注记（ADR-0014）：仅随结果透传持久化，不影响分数聚合。
    perspectives: dict[str, Any] = field(default_factory=dict)
    perspective_disagreement: bool = False


def load_rubric(path: str | Path = "spec/rubrics/rubric_v1.yaml") -> dict[str, Any]:
    """加载 rubric：dimensions 以 id 索引。"""
    data = yaml.safe_load(Path(path).read_text("utf-8")) or {}
    return {
        "scale": data.get("scale", {}),
        "dimensions": {d["id"]: d for d in data.get("dimensions", [])},
        "aggregate": data.get("aggregate", {}),
    }


def load_anchors(
    dimension: str, anchor_dir: str | Path = "spec/rubrics/anchors"
) -> list[dict[str, Any]]:
    p = Path(anchor_dir) / f"{dimension}.yaml"
    if not p.exists():
        return []
    return (yaml.safe_load(p.read_text("utf-8")) or {}).get("anchors", [])


def _extract_json(raw: str) -> Any:
    """容错提取 JSON 对象：平衡括号扫描（兼容推理内容夹带），见 runtime/json_extract。"""
    from nsc.runtime.json_extract import extract_json

    return extract_json(raw)


def _parse_perspectives(obj: dict[str, Any]) -> dict[str, Any]:
    """防御式解析三视角注记（ADR-0014）：缺省/类型异常 → 空 dict，不判 invalid。"""
    raw = obj.get("perspectives")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("editor", "genre_reader", "lay_reader"):
        v = raw.get(key)
        if isinstance(v, dict):
            note = str(v.get("note", "")).strip()
        elif isinstance(v, str):
            note = v.strip()  # 兼容 LLM 直接给字符串
        else:
            continue
        if note:
            out[key] = {"note": note}
    return out


def parse_pairwise(raw: str) -> JudgeDecision:
    obj = _extract_json(raw)
    if not isinstance(obj, dict):
        return JudgeDecision(invalid=True, rationale="无法解析判定输出")
    winner = str(obj.get("winner", "tie")).strip().lower()
    if winner not in ("a", "b", "tie"):
        return JudgeDecision(invalid=True, rationale=f"非法 winner：{obj.get('winner')!r}")
    try:
        margin = int(obj.get("margin", 0))
    except (TypeError, ValueError):
        margin = 0
    if winner != "tie" and margin not in (1, 2, 3):
        margin = 1
    spans = [str(s).strip() for s in (obj.get("cited_spans") or []) if str(s).strip()]
    return JudgeDecision(
        winner=winner,
        margin=margin,
        rationale=str(obj.get("rationale", "")),
        cited_spans=spans,
        invalid=bool(obj.get("invalid")) or not spans,
        perspectives=_parse_perspectives(obj),
        perspective_disagreement=bool(obj.get("perspective_disagreement", False)),
    )


def parse_absolute(raw: str) -> JudgeScore:
    obj = _extract_json(raw)
    if not isinstance(obj, dict):
        return JudgeScore(invalid=True, rationale="无法解析评分输出")
    try:
        score = float(obj.get("score", 3.0))
    except (TypeError, ValueError):
        score = 3.0
    spans = [str(s).strip() for s in (obj.get("cited_spans") or []) if str(s).strip()]
    return JudgeScore(
        score=min(max(score, 1.0), 5.0),
        rationale=str(obj.get("rationale", "")),
        cited_spans=spans,
        invalid=bool(obj.get("invalid")) or not spans,
        perspectives=_parse_perspectives(obj),
        perspective_disagreement=bool(obj.get("perspective_disagreement", False)),
    )


def _orig_winner(d: JudgeDecision, first_is_orig_a: bool) -> str:
    """把某次调用的 winner 映射回原始文本（调用 2 的 A 位是原始 B）。"""
    if d.winner == "tie":
        return "tie"
    if d.winner == "a":
        return "a" if first_is_orig_a else "b"
    return "b" if first_is_orig_a else "a"


def merge_pairwise(call1: JudgeDecision, call2: JudgeDecision) -> JudgeDecision:
    """成对协议 §3：两次结论相反 → tie；仅一次 invalid → 退回有效那次；全 invalid → invalid。

    三视角注记（ADR-0014）不参与归并：仅透传（取首个非空一侧），聚合逻辑不变。
    """
    merged = _merge_verdict(call1, call2)
    merged.perspectives = call1.perspectives or call2.perspectives
    merged.perspective_disagreement = call1.perspective_disagreement or (
        call2.perspective_disagreement
    )
    return merged


def _merge_verdict(call1: JudgeDecision, call2: JudgeDecision) -> JudgeDecision:
    """归并主体：winner/margin/invalid 的既有确定性逻辑（不动）。"""
    if call1.invalid and call2.invalid:
        return JudgeDecision(winner="tie", invalid=True, rationale="两次调用均无效")
    w1 = _orig_winner(call1, True)
    w2 = _orig_winner(call2, False) if not call2.invalid else None
    if w1 == "tie":
        return JudgeDecision(winner="tie", rationale=call1.rationale, cited_spans=call1.cited_spans)
    if w2 is None:
        return JudgeDecision(
            winner=w1,
            margin=call1.margin,
            rationale=call1.rationale,
            cited_spans=call1.cited_spans,
        )
    if w2 == "tie":
        return JudgeDecision(winner="tie", rationale=call2.rationale, cited_spans=call2.cited_spans)
    if w1 != w2:
        return JudgeDecision(winner="tie", rationale=f"两次结论相反（{w1} vs {w2}）")
    return JudgeDecision(
        winner=w1,
        margin=call1.margin,
        rationale=call1.rationale,
        cited_spans=call1.cited_spans,
    )


class RubricJudge:
    """一次评测会话内的判官。judge_ver 写入 provenance（judge_scores.judge_ver）。"""

    def __init__(
        self,
        router: ModelRouter | None = None,
        *,
        judge_ver: str = "1.0.0",
        rubric_path: str | Path = "spec/rubrics/rubric_v1.yaml",
        anchor_dir: str | Path = "spec/rubrics/anchors",
        tier: str = "tier_judge",
    ) -> None:
        self.router = router or ModelRouter()
        self.judge_ver = judge_ver
        self.tier = tier
        self.rubric = load_rubric(rubric_path)
        self.anchor_dir = Path(anchor_dir)
        self.cost_usd = 0.0  # 会话累计成本（供 L1/校准成本上限）

    def dimension(self, dim_id: str) -> dict[str, Any]:
        try:
            return self.rubric["dimensions"][dim_id]
        except KeyError as e:
            raise KeyError(f"rubric 没有维度 {dim_id}") from e

    def _anchors_text(self, dim_id: str) -> str:
        anchors = load_anchors(dim_id, self.anchor_dir)
        return (
            "\n".join(
                f"- {a.get('score')} 分｜{a.get('label')}：\n{a.get('sample', '').strip()}"
                for a in anchors
            )
            or "（无锚例）"
        )

    def _pairwise_messages(self, dim_id: str, context: str, a: str, b: str) -> list[dict[str, str]]:
        dim = self.dimension(dim_id)
        system = _SEED_PAIRWISE.format(
            dimension=dim["name"],
            question=dim["question"],
            positive="、".join(dim.get("positive_signals", [])),
            negative="、".join(dim.get("negative_signals", [])),
            anchors=self._anchors_text(dim_id),
        )
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"上下文：\n{context}\n\n【A】\n{a}\n\n【B】\n{b}",
            },
        ]

    def _absolute_messages(self, dim_id: str, context: str, text: str) -> list[dict[str, str]]:
        dim = self.dimension(dim_id)
        system = _SEED_ABSOLUTE.format(
            dimension=dim["name"],
            question=dim["question"],
            positive="、".join(dim.get("positive_signals", [])),
            negative="、".join(dim.get("negative_signals", [])),
            anchors=self._anchors_text(dim_id),
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": f"上下文：\n{context}\n\n文本：\n{text}"},
        ]

    def call_pairwise(
        self, dim_id: str, context: str, a: str, b: str, *, seed: int = 1
    ) -> JudgeDecision:
        """单次调用（顺序 a,b）。未引用 span → 重试一次；再次无效 → invalid（协议 §3）。"""
        for attempt in (seed, seed + 100):
            try:
                raw = self.router.complete(
                    self.tier,
                    self._pairwise_messages(dim_id, context, a, b),
                    json_mode=True,
                    seed=attempt,
                )
            except Exception:
                return JudgeDecision(invalid=True, rationale="LLM 调用失败")
            self.cost_usd += raw.cost_usd
            d = parse_pairwise(raw.text)
            if not d.invalid and d.cited_spans:
                return d
        return JudgeDecision(winner="tie", invalid=True, rationale="两次均未引用 span")

    def judge_pair(
        self, dim_id: str, context: str, a: str, b: str, *, seed: int = 1
    ) -> tuple[JudgeDecision, JudgeDecision, JudgeDecision]:
        """成对协议 §3：正向调用 + 反向调用（swap）→ 归并。返回 (call1, call2, resolved)。"""
        call1 = self.call_pairwise(dim_id, context, a, b, seed=seed)
        call2 = self.call_pairwise(dim_id, context, b, a, seed=seed + 1)
        return call1, call2, merge_pairwise(call1, call2)

    def judge_absolute(self, dim_id: str, context: str, text: str, *, seed: int = 1) -> JudgeScore:
        for attempt in (seed, seed + 100):
            try:
                raw = self.router.complete(
                    self.tier,
                    self._absolute_messages(dim_id, context, text),
                    json_mode=True,
                    seed=attempt,
                )
            except Exception:
                return JudgeScore(invalid=True, rationale="LLM 调用失败")
            self.cost_usd += raw.cost_usd
            s = parse_absolute(raw.text)
            if not s.invalid and s.cited_spans:
                return s
        return JudgeScore(invalid=True, rationale="两次均未引用 span")
