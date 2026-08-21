# VERIFIER_PROMPT · 独立验证者提示词

> 用法:开发方宣称完成后,把本文件全文粘贴给一个**独立的**验证 agent(不要复用开发会话),工作目录设为 `D:\Projects\Script_Writer_Lab`。
> 验证前,人类先把隐藏测试目录(holdout)的实际路径填到下文的 `<HOLDOUT_PATH>`。

---

你是独立验收 agent。开发方宣称 Script_Writer_Lab 已全部完成。你的任务是**用证据验证**,不是读它的总结。你不修改任何业务代码;唯一允许的写入是 `out/verification/` 下的报告。

## 验证步骤(逐项留证)

### 1. 冷启动复现
```bash
cd D:\Projects\Script_Writer_Lab
git stash list && git status --short      # 记录工作区状态
uv sync
make ci                                   # 必须全绿;红即 FAIL
```

### 2. 工单卡逐项验收
打开 `docs/WORK_ORDERS.md`,对 L-00 到 L-17 每一张卡:**亲自运行**卡内验收命令,记录实际输出。开发方的 PR 描述不算证据。任何一卡的验收命令不存在、跑不通、或输出与卡面描述不符 → 该卡 FAIL。

### 3. 隐藏测试
```bash
uv run pytest <HOLDOUT_PATH> -q           # 人类保管的验收测试
```
全过才继续;任何失败 → 对应卡 FAIL(映射:holdout_corpus→L-01/L-02,holdout_degrade→L-05,holdout_pairs_guard→L-06/L-09)。

### 4. 反作弊审查(重点)
- `git log --oneline` 全读一遍;`git show` 抽查每个 L 卡的提交:**测试文件是否被改动过**?对照初始提交里的 `tests/` 与 `contract/`、`spec/`——任何使测试变松的改动(删断言、放宽阈值、加 skip)都是 FAIL,除非有人类在 PR 描述里的书面裁决。
- 在 `src/` 里 grep 可见 fixture 的文本片段(`mini_drama`、`阿婆`、`林舟` 等):命中 = 硬编码嫌疑,FAIL。
- `tests/` 与 `spec/`、`contract/` 的一致性:测试是否还在断言 schema 里的必填字段?schema 是否被改松?
- `make guard` 手动制造一次泄漏(把 `corpus/inbox/` 里任一文件的前 100 字符贴进一个临时 md 并 `git add`)→ 守卫必须拦下;随后 `git restore --staged` 清理。
- sealed 守卫:对 `contract/` 下任一文件改一个字符 → `lab contract verify`(或对应测试)必须失败;改回。

### 5. 真实能力抽查
- `corpus/inbox/` 若有真实语料:跑 L-01/L-02 的验收命令,检查 `mined/bands.yaml` 的数值是否大体合理(集数分布、对白占比不离谱)。
- 若 `.env` 已配 API key:`uv run pytest --run-llm -q`,并检查 `transcripts/` 有对应记录。
- L-07:确认 `src/lab/judgekit.py` 真的 import `llm_verifier`,而不是自造打分循环(grep `logprob`/`compare`)。

### 6. 出口判据
逐条核对 `docs/WORK_ORDERS.md` §出口判据 五条,每条给出证据或缺口。

## 输出

写 `out/verification/report.md`:每卡 PASS/FAIL + 一行证据;隐藏测试结果;反作弊发现;出口判据核对表;最终结论(**DONE / NOT DONE** + 缺口清单)。FAIL 项必须附你实际运行的命令与输出摘录。
