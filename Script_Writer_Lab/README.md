# Script_Writer_Lab · 游乐场

为 `../Script_Writer`(交付物仓库)提供三件事:**"好"的定义(指标注册表)、外部固定契约(sealed 评测)、自优化实验场(OEO 循环)**。
本仓库不产出任何客户交付物;交付物仓库对本仓库是**只读依赖**(pinned checkout,路径见 `lab.toml`)。

## 三条铁律

1. **`corpus/` 只进不出。** 剧本原文永不提交 git、永不复制进交付物仓库、优化 agent 永不接触原文;只有 `mined/` 下的**聚合洞察**(统计分布、规则候选、词典)可进 git。CI 有泄漏守卫(`make guard`)。
2. **`contract/` 是外部固定契约。** 优化器只读;任何改动需人类确认 + ADR;sealed 文件带哈希锁,篡改即 `lab contract verify` 失败。
3. **洞察回流交付物只有一条路:对 `../Script_Writer` 提 PR**,走它自己的 ADR + spec-guard 流程。

## 快速开始

```bash
uv sync
cp .env.example .env        # 填三个模型家族的 key(生成 / dev 判官 / sealed 判官)
# 把剧本放进 corpus/inbox/(任意格式,只进不出)
make ci
```

## 今夜状态

仓库为 **IR + 工单卡 + 红测试** 形态:`src/lab/` 为空,`tests/` 四个文件全红(ImportError 即红)。
开发顺序见 `docs/WORK_ORDERS.md`(L-00 → L-15),治理见 `AGENTS.md`,设计宪法见 `adr/0001-lab-constitution.md`。
所有工作在 `feature/lab-bootstrap` 分支上进行,`make ci` 全绿才合 main。
