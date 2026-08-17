from __future__ import annotations

from pathlib import Path
import sys


def resource_path(relative: str | Path) -> Path:
    """Return a source-tree or PyInstaller bundle resource path."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / Path(relative)
