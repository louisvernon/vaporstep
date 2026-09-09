from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import copy
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pygame

from .cached_character_renderer import Renderer as CachedCharacterRenderer
from .domain import PoseFigure
from .user_paths import characters_dir


FORMAT_VERSION = "1"
RASTER_WIDTH = 768
MAX_RASTER_HEIGHT = 2048
MAX_SVG_BYTES = 2_000_000
MAX_SVG_ELEMENTS = 5000

BONE_PARTS = {
    "left-upper-arm": ("left-shoulder", "left-elbow"),
    "left-lower-arm": ("left-elbow", "left-wrist"),
    "right-upper-arm": ("right-shoulder", "right-elbow"),
    "right-lower-arm": ("right-elbow", "right-wrist"),
    "left-upper-leg": ("left-hip", "left-knee"),
    "left-lower-leg": ("left-knee", "left-ankle"),
    "right-upper-leg": ("right-hip", "right-knee"),
    "right-lower-leg": ("right-knee", "right-ankle"),
    "left-shoe": ("left-ankle", "left-toe"),
    "right-shoe": ("right-ankle", "right-toe"),
}
POINT_PARTS = {
    "left-hand": "left-wrist",
    "right-hand": "right-wrist",
}
REQUIRED_PARTS = frozenset(
    {
        "head",
        "torso",
        "left-upper-arm",
        "left-lower-arm",
        "right-upper-arm",
        "right-lower-arm",
        "left-upper-leg",
        "left-lower-leg",
        "right-upper-leg",
        "right-lower-leg",
    }
)
OPTIONAL_PARTS = frozenset({"left-hand", "right-hand", "left-shoe", "right-shoe"})
ALL_PARTS = REQUIRED_PARTS | OPTIONAL_PARTS
REQUIRED_ANCHORS = frozenset(
    {
        "left-ear",
        "right-ear",
        "left-shoulder",
        "right-shoulder",
        "left-elbow",
        "right-elbow",
        "left-wrist",
        "right-wrist",
        "left-hip",
        "right-hip",
        "left-knee",
        "right-knee",
        "left-ankle",
        "right-ankle",
        "left-toe",
        "right-toe",
    }
)


class SvgCharacterError(ValueError):
    pass


@dataclass(frozen=True)
class SvgCharacterDefinition:
    path: Path
    name: str
    root: ET.Element
    view_box: tuple[float, float, float, float]
    anchors: dict[str, tuple[float, float]]
    parts: dict[str, ET.Element]


@dataclass(frozen=True)
class _RasterPart:
    surface: pygame.Surface
    anchors: dict[str, tuple[float, float]]
    full_raster_width: int


@dataclass(frozen=True)
class _BonePart:
    surface: pygame.Surface
    anchor: tuple[float, float]
    bone_length: float
    full_raster_width: int


@dataclass(frozen=True)
class _TorsoPart:
    surface: pygame.Surface
    rgba: object
    anchors: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: object, *, field: str) -> float:
    text = str(value or "").strip()
    if text.endswith("px"):
        text = text[:-2]
    try:
        return float(text)
    except ValueError as exc:
        raise SvgCharacterError(f"{field} must be a plain numeric SVG coordinate") from exc


def _view_box(root: ET.Element) -> tuple[float, float, float, float]:
    raw = root.attrib.get("viewBox", "")
    try:
        values = tuple(float(value) for value in raw.replace(",", " ").split())
    except ValueError as exc:
        raise SvgCharacterError("SVG viewBox must contain four numeric values") from exc
    if len(values) != 4 or values[2] <= 0.0 or values[3] <= 0.0:
        raise SvgCharacterError("SVG viewBox must be 'x y width height' with positive size")
    return values  # type: ignore[return-value]


def _validate_safe_svg(root: ET.Element) -> None:
    blocked_tags = {
        "script",
        "foreignObject",
        "image",
        "audio",
        "video",
        "iframe",
        "object",
        "animate",
        "animateMotion",
        "animateTransform",
        "set",
    }
    elements = list(root.iter())
    if len(elements) > MAX_SVG_ELEMENTS:
        raise SvgCharacterError(f"SVG has too many elements ({len(elements)} > {MAX_SVG_ELEMENTS})")
    for element in elements:
        tag = _local_name(element.tag)
        if tag in blocked_tags:
            raise SvgCharacterError(f"unsupported SVG element <{tag}>")
        for key, value in element.attrib.items():
            local_key = _local_name(key).casefold()
            text = str(value).strip()
            if local_key == "href" and text and not text.startswith("#"):
                raise SvgCharacterError("external SVG links/resources are not supported")
            lowered = text.casefold().replace(" ", "")
            if "url(" in lowered and "url(#" not in lowered:
                raise SvgCharacterError("external CSS/SVG resources are not supported")


