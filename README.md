# NSC · Narrative Spec Compiler

把「写小说 / 写剧本」变成**编译**：`spec/` 是源码，小说、剧本、prompt、代码都是编译产物。

- 业务：为商家生成可直接发在自有短视频账号的**营销短剧**。先出**小说**（商家确认物），再出**剧本**（制作团队执行物）。
- 视频拍摄/剪辑由外部制作团队负责，本系统**不做视频生成**。

## 快速开始
```bash
uv sync
make db-rebuild                 # 从 cases/export/*.jsonl 重建 SQLite（案例检索层需要；--no-retrieval 可跳过）
make test-fast                  # 不调用 LLM 的全部门禁
```

**配置 LLM 端点（唯一外部依赖）**：`config/models.yaml` 各 tier 的 `api_base` 指向任一
**OpenAI 兼容端点**（默认 LongCat-2.0），`export OPENAI_API_KEY=<key>`（绝不落盘）。

```bash
uv run nsc run examples/demo_tea/brief.yaml --profile short_drama_v1
# 产物在 out/<标题>/：novel.md(小说) + script.md(剧本) + ir.json(全量 IR) + manifest.json(溯源)
nsc check out/<标题>/ir.json    # L0 检查
nsc render out/<标题>/ir.json   # 重新渲染交付物
```

## 独立使用说明（本仓库无外部仓库依赖）

本仓库即是完整可用的短剧/小说生成器：7 段编译管线（p0 需求归一→p6 小说→p7 渲染）、
82 条声明式门禁（`spec/checks/`）、相位内带诊断重试、以及一组**后端无关的机械兜底**
（结构修复/时长缩放/对白欠量扩写/暗线钳制/合规词替换等，在 `src/nsc/passes/`，
只对违规形态触发，换任何 LLM 都生效）。

- **换后端**：只改 `config/models.yaml` 的 `api_base`（参考 `config/models.yaml.bak`）。
  2026-08 Lab 战役期间该文件曾指向本地 shim（`127.0.0.1:8400`），独立使用时改回真实端点即可。
- **新品牌/新故事**：复制 `brands/demo_tea/` 与 `examples/demo_tea/brief.yaml` 改内容。
  注意：目录名 = `brand_id`；`banned_words` 不得与 `products.facts` 冲突；
  `canonical_name` 必须是最自然的写法（它会被 BM-009 当成唯一合法产品名）。
  现成第二套范例：`brands/hainan_nolan/` + `examples/hainan_nolan/brief.yaml`（海南文旅 IP）。
- **profile 决定形态**：`profiles/short_drama_v1.yaml`（6-12 集正片）、
  `profiles/lab_smoke_v1.yaml`（迭代切片）；`novel.enabled` 控制是否出小说视图。
- **全量测试**：`uv run pytest tests --ignore=tests/test_pipeline_llm.py`（无 LLM，597 个）。
- **分支说明**：2026-08 Lab 优化战役的 10 轮 harness 硬化（round14-20d，
  全部带测试）在分支 `sw/lab-campaign-20260825`；配套的判分/游乐场设施在私有仓
  Script_Writer_Lab（非必需，仅质量测量与优化循环用）。

## 三条铁律
1. **`spec/` 是唯一真相。** 任何知识若不能落进 `spec/ir | spec/checks | spec/rubrics | spec/rules | profiles | brands`，视为不存在。
2. **`prompts/`、`src/`、`out/` 是生成物。** 手改 `prompts/` = CI 失败。重写 `src/` 必须能通过同一套 `tests/`。
3. **反馈必须锚定到节点 ID。** 无 `node_id` 的反馈不入库。

详见 [AGENTS.md](AGENTS.md)、[docs/ENGINEERING_PLAN.md](docs/ENGINEERING_PLAN.md)、[docs/BORROW_MAP.md](docs/BORROW_MAP.md)。