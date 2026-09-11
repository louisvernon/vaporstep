from __future__ import annotations

import time

import pygame

from .svg_character_orientation import Renderer as CharacterRenderer, active_character_filename
from .debug_state import set_debug_enabled
from .pose_presentation import PosePresentationExtrapolator
from .renderer import AMBER, BG, CYAN, DIM, GREEN, RED, WHITE


CALIBRATION_OVERLAY_ALPHA = 72


class Renderer(CharacterRenderer):
    """Character renderer with presentation extrapolation and calibration overlays."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._overlay_alpha_override: int | None = None
        self._pose_presentation = PosePresentationExtrapolator()
        self._defer_character_visual = False
        self._deferred_pose_figure = None
        self._deferred_character_ms = 0.0

    def reset_game_effects(self) -> None:
        super().reset_game_effects()
        self._pose_presentation.reset()

    def draw(self, *args, **kwargs) -> None:
        # Either visible F3 level arrives here as debug=True. Publish it once so
        # runtime diagnostics can follow F3 without threading another flag
        # through gameplay and scoring APIs.
        set_debug_enabled(bool(kwargs.get("debug", False)))
        overlay_alpha = kwargs.pop("overlay_alpha", None)
        previous = self._overlay_alpha_override
        self._overlay_alpha_override = (
            None
            if overlay_alpha is None
            else max(0, min(255, int(overlay_alpha)))
        )

        body = kwargs.get("body")
        if body is None and args:
            body = args[0]
        pose_figure = kwargs.get("pose_figure")
        now = time.monotonic()
        if (
            pose_figure is not None
            and body is not None
            and body.timestamp_is_capture
            and body.timestamp > 0.0
        ):
            self._pose_presentation.observe(
                pose_figure,
                captured_at=body.timestamp,
                observed_at=now,
            )
            kwargs["pose_figure"] = self._pose_presentation.figure_at(now)
        else:
            # Silhouette/keyboard modes should retain today's exact presentation
            # and must not resurrect stale character state when toggled back on.
            self._pose_presentation.reset()

        # Character mode is intentionally the final gameplay scene layer. The
        # character is drawn directly (no extra alpha pass) after playfields,
        # notes, receptors, effects, HUD and debug rendering have completed.
        # Silhouette mode keeps its existing render order and native alpha.
        previous_phase_averages = (
            dict(self._phase_averages_ms) if self._profiling_enabled else None
        )
        self._defer_character_visual = True
        self._deferred_pose_figure = None
        self._deferred_character_ms = 0.0
        try:
            super().draw(*args, **kwargs)
            figure = self._deferred_pose_figure
            if figure is not None:
                self._defer_character_visual = False
                started = time.perf_counter()
                self._render_deferred_character(figure)
                self._deferred_character_ms = (time.perf_counter() - started) * 1000.0
            if previous_phase_averages is not None:
                self._correct_deferred_character_profile(previous_phase_averages)
        finally:
            self._defer_character_visual = False
            self._deferred_pose_figure = None
            self._overlay_alpha_override = previous

    def _draw_pose_figure(self, figure) -> None:
        if self._defer_character_visual:
            self._deferred_pose_figure = figure
            return
        super()._draw_pose_figure(figure)

    def _render_deferred_character(self, figure) -> None:
        # Draw directly to the gameplay surface. Individual SVG opacity values
        # still affect imported colors, but there is no whole-character alpha
        # compositing pass here.
        super()._draw_pose_figure(figure)

    def _correct_deferred_character_profile(
        self,
        previous_phase_averages: dict[str, float],
    ) -> None:
        """Keep F3 character cost attributed to the existing player phase."""
        elapsed = self._deferred_character_ms
        if elapsed <= 0.0:
            return

        phase_times = dict(self._phase_times_ms)
        phase_times["silhouette"] = phase_times.get("silhouette", 0.0) + elapsed
        phase_times["total"] = phase_times.get("total", 0.0) + elapsed
        self._phase_times_ms = phase_times

        for name, value in phase_times.items():
            previous_average = previous_phase_averages.get(name)
            self._phase_averages_ms[name] = (
                value
                if previous_average is None
                else 0.9 * previous_average + 0.1 * value
            )

    def _draw_status(self, status, input_name, song_title, chart_label, audio_error) -> None:
        if self._overlay_alpha_override is None:
            super()._draw_status(status, input_name, song_title, chart_label, audio_error)
            return

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
            bg.fill((0, 0, 0, self._overlay_alpha_override))
            self.screen.blit(bg, (x - 6, y - 3))
            self.screen.blit(surf, (x, y))
            y += surf.get_height() + 8

    def _draw_debug_lines(self, lines: list[str]) -> None:
        if self._overlay_alpha_override is None:
            super()._draw_debug_lines(lines)
            return

        x, y = 18, 92
        for line in lines:
            surf = self.small_font.render(line, True, WHITE)
            bg = pygame.Surface((surf.get_width() + 12, surf.get_height() + 4), pygame.SRCALPHA)
            bg.fill((0, 0, 0, self._overlay_alpha_override))
            self.screen.blit(bg, (x - 6, y - 2))
            self.screen.blit(surf, (x, y))
            y += 23

    def draw_calibration_overlay(
        self,
        camera_index: int | None,
        horizontal_reach: float,
        camera_status: str,
        player_visual: str = "character",
        *,
        pose_model_mode: str = "accuracy",
        inference_percent: int | None = None,
    ) -> None:
        w, h = self.size
        panel_width = min(820, w - 40)
        panel = pygame.Surface((panel_width, 128), pygame.SRCALPHA)
        panel.fill((*BG, CALIBRATION_OVERLAY_ALPHA))
        self.screen.blit(panel, (20, h - 148))

        camera_label = "OFF (KEYBOARD)" if camera_index is None else str(camera_index)
        mode = "ACCURACY" if str(pose_model_mode).casefold() == "accuracy" else "SPEED"
        model_name = "FULL" if mode == "ACCURACY" else "LITE"
        line1 = self.font.render(
            f"CAMERA  {camera_label}      REACH  {horizontal_reach:.2f}x      TRACKING  {mode} ({model_name})",
            True,
            WHITE,
        )
        self.screen.blit(line1, (38, h - 138))

        selected_filename = active_character_filename()
        if player_visual == "character" and selected_filename is not None:
            visual_label = selected_filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").upper()
        else:
            visual_label = player_visual.upper()
        line2 = self.small_font.render(
            f"←/→ reach    ↑/↓ camera    M tracking model    V visual ({visual_label})    Esc save & return",
            True,
            CYAN,
        )
        self.screen.blit(line2, (38, h - 108))

        low_inference = inference_percent is not None and inference_percent < 75
        if low_inference and mode == "ACCURACY":
            guidance = (
                f"INFERENCE {inference_percent}% — TRY SPEED (M) FOR LOWER CPU USE"
            )
            guidance_color = AMBER
        elif low_inference and player_visual == "silhouette":
            guidance = (
                f"INFERENCE {inference_percent}% — CHARACTER VISUAL (V) MAY FREE TRACKING HEADROOM"
            )
            guidance_color = AMBER
        else:
            guidance = "SPEED: lower CPU / faster    •    ACCURACY: stronger tracking / higher CPU"
            guidance_color = DIM
        tracking = self.small_font.render(guidance, True, guidance_color)
        self.screen.blit(tracking, (38, h - 82))

        sources = self.small_font.render(
            "Foot control: bright cyan ring   •   faint dots: knee / ankle",
            True,
            DIM,
        )
        self.screen.blit(sources, (38, h - 58))

        line3 = self.small_font.render(camera_status, True, DIM)
        self.screen.blit(line3, (38, h - 34))