def parse_svg_character(path: Path) -> SvgCharacterDefinition:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_SVG_BYTES:
            raise SvgCharacterError(f"SVG is larger than {MAX_SVG_BYTES // 1_000_000} MB")
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SvgCharacterError(f"could not read SVG: {exc}") from exc

    if _local_name(root.tag) != "svg":
        raise SvgCharacterError("character file root must be an SVG element")
    _validate_safe_svg(root)
    version = root.attrib.get("data-vaporstep-version", "")
    if version != FORMAT_VERSION:
        raise SvgCharacterError(
            f"unsupported VaporStep character version {version!r}; expected {FORMAT_VERSION!r}"
        )

    ids: dict[str, ET.Element] = {}
    for element in root.iter():
        element_id = element.attrib.get("id")
        if not element_id:
            continue
        if element_id in ids:
            raise SvgCharacterError(f"duplicate SVG id {element_id!r}")
        ids[element_id] = element

    parts: dict[str, ET.Element] = {}
    for part_name in ALL_PARTS:
        element = ids.get(part_name)
        if element is not None:
            parts[part_name] = element

    missing_parts = sorted(REQUIRED_PARTS - parts.keys())
    if missing_parts:
        raise SvgCharacterError("missing artwork groups: " + ", ".join(missing_parts))

    anchors: dict[str, tuple[float, float]] = {}
    for anchor_name in REQUIRED_ANCHORS:
        element = ids.get(f"anchor-{anchor_name}")
        if element is None:
            continue
        if "transform" in element.attrib:
            raise SvgCharacterError(
                f"anchor-{anchor_name} must use cx/cy coordinates, not an SVG transform"
            )
        if _local_name(element.tag) not in {"circle", "ellipse"}:
            raise SvgCharacterError(f"anchor-{anchor_name} must be a circle or ellipse")
        anchors[anchor_name] = (
            _number(element.attrib.get("cx"), field=f"anchor-{anchor_name} cx"),
            _number(element.attrib.get("cy"), field=f"anchor-{anchor_name} cy"),
        )

    missing_anchors = sorted(REQUIRED_ANCHORS - anchors.keys())
    if missing_anchors:
        raise SvgCharacterError("missing rig anchors: " + ", ".join(missing_anchors))

    name = root.attrib.get("data-vaporstep-name", "").strip() or path.stem
    return SvgCharacterDefinition(
        path=path,
        name=name,
        root=root,
        view_box=_view_box(root),
        anchors=anchors,
        parts=parts,
    )


def discover_character_files(directory: Path | None = None) -> tuple[Path, ...]:
    directory = Path(directory) if directory is not None else characters_dir()
    try:
        files = [path for path in directory.iterdir() if path.is_file() and path.suffix.casefold() == ".svg"]
    except OSError:
        return ()
    return tuple(sorted(files, key=lambda path: path.name.casefold()))


def select_custom_character_file(directory: Path | None = None) -> Path | None:
    """Select an explicitly active custom character, or the sole SVG in the folder.

    This keeps the built-in procedural character as the no-file/default path. A
    single custom SVG is convenient for first-time creators; collections remain
    inert unless one file is named active.svg, avoiding surprising selection.
    """

    files = discover_character_files(directory)
    for path in files:
        if path.name.casefold() == "active.svg":
            return path
    return files[0] if len(files) == 1 else None


