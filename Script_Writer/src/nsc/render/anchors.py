"""D29 三级锚点：让渲染出的交付物能 `段落 → node_id` 反向恢复。

锚点用途：客户在 docx 里改的每一段，必须能映射回 IR 的稳定 node_id，
否则反馈回流（T-10/T-11）会把第 5 集的改动记到第 2 集上。

三级策略（可靠性递减）：
  L1 书签：docx 内 `NID_<ulid>` 书签直接给出 node_id（最可靠）。
  L2 附录：文末"锚点索引表"（段落序号 ↔ node_id），用户删表则失效。
  L3 模糊：把交付段落序列与回收文本序列做单调对齐（rapidfuzz），
          在对齐成功的段上恢复 node_id。

本模块只定义统一的数据结构与 L2 表的读写；L1 书签的读写落在 docx.py，
L3 对齐落在 feedback/align.py。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 书签/锚点名前缀。`NID_<ulid>` 即一段交付文本的稳定节点 ID。
BEACON_PREFIX = "NID_"


@dataclass(slots=True)
class Paragraph:
    """一段交付文本 + 它锚定的节点 ID。

    `node_id` 为 None 时表示"新增/游离"段（无锚点，如客户自己加的段）。
    """

    node_id: str | None
    text: str
    kind: str = "paragraph"  # novel_paragraph | line | scene_heading ...


@dataclass(slots=True)
class AnchorIndex:
    """L2 附录表：段落序号 ↔ 节点 ID。按段落顺序排列。"""

    entries: list[tuple[int, str]] = field(default_factory=list)  # [(paragraph_no, node_id)]

    def to_text(self) -> str:
        lines = ["# 锚点索引（段落序号 ↔ 节点 ID）", "序号\t节点ID"]
        for no, nid in self.entries:
            lines.append(f"{no}\t{nid}")
        return "\n".join(lines)

    def node_id_for(self, paragraph_no: int) -> str | None:
        for no, nid in self.entries:
            if no == paragraph_no:
                return nid
        return None


def beacon_for(node_id: str) -> str:
    """节点 ID → 书签名。"""
    return f"{BEACON_PREFIX}{node_id}"


def node_id_from_beacon(name: str) -> str | None:
    """书签名 → 节点 ID；非锚点书签返回 None。"""
    if name.startswith(BEACON_PREFIX):
        return name[len(BEACON_PREFIX) :]
    return None
