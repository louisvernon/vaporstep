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
        self.player_horizontal_zoom = 1.10

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
        # Sit below BEST / chain-mode HUD so it is visible during READY and play
        # without covering incoming notes or the combo counter.
        self.screen.blit(label, label.get_rect(topright=(w - 18, 94)))

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
            "MediaPipe Tasks may send performance and usage metrics to Google.",
            "The camera is active only during calibration and gameplay.",
        )
        y = int(h * 0.51)
        for line in privacy_lines:
            surf = self.small_font.render(line, True, DIM)
            self.screen.blit(surf, surf.get_rect(center=(w // 2, y)))
            y += 32

        accept = self.font.render("ENTER  I UNDERSTAND — CONTINUE", True, CYAN)
        self.screen.blit(accept, accept.get_rect(center=(w // 2, int(h * 0.74))))
        more = self.small_font.render("Safety, privacy and license information is available from About.", True, DIM)
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
                "MediaPipe Tasks may send performance/utilization metrics to Google.",
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
        camera_index: int,
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
        camera = self.small_font.render(
            f"CAMERA {camera_index}   •   REACH {horizontal_reach:.2f}x" + (f"   •   {camera_status}" if camera_status else ""),
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
        camera_index: int,
        horizontal_reach: float,
        camera_status: str,
    ) -> None:
        w, h = self.size
        panel = pygame.Surface((min(660, w - 40), 108), pygame.SRCALPHA)
        panel.fill((*BG, 210))
        self.screen.blit(panel, (20, h - 128))
        line1 = self.font.render(
            f"CAMERA  {camera_index}      REACH  {horizontal_reach:.2f}x", True, WHITE
        )
        self.screen.blit(line1, (38, h - 118))
        line2 = self.small_font.render(
            "←/→ reach    ↑/↓ camera    Esc save & return", True, CYAN
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
            f"{filter_label}   •   {len(menu.songs)}/{library_count or len(menu.songs)} SONGS   •   CHAINS {chain_mode.label}",
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

        # Leave more room below the wheel for chart information/artwork.
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
            # Optional source-chart banner. It stays secondary to the vector UI.
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
            chains_text = self.small_font.render(f"CHAINS  {chart.chain_count}", True, WHITE)
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

            # Show the full chart ladder so left/right selection is immediately legible.
            difficulty_y = min(h - 88, panel_top + 128)
            self._draw_difficulty_selector(menu, difficulty_y)

            controls = self.small_font.render(
                "↑/↓ song    ←/→ difficulty    Enter play    F favorite    Shift+F favorites    Shift+P played    Shift+R record",
                True,
                DIM,
            )
            self.screen.blit(controls, controls.get_rect(midbottom=(w // 2, h - 34)))
            controls2 = self.small_font.render(
                f"A/C chain mode: {chain_mode.label}    F11 fullscreen    Esc main menu", True, DIM
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

        title = self.font.render(song_title, True, WHITE)
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
        # No full-width horizon line: even a static line visually merged with the
        # beat-reactive geometry and read as a pulsing bar through the player.
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
        """Return one of the five lane boundaries at ``progress``.

        Interior boundaries retain the existing perspective geometry. Only the
        two outside edges flare a little wider toward the receptors, matching
        the tracker-side outer-edge extension without squeezing lanes 2/3.
        """
        left, right = self._field_bounds(kind, progress)
        lane_w = (right - left) / 4.0
        x = left + boundary * lane_w
        # No extra width at the shared vanishing point; smoothly reach the full
        # extension at the receptor end.
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
        # A translucent trapezoid makes occupancy readable at a glance instead
        # of asking the player to infer it from two highlighted rail edges.
        l0, r0 = self._lane_bounds(kind, lane, 0.0)
        l1, r1 = self._lane_bounds(kind, lane, 1.0)
        y0 = self._field_y(kind, 0.0)
        y1 = self._field_y(kind, 1.0)
        alpha = 54
        pygame.draw.polygon(surface, (*color, alpha), [(l0, y0), (r0, y0), (r1, y1), (l1, y1)])

    def _draw_playfields(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        downbeat: bool,
        hand_enabled: bool,
        foot_enabled: bool,
        overdrive: bool = False,
        animate_buzz: bool = True,
    ) -> None:
        # Structural playfield geometry stays stable. Musical motion is carried
        # by the dedicated buzz traces outside the rails instead of strobing
        # the columns themselves.
        grid_color = GRID

        # Reuse one alpha surface per frame rather than allocating a full-screen
        # surface for every occupied limb/lane.
        if self._lane_fill_surface is None or self._lane_fill_surface.get_size() != self.size:
            self._lane_fill_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        self._lane_fill_surface.fill((0, 0, 0, 0))
        for kind, color, enabled in (
            (NoteKind.HANDS, MAGENTA, hand_enabled),
            (NoteKind.FOOT, CYAN, foot_enabled),
        ):
            if not enabled:
                continue
            occupied = body.hand_lanes if kind == NoteKind.HANDS else body.foot_lanes
            for lane in occupied:
                self._draw_active_lane_fill(self._lane_fill_surface, kind, lane, color, beat_pulse)
        self.screen.blit(self._lane_fill_surface, (0, 0))

        for kind, color, enabled in (
            (NoteKind.HANDS, MAGENTA, hand_enabled),
            (NoteKind.FOOT, CYAN, foot_enabled),
        ):
            occupied = body.hand_lanes if kind == NoteKind.HANDS else body.foot_lanes
            if not enabled:
                occupied = frozenset()

            disabled_grid = _blend(GRID, BG, 0.62)
            local_grid = grid_color if enabled else disabled_grid
            outer_base = color if enabled else _blend(DIM, BG, 0.55)
            outer_color = outer_base
            outer_width = 2 if enabled else 1

            for i in range(5):
                x0 = self._lane_boundary_x(kind, i, 0.0)
                x1 = self._lane_boundary_x(kind, i, 1.0)
                y0 = self._field_y(kind, 0.0)
                y1 = self._field_y(kind, 1.0)
                if i in (0, 4):
                    pygame.draw.line(self.screen, outer_color, (x0, y0), (x1, y1), outer_width)
                else:
                    pygame.draw.line(self.screen, local_grid, (x0, y0), (x1, y1), 1)

            # Keep colored active-lane borders as a crisp accent on top of the
            # filled column, but they are no longer the sole occupancy cue.
            if enabled:
                for lane in occupied:
                    active_color = color
                    for boundary in (lane - 1, lane):
                        x0 = self._lane_boundary_x(kind, boundary, 0.0)
                        x1 = self._lane_boundary_x(kind, boundary, 1.0)
                        y0 = self._field_y(kind, 0.0)
                        y1 = self._field_y(kind, 1.0)
                        pygame.draw.line(self.screen, active_color, (x0, y0), (x1, y1), 3)

            for j in range(1, 8):
                p = j / 8.0
                left = self._lane_boundary_x(kind, 0, p)
                right = self._lane_boundary_x(kind, 4, p)
                y = self._field_y(kind, p)
                pygame.draw.line(self.screen, local_grid, (left, y), (right, y), 1)

            if enabled:
                self._draw_buzz_rails(kind, color, song_time, beat_pulse, downbeat, overdrive, animated=animate_buzz)

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
        """Draw oscilloscope-like traces just outside the playfield.

        During READY/positioning, the traces stay flat and calm so the screen
        communicates that gameplay timing has not started yet. Once the song is
        running, they animate/pulse with the chart beat.
        """
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

        # Return the buzz traces to the hand/foot theme colors, but make the
        # waveform substantially larger. The displacement is intentionally large enough to read clearly while
        # remaining outside the gameplay rails.
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

                # Deterministic pseudo-static: layered sine terms read as a
                # vector buzz line rather than a smooth decorative wave.
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

    def _draw_chains(
        self,
        chains: tuple[RuntimeChain, ...],
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        # READY deliberately hides incoming chart geometry.
        if not chains or not notes:
            return
        for chain in chains:
            definition = chain.definition
            is_hold = definition.source == SustainSource.EXPLICIT_HOLD
            if not is_hold and chain_mode == ChainMode.OFF:
                continue
            if not timed_is_within_lookahead(
                definition.start_time, definition.start_beat, song_time, song_beat
            ):
                continue
            if chain.state == ChainState.COMPLETE and song_time > definition.end_time + 0.10:
                continue
            if song_time > definition.end_time + HIT_FLASH_SECONDS:
                continue

            head_progress = timed_progress(
                definition.start_time, definition.start_beat, song_time, song_beat
            )
            tail_progress = timed_progress(
                definition.end_time, definition.end_beat, song_time, song_beat
            )
            lo = min(head_progress, tail_progress)
            hi = max(head_progress, tail_progress)
            if hi <= 0.0:
                continue

            theme = MAGENTA if definition.kind == NoteKind.HANDS else CYAN
            if chain.state == ChainState.BROKEN:
                fill = _blend(BG, DIM, 0.56)
                edge = _blend(DIM, WHITE, 0.10)
            elif chain.state == ChainState.ACTIVE:
                fill = _blend(BG, theme, 0.52)
                edge = _blend(theme, WHITE, 0.30)
            else:
                fill = _blend(BG, theme, 0.27)
                edge = _blend(BG, theme, 0.66)

            for lane in definition.lanes:
                left0, right0 = self._lane_bounds(definition.kind, lane, lo)
                left1, right1 = self._lane_bounds(definition.kind, lane, hi)
                y0 = self._field_y(definition.kind, lo)
                y1 = self._field_y(definition.kind, hi)
                pad0 = max(2.0, (right0 - left0) * 0.10)
                pad1 = max(2.0, (right1 - left1) * 0.10)
                polygon = [
                    (int(left0 + pad0), int(y0)),
                    (int(right0 - pad0), int(y0)),
                    (int(right1 - pad1), int(y1)),
                    (int(left1 + pad1), int(y1)),
                ]
                pygame.draw.polygon(self.screen, fill, polygon)
                pygame.draw.lines(self.screen, edge, True, polygon, 2 if chain.state == ChainState.ACTIVE else 1)

                center0 = (left0 + right0) * 0.5
                center1 = (left1 + right1) * 0.5
                center_color = WHITE if chain.state == ChainState.ACTIVE else edge
                pygame.draw.line(
                    self.screen,
                    center_color,
                    (int(center0), int(y0)),
                    (int(center1), int(y1)),
                    2 if chain.state == ChainState.ACTIVE else 1,
                )

                # Give every sustain a real note-like leading edge. The body
                # communicates duration; this bright bar communicates exactly
                # what must be hit to start the hold/chain.
                head_p = max(0.0, min(1.0, head_progress))
                head_left, head_right = self._lane_bounds(definition.kind, lane, head_p)
                head_y = self._field_y(definition.kind, head_p)
                head_pad = max(2.0, (head_right - head_left) * 0.08)
                head_thickness = max(5, int(4 + 12 * head_p))
                if chain.state == ChainState.BROKEN:
                    head_color = _blend(BG, DIM, 0.72)
                else:
                    head_color = theme
                pygame.draw.line(
                    self.screen,
                    BG,
                    (head_left + head_pad, head_y),
                    (head_right - head_pad, head_y),
                    head_thickness + 8,
                )
                pygame.draw.line(
                    self.screen,
                    head_color,
                    (head_left + head_pad, head_y),
                    (head_right - head_pad, head_y),
                    head_thickness,
                )
                if chain.state != ChainState.BROKEN:
                    pygame.draw.line(
                        self.screen,
                        WHITE,
                        (head_left + head_pad, head_y - max(1, head_thickness // 4)),
                        (head_right - head_pad, head_y - max(1, head_thickness // 4)),
                        1,
                    )

                # A bright receptor cap makes successful sustain activation
                # unmistakable while the long body communicates the hold.
                if chain.state == ChainState.ACTIVE:
                    left, right = self._lane_bounds(definition.kind, lane, 1.0)
                    y = self._field_y(definition.kind, 1.0)
                    cap_pad = max(2.0, (right - left) * 0.08)
                    pygame.draw.line(self.screen, theme, (left + cap_pad, y), (right - cap_pad, y), 9)
                    pygame.draw.line(self.screen, WHITE, (left + cap_pad, y), (right - cap_pad, y), 2)

    def _draw_notes(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode = ChainMode.OFF,
    ) -> None:
        for note in notes:
            if note.end_time is not None and note.chain_id is not None:
                # Explicit holds are always represented by their long sustain
                # block; chain debug/off modes only affect generated chains.
                continue
            if note.chain_id is not None and chain_mode == ChainMode.BLOCKS:
                continue
            dt = note.time - song_time
            if not note_is_within_lookahead(note, song_time, song_beat):
                continue
            if note.judged and note.judged_at is not None:
                age = song_time - note.judged_at
                if age > HIT_FLASH_SECONDS:
                    continue
                # Successful bricks disappear almost immediately into fragments;
                # misses linger red so the failure remains readable.
                if note.hit and age > HIT_BRICK_POP_SECONDS:
                    continue
            elif dt < -HIT_WINDOW_SECONDS:
                continue

            if note.judged and note.hit:
                quality = note.judgement or HitQuality.HIT
                color = WHITE if quality != HitQuality.PERFECT else _blend(AMBER, WHITE, 0.55)
            elif note.judged:
                color = RED
            else:
                color = MAGENTA if note.kind == NoteKind.HANDS else CYAN

            progress = self._note_progress(note, song_time, song_beat)

            if not note.judged:
                beat_phase = song_beat - math.floor(song_beat)
                breathe = 0.5 + 0.5 * math.cos(beat_phase * math.tau)
                near_receptor = max(0.0, min(1.0, progress))
                trough = 0.72 + 0.14 * near_receptor
                intensity = trough + (1.0 - trough) * breathe
                color = _blend(BG, color, intensity)
                color = _blend(color, WHITE, 0.05 * breathe)

            for lane in note.lanes:
                if note.judged and note.hit and note.judged_at is not None:
                    self._draw_hit_pop_bar(
                        note.kind,
                        lane,
                        max(0.0, song_time - note.judged_at),
                        note.judgement or HitQuality.HIT,
                    )
                else:
                    self._draw_note_bar(note.kind, lane, progress, color, False)

    def _draw_hit_pop_bar(
        self, kind: NoteKind, lane: int, age: float, quality: HitQuality
    ) -> None:
        phase = max(0.0, min(1.0, age / HIT_BRICK_POP_SECONDS))
        left, right = self._lane_bounds(kind, lane, 1.0)
        y = self._field_y(kind, 1.0)
        lane_w = max(4.0, right - left)
        center = (left + right) * 0.5
        power = {HitQuality.HIT: 1.0, HitQuality.GREAT: 1.28, HitQuality.PERFECT: 1.60}[quality]

        # The tile briefly grows, splits at the center, and burns out. This gives
        # the eye one readable impact frame before the shards take over.
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

    def _spawn_note_effects(self, notes: list[GameNote]) -> None:
        for note in notes:
            ident = id(note)
            if not note.judged or note.judged_at is None:
                continue
            if not note.hit:
                if ident not in self._seen_misses:
                    self._seen_misses.add(ident)
                    for lane in note.lanes:
                        self._miss_impacts.append(
                            {
                                "kind": note.kind,
                                "lane": lane,
                                "born": note.judged_at,
                                "life": 0.34,
                            }
                        )
                continue
            if ident in self._seen_hits:
                continue
            self._seen_hits.add(ident)
            quality = note.judgement or HitQuality.HIT
            power = {HitQuality.HIT: 1.0, HitQuality.GREAT: 1.35, HitQuality.PERFECT: 1.75}[quality]
            base_color = MAGENTA if note.kind == NoteKind.HANDS else CYAN
            shard_color = _blend(base_color, WHITE, {HitQuality.HIT: 0.10, HitQuality.GREAT: 0.35, HitQuality.PERFECT: 0.60}[quality])
            count = {HitQuality.HIT: 11, HitQuality.GREAT: 17, HitQuality.PERFECT: 25}[quality]
            for lane in note.lanes:
                self._impact_bursts.append(
                    {
                        "kind": note.kind,
                        "lane": lane,
                        "born": note.judged_at,
                        "life": {HitQuality.HIT: 0.18, HitQuality.GREAT: 0.23, HitQuality.PERFECT: 0.29}[quality],
                        "power": power,
                        "color": shard_color,
                    }
                )
                # A smaller portion of the impact continues past the receptor
                # toward the screen edge. This makes the destruction readable
                # at the actual collision point while preserving the stronger
                # reflected beam/shards travelling back toward the origin.
                outward_count = {HitQuality.HIT: 4, HitQuality.GREAT: 6, HitQuality.PERFECT: 9}[quality]
                for _ in range(outward_count):
                    self._outbound_particles.append(
                        {
                            "kind": note.kind,
                            "lane": lane,
                            "born": note.judged_at,
                            "life": self._rng.uniform(0.20, 0.34),
                            "vx": self._rng.uniform(-48.0, 48.0) * power,
                            "vy": self._rng.uniform(150.0, 280.0) * power,
                            "length": self._rng.uniform(7.0, 18.0) * power,
                            "size": self._rng.randint(1, 3),
                            "color": shard_color,
                        }
                    )
                for _ in range(count):
                    self._particles.append(
                        {
                            "kind": note.kind,
                            "lane": lane,
                            "born": note.judged_at,
                            "life": self._rng.uniform(0.38, 0.66) * (0.95 + 0.12 * power),
                            "speed": self._rng.uniform(1.05, 2.15) * (0.90 + 0.12 * power),
                            "jitter": self._rng.uniform(-0.12, 0.12),
                            "lateral": self._rng.uniform(-0.95, 0.95),
                            "drift": self._rng.uniform(-0.20, 0.20),
                            "length": self._rng.uniform(0.10, 0.24) * power,
                            "size": self._rng.randint(2, max(3, int(3 + power))),
                            "color": shard_color,
                        }
                    )

    def _draw_particles(self, song_time: float) -> None:
        # A cheap receptor-local impact bloom gives each successful tile a
        # readable POP before the existing vector shards travel up the lane.
        burst_alive: list[dict[str, object]] = []
        for burst in self._impact_bursts:
            age = song_time - float(burst["born"])
            life = float(burst["life"])
            if age < 0.0 or age > life:
                continue
            phase = age / max(life, 1e-6)
            kind = burst["kind"]
            lane = int(burst["lane"])
            left, right = self._lane_bounds(kind, lane, 1.0)
            cx = int((left + right) * 0.5)
            cy = int(self._field_y(kind, 1.0))
            lane_w = max(4.0, right - left)
            power = float(burst["power"])
            fade = (1.0 - phase) ** 1.4
            color = _blend(BG, burst["color"], fade)
            radius = int(lane_w * (0.10 + 0.30 * phase) * power)
            # Diamond + cross reads as an impact rather than a soft glow.
            diamond = [(cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy)]
            pygame.draw.polygon(self.screen, _blend(BG, color, 0.24 * fade), diamond, 0)
            pygame.draw.polygon(
                self.screen,
                _blend(BG, color, 0.70),
                diamond,
                max(1, int(5 * fade)),
            )
            arm = int(radius * 0.72)
            pygame.draw.line(self.screen, color, (cx - arm, cy), (cx + arm, cy), max(1, int(3 * fade)))
            pygame.draw.line(self.screen, color, (cx, cy - arm), (cx, cy + arm), max(1, int(3 * fade)))
            burst_alive.append(burst)
        self._impact_bursts = burst_alive

        alive: list[dict[str, object]] = []
        for p in self._particles:
            age = song_time - float(p["born"])
            life = float(p["life"])
            if age < 0.0 or age > life:
                continue
            progress = max(0.03, 1.0 - age * float(p["speed"]))
            kind = p["kind"]
            lane = int(p["lane"])
            left, right = self._lane_bounds(kind, lane, progress)
            lane_w = max(1.0, right - left)
            center = (left + right) / 2.0
            particle_phase = age / max(life, 1e-6)
            drift = float(p["drift"]) * particle_phase
            lateral = float(p.get("lateral", 0.0)) * (particle_phase ** 0.72) * 0.72
            x = center + (float(p["jitter"]) + drift + lateral) * lane_w
            y = self._field_y(kind, progress)
            fade = 1.0 - age / life
            color = _blend(BG, p["color"], fade)

            # Rectangular/vector shards make the arriving bar appear to fracture
            # rather than merely vanish into generic sparkles.
            length = max(2.0, lane_w * float(p["length"]) * (0.35 + 0.65 * fade))
            thickness = max(1, int(int(p["size"]) * (0.65 + fade)))
            tilt = float(p["jitter"]) * 0.35
            dx = length * 0.5
            dy = dx * tilt
            pygame.draw.line(
                self.screen,
                _blend(BG, color, 0.42),
                (int(x - dx), int(y - dy)),
                (int(x + dx), int(y + dy)),
                thickness + 3,
            )
            pygame.draw.line(
                self.screen,
                color,
                (int(x - dx), int(y - dy)),
                (int(x + dx), int(y + dy)),
                thickness,
            )
            alive.append(p)
        self._particles = alive

        # Success debris that escapes beyond the receptor. Kept intentionally
        # small so the main reflected pulse still owns the visual language.
        outward_alive: list[dict[str, object]] = []
        for p in self._outbound_particles:
            age = song_time - float(p["born"])
            life = float(p["life"])
            if age < 0.0 or age > life:
                continue
            kind = p["kind"]
            lane = int(p["lane"])
            left, right = self._lane_bounds(kind, lane, 1.0)
            cx = (left + right) * 0.5
            hit_y = self._field_y(kind, 1.0)
            direction = -1.0 if kind == NoteKind.HANDS else 1.0
            phase = age / max(life, 1e-6)
            x = cx + float(p["vx"]) * age
            y = hit_y + direction * float(p["vy"]) * age
            fade = (1.0 - phase) ** 1.25
            color = _blend(BG, p["color"], fade)
            length = float(p["length"]) * (0.55 + 0.45 * fade)
            pygame.draw.line(
                self.screen,
                color,
                (int(x), int(y - direction * length * 0.5)),
                (int(x), int(y + direction * length * 0.5)),
                max(1, int(p["size"])),
            )
            outward_alive.append(p)
        self._outbound_particles = outward_alive

        # A miss feels like the incoming object made it through the defenses:
        # briefly wash the margin *outside* that receptor red. No particles or
        # reward-like explosion are added.
        miss_alive: list[dict[str, object]] = []
        w, h = self.size
        for impact in self._miss_impacts:
            age = song_time - float(impact["born"])
            life = float(impact["life"])
            if age < 0.0 or age > life:
                continue
            kind = impact["kind"]
            lane = int(impact["lane"])
            phase = age / max(life, 1e-6)
            pulse = math.sin(math.pi * min(1.0, phase)) * (1.0 - 0.32 * phase)
            left, right = self._lane_bounds(kind, lane, 1.0)
            pad = max(8.0, (right - left) * 0.15)
            if kind == NoteKind.HANDS:
                points = [(left - pad, 0), (right + pad, 0), (right, self._field_y(kind, 1.0)), (left, self._field_y(kind, 1.0))]
            else:
                points = [(left, self._field_y(kind, 1.0)), (right, self._field_y(kind, 1.0)), (right + pad, h), (left - pad, h)]
            glow = _blend(BG, RED, 0.18 + 0.42 * pulse)
            pygame.draw.polygon(self.screen, glow, points, 0)
            edge_y = 2 if kind == NoteKind.HANDS else h - 3
            pygame.draw.line(
                self.screen,
                _blend(BG, RED, 0.48 + 0.42 * pulse),
                (int(max(0, left - pad)), edge_y),
                (int(min(w, right + pad)), edge_y),
                max(2, int(5 * pulse)),
            )
            miss_alive.append(impact)
        self._miss_impacts = miss_alive

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

    def _draw_receptors(
        self,
        body: BodyState,
        notes: list[GameNote],
        song_time: float,
        hand_enabled: bool,
        foot_enabled: bool,
        strike_events: tuple[MotionEvent, ...],
    ) -> None:
        for kind, occupied, color, enabled in (
            (NoteKind.HANDS, body.hand_lanes, MAGENTA, hand_enabled),
            (NoteKind.FOOT, body.foot_lanes, CYAN, foot_enabled),
        ):
            if not enabled:
                occupied = frozenset()
            y = self._field_y(kind, 1.0)
            left, right = self._field_bounds(kind, 1.0)
            line_color = _blend(WHITE, BG, 0.30) if enabled else _blend(DIM, BG, 0.55)
            pygame.draw.line(self.screen, line_color, (left, y), (right, y), 1)

            label_text = "HANDS" if kind == NoteKind.HANDS else "FEET"
            label_y = y - 34 if kind == NoteKind.HANDS else y + 25
            label = self.small_font.render(label_text, True, color if enabled else DIM)
            self.screen.blit(label, (left - label.get_width() - 12, label_y - label.get_height() // 2))

            for lane in range(1, 5):
                l, r = self._lane_bounds(kind, lane, 1.0)
                pad = max(5, int((r - l) * 0.08))
                gate_l = l + pad
                gate_r = r - pad
                center_x = (gate_l + gate_r) / 2.0
                is_occupied = enabled and lane in occupied
                near = enabled and self._target_is_near(notes, song_time, kind, lane)
                judgement, age = self._judgement_for_lane(notes, song_time, kind, lane) if enabled else (None, 999.0)
                strike_age: float | None = None
                strike_strength = 0.0
                if enabled and strike_events:
                    matching = [
                        e
                        for e in strike_events
                        if e.kind == kind and e.lane == lane and 0.0 <= song_time - e.song_time <= MOTION_EVENT_VISUAL_SECONDS + 0.04
                    ]
                    if matching:
                        latest = max(matching, key=lambda e: e.song_time)
                        strike_age = song_time - latest.song_time
                        strike_strength = max(1.0, min(2.2, float(latest.strength)))

                # Receptors are deliberately *not* bars. They are open bracket
                # gates, while incoming notes remain solid horizontal bars.
                # A detected lane-entry/strike temporarily drives the receptor
                # toward white-hot luminosity, then it decays smoothly back to
                # the ordinary occupancy state. This is the player's direct
                # input acknowledgement; actual note hits retain the much larger
                # shatter/back-pulse effect below.
                idle_color = DIM if enabled else _blend(DIM, BG, 0.58)
                base_gate_color = color if is_occupied else idle_color
                input_flash = 0.0
                if strike_age is not None:
                    life = min(1.0, strike_age / MOTION_EVENT_VISUAL_SECONDS)
                    # Fast initial flare, followed by a visible recovery tail.
                    input_flash = (1.0 - life) ** 1.45
                    input_flash *= min(1.0, 0.82 + 0.08 * strike_strength)

                gate_color = _blend(base_gate_color, WHITE, 0.90 * input_flash)
                gate_width = max(1, (4 if is_occupied else 1) + int(round(2.0 * input_flash)))
                tick = 9 + int(round(5.0 * input_flash))
                arm = max(10, int((gate_r - gate_l) * (0.15 + 0.035 * input_flash)))

                # A dim outer halo makes the flare readable even against a
                # filled/occupied lane without introducing another travelling
                # effect that can be mistaken for a note hit.
                if input_flash > 0.02:
                    halo_color = _blend(BG, _blend(color, WHITE, 0.62), 0.30 + 0.52 * input_flash)
                    halo_pad = 4 + int(5 * input_flash)
                    halo_tick = tick + 4 + int(4 * input_flash)
                    pygame.draw.line(
                        self.screen, halo_color,
                        (gate_l - halo_pad, y - halo_tick), (gate_l - halo_pad, y + halo_tick), 2,
                    )
                    pygame.draw.line(
                        self.screen, halo_color,
                        (gate_r + halo_pad, y - halo_tick), (gate_r + halo_pad, y + halo_tick), 2,
                    )

                pygame.draw.line(self.screen, gate_color, (gate_l, y - tick), (gate_l, y + tick), gate_width)
                pygame.draw.line(self.screen, gate_color, (gate_l, y), (gate_l + arm, y), gate_width)
                pygame.draw.line(self.screen, gate_color, (gate_r, y - tick), (gate_r, y + tick), gate_width)
                pygame.draw.line(self.screen, gate_color, (gate_r - arm, y), (gate_r, y), gate_width)

                # Occupancy gets a small diamond at the gate center; an input
                # impulse turns it into a bright, larger core and the same core
                # fades during the detector recovery period.
                base_diamond = color if is_occupied else idle_color
                diamond_color = _blend(base_diamond, WHITE, 0.96 * input_flash)
                radius = (6 if is_occupied else 3) + int(round(5.0 * input_flash))
                pygame.draw.polygon(
                    self.screen,
                    diamond_color,
                    [(center_x, y - radius), (center_x + radius, y), (center_x, y + radius), (center_x - radius, y)],
                    0 if (is_occupied or input_flash > 0.02) else 1,
                )

                if input_flash > 0.08:
                    core_r = max(2, int(3 + 4 * input_flash))
                    pygame.draw.circle(self.screen, WHITE, (int(center_x), int(y)), core_r)

                if near:
                    outer_tick = 14
                    near_color = _blend(WHITE, color, 0.25)
                    pygame.draw.line(self.screen, near_color, (gate_l - 4, y - outer_tick), (gate_l - 4, y + outer_tick), 1)
                    pygame.draw.line(self.screen, near_color, (gate_r + 4, y - outer_tick), (gate_r + 4, y + outer_tick), 1)

                if judgement is not None:
                    phase = 1.0 - min(age / HIT_FLASH_SECONDS, 1.0)
                    is_hit = judgement != "miss"
                    if judgement == "perfect":
                        jcolor = _blend(AMBER, WHITE, 0.35)
                        pulse_power = 1.65
                    elif judgement == "great":
                        jcolor = _blend(color, WHITE, 0.55)
                        pulse_power = 1.30
                    elif judgement == "hit":
                        jcolor = GREEN
                        pulse_power = 1.0
                    else:
                        jcolor = RED
                        pulse_power = 0.0

                    if is_hit:
                        # Timing quality directly changes the force of the visual
                        # impact: stronger packet, thicker lane streak and wider
                        # receptor shock ring for GREAT/PERFECT.
                        travel = min(1.0, age / HIT_FLASH_SECONDS)
                        head_p = max(0.03, 1.0 - travel * 0.97)
                        tail_p = min(1.0, head_p + 0.22 + 0.06 * pulse_power)
                        pulse_color = _blend(color, WHITE, min(0.96, 0.64 + 0.16 * pulse_power))
                        trail_color = _blend(BG, color, min(0.75, 0.34 * pulse_power * phase))
                        for boundary in (lane - 1, lane):
                            frac = boundary / 4.0
                            hl, hr = self._field_bounds(kind, head_p)
                            tl, tr = self._field_bounds(kind, tail_p)
                            el, er = self._field_bounds(kind, 1.0)
                            x_head = hl + (hr - hl) * frac
                            x_tail = tl + (tr - tl) * frac
                            x_end = el + (er - el) * frac
                            y_head = self._field_y(kind, head_p)
                            y_tail = self._field_y(kind, tail_p)
                            y_end = self._field_y(kind, 1.0)
                            pygame.draw.line(self.screen, trail_color, (x_head, y_head), (x_end, y_end), max(2, int(2 * pulse_power)))
                            pygame.draw.line(self.screen, pulse_color, (x_head, y_head), (x_tail, y_tail), max(6, int(6 * pulse_power)))
                            pygame.draw.line(self.screen, WHITE, (x_head, y_head), (x_tail, y_tail), max(2, int(2 * pulse_power)))

                        center_frac = (lane - 0.5) / 4.0
                        hl, hr = self._field_bounds(kind, head_p)
                        tl, tr = self._field_bounds(kind, tail_p)
                        cx_head = hl + (hr - hl) * center_frac
                        cx_tail = tl + (tr - tl) * center_frac
                        pygame.draw.line(
                            self.screen,
                            _blend(color, WHITE, min(0.92, 0.48 + 0.22 * pulse_power)),
                            (cx_head, self._field_y(kind, head_p)),
                            (cx_tail, self._field_y(kind, tail_p)),
                            max(3, int(3 * pulse_power)),
                        )

                        ring_r = int(12 + (22 + 8 * pulse_power) * (1.0 - phase))
                        pygame.draw.circle(self.screen, jcolor, (int(center_x), int(y)), ring_r, max(2, int(4 * phase * pulse_power)))
                        pygame.draw.circle(self.screen, WHITE, (int(center_x), int(y)), max(3, int(6 * phase * pulse_power)), 1)
                    else:
                        cross = int(7 + 7 * (1.0 - phase))
                        pygame.draw.line(self.screen, jcolor, (center_x - cross, y - cross), (center_x + cross, y + cross), 3)
                        pygame.draw.line(self.screen, jcolor, (center_x - cross, y + cross), (center_x + cross, y - cross), 3)

                    word = judgement.upper()
                    surf = self.hit_font.render(word, True, jcolor)
                    text_y = y - 31 if kind == NoteKind.HANDS else y + 31
                    self.screen.blit(surf, surf.get_rect(center=(center_x, text_y)))

                lane_label = self.small_font.render(
                    str(lane),
                    True,
                    WHITE if is_occupied else (DIM if enabled else _blend(DIM, BG, 0.55)),
                )
                number_y = y + 24 if kind == NoteKind.HANDS else y - 24
                self.screen.blit(lane_label, lane_label.get_rect(center=(center_x, number_y)))

            if not enabled:
                off = self.small_font.render(
                    "NO HAND NOTES" if kind == NoteKind.HANDS else "NO FOOT NOTES",
                    True,
                    _blend(DIM, BG, 0.30),
                )
                offset = 48 if kind == NoteKind.HANDS else -48
                self.screen.blit(off, off.get_rect(center=((left + right) / 2, y + offset)))

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

    def _draw_body_markers(
        self,
        body: BodyState,
        show_labels: bool = False,
        hand_enabled: bool = True,
        foot_enabled: bool = True,
        show_lower_body_sources: bool = False,
    ) -> None:
        points = []
        if hand_enabled:
            points.extend([(body.left_wrist, MAGENTA), (body.right_wrist, MAGENTA)])
        if foot_enabled:
            left_control = body.left_foot_control if body.left_foot_control.visible else body.left_knee
            right_control = body.right_foot_control if body.right_foot_control.visible else body.right_knee
            points.extend([(left_control, CYAN), (right_control, CYAN)])

            if show_lower_body_sources:
                source_color = _blend(BG, CYAN, 0.42)
                for knee, ankle, control in (
                    (body.left_knee, body.left_ankle, left_control),
                    (body.right_knee, body.right_ankle, right_control),
                ):
                    if knee.visible and ankle.visible:
                        pygame.draw.line(
                            self.screen,
                            _blend(BG, CYAN, 0.25),
                            self._screen_point(knee),
                            self._screen_point(ankle),
                            1,
                        )
                    for source in (knee, ankle):
                        if source.visible:
                            pos = self._screen_point(source)
                            pygame.draw.circle(self.screen, BG, pos, 5)
                            pygame.draw.circle(self.screen, source_color, pos, 4, 1)
                    if control.visible:
                        pos = self._screen_point(control)
                        pygame.draw.circle(self.screen, WHITE, pos, 11, 1)

        for p, color in points:
            if not p.visible:
                continue
            pos = self._screen_point(p)
            pygame.draw.circle(self.screen, BG, pos, 9)
            pygame.draw.circle(self.screen, color, pos, 7, 2)
            if show_labels and p.lane is not None:
                label = self.small_font.render(str(p.lane), True, WHITE)
                self.screen.blit(label, label.get_rect(center=pos))

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
        chain_label = self.small_font.render(f"A/C  CHAINS: {chain_mode.label}", True, DIM)
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
        # A restrained music-synced size pulse gives the combo counter life
        # without reintroducing a screen-wide brightness strobe.
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
            # Tiny vector embers: enough to read as "on fire" while retaining
            # the game's abstract vector aesthetic.
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
        good = status == "READY" or input_name == "keyboard"
        color = GREEN if good else WHITE
        text = "READY" if input_name == "keyboard" else status
        lines = [(text, color, self.font), (song_title, WHITE, self.small_font), (chart_label, DIM, self.small_font)]
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
