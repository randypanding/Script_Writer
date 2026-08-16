---
name: 规则候选（人工发起）
about: 你从一次交付里看出了一个规律，想让它进规则库
labels: [rule-candidate, asset-change]
---
## 规则陈述（必须可判定）
> 格式："当 X 时，应该 Y"。不可判定的写法（"应该更自然"）会被打回。

## 证据（≥3 条，来自 ≥2 个 case）
- case:____ node:____ ：
- case:____ node:____ ：
- case:____ node:____ ：

## 形态（D2 三形态）
- [ ] `schema` → 改 `spec/ir/`（需 ADR）
- [ ] `check` → 新增 `spec/checks/**.yaml`（附 select/assert 草案）
- [ ] `rubric` → 新增/修改锚定样例
- [ ] `prompt` → 进 `L3_canonical` 且 `form: prompt`
- [ ] `profile_default`

## scope（最小可支撑范围）
- [ ] global  - [ ] format:____  - [ ] industry:____  - [ ] client:____

## 反例（这条规则什么时候不适用）

## 这条是"品味"还是"规律"？
若只反映某个客户的偏好 → **必须** `scope: client`（TAXONOMY 的 taste 隔离）。