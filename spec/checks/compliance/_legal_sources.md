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
- 影响规则：`CMP-003`（尚未启用）