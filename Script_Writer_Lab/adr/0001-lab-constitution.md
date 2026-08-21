# ADR-0001 · Lab 宪法

status: accepted(人类批准即冻结;修订需新 ADR)

## 背景

`../Script_Writer`(下称 SW)治理完备(spec 即源码、L0 八十条规则、判官成对协议、成本账本),但三处信号缺失:判官未过校准(κ=0.156,仅合成冷启动数据)、人类反馈为零(无人懂行,标注即噪声)、无任何 sealed 评测。本仓(Lab)的任务是在**不依赖人类标注**的前提下,把"好"定义出来、密封起来,再让强模型在契约内自优化。

商业模式:客户付费做营销短剧,交付物是"可解释的工业化质量",不是完播率/转化率。因此质量标准可以是封闭世界,**指标体系本身就是产品件,宁滥勿缺**。

## 决策

- **L-D1 仓内外分离。** Lab 与 SW 物理分仓;SW 对 Lab 是 pinned 只读依赖,只能 subprocess 调用;洞察回流只走对 SW 的 PR。
- **L-D2 合成优先的三锚"好"定义**(替代人类标注):
  1. **语料锚**——千部剧本的群体统计正常带(单部噪声大,千部分布噪声小);"好"= 不偏离带内。
  2. **退化锚**——机械退化算子制造已知缺陷(`spec/degradation/operators.yaml`),原版按定义优于退化版;判官考试与偏好对的标签由构造保证,不依赖任何模型判断。
  3. **交叉锚**——sealed 判官必须跨模型家族;同族一致性高不等于对,但跨族一致性低的轴直接降级"仅报告"。
- **L-D3 指标注册表是产品。** 每条指标五要素:度量什么/检测器/成本/防作弊注记/交付话术。注册表在 `mined/metrics_registry/`(L-04 起建)。
- **L-D4 判官架构:采用 LLM-as-a-Verifier 范式**(arXiv:2607.05391),四条全部采纳但分层使用:
  1. logprob 期望连续分替代离散打分 token(API 不暴露 logprobs 时降级为 k 采样投票,降级路径必须有测试);
  2. k=5 重复评估降方差(叠加 SW 已有的位置交换去偏);
  3. 子信号分解:每轴拆成 rubric 信号级子问题分别验证,再聚合;
  4. 成本感知排名用于 best-of-n 选优(SW 的 `p5 --rerank` 是天然落点)。
  **dev 判官**可用中档模型×k(该论文的核心收益:弱验证器+重复采样逼近强验证器);**sealed 判官不降档**,保持强模型跨家族——弱判官的系统性盲区会被优化器定向利用,采样只能降方差、不能消偏。所有判官(任何范式)必须先通过退化考试(`contract/judges.yaml` §exam)才准出分。
  **实现一律复用官方包 `llm-verifier`(GRANULARITY=20、compare/select/PPT),禁止自造打分内核**;封装细则见 `docs/VERIFIER_IMPLEMENTATION.md`。
- **L-D5 优化面三级放权**,目录即 `spec/operators/surface.yaml`:M1 立即可放(prompts/路由/profile 旋钮),M2 契约稳定后放(记忆挂载/流程图),M3 永不放(评测器、规则、阈值、晋升规则本身)——M3 只接受 ADR 建议文本。两处已知的面缺口由上游卡补齐:SW-03(契约字符串从 pass 代码提升到 prompts 层)、L-14(合成 brief 生成器;分布规格冻结在 contract,优化器不可改)。
- **L-D6 观测性契约。** "真优化"的五项证据(dashboard 固定面板,`lab report` 生成):
  1. sealed 对 champion 胜率轨迹(带 bootstrap 置信带)——**唯一主指标**;
  2. dev 与 sealed 趋势背离警报(背离 = dev 被过拟合);
  3. 语料盲测胜率趋势(内部指标涨而它不爬升 = 指标腐坏);
  4. 退化检出率(判官健康度,掉线 = 判官被绕过);
  5. 实验接受/拒绝比(健康带约 30–70% 接受;100% 接受 = 在作弊或噪声)。
- **L-D7 晋升规则外置**(`contract/promotion.yaml`):优化器无权接受自己的改动;未过判据自动回滚;champion 以 git tag + champions.yaml 注册。
- **L-D8 语料纪律。** 原文只进不出;`mined/` 只存聚合产物;`make guard` 泄漏守卫进 CI。
- **L-D9 优化 agent 用 coding CLI 承载,不自建框架。** Lab 只提供:契约(只读+哈希锁)、`lab` 工具面、`OPTIMIZER.md` 纪律(L-13)。每个优化会话 = 一轮实验(一个假设、一次 A/B、一条日志)。
- **L-D10 小模型暂缓。** 训练数据为零、靶子在动;触发条件(数据量/稳定性/成本)成熟后另立 ADR。本仓不预设预算门限,资源由人类管理。

## 接口(实现契约,红测试的依据)

- `lab.corpus`: `parse_script(path) -> ScriptCard`;`stats_card(card) -> dict`(符合 `spec/schemas/corpus_card.schema.yaml`);`ingest(inbox_dir, store_dir) -> IngestReport`(simhash 去重)。
- `lab.degrade`: `REGISTRY: dict[str, Operator]`;`Operator.apply(text, severity, rng_seed) -> str`;属性 `.axis`、`.mechanism ∈ {deterministic, llm_mid}`。注册表必须与 `spec/degradation/operators.yaml` 一一对应。
- `lab.pairs`: `build_pair(axis, a_text, b_text, label, construction, split) -> dict`(符合 `spec/schemas/pairs.schema.yaml`;label/split 非法值抛 `ValueError`)。
- `lab.judgekit`: `score_pair(a, b, axis, judge_cfg) -> Verdict`(k 采样 + logprob 期望 + 位置交换);`run_exam(judge_cfg, exam_pairs) -> AxisReport`(对照 `contract/judges.yaml` §exam 门限)。
- `lab.contract_guard`: `seal_dir(dir, key) -> LockFile`;`verify(dir, lock) -> bool`。
- `lab.runner`: `run(brief, config, seed) -> Artifact`;`ab(candidate_cfg, champion_cfg, briefs, seeds) -> ABReport`(配对同种子 + bootstrap CI95);`sealed_submit(candidate) -> float`(配额账本)。
- `lab.report`: `render(db_path) -> dashboards/latest.md`(五面板,L-D6)。
- transcript 表(SQLite): `(ts, caller, model, prompt, response, tokens_in, tokens_out, cost_usd, experiment_id)`。

## 否决项(明确不做)

- 自建 agent 框架(用 coding CLI);
- 人类标注先行(不懂行,真实世界噪声更大);
- 语料上传任何云端/git;
- 现在微调小模型(L-D10);
- 把完播率/转化率作为优化目标(商业模式不要求,SW 的 METRICS.md 已否决)。
