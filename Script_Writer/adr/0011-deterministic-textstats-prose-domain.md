# ADR-0011：确定性文本统计检查与 prose 检查域

- 状态：accepted（项目负责人 2026-08-17 指令授权，见 `docs/UPGRADE_PLAN_2026-08-17.md` §0 授权条款）
- 日期：2026-08-17
- 影响层：A2 约束（新增 prose 域 16 条 + STR-014/015 + CMP-003..007，共 23 条规则）+ A5 知识（`_wordlists.yaml` / `_platform_terms.yaml` 词表资产）+ B2 生成物（新模块 `src/nsc/textstats/`、registry 薄注册）

## 背景

NSC 的质量检查此前以 LLM 判官 + 结构型 YAML 规则为主，缺少**零 LLM 成本的统计型检查**。三个独立外部项目在此形成强共识并给出全部实测参数：inkos `post-write-validator.ts`/`ai-tells.ts`（12+ 项 error/warning 与 4 维 AI-tell）、autonovel `evaluate.py::slop_score`（11 项合成 penalty）、novel-studio 6 条红线。这些阈值与词表是外部项目在生产中校准过的，直接采用，不做二次人工校准。

## 决定

1. 新增检查域 `prose`，16 条规则（PRS-001..016），规格全文见 `docs/UPGRADE_PLAN_2026-08-17.md` §5.1。其中 **PRS-009（报告术语入正文）与 PRS-010（章节号指称）为 `severity: block`**——二者是客观缺陷（大纲语言残留、文本自指），不是文笔偏好。
2. structure 域新增 2 条 block 红线：**STR-014**（每集必须含 inciting + climax 承重 beat）、**STR-015**（情感弧零振幅即失败），来自 novel-studio 红线清单的确定性子集。
3. compliance 域新增 5 条平台合规规则（CMP-003..007，番茄小说 must_avoid 清单），其中 CMP-003/004/005 为 block；`legal_ref` 指向 `_legal_sources.md` 新增 `#platform-rules` 节。平台 must_have 节奏项不进 checker，落 rubric 锚点。
4. 全部词表/阈值参数化进 `spec/checks/prose/_wordlists.yaml` 与 `spec/checks/compliance/_platform_terms.yaml`；checker 的 `__ctx` 加载器从 compliance 专用泛化为按域自动加载 `_*.yaml`。
5. 统计函数（段长 CV、句长 CV、n-gram 跨章重复、前缀 run 等）落新模块 `src/nsc/textstats/`，为无业务参数的纯机制函数；`checker/registry.py` 仅做薄注册。

## 被否决的替代

| 替代 | 为什么否决 |
|---|---|
| 把统计逻辑写进 interpreter/registry | 违反 D21 行数预算（runtime+checker 已 1433/1500），且机制应可独立测试 |
| 词表硬编码进 textstats | 违反"知识落 spec/"；词表必须可被反馈管道修订而不动代码 |
| 文笔类规则也用 block | 沿用 ADR-0010 结论：文笔偏好一律 warn/info，block 只给客观缺陷与红线 |
| 阈值自行发明 | 外部项目已实测校准；自行发明等于丢掉"拿来即用"的授权前提 |

## 对下游的约束

- golden IR 必须通过全部新规则（零误报）才可合并；误报一律改 fixture 或调词表，不许关规则。
- 词表修订走 PROMOTION.md 流程，代码零改动。
- PRS/STR/CMP 新规则的 message 必须遵守 DSL §5 诊断句三件套（直接进 GEPA feedback）。

## 迁移

纯新增。回滚 = 删除 23 条规则与 fixtures、删除 textstats 模块与注册项。

## 验证

- `pytest tests/test_checker_dsl.py`：23 条新规则 pass/fail/expected 全绿。
- `nsc check tests/fixtures/golden/demo_tea_ir.json`：零新增 block。
- `make spec-guard` 绿（含 rules_conflict 与 budgets）。
