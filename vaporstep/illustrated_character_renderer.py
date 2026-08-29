from __future__ import annotations

import base64
import io
import math
from collections import OrderedDict

import pygame

from .character_renderer import Renderer as ProceduralCharacterRenderer
from .domain import PoseFigure
from .resources import resource_path


_AVATAR_ATLAS_RECTS = {
    "head": (0, 0, 98, 103),
    "hair_front": (100, 0, 155, 148),
    "hair_back": (258, 0, 120, 131),
    "torso": (378, 0, 133, 161),
    "pelvis": (0, 165, 130, 93),
    "shoe_left": (135, 165, 108, 102),
    "shoe_right": (248, 165, 129, 103),
}
_AVATAR_CACHE_LIMIT = 192


class Renderer(ProceduralCharacterRenderer):
    """Hybrid character: procedural articulated limbs plus illustrated clothing."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._avatar_parts: dict[str, pygame.Surface] | None = None
        self._avatar_transform_cache: OrderedDict[tuple[object, ...], pygame.Surface] = OrderedDict()

    def _avatar_part(self, name: str) -> pygame.Surface | None:
        if self._avatar_parts is None:
            parts: dict[str, pygame.Surface] = {}
            try:
                encoded = resource_path("assets/avatar_atlas.png.b64").read_text(encoding="ascii")
                atlas = pygame.image.load(io.BytesIO(base64.b64decode(encoded)))
                for part_name, rect in _AVATAR_ATLAS_RECTS.items():
                    parts[part_name] = atlas.subsurface(pygame.Rect(rect)).copy()
            except (OSError, ValueError, pygame.error):
                # The procedural character is intentionally a complete fallback.
                parts = {}
            self._avatar_parts = parts
        return self._avatar_parts.get(name)

    def _avatar_transform(
        self,
        name: str,
        width: float,
        height: float,
        angle: float = 0.0,
    ) -> pygame.Surface | None:
        part = self._avatar_part(name)
        if part is None:
            return None

        # Quantization keeps transform churn bounded on older CPUs. At gameplay
        # scale 4 px / 5 degrees is visually smooth while giving the cache reuse.
        quant_w = max(4, int(round(max(4.0, width) / 4.0)) * 4)
        quant_h = max(4, int(round(max(4.0, height) / 4.0)) * 4)
        quant_angle = int(round(angle / 5.0)) * 5
        key = (name, quant_w, quant_h, quant_angle)
        cached = self._avatar_transform_cache.get(key)
        if cached is not None:
            self._avatar_transform_cache.move_to_end(key)
            return cached

        transformed = pygame.transform.smoothscale(part, (quant_w, quant_h))
        if quant_angle:
            transformed = pygame.transform.rotate(transformed, quant_angle)
        self._avatar_transform_cache[key] = transformed
        self._avatar_transform_cache.move_to_end(key)
        while len(self._avatar_transform_cache) > _AVATAR_CACHE_LIMIT:
            self._avatar_transform_cache.popitem(last=False)
        return transformed

    def _blit_avatar_part(
        self,
        name: str,
        center: tuple[float, float],
        width: float,
        height: float,
        *,
        angle: float = 0.0,
    ) -> bool:
        image = self._avatar_transform(name, width, height, angle)
        if image is None:
            return False
        self.screen.blit(image, image.get_rect(center=(int(center[0]), int(center[1]))))
        return True

    def _draw_head_and_hair(self, figure: PoseFigure) -> None:
        geometry = self._head_geometry(figure)
        if geometry is None or self._avatar_part("head") is None:
            super()._draw_head_and_hair(figure)
            return

        center, radius = geometry
        sway = self._update_hair_sway(center, radius)
        hair_angle = max(-12.0, min(12.0, -sway / max(radius, 1) * 10.0))

        # Back hair carries most of the spring lag. Face is tied rigidly to the
        # tracked head; front hair gets only a little lag so the eyes stay clear.
        back_w = radius * 2.65
        self._blit_avatar_part(
            "hair_back",
            (center[0] + sway * 0.70, center[1] - radius * 0.18),
            back_w,
            back_w * (131.0 / 120.0),
            angle=hair_angle,
        )
        head_w = radius * 2.15
        self._blit_avatar_part("head", center, head_w, head_w * (103.0 / 98.0))
        front_w = radius * 2.85
        self._blit_avatar_part(
            "hair_front",
            (center[0] + sway * 0.28, center[1] - radius * 0.40),
            front_w,
            front_w * (148.0 / 155.0),
            angle=hair_angle * 0.45,
        )

    def _draw_torso(self, figure: PoseFigure, scale: float) -> None:
        # Keep the procedural torso underneath: if an illustrated edge is
        # transparent or briefly misaligned, the body never disappears.
        super()._draw_torso(figure, scale)

        ls = self._visible_screen_point(figure, 11)
        rs = self._visible_screen_point(figure, 12)
        lh = self._visible_screen_point(figure, 23)
        rh = self._visible_screen_point(figure, 24)
        if any(point is None for point in (ls, rs, lh, rh)):
            return
        assert ls is not None and rs is not None and lh is not None and rh is not None

        shoulder_mid = ((ls[0] + rs[0]) * 0.5, (ls[1] + rs[1]) * 0.5)
        hip_mid = ((lh[0] + rh[0]) * 0.5, (lh[1] + rh[1]) * 0.5)
        body_dx = hip_mid[0] - shoulder_mid[0]
        body_dy = hip_mid[1] - shoulder_mid[1]
        body_length = max(1.0, math.hypot(body_dx, body_dy))
        shoulder_width = max(1.0, math.dist(ls, rs))
        torso_angle = -math.degrees(math.atan2(body_dx, max(1.0, body_dy)))
        torso_center = (
            shoulder_mid[0] + body_dx * 0.42,
            shoulder_mid[1] + body_dy * 0.42,
        )
        self._blit_avatar_part(
            "torso",
            torso_center,
            shoulder_width * 1.55,
            body_length * 1.34,
            angle=torso_angle,
        )

        hip_width = max(1.0, math.dist(lh, rh))
        hip_angle = -math.degrees(math.atan2(rh[1] - lh[1], rh[0] - lh[0]))
        pelvis_w = hip_width * 1.70
        pelvis_h = pelvis_w * (93.0 / 130.0)
        self._blit_avatar_part(
            "pelvis",
            (hip_mid[0], hip_mid[1] + pelvis_h * 0.12),
            pelvis_w,
            pelvis_h,
            angle=hip_angle,
        )

    def _draw_illustrated_shoe(
        self,
        name: str,
        ankle: tuple[int, int] | None,
        toe: tuple[int, int] | None,
        scale: float,
        *,
        base_angle: float,
    ) -> None:
        if ankle is None or toe is None:
            return
        part = self._avatar_part(name)
        if part is None:
            return
        dx = toe[0] - ankle[0]
        dy = toe[1] - ankle[1]
        foot_length = max(1.0, math.hypot(dx, dy))
        target_angle = math.degrees(math.atan2(dy, dx))
        rotation = -(target_angle - base_angle)
        width = max(scale * 0.055, foot_length * 2.15)
        height = width * part.get_height() / max(1, part.get_width())
        center = (ankle[0] + dx * 0.48, ankle[1] + dy * 0.48)
        self._blit_avatar_part(name, center, width, height, angle=rotation)

    def _draw_character_figure(self, figure: PoseFigure) -> None:
        # The parent draws the complete procedural avatar (our baseline and
        # fallback), calling the overridden head/torso methods above. Shoes are
        # overlaid last so their detailed silhouette wins at the feet.
        super()._draw_character_figure(figure)
        scale = float(self._camera_rect().width)
        self._draw_illustrated_shoe(
            "shoe_left",
            self._visible_screen_point(figure, 27),
            self._visible_screen_point(figure, 31),
            scale,
            base_angle=180.0,
        )
        self._draw_illustrated_shoe(
            "shoe_right",
            self._visible_screen_point(figure, 28),
            self._visible_screen_point(figure, 32),
            scale,
            base_angle=0.0,
        )
