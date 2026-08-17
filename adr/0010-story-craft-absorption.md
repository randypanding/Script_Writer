# ADR-0010：吸收 story-craft 技能为叙事创作资产

- 状态：proposed
- 日期：2026-08-17
- 影响层：A2 约束（新增 7 条 warn 检查）+ A3 品味（rubric 新增 prose_craft 维度）+ A5 知识（6 条 L3 canonical 规则）+ B2 生成物（registry / build_view 扩展）

## 背景

工作区根目录的 `story-craft-skill.md` 是一份完整的创意写作技能文档（角色系统 Soul Field、叙事逻辑、风格温度、文笔工艺、13 类反 AI 指纹、长期状态管理、同人/剧本模块等）。它不能留在仓库里当孤岛文件：AGENTS.md 铁律一"`spec/` 是唯一真相，任何知识若不能落进 `spec/ir | spec/checks | spec/rubrics | spec/rules | profiles | brands` 视为不存在"。需要把它按本项目（营销短剧：先出小说确认物、再出剧本执行物）的形态吸收为可复用资产，然后删除源文件。

## 决定

把 story-craft 技能吸收为四类资产：

1. **门禁（7 条 `severity: warn` 检查规则）**，全部可机械化、可被 golden 回归：
   - `spec/checks/novel/NOV-004`：抽象情绪标签句（show-don't-tell 的机械代理）
   - `spec/checks/novel/NOV-005`：AI 高频套话词
   - `spec/checks/novel/NOV-006`：弱化拟态词堆叠（新增 registry 白名单函数 `count_any`）
   - `spec/checks/novel/NOV-007`：空泛强调词堆叠
   - `spec/checks/novel/NOV-008`：等距时间线开头（流水账）
   - `spec/checks/novel/NOV-009`：主角/反派必须带缺陷与成长弧（Soul Field 的机械部分，build_view 暴露 `flaw/arc`）
   - `spec/checks/dialogue/DLG-007`：场景级对白墙（≥4 条对白且无动作行）
2. **品味（rubric 新增第 6 维 `prose_craft`·文笔与反AI味）**，`applies_to: [chapter]`，权重重平衡（transportation 0.20→0.15、placement_integration 0.25→0.20，新增 prose_craft 0.10；naturalness 0.25 / hook_strength 0.20 不动，保证 `test_aggregate_l1_weighted` 的 4.111 不变）。
3. **知识（6 条 `spec/rules/L3_canonical/` R3-0002…0007）**：以"借入知识"形式落库，每条 `rationale` 注明来源（story-craft 技能章节），`target` 指向对应检查，`evidence_ids` 沿用仓库既有惯例（`case:0142/0177` + 未来反馈管道的 `obs:` 记录），待真实反馈数据产出后按 PROMOTION.md 复核/替换。
4. **流程（`docs/SOP_PROSE_CRAFT.md`）**：p6_prose 写小说时的文笔工艺 checklist，把"禁止硬编码进 prompt"的自然语言知识以 SOP 形式沉淀。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 直接写进 `prompts/` | `prompts/` 是生成物 B1，禁止手改（AGENTS.md 铁律二），只能由 `nsc optimize` 写入 |
| 硬编码进 `src/` | 违反 D21 行数预算与"禁止在 Python 里写业务规则"，知识应抽回 `spec/` |
| 原样全量搬进 `spec/` | 技能含同人/CP/连载站运营等本项目不需要的内容，会稀释资产；只吸收对"营销短剧小说"有直接价值的骨架 |
| 新建块级（block）规则 | 触碰 AGENTS.md §5 的"改 `spec/checks` 的 `severity: block`"红线，且文笔类规则不应阻塞交付；一律用 `warn` |

## 对下游的约束

- 新增的文笔类规则是**非阻塞（warn）**，允许进入 GEPA feedback 通道，但不作交付门禁。
- 6 条 canonical 规则的 `evidence_ids` 是"借入知识"的占位证据；真实反馈管道（T-11/T-14）产出的案例应回填复核，若与真实数据冲突按 PROMOTION.md 退役。
- rubric `prose_craft` 维度加入后，需在下次 `make judge-cal` 一并校准该维度的一致率。
- 删除 `story-craft-skill.md`；其知识索引见 `docs/BORROW_MAP.md` 新增条目与 `docs/SOP_PROSE_CRAFT.md`。

## 迁移

非 breaking：纯新增资产 + 1 个 registry 白名单纯函数 + build_view 只增字段。回滚方式：删除 7 条规则与 fixtures、回滚 rubric 权重、删除 6 条 canonical 规则与 SOP。

## 验证

- `make ci-local` 全绿（lint / typecheck / spec-guard / test-fast）。
- `tests/test_checker_dsl.py`：7 条新规则 pass/fail 全部符合预期。
- `tests/test_pipeline_stub.py`：黄金 IR 端到端 findings 仍为空（新规则在"合格内容"上不误报）。
- `tests/test_judge.py::test_all_dimensions_have_anchors`：prose_craft 有 ≥2 锚例。
