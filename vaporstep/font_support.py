from __future__ import annotations

"""Fonts used only for user-supplied song metadata.

Pygame's bundled default font is part of VaporStep's visual style, so we never
replace it globally. Song titles and artists can contain scripts the bundled
font does not cover; those strings use the best available broad system font.
"""

import pygame


# Prefer fonts that commonly ship with broad CJK + Latin coverage on each
# supported desktop platform. ``match_font`` returns None when a candidate is
# unavailable, so this remains portable without adding a bundled font asset.
_FONT_CANDIDATES = (
    "Noto Sans CJK JP",
    "Noto Sans CJK SC",
    "Noto Sans CJK KR",
    "PingFang SC",
    "PingFang TC",
    "Hiragino Sans",
    "Yu Gothic UI",
    "Yu Gothic",
    "Meiryo",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Malgun Gothic",
    "Arial Unicode MS",
    "Noto Sans",
    "DejaVu Sans",
    "Arial",
    "Helvetica",
)


def _font_supports(font: pygame.font.Font, text: str) -> bool:
    if not text:
        return True
    try:
        metrics = font.metrics(text)
    except (AttributeError, UnicodeError):
        return False
    return metrics is not None and all(metric is not None for metric in metrics)


class MetadataFont:
    """Consistent song-metadata font with per-string glyph fallback."""

    def __init__(self, size: int) -> None:
        self._default = pygame.font.Font(None, size)
        fonts: list[pygame.font.Font] = []
        seen: set[str] = set()
        for name in _FONT_CANDIDATES:
            path = pygame.font.match_font(name)
            if not path or path in seen:
                continue
            seen.add(path)
            try:
                fonts.append(pygame.font.Font(path, size))
            except (OSError, pygame.error):
                continue
        self._fonts = tuple(fonts)
        # Use one metadata font for ordinary Latin text too, so titles do not
        # randomly change typeface merely because one row contains Unicode.
        self._primary = self._fonts[0] if self._fonts else self._default

    def _font_for(self, text: str) -> pygame.font.Font:
        if _font_supports(self._primary, text):
            return self._primary
        for font in self._fonts[1:]:
            if _font_supports(font, text):
                return font
        if _font_supports(self._default, text):
            return self._default
        return self._primary

    def render(self, text: str, antialias: bool, color, background=None) -> pygame.Surface:
        font = self._font_for(text)
        if background is None:
            return font.render(text, antialias, color)
        return font.render(text, antialias, color, background)

    def size(self, text: str) -> tuple[int, int]:
        return self._font_for(text).size(text)
