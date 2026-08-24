from __future__ import annotations

"""Song-library presentation additions kept out of gameplay rendering."""

import pygame

from .domain import ChainMode
from .font_support import MetadataFont
from .records import song_key
from .renderer import BG, CYAN, DIM, GRID, MAGENTA, Renderer, WHITE, _blend


_installed = False


def _draw_foot(surface: pygame.Surface, center: tuple[int, int], color) -> None:
    """Small monochrome footprint silhouette drawn directly in VaporStep colors."""
    x, y = center
    # Heel / sole
    pygame.draw.ellipse(surface, color, (x - 4, y - 2, 8, 10))
    # Toes, intentionally asymmetric so it reads as a footprint rather than a blob.
    pygame.draw.circle(surface, color, (x + 4, y - 6), 2)
    pygame.draw.circle(surface, color, (x + 1, y - 8), 2)
    pygame.draw.circle(surface, color, (x - 2, y - 8), 1)


def _draw_hand(surface: pygame.Surface, center: tuple[int, int], color) -> None:
    """Small monochrome open-hand silhouette drawn directly in VaporStep colors."""
    x, y = center
    pygame.draw.rect(surface, color, (x - 4, y - 1, 8, 8), border_radius=2)
    for offset, top in ((-4, -8), (-1, -10), (2, -9), (5, -7)):
        pygame.draw.line(surface, color, (x + offset, y), (x + offset, y + top), 2)
    pygame.draw.line(surface, color, (x - 4, y + 2), (x - 8, y - 2), 2)


def _metadata_font(renderer: Renderer) -> MetadataFont:
    font = getattr(renderer, "_song_metadata_font", None)
    if font is None:
        # Match the artist text scale rather than enlarging song titles.
        font = MetadataFont(21)
        renderer._song_metadata_font = font
    return font


def _draw_capability_icons(renderer: Renderer, song, x: int, y: int, color) -> None:
    """Draw a compact feet / hands / native-eight capability column."""
    # These are intentionally vector-drawn rather than font/emoji glyphs. SDL_ttf
    # can render a missing glyph as a tofu box while still reporting success,
    # making Unicode symbol fallback unreliable across platforms.
    if song.has_foot_targets:
        _draw_foot(renderer.screen, (x, y), color)
    if song.has_hand_targets:
        _draw_hand(renderer.screen, (x + 22, y), color)
    if song.has_native_8_lane:
        eight_font = renderer.small_font
        previous_italic = eight_font.get_italic()
        eight_font.set_italic(True)
        try:
            glyph = eight_font.render("8", True, color)
        finally:
            eight_font.set_italic(previous_italic)
        renderer.screen.blit(glyph, glyph.get_rect(center=(x + 44, y)))


