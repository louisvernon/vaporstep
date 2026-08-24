from __future__ import annotations

"""Font helpers for user-supplied song metadata and capability glyphs.

Unicode defines characters, not glyphs. Pygame/SDL_ttf does not provide the
platform text stack's automatic per-character font fallback, so VaporStep keeps
a small cross-platform list of likely system fonts and chooses one by actual
glyph coverage rather than trying to classify metadata as Japanese/Korean/etc.
"""

from pathlib import Path

import pygame


_METADATA_FONTS = (
    # macOS CJK faces
    "Hiragino Sans W3",
    "Hiragino Kaku Gothic ProN W3",
    "Apple SD Gothic Neo",
    "AppleGothic",
    "PingFang SC",
    "PingFang TC",
    "Arial Unicode MS",
    # Common Noto installations / packaged Linux environments
    "Noto Sans CJK JP",
    "Noto Sans CJK KR",
    "Noto Sans CJK SC",
    "Noto Sans CJK TC",
    "Noto Sans JP",
    "Noto Sans KR",
    "Noto Sans",
    # Windows CJK faces
    "Yu Gothic UI",
    "Yu Gothic",
    "Meiryo",
    "Malgun Gothic",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    # Broad Latin/general fallbacks
    "DejaVu Sans",
    "Arial",
    "Helvetica",
)
_SYMBOL_FONTS = (
    "Noto Emoji",
    "Noto Sans Symbols 2",
    "Apple Color Emoji",
    "Apple Symbols",
    "Segoe UI Emoji",
    "Segoe UI Symbol",
    "Noto Color Emoji",
    "Symbola",
)

# SDL/Pygame font discovery can miss TTC-backed macOS faces. These are fallback
# hints only; normal ``match_font`` discovery remains the first choice.
_FONT_PATH_HINTS = {
    "Apple SD Gothic Neo": ("/System/Library/Fonts/AppleSDGothicNeo.ttc",),
    "AppleGothic": ("/System/Library/Fonts/Supplemental/AppleGothic.ttf",),
    "Hiragino Sans W3": (
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴ ProN W3.otf",
    ),
    "Hiragino Kaku Gothic ProN W3": (
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴ ProN W3.otf",
    ),
    "PingFang SC": ("/System/Library/Fonts/PingFang.ttc",),
    "PingFang TC": ("/System/Library/Fonts/PingFang.ttc",),
    "Apple Color Emoji": ("/System/Library/Fonts/Apple Color Emoji.ttc",),
}


def _candidate_names_for_text(_text: str) -> tuple[str, ...]:
    """Return one coverage-based fallback pool for every metadata string."""
    return _METADATA_FONTS


def _font_path(name: str) -> str | None:
    path = pygame.font.match_font(name)
    if path:
        return path
    for hint in _FONT_PATH_HINTS.get(name, ()):
        if Path(hint).is_file():
            return hint
    return None


def _cropped_signature(surface: pygame.Surface) -> tuple[tuple[int, int], bytes] | None:
    """Return a stable signature for rendered pixels, ignoring surrounding space."""
    bounds = surface.get_bounding_rect(min_alpha=8)
    if bounds.width <= 0 or bounds.height <= 0:
        return None
    cropped = surface.subsurface(bounds).copy()
    return cropped.get_size(), pygame.image.tostring(cropped, "RGBA")


class _GlyphCoverage:
    """Detect SDL_ttf's .notdef/tofu glyph using a Unicode noncharacter."""

    _MISSING_SENTINEL = "\U0010ffff"

    def __init__(self) -> None:
        self._missing_signatures: dict[int, tuple[tuple[int, int], bytes] | None] = {}
        self._glyph_cache: dict[tuple[int, str], bool] = {}

    def _missing_signature(self, font: pygame.font.Font):
        key = id(font)
        if key not in self._missing_signatures:
            try:
                missing = font.render(self._MISSING_SENTINEL, True, (255, 255, 255))
                self._missing_signatures[key] = _cropped_signature(missing)
            except (UnicodeError, pygame.error):
                self._missing_signatures[key] = None
        return self._missing_signatures[key]

    def supports_glyph(self, font: pygame.font.Font, char: str) -> bool:
        if char.isspace():
            return True
        cache_key = (id(font), char)
        if cache_key in self._glyph_cache:
            return self._glyph_cache[cache_key]
        try:
            rendered = font.render(char, True, (255, 255, 255))
        except (UnicodeError, pygame.error):
            self._glyph_cache[cache_key] = False
            return False
        signature = _cropped_signature(rendered)
        supported = signature is not None and signature != self._missing_signature(font)
        self._glyph_cache[cache_key] = supported
        return supported

    def supports_text(self, font: pygame.font.Font, text: str) -> bool:
        return all(self.supports_glyph(font, char) for char in set(text))


