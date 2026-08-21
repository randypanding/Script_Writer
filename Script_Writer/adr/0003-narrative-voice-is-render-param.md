# ADR-0003：叙述视角/人称/文体是渲染参数，不进 IR 主干

- 状态：accepted · 日期：2025-01-01 · 影响层：A1 / A6

## 决定
`NarrativeVoice`（person / tense / pov / style / paragraph_max_chars / interiority）挂在 IR 的 `voice` 字段，
但**不参与 Beat/Line 的语义**。默认值来自 `profiles.*.novel.default_voice`。

## 理由
同一部剧要能同时给出"第三人称限知爽文体"和"第一人称日记体"两版小说给商家选。
若视角进主干，同构性被破坏，两个 Profile 就会 fork 内核（违反 D18）。

## 对下游的约束
`dep_graph.yaml` 中 `voice.*` 只失效 `p6_prose` 与 `p7_render`。这条是可测的收益。