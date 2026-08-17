"""revise 模块（T-32）：spot-fix patch 引擎 / revisionGate 三档 / SQLite 快照链 / Idea Bank。

全部确定性、无 LLM 调用；LLM 只在模块外产出 PATCH 文本，由 parse_patches 接管。
"""

from __future__ import annotations

from nsc.revise.gate import Counts, decide
from nsc.revise.idea_bank import deposit, list_ideas, render_for_prompt, revive
from nsc.revise.patch import Patch, PatchResult, apply_patches, parse_patches
from nsc.revise.snapshot import best_snapshot, list_snapshots, rollback_to, save_snapshot

__all__ = [
    "Counts",
    "Patch",
    "PatchResult",
    "apply_patches",
    "best_snapshot",
    "decide",
    "deposit",
    "list_ideas",
    "list_snapshots",
    "parse_patches",
    "render_for_prompt",
    "revive",
    "rollback_to",
    "save_snapshot",
]
