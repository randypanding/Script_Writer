# WORK_ORDERS · Lab 工单卡

规则:按序开发;每卡**先红后绿**;验收命令必须通过;`L-` 卡在本仓,`SW-` 卡是对 `../Script_Writer` 的上游 PR(走对面仓库的工单/ADR 流程,不在本仓实现)。
启动状态:`tests/` 四文件全红为预期;全部转绿 = bootstrap 完成。
有歧义时:接口签名以 `adr/0001-lab-constitution.md` §接口为准,解析口径以 `spec/parsing_conventions.md` 为准,判官实现以 `docs/VERIFIER_IMPLEMENTATION.md` 为准。

## Track A · 骨架与安全

### L-00 仓库骨架
- 范围:`pyproject.toml` `Makefile` `.gitignore` `scripts/corpus_leak_guard.py`(已给 v0)。
- 验收:`make lint` 绿;`uv run pytest --collect-only` 收集到 4 个测试文件;`make guard` 在无语料时通过、在 `corpus/` 被 `git add` 时失败。

### L-01 语料入库 `lab.corpus`
- 范围:`src/lab/corpus.py`。格式归一(短剧剧本/小说分流)、simhash 去重、元数据卡(声称题材/平台/集数)。口径见 `spec/parsing_conventions.md`。
- 测试:`tests/test_corpus_card.py`(已给,红)。
- 验收:`uv run pytest tests/test_corpus_card.py -q` 绿;`uv run python -m lab.corpus ingest corpus/inbox` 对真实语料跑通,重复文件被拦。

### L-02 确定性统计卡
- 范围:`src/lab/corpus.py::stats_card` 扩全字段:句长均值/CV、对白占比、钩子位置、分集字数。
- 验收:全量语料跑完,`mined/bands.yaml`(各指标 P25/P50/P75 正常带)+ `mined/corpus_stats.md`(语料画像)落盘。

### L-03 LLM 深提取(分层抽样)
- 范围:`src/lab/corpus_mine.py`。按题材×集数分层抽样 N(默认 100)部,出 beat 卡/钩子/反转点;断点续跑;走 `lab.models` 路由写 transcript。
- 验收:`uv run python -m lab.corpus_mine --sample 100` 产出 `mined/patterns/*.yaml`;中断重跑不重复扣费。

### L-04 AI 味词典 + 语料相对指标
- 范围:`src/lab/slop.py`。我们生成物 vs 语料的 PMI/n-gram 差异 → `mined/slop_lexicon.yaml`;指标注册进 `mined/metrics_registry/`(五要素,L-D3)。
- 验收:词典 ≥100 条,每条带 PMI 值;不含 >50 字符语料原文(`make guard` 须过)。

## Track B · "好"的定义实体化

### L-05 退化算子库 `lab.degrade`
- 范围:`src/lab/degrade.py`,实现 `spec/degradation/operators.yaml` 全部 15 个算子,语义补充约定见 `spec/parsing_conventions.md`。
- 测试:`tests/test_degradation.py`(已给,红)。
- 验收:`uv run pytest tests/test_degradation.py -q` 绿;每个 llm_mid 算子附一条 `--run-llm` 冒烟测试。

### L-06 合成偏好对 `lab.pairs`
- 范围:`src/lab/pairs.py`;三类来源:语料×退化算子 / 语料 vs 我们生成物 / 生成物×退化算子。
- 测试:`tests/test_pairs_schema.py`(已给,红)。
- 验收:产出 `out/pairs/{exam,train,val}.jsonl` ≥3000 条,schema 全过,**按 script_id 切分**,split 间无泄漏。

### L-07 判官工具箱 `lab.judgekit`
- 范围:**复用官方包 `llm_verifier`,禁止自造打分内核**。做法全部照 `docs/VERIFIER_IMPLEMENTATION.md`:`score_pair` = 两次有向 `compare` 取平均(去槽位偏差);best-of-n 用 `select`(PPT);每轴一份信号级 criteria md(放 `criteria/`);`ground_truth_note` 禁用。
- 先决:实测各端点 logprobs 支持并记录结论(dashscope 不行则 dev 判官走本地 vllm,sealed 走 DeepSeek)。
- 验收:单测 mock 客户端验证期望分聚合与位置交换逻辑;k_sample_vote 降级路径有测试;`--run-llm` 冒烟通过。

### L-08 判官考试
- 范围:`lab.judgekit.run_exam`,对照 `contract/judges.yaml` §exam 五门限出 pass/fail。
- 验收:对 mock 判官出格式正确的报告;对真实 dev/sealed 判官各跑一次,报告落 `dashboards/judge_exam.md`。**考试全过 = 判官闸门 ON,这是 bootstrap 的第一个硬关卡。**