def _fragment_svg(definition: SvgCharacterDefinition, part_name: str) -> bytes:
    root = definition.root
    view_x, view_y, view_w, view_h = definition.view_box
    raster_height = max(1, int(round(RASTER_WIDTH * view_h / view_w)))
    if raster_height > MAX_RASTER_HEIGHT:
        raise SvgCharacterError(
            f"SVG aspect ratio would rasterize taller than {MAX_RASTER_HEIGHT}px"
        )
    attrs = dict(root.attrib)
    attrs["width"] = str(RASTER_WIDTH)
    attrs["height"] = str(raster_height)
    attrs["viewBox"] = f"{view_x:g} {view_y:g} {view_w:g} {view_h:g}"
    fragment_root = ET.Element(root.tag, attrs)

    # Retain internal definitions used by the selected artwork, but never copy
    # the guide/rig layer itself into runtime output.
    for child in root:
        if _local_name(child.tag) == "defs":
            fragment_root.append(copy.deepcopy(child))
    fragment_root.append(copy.deepcopy(definition.parts[part_name]))
    return ET.tostring(fragment_root, encoding="utf-8", xml_declaration=True)


def _rasterize_part(definition: SvgCharacterDefinition, part_name: str) -> _RasterPart:
    try:
        surface = pygame.image.load(BytesIO(_fragment_svg(definition, part_name)), f"{part_name}.svg")
    except (pygame.error, OSError) as exc:
        raise SvgCharacterError(f"could not rasterize {part_name}: {exc}") from exc

    alpha_rect = surface.get_bounding_rect(min_alpha=1)
    if alpha_rect.width <= 0 or alpha_rect.height <= 0:
        raise SvgCharacterError(f"artwork group {part_name!r} is empty")
    cropped = surface.subsurface(alpha_rect).copy()

    view_x, view_y, view_w, view_h = definition.view_box
    scale_x = surface.get_width() / view_w
    scale_y = surface.get_height() / view_h
    anchors = {
        name: (
            (x - view_x) * scale_x - alpha_rect.left,
            (y - view_y) * scale_y - alpha_rect.top,
        )
        for name, (x, y) in definition.anchors.items()
    }
    return _RasterPart(cropped, anchors, surface.get_width())


def _rotate_point(
    point: tuple[float, float],
    old_size: tuple[int, int],
    new_size: tuple[int, int],
    angle_degrees: float,
) -> tuple[float, float]:
    # pygame.transform.rotate uses mathematical CCW rotation, while pygame's
    # screen coordinates have +Y downward.
    old_center = (old_size[0] * 0.5, old_size[1] * 0.5)
    new_center = (new_size[0] * 0.5, new_size[1] * 0.5)
    dx = point[0] - old_center[0]
    dy = point[1] - old_center[1]
    radians = math.radians(angle_degrees)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    return (
        new_center[0] + cos_a * dx + sin_a * dy,
        new_center[1] - sin_a * dx + cos_a * dy,
    )


def _normalize_bone(part: _RasterPart, anchor_a: str, anchor_b: str) -> _BonePart:
    a = part.anchors[anchor_a]
    b = part.anchors[anchor_b]
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    distance = math.hypot(dx, dy)
    if distance < 1.0:
        raise SvgCharacterError(f"anchors {anchor_a} and {anchor_b} are too close together")

    source_angle = math.degrees(math.atan2(dy, dx))
    rotated = pygame.transform.rotate(part.surface, source_angle)
    rotated_a = _rotate_point(a, part.surface.get_size(), rotated.get_size(), source_angle)
    alpha_rect = rotated.get_bounding_rect(min_alpha=1)
    cropped = rotated.subsurface(alpha_rect).copy()
    cropped_a = (rotated_a[0] - alpha_rect.left, rotated_a[1] - alpha_rect.top)
    return _BonePart(cropped, cropped_a, distance, part.full_raster_width)


