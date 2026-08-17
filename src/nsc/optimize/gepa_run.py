"""GEPA 运行编排（D13 3 档）。

分趟优化 + 教师强制（原则 5）：
    nsc optimize --pass p3_beatsheet --auto light
会构造一个只含 p3 的 dspy.Module，输入直接取黄金 IR 的 p0-p2 产物。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from nsc.optimize.plateau import should_stop

PassName = Literal["p1_bible", "p2_arc", "p3_beatsheet", "p4_scene", "p5_dialogue", "p6_prose"]

# 优化顺序（先结构后文字：结构错了优化台词是浪费）
OPTIMIZE_ORDER: tuple[PassName, ...] = (
    "p3_beatsheet",
    "p2_arc",
    "p5_dialogue",
    "p6_prose",
    "p4_scene",
    "p1_bible",
)


#: 回归闸阈值：score_after 必须 > score_before + REGRESSION_MARGIN 才写入 prompts/。
REGRESSION_MARGIN = 0.02


def _content_hash(instruction: str) -> str:
    import hashlib

    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()


def run(
    pass_name: PassName,
    *,
    auto: Literal["light", "medium", "heavy"] = "light",
    reflection_model_tier: str = "tier_reflect",
    out_dir: Path = Path("prompts"),
    max_cost_usd: float = 20.0,
    db_path: str | Path = "cases/cases.db",
    dataset_dir: str | Path = "eval/datasets",
    router: Any = None,
    gepa_runner: Any = None,
    judge: Any = None,
    versions: dict[str, str] | None = None,
    rejected_dir: str | Path = "out/gepa/rejected",
    log_root: str | Path = "out/gepa",
) -> dict[str, Any]:
    """跑一趟 GEPA 优化并产出可审计结果。

    返回 {"written": bool, "path"?, "reason", "score_before", "score_after", "cost_usd"}。
    `gepa_runner` 可注入（测试桩）；缺省走 dspy_gepa_runner（真实 GEPA，需 API key）。
    `judge` 可注入 T-08b 判官（缺省 None → metric 的 rubric 分量取中性 0.5）。
    """
    import json
    from datetime import UTC, datetime

    from nsc.optimize.build_dataset import build_dataset
    from nsc.optimize.gepa_integration import dspy_gepa_runner, make_judge_scorer

    versions = versions or {}
    # 1. 数据集（按 case 切分防泄漏，build_dataset 内保证）
    ds = build_dataset(db_path, pass_name, out_dir=dataset_dir)
    trainset = _load_jsonl(ds["train_path"])
    valset = _load_jsonl(ds["val_path"])
    if not trainset:
        return {
            "written": False,
            "reason": "trainset 为空（无已确认 revision_pairs）",
            "score_before": 0.0,
            "score_after": 0.0,
            "cost_usd": 0.0,
            "cycles": 0,
            "plateau_reason": "",
        }

    # 2. metric：按 gold.split 分流（train 暴露人类修订，val 只用 checker+判官）
    scorer = make_judge_scorer(judge) if judge is not None else None
    metric = _make_split_metric(scorer)

    # 3. 跑 GEPA（注入桩或真实 runner）：T-41 plateau 迭代循环——每轮以上轮最优指令为
    #    种子，归一化指标 append 进 history；Δ<0.03@≥3 轮或 6 轮上限即停（原因透传）。
    runner = gepa_runner or dspy_gepa_runner
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    log_dir = str(Path(log_root) / pass_name / ts)
    seed_instruction = _seed_instruction(pass_name)

    history: list[float] = []
    best: dict[str, Any] = {}
    total_cost = 0.0
    plateau_reason = ""
    for _cycle in range(6):  # 上限 = should_stop 默认 max_cycles
        result = runner(
            pass_name=pass_name,
            auto=auto,
            trainset=trainset,
            valset=valset,
            metric=metric,
            reflection_tier=reflection_model_tier,
            seed_instruction=seed_instruction,
            router=router,
            log_dir=log_dir,
            max_cost_usd=max_cost_usd,
        )
        score = min(max(float(result.get("score_after", 0.0)), 0.0), 1.0)  # 归一化到 [0,1]
        history.append(score)
        total_cost += float(result.get("cost_usd", 0.0))
        if not best or score > float(best.get("score_after", 0.0)):
            best = result
        seed_instruction = str(result.get("instruction", "")) or seed_instruction
        stop, plateau_reason = should_stop(history)
        if stop:
            break

    result = best
    score_before = float(result.get("score_before", 0.0))
    score_after = float(result.get("score_after", 0.0))
    cost = total_cost
    instruction = str(result.get("instruction", ""))

    # 4. 成本上限：超了不写入，保存中间结果
    if cost > max_cost_usd:
        _dump_rejected(
            rejected_dir, pass_name, ts, result, reason=f"成本 {cost} 超上限 {max_cost_usd}"
        )
        return {
            "written": False,
            "reason": f"成本超限（{cost} > {max_cost_usd}）",
            "score_before": score_before,
            "score_after": score_after,
            "cost_usd": cost,
            "cycles": len(history),
            "plateau_reason": plateau_reason,
        }

    # 5. 回归闸：score_after 必须 > score_before + margin，否则不写入 prompts/
    if score_after <= score_before + REGRESSION_MARGIN:
        _dump_rejected(
            rejected_dir,
            pass_name,
            ts,
            result,
            reason=f"回归闸：{score_after} 未超 {score_before}+{REGRESSION_MARGIN}",
        )
        return {
            "written": False,
            "reason": f"回归闸未过（after {score_after} ≤ before {score_before}+{REGRESSION_MARGIN}）",
            "score_before": score_before,
            "score_after": score_after,
            "cost_usd": cost,
            "cycles": len(history),
            "plateau_reason": plateau_reason,
        }

    # 6. 写入 prompts/<pass>.json（含 content_hash，CI 检测手改的依据）
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "instructions": instruction,
        "_meta": {
            "generated_by": "gepa",
            "pass_name": pass_name,
            "auto": auto,
            "spec_sha": versions.get("spec_sha", ""),
            "promptset_ver": versions.get("promptset_ver", ""),
            "content_hash": _content_hash(instruction),
            "score_before": score_before,
            "score_after": score_after,
            "valset_size": len(valset),
            "cost_usd": cost,
            "created_at": ts,
            "cycles": len(history),
            "plateau_reason": plateau_reason,
        },
    }
    path = out_dir / f"{pass_name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return {
        "written": True,
        "path": str(path),
        "reason": "ok",
        "score_before": score_before,
        "score_after": score_after,
        "cost_usd": cost,
        "cycles": len(history),
        "plateau_reason": plateau_reason,
    }


def _make_split_metric(scorer: Any) -> Any:
    """构造按 gold['split'] 分流的 metric（dspy.GEPA 只接一个 metric）。"""
    from nsc.optimize.gepa_metric import make_metric

    train_metric = make_metric(split="train", judge_scorer=scorer)
    val_metric = make_metric(split="val", judge_scorer=scorer)

    def metric(
        gold: Any, pred: Any, trace: Any = None, pred_name: Any = None, pred_trace: Any = None
    ) -> Any:
        split = "train"
        if isinstance(gold, dict):
            split = gold.get("split", "train")
        else:
            split = getattr(gold, "split", None) or (
                gold.get("split") if hasattr(gold, "get") else "train"
            )
        m = val_metric if split == "val" else train_metric
        return m(gold, pred, trace=trace, pred_name=pred_name, pred_trace=pred_trace)

    return metric


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    import json

    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]


def _seed_instruction(pass_name: str) -> str:
    from nsc.optimize.gepa_integration import _SIGNATURE_BY_PASS
    from spec.passes import signatures

    sig = getattr(signatures, _SIGNATURE_BY_PASS[pass_name], None)
    return (sig.__doc__ or "").strip() if sig else ""


def _dump_rejected(
    rejected_dir: str | Path, pass_name: str, ts: str, result: Any, reason: str
) -> None:
    import json

    d = Path(rejected_dir) / pass_name
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "reason": reason,
        "ts": ts,
        **{k: v for k, v in result.items() if k != "detailed_results"},
    }
    (d / f"{ts}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
