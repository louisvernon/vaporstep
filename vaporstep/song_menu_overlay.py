from __future__ import annotations

"""Song-library presentation additions kept out of gameplay rendering."""

import pygame

from .domain import ChainMode
from .font_support import MetadataFont
from .records import song_key
from .renderer import BG, CYAN, DIM, GRID, MAGENTA, Renderer, WHITE, _blend


_installed = False


def _draw_foot(surface: pygame.Surface, center: tuple[int, int], color) -> None:
    """Tiny abstract footprint icon drawn directly, independent of font glyphs."""
    x, y = center
    pygame.draw.ellipse(surface, color, (x - 4, y - 5, 8, 12), 1)
    pygame.draw.circle(surface, color, (x + 4, y - 6), 2, 1)
    pygame.draw.circle(surface, color, (x + 1, y - 9), 2, 1)


def _draw_hand(surface: pygame.Surface, center: tuple[int, int], color) -> None:
    """Tiny line-art hand icon drawn directly, independent of font glyphs."""
    x, y = center
    pygame.draw.rect(surface, color, (x - 4, y - 1, 8, 8), 1)
    for offset, height in ((-4, 7), (-1, 9), (2, 8), (5, 6)):
        pygame.draw.line(surface, color, (x + offset, y), (x + offset, y - height), 1)
    pygame.draw.line(surface, color, (x - 4, y + 2), (x - 8, y - 1), 1)


def _draw_capability_icons(renderer: Renderer, song, x: int, y: int, color) -> None:
    """Draw fixed-column feet, hands, and native-eight capability markers."""
    if song.has_foot_targets:
        _draw_foot(renderer.screen, (x, y), color)
    if song.has_hand_targets:
        _draw_hand(renderer.screen, (x + 23, y), color)
    if song.has_native_8_lane:
        badge = renderer.small_font.render("8", True, color)
        rect = badge.get_rect(center=(x + 46, y))
        pygame.draw.rect(renderer.screen, color, rect.inflate(6, 3), 1, border_radius=3)
        renderer.screen.blit(badge, rect)


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

    # Replace the original filter line with pack scope + filters. This stays on
    # VaporStep's normal UI font; only user-supplied song metadata gets fallback.
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

    title_font = MetadataFont(28)
    artist_font = MetadataFont(21)
    center_y = int(h * 0.34)
    row_h = 42
    nearest = int(round(menu.visual_position))
    max_rows = min(7, len(menu.songs))
    half = max_rows // 2
    text_x = max(38, w // 2 - 365)
    icon_x = text_x - 66
    artist_x = max(26, w // 2 + 115)

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

        # Clear only the old row text. The original renderer still owns the
        # selection rails and all other fixed UI elements.
        clear_left = max(8, icon_x - 14)
        clear_right = min(w - 8, w // 2 + 375)
        pygame.draw.rect(renderer.screen, BG, (clear_left, y - 2, clear_right - clear_left, 35))

        if song_key(song) in favorite_keys:
            cx, cy = text_x - 18, y + 13
            pygame.draw.polygon(
                renderer.screen,
                MAGENTA if selected else _blend(MAGENTA, BG, 0.45),
                [(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)],
            )

        capability_color = CYAN if selected else _blend(DIM, BG, distance * 0.55)
        _draw_capability_icons(renderer, song, icon_x, y + 13, capability_color)

        title = title_font.render(song.display_title, True, color)
        renderer.screen.blit(title, (text_x, y))
        artist = artist_font.render(song.artist or "Unknown artist", True, artist_color)
        renderer.screen.blit(artist, (artist_x, y + 4))


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