class SvgCharacter:
    def __init__(self, definition: SvgCharacterDefinition) -> None:
        self.definition = definition
        rasters = {name: _rasterize_part(definition, name) for name in definition.parts}
        self._bones = {
            name: _normalize_bone(rasters[name], *anchors)
            for name, anchors in BONE_PARTS.items()
            if name in rasters
        }
        self._points = {name: rasters[name] for name in POINT_PARTS if name in rasters}
        self._head = rasters["head"]
        torso = rasters["torso"]

        # Cache the source torso pixels once. Only the small perspective warp is
        # repeated each frame.
        import numpy as np

        torso_rgb = pygame.surfarray.array3d(torso.surface).swapaxes(0, 1)
        torso_alpha = pygame.surfarray.array_alpha(torso.surface).swapaxes(0, 1)
        torso_rgba = np.dstack((torso_rgb, torso_alpha))
        self._torso = _TorsoPart(
            torso.surface,
            torso_rgba,
            (
                torso.anchors["left-shoulder"],
                torso.anchors["right-shoulder"],
                torso.anchors["right-hip"],
                torso.anchors["left-hip"],
            ),
        )

    @classmethod
    def from_file(cls, path: Path) -> "SvgCharacter":
        return cls(parse_svg_character(path))

    @staticmethod
    def _scaled_size(surface: pygame.Surface, sx: float, sy: float) -> tuple[int, int]:
        return (
            max(1, min(4096, int(round(surface.get_width() * sx)))),
            max(1, min(4096, int(round(surface.get_height() * sy)))),
        )

    def _draw_bone(
        self,
        renderer: CachedCharacterRenderer,
        part_name: str,
        live_a: tuple[int, int] | None,
        live_b: tuple[int, int] | None,
    ) -> None:
        if live_a is None or live_b is None:
            return
        part = self._bones.get(part_name)
        if part is None:
            return
        dx = live_b[0] - live_a[0]
        dy = live_b[1] - live_a[1]
        length = math.hypot(dx, dy)
        if length < 1.0:
            return

        viewport_scale = renderer._camera_rect().width / part.full_raster_width
        sx = length / part.bone_length
        sy = viewport_scale
        size = self._scaled_size(part.surface, sx, sy)
        scaled = pygame.transform.smoothscale(part.surface, size)
        scaled_anchor = (part.anchor[0] * sx, part.anchor[1] * sy)

        live_angle = math.degrees(math.atan2(dy, dx))
        rotated = pygame.transform.rotate(scaled, -live_angle)
        rotated_anchor = _rotate_point(
            scaled_anchor,
            scaled.get_size(),
            rotated.get_size(),
            -live_angle,
        )
        renderer.screen.blit(
            rotated,
            (
                int(round(live_a[0] - rotated_anchor[0])),
                int(round(live_a[1] - rotated_anchor[1])),
            ),
        )

    def _draw_point_part(
        self,
        renderer: CachedCharacterRenderer,
        part_name: str,
        live_anchor: tuple[int, int] | None,
    ) -> None:
        if live_anchor is None:
            return
        part = self._points.get(part_name)
        if part is None:
            return
        anchor_name = POINT_PARTS[part_name]
        scale = renderer._camera_rect().width / part.full_raster_width
        size = self._scaled_size(part.surface, scale, scale)
        scaled = pygame.transform.smoothscale(part.surface, size)
        source_anchor = part.anchors[anchor_name]
        anchor = (source_anchor[0] * scale, source_anchor[1] * scale)
        renderer.screen.blit(
            scaled,
            (
                int(round(live_anchor[0] - anchor[0])),
                int(round(live_anchor[1] - anchor[1])),
            ),
        )

    def _draw_head(self, renderer: CachedCharacterRenderer, figure: PoseFigure) -> None:
        geometry = renderer._head_geometry(figure)
        if geometry is None:
            return
        center, radius = geometry
        left = self._head.anchors["left-ear"]
        right = self._head.anchors["right-ear"]
        source_mid = ((left[0] + right[0]) * 0.5, (left[1] + right[1]) * 0.5)
        source_span = max(1.0, math.dist(left, right))
        # The built-in character uses radius = ear distance * 0.70. Recover
        # that same implied ear span so custom heads inherit identical sizing
        # and fallback behavior while remaining upright like the built-in head.
        target_span = radius / 0.70
        scale = target_span / source_span
        size = self._scaled_size(self._head.surface, scale, scale)
        scaled = pygame.transform.smoothscale(self._head.surface, size)
        midpoint = (source_mid[0] * scale, source_mid[1] * scale)
        renderer.screen.blit(
            scaled,
            (
                int(round(center[0] - midpoint[0])),
                int(round(center[1] - midpoint[1])),
            ),
        )

    def _live_torso_quad(
        self,
        renderer: CachedCharacterRenderer,
        figure: PoseFigure,
    ) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None:
        points = [renderer._visible_screen_point(figure, index) for index in (11, 12, 24, 23)]
        if any(point is None for point in points):
            return None
        ls, rs, rh, lh = points
        assert ls is not None and rs is not None and rh is not None and lh is not None
        scale = float(renderer._camera_rect().width)
        shoulder_width = max(1.0, math.dist(ls, rs))
        shoulder_dx = (rs[0] - ls[0]) / shoulder_width
        shoulder_dy = (rs[1] - ls[1]) / shoulder_width
        shoulder_inset = max(scale * 0.006, shoulder_width * 0.08)
        hip_pad = scale * 0.007
        return (
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
        )

    def _draw_torso(self, renderer: CachedCharacterRenderer, figure: PoseFigure) -> None:
        live_quad = self._live_torso_quad(renderer, figure)
        if live_quad is None:
            return
        try:
            import cv2
            import numpy as np
        except ImportError:
            return

        source = np.asarray(self._torso.anchors, dtype=np.float32)
        destination = np.asarray(live_quad, dtype=np.float32)
        matrix = cv2.getPerspectiveTransform(source, destination)

        width, height = self._torso.surface.get_size()
        corners = np.asarray(
            [
                [
                    [0.0, 0.0],
                    [float(width), 0.0],
                    [float(width), float(height)],
                    [0.0, float(height)],
                ]
            ],
            dtype=np.float32,
        )
        transformed = cv2.perspectiveTransform(corners, matrix)[0]
        min_x = math.floor(float(transformed[:, 0].min()))
        min_y = math.floor(float(transformed[:, 1].min()))
        max_x = math.ceil(float(transformed[:, 0].max()))
        max_y = math.ceil(float(transformed[:, 1].max()))
        out_w = max_x - min_x
        out_h = max_y - min_y
        if out_w <= 0 or out_h <= 0 or out_w > 4096 or out_h > 4096:
            return

        translation = np.asarray(
            [[1.0, 0.0, -min_x], [0.0, 1.0, -min_y], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        local_matrix = translation @ matrix
        warped = cv2.warpPerspective(
            self._torso.rgba,
            local_matrix,
            (out_w, out_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        surface = pygame.image.frombuffer(warped.data, (out_w, out_h), "RGBA")
        renderer.screen.blit(surface, (min_x, min_y))

    def draw(self, renderer: CachedCharacterRenderer, figure: PoseFigure) -> None:
        # Preserve the built-in character's draw order: legs, torso, arms,
        # head, then endpoint details.
        live = renderer._visible_screen_point
        for name, indices in (
            ("left-upper-leg", (23, 25)),
            ("left-lower-leg", (25, 27)),
            ("right-upper-leg", (24, 26)),
            ("right-lower-leg", (26, 28)),
        ):
            self._draw_bone(renderer, name, live(figure, indices[0]), live(figure, indices[1]))

        self._draw_torso(renderer, figure)

        for name, indices in (
            ("left-upper-arm", (11, 13)),
            ("left-lower-arm", (13, 15)),
            ("right-upper-arm", (12, 14)),
            ("right-lower-arm", (14, 16)),
        ):
            self._draw_bone(renderer, name, live(figure, indices[0]), live(figure, indices[1]))

        self._draw_head(renderer, figure)
        self._draw_point_part(renderer, "left-hand", live(figure, 15))
        self._draw_point_part(renderer, "right-hand", live(figure, 16))
        self._draw_bone(renderer, "left-shoe", live(figure, 27), live(figure, 31))
        self._draw_bone(renderer, "right-shoe", live(figure, 28), live(figure, 32))


class Renderer(CachedCharacterRenderer):
    """Cached renderer that optionally replaces built-in character artwork with a rigged SVG."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._svg_character: SvgCharacter | None = None
        self._svg_character_error: str | None = None
        path = select_custom_character_file()
        if path is not None:
            try:
                self._svg_character = SvgCharacter.from_file(path)
            except SvgCharacterError as exc:
                self._svg_character_error = str(exc)
                print(
                    f"VaporStep: could not load custom character {path.name}: {exc}; using built-in character",
                    file=sys.stderr,
                )

    def _draw_pose_figure(self, figure: PoseFigure) -> None:
        if self._svg_character is not None:
            try:
                self._svg_character.draw(self, figure)
                return
            except Exception as exc:
                # A bad user asset should never take down gameplay. Disable it
                # for the rest of this run and fall back to the built-in figure.
                self._svg_character_error = str(exc)
                self._svg_character = None
                print(
                    f"VaporStep: custom character rendering failed: {exc}; using built-in character",
                    file=sys.stderr,
                )
        super()._draw_pose_figure(figure)
