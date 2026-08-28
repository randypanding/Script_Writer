# ADR-0019：题材工艺形状（craft_shape）——爆款契约按题材参数化

- 状态：proposed
- 日期：2026-08-28
- 影响层：A 资产层（spec/craft_shape.yaml 新增、spec/checks/structure/CRAFT-001.yaml 条件化、
  spec/passes/signatures.py 种子指令）；B 层消费（src/nsc/context/craft_shape.py、
  src/nsc/cli.py::_make_ctx、prompts/p3_beatsheet.json 编译版同步）
- 证据链：Lab W1 分题材锚 v2（`mined/craft_anchors_v2.json`，522 卡，k=3 多数票，
  标注器一致率 0.73；docs/craft_taxonomy_v2.md §5 round27 增补）

## 背景

R2/R3 的正向契约把"爆款铁律"写进了每个 Pass 的硬约束：antagonist 必有（person 0.83）、
威胁/承诺/颠覆开局（攻击型钩子 0.75）、赌注逐集升级、对手戏同框、末拍 reveal/danger。
这些数字全部来自**混题材爆款**（复仇/爽文主导）。Lab round25/26 实证锚错位：
治愈成长桶 person 0.33、cliff 0.27、张力 3.4/3.2/3.4——为治愈系 IP 强拉人与人冲突
（R4 季弧重排）把 transportation 打破地板（0.65），属于"用错了锚的工艺加压"。

## 决定

1. **知识进 spec**：新增 `spec/craft_shape.yaml`——题材检测关键词（与 Lab genre_classify
   同源）+ 每题材一张形状卡（antagonist_required / ensemble_scene_required / hook_types /
   hook_other_allowed / stakes_escalation / arousal_peak / ending_beats）。
   默认形状 `爆款通用` 与现行契约逐字节一致；唯一非默认桶为 `治愈成长`（治愈锚 v2 暂定锚）。
2. **机制进代码**：`nsc.context.craft_shape.resolve/attach` 只做"读 spec → 数关键词 →
   返回形状"；`_make_ctx` 把形状并入 `ctx.profile["craft_shape"]`，随 profile_json
   注入每个 Pass。无关键词命中/平票落默认（与 Lab `craft_bench.detect_genre` 同语义）。
3. **种子指令引用形状字段**（p1 Bible / p2 Arc / p3 BeatSheet / p4 SceneCards）：
   硬约束改写为"以 profile_json.craft_shape.<field> 为准"，默认分支保留原爆款理由与数字。
4. **编译版 p3 同步**：`prompts/p3_beatsheet.json` 运行时优先级高于种子，追加
   【题材工艺形状(craft_shape)】块并更新 _meta（lab-round28-optimizer）。
5. **CRAFT-001 题材豁免**：bind 增加
   `ant_req: "@.__ctx.profile.craft_shape.antagonist_required || `true`"`，
   assert 改为"主角在场 and (not ant_req or 对手同场)"——旧 profile 无 craft_shape 时
   JMESPath 缺省回 true，行为与现行完全一致（fixtures 双测覆盖）。

## 后果

- 治愈系 brief（如南浪仔，检测词"治愈/自在"命中）自动落到温和形状：
  不设反派、允许悬念开局与温和冲突升级、对手戏改为"真实连接场景"。
- 非治愈 brief 行为零变化（默认形状），R2/R3 的全部实证结论继续有效。
- 新题材扩展路径：先在 Lab 补锚（≥3 部，或标 provisional），再加 shape 卡。
- 局限：检测是关键词计数（与 Lab 判分器同一弱点），brief 不写气质词时落默认形状——
  宁可误用爆款契约（保守方向），不误入温和形状。
