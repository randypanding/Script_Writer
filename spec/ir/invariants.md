# IR 结构不变量（19 条，全部 `[[form:schema]]` 或 `[[form:check]]`）

所有不变量由 `spec/ir/invariants.py` 实现，`tests/test_invariants.py` 用 Hypothesis 做 property-based 验证。
违反 = `severity: block`，无例外。

| ID | 不变量 | 形态 |
|---|---|---|
| INV-01 | 全 IR 内所有 `id` 唯一，且符合 ULID 正则 | `[[form:schema]]` → `spec/ir/nodes.py::ULID` |
| INV-02 | `parent_id` 指向存在的节点，且父子 kind 满足 `HIERARCHY` | `[[form:check]]` → `spec/ir/invariants.py::inv_02` |
| INV-03 | 同 parent 下 `order` 为 `0..n-1` 连续无重复 | `[[form:check]]` → `inv_03` |
| INV-04 | parent 链无环且可达 Project | `[[form:check]]` → `inv_04` |
| INV-05 | 每个 Episode 恰好 1 个 `beat_kind==hook` 的 Beat | `[[form:check]]` → `inv_05`（位置约束在 STR-001） |
| INV-06 | `beat_kind==brand_moment` ⇔ `brand_moment_id` 非空；且 `BrandMoment.anchor_beat_id` 反向一致；一个 Beat 至多 1 个 BrandMoment | `[[form:check]]` → `inv_06` |
| INV-07 | `line_type in {dialogue, voiceover}` 时 `character_id` 非空，且该角色在所属 Scene 的 `present_character_ids` 内 | `[[form:check]]` → `inv_07` |
| INV-08 | `SetupPayoff` 的 `linear_index(setup) < linear_index(payoff)`，两端 Beat 均存在 | `[[form:check]]` → `inv_08` |
| INV-09 | 所有跨引用完整：`location_id / present_character_ids / prop_id / selling_point_id / persona_ref / pov_character_id` | `[[form:check]]` → `inv_09` |
| INV-10 | `Emotion.valence ∈ [-1,1]`，`arousal ∈ [0,1]` | `[[form:schema]]` → `Emotion` |
| INV-11 | 每个 Episode ≥1 Scene；每个 Scene ≥1 Beat；每个非 `action`-only Beat ≥1 Line（Pass5 之后） | `[[form:check]]` → `inv_11` |
| INV-12 | `Episode.no` 在同 Season 内从 1 连续递增，且与 `order` 同序 | `[[form:check]]` → `inv_12` |
| INV-13 | Profile 层级启用一致：`profile.layers.season == false` ⇒ `len(seasons) == 1` 且 `Season.title == ""` | `[[form:check]]` → `inv_13` |
| INV-14 | 每个主干节点与 NovelChapter 的 `provenance_id` 存在于 `provenance[*].run_id` | `[[form:check]]` → `inv_14` |
| INV-15 | `sum(beat.est_duration_s)` 落在 `episode.duration_target_s × (1 ± profile.duration_tolerance)` 内 | `[[form:check]]` → `inv_15` |
| INV-17 | 所有 `Fact.resolves` 指向存在且≠自身的 Fact id；且 `status==resolved ⇔ 存在另一条非 deprecated 的 Fact.resolves==该 id` | `[[form:check]]` → `inv_17`（ADR-0012） |
| INV-18 | `Fact.caused_by` 的每个 id 存在，且目标 Fact 的 `episode_no <= 本 Fact.episode_no`（因果不得倒置） | `[[form:check]]` → `inv_18`（ADR-0012） |
| INV-19 | DarkThread 按 `episode_no` 升序累加 key 匹配的 int delta 得 `current_stage ∈ [0, len(stages)-1]`；`type=="number"` 的 StateVariable 匹配 delta 必须是 int/float | `[[form:check]]` → `inv_19`（派生纯函数 `nsc.runtime.ir_io::derive_state / derive_stage`，ADR-0012） |
| INV-20 | `Episode.responds_to` 每个元素是存在 Episode 的 `no` 且严格小于本集 `no` | `[[form:check]]` → `inv_20`（ADR-0012） |

## 局部重编译的 ID 稳定性契约 `[[form:check]]` → `inv_16_id_stability`
重编译一个子树时，**未被 LLM 改动的节点必须保留原 ID**。
判定：`merge_preserving_ids(old, new)` 后，`old` 中 `text/summary` 未变的节点，其 ID 必须与 `old` 一致。
违反此条 = 所有历史反馈失效 = 系统性资产损毁。这是最高优先级的测试（`tests/test_invariants.py::test_id_stability`）。