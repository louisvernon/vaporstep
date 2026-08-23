"""VaporStep webcam full-body rhythm game."""

import os

# Pygame prints a support banner on import unless this is set first. Keeping it
# at package import level covers `python -m vaporstep`, the console script, and
# the frozen PyInstaller launcher.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from .font_support import install_unicode_font_fallback
from ._version import __version__

install_unicode_font_fallback()

__all__ = ["__version__"]
