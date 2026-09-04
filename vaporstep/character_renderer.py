from __future__ import annotations

import math
import time

import pygame

from .domain import BodyState, PoseFigure
from .framing import FramingMonitor, FramingWarnings
from .renderer import (
    BG,
    CYAN,
    MAGENTA,
    PURPLE,
    RED,
    WHITE,
    Renderer as GameplayRenderer,
    _blend,
)


CHARACTER_CYAN = _blend(BG, CYAN, 0.52)
CHARACTER_MAGENTA = _blend(BG, MAGENTA, 0.52)
CHARACTER_CYAN_EDGE = _blend(BG, CYAN, 0.64)
CHARACTER_MAGENTA_EDGE = _blend(BG, MAGENTA, 0.64)
CHARACTER_WHITE = _blend(BG, WHITE, 0.55)


class Renderer(GameplayRenderer):
    """Gameplay renderer with an optional cheap pose-driven character skin."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._character_last_head: tuple[float, float] | None = None
        self._character_last_time: float | None = None
        self._character_hair_sway = 0.0
        self._character_hair_velocity = 0.0
        self._framing_monitor = FramingMonitor()
        self._framing_running = False

    def reset_game_effects(self) -> None:
        super().reset_game_effects()
        self._character_last_head = None
        self._character_last_time = None
        self._character_hair_sway = 0.0
        self._character_hair_velocity = 0.0
        self._framing_monitor.reset()
        self._framing_running = False

    def draw(self, body: BodyState, *args, **kwargs) -> None:
        running = bool(kwargs.get("running", False))
        framing_active = running and kwargs.get("stats") is not None
        hands_enabled = bool(kwargs.get("hand_enabled", True))
        feet_enabled = bool(kwargs.get("foot_enabled", True))
        show_body_markers = bool(kwargs.get("show_body_markers", True))
        performance_state = str(kwargs.get("performance_state", "ok"))

        if framing_active and not self._framing_running:
            self._framing_monitor.start(
                body,
                hands_enabled=hands_enabled,
                feet_enabled=feet_enabled,
            )

        warnings = FramingWarnings()
        if framing_active and show_body_markers and performance_state != "failed":
            warnings = self._framing_monitor.update(
                body,
                now=time.monotonic(),
                hands_enabled=hands_enabled,
                feet_enabled=feet_enabled,
            )

        super().draw(body, *args, **kwargs)
        self._draw_framing_warning(warnings)
        self._framing_running = framing_active

    def _draw_framing_warning(self, warnings: FramingWarnings) -> None:
        if not warnings.top and not warnings.bottom:
            return
        w, h = self.size
        glow = (1.0, 0.68, 0.42, 0.24, 0.12)
        if warnings.top:
            for offset, strength in enumerate(glow):
                pygame.draw.line(
                    self.screen,
                    _blend(BG, RED, strength),
                    (0, offset),
                    (w - 1, offset),
                )
        if warnings.bottom:
            for offset, strength in enumerate(glow):
                y = h - 1 - offset
                pygame.draw.line(
                    self.screen,
                    _blend(BG, RED, strength),
                    (0, y),
                    (w - 1, y),
                )

    def _draw_pose_figure(self, figure: PoseFigure) -> None:
        self._draw_character_figure(figure)

    @staticmethod
    def _normal(p0: tuple[float, float], p1: tuple[float, float]) -> tuple[float, float]:
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length = max(1.0, math.hypot(dx, dy))
        return -dy / length, dx / length

    def _draw_tapered_segment(
        self,
        p0: tuple[int, int],
        p1: tuple[int, int],
        width0: float,
        width1: float,
        *,
        fill,
        outline,
        accent=None,
    ) -> None:
        nx, ny = self._normal(p0, p1)
        h0 = width0 * 0.5
        h1 = width1 * 0.5
        polygon = [
            (int(p0[0] + nx * h0), int(p0[1] + ny * h0)),
            (int(p1[0] + nx * h1), int(p1[1] + ny * h1)),
            (int(p1[0] - nx * h1), int(p1[1] - ny * h1)),
            (int(p0[0] - nx * h0), int(p0[1] - ny * h0)),
        ]
        pygame.draw.polygon(self.screen, fill, polygon)
        pygame.draw.lines(self.screen, outline, True, polygon, 2)
        if accent is not None:
            a0 = (int(p0[0] + nx * h0 * 0.72), int(p0[1] + ny * h0 * 0.72))
            a1 = (int(p1[0] + nx * h1 * 0.72), int(p1[1] + ny * h1 * 0.72))
            pygame.draw.line(self.screen, accent, a0, a1, 2)

    def _visible_screen_point(self, figure: PoseFigure, index: int) -> tuple[int, int] | None:
        point = figure.point(index)
        return self._screen_point(point) if point.visible else None

    def _head_geometry(self, figure: PoseFigure) -> tuple[tuple[int, int], int] | None:
        viewport = self._camera_rect()
        left_ear = self._visible_screen_point(figure, 7)
        right_ear = self._visible_screen_point(figure, 8)
        nose = self._visible_screen_point(figure, 0)
        left_shoulder = self._visible_screen_point(figure, 11)
        right_shoulder = self._visible_screen_point(figure, 12)

        if left_ear is not None and right_ear is not None:
            center = ((left_ear[0] + right_ear[0]) // 2, (left_ear[1] + right_ear[1]) // 2)
            radius = max(12, int(round(math.dist(left_ear, right_ear) * 0.70)))
            return center, radius
        if nose is not None:
            return nose, max(14, int(round(viewport.width * 0.030)))
        if left_shoulder is not None and right_shoulder is not None:
            shoulder_width = math.dist(left_shoulder, right_shoulder)
            center = (
                int((left_shoulder[0] + right_shoulder[0]) * 0.5),
                int((left_shoulder[1] + right_shoulder[1]) * 0.5 - shoulder_width * 0.78),
            )
            return center, max(14, int(shoulder_width * 0.32))
        return None

    def _update_hair_sway(self, center: tuple[int, int], radius: int) -> float:
        now = pygame.time.get_ticks() / 1000.0
        if self._character_last_time is None or self._character_last_head is None:
            self._character_last_time = now
            self._character_last_head = center
            return self._character_hair_sway

        dt = max(1.0 / 240.0, min(0.08, now - self._character_last_time))
        vx = (center[0] - self._character_last_head[0]) / dt
        target = max(-radius * 0.65, min(radius * 0.65, -vx * 0.018))
        spring = 42.0
        damping = 0.76 ** (dt * 60.0)
        self._character_hair_velocity += (target - self._character_hair_sway) * spring * dt
        self._character_hair_velocity *= damping
        self._character_hair_sway += self._character_hair_velocity * dt
        self._character_hair_sway = max(-radius * 0.78, min(radius * 0.78, self._character_hair_sway))
        self._character_last_time = now
        self._character_last_head = center
        return self._character_hair_sway

    def _draw_head_and_hair(self, figure: PoseFigure) -> None:
        geometry = self._head_geometry(figure)
        if geometry is None:
            return
        center, radius = geometry
        sway = self._update_hair_sway(center, radius)
        face_fill = _blend(BG, PURPLE, 0.10)
        face_outline = _blend(BG, _blend(PURPLE, CYAN, 0.42), 0.72)

        pygame.draw.circle(self.screen, face_fill, center, radius)
        pygame.draw.circle(self.screen, face_outline, center, radius, 2)

        cx, cy = center
        hair = [
            (cx - int(radius * 0.92), cy - int(radius * 0.30)),
            (cx - int(radius * 1.08) + int(sway * 0.20), cy - int(radius * 0.90)),
            (cx - int(radius * 0.48) + int(sway * 0.14), cy - int(radius * 0.74)),
            (cx - int(radius * 0.18) + int(sway * 0.10), cy - int(radius * 1.23)),
            (cx + int(radius * 0.08) + int(sway * 0.08), cy - int(radius * 0.82)),
            (cx + int(radius * 0.62) + int(sway * 0.18), cy - int(radius * 1.08)),
            (cx + int(radius * 0.98) + int(sway * 0.34), cy - int(radius * 0.48)),
            (cx + int(radius * 0.78) + int(sway * 0.52), cy + int(radius * 0.12)),
            (cx + int(radius * 0.36) + int(sway * 0.42), cy - int(radius * 0.10)),
            (cx + int(radius * 0.02), cy + int(radius * 0.10)),
            (cx - int(radius * 0.48), cy + int(radius * 0.02)),
        ]
        pygame.draw.polygon(self.screen, _blend(BG, PURPLE, 0.17), hair)
        pygame.draw.lines(self.screen, CHARACTER_MAGENTA_EDGE, False, hair[:8], 2)
        pygame.draw.lines(self.screen, CHARACTER_CYAN_EDGE, False, hair[7:] + hair[:2], 2)

        eye_y = cy + int(radius * 0.10)
        eye_dx = int(radius * 0.34)
        eye_h = max(4, int(radius * 0.28))
        for ex in (cx - eye_dx, cx + eye_dx):
            pygame.draw.line(
                self.screen,
                _blend(CHARACTER_CYAN_EDGE, CHARACTER_WHITE, 0.14),
                (ex, eye_y - eye_h // 2),
                (ex, eye_y + eye_h // 2),
                max(2, radius // 8),
            )

    def _draw_torso(self, figure: PoseFigure, scale: float) -> None:
        points = [self._visible_screen_point(figure, index) for index in (11, 12, 24, 23)]
        if any(point is None for point in points):
            return
        ls, rs, rh, lh = points
        shoulder_width = max(1.0, math.dist(ls, rs))
        shoulder_dx = (rs[0] - ls[0]) / shoulder_width
        shoulder_dy = (rs[1] - ls[1]) / shoulder_width
        shoulder_inset = max(scale * 0.006, shoulder_width * 0.08)
        hip_pad = scale * 0.007
        polygon = [
            (
                int(ls[0] + shoulder_dx * shoulder_inset),
                int(ls[1] + shoulder_dy * shoulder_inset),
            ),
            (
                int(rs[0] - shoulder_dx * shoulder_inset),
                int(rs[1] - shoulder_dy * shoulder_inset),
            ),
            (int(rh[0] + hip_pad), int(rh[1] + scale * 0.010)),
            (int(lh[0] - hip_pad), int(lh[1] + scale * 0.010)),
        ]
        jacket = _blend(BG, PURPLE, 0.18)
        pygame.draw.polygon(self.screen, jacket, polygon)
        pygame.draw.lines(
            self.screen,
            _blend(BG, _blend(PURPLE, MAGENTA, 0.48), 0.72),
            True,
            polygon,
            3,
        )
        pygame.draw.line(self.screen, CHARACTER_CYAN, polygon[0], polygon[3], 2)

        # A narrow brighter side face gives the torso the same faux depth as
        # the tapered limbs without adding image transforms or cached surfaces.
        side_top = (
            int(polygon[1][0] * 0.86 + polygon[0][0] * 0.14),
            int(polygon[1][1] * 0.86 + polygon[0][1] * 0.14),
        )
        side_bottom = (
            int(polygon[2][0] * 0.88 + polygon[3][0] * 0.12),
            int(polygon[2][1] * 0.88 + polygon[3][1] * 0.12),
        )
        side_face = [polygon[1], polygon[2], side_bottom, side_top]
        pygame.draw.polygon(self.screen, _blend(BG, PURPLE, 0.29), side_face)
        pygame.draw.line(
            self.screen,
            _blend(CHARACTER_MAGENTA_EDGE, CHARACTER_WHITE, 0.14),
            side_top,
            side_bottom,
            2,
        )
        pygame.draw.line(self.screen, CHARACTER_MAGENTA, polygon[1], polygon[2], 2)

        shoulder_mid = ((ls[0] + rs[0]) // 2, (ls[1] + rs[1]) // 2)
        hood_radius = max(8, int(math.dist(ls, rs) * 0.28))
        pygame.draw.arc(
            self.screen,
            _blend(CHARACTER_CYAN, _blend(BG, PURPLE, 0.66), 0.45),
            pygame.Rect(
                shoulder_mid[0] - hood_radius,
                shoulder_mid[1] - hood_radius // 2,
                hood_radius * 2,
                hood_radius,
            ),
            math.pi,
            math.tau,
            3,
        )

    def _draw_hand(self, point: tuple[int, int] | None, radius: int, color, *, right: bool) -> None:
        if point is None:
            return
        fill = _blend(BG, PURPLE, 0.14)
        pygame.draw.circle(self.screen, fill, point, radius)
        pygame.draw.circle(self.screen, color, point, radius, 2)
        thumb = (point[0] + (radius // 2 if right else -radius // 2), point[1] + radius // 3)
        pygame.draw.circle(self.screen, fill, thumb, max(2, radius // 2))
        pygame.draw.circle(self.screen, color, thumb, max(2, radius // 2), 1)

    def _draw_shoe(
        self,
        ankle: tuple[int, int] | None,
        toe: tuple[int, int] | None,
        scale: float,
        color,
        *,
        right: bool,
    ) -> None:
        if ankle is None:
            return
        if toe is None:
            direction = 1 if right else -1
            toe = (ankle[0] + int(scale * 0.018) * direction, ankle[1] + int(scale * 0.008))
        dx = toe[0] - ankle[0]
        dy = toe[1] - ankle[1]
        raw_length = max(1.0, math.hypot(dx, dy))
        length = max(scale * 0.030, raw_length)
        ux, uy = dx / raw_length, dy / raw_length
        nx, ny = -uy, ux
        width = scale * 0.018
        heel = (ankle[0] - ux * length * 0.22, ankle[1] - uy * length * 0.22)
        tip = (ankle[0] + ux * length * 0.92, ankle[1] + uy * length * 0.92)
        polygon = [
            (int(heel[0] + nx * width), int(heel[1] + ny * width)),
            (int(tip[0] + nx * width * 0.70), int(tip[1] + ny * width * 0.70)),
            (int(tip[0] - nx * width * 0.75), int(tip[1] - ny * width * 0.75)),
            (int(heel[0] - nx * width * 0.65), int(heel[1] - ny * width * 0.65)),
        ]
        pygame.draw.polygon(self.screen, _blend(BG, PURPLE, 0.16), polygon)
        pygame.draw.lines(self.screen, color, True, polygon, 2)
        pygame.draw.line(
            self.screen,
            _blend(color, CHARACTER_WHITE, 0.16),
            polygon[2],
            polygon[3],
            2,
        )

    def _draw_character_figure(self, figure: PoseFigure) -> None:
        viewport = self._camera_rect()
        scale = float(viewport.width)
        body_fill = _blend(BG, PURPLE, 0.14)

        for hip_i, knee_i, ankle_i, outline, accent in (
            (23, 25, 27, CHARACTER_CYAN, CHARACTER_CYAN_EDGE),
            (24, 26, 28, CHARACTER_MAGENTA, CHARACTER_MAGENTA_EDGE),
        ):
            hip = self._visible_screen_point(figure, hip_i)
            knee = self._visible_screen_point(figure, knee_i)
            ankle = self._visible_screen_point(figure, ankle_i)
            if hip is not None and knee is not None:
                self._draw_tapered_segment(
                    hip, knee, scale * 0.037, scale * 0.031,
                    fill=body_fill, outline=outline, accent=accent,
                )
            if knee is not None and ankle is not None:
                self._draw_tapered_segment(
                    knee, ankle, scale * 0.031, scale * 0.024,
                    fill=body_fill, outline=outline, accent=accent,
                )

        self._draw_torso(figure, scale)

        for shoulder_i, elbow_i, wrist_i, outline, accent in (
            (11, 13, 15, CHARACTER_CYAN, CHARACTER_CYAN_EDGE),
            (12, 14, 16, CHARACTER_MAGENTA, CHARACTER_MAGENTA_EDGE),
        ):
            shoulder = self._visible_screen_point(figure, shoulder_i)
            elbow = self._visible_screen_point(figure, elbow_i)
            wrist = self._visible_screen_point(figure, wrist_i)
            if shoulder is not None and elbow is not None:
                self._draw_tapered_segment(
                    shoulder, elbow, scale * 0.030, scale * 0.025,
                    fill=body_fill, outline=outline, accent=accent,
                )
            if elbow is not None and wrist is not None:
                self._draw_tapered_segment(
                    elbow, wrist, scale * 0.025, scale * 0.020,
                    fill=body_fill, outline=outline, accent=accent,
                )

        self._draw_head_and_hair(figure)

        hand_radius = max(5, int(scale * 0.014))
        self._draw_hand(
            self._visible_screen_point(figure, 15), hand_radius, CHARACTER_CYAN_EDGE, right=False
        )
        self._draw_hand(
            self._visible_screen_point(figure, 16), hand_radius, CHARACTER_MAGENTA_EDGE, right=True
        )
        self._draw_shoe(
            self._visible_screen_point(figure, 27), self._visible_screen_point(figure, 31),
            scale, CHARACTER_CYAN_EDGE, right=False,
        )
        self._draw_shoe(
            self._visible_screen_point(figure, 28), self._visible_screen_point(figure, 32),
            scale, CHARACTER_MAGENTA_EDGE, right=True,
        )
