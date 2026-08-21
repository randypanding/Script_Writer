"""T-12/T-13 集成对接：把已完成的 T-08b 判官与 T-04 路由接到 GEPA metric 上。

两件事：
1. `make_judge_scorer`：把 RubricJudge（judge_absolute 返回 1–5 分）适配成
   gepa_metric 约定的 JudgeScorer（返回 {dimension: 0..1}）。这是 T-08b 与 T-12
   之间的尺度对接——判官是 1–5，metric 内部权重按 0–1 设计。
2. `dspy_gepa_runner`：经 ModelRouter（唯一 LLM 出口）驱动 dspy.GEPA 的真实运行器，
   供 gepa_run.run 在不做单元测试时调用。GEPA 内部的 student/reflection 调用都
   通过 dspy.LM 走 LiteLLM（与 ModelRouter 同源），reflection 用 tier_reflect（强模型）。
"""

from __future__ import annotations

from typing import Any

#: 判官绝对分的量程（spec/rubrics/rubric_v1.yaml::scale）。
_JUDGE_MIN = 1.0
_JUDGE_MAX = 5.0


def _to_unit(score: float) -> float:
    """1–5 → 0–1（线性），裁剪到 [0,1]。"""
    return max(0.0, min(1.0, (score - _JUDGE_MIN) / (_JUDGE_MAX - _JUDGE_MIN)))


def make_judge_scorer(judge: Any, *, context: str = "", dims: list[str] | None = None) -> Any:
    """RubricJudge → JudgeScorer（gepa_metric 的 rubric 分量）。

    对 pred 的文本逐适用维度判绝对分，归一化到 0–1。判官未就绪/全部 invalid → 返回 {}，
    由 gepa_metric 落到中性 0.5（不惩罚不奖励）。
    """

    def scorer(gold: dict[str, Any], pred: dict[str, Any]) -> dict[str, float]:
        text = _pred_text(pred)
        if not text.strip():
            return {}
        rubric = getattr(judge, "rubric", {})
        dimensions = rubric.get("dimensions", {})
        wanted = dims or list(dimensions)
        out: dict[str, float] = {}
        for dim_id in wanted:
            if dim_id not in dimensions:
                continue
            sc = judge.judge_absolute(dim_id, context, text)
            if not getattr(sc, "invalid", False):
                out[dim_id] = _to_unit(float(getattr(sc, "score", 3.0)))
        return out

    return scorer


def _pred_text(pred: dict[str, Any]) -> str:
    """从预测产物抽一段可判分文本：优先章节段落，其次台词，再次任意文本字段。"""
    import json

    for key in ("paragraphs_json", "lines_json"):
        items = pred.get(key)
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except json.JSONDecodeError:
                items = None
        if isinstance(items, list) and items:
            parts = []
            for it in items:
                if isinstance(it, dict):
                    parts.append(str(it.get("text", "")))
                else:
                    parts.append(str(it))
            return "\n".join(p for p in parts if p)
    for key in ("season_arc", "chapter_title", "normalized_brief"):
        if pred.get(key):
            return str(pred[key])
    return ""


def dspy_gepa_runner(
    *,
    pass_name: str,
    auto: str,
    trainset: list[Any],
    valset: list[Any],
    metric: Any,
    reflection_tier: str,
    seed_instruction: str,
    router: Any,
    log_dir: str,
    max_cost_usd: float,
) -> dict[str, Any]:
    """真实 GEPA 运行（生产路径）。经 dspy.GEPA + LiteLLM（与 ModelRouter 同源）。

    - reflection_lm 用 reflection_tier 指定的强模型（反思质量决定一切，SOP_GEPA §反面清单）。
    - student 用该 pass 的 tier。
    - track_stats + log_dir 存档 detailed_results（可审计）。
    返回 {"instruction", "score_before", "score_after", "cost_usd", "detailed_results"}。

    说明：本函数只在真实跑 GEPA 时被调用（需 API key），单元测试走 gepa_run 的注入桩。
    """
    import dspy

    from spec.passes import signatures

    sig = getattr(signatures, _SIGNATURE_BY_PASS[pass_name])

    class _OnePass(dspy.Module):
        def __init__(self) -> None:
            super().__init__()
            self.prog = dspy.Predict(sig)

        def forward(self, **kwargs: Any) -> Any:
            return self.prog(**kwargs)

    student_cfg = router.resolve(_student_tier(pass_name, router))
    reflect_cfg = router.resolve(reflection_tier)
    task_lm = dspy.LM(student_cfg["model"], temperature=student_cfg.get("temperature", 0.7))
    reflect_lm = dspy.LM(reflect_cfg["model"], temperature=reflect_cfg.get("temperature", 1.0))

    program = _OnePass()
    if seed_instruction:
        sig_now = program.prog.signature
        if sig_now is not None:
            program.prog.signature = sig_now.with_instructions(seed_instruction)

    with dspy.context(lm=task_lm):
        gepa = dspy.GEPA(
            metric=metric,
            auto=auto,  # type: ignore[arg-type]
            reflection_lm=reflect_lm,
            candidate_selection_strategy="pareto",
            track_stats=True,
            log_dir=log_dir,
            seed=0,
        )
        compiled = gepa.compile(program, trainset=trainset, valset=valset)

    instruction = _extract_instruction(compiled)
    detailed = getattr(gepa, "detailed_results", None)
    score_after = float(getattr(detailed, "best_score", 0.0) or 0.0) if detailed else 0.0
    score_before = float(getattr(detailed, "base_score", 0.0) or 0.0) if detailed else 0.0
    cost = float(getattr(detailed, "total_cost_usd", 0.0) or 0.0) if detailed else 0.0
    return {
        "instruction": instruction,
        "score_before": score_before,
        "score_after": score_after,
        "cost_usd": cost,
        "detailed_results": detailed,
    }


_SIGNATURE_BY_PASS = {
    "p1_bible": "Bible",
    "p2_arc": "Arc",
    "p3_beatsheet": "BeatSheet",
    "p4_scene": "SceneCards",
    "p5_dialogue": "Dialogue",
    "p6_prose": "Prose",
}


def _student_tier(pass_name: str, router: Any) -> str:
    """该 pass 的 student tier：优先 profile 路由，回退到 plan/draft 约定。"""
    plan = {"p1_bible", "p2_arc", "p3_beatsheet"}
    return "tier_plan" if pass_name in plan else "tier_draft"


def _extract_instruction(compiled: Any) -> str:
    try:
        sig = compiled.prog.signature
        return str(getattr(sig, "instructions", "") or getattr(sig, "__doc__", "") or "")
    except Exception:
        return ""
