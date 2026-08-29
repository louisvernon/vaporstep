from __future__ import annotations

import math

import pygame

from .character_renderer import Renderer as ProceduralRenderer
from .domain import PoseFigure
from .player_visual_runtime import current_player_visual
from .renderer import BG, CYAN, MAGENTA, PURPLE
from .resources import resource_path


class Renderer(ProceduralRenderer):
    """Pose-driven procedural avatar with optional illustrated overlays."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._avatar_parts: dict[str, pygame.Surface | None] = {}
        self._avatar_transform_cache: dict[tuple[object, ...], pygame.Surface] = {}

    def replace_screen(self, screen: pygame.Surface) -> None:
        super().replace_screen(screen)
        self._avatar_transform_cache.clear()

    def _draw_pose_figure(self, figure: PoseFigure) -> None:
        # The former Skeleton slot is now the dimensional procedural character.
        if current_player_visual() == "character":
            self._draw_hybrid_character(figure)
        else:
            super()._draw_character_figure(figure)

    def _avatar_part(self, name: str) -> pygame.Surface | None:
        if name in self._avatar_parts:
            return self._avatar_parts[name]
        try:
            path = resource_path(f"assets/avatar/{name}.png")
            part = pygame.image.load(str(path)).convert_alpha() if path.exists() else None
        except Exception:
            part = None
        self._avatar_parts[name] = part
        return part

    def _transformed_part(
        self,
        name: str,
        width: float,
        height: float,
        angle: float = 0.0,
        *,
        flip_x: bool = False,
    ) -> pygame.Surface | None:
        source = self._avatar_part(name)
        if source is None:
            return None
        width_px = max(2, int(round(width / 4.0)) * 4)
        height_px = max(2, int(round(height / 4.0)) * 4)
        angle_deg = int(round(angle / 5.0)) * 5
        key = (name, width_px, height_px, angle_deg, flip_x)
        cached = self._avatar_transform_cache.get(key)
        if cached is not None:
            return cached
        scaled = pygame.transform.smoothscale(source, (width_px, height_px))
        if flip_x:
            scaled = pygame.transform.flip(scaled, True, False)
        result = pygame.transform.rotate(scaled, -angle_deg) if angle_deg else scaled
        if len(self._avatar_transform_cache) >= 384:
            self._avatar_transform_cache.clear()
        self._avatar_transform_cache[key] = result
        return result

    def _blit_part(
        self,
        name: str,
        center: tuple[float, float],
        width: float,
        height: float,
        angle: float = 0.0,
        *,
        flip_x: bool = False,
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> bool:
        part = self._transformed_part(name, width, height, angle, flip_x=flip_x)
        if part is None:
            return False
        target = (int(center[0] + offset[0]), int(center[1] + offset[1]))
        self.screen.blit(part, part.get_rect(center=target))
        return True

    @staticmethod
    def _angle(p0: tuple[float, float], p1: tuple[float, float]) -> float:
        return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))

    def _draw_art_torso(self, figure: PoseFigure) -> None:
        ls = self._visible_screen_point(figure, 11)
        rs = self._visible_screen_point(figure, 12)
        lh = self._visible_screen_point(figure, 23)
        rh = self._visible_screen_point(figure, 24)
        if any(point is None for point in (ls, rs, lh, rh)):
            return
        assert ls is not None and rs is not None and lh is not None and rh is not None
        shoulders = ((ls[0] + rs[0]) * 0.5, (ls[1] + rs[1]) * 0.5)
        hips = ((lh[0] + rh[0]) * 0.5, (lh[1] + rh[1]) * 0.5)
        shoulder_width = max(12.0, math.dist(ls, rs))
        torso_length = max(18.0, math.dist(shoulders, hips))
        center = (
            (shoulders[0] + hips[0]) * 0.5,
            (shoulders[1] + hips[1]) * 0.5 - torso_length * 0.10,
        )
        lean = self._angle(shoulders, hips) - 90.0
        self._blit_part("torso", center, shoulder_width * 1.05, torso_length * 1.43, lean)

        hip_width = max(10.0, math.dist(lh, rh))
        self._blit_part(
            "pelvis",
            hips,
            hip_width * 1.48,
            hip_width * 0.78,
            self._angle(lh, rh),
            offset=(0.0, hip_width * 0.10),
        )

    def _draw_art_head(self, figure: PoseFigure) -> bool:
        geometry = self._head_geometry(figure)
        if geometry is None:
            return False
        center, radius = geometry
        left_ear = self._visible_screen_point(figure, 7)
        right_ear = self._visible_screen_point(figure, 8)
        tilt = self._angle(left_ear, right_ear) if left_ear and right_ear else 0.0
        sway = self._update_hair_sway(center, radius)
        hair_center = (center[0] + sway * 0.28, center[1] - radius * 0.30)
        self._blit_part("hair_back", hair_center, radius * 2.45, radius * 2.35, tilt)
        drawn = self._blit_part("head", center, radius * 2.05, radius * 2.05, tilt)
        self._blit_part("hair_front", hair_center, radius * 2.85, radius * 2.60, tilt)
        return drawn

    def _draw_art_shoe(
        self,
        ankle: tuple[int, int] | None,
        toe: tuple[int, int] | None,
        scale: float,
        *,
        right: bool,
    ) -> bool:
        if ankle is None or toe is None:
            return False
        foot_length = math.dist(ankle, toe)
        if foot_length < 3.0:
            return False
        ux = (toe[0] - ankle[0]) / foot_length
        uy = (toe[1] - ankle[1]) / foot_length
        center = (ankle[0] + ux * foot_length * 0.50, ankle[1] + uy * foot_length * 0.50)
        width = max(scale * 0.035, foot_length * 1.72)
        return self._blit_part(
            "shoe_left",
            center,
            width,
            width * 0.48,
            self._angle(ankle, toe),
            flip_x=right,
        )

    def _draw_hybrid_character(self, figure: PoseFigure) -> None:
        scale = float(self._camera_rect().width)
        body_fill = self._blend_body_fill()

        for hip_i, knee_i, ankle_i, color in (
            (23, 25, 27, CYAN),
            (24, 26, 28, MAGENTA),
        ):
            hip = self._visible_screen_point(figure, hip_i)
            knee = self._visible_screen_point(figure, knee_i)
            ankle = self._visible_screen_point(figure, ankle_i)
            if hip is not None and knee is not None:
                self._draw_tapered_segment(
                    hip, knee, scale * 0.037, scale * 0.031,
                    fill=body_fill, outline=color, accent=color,
                )
            if knee is not None and ankle is not None:
                self._draw_tapered_segment(
                    knee, ankle, scale * 0.031, scale * 0.024,
                    fill=body_fill, outline=color, accent=color,
                )

        self._draw_torso(figure, scale)
        self._draw_art_torso(figure)

        for shoulder_i, elbow_i, wrist_i, color in (
            (11, 13, 15, CYAN),
            (12, 14, 16, MAGENTA),
        ):
            shoulder = self._visible_screen_point(figure, shoulder_i)
            elbow = self._visible_screen_point(figure, elbow_i)
            wrist = self._visible_screen_point(figure, wrist_i)
            if shoulder is not None and elbow is not None:
                self._draw_tapered_segment(
                    shoulder, elbow, scale * 0.030, scale * 0.025,
                    fill=body_fill, outline=color, accent=color,
                )
            if elbow is not None and wrist is not None:
                self._draw_tapered_segment(
                    elbow, wrist, scale * 0.025, scale * 0.020,
                    fill=body_fill, outline=color, accent=color,
                )

        if not self._draw_art_head(figure):
            self._draw_head_and_hair(figure)

        hand_radius = max(5, int(scale * 0.014))
        self._draw_hand(self._visible_screen_point(figure, 15), hand_radius, CYAN, right=False)
        self._draw_hand(self._visible_screen_point(figure, 16), hand_radius, MAGENTA, right=True)

        left_ankle = self._visible_screen_point(figure, 27)
        left_toe = self._visible_screen_point(figure, 31)
        right_ankle = self._visible_screen_point(figure, 28)
        right_toe = self._visible_screen_point(figure, 32)
        if not self._draw_art_shoe(left_ankle, left_toe, scale, right=False):
            self._draw_shoe(left_ankle, left_toe, scale, CYAN, right=False)
        if not self._draw_art_shoe(right_ankle, right_toe, scale, right=True):
            self._draw_shoe(right_ankle, right_toe, scale, MAGENTA, right=True)

    @staticmethod
    def _blend_body_fill():
        # Same fill as the procedural renderer, kept here to avoid importing
        # private implementation details beyond the existing drawing helpers.
        return (int(BG[0] + (PURPLE[0] - BG[0]) * 0.18),
                int(BG[1] + (PURPLE[1] - BG[1]) * 0.18),
                int(BG[2] + (PURPLE[2] - BG[2]) * 0.18))
