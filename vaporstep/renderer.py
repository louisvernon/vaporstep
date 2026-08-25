from __future__ import annotations

import math

import pygame

from . import renderer_tunnel_base as _tunnel
from .domain import BodyState, NoteKind
from .keyboard_input import label_for_lane


# Keep the renderer module's established public palette/constants available to
# callers while this file stays a thin visual specialization of the proven
# tunnel renderer.
BG = _tunnel.BG
CYAN = _tunnel.CYAN
MAGENTA = _tunnel.MAGENTA
PURPLE = _tunnel.PURPLE
WHITE = _tunnel.WHITE
DIM = _tunnel.DIM
GRID = _tunnel.GRID
GREEN = _tunnel.GREEN
RED = _tunnel.RED
AMBER = _tunnel.AMBER
ELECTRIC_YELLOW = _tunnel.ELECTRIC_YELLOW
HIT_BRICK_POP_SECONDS = _tunnel.HIT_BRICK_POP_SECONDS
_blend = _tunnel._blend


# The seam beside the feet stays exactly where the previous tunnel put it. The
# receptor then runs briefly outward on a flat shoulder before turning into the
# broad upper arch, making the tunnel fill the screen without overlapping feet.
_HAND_SHOULDER_EXTENSION = 0.12
_HAND_SHOULDER_PATH_FRACTION = 0.075
_HAND_TRACKER_OFFSET_PX = 10.0


class Renderer(_tunnel.Renderer):
    """Tunnel renderer with a wider shouldered shell and lightweight feedback."""

    def _hand_tunnel_geometry(self):
        inner, old_outer = super()._hand_arc_geometry()
        viewport = self._camera_rect()
        cx, base_y, rx, _ = old_outer

        seam_left = (cx - rx, base_y)
        seam_right = (cx + rx, base_y)
        extension = viewport.width * _HAND_SHOULDER_EXTENSION
        shoulder_left = (
            max(float(viewport.left + 10), seam_left[0] - extension),
            base_y,
        )
        shoulder_right = (
            min(float(viewport.right - 10), seam_right[0] + extension),
            base_y,
        )
        # Leave room for the optional tracker dot just outside the top receptor.
        outer_top = float(viewport.top) + max(26.0, viewport.height * 0.035)
        outer = (seam_left, seam_right, shoulder_left, shoulder_right, outer_top)
        return inner, outer

    @staticmethod
    def _outer_tunnel_point(outer, along: float) -> tuple[float, float]:
        seam_left, seam_right, shoulder_left, shoulder_right, outer_top = outer
        t = max(0.0, min(1.0, along))
        shelf = _HAND_SHOULDER_PATH_FRACTION

        if t <= shelf:
            u = t / max(shelf, 1e-6)
            return (
                seam_left[0] + (shoulder_left[0] - seam_left[0]) * u,
                seam_left[1] + (shoulder_left[1] - seam_left[1]) * u,
            )
        if t >= 1.0 - shelf:
            u = (t - (1.0 - shelf)) / max(shelf, 1e-6)
            return (
                shoulder_right[0] + (seam_right[0] - shoulder_right[0]) * u,
                shoulder_right[1] + (seam_right[1] - shoulder_right[1]) * u,
            )

        # The middle of the receptor is a broad upper half-ellipse joining the
        # two flat shoulders. This is intentionally exaggerated perspective.
        u = (t - shelf) / max(1.0 - 2.0 * shelf, 1e-6)
        arch_cx = (shoulder_left[0] + shoulder_right[0]) * 0.5
        arch_base_y = (shoulder_left[1] + shoulder_right[1]) * 0.5
        arch_rx = max(10.0, (shoulder_right[0] - shoulder_left[0]) * 0.5)
        arch_ry = max(20.0, arch_base_y - outer_top)
        angle = math.pi + math.pi * u
        return (
            arch_cx + arch_rx * math.cos(angle),
            arch_base_y + arch_ry * math.sin(angle),
        )

    def _hand_point(self, along: float, progress: float) -> tuple[float, float]:
        inner, outer = self._hand_tunnel_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        ix, iy = self._ellipse_upper_point(inner, along)
        ox, oy = self._outer_tunnel_point(outer, along)
        return ix + (ox - ix) * p, iy + (oy - iy) * p

    def _hand_depth_band(self, p0: float, p1: float) -> list[tuple[int, int]]:
        outer = self._hand_arc_points(0.0, 1.0, p1, samples=64)
        inner = self._hand_arc_points(1.0, 0.0, p0, samples=64)
        return [*outer, *inner]

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
    ) -> None:
        occupied = body.hand_lanes if enabled else frozenset()
        disabled = _blend(DIM, BG, 0.58)

        # A tiny amount of inner darkening makes the shell read as depth rather
        # than a flat overlay, while preserving the camera/silhouette underneath.
        depth_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        for band in range(8):
            p0 = band / 8.0
            p1 = (band + 1) / 8.0
            mid = (p0 + p1) * 0.5
            alpha = int(3 + 15 * (1.0 - mid))
            pygame.draw.polygon(
                depth_surface,
                (*BG, alpha),
                self._hand_depth_band(p0, p1),
            )
        self.screen.blit(depth_surface, (0, 0))

        fill_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        for lane in range(1, 5):
            if enabled:
                pygame.draw.polygon(
                    fill_surface,
                    (*MAGENTA, 58 if lane in occupied else 8),
                    self._hand_sector_polygon(lane),
                )
        self.screen.blit(fill_surface, (0, 0))

        rail_color = GRID if enabled else disabled
        boundaries = _tunnel._HAND_BOUNDARIES

        for boundary, along in enumerate(boundaries):
            p0 = self._hand_point(along, 0.0)
            p1 = self._hand_point(along, 1.0)
            active_boundary = enabled and (
                (boundary > 0 and boundary in occupied)
                or (boundary < 4 and boundary + 1 in occupied)
            )
            if active_boundary:
                color, width = MAGENTA, 3
            elif enabled and boundary in (0, 4):
                color, width = MAGENTA, 2
            else:
                color, width = rail_color, 1
            pygame.draw.line(self.screen, color, p0, p1, width)

        inner_arc = self._hand_arc_points(0.0, 1.0, 0.0, samples=64)
        pygame.draw.lines(
            self.screen,
            _blend(rail_color, WHITE, 0.10),
            False,
            inner_arc,
            2,
        )

        # Experimental beat ripple: one depth ring receives a brief, restrained
        # pink lift that moves from the inner opening toward the receptor over
        # the short beat-pulse lifetime. It is deliberately easy to remove.
        pulse = max(0.0, min(1.0, beat_pulse))
        pulse_position = 1.0 - math.sqrt(pulse) if pulse > 0.005 else -1.0
        for step in range(1, 9):
            progress = step / 9.0
            ring_color = rail_color
            width = 1
            if enabled and pulse_position >= 0.0:
                proximity = max(0.0, 1.0 - abs(progress - pulse_position) / 0.18)
                if proximity > 0.0:
                    amount = proximity * (0.18 + 0.30 * math.sqrt(pulse))
                    ring_color = _blend(rail_color, MAGENTA, amount)
                    width = 2 if amount > 0.18 else 1
            arc = self._hand_arc_points(0.0, 1.0, progress, samples=64)
            pygame.draw.lines(self.screen, ring_color, False, arc, width)

        for lane in range(1, 5):
            active = enabled and lane in occupied
            receptor = self._hand_lane_arc(lane, 1.0, 1.0)
            pygame.draw.lines(
                self.screen,
                MAGENTA if active else (DIM if enabled else disabled),
                False,
                receptor,
                6 if active else 2,
            )

            # Restore the keyboard mapping labels lost when the linear hand
            # receptors were replaced. Keep them just inside the receptor so an
            # arriving note naturally renders over the label rather than behind it.
            if enabled:
                lx, ly = self._hand_target_point(lane, 0.955)
                label = self.small_font.render(
                    label_for_lane(NoteKind.HANDS, lane),
                    True,
                    WHITE if active else DIM,
                )
                self.screen.blit(label, label.get_rect(center=(int(lx), int(ly))))

        if not enabled:
            cx, cy = self._hand_point(0.5, 0.0)
            off = self.small_font.render(
                "NO HAND NOTES",
                True,
                _blend(DIM, BG, 0.30),
            )
            self.screen.blit(off, off.get_rect(center=(int(cx), int(cy - 20))))

    def _draw_hand_tracking_markers(self, body: BodyState, enabled: bool) -> None:
        if not enabled:
            return
        w, h = self.size
        for control in (body.left_hand_control, body.right_hand_control):
            # Neutral deliberately has no marker. Segment highlighting remains
            # the authoritative resolved-state feedback.
            if not control.visible or control.lane is None:
                continue

            vx = (control.x - 0.5) * 2.0
            up = (0.5 - control.y) * 2.0
            # Project the wrist's body-relative direction onto the upper tunnel
            # rim. Downward components simply land toward the low/out ends.
            angle = math.atan2(max(0.0, up), vx)
            along = max(0.0, min(1.0, 1.0 - angle / math.pi))
            outer = self._hand_point(along, 1.0)
            inner = self._hand_point(along, 0.94)
            dx, dy = outer[0] - inner[0], outer[1] - inner[1]
            length = max(1.0, math.hypot(dx, dy))
            mx = outer[0] + dx / length * _HAND_TRACKER_OFFSET_PX
            my = outer[1] + dy / length * _HAND_TRACKER_OFFSET_PX
            mx = max(8.0, min(float(w - 8), mx))
            my = max(8.0, min(float(h - 8), my))

            pygame.draw.circle(self.screen, BG, (int(mx), int(my)), 9)
            pygame.draw.circle(self.screen, MAGENTA, (int(mx), int(my)), 6)
            pygame.draw.circle(
                self.screen,
                _blend(MAGENTA, WHITE, 0.34),
                (int(mx), int(my)),
                6,
                1,
            )

    def _draw_body_markers(
        self,
        body: BodyState,
        show_labels: bool = False,
        hand_enabled: bool = True,
        foot_enabled: bool = True,
        show_lower_body_sources: bool = False,
    ) -> None:
        # Preserve the existing foot markers and intentionally continue hiding
        # raw camera-space wrist dots inside the playfield.
        super()._draw_body_markers(
            body,
            show_labels=show_labels,
            hand_enabled=hand_enabled,
            foot_enabled=foot_enabled,
            show_lower_body_sources=show_lower_body_sources,
        )
        self._draw_hand_tracking_markers(body, hand_enabled)
