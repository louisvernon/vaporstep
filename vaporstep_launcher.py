"""PyInstaller entry point for VaporStep.

Keep this outside the package so frozen execution does not treat
vaporstep/__main__.py as an unparented standalone module.
"""
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from vaporstep.player_visual_runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
