"""Narrative Spec Compiler (nsc)."""

import sys
from pathlib import Path

# spec/ 是资产层（非 pip 包）。从仓库根运行 CLI 时必须可 import spec。
_ROOT = Path(__file__).resolve().parents[2]
if (_ROOT / "spec").is_dir() and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

__version__ = "0.1.0"