class MetadataFont:
    """Render metadata with the first installed font that covers the whole string."""

    def __init__(self, size: int) -> None:
        self._default = pygame.font.Font(None, size)
        self._fonts: dict[str, pygame.font.Font | None] = {}
        self._coverage = _GlyphCoverage()
        self._selection_cache: dict[str, pygame.font.Font] = {}
        self._size = size

    def _load(self, name: str) -> pygame.font.Font | None:
        if name in self._fonts:
            return self._fonts[name]
        path = _font_path(name)
        if path is None:
            self._fonts[name] = None
            return None
        try:
            font = pygame.font.Font(path, self._size)
        except (OSError, pygame.error):
            font = None
        self._fonts[name] = font
        return font

    def _font_for(self, text: str) -> pygame.font.Font:
        cached = self._selection_cache.get(text)
        if cached is not None:
            return cached

        # Preserve VaporStep's normal UI face where it actually has every glyph.
        if self._coverage.supports_text(self._default, text):
            self._selection_cache[text] = self._default
            return self._default

        available: list[pygame.font.Font] = []
        for name in _METADATA_FONTS:
            font = self._load(name)
            if font is None:
                continue
            available.append(font)
            if self._coverage.supports_text(font, text):
                self._selection_cache[text] = font
                return font

        # No single installed candidate covers the entire string. Choose the one
        # that covers the most unique characters rather than blindly returning a
        # font that turns all unsupported code points into tofu.
        chars = {char for char in text if not char.isspace()}
        if available and chars:
            best = max(
                available,
                key=lambda font: sum(self._coverage.supports_glyph(font, char) for char in chars),
            )
            self._selection_cache[text] = best
            return best

        self._selection_cache[text] = self._default
        return self._default

    def render(self, text: str, antialias: bool, color, background=None) -> pygame.Surface:
        font = self._font_for(text)
        if background is None:
            return font.render(text, antialias, color)
        return font.render(text, antialias, color, background)

    def size(self, text: str) -> tuple[int, int]:
        return self._font_for(text).size(text)


class SymbolFont:
    """Render familiar Unicode capability glyphs as tinted monochrome masks."""

    def __init__(self, size: int) -> None:
        self._fonts: list[pygame.font.Font] = []
        self._coverage = _GlyphCoverage()
        seen: set[str] = set()
        for name in _SYMBOL_FONTS:
            path = _font_path(name)
            if not path or path in seen:
                continue
            seen.add(path)
            try:
                self._fonts.append(pygame.font.Font(path, size))
            except (OSError, pygame.error):
                continue

    def render(self, glyph: str, color, max_size: tuple[int, int]) -> pygame.Surface | None:
        base = glyph.replace("\ufe0e", "").replace("\ufe0f", "")
        for font in self._fonts:
            if not all(self._coverage.supports_glyph(font, char) for char in base):
                continue
            try:
                raw = font.render(glyph, True, (255, 255, 255))
            except (UnicodeError, pygame.error):
                continue
            bounds = raw.get_bounding_rect(min_alpha=8)
            if bounds.width <= 0 or bounds.height <= 0:
                continue
            raw = raw.subsurface(bounds).copy()
            mask = pygame.mask.from_surface(raw, 8)
            if mask.count() <= 0:
                continue
            mono = pygame.Surface(raw.get_size(), pygame.SRCALPHA)
            mask.to_surface(
                surface=mono,
                setcolor=(*color, 255),
                unsetcolor=(0, 0, 0, 0),
            )
            limit_w, limit_h = max_size
            scale = min(limit_w / mono.get_width(), limit_h / mono.get_height(), 1.0)
            if scale < 1.0:
                mono = pygame.transform.smoothscale(
                    mono,
                    (max(1, round(mono.get_width() * scale)), max(1, round(mono.get_height() * scale))),
                )
            return mono
        return None
