# 合规词表出处（人工核对台账）

> ⚠️ 本文件中的每一项在标为 `severity: block` 前，必须由你（人类）核对官方出处并在此登记日期。
> CI（`nsc.guards.checks_schema`）要求 `domain: compliance` 的规则 `legal_ref` 非空且指向本文件的锚点。

## absolute-terms
绝对化用语（"国家级/最高级/第一/唯一/最佳/绝无"等）。
- 出处：待登记（人工核对广告相关法规与平台规则后填写条款号与链接）
- 核对人 / 日期：（待填）
- 词表文件：`spec/checks/compliance/absolute_terms.yaml`

## health-claims
功效/疗效类表述（"治疗/根治/降血糖/防癌"等）。
- 出处：待登记
- 核对人 / 日期：（待填）
- 词表文件：`spec/checks/compliance/regulated_claims.yaml`

## 平台规则
各短视频平台对商业内容的标注要求（如是否需标记"广告"）。
- 出处：待登记
- 影响规则：内容标注类要求尚未建规则（建规则时在此登记）

## platform-rules
平台内容安全词表（暴恐血腥毒品 / 露骨性描写 / 现实政治影射 / 现实迷信宣扬 / 校园霸凌细节）。
- 出处：开源项目 novel-distiller 的 `platform.py` `TOMATO_RULES must_avoid`（番茄小说平台公开审核口径的开源整理，ADR-0011 / T-29 引入）
- 核对人 / 日期：（待人工复核平台最新审核口径后登记；`CMP-006`/`CMP-007` 在复核前保持 warn）
- 词表文件：`spec/checks/compliance/_platform_terms.yaml`
- 影响规则与词表对应：
  - `CMP-003`（block）← `violent_terms` 暴恐/血腥/毒品
  - `CMP-004`（block）← `explicit_terms` 露骨性描写
  - `CMP-005`（block）← `political_terms` 现实政治影射
  - `CMP-006`（warn）← `superstition_terms` 现实迷信宣扬（奇幻设定不禁）
  - `CMP-007`（warn）← `bullying_terms` 校园霸凌细节描写