# ADR-0008：EditClassify 判定标准落盘为 spec 资产

- 状态：accepted（2026-08-16 由负责人确认；判定标准作为 spec 资产落盘）
- 日期：2026-08-16
- 影响层：A2 规则/标准（新增 `spec/feedback/edit_classify_rubric.yaml`，无 schema 变化）

## 背景
T-11 反馈摄入流水线需要对每处客户编辑做八维语义分类（D11）。
硬约束禁止在 Python 里写自然语言业务判定（"台词要口语化"这类知识），
要求分类标准/示例进 `spec/rubrics/` 或 `spec/checks/`。

## 决定
分类判定标准（八维定义与信号、verdict 四值、severity 1–5 锚点、few-shot 示例、
"完全重写"段的同节点归并判据）全部落盘到 `spec/feedback/edit_classify_rubric.yaml`。
`src/nsc/feedback/classify.py` 只做编排：加载 rubric → 拼 prompt → 经
`src/nsc/runtime/models.py` 路由调用 → 按 rubric 声明的合法值集合校验输出。
代码中不出现任何维度定义文本。

## 被否决的替代
| 替代 | 为什么否决 |
|---|---|
| 判定标准写进 classify.py 的 prompt 常量 | 违反 AGENTS.md §2：自然语言知识必须进 spec，否则 GEPA/挖掘无法演化它 |
| 复用 `spec/checks/**` 的 DSL 表达分类 | 分类是语义判定而非可执行断言，DSL 表达不了"叙事功能是否相同" |

## 对下游的约束
- 修改 rubric 的维度定义 = 改资产，需要 ADR + evidence。
- `dimension`/`verdict` 的合法值集合以 rubric 为准，与 `db/migrations/0001_init.sql`
  的 CHECK 约束保持同步；新增维度必须先改 schema migration（另开 ADR）。

## 迁移
无（新增文件，无数据变化）。

## 验证
`make spec-guard` 全绿；`tests/test_ingest.py` 以 stub 路由验证八维各至少一条落库。
