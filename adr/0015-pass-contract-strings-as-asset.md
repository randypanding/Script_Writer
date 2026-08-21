# ADR-0015：Pass 契约文案作为资产（spec/passes/contracts.yaml）

- 状态：proposed
- 日期：2026-08-22
- 影响层：A5 知识（+ A6 配置）

## 背景

p3_beatsheet 与 p5_dialogue 把"机械复述给模型的输出格式契约"（`_SP_CONTRACT`、
`_FACT_CONTRACT`、`_SC_CONTRACT`、必现视觉/命名/字数目标文案）以 Python 字符串字面量
硬编码在 `src/nsc/passes/`。这与 AGENTS.md §2 "禁止在 prompt/代码里硬编码自然语言
知识"相悖：这些文案是规范知识，不是机制；改一句契约要动代码层，也无法在资产层审阅。

它们也不能进 `prompts/<pass>.json`：prompts/** 是 GEPA 的生成物（B1），禁止手改，
只有 `nsc optimize` / `nsc compile-prompts` 能写。契约文案需要人工精确维护，
不是优化对象。

## 决定

把 Pass 的静态契约文案搬进 `spec/passes/contracts.yaml`（资产层），Pass 在组装
LLM 输入时经 `nsc.passes.contract_text(pass_name, key)` 读取注入；带动态数据的
文案（品牌名、字数目标等）保留代码侧机械派生，模板用 `${name}` 占位
（string.Template），模板本体仍在 yaml。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 写进 prompts/<pass>.json | prompts/** 禁止手改（B1 生成物），契约需要人工精确维护 |
| 写进 signature docstring | docstring 是"种子指令"，会被 GEPA 优化漂移，契约必须稳定 |
| 保留在代码里加注释 | 违反 AGENTS.md §2 反模式；文案漂移无资产层审阅 |

## 对下游的约束

- 新增/修改 Pass 输出格式契约 → 改 `spec/passes/contracts.yaml`，不再进 `.py`。
- 契约文案变更会改变 spec/passes 域指纹 → 经 spec_sha 使该缓存失效（预期行为）。
- 模板占位符语法固定为 `${name}`（string.Template），避免与 JSON 示例里的花括号冲突。

## 迁移

纯搬家，文案逐字节不变（见 `tests/test_pass_contracts.py` 与 PR 描述的字节一致性
验证）。无 schema/IR 变更，无回滚成本：revert 即回代码字面量。

## 验证

`tests/test_pass_contracts.py`：键完整性、p3 常量与 spec 同源、p5 模板填充结果与
原 f-string 输出逐字节一致；全量 `pytest -m "not llm"` 绿。
