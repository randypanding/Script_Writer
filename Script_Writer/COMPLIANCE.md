# 合规与法务边界（D30）

## 1. 逆向标注（`nsc annotate`）
**允许入库**：Narrative IR（结构、Beat 类型、植入位置、情绪值）、统计量、`source_url` + `source_title`、**每节点 ≤50 字**的引用片段（用于人工核验标注是否正确）。
**禁止入库**：完整字幕/转写文本、视频/音频文件、完整台词。
**禁止用途**：`counterexamples` 与 `retrieval_pool` 中的片段**不得**出现在任何交付物中。`nsc check` 内置 `FCT-002` 规则：交付文本与 `cases` 中 source 片段的最长公共子串 > 12 字 → block。

## 2. 广告合规
`spec/checks/compliance/` 中的绝对化用语、功效承诺清单来自公开法规整理，**必须由人工（你）逐条核对后才可标 `severity: block`**。新增此类规则的 PR 必须在描述中给出法条/官方指引出处，CI 会检查 `legal_ref` 字段非空。

## 3. 客户资产
`brands/<client>/` 含商业机密。若仓库将来开源或外协，`brands/` 必须走 submodule 或私有 overlay（见 `adr/0007-brands-isolation.md`）。

## 4. 交付物权属
交付给商家的小说/剧本，其著作权归属在 `brands/<client>/brand.yaml::legal.ip_assignment` 声明；`nsc render` 会把该声明写入 docx 页脚。