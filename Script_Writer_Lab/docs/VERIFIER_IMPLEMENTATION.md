# LLM-as-a-Verifier 复用实现笔记(L-07 的依据)

来源:官方开源实现 [llm-as-a-verifier/llm-as-a-verifier](https://github.com/llm-as-a-verifier/llm-as-a-verifier),PyPI 包 `llm-verifier`(已入 `pyproject.toml`,v0.2+)。**禁止自造打分内核**——下列语义以包内实现为准。

## 已核实的核心机制

- **细粒度连续分**:`GRANULARITY = 20`(打分 token 为 1–20 的刻度),对每个刻度 token 的 logprob 分布求期望:
  `R(x,τ) = (1/CK) Σ_c Σ_k Σ_g p_θ(v_g | x,c,τ) · φ(v_g)`,C=准则数,K=重复次数,G=粒度。实现在 `llm_verifier/fine_grained_reward.py`。
- **`compare(problem, trace_a, trace_b, criteria=..., n_evaluations=..., model=...) -> (R_A, R_B)`**,[0,1] 细粒度奖励。**注意:单次 compare 是有向的,不去槽位偏差**(官方 docstring 明说)。→ 我们的封装必须 (A,B)+(B,A) 两调取平均,对应 SW 既有 position_swap 纪律。
- **`select(problem, candidates, criteria=..., n_evaluations=4, pivots=2, seed=0, cache=...) -> VerifierResult`**:Probabilistic Pivot Tournament,O(Nk) 次成对验证替代 O(N²),Bradley-Terry 排名,`pivots` 控成本/精度,内部 ring pass 去位置偏。→ 这是 SW `p5 --rerank` 的未来选优内核,也是语料盲测对打的排名器。
- **criteria**:接受 dict 或 `criteria/*.md` 文件 → 我们把 SW rubric 六轴每轴拆成信号级子问题,一轴一个 md。
- **`ground_truth_note` 参数存在,但本仓禁用**——考试时喂 GT 等于把答案泄漏给判官。
- **成本特性**:score 缓存(`cache=`)、`token_usage()` 记账、前缀缓存优化(~3.4× 省输入 token)。

## 后端要求(关键约束)

端点必须是**返回 logprobs 的 OpenAI 兼容 API**。官方验证过:DeepSeek API、Gemini、`vllm serve`(如本地 `Qwen/Qwen3.5-9B`)。
- L-07 第一步:实测 dashscope 兼容模式是否返回 logprobs;不返回则 dev 判官走本地 vllm。
- sealed 判官默认 DeepSeek(与生成家族 Qwen 不同族,满足交叉锚)。
- 降级路径(任何端点都不给 logprobs):k 采样投票,按 `contract/judges.yaml::scoring_fallback`,必须有测试。

## 官方自验证数据点(支撑"dev 判官可降档")

Terminal-Bench 2.1:同一模型(deepseek-v4-flash)生成 5 条轨迹并自验选优,Best-of-5 达 88.0%(Pass@1 仅 78.7%,Oracle 96.6%)。即**弱模型 + 采样 + 细粒度验证**在"选优"上确实逼近强模型——但注意这是可验证任务,且 Oracle 仍有 8pp 差距。所以本仓:dev 判官可中档 × k;sealed 不降档、跨家族;一切判官先过退化考试。

## 我们的封装层(`lab.judgekit`,L-07)

1. `score_pair(a, b, axis, judge_cfg)`:内部两次 directed `compare` 取平均;criteria 取该轴的信号级 md。
2. 语料盲测对打/rerank:`select` + PPT,`cache=` 指向 `out/judge_cache/`。
3. 考试 `run_exam`:对 exam split 构造对跑灵敏度/传递性/位置偏差/跨家族一致,对照 `contract/judges.yaml::exam` 门限。
4. 所有调用经 `lab.models` 路由写 transcript;`token_usage()` 并入成本账本。
