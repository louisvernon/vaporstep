from __future__ import annotations

"""Small song-library presentation additions kept out of gameplay rendering."""

import pygame

from .domain import ChainMode
from .renderer import BG, CYAN, DIM, MAGENTA, Renderer, _blend


_installed = False


def _draw_library_overlay(
    renderer: Renderer,
    menu,
    *,
    library_count: int,
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

    center_y = int(h * 0.34)
    row_h = 42
    nearest = int(round(menu.visual_position))
    max_rows = min(7, len(menu.songs))
    half = max_rows // 2
    text_x = max(38, w // 2 - 365)
    for logical in range(nearest - half - 1, nearest + half + 2):
        offset = logical - menu.visual_position
        if abs(offset) > half + 0.8:
            continue
        index = logical % len(menu.songs)
        song = menu.songs[index]
        if not song.has_native_8_lane:
            continue
        y = center_y + int(offset * row_h)
        selected = logical == menu.scroll_target
        distance = min(1.0, abs(offset) / max(half, 1))
        color = CYAN if selected else _blend(DIM, BG, distance * 0.65)
        title_width = renderer.font.size(song.display_title)[0]
        badge = renderer.small_font.render("[8]", True, color)
        renderer.screen.blit(badge, (text_x + title_width + 9, y + 4))

    chart = menu.chart
    if chart is not None and chart.native_8_lane:
        panel_top = int(h * 0.58)
        info_x = max(24, w // 2 - 165)
        badge = renderer.small_font.render("NATIVE 8-LANE", True, MAGENTA)
        renderer.screen.blit(badge, (info_x + 155, panel_top + 5))


def install_song_menu_overlay() -> None:
    """Augment Renderer.draw_song_menu without touching gameplay rendering."""
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
            favorites_only=favorites_only,
            played_only=played_only,
            chain_mode=chain_mode,
        )

    Renderer.draw_song_menu = draw_song_menu
    _installed = True
