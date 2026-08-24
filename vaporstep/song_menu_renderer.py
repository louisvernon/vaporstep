from __future__ import annotations

"""Song-library rendering kept separate from gameplay rendering.

This module owns the complete song-menu draw pass. It deliberately replaces the
legacy Renderer.draw_song_menu method rather than drawing an overlay on top of
it, so each row element has one renderer and one source of layout truth.
"""

import pygame

from .domain import ChainMode
from .font_support import MetadataFont, SymbolFont
from .records import song_key
from .renderer import (
    BG,
    CYAN,
    DIM,
    GRID,
    MAGENTA,
    PURPLE,
    RED,
    WHITE,
    Renderer,
    _blend,
)


_installed = False


def _metadata_font(renderer: Renderer, size: int) -> MetadataFont:
    fonts = getattr(renderer, "_song_metadata_fonts", None)
    if fonts is None:
        fonts = {}
        renderer._song_metadata_fonts = fonts
    font = fonts.get(size)
    if font is None:
        font = MetadataFont(size)
        fonts[size] = font
    return font


def _symbol_font(renderer: Renderer) -> SymbolFont:
    font = getattr(renderer, "_song_symbol_font", None)
    if font is None:
        font = SymbolFont(24)
        renderer._song_symbol_font = font
    return font


def _draw_symbol_or_letter(
    renderer: Renderer,
    glyph: str,
    fallback: str,
    center: tuple[int, int],
    color,
) -> None:
    icon = _symbol_font(renderer).render(glyph, color, (18, 18))
    if icon is not None:
        renderer.screen.blit(icon, icon.get_rect(center=center))
        return
    label = renderer.small_font.render(fallback, True, color)
    renderer.screen.blit(label, label.get_rect(center=center))


def _draw_capability_icons(renderer: Renderer, chart, x: int, y: int, color) -> None:
    """Draw capabilities for the chart represented by this row."""
    if chart is None:
        return
    if chart.foot_count > 0:
        _draw_symbol_or_letter(renderer, "👣︎", "F", (x, y), color)
    if chart.hand_count > 0:
        _draw_symbol_or_letter(renderer, "✋︎", "H", (x + 22, y), color)
    if chart.native_8_lane:
        eight_font = renderer.small_font
        previous_italic = eight_font.get_italic()
        eight_font.set_italic(True)
        try:
            glyph = eight_font.render("8", True, color)
        finally:
            eight_font.set_italic(previous_italic)
        renderer.screen.blit(glyph, glyph.get_rect(center=(x + 44, y)))


def _chart_for_row(menu, song):
    """Use the active chart for the selected song and preferred tier elsewhere."""
    if song is menu.song:
        return menu.chart
    if not song.charts:
        return None
    return song.charts[menu._preferred_chart_index(song)]


