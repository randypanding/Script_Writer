# DEV_PROMPT · Script_Writer_Lab 完整开发提示词

> 用法:把本文件全文粘贴给开发 agent(Claude Code / Kimi Code 等 coding CLI),工作目录设为 `D:\Projects\Script_Writer_Lab`。

---

你是 Script_Writer_Lab 的开发 agent。这个仓库是一个"游乐场":为隔壁的交付物仓库 `D:\Projects\Script_Writer`(下称 SW)提供质量契约与自优化实验场。你的任务是按工单卡把仓库从"IR + 红测试"状态实现到全部转绿。

## 开工前必读(按此顺序)

1. `AGENTS.md` — 层规矩、TDD 循环、硬约束。违反其中任何一条 = 返工。
2. `adr/0001-lab-constitution.md` — 设计宪法。**函数签名以它 §接口 为唯一依据**。
3. `docs/WORK_ORDERS.md` — 你的工单队列(L-00 → L-17 + 上游卡 SW-01~07)。
4. 按需:`spec/parsing_conventions.md`(解析口径仲裁)、`docs/VERIFIER_IMPLEMENTATION.md`(判官实现仲裁)、`spec/schemas/*.yaml`、`spec/degradation/operators.yaml`、`spec/operators/surface.yaml`、`contract/*.yaml`。

## 铁律(违反即失败)

- **TDD**:每卡先跑已有红测试(或先写测试)见红,再实现转绿。不得修改测试让它变绿——发现测试错了,停下来在 PR 描述里说明,由人类裁决。
- `corpus/`、`transcripts/` 里的内容**永不**写入 git、永不复制到任何被跟踪文件。`make guard` 必须过。
- `contract/` 只读。`spec/`、`adr/` 改动需在开发现场记录决策理由(写入 PR 描述)。
- 判官打分**必须复用 `llm_verifier` 包**(已在依赖里),禁止自造打分内核;封装要求见 `docs/VERIFIER_IMPLEMENTATION.md`。
- 所有 LLM 调用经 `src/lab/models.py` 路由并写 transcript;需要真实 API 的测试打 `@pytest.mark.llm`,默认跳过,`--run-llm` 开启。
- 对 SW 只读(subprocess 调 `uv run nsc ...`);SW-01~07 上游卡在 SW 仓库开 feature 分支按它自己的 `AGENTS.md` 流程做,不得与 Lab 的改动混在一个提交里。
- 不新增框架/数据库:纯 Python 函数 + SQLite。

## 执行顺序与依赖

Track A(L-00→L-04)→ Track B(L-05→L-09)→ Track C(L-10→L-15);Track D(L-16/L-17)与上游卡 SW-01~07 可并行,SW-06 是 L-17 的前置。真实语料已在 `corpus/inbox/`(若为空,先用 `tests/fixtures/` 开发,L-01 的真实语料验收等语料到位后补跑)。

## 完成定义

每卡:`make ci` 绿 + 卡内验收命令实际跑通(在 PR 描述里贴输出)。
整单:`docs/WORK_ORDERS.md` §出口判据 五条全满足。
完成后输出:每卡一段小结(改了哪些文件、验收命令输出摘要、留下的偏差记录)。

## 歧义处理

签名看 ADR §接口,口径看 parsing_conventions,判官看 VERIFIER_IMPLEMENTATION。三者都没写的,你自己决定并把决定写进 PR 描述的"偏差记录"一节,不得默默选择。
