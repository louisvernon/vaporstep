from __future__ import annotations

"""Font helpers for user-supplied song metadata and capability glyphs.

VaporStep's bundled Pygame font remains the fixed UI/HUD font. Song metadata is
user content and can require scripts that font does not cover, so it gets a
small, explicitly scoped system-font fallback layer instead.
"""

from pathlib import Path

import pygame


_HANGUL_FONTS = (
    "Apple SD Gothic Neo",
    "AppleGothic",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "Malgun Gothic",
    "NanumGothic",
)
_JAPANESE_FONTS = (
    "Hiragino Sans W3",
    "Hiragino Kaku Gothic ProN W3",
    "Hiragino Sans",
    "Yu Gothic UI",
    "Yu Gothic",
    "Meiryo",
    "Noto Sans CJK JP",
    "Noto Sans JP",
)
_CJK_FONTS = (
    "PingFang SC",
    "PingFang TC",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Noto Sans CJK TC",
)
_GENERAL_FONTS = (
    "Arial Unicode MS",
    "Noto Sans",
    "DejaVu Sans",
    "Arial",
    "Helvetica",
)
_SYMBOL_FONTS = (
    "Apple Color Emoji",
    "Apple Symbols",
    "Segoe UI Emoji",
    "Segoe UI Symbol",
    "Noto Color Emoji",
    "Noto Emoji",
    "Symbola",
)

# SDL/Pygame font discovery can occasionally miss TTC-backed macOS faces. These
# are fallback hints only; normal ``match_font`` discovery remains first choice.
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
    "Hiragino Sans": ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",),
    "Apple Color Emoji": ("/System/Library/Fonts/Apple Color Emoji.ttc",),
}


def _contains_hangul(text: str) -> bool:
    return any(
        0x1100 <= ord(char) <= 0x11FF
        or 0x3130 <= ord(char) <= 0x318F
        or 0xA960 <= ord(char) <= 0xA97F
        or 0xAC00 <= ord(char) <= 0xD7AF
        or 0xD7B0 <= ord(char) <= 0xD7FF
        for char in text
    )


def _contains_japanese(text: str) -> bool:
    return any(
        0x3040 <= ord(char) <= 0x30FF
        or 0x31F0 <= ord(char) <= 0x31FF
        for char in text
    )


def _contains_cjk(text: str) -> bool:
    return any(
        0x3400 <= ord(char) <= 0x4DBF
        or 0x4E00 <= ord(char) <= 0x9FFF
        or 0xF900 <= ord(char) <= 0xFAFF
        for char in text
    )


def _candidate_names_for_text(text: str) -> tuple[str, ...]:
    """Return script-aware font preferences for one metadata string."""
    if _contains_hangul(text):
        return (*_HANGUL_FONTS, *_GENERAL_FONTS)
    if _contains_japanese(text):
        return (*_JAPANESE_FONTS, *_GENERAL_FONTS)
    if _contains_cjk(text):
        return (*_CJK_FONTS, *_GENERAL_FONTS)
    return _GENERAL_FONTS


def _font_path(name: str) -> str | None:
    path = pygame.font.match_font(name)
    if path:
        return path
    for hint in _FONT_PATH_HINTS.get(name, ()):
        if Path(hint).is_file():
            return hint
    return None


def _font_supports(font: pygame.font.Font, text: str) -> bool:
    if not text:
        return True
    try:
        metrics = font.metrics(text)
    except (AttributeError, UnicodeError):
        return False
    return metrics is not None and all(metric is not None for metric in metrics)


def _cropped_signature(surface: pygame.Surface) -> tuple[tuple[int, int], bytes] | None:
    """Return a stable signature for rendered pixels, ignoring surrounding space."""
    bounds = surface.get_bounding_rect(min_alpha=8)
    if bounds.width <= 0 or bounds.height <= 0:
        return None
    cropped = surface.subsurface(bounds).copy()
    return cropped.get_size(), pygame.image.tostring(cropped, "RGBA")


class MetadataFont:
    """Render song metadata using a font chosen for the string's script."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._default = pygame.font.Font(None, size)
        self._fonts: dict[str, pygame.font.Font | None] = {}

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
        names = _candidate_names_for_text(text)
        script_specific = _contains_hangul(text) or _contains_japanese(text) or _contains_cjk(text)
        script_count = len(names) - len(_GENERAL_FONTS) if script_specific else 0
        for index, name in enumerate(names):
            font = self._load(name)
            if font is None:
                continue
            # Trust known script-specific faces. SDL_ttf metrics are not reliable
            # enough to distinguish a real CJK glyph from tofu on every build.
            if index < script_count:
                return font
            if _font_supports(font, text):
                return font
        if _font_supports(self._default, text):
            return self._default
        for name in names:
            font = self._load(name)
            if font is not None:
                return font
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

    _MISSING_SENTINEL = "\U0010ffff"

    def __init__(self, size: int) -> None:
        self._fonts: list[pygame.font.Font] = []
        self._missing_signatures: dict[int, tuple[tuple[int, int], bytes] | None] = {}
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

    def _is_missing_glyph(self, font: pygame.font.Font, rendered: pygame.Surface) -> bool:
        """Detect SDL_ttf's .notdef/tofu glyph by comparing a noncharacter."""
        key = id(font)
        if key not in self._missing_signatures:
            try:
                missing = font.render(self._MISSING_SENTINEL, True, (255, 255, 255))
                self._missing_signatures[key] = _cropped_signature(missing)
            except (UnicodeError, pygame.error):
                self._missing_signatures[key] = None
        missing_signature = self._missing_signatures[key]
        return missing_signature is not None and _cropped_signature(rendered) == missing_signature

    def render(self, glyph: str, color, max_size: tuple[int, int]) -> pygame.Surface | None:
        for font in self._fonts:
            try:
                raw = font.render(glyph, True, (255, 255, 255))
            except (UnicodeError, pygame.error):
                continue
            if self._is_missing_glyph(font, raw):
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
