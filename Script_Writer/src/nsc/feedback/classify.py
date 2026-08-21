"""EditClassify（T-11）：对 EditRecord 做语义判定并回填 dimension/verdict/severity/rationale_nl。

判定知识全部在 `spec/feedback/edit_classify_rubric.yaml`（ADR-0008）；
本模块只做编排：拼 prompt → 经 ModelRouter 路由 → 校验输出合法性 → 写 provenance。
禁止把维度定义/判定示例写进本文件（AGENTS.md §2）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

import yaml

from nsc.feedback.align import EditRecord
from nsc.runtime.provenance import RunRecord, RunsStore

RUBRIC_PATH = Path("spec/feedback/edit_classify_rubric.yaml")


class ClassifyError(RuntimeError):
    """分类输出不合法。消息写成可直接喂给挖掘/GEPA 的诊断句。"""


class _Router(Protocol):
    """ModelRouter 的最小协议（测试用 stub 注入，无需真 LLM）。"""

    def complete(
        self,
        tier: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        seed: int | None = None,
    ) -> Any: ...


def load_rubric(path: str | Path = RUBRIC_PATH) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text("utf-8"))


class EditClassify:
    """批量语义分类器。一次 LLM 调用判完一批记录，满足 ≤60s 验收。"""

    def __init__(
        self,
        router: _Router,
        *,
        rubric_path: str | Path = RUBRIC_PATH,
        store: RunsStore | None = None,
        versions: dict[str, str] | None = None,
    ) -> None:
        self.router = router
        self.rubric = load_rubric(rubric_path)
        self.store = store
        self.versions = versions or {}

    @property
    def dimensions(self) -> list[str]:
        return list(self.rubric["dimensions"])

    @property
    def verdicts(self) -> list[str]:
        return list(self.rubric["verdicts"])

    # ---------------------------------------------------------------- prompt
    def _rubric_text(self) -> str:
        r = self.rubric
        parts = [str(r["task"]).strip(), "\n## 维度定义"]
        for name, d in r["dimensions"].items():
            signals = "、".join(d.get("signals", []))
            parts.append(f"- {name}: {d['definition']}；典型信号：{signals}")
        parts.append("\n## verdict 取值")
        for name, desc in r["verdicts"].items():
            parts.append(f"- {name}: {desc}")
        parts.append("\n## severity 锚点")
        for level, desc in r["severity_anchors"].items():
            parts.append(f"- {level}: {desc}")
        shots = r.get("few_shots", [])
        if shots:
            parts.append("\n## 示例")
            for ex in shots:
                parts.append(json.dumps(ex, ensure_ascii=False))
        return "\n".join(parts)

    def _call(self, pass_name: str, contract_key: str, payload: dict[str, Any]) -> Any:
        tier = str(self.rubric.get("tier", "tier_bulk"))
        messages = [
            {"role": "system", "content": self._rubric_text()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        result = self.router.complete(tier, messages, json_mode=True)
        self._record_run(pass_name, tier, payload, result)
        try:
            data = json.loads(result.text)
        except json.JSONDecodeError as e:
            raise ClassifyError(
                f"{pass_name} 输出不是合法 JSON：{result.text[:200]!r}（模型未遵守 output contract）"
            ) from e
        if contract_key not in data:
            raise ClassifyError(f"{pass_name} 输出缺少 {contract_key!r} 键：{str(data)[:200]!r}")
        return data[contract_key]

    def _record_run(self, pass_name: str, tier: str, payload: dict[str, Any], result: Any) -> None:
        if self.store is None:
            return
        temperature = float(getattr(self.router, "tiers", {}).get(tier, {}).get("temperature", 0.0))
        input_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
        self.store.record(
            RunRecord.new(
                pass_name=pass_name,
                spec_sha=self.versions.get("spec_sha", ""),
                profile_ver=self.versions.get("profile_ver", ""),
                brand_ver=self.versions.get("brand_ver", ""),
                ruleset_ver=self.versions.get("ruleset_ver", ""),
                promptset_ver=self.versions.get("promptset_ver", ""),
                model_id=getattr(result, "model_id", ""),
                temperature=temperature,
                seed=None,
                input_hash=input_hash,
                tokens_in=getattr(result, "tokens_in", 0),
                tokens_out=getattr(result, "tokens_out", 0),
                cost_usd=getattr(result, "cost_usd", 0.0),
                wall_ms=getattr(result, "wall_ms", 0),
                langfuse_trace_id=getattr(result, "trace_id", ""),
            )
        )

    # ---------------------------------------------------------------- 八维分类
    def classify(self, records: list[EditRecord]) -> list[EditRecord]:
        """回填每条记录的 dimension/verdict/severity/rationale_nl。"""
        if not records:
            return records
        payload = {
            "records": [
                {
                    "index": i,
                    "edit_type": r.edit_type,
                    "before": r.before,
                    "after": r.after,
                    "human_comment": r.human_comment,
                    "context": "",
                }
                for i, r in enumerate(records)
            ]
        }
        items = self._call("edit_classify", "records", payload)
        if len(items) != len(records):
            raise ClassifyError(
                f"edit_classify 输出条数 {len(items)} != 输入条数 {len(records)}，"
                "模型漏判了记录（output contract 要求一一对应）"
            )
        for i, (rec, item) in enumerate(zip(records, items, strict=True)):
            rec.dimension = self._check_choice(item, "dimension", self.dimensions, i)
            rec.verdict = self._check_choice(item, "verdict", self.verdicts, i)
            rec.severity = self._check_severity(item, i)
            rec.rationale_nl = str(item.get("rationale_nl", "")).strip()
            if not rec.rationale_nl:
                raise ClassifyError(f"edit_classify 第 {i} 条 rationale_nl 为空，无法喂给规则挖掘")
        return records

    def _check_choice(self, item: dict[str, Any], key: str, allowed: list[str], i: int) -> str:
        value = str(item.get(key, "")).strip()
        if value not in allowed:
            raise ClassifyError(
                f"edit_classify 第 {i} 条 {key}={value!r} 不在合法集合 {allowed} 内"
            )
        return value

    def _check_severity(self, item: dict[str, Any], i: int) -> int:
        try:
            severity = int(item.get("severity", 0))
        except (TypeError, ValueError) as e:
            raise ClassifyError(f"edit_classify 第 {i} 条 severity 不是整数") from e
        if not 1 <= severity <= 5:
            raise ClassifyError(f"edit_classify 第 {i} 条 severity={severity} 超出 1–5 锚点范围")
        return severity

    # ---------------------------------------------------------------- 重写归并
    def judge_rewrite_pairs(self, pairs: list[dict[str, str]]) -> list[bool]:
        """低相似"完全重写"段的语义裁决：每对 {before, after} → 是否同一叙事节点。

        判据在 rubric 的 rewrite_resolution 节（资产），代码只做收发。
        """
        if not pairs:
            return []
        payload: dict[str, Any] = {
            "pairs": [
                {
                    "index": i,
                    "before": p["before"],
                    "after": p["after"],
                    "context": p.get("context", ""),
                }
                for i, p in enumerate(pairs)
            ]
        }
        rubric_note = str(self.rubric.get("rewrite_resolution", "")).strip()
        if rubric_note:
            payload["instruction"] = rubric_note
        items = self._call("edit_resolve_rewrite", "pairs", payload)
        if len(items) != len(pairs):
            raise ClassifyError(
                f"edit_resolve_rewrite 输出条数 {len(items)} != 输入条数 {len(pairs)}"
            )
        verdicts: list[bool] = []
        for i, item in enumerate(items):
            same = item.get("same_node")
            if not isinstance(same, bool):
                raise ClassifyError(f"edit_resolve_rewrite 第 {i} 条 same_node 不是布尔值")
            verdicts.append(same)
        return verdicts
