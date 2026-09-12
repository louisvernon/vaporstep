"""VaporStep webcam full-body rhythm game."""

import os

# Pygame prints a support banner on import unless this is set first. Keeping it
# at package import level covers `python -m vaporstep`, the console script, and
# the frozen PyInstaller launcher.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from ._version import __version__

# The browser prototype deliberately imports only the platform-neutral domain
# model plus its own pygame-ce renderer. Desktop startup retains the historical
# import-time integrations, while the staged WASM bundle does not need to carry
# simfile/rendering modules that eventually pull in native OpenCV/NumPy pieces.
if os.environ.get("VAPORSTEP_WEB") != "1":
    from .simfile_encoding import install_simfile_encoding_detection

    install_simfile_encoding_detection()

    # Keep song-library rendering separate from the large gameplay renderer while
    # still installing one authoritative draw pass for every desktop entry point.
    from .song_menu_renderer import install_song_menu_renderer

    install_song_menu_renderer()

__all__ = ["__version__"]