### L-09 契约守卫 `lab.contract_guard`
- 测试:`tests/test_contract_guard.py`(已给,红)。
- 约定:锁文件 = `<dir>/.seal.lock.json`,内容为文件清单 + 每文件哈希 + 整体 HMAC(key);`verify` 重算比对。
- 验收:测试绿;`make guard` 集成 sealed 哈希校验;篡改、新增、重命名任一 sealed 文件均判失败。

## Track C · 运行器与优化循环

### L-10 运行器 `lab.runner.run`
- 范围:subprocess 包 pinned SW 的 `nsc run`/`nsc check`;产物 + transcript 落 `transcripts/`。依赖 SW-01。
- 验收:一个 brief 一次 run,trace 完整可查;`NSC_NO_CACHE=1` 开关可用。

### L-11 配对 A/B `lab.runner.ab`
- 范围:同 brief 同种子 champion vs candidate;bootstrap CI95;输出 ABReport。
- 验收:对 fixture 双配置跑出区间;种子/缓存键正确隔离。

### L-12 sealed 提交 `lab.runner.sealed_submit`
- 范围:配额账本(默认每实验轮 20 次,见 contract);只回标量,理由不可读。
- 验收:超配额被拒;账本持久化。

### L-13 OPTIMIZER.md + 优化驱动
- 范围:`OPTIMIZER.md`(每会话=一轮实验:假设→改动→`lab ab`→日志;M3 只许提 ADR 建议)+ `optimizer/notebook.md` 模板。
- 验收:用一个 coding CLI 会话按 OPTIMIZER.md 完成一轮 dry-run,日志格式合规。

### L-14 合成 brief 生成器
- 范围:`src/lab/briefs.py`;按 `mined/bands.yaml` 分布生成 dev/val briefs;分布规格在 `contract/objective.yaml::brief_distribution`,优化器不可改。
- 验收:dev 30 / val 15 briefs 落盘,分布卡方检验不偏离规格。

### L-15 观测面板 `lab.report`
- 范围:五面板 dashboard(L-D6)+ 实验台账 SQL。
- 验收:`uv run python -m lab.report` 生成 `dashboards/latest.md`;五面板数据齐。

## Track D · M2 面(与 A/B/C 并行开发,当日完成)

> 注意:M2 的**开发**今天做完;M2 的**放权**仍等判官闸门 ON(L-08)——闸门之前 M2 实验无法打分,跑了也是空转。

### L-16 M2 变更面应用器
- 范围:`src/lab/overlay.py`。把 candidate 的 profile/config 变更映射到 SW 的临时副本(**git worktree**,不污染 pinned checkout):写入 profile yaml、models.yaml、prompts/*.json,然后供 `lab.runner` 指向该副本运行。
- 验收:同一 brief 在 pinned 副本与 overlay 副本上各跑一次,产物差异可归因到 overlay 的变更项;worktree 用完即清理。

### L-17 M2 冒烟实验
- 范围:依赖 SW-06 完成后,用 L-16 跑三组对照——assembler P2-P4 开/关、compress ratio 0.1/0.3、Thread 注入开/关;`lab ab` 出报告。
- 验收:`dashboards/m2_smoke.md` 落盘,证明 M2 面是活的(变更可应用、可打分、可归因)。

## 上游依赖卡(对 SW 提 PR,走对面仓库流程;SW-05~07 即"M2 今天开发"的主体)

- **SW-01** transcript 持久化:`src/nsc/runtime/models.py` 单点改动,prompt/response 落 SQLite。(L-10 前置)
- **SW-02** `spec_sha` 分域哈希:避免任何 spec 小编订使全量内容缓存失效。
- **SW-03** pass 内嵌契约字符串(p3 `_SP_CONTRACT` 等、p5)提升到 prompts 层。
- **SW-04** `gate_enabled()` 去除环境变量覆盖。
- **SW-05** p3 fragment 组成数据化:prev_summary 窗口、known_facts 投影字段、Thread 注入开关,全部由 profile 驱动(当前硬编码在 `pipeline.py`)。
- **SW-06** 接线休眠模块:`context/assembler` 的 P2–P4 层接入 p3/p5,`compress_history` 接入 p3 的远端历史(两者已实现未接线;profile `context.*` 配置段已存在)。
- **SW-07** pipeline 策略 profile 化:各 phase 重试次数、定向重生成策略、self-check 子步骤开关、rerank n,从代码常量改为 profile 可读。

## 出口判据(整个 bootstrap)

1. L-08 判官考试全过(dev + sealed 双判官);
2. L-06 偏好对 ≥3000 条,split 无泄漏;
3. SW champion 刻印:git tag + 10 个合成 brief 的基线产物 + 基准分;
4. L-17 的 `dashboards/m2_smoke.md` 证明 M2 面可用;
5. `make ci` 全绿,`lab report` 五面板出数。
到此,优化 agent 进场条件成熟(M1 立即放权,M2 随闸门 ON 放权)。
