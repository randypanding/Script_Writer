# Developing 分支交接 · 最新成果与遗留问题（2026-08-31）

> 本分支 = `origin/main` + 战役全部本地提交（PR #16 机器 + round28 craft_shape + CRAFT-001 修复）。
> 配套仓库 `Script_Writer_Lab`（优化游乐场）已同步推送同名 `Developing` 分支：
> round27/28 台账、分题材锚 v2.1、CNB 配额手册 §7 纠正版都在那边。

## 1. 最新成果（本轮接手完成）

### 1.1 题材工艺形状 craft_shape（SW 4a8bbe6 + 01c3856，ADR-0019）

- `spec/craft_shape.yaml`：题材关键词检测 + 每题材一张形状卡
  （antagonist_required / ensemble_scene_required / hook_types / stakes_escalation / arousal_peak / ending_beats）。
  默认形状 `爆款通用` 与现行正向契约逐字节一致；非默认桶现仅 `治愈成长`（Lab 治愈锚 v2）。
- `_make_ctx` 把形状并入 `ctx.profile["craft_shape"]`，随 profile_json 注入每个 Pass；
  p1/p2/p4 种子指令与 p3 编译版（round28 provenance）同步参数化。
- **CRAFT-001 题材豁免**（01c3856）：修复两处缺陷——JMESPath 的 `||` 对布尔 false 回退右值
  （`false || true = true` 吞掉豁免），bind 改 `!= \`false\`` 比较；assert 反逻辑（丢 `not`）。
  旧配置无 craft_shape 时行为与修复前完全一致（fixture 双向测试锁定）。
- **验证**（南浪仔全链路跑批，attempt3 全绿 70min）：IR 角色表无 antagonist
  （protagonist/customer_proxy/ally/foil），hook 出现【悬】【承】温和标注——治愈形状原生落地；
  fresh 标注卡（n=6）vs 治愈锚 0.835 / vs 复仇锚 0.531，与 v4 champion 的 0.876 在薄卡噪声带内等价。
  champion 维持 v4（Lab round28 台账）。

### 1.2 W4 泛化验证结论（negative result，已入台账）

demo_tea（第二个真实 brief）用 champion 配置 5 个 attempt **五种不同门禁死法**：
p2 空 hook_promise×6 集 → DLG-006 对白偏短×2 轮 → CMP-002 疗效表述 → p6 anchor_map 幻觉 line_id。
**一过能力不迁移**：harness 硬化是 brief 特异的（南浪仔吃了 round8-25 全部加固，demo_tea 没有）。
新 brief 上线需要自己的加固周期，或付费后端。

### 1.3 CNB 免费通道降配真解（Lab d2ccda4 + 镜像仓 471a41f）

- **机制实证**：只有"自定义 NPC"才合并其所属仓 `.cnb.yml` 的 `runner.cpus: 1`；
  `@CodeBuddy`（系统 NPC）走平台默认流水线 **8 核计费**。此前所有生成/标注任务 8× 超耗，
  原手册"nproc=1"验证系假阳性（cgroup quota 实为 800000）。
- **部署**：主池 `zhuzhu-team/swarm-pool`（判官+写手两角色，30 窗口）；
  写手人格带"数字目标硬指标"纪律（实测治好 DLG-006 对白系统性偏短 ~17%）；
  生成/标注/shim 全部 mention 已切写手；旧池 `Cloudbird-Software/swarm-pool` 转备用（100 窗口仍在）。
- 纠正版机制与成本口径：Lab 仓 `docs/CNB_QUOTA_PLAYBOOK.md` §7。

### 1.4 度量侧（Lab round27）

- `金榜题名之寒门状元` k=2 双标复核改判 治愈成长→复仇爽文（单跑分类误差）；
  锚表 v2.1 改为 `scripts/compute_anchors.py` 可复现生成（六个未变动桶五维与冻结值逐项一致）。
- `corpus_extract.py` 双修：带属性 `<w:p>` 剥壳残渣 + 场号 `x-1` 分集兜底（回归测试锁定，Lab 6e349da）。
- champions.yaml v4 条目补 `anchor_version`/`anchor_scores` 字段（W1.5 验收收口）。

## 2. 遗留问题（需要 owner 处理）

| # | 问题 | 需要的动作 |
|---|---|---|
| 1 | `Script_Writer_Lab` 的 `contract/.seal.lock.json` 与 judges/objective.yaml 失配（契约 v2 更新后未重封印，Lab CI 第三防线常红） | 在有 `LAB_SEAL_KEY` 的机器上执行 `uv run python -m lab.contract_guard seal contract` |
| 2 | W2 sealed 判官（跨家族校验重刻基线）整卡待付费 key | 提供任一付费 LLM key（lab.toml judge_sealed 槽位） |
| 3 | 治愈成长锚仅 1 部 15 卡（provisional），语料内已确认无第二部治愈作品 | 投放治愈系剧本/小说到 Lab 仓 `corpus/inbox/`，重跑 W1.2 标注即可自动加厚 |
| 4 | CNB 全权限令牌明文在 Lab 仓 `.env`（gitignored，但注意本机安全）；旧池令牌备份于同文件注释 | 如泄露可随时在 cnb.cool 撤换 |
| 5 | SW 本地 `config/models.yaml` 的 api_base 指向 `127.0.0.1:8400`（本机 CNB shim，未提交——端点配置非密钥） | 本地跑批前先起 shim：Lab 仓 `bash scripts/supervise.sh shim_service uv run python -m lab.cnb_shim` |

## 3. 下轮候选（按期望值，详见 Lab 台账 round28 notes）

1. **demo_tea 专项加固轮**：把 W4 实证的五类死因逐个变机械兜底（round14 方法论：结构性约束一律机械兜底）；
   其中 p6 anchor_map 幻觉 line_id 最适合先做（机械校验前置，成本最低）。
2. **治愈锚补料重标**（卡 owner 语料投放）：锚厚了才能下"治愈系工艺是否饱和"的结论。
3. **sealed 判官**（卡付费 key）：craft_bench 与判官轴的分歧（round24 遗案）只有它能仲裁。

## 4. 本分支提交索引

- `4a8bbe6` craft_shape 题材参数化（ADR-0019）
- `01c3856` CRAFT-001 豁免双缺陷修复
- （Lab 仓）`14dfd8d` round27 度量复核 / `d2ccda4` CNB 切换 / `6e349da` 切分器测试 /
  `d38b1dd` round28 台账 / `6a47ea5` v5 产物归档
