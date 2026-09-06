from __future__ import annotations

import pygame

from .character_renderer import Renderer as CharacterRenderer
from .renderer import AMBER, BG, CYAN, DIM, GREEN, RED, WHITE


CALIBRATION_OVERLAY_ALPHA = 72


class Renderer(CharacterRenderer):
    """Character renderer with calibration-only translucent diagnostic overlays."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._overlay_alpha_override: int | None = None

    def draw(self, *args, **kwargs) -> None:
        overlay_alpha = kwargs.pop("overlay_alpha", None)
        previous = self._overlay_alpha_override
        self._overlay_alpha_override = (
            None
            if overlay_alpha is None
            else max(0, min(255, int(overlay_alpha)))
        )
        try:
            super().draw(*args, **kwargs)
        finally:
            self._overlay_alpha_override = previous

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
        player_visual: str = "silhouette",
        *,
        pose_model_mode: str = "speed",
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

        line2 = self.small_font.render(
            f"←/→ reach    ↑/↓ camera    M tracking model    V visual ({player_visual.upper()})    Esc save & return",
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
