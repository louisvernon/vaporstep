"""VaporStep webcam full-body rhythm game."""

import os

# Pygame prints a support banner on import unless this is set first.  Keeping it
# at package import level covers `python -m vaporstep`, the console script, and
# the frozen PyInstaller launcher.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

__version__ = "0.13.7"
