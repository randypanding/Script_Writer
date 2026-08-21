# Script_Writer · 组织仓(双文件夹布局)

本仓是组织级聚合仓,**已决策**:交付物项目与实验场项目分两个文件夹保存,各自保留完整的工程结构(各自的 pyproject/Makefile/AGENTS.md,独立 CI)。

| 文件夹 | 项目 | 角色 |
|---|---|---|
| [`Script_Writer/`](Script_Writer/) | 交付物仓本体(SW) | spec 即源码的短剧编译器(`nsc`);治理完备,L0~L3 规则 + 判官协议 |
| [`Script_Writer_Lab/`](Script_Writer_Lab/) | 质量契约与自优化实验场(Lab) | 为 SW 提供退化锚/语料锚/判官考试,承载 M1/M2 优化循环(见其 `adr/0001-lab-constitution.md`) |

## 两仓关系(ADR: Lab L-D1 仓内外分离)

- Lab 对 SW 是 **pinned 只读依赖**:只能 subprocess 调 SW checkout 的 `uv run nsc ...`,禁止 import。
- 洞察回流只走对 `Script_Writer/` 的 PR(SW-xx 上游卡)。
- Lab 的 `corpus/`、`transcripts/` 永不入库(泄漏守卫拦截)。

## CI

- `Script_Writer/`:lint/typecheck/spec-guard/tests/golden(见 `.github/workflows/ci.yml`)。
- `Script_Writer_Lab/`:`make ci`(lint + pytest + corpus 泄漏守卫)。
- 周期任务(判官校准/规则挖掘/飞轮面板)均在 `Script_Writer/` 上下文执行。

各文件夹内的开发规矩见各自的 `AGENTS.md`。