def _draw_library_overlay(
    renderer: Renderer,
    menu,
    *,
    library_count: int,
    favorite_keys: set[str],
    favorites_only: bool,
    played_only: bool,
    chain_mode: ChainMode,
) -> None:
    w, h = renderer.size

    active_filters = []
    if favorites_only:
        active_filters.append("FAVORITES")
    if played_only:
        active_filters.append("PLAYED")
    filter_label = " + ".join(active_filters) if active_filters else "ALL SONGS"

    panel = pygame.Surface((min(w - 40, 920), 27), pygame.SRCALPHA)
    panel.fill((*BG, 238))
    renderer.screen.blit(panel, panel.get_rect(midtop=(w // 2, 84)))
    count_total = library_count or len(menu._all_songs) or len(menu.songs)
    header = renderer.small_font.render(
        f"PACK {menu.active_pack}   •   {filter_label}   •   {len(menu.songs)}/{count_total} SONGS   •   VIRTUAL HOLDS {chain_mode.label}",
        True,
        DIM,
    )
    renderer.screen.blit(header, header.get_rect(midtop=(w // 2, 88)))

    pack_hint = renderer.small_font.render("TAB next pack   SHIFT+TAB previous", True, DIM)
    renderer.screen.blit(pack_hint, pack_hint.get_rect(topright=(w - 28, 64)))

    if not menu.songs:
        return

    metadata_font = _metadata_font(renderer)
    center_y = int(h * 0.34)
    row_h = 42
    nearest = int(round(menu.visual_position))
    max_rows = min(7, len(menu.songs))
    half = max_rows // 2

    # Leave a real gap between the scrolling list and the lower detail panel.
    list_clip = pygame.Rect(0, 108, w, max(1, int(h * 0.56) - 108))
    old_clip = renderer.screen.get_clip()
    renderer.screen.set_clip(list_clip)

    icon_x = max(48, w // 2 - 350)
    favorite_x = max(70, w // 2 - 282)
    text_x = max(92, w // 2 - 260)
    artist_x = max(26, w // 2 + 115)

    try:
        for logical in range(nearest - half - 1, nearest + half + 2):
            offset = logical - menu.visual_position
            if abs(offset) > half + 0.8:
                continue
            index = logical % len(menu.songs)
            song = menu.songs[index]
            y = center_y + int(offset * row_h)
            distance = min(1.0, abs(offset) / max(half, 1))
            selected = logical == menu.scroll_target
            color = WHITE if selected else _blend(DIM, BG, distance * 0.65)
            artist_color = MAGENTA if selected else _blend(GRID, BG, distance * 0.55)

            clear_left = max(20, w // 2 - 374)
            clear_right = min(w - 20, w // 2 + 374)
            pygame.draw.rect(renderer.screen, BG, (clear_left, y - 2, clear_right - clear_left, 35))

            capability_color = CYAN if selected else _blend(DIM, BG, distance * 0.55)
            _draw_capability_icons(renderer, song, icon_x, y + 13, capability_color)

            if song_key(song) in favorite_keys:
                cx, cy = favorite_x, y + 13
                pygame.draw.polygon(
                    renderer.screen,
                    MAGENTA if selected else _blend(MAGENTA, BG, 0.45),
                    [(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)],
                )

            title = metadata_font.render(song.display_title, True, color)
            renderer.screen.blit(title, (text_x, y + 4))
            artist = metadata_font.render(song.artist or "Unknown artist", True, artist_color)
            renderer.screen.blit(artist, (artist_x, y + 4))
    finally:
        renderer.screen.set_clip(old_clip)

    selected_song = menu.song
    if selected_song is not None:
        pack_label = renderer.small_font.render(f"PACK  {selected_song.pack_name}", True, DIM)
        panel_top = int(h * 0.58)
        renderer.screen.blit(pack_label, (max(24, w // 2 - 165), panel_top - 23))


def install_song_menu_overlay() -> None:
    """Augment Renderer.draw_song_menu without affecting gameplay rendering."""
    global _installed
    if _installed:
        return
    original = Renderer.draw_song_menu

    def draw_song_menu(
        self,
        menu,
        songs_root,
        load_error,
        scan_error_count,
        record=None,
        library_count=0,
        favorite_keys=None,
        favorites_only=False,
        played_only=False,
        chain_mode=ChainMode.BLOCKS,
        recording_enabled=False,
    ):
        favorite_keys = favorite_keys or set()
        original(
            self,
            menu,
            songs_root,
            load_error,
            scan_error_count,
            record=record,
            library_count=library_count,
            favorite_keys=favorite_keys,
            favorites_only=favorites_only,
            played_only=played_only,
            chain_mode=chain_mode,
            recording_enabled=recording_enabled,
        )
        _draw_library_overlay(
            self,
            menu,
            library_count=library_count,
            favorite_keys=favorite_keys,
            favorites_only=favorites_only,
            played_only=played_only,
            chain_mode=chain_mode,
        )

    Renderer.draw_song_menu = draw_song_menu
    _installed = True
