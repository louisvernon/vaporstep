import pygame

from vaporstep.font_support import SymbolFont, _bundled_symbol_font_path, _candidate_names_for_text


def test_metadata_uses_one_cross_platform_glyph_fallback_pool():
    latin = _candidate_names_for_text("Synthetic Track")
    hangul = _candidate_names_for_text("테스트 음악")
    japanese = _candidate_names_for_text("テスト 音楽")
    han_only = _candidate_names_for_text("星空記憶")

    # Metadata routing is intentionally language-neutral: Unicode code points
    # are matched by actual glyph coverage at runtime rather than guessed script.
    assert latin == hangul == japanese == han_only
    assert "Hiragino Sans W3" in latin
    assert "Apple SD Gothic Neo" in latin
    assert "PingFang SC" in latin
    assert "Noto Sans CJK JP" in latin
    assert "Malgun Gothic" in latin


def test_plain_latin_pool_still_contains_general_fallbacks():
    candidates = _candidate_names_for_text("Synthetic Track")
    assert "Noto Sans" in candidates
    assert "DejaVu Sans" in candidates


def test_bundled_capability_font_renders_foot_and_hand():
    path = _bundled_symbol_font_path()
    assert path is not None
    assert path.name == "VaporStepEmojiSymbols.ttf"

    pygame.font.init()
    font = SymbolFont(32)
    for glyph in ("👣", "✋"):
        rendered = font.render(glyph, (255, 255, 255), (32, 32))
        assert rendered is not None
        bounds = rendered.get_bounding_rect(min_alpha=8)
        assert bounds.width > 0
        assert bounds.height > 0
