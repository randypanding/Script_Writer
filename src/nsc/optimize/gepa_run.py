"""GEPA 运行编排（D13 3 档）。

分趟优化 + 教师强制（原则 5）：
    nsc optimize --pass p3_beatsheet --auto light
会构造一个只含 p3 的 dspy.Module，输入直接取黄金 IR 的 p0-p2 产物。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

PassName = Literal["p1_bible", "p2_arc", "p3_beatsheet", "p4_scene", "p5_dialogue", "p6_prose"]

# 优化顺序（先结构后文字：结构错了优化台词是浪费）
OPTIMIZE_ORDER: tuple[PassName, ...] = ("p3_beatsheet", "p2_arc", "p5_dialogue", "p6_prose", "p4_scene", "p1_bible")


def run(
    pass_name: PassName,
    *,
    auto: Literal["light", "medium", "heavy"] = "light",
    reflection_model_tier: str = "tier_reflect",
    out_dir: Path = Path("prompts"),
    max_cost_usd: float = 20.0,
) -> None:
    """
    实现要点（agent 必读）：
      1. trainset / valset 来自 eval/datasets/<pass_name>_{train,val}.jsonl，
         由 `nsc eval build-dataset` 从 cases 生成。**train/val 必须按 case 切分，不能按节点切分**
         （同一个项目的不同集出现在两侧 = 泄漏）。
      2. metric = make_metric(split="train") 用于 trainset；
         GEPA 用 valset 追踪 Pareto 分数 → 那里必须用 make_metric(split="val")。
         dspy.GEPA 只接一个 metric，因此实现方式：metric 内部按 gold.meta["split"] 分流。
      3. reflection_lm 必须是强模型（config/models.yaml::tier_reflect）；student 用该 pass 的 tier。
      4. track_stats=True，log_dir=out/gepa/<pass>/<ts>，把 detailed_results 存档（可审计）。
      5. 产出：compiled program 的 instruction 写入
         prompts/<pass_name>.json = {
           "instruction": "...", "_meta": {"generated_by":"gepa", "run_id":..., "spec_sha":...,
           "seed_sig_hash":..., "content_hash": sha256(instruction), "score_before":..., "score_after":...,
           "valset_size":..., "cost_usd":...}}
         `content_hash` 是 CI 检测手改的依据（nsc.guards.prompts_untouched）。
      6. **回归闸**：score_after 必须 > score_before + 0.02，且在 holdout 上其他 pass 的分数不下降；
         否则不写入 prompts/，只写 out/gepa/rejected/。
      7. 成本上限：超过 max_cost_usd 立即停止并保存中间结果。

    TODO(agent, T-13)
    """
    raise NotImplementedError("T-13")