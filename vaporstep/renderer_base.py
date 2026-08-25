from __future__ import annotations

import math
import random

import cv2
import numpy as np
import pygame

from .config import (
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    FOOT_HIT_Y,
    FOOT_PLAYFIELD_LEFT,
    FOOT_PLAYFIELD_RIGHT,
    HAND_HIT_Y,
    HAND_PLAYFIELD_LEFT,
    HAND_PLAYFIELD_RIGHT,
    HIT_FLASH_SECONDS,
    HIT_WINDOW_SECONDS,
    OUTER_LANE_EDGE_EXTENSION,
    VANISH_HALF_WIDTH,
    VANISH_Y,
)
from .domain import BodyPoint, BodyState, ChainMode, ChainState, GameNote, HitQuality, NoteKind, RuntimeChain, SustainSource
from .font_support import MetadataFont
from .keyboard_input import label_for_lane
from .menu import SongMenu
from .motion import MOTION_EVENT_VISUAL_SECONDS, MotionEvent
from .records import ChartRecord, song_key
from .scoring import RunStats
from .scroll import note_is_within_lookahead, note_progress, timed_is_within_lookahead, timed_progress


BG = (2, 2, 8)
CYAN = (70, 245, 255)
MAGENTA = (255, 55, 210)
PURPLE = (140, 75, 255)
WHITE = (235, 245, 255)
DIM = (70, 88, 115)
GRID = (25, 64, 88)
GREEN = (95, 255, 175)
RED = (255, 75, 110)
AMBER = (255, 190, 75)
ELECTRIC_YELLOW = (255, 232, 70)
HIT_BRICK_POP_SECONDS = 0.16


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, amount))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


class Renderer:
    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.font = pygame.font.Font(None, 28)
        self.small_font = pygame.font.Font(None, 21)
        self.big_font = pygame.font.Font(None, 44)
        self.huge_font = pygame.font.Font(None, 112)
        self.score_font = pygame.font.Font(None, 36)
        self.combo_font = pygame.font.Font(None, 54)
        self.hit_font = pygame.font.Font(None, 32)
        self._silhouette_surface: pygame.Surface | None = None
        self._last_mask: np.ndarray | None = None
        self._silhouette_size: tuple[int, int] | None = None
        self._seen_hits: set[int] = set()
        self._particles: list[dict[str, object]] = []
        self._impact_bursts: list[dict[str, object]] = []
        self._outbound_particles: list[dict[str, object]] = []
        self._miss_impacts: list[dict[str, object]] = []
        self._seen_misses: set[int] = set()
        self._rng = random.Random(0xC0FFEE)
        self._lane_fill_surface: pygame.Surface | None = None
        self._banner_cache: dict[str, pygame.Surface | None] = {}
        self._song_metadata_fonts: dict[int, MetadataFont] = {}
        self.player_horizontal_zoom = 1.10

    def _song_metadata_font(self, size: int) -> MetadataFont:
        """Return a cached coverage-based font for user-supplied song text."""
        font = self._song_metadata_fonts.get(size)
        if font is None:
            font = MetadataFont(size)
            self._song_metadata_fonts[size] = font
        return font

    @property
    def size(self) -> tuple[int, int]:
        return self.screen.get_size()

    def replace_screen(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._silhouette_surface = None
        self._last_mask = None
        self._silhouette_size = None
        self._lane_fill_surface = None

    def reset_game_effects(self) -> None:
        self._seen_hits.clear()
        self._particles.clear()
        self._impact_bursts.clear()
        self._outbound_particles.clear()
        self._miss_impacts.clear()
        self._seen_misses.clear()

    def set_player_horizontal_zoom(self, value: float) -> None:
        value = max(1.0, float(value))
        if abs(value - self.player_horizontal_zoom) < 1e-6:
            return
        self.player_horizontal_zoom = value
        self._silhouette_surface = None
        self._last_mask = None
        self._silhouette_size = None

    def draw(
        self,
        body: BodyState,
        mask: np.ndarray | None,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        status: str,
        debug: bool,
        pose_fps: float,
        input_name: str,
        song_title: str = "",
        chart_label: str = "",
        audio_error: str | None = None,
        stats: RunStats | None = None,
        best_score: int = 0,
        running: bool = False,
        beat_pulse: float = 0.0,
        downbeat: bool = False,
        hand_enabled: bool = True,
        foot_enabled: bool = True,
        performance_state: str = "ok",
        strike_events: tuple[MotionEvent, ...] = (),
        chains: tuple[RuntimeChain, ...] = (),
        chain_mode: ChainMode = ChainMode.OFF,
        show_lower_body_sources: bool = False,
    ) -> None:
        self.screen.fill(BG)
        self._draw_background(song_time, beat_pulse, downbeat)

        if mask is not None:
            self._draw_silhouette(mask)

        overdrive = stats is not None and stats.multiplier >= 5 and running
        self._draw_playfields(body, song_time, beat_pulse, downbeat, hand_enabled, foot_enabled, overdrive, animate_buzz=running)
        # Do not preview the opening bars while the player is still positioning.
        # A failed run deliberately keeps the frozen chart visible during its hold.
        visible_notes = notes if (running or performance_state == "failed") else []
        self._draw_chains(chains, visible_notes, song_time, song_beat, chain_mode)
        self._draw_notes(visible_notes, song_time, song_beat, chain_mode)
        if running:
            self._spawn_note_effects(notes)
            self._draw_particles(song_time)
        self._draw_receptors(body, visible_notes, song_time, hand_enabled, foot_enabled, strike_events)
        self._draw_body_markers(
            body,
            show_labels=debug,
            hand_enabled=hand_enabled,
            foot_enabled=foot_enabled,
            show_lower_body_sources=show_lower_body_sources,
        )

        if running and stats is not None:
            self._draw_hud(
                stats,
                best_score,
                beat_pulse=beat_pulse,
                performance_state=performance_state,
                chain_mode=chain_mode,
            )
            if audio_error:
                self._draw_audio_error(audio_error)
        else:
            self._draw_status(status, input_name, song_title, chart_label, audio_error)

        if debug:
            self._draw_debug(body, song_time, pose_fps)

    def draw_recording_indicator(self) -> None:
        w, _ = self.size
        label = self.small_font.render("● REC", True, RED)
        self.screen.blit(label, label.get_rect(topright=(w - 18, 94)))

    def draw_startup_splash(self, status: str = "INITIALIZING") -> None:
        self.screen.fill(BG)
        now = pygame.time.get_ticks() / 1000.0
        self._draw_background(now, 0.0, False)
        w, h = self.size

        pulse = 0.5 + 0.5 * math.sin(now * 2.4)
        title_color = _blend(MAGENTA, WHITE, pulse * 0.12)
        title = self.huge_font.render("VAPORSTEP", True, title_color)
        self.screen.blit(title, title.get_rect(center=(w // 2, int(h * 0.39))))
        subtitle = self.small_font.render("FULL-BODY RHYTHM", True, CYAN)
        self.screen.blit(subtitle, subtitle.get_rect(center=(w // 2, int(h * 0.50))))

        segment_count = 7
        segment_w = 28
        segment_gap = 10
        rail_w = segment_count * segment_w + (segment_count - 1) * segment_gap
        rail_x = (w - rail_w) // 2
        rail_y = int(h * 0.60)
        active = int(now * 7.0) % segment_count
        for index in range(segment_count):
            distance = (active - index) % segment_count
            if distance == 0:
                color = CYAN
            elif distance in (1, 2):
                color = _blend(GRID, CYAN, 0.45 if distance == 1 else 0.20)
            else:
                color = GRID
            pygame.draw.rect(
                self.screen,
                color,
                (rail_x + index * (segment_w + segment_gap), rail_y, segment_w, 3),
            )

        status_text = self.small_font.render(status.upper(), True, DIM)
        self.screen.blit(status_text, status_text.get_rect(center=(w // 2, rail_y + 38)))

    def draw_privacy_notice(self) -> None:
        self.screen.fill(BG)
        now = pygame.time.get_ticks() / 1000.0
        self._draw_background(now, 0.0, False)
        w, h = self.size

        title = self.big_font.render("SAFETY & PRIVACY", True, MAGENTA)
        self.screen.blit(title, title.get_rect(center=(w // 2, int(h * 0.16))))

        safety_title = self.font.render("PLAY SAFELY", True, CYAN)
        self.screen.blit(safety_title, safety_title.get_rect(center=(w // 2, int(h * 0.25))))
        safety_lines = (
            "Clear enough space to step, reach and turn safely.",
            "Play within your abilities and stop if you feel pain, dizziness, or otherwise unwell.",
        )
        y = int(h * 0.31)
        for line in safety_lines:
            surf = self.small_font.render(line, True, WHITE)
            self.screen.blit(surf, surf.get_rect(center=(w // 2, y)))
            y += 34

        privacy_title = self.font.render("CAMERA & PRIVACY", True, CYAN)
        self.screen.blit(privacy_title, privacy_title.get_rect(center=(w // 2, int(h * 0.45))))
        privacy_lines = (
            "Camera frames are processed on this device and are not saved or uploaded by VaporStep.",
            "The camera is active only during calibration and gameplay.",
        )
        y = int(h * 0.51)
        for line in privacy_lines:
            surf = self.small_font.render(line, True, DIM)
            self.screen.blit(surf, surf.get_rect(center=(w // 2, y)))
            y += 32

        accept = self.font.render("ENTER  I UNDERSTAND — CONTINUE", True, CYAN)
        self.screen.blit(accept, accept.get_rect(center=(w // 2, int(h * 0.74))))
        more = self.small_font.render("See About for safety, privacy, and licensing details.", True, DIM)
        self.screen.blit(more, more.get_rect(center=(w // 2, int(h * 0.81))))
        quit_text = self.small_font.render("Esc quit", True, GRID)
        self.screen.blit(quit_text, quit_text.get_rect(center=(w // 2, int(h * 0.86))))

    def draw_about(self) -> None:
        self.screen.fill(BG)
        now = pygame.time.get_ticks() / 1000.0
        self._draw_background(now, 0.0, False)
        w, h = self.size

        title = self.big_font.render("ABOUT VAPORSTEP", True, MAGENTA)
        self.screen.blit(title, title.get_rect(center=(w // 2, int(h * 0.10))))

        sections = (
            ("HEALTH & SAFETY", CYAN, (
                "VaporStep involves stepping, reaching, twisting and rapid movement.",
                "Use a clear, stable play area, play within your abilities, and stop if you feel unwell.",
                "Children should play with appropriate adult supervision.",
            )),
            ("PRIVACY", CYAN, (
                "Webcam images are processed locally and are not saved or uploaded by VaporStep.",
                "Record Play saves the rendered game view and reconstructed game audio locally.",
            )),
            ("LICENSES", CYAN, (
                "VaporStep source code: MIT License.",
                "MediaPipe/model: Apache-2.0  •  Pygame: LGPL-2.1  •  NumPy: BSD-3-Clause.",
                "FFmpeg and other bundled components retain their own licenses.",
                "License/notice files and FFmpeg provenance are bundled with release builds.",
            )),
        )
        y = int(h * 0.19)
        for heading, color, lines in sections:
            hs = self.font.render(heading, True, color)
            self.screen.blit(hs, hs.get_rect(center=(w // 2, y)))
            y += 34
            for line in lines:
                surf = self.small_font.render(line, True, WHITE if heading == "HEALTH & SAFETY" else DIM)
                self.screen.blit(surf, surf.get_rect(center=(w // 2, y)))
                y += 29
            y += 17

        controls = self.small_font.render("Enter / Esc  back", True, GRID)
        self.screen.blit(controls, controls.get_rect(midbottom=(w // 2, h - 18)))

    def draw_main_menu(
        self,
        selected: int,
        songs_root,
        song_count: int,
        camera_index: int | None,
        horizontal_reach: float,
        camera_status: str = "",
    ) -> None:
        self.screen.fill(BG)
        now = pygame.time.get_ticks() / 1000.0
        self._draw_background(now, 0.0, False)
        w, h = self.size

        title = self.huge_font.render("VAPORSTEP", True, MAGENTA)
        self.screen.blit(title, title.get_rect(center=(w // 2, int(h * 0.20))))
        subtitle = self.small_font.render("FULL-BODY RHYTHM", True, CYAN)
        self.screen.blit(subtitle, subtitle.get_rect(center=(w // 2, int(h * 0.29))))

        options = ("PLAY", "CALIBRATE", "SONG FOLDER", "ABOUT", "QUIT")
        start_y = int(h * 0.40)
        for i, label in enumerate(options):
            y = start_y + i * 58
            active = i == selected
            color = WHITE if active else DIM
            text = self.big_font.render(label, True, color)
            rect = text.get_rect(center=(w // 2, y))
            if active:
                pygame.draw.line(self.screen, CYAN, (rect.left - 42, y), (rect.left - 14, y), 2)
                pygame.draw.line(self.screen, MAGENTA, (rect.right + 14, y), (rect.right + 42, y), 2)
            self.screen.blit(text, rect)

        root_text = str(songs_root) if songs_root is not None else "not configured"
        library = f"SONGS  {song_count}   •   {root_text}"
        lib = self.small_font.render(library, True, DIM)
        self.screen.blit(lib, lib.get_rect(midbottom=(w // 2, h - 64)))
        camera_label = "OFF" if camera_index is None else str(camera_index)
        camera = self.small_font.render(
            f"CAMERA {camera_label}   •   REACH {horizontal_reach:.2f}x" + (f"   •   {camera_status}" if camera_status else ""),
            True,
            DIM,
        )
        self.screen.blit(camera, camera.get_rect(midbottom=(w // 2, h - 40)))
        controls = self.small_font.render("↑/↓ choose    Enter select    F11 fullscreen", True, GRID)
        self.screen.blit(controls, controls.get_rect(midbottom=(w // 2, h - 16)))

    def draw_directory_browser(self, browser) -> None:
        self.screen.fill(BG)
        now = pygame.time.get_ticks() / 1000.0
        self._draw_background(now, 0.0, False)
        w, h = self.size

        title = self.big_font.render("SELECT SONG FOLDER", True, MAGENTA)
        self.screen.blit(title, title.get_rect(midtop=(w // 2, 28)))
        path = self.small_font.render(str(browser.current), True, CYAN)
        self.screen.blit(path, path.get_rect(midtop=(w // 2, 76)))

        entries = browser.entries
        visible = 11
        half = visible // 2
        start = max(0, min(browser.index - half, max(0, len(entries) - visible)))
        end = min(len(entries), start + visible)
        y0 = 126
        row_h = 42
        for i in range(start, end):
            label, _ = entries[i]
            active = i == browser.index
            color = WHITE if active else DIM
            if label == "USE THIS FOLDER":
                color = CYAN if active else _blend(CYAN, BG, 0.55)
                display = "[ USE THIS FOLDER ]"
            else:
                display = label + ("/" if label != ".." else "")
            surf = self.font.render(display, True, color)
            y = y0 + (i - start) * row_h
            if active:
                pygame.draw.line(self.screen, MAGENTA, (w // 2 - 330, y + 14), (w // 2 - 300, y + 14), 2)
            self.screen.blit(surf, (w // 2 - 280, y))

        if browser.error:
            err = self.small_font.render(browser.error, True, RED)
            self.screen.blit(err, err.get_rect(midbottom=(w // 2, h - 52)))
        controls = self.small_font.render("↑/↓ choose    Enter open/use    Esc cancel", True, DIM)
        self.screen.blit(controls, controls.get_rect(midbottom=(w // 2, h - 20)))

    def draw_calibration_overlay(
        self,
        camera_index: int | None,
        horizontal_reach: float,
        camera_status: str,
    ) -> None:
        w, h = self.size
        panel = pygame.Surface((min(660, w - 40), 108), pygame.SRCALPHA)
        panel.fill((*BG, 210))
        self.screen.blit(panel, (20, h - 128))
        camera_label = "OFF (KEYBOARD)" if camera_index is None else str(camera_index)
        line1 = self.font.render(
            f"CAMERA  {camera_label}      REACH  {horizontal_reach:.2f}x", True, WHITE
        )
        self.screen.blit(line1, (38, h - 118))
        line2 = self.small_font.render(
            "←/→ reach    ↑/↓ camera (below 0 = keyboard)    Esc save & return", True, CYAN
        )
        self.screen.blit(line2, (38, h - 88))
        tracking = self.small_font.render(
            "Foot control: bright cyan ring   •   faint dots: knee / ankle", True, DIM
        )
        self.screen.blit(tracking, (38, h - 62))
        line3 = self.small_font.render(camera_status, True, DIM)
        self.screen.blit(line3, (38, h - 38))

    def draw_song_menu(
        self,
        menu: SongMenu,
        songs_root,
        load_error: str | None,
        scan_error_count: int,
        record: ChartRecord | None = None,
        library_count: int = 0,
        favorite_keys: set[str] | None = None,
        favorites_only: bool = False,
        played_only: bool = False,
        chain_mode: ChainMode = ChainMode.BLOCKS,
        recording_enabled: bool = False,
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
        filter_text = self.small_font.render(
            f"{filter_label}   •   {len(menu.songs)}/{library_count or len(menu.songs)} SONGS   •   VIRTUAL HOLDS {chain_mode.label}",
            True,
            DIM,
        )
        self.screen.blit(filter_text, filter_text.get_rect(midtop=(w // 2, 88)))
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

        center_y = int(h * 0.34)
        row_h = 42
        nearest = int(round(menu.visual_position))
        max_rows = min(7, len(menu.songs))
        half = max_rows // 2
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

            text_x = max(38, w // 2 - 365)
            if song_key(song) in favorite_keys:
                cx, cy = text_x - 18, y + 13
                pygame.draw.polygon(
                    self.screen,
                    MAGENTA if selected else _blend(MAGENTA, BG, 0.45),
                    [(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)],
                )
            song_text = self.font.render(song.display_title, True, color)
            self.screen.blit(song_text, (text_x, y))
            artist = self.small_font.render(song.artist or "Unknown artist", True, artist_color)
            self.screen.blit(artist, (max(26, w // 2 + 115), y + 4))

        pygame.draw.line(self.screen, GRID, (w // 2 - 420, center_y + 31), (w // 2 + 420, center_y + 31), 1)

        song = menu.song
        chart = menu.chart
        if song is not None and chart is not None:
            panel_top = int(h * 0.58)
            banner = self._load_banner(song.banner_path)
            if banner is not None:
                box = pygame.Rect(max(22, w // 2 - 430), panel_top, 230, 82)
                pygame.draw.rect(self.screen, _blend(BG, PURPLE, 0.20), box, 1)
                scale = min(box.width / banner.get_width(), box.height / banner.get_height())
                size = (max(1, int(banner.get_width() * scale)), max(1, int(banner.get_height() * scale)))
                scaled = pygame.transform.smoothscale(banner, size)
                scaled.set_alpha(215)
                self.screen.blit(scaled, scaled.get_rect(center=box.center))

            info_x = max(24, w // 2 - 165)
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

    def _load_banner(self, path) -> pygame.Surface | None:
        if path is None:
            return None
        key = str(path)
        if key in self._banner_cache:
            return self._banner_cache[key]
        try:
            image = pygame.image.load(key).convert_alpha()
        except Exception:
            image = None
        self._banner_cache[key] = image
        return image

    def _draw_composition_bar(self, x: int, y: int, width: int, label: str, count: int, total: int, color) -> None:
        label_s = self.small_font.render(label, True, color if count else DIM)
        self.screen.blit(label_s, (x, y - 3))
        value = self.small_font.render("NONE" if count == 0 else f"{count:,}", True, WHITE if count else DIM)
        self.screen.blit(value, value.get_rect(topright=(x + width, y - 3)))
        bar_x = x + 62
        bar_w = max(30, width - 112)
        pygame.draw.rect(self.screen, _blend(GRID, BG, 0.30), (bar_x, y + 4, bar_w, 7), 1)
        if count > 0:
            fill = max(2, int(bar_w * min(1.0, count / max(total, 1))))
            pygame.draw.rect(self.screen, _blend(BG, color, 0.72), (bar_x + 1, y + 5, max(1, fill - 2), 5))

    def _draw_difficulty_selector(self, menu: SongMenu, y: int) -> None:
        song = menu.song
        if song is None:
            return
        w, _ = self.size
        pieces = []
        for idx, chart in enumerate(song.charts):
            selected = idx == menu.chart_index
            text = f"{chart.difficulty.upper()} {chart.meter}"
            surf = self.small_font.render(text, True, WHITE if selected else DIM)
            pieces.append((surf, selected))
        gap = 18
        total_w = sum(s.get_width() for s, _ in pieces) + gap * max(0, len(pieces) - 1)
        x = w // 2 - total_w // 2
        for surf, selected in pieces:
            if selected:
                rect = surf.get_rect(topleft=(x, y))
                pygame.draw.line(self.screen, CYAN, (rect.left, rect.bottom + 3), (rect.right, rect.bottom + 3), 2)
            self.screen.blit(surf, (x, y))
            x += surf.get_width() + gap

    def draw_results(
        self,
        song_title: str,
        chart_label: str,
        stats: RunStats,
        best_score: int,
        new_high: bool,
        failed: bool = False,
        recording_status: str = "",
    ) -> None:
        self.screen.fill(BG)
        t = pygame.time.get_ticks() / 1000.0
        decorative_pulse = 0.15 + 0.10 * (0.5 + 0.5 * math.sin(t * 2.0))
        self._draw_background(t, decorative_pulse, False)
        w, h = self.size

        title = self._song_metadata_font(28).render(song_title, True, WHITE)
        self.screen.blit(title, title.get_rect(midtop=(w // 2, 28)))
        chart = self.small_font.render(chart_label, True, DIM)
        self.screen.blit(chart, chart.get_rect(midtop=(w // 2, 60)))

        grade_text = "FAILED" if failed else stats.grade
        grade_color = RED if failed else (MAGENTA if stats.grade in ("S", "A") else CYAN)
        grade_font = self.big_font if failed else self.huge_font
        grade = grade_font.render(grade_text, True, grade_color)
        self.screen.blit(grade, grade.get_rect(center=(w // 2, int(h * 0.27))))

        score = self.score_font.render(f"{stats.score:,}", True, WHITE)
        self.screen.blit(score, score.get_rect(center=(w // 2, int(h * 0.42))))
        pct = self.font.render(f"{stats.score_ratio * 100.0:0.1f}% OF MAXIMUM SCORE", True, CYAN)
        self.screen.blit(pct, pct.get_rect(center=(w // 2, int(h * 0.48))))

        lines = [
            ("PERFECT", f"{stats.perfects:,}"),
            ("GREAT", f"{stats.greats:,}"),
            ("HIT", f"{stats.basic_hits:,}"),
            ("MISSED", f"{stats.misses:,}"),
            ("DROPPED HOLDS", f"{stats.dropped_holds:,}"),
            ("MAX COMBO", f"{stats.max_combo:,}"),
            ("BEST SCORE", f"{best_score:,}"),
        ]
        start_y = int(h * 0.55)
        for i, (label, value) in enumerate(lines):
            y = start_y + i * 30
            ls = self.small_font.render(label, True, DIM)
            vs = self.font.render(value, True, WHITE)
            self.screen.blit(ls, ls.get_rect(midright=(w // 2 - 16, y)))
            self.screen.blit(vs, vs.get_rect(midleft=(w // 2 + 16, y)))

        if new_high:
            banner = self.font.render("NEW HIGH SCORE", True, MAGENTA)
            self.screen.blit(banner, banner.get_rect(center=(w // 2, int(h * 0.84))))

        if recording_status:
            rec_color = RED if "ERROR" in recording_status else CYAN
            rec = self.small_font.render(recording_status, True, rec_color)
            self.screen.blit(rec, rec.get_rect(center=(w // 2, int(h * 0.89))))

        controls = self.small_font.render("Enter song selection    R replay    Esc song selection", True, DIM)
        self.screen.blit(controls, controls.get_rect(midbottom=(w // 2, h - 24)))

    def _draw_background(self, t: float, beat_pulse: float, downbeat: bool) -> None:
        w, h = self.size
        for i in range(22):
            x = (i * 173 + 37) % w
            y = (i * 97 + int(t * (10 + i % 4))) % max(h - 20, 1)
            pygame.draw.circle(self.screen, DIM, (x, y), 1)

    def _camera_rect(self) -> pygame.Rect:
        w, h = self.size
        camera_aspect = CAMERA_WIDTH / CAMERA_HEIGHT
        screen_aspect = w / max(h, 1)
        if screen_aspect >= camera_aspect:
            vh = h
            vw = int(vh * camera_aspect)
            x = (w - vw) // 2
            y = 0
        else:
            vw = w
            vh = int(vw / camera_aspect)
            x = 0
            y = (h - vh) // 2
        return pygame.Rect(x, y, vw, vh)

    def _camera_x(self, normalized_x: float) -> float:
        viewport = self._camera_rect()
        return viewport.left + normalized_x * viewport.width

    def _camera_y(self, normalized_y: float) -> float:
        viewport = self._camera_rect()
        return viewport.top + normalized_y * viewport.height

    def _hit_bounds(self, kind: NoteKind) -> tuple[float, float]:
        if kind == NoteKind.HANDS:
            return self._camera_x(HAND_PLAYFIELD_LEFT), self._camera_x(HAND_PLAYFIELD_RIGHT)
        return self._camera_x(FOOT_PLAYFIELD_LEFT), self._camera_x(FOOT_PLAYFIELD_RIGHT)

    def _vanish_bounds(self) -> tuple[float, float]:
        viewport = self._camera_rect()
        center = viewport.centerx
        half = viewport.width * VANISH_HALF_WIDTH
        return center - half, center + half

    def _field_bounds(self, kind: NoteKind, progress: float) -> tuple[float, float]:
        p = max(0.0, min(1.0, progress)) ** 1.35
        vl, vr = self._vanish_bounds()
        hl, hr = self._hit_bounds(kind)
        return vl + (hl - vl) * p, vr + (hr - vr) * p

    def _field_y(self, kind: NoteKind, progress: float) -> float:
        p = max(0.0, min(1.0, progress)) ** 1.35
        start = self._camera_y(VANISH_Y)
        end = self._camera_y(HAND_HIT_Y if kind == NoteKind.HANDS else FOOT_HIT_Y)
        return start + (end - start) * p

    def _lane_boundary_x(self, kind: NoteKind, boundary: int, progress: float) -> float:
        left, right = self._field_bounds(kind, progress)
        lane_w = (right - left) / 4.0
        x = left + boundary * lane_w
        edge_extension = lane_w * OUTER_LANE_EDGE_EXTENSION * max(0.0, min(1.0, progress))
        if boundary == 0:
            x -= edge_extension
        elif boundary == 4:
            x += edge_extension
        return x

    def _lane_bounds(self, kind: NoteKind, lane: int, progress: float) -> tuple[float, float]:
        return (
            self._lane_boundary_x(kind, lane - 1, progress),
            self._lane_boundary_x(kind, lane, progress),
        )

    def _draw_active_lane_fill(
        self, surface: pygame.Surface, kind: NoteKind, lane: int, color, beat_pulse: float
    ) -> None:
        l0, r0 = self._lane_bounds(kind, lane, 0.0)
        l1, r1 = self._lane_bounds(kind, lane, 1.0)
        y0 = self._field_y(kind, 0.0)
        y1 = self._field_y(kind, 1.0)
        alpha = 54
        pygame.draw.polygon(surface, (*color, alpha), [(l0, y0), (r0, y0), (r1, y1), (l1, y1)])


    def _draw_buzz_rails(
        self,
        kind: NoteKind,
        color,
        song_time: float,
        beat_pulse: float,
        downbeat: bool,
        overdrive: bool = False,
        animated: bool = True,
    ) -> None:
        trace_base = ELECTRIC_YELLOW if overdrive else color
        if not animated:
            trace_color = _blend(BG, trace_base, 0.42)
            for side in (0, 4):
                points: list[tuple[int, int]] = []
                for i in range(31):
                    p = i / 30.0
                    boundary_x = self._lane_boundary_x(kind, side, p)
                    y = self._field_y(kind, p)
                    offset = -8.0 if side == 0 else 8.0
                    points.append((int(boundary_x + offset), int(y)))
                if len(points) >= 2:
                    pygame.draw.lines(self.screen, _blend(BG, trace_color, 0.25), False, points, 3)
                    pygame.draw.lines(self.screen, trace_color, False, points, 1)
            return

        base_amp = 11.2
        beat_amp = (33.6 if downbeat else 25.6) * beat_pulse
        amplitude = base_amp + beat_amp
        glow = min(1.0, 0.34 + beat_pulse * (0.58 if downbeat else 0.46))
        trace_color = _blend(DIM, trace_base, glow)

        samples = 30
        for side, sign in ((0, -1.0), (4, 1.0)):
            points: list[tuple[int, int]] = []
            for i in range(samples + 1):
                p = i / samples
                boundary_x = self._lane_boundary_x(kind, side, p)
                y = self._field_y(kind, p)
                noise = (
                    math.sin(song_time * 22.0 + p * 77.0 + side * 0.7)
                    + 0.55 * math.sin(song_time * 41.0 + p * 143.0 + side * 1.3)
                    + 0.28 * math.sin(song_time * 67.0 + p * 211.0)
                ) / 1.83
                offset = sign * (8.0 + amplitude * noise)
                points.append((int(boundary_x + offset), int(y)))

            if len(points) >= 2:
                pygame.draw.lines(self.screen, _blend(BG, trace_color, 0.35), False, points, 3)
                pygame.draw.lines(self.screen, trace_color, False, points, 1)

    def _note_progress(self, note: GameNote, song_time: float, song_beat: float) -> float:
        return note_progress(note, song_time, song_beat)



    def _draw_hit_pop_bar(
        self, kind: NoteKind, lane: int, age: float, quality: HitQuality
    ) -> None:
        phase = max(0.0, min(1.0, age / HIT_BRICK_POP_SECONDS))
        left, right = self._lane_bounds(kind, lane, 1.0)
        y = self._field_y(kind, 1.0)
        lane_w = max(4.0, right - left)
        center = (left + right) * 0.5
        power = {HitQuality.HIT: 1.0, HitQuality.GREAT: 1.28, HitQuality.PERFECT: 1.60}[quality]

        kick = math.sin(min(1.0, phase * 1.6) * math.pi)
        half = lane_w * (0.39 + 0.055 * power * kick)
        gap = lane_w * (0.02 + 0.16 * phase)
        fade = (1.0 - phase) ** 0.72
        theme = MAGENTA if kind == NoteKind.HANDS else CYAN
        hot = _blend(theme, WHITE, min(0.92, 0.40 + 0.24 * power))
        color = _blend(BG, hot, fade)
        thickness = max(3, int((13 + 4 * power) * (0.72 + 0.28 * fade)))

        x0 = center - half
        x1 = center - gap
        x2 = center + gap
        x3 = center + half
        pygame.draw.line(self.screen, BG, (x0, y), (x1, y), thickness + 9)
        pygame.draw.line(self.screen, BG, (x2, y), (x3, y), thickness + 9)
        pygame.draw.line(self.screen, color, (x0, y), (x1, y), thickness)
        pygame.draw.line(self.screen, color, (x2, y), (x3, y), thickness)
        if fade > 0.16:
            highlight = _blend(color, WHITE, 0.68 * fade)
            pygame.draw.line(self.screen, highlight, (x0, y - thickness // 4), (x1, y - thickness // 4), 2)
            pygame.draw.line(self.screen, highlight, (x2, y - thickness // 4), (x3, y - thickness // 4), 2)

    def _draw_note_bar(self, kind: NoteKind, lane: int, progress: float, color, hit: bool) -> None:
        left, right = self._lane_bounds(kind, lane, progress)
        y = self._field_y(kind, progress)
        pad = max(2.0, (right - left) * 0.08)
        thickness = max(4, int(4 + 12 * progress))
        pygame.draw.line(self.screen, BG, (left + pad, y), (right - pad, y), thickness + 8)
        pygame.draw.line(self.screen, color, (left + pad, y), (right - pad, y), thickness)
        pygame.draw.line(
            self.screen,
            WHITE if hit else color,
            (left + pad, y - max(1, thickness // 4)),
            (right - pad, y - max(1, thickness // 4)),
            1,
        )



    def _judgement_for_lane(self, notes, song_time, kind, lane) -> tuple[str | None, float]:
        newest: tuple[str | None, float] = (None, 999.0)
        for note in notes:
            if note.kind != kind or lane not in note.lanes or not note.judged or note.judged_at is None:
                continue
            age = song_time - note.judged_at
            if 0.0 <= age <= HIT_FLASH_SECONDS and age < newest[1]:
                if note.hit:
                    label = (note.judgement or HitQuality.HIT).value
                else:
                    label = "miss"
                newest = (label, age)
        return newest

    def _target_is_near(self, notes, song_time, kind, lane) -> bool:
        for note in notes:
            if note.judged or note.kind != kind or lane not in note.lanes:
                continue
            if abs(note.time - song_time) <= max(0.45, HIT_WINDOW_SECONDS):
                return True
        return False


    def _draw_silhouette(self, mask: np.ndarray) -> None:
        viewport = self._camera_rect()
        size = (viewport.width, viewport.height)
        if mask is not self._last_mask or size != self._silhouette_size:
            source = mask
            if self.player_horizontal_zoom > 1.0 and getattr(mask, "shape", None) is not None and mask.ndim >= 2:
                source_w = mask.shape[1]
                crop_w = max(1, min(source_w, int(round(source_w / self.player_horizontal_zoom))))
                x0 = max(0, (source_w - crop_w) // 2)
                source = mask[:, x0 : x0 + crop_w]
            resized = cv2.resize(source, size, interpolation=cv2.INTER_LINEAR)
            clipped = np.clip((resized - 0.25) / 0.55, 0.0, 1.0)
            alpha = (clipped * 75).astype(np.uint8)
            surf = pygame.Surface(size, pygame.SRCALPHA)
            surf.fill((*PURPLE, 0))
            a = pygame.surfarray.pixels_alpha(surf)
            a[:, :] = alpha.T
            del a

            binary = (resized > 0.50).astype(np.uint8) * 255
            edges = cv2.Canny(binary, 60, 120)
            outline = pygame.Surface(size, pygame.SRCALPHA)
            outline.fill((*CYAN, 0))
            oa = pygame.surfarray.pixels_alpha(outline)
            oa[:, :] = (edges.T * 0.60).astype(np.uint8)
            del oa
            surf.blit(outline, (0, 0))
            self._silhouette_surface = surf
            self._last_mask = mask
            self._silhouette_size = size
        if self._silhouette_surface is not None:
            self.screen.blit(self._silhouette_surface, viewport.topleft)

    def _screen_point(self, p: BodyPoint) -> tuple[int, int]:
        viewport = self._camera_rect()
        return (int(viewport.left + p.x * viewport.width), int(viewport.top + p.y * viewport.height))


    def _draw_hud(
        self,
        stats: RunStats,
        best_score: int,
        beat_pulse: float = 0.0,
        performance_state: str = "ok",
        chain_mode: ChainMode = ChainMode.OFF,
    ) -> None:
        w, h = self.size
        score_label = self.small_font.render("SCORE", True, CYAN)
        score = self.score_font.render(f"{stats.score:,}", True, WHITE)
        self.screen.blit(score_label, (18, 14))
        self.screen.blit(score, (18, 31))

        best_label = self.small_font.render("BEST", True, MAGENTA)
        best = self.score_font.render(f"{best_score:,}", True, WHITE)
        self.screen.blit(best_label, best_label.get_rect(topright=(w - 18, 14)))
        self.screen.blit(best, best.get_rect(topright=(w - 18, 31)))
        chain_label = self.small_font.render(f"V  VIRTUAL HOLDS: {chain_mode.label}", True, DIM)
        self.screen.blit(chain_label, chain_label.get_rect(topright=(w - 18, 70)))

        center_y = int(h * VANISH_Y) - 48
        if performance_state == "failed":
            phase = (pygame.time.get_ticks() // 220) % 2
            failed_color = RED if phase == 0 else _blend(RED, WHITE, 0.35)
            failed = self.combo_font.render("FAILED", True, failed_color)
            self.screen.blit(failed, failed.get_rect(center=(w // 2, center_y + 12)))
            hold = self.small_font.render("RUN ENDED", True, failed_color)
            self.screen.blit(hold, hold.get_rect(center=(w // 2, center_y + 52)))
            return

        if performance_state in ("warning", "danger"):
            danger = performance_state == "danger"
            if danger:
                phase = (pygame.time.get_ticks() // 180) % 2
                warning_color = RED if phase == 0 else _blend(RED, WHITE, 0.45)
                word = "DANGER"
            else:
                warning_color = AMBER
                word = "WARNING"

            if stats.combo > 0:
                combo = self.combo_font.render(str(stats.combo), True, warning_color)
                self.screen.blit(combo, combo.get_rect(center=(w // 2, center_y)))
            warning = self.font.render(word, True, warning_color)
            self.screen.blit(warning, warning.get_rect(center=(w // 2, center_y + 36)))
            recent = stats.recent_hit_rate
            if recent is not None:
                rate = self.small_font.render(
                    f"LAST {stats.recent_window_size}  {recent * 100:0.0f}%", True, warning_color
                )
                self.screen.blit(rate, rate.get_rect(center=(w // 2, center_y + 60)))
            return

        if stats.combo <= 0:
            return

        combo_colors = {
            1: WHITE,
            2: CYAN,
            3: PURPLE,
            4: MAGENTA,
            5: ELECTRIC_YELLOW,
        }
        combo_color = combo_colors[stats.multiplier]
        combo = self.combo_font.render(str(stats.combo), True, combo_color)
        scale = 1.0 + 0.075 * beat_pulse
        if scale > 1.002:
            combo = pygame.transform.smoothscale(
                combo,
                (max(1, int(combo.get_width() * scale)), max(1, int(combo.get_height() * scale))),
            )
        combo_label = self.small_font.render("COMBO", True, _blend(DIM, combo_color, 0.35))
        mult_label = "MAX ×5" if stats.multiplier >= 5 else f"×{stats.multiplier}"
        mult = self.font.render(mult_label, True, combo_color)
        self.screen.blit(combo, combo.get_rect(center=(w // 2, center_y)))
        self.screen.blit(combo_label, combo_label.get_rect(center=(w // 2, center_y + 31)))
        self.screen.blit(mult, mult.get_rect(center=(w // 2, center_y + 54)))

        if stats.multiplier >= 5:
            t = pygame.time.get_ticks() / 1000.0
            for i in range(7):
                phase = (t * 1.8 + i / 7.0) % 1.0
                x = w // 2 + int(math.sin(i * 2.27 + t * 2.0) * (24 + 12 * phase))
                y = center_y + 34 - int(65 * phase)
                ember = _blend(BG, ELECTRIC_YELLOW, 1.0 - phase)
                pygame.draw.line(self.screen, ember, (x, y), (x + (i % 3) - 1, y - 5), 2)

    def _draw_audio_error(self, audio_error: str) -> None:
        w, h = self.size
        surf = self.small_font.render(f"Audio unavailable: {audio_error}", True, RED)
        self.screen.blit(surf, surf.get_rect(midbottom=(w // 2, h - 8)))

    def _draw_status(self, status, input_name, song_title, chart_label, audio_error) -> None:
        status_lines = str(status).splitlines()
        lines = []
        for index, value in enumerate(status_lines):
            line_color = GREEN if index == 0 and value == "READY" else WHITE
            font = self.font if index == 0 else self.small_font
            lines.append((value, line_color, font))
        lines.extend(
            (
                (song_title, WHITE, self._song_metadata_font(21)),
                (chart_label, DIM, self.small_font),
            )
        )
        if audio_error:
            lines.append((f"Audio unavailable: {audio_error}", RED, self.small_font))
        x, y = 14, 12
        for value, line_color, font in lines:
            if not value:
                continue
            surf = font.render(value, True, line_color)
            bg = pygame.Surface((surf.get_width() + 12, surf.get_height() + 6), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 145))
            self.screen.blit(bg, (x - 6, y - 3))
            self.screen.blit(surf, (x, y))
            y += surf.get_height() + 8

    def _draw_debug(self, body: BodyState, t: float, pose_fps: float) -> None:
        labels = [
            ("LW", body.left_wrist),
            ("RW", body.right_wrist),
            ("LK", body.left_knee),
            ("RK", body.right_knee),
            ("LF", body.left_foot_control),
            ("RF", body.right_foot_control),
        ]
        lines = [f"song {t:5.2f}s    pose {pose_fps:4.1f} fps"]
        for name, p in labels:
            lane = "-" if p.lane is None else str(p.lane)
            vis = "ok" if p.visible else "lost"
            lines.append(f"{name}: lane {lane}   x={p.x:0.3f} y={p.y:0.3f} {vis}")
        lines.append(f"feet(control)={sorted(body.foot_lanes)} hands={sorted(body.hand_lanes)}")
        x, y = 18, 92
        for line in lines:
            surf = self.small_font.render(line, True, WHITE)
            bg = pygame.Surface((surf.get_width() + 12, surf.get_height() + 4), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 155))
            self.screen.blit(bg, (x - 6, y - 2))
            self.screen.blit(surf, (x, y))
            y += 23