def _draw_song_menu(
    self: Renderer,
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
) -> None:
    self.screen.fill(BG)
    now = pygame.time.get_ticks() / 1000.0
    self._draw_background(now, 0.0, False)
    w, h = self.size

    title = self.big_font.render("VAPORSTEP", True, MAGENTA)
    self.screen.blit(title, title.get_rect(midtop=(w // 2, 22)))
    subtitle = self.small_font.render("STEPFILE LIBRARY", True, CYAN)
    self.screen.blit(subtitle, subtitle.get_rect(midtop=(w // 2, 65)))

    favorite_keys = favorite_keys or set()
    active_filters = []
    if favorites_only:
        active_filters.append("FAVORITES")
    if played_only:
        active_filters.append("PLAYED")
    filter_label = " + ".join(active_filters) if active_filters else "ALL SONGS"
    count_total = library_count or len(menu._all_songs) or len(menu.songs)
    header = self.small_font.render(
        f"PACK {menu.active_pack}   •   {filter_label}   •   {len(menu.songs)}/{count_total} SONGS   •   VIRTUAL HOLDS {chain_mode.label}",
        True,
        DIM,
    )
    self.screen.blit(header, header.get_rect(midtop=(w // 2, 88)))

    pack_hint = self.small_font.render("TAB next pack   SHIFT+TAB previous", True, DIM)
    self.screen.blit(pack_hint, pack_hint.get_rect(topright=(w - 28, 64)))
    if recording_enabled:
        rec = self.small_font.render("● REC PLAY", True, RED)
        self.screen.blit(rec, rec.get_rect(topright=(w - 28, 88)))

    if not menu.songs:
        message = "No songs match the active filters." if active_filters else "No compatible songs found."
        msg = self.font.render(message, True, WHITE)
        self.screen.blit(msg, msg.get_rect(center=(w // 2, h // 2 - 20)))
        root_text = str(songs_root) if songs_root is not None else "not configured"
        hint_text = (
            "Shift+F / Shift+P clear filters"
            if active_filters
            else f"Songs directory: {root_text}   •   choose SONG FOLDER from the main menu"
        )
        hint = self.small_font.render(hint_text, True, DIM)
        self.screen.blit(hint, hint.get_rect(center=(w // 2, h // 2 + 20)))
        return

    title_font = _metadata_font(self, 28)
    artist_font = _metadata_font(self, 21)
    center_y = int(h * 0.34)
    row_h = 42
    nearest = int(round(menu.visual_position))
    max_rows = min(7, len(menu.songs))
    half = max_rows // 2

    # Explicit row columns: capability glyphs -> favorite -> title -> artist.
    capability_x = max(48, w // 2 - 350)
    favorite_x = max(70, w // 2 - 282)
    text_x = max(92, w // 2 - 260)
    artist_x = max(26, w // 2 + 115)

    # Keep interpolated scrolling rows out of the lower chart-detail panel.
    list_clip = pygame.Rect(0, 108, w, max(1, int(h * 0.56) - 108))
    old_clip = self.screen.get_clip()
    self.screen.set_clip(list_clip)
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

            if selected:
                pygame.draw.line(self.screen, CYAN, (w // 2 - 405, y + 14), (w // 2 - 378, y + 14), 2)
                pygame.draw.line(self.screen, MAGENTA, (w // 2 + 378, y + 14), (w // 2 + 405, y + 14), 2)

            capability_color = CYAN if selected else _blend(DIM, BG, distance * 0.55)
            _draw_capability_icons(self, _chart_for_row(menu, song), capability_x, y + 13, capability_color)

            if song_key(song) in favorite_keys:
                cx, cy = favorite_x, y + 13
                pygame.draw.polygon(
                    self.screen,
                    MAGENTA if selected else _blend(MAGENTA, BG, 0.45),
                    [(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)],
                )

            song_text = title_font.render(song.display_title, True, color)
            self.screen.blit(song_text, song_text.get_rect(midleft=(text_x, y + 13)))
            artist = artist_font.render(song.artist or "Unknown artist", True, artist_color)
            self.screen.blit(artist, artist.get_rect(midleft=(artist_x, y + 13)))
    finally:
        self.screen.set_clip(old_clip)

    pygame.draw.line(self.screen, GRID, (w // 2 - 420, center_y + 31), (w // 2 + 420, center_y + 31), 1)

    song = menu.song
    chart = menu.chart
    if song is not None and chart is not None:
        # Leave a little more breathing room below the scrolling song list. The
        # pack label is positioned above this origin, so 61% keeps it clear of
        # the list clip without sacrificing a visible song row.
        panel_top = int(h * 0.61)
        banner = self._load_banner(song.banner_path)
        if banner is not None:
            box = pygame.Rect(max(22, w // 2 - 430), panel_top, 230, 82)
            pygame.draw.rect(self.screen, _blend(BG, PURPLE, 0.20), box, 1)
            scale = min(box.width / banner.get_width(), box.height / banner.get_height())
            size = (
                max(1, int(banner.get_width() * scale)),
                max(1, int(banner.get_height() * scale)),
            )
            scaled = pygame.transform.smoothscale(banner, size)
            scaled.set_alpha(215)
            self.screen.blit(scaled, scaled.get_rect(center=box.center))

        info_x = max(24, w // 2 - 165)
        pack_label = self.small_font.render(f"PACK  {song.pack_name}", True, DIM)
        self.screen.blit(pack_label, (info_x, panel_top - 23))

        chart_title = self.font.render(f"{chart.difficulty.upper()}  {chart.meter}", True, CYAN)
        self.screen.blit(chart_title, (info_x, panel_top))

        bpm = self.small_font.render(f"BPM  {chart.bpm_label}", True, WHITE)
        targets = self.small_font.render(f"TARGETS  {chart.target_count:,}", True, WHITE)
        chains_text = self.small_font.render(f"V-HOLDS  {chart.chain_count}", True, WHITE)
        self.screen.blit(bpm, (info_x, panel_top + 34))
        self.screen.blit(targets, (info_x + 125, panel_top + 34))
        self.screen.blit(chains_text, (info_x + 265, panel_top + 34))

        total = max(1, chart.foot_count + chart.hand_count)
        self._draw_composition_bar(
            info_x,
            panel_top + 63,
            275,
            "FEET",
            chart.foot_count,
            total,
            CYAN,
        )
        self._draw_composition_bar(
            info_x,
            panel_top + 88,
            275,
            "HANDS",
            chart.hand_count,
            total,
            MAGENTA,
        )

        difficulty_y = min(h - 88, panel_top + 128)
        self._draw_difficulty_selector(menu, difficulty_y)

        controls = self.small_font.render(
            "↑/↓ song    ←/→ difficulty    Enter play    F favorite    Shift+F favorites    Shift+P played    Shift+R record",
            True,
            DIM,
        )
        self.screen.blit(controls, controls.get_rect(midbottom=(w // 2, h - 34)))
        controls2 = self.small_font.render(
            f"V virtual holds: {chain_mode.label}    F11 fullscreen    Esc main menu", True, DIM
        )
        self.screen.blit(controls2, controls2.get_rect(midbottom=(w // 2, h - 13)))

        if record is not None and record.score > 0:
            best = self.font.render(f"BEST  {record.score:,}", True, WHITE)
            self.screen.blit(best, best.get_rect(topright=(w - 24, panel_top)))
            grade = self.small_font.render(
                f"{record.grade}   MAX COMBO {record.max_combo}", True, MAGENTA
            )
            self.screen.blit(grade, grade.get_rect(topright=(w - 24, panel_top + 34)))
        else:
            best = self.small_font.render("NO SCORE YET", True, DIM)
            self.screen.blit(best, best.get_rect(topright=(w - 24, panel_top + 6)))

    if load_error:
        err = self.small_font.render(f"Could not load chart: {load_error}", True, RED)
        self.screen.blit(err, err.get_rect(midbottom=(w // 2, h - 42)))
    elif scan_error_count:
        err = self.small_font.render(
            f"{scan_error_count} simfile(s) skipped while scanning; see terminal for details", True, DIM
        )
        self.screen.blit(err, err.get_rect(midbottom=(w // 2, h - 42)))


def install_song_menu_renderer() -> None:
    """Install the single-pass song-library renderer."""
    global _installed
    if _installed:
        return
    Renderer.draw_song_menu = _draw_song_menu
    _installed = True
