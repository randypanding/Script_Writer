# Spec 写作规范（D2 的执行细则）

## 1. 每条规范语句必须带形态标记
在 `spec/**/*.md` 中，任何规范性语句必须以标记结尾，否则 `make spec-guard` 失败：

- `[[form:schema]]` → 已落为 Pydantic/JSON Schema。必须紧跟 `→ spec/ir/xxx.py::ClassName.field`
- `[[form:check]]`  → 已落为检查规则。必须紧跟 `→ spec/checks/xxx/RULE-ID.yaml`
- `[[form:rubric]]` → 已落为评分卡维度 + 锚定样例。必须紧跟 `→ spec/rubrics/rubric_v1.yaml#dim`
- `[[form:non-normative]]` → 仅供人读，**不参与门禁**

**示例**
> 每集必须恰好包含 1 个 Hook Beat，且位于该集前 20% 的 Beat 内。 `[[form:check]]` → `spec/checks/structure/STR-001.yaml`
> 商业短剧的钩子应该让人"来不及划走"。 `[[form:non-normative]]`

## 2. 禁止事项
- 禁止写"应该/尽量/最好"而不给形态标记。这类句子是愿望，不是 Spec。
- 禁止在 `spec/` 里写实现细节（用什么库、怎么循环）。那属于 `src/` 或 ADR。
- 禁止无 `evidence` 的 canonical 规则（`spec/rules/L3_canonical/` 强制 `evidence_ids` 非空）。

## 3. 变更流程
改 `spec/ir/**` 或任何 `severity: block` → 必须 ADR（`adr/`）+ PR 标签 `asset-change` + 人工 approve。