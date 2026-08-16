# NSC · Narrative Spec Compiler

把「写小说 / 写剧本」变成**编译**：`spec/` 是源码，小说、剧本、prompt、代码都是编译产物。

- 业务：为商家生成可直接发在自有短视频账号的**营销短剧**。先出**小说**（商家确认物），再出**剧本**（制作团队执行物）。
- 视频拍摄/剪辑由外部制作团队负责，本系统**不做视频生成**。

## 快速开始
```bash
uv sync
make db-rebuild                 # 从 cases/export/*.jsonl 重建 SQLite
make test-fast                  # 不调用 LLM 的全部门禁
nsc run --brief examples/demo_tea/brief.yaml --profile short_drama_v1
nsc check out/demo_tea/ir.json  # L0 检查
nsc render out/demo_tea/ir.json --target novel_docx script_fountain
```

## 三条铁律
1. **`spec/` 是唯一真相。** 任何知识若不能落进 `spec/ir | spec/checks | spec/rubrics | spec/rules | profiles | brands`，视为不存在。
2. **`prompts/`、`src/`、`out/` 是生成物。** 手改 `prompts/` = CI 失败。重写 `src/` 必须能通过同一套 `tests/`。
3. **反馈必须锚定到节点 ID。** 无 `node_id` 的反馈不入库。

详见 [AGENTS.md](AGENTS.md)、[docs/ENGINEERING_PLAN.md](docs/ENGINEERING_PLAN.md)、[docs/BORROW_MAP.md](docs/BORROW_MAP.md)。