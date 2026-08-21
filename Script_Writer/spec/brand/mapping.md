# BrandBrief 字段 → checker 规则 编译映射表

`nsc compile-constraints` 读 `brands/<id>/brand.yaml`，按下表产出 `Constraint[]` 注入 IR。
**每一行都必须有对应的 `spec/checks/**.yaml`；缺失则 `make spec-guard` 失败。** `[[form:check]]`

| BrandBrief 字段 | 生成的 Constraint | 规则 ID | severity |
|---|---|---|---|
| `products[*].canonical_name` + `aliases` | 产品名写法白名单 | `BM-009` | block |
| `products[*].facts` | 交付文本中的数字/参数必须来自 facts | `FCT-001` | block |
| `selling_points[?must_cover]` | 每个必覆盖卖点 ≥1 BrandMoment | `BM-006` | block |
| `selling_points[*].forbidden_phrasings` | 禁用表述 | `DLG-001` | block |
| `selling_points[?proof==''] ` | 无证据卖点禁止 `proof_mode==demo` | `BM-012` | block |
| `audience[*]` | 至少 1 个 `customer_proxy` 角色 `persona_ref` 命中 | `STR-013` | block |
| `usage_scenes[?!shootable]` | 不得作为 Scene 的 location | `PRD-003` | warn |
| `tone_words` | rubric 调性维度上下文（非 block） | `rubric_v1#tone` | info |
| `banned_words` + `legal.banned_words` | 零出现 | `DLG-001` | block |
| `must_include_lines` | 原文出现且标记 `is_brand_line` | `BM-007` | block |
| `must_include_visuals` | 至少一个 Line/Scene 描述命中 | `BM-007b` | block |
| `placement.max_moments_per_episode` | 单集植入上限 | `BM-001` | block |
| `placement.min_gap_beats` | 植入最小间隔 | `BM-002` | block |
| `placement.forbid_in_beat_kinds` | 禁止落位 | `BM-003` | block |
| `placement.max_high_intensity_per_episode` | 高强度植入上限 | `BM-005` | block |
| `placement.require_high_plot_connection` | 全季高情节关联植入下限 | `BM-004` | block |
| `legal.competitor_names` | 竞品名零出现 | `BM-011` | block |
| `legal.claim_whitelist` | 功效表述白名单外零出现 | `CMP-002` | block |
| `business_goal` | 影响 Profile 的 CTA/beat 模板选择 | `profiles.*` | — |