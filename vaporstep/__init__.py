"""VaporStep webcam full-body rhythm game."""

import os

# Pygame prints a support banner on import unless this is set first. Keeping it
# at package import level covers `python -m vaporstep`, the console script, and
# the frozen PyInstaller launcher.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from ._version import __version__

# Keep song-library-only polish out of the large gameplay renderer while still
# applying it consistently to the console entry point and frozen builds.
from .song_menu_overlay import install_song_menu_overlay

install_song_menu_overlay()

__all__ = ["__version__"]
