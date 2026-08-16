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
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz

from nsc.render.anchors import Paragraph

EditType = Literal["insert", "delete", "replace", "move", "comment"]
AnchorLevel = Literal["bookmark", "appendix", "fuzzy", "failed"]

_GAP = -2.0
# 低于该相似度的段落不做 match，一律按 delete+insert 处理。
# 否则段落重排/整段删除时，DP 会把"不同但字形相似"的段落误配成 replace，
# 把改动记到错误的 node_id 上（D10：反向对齐优先级高于生成质量）。
# 0.7 的经验值：标点类改动(~0.75)与同句改写(~0.85)可保留 node_id；
# 完全重写(<0.5)超出确定性对齐能力，交给强模型（EditClassify）判定。
_MIN_MATCH = 0.7
_REJECT = -1e9


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


def _sim(a: str, b: str) -> float:
    """归一化相似度 [0,1]。"""
    return fuzz.ratio(a, b) / 100.0


def _match_score(a: str, b: str) -> float:
    """DP 的 match 打分。低于 _MIN_MATCH 视为不可信匹配 → 极负分，逼迫走 gap。

    这样段落重排/重写导致的"字形相似但非同一段"不会被误配成 replace。
    """
    s = _sim(a, b)
    return s if s >= _MIN_MATCH else _REJECT


def align_paragraphs(
    delivered: list[str], returned: list[str]
) -> list[tuple[int | None, int | None]]:
    """单调对齐。返回 (delivered_idx, returned_idx) 对，None 表示增/删。

    禁止用贪心最近邻——那会在段落重排时崩掉。必须 DP。
    Needleman-Wunsch：match = 相似度，indel = 固定罚分，保持顺序单调。
    """
    n, m = len(delivered), len(returned)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = _GAP * i
    for j in range(1, m + 1):
        dp[0][j] = _GAP * j

    for i in range(1, n + 1):
        di = delivered[i - 1]
        for j in range(1, m + 1):
            match = _match_score(di, returned[j - 1])
            dp[i][j] = max(match + dp[i - 1][j - 1], dp[i - 1][j] + _GAP, dp[i][j - 1] + _GAP)

    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            match = _match_score(delivered[i - 1], returned[j - 1])
            if abs(dp[i][j] - (match + dp[i - 1][j - 1])) < 1e-9:
                pairs.append((i - 1, j - 1))
                i -= 1
                j -= 1
                continue
        if i > 0 and abs(dp[i][j] - (dp[i - 1][j] + _GAP)) < 1e-9:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def recover_anchors(
    returned_paragraphs: list[str],
    delivered_paragraphs: list[Paragraph],
) -> list[EditRecord]:
    """把回收段落序列对齐到交付段落（带 node_id），产出 EditRecord。

    同一段交付文本未被改动 → 不产生记录；被改动 → replace；
    交付有而回收无 → delete；回收有而交付无 → insert（node_id=None）。
    锚点层级一律 fuzzy（L3）——本函数只做段落级对齐，不做书签级。
    """
    delivered_texts = [p.text for p in delivered_paragraphs]
    pairs = align_paragraphs(delivered_texts, returned_paragraphs)

    records: list[EditRecord] = []
    for d_idx, r_idx in pairs:
        if d_idx is not None and r_idx is not None:
            before = delivered_texts[d_idx]
            after = returned_paragraphs[r_idx]
            if before == after:
                continue
            conf = _sim(before, after)
            records.append(
                EditRecord(
                    node_id=delivered_paragraphs[d_idx].node_id,
                    anchor_level="fuzzy",
                    anchor_confidence=conf,
                    edit_type="replace",
                    before=before,
                    after=after,
                )
            )
        elif d_idx is not None:
            before = delivered_texts[d_idx]
            records.append(
                EditRecord(
                    node_id=delivered_paragraphs[d_idx].node_id,
                    anchor_level="fuzzy",
                    anchor_confidence=0.0,
                    edit_type="delete",
                    before=before,
                    after="",
                )
            )
        else:
            assert r_idx is not None  # 对齐器保证 (None, None) 不会出现
            after = returned_paragraphs[r_idx]
            records.append(
                EditRecord(
                    node_id=None,
                    anchor_level="fuzzy",
                    anchor_confidence=0.0,
                    edit_type="insert",
                    before="",
                    after=after,
                )
            )
    return records


def extract_revisions(path: Path) -> list[dict]:  # 已在 docx_revisions 实现
    from nsc.feedback.docx_revisions import extract_revisions as _extract

    _, ops = _extract(path)
    return [op.__dict__ for op in ops]


def ingest(path: Path, *, case_id: str, auto_classify: bool = True) -> list[EditRecord]:
    """端到端。T-11 实现；本阶段只做恢复锚点。"""
    raise NotImplementedError("T-11")
