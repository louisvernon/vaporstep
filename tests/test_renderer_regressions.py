"""Small static regressions for renderer-only paths not exercised in headless CI."""

from __future__ import annotations

import ast
from pathlib import Path


def test_receptor_renderer_has_no_removed_timing_hint_references() -> None:
    source = Path("vaporstep/renderer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    receptor = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_draw_receptors"
    )
    loaded_names = {
        node.id
        for node in ast.walk(receptor)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }

    # EARLY/LATE receptor hints were removed in v0.13.6. A stale blit of
    # `hint`/`hint_y` caused calibration to crash whenever input_flash fired.
    assert "hint" not in loaded_names
    assert "hint_y" not in loaded_names
