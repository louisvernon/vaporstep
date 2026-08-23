from __future__ import annotations

"""Unicode fallback for Pygame's bundled default font.

VaporStep's fixed UI deliberately uses Pygame's compact bundled font. That font
has limited glyph coverage, however, which is noticeable for user-supplied song
metadata. This shim keeps the bundled font for ASCII text and uses a suitable
system font only when text contains non-ASCII characters.
"""

import pygame


_FONT_CANDIDATES = (
    "Noto Sans CJK JP",
    "Noto Sans CJK SC",
    "Noto Sans",
    "Arial Unicode MS",
    "Segoe UI",
    "DejaVu Sans",
    "Arial",
    "Helvetica",
)
_original_font = pygame.font.Font
_installed = False


def _find_fallback_font() -> str | None:
    for name in _FONT_CANDIDATES:
        path = pygame.font.match_font(name)
        if path:
            return path
    return None


class _UnicodeFallbackFont:
    def __init__(self, size: int) -> None:
        self._primary = _original_font(None, size)
        fallback_path = _find_fallback_font()
        self._fallback = _original_font(fallback_path, size) if fallback_path else self._primary

    @staticmethod
    def _needs_fallback(text: object) -> bool:
        return isinstance(text, str) and any(ord(char) > 127 for char in text)

    def render(self, text, *args, **kwargs):
        font = self._fallback if self._needs_fallback(text) else self._primary
        return font.render(text, *args, **kwargs)

    def size(self, text):
        font = self._fallback if self._needs_fallback(text) else self._primary
        return font.size(text)

    def __getattr__(self, name):
        return getattr(self._primary, name)


def install_unicode_font_fallback() -> None:
    """Patch ``pygame.font.Font(None, size)`` without changing explicit fonts."""
    global _installed
    if _installed:
        return

    def font_factory(file, size, *args, **kwargs):
        if file is None and not args and not kwargs:
            return _UnicodeFallbackFont(size)
        return _original_font(file, size, *args, **kwargs)

    pygame.font.Font = font_factory
    _installed = True
