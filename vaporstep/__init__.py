"""VaporStep webcam full-body rhythm game."""

import os

# Pygame prints a support banner on import unless this is set first. Keeping it
# at package import level covers `python -m vaporstep`, the console script, and
# the frozen PyInstaller launcher.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from ._version import __version__
from .simfile_encoding import install_simfile_encoding_detection

install_simfile_encoding_detection()

# Keep song-library rendering separate from the large gameplay renderer while
# still installing one authoritative draw pass for every entry point.
from .song_menu_renderer import install_song_menu_renderer

install_song_menu_renderer()

__all__ = ["__version__"]
