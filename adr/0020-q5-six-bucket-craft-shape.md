# ADR-0020：Q5 六桶全量映射——craft_shape 题材参数化扩桶

- 状态：proposed
- 日期：2026-09-02
- 影响层：A5 知识（spec/craft_shape.yaml 扩桶）、B2 测试（tests/test_craft_shape.py）
- 关联：Lab ADR-0004 Q5 · SW ADR-0019

## 背景

SW ADR-0019 落地了 craft_shape 题材参数化，但 `spec/craft_shape.yaml` 仅映射两个桶：
`爆款通用`（默认）与 `治愈成长`（低冲突豁免）。Lab 侧 `spec/genre_shapes/shapes.yaml`
已就绪七桶题材锚（522 卡，v2.1），`structure_terms.yaml` 配套了八桶结构约束。

Lab ADR-0004 Q5 明确要求：六桶全量映射消费 `genre_shapes`。当前 SW 侧的
`detect.keywords` 已覆盖七题材，但 `shapes` 仅有两卡——关键词命中后会在
`src/nsc/context/craft_shape.py:38` 触发 `KeyError`，属于未完成落地。

## 决定

1. **扩桶到六题材全量**：`spec/craft_shape.yaml` 的 `shapes` 从 2 卡扩到 8 卡
   （保留 `爆款通用` + `治愈成长`，新增 `历史穿越` / `复仇爽文` / `悬疑探秘` /
   `玄幻仙侠` / `甜宠言情` / `都市日常`）。
2. **锚与曲线进 shape 卡**：每张 shape 卡新增 `provisional`、`anchor`
   （五维：`hook_attack` / `conflict_person` / `info_gap` / `cliffhanger_rd` /
   `scene_turn`）、`tension_curve`（前/中/后三段张力）。数值直接消费 Lab
   `shapes.yaml` v2.1，`note` 字段保留来源摘要（`n_works`、`n_cards`、
   `provisional` 来源），不复制大段说明文。
3. **结构约束 1:1 映射**：`antagonist_required` / `ensemble_scene_required` /
   `hook_types` / `hook_other_allowed` / `stakes_escalation` / `arousal_peak` /
   `ending_beats` 七字段映射自 Lab `structure_terms.yaml`，保持语义一致。
4. **代码零改动**：`src/nsc/context/craft_shape.py` 的 `resolve()` 已通过
   `dict(data["shapes"][best])` 泛化返回，新增字段自动透传到
   `ctx.profile["craft_shape"]`，随 `profile_json` 注入全 Pass 与检查 bind。
5. **同步机制**：Lab 重跑锚（补料/重标）生成新 `shapes.yaml` 后，需人工开 PR
   同步 SW `spec/craft_shape.yaml` 的数值字段。本 ADR 不引入自动同步链路。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 在 `craft_shape.py` 里硬编码六桶 if/elif 映射 | 违反 AGENTS.md §2"禁止在 Python 里写业务规则" |
| 运行时读取 Lab `shapes.yaml` 作为单一事实源 | 跨仓依赖违背当前 subprocess 调用边界（Lab AGENTS.md §2） |
| 保持 2 桶 stub，其余桶落 `爆款通用` | Q5 明确要求六桶全量映射，且 Lab 锚数据已就绪 |

## 对下游的约束

- 新增题材须先在 Lab 补锚（≥8 部或标 `provisional`），再按本文件格式映射
  SW shape 卡。
- `爆款通用` 不设 `anchor` / `tension_curve`（它是混题材复合契约，无单一事实源）。
- `provisional: true` 的桶（当前仅 `治愈成长`）其结构约束仅供判官参考，
  不用于门禁阻断（与 Lab `structure_terms.yaml` 的 `provisional_constraint`
  语义一致）。

## 迁移

非 breaking change：旧 brief 无关键词命中时仍落 `default_shape=爆款通用`，
行为与 ADR-0019 逐字节一致。`profile` 无 `craft_shape` 时 CRAFT-001 的
JMESPath 缺省回 `true`，旧配置零变化。

## 验证

- `tests/test_craft_shape.py`：新增 14 条用例（6 桶检测 + 6 桶锚曲线存在性 +
  `治愈成长` 锚曲线补全 + `爆款通用` 无锚断言）。
- `make spec-guard`：spec 层完整性门禁全过。
- `uv run pytest -m "not llm" -n auto -q`：全绿（25/25）。
