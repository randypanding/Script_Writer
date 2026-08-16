"""反向对齐器（D10）—— 优先级高于生成质量（决策文档第十五章第 2 条）。

输入：客户回收的 docx（可能带修订）/ 纯文本 / 微信消息
输出：list[EditRecord]，每条锚定到一个 node_id

## 三级锚点恢复（D29）
L1 bookmark：docx 中 `NID_<ulid>` 书签 → 直接得到 node_id。最可靠。
L2 附录索引：文末"锚点索引"表（段落序号 ↔ node_id）。用户删表则失效。
L3 模糊回退：把交付时的段落序列与回收文本的段落序列做**单调对齐**
             （Needleman-Wunsch，打分函数 = rapidfuzz 归一化相似度），
             再在对齐段内做句级二次对齐。

L3 必须保持单调（段落顺序不可交叉），否则会把第 5 集的改动记到第 2 集上。
这是整个模块最容易出错的地方，`tests/test_align.py` 必须覆盖：
  - 整段删除 / 整段新增 / 段落顺序调整 / 大幅重写 / 只改标点

## 修订提取
优先直接解析 OOXML 的 w:ins / w:del / w:comment（拿到作者与时间戳）。
pandoc --track-changes=all 作为兜底。见 docs/BORROW_MAP.md #18。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

EditType = Literal["insert", "delete", "replace", "move", "comment"]
AnchorLevel = Literal["bookmark", "appendix", "fuzzy", "failed"]


@dataclass(slots=True)
class EditRecord:
    node_id: str | None
    anchor_level: AnchorLevel
    anchor_confidence: float
    edit_type: EditType
    before: str
    after: str
    human_comment: str = ""
    author: str = ""
    # 由 EditClassify 填充，人工在 Langfuse 确认
    dimension: str | None = None
    severity: int | None = None
    rule_hint: str = ""


def extract_revisions(path: Path) -> list[dict]: ...            # T-10
def recover_anchors(edits: list[dict], delivered_ir_path: Path) -> list[EditRecord]: ...  # T-10
def align_paragraphs(delivered: list[str], returned: list[str]) -> list[tuple[int | None, int | None]]:
    """单调对齐。返回 (delivered_idx, returned_idx) 对，None 表示增/删。

    禁止用贪心最近邻——那会在段落重排时崩掉。必须 DP。
    """
    raise NotImplementedError("T-10")


def ingest(path: Path, *, case_id: str, auto_classify: bool = True) -> list[EditRecord]:
    """端到端。产出：
      - feedback 表（D9 五元组）
      - revision_pairs（before/after/dimension）
      - preference_pairs（原文 vs 改后，人类偏好=改后）
      - L0 observations（spec/rules/L0_observations/*.yaml）
      - Langfuse annotation queue 条目（供你 30s 批量确认）
    验收：`tests/test_align.py::test_end_to_end_ingest` 中，
          对 fixtures/ingest/demo_tea_round1.docx 恢复出 ≥90% 的编辑且 node_id 正确。
    """
    raise NotImplementedError("T-11")