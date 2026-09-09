from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pygame

from .cached_character_renderer import Renderer as CachedCharacterRenderer
from .domain import PoseFigure
from .renderer import BG
from .resources import resource_path
from .user_paths import characters_dir


FORMAT_VERSION = "1"
MAX_SVG_BYTES = 2_000_000
MAX_SVG_ELEMENTS = 5000
REFERENCE_FILENAME = "reference-robot.svg"
_CURVE_STEPS = 10
_CIRCLE_STEPS = 28

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


Color = tuple[int, int, int, int]
Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]


@dataclass(frozen=True)
class VectorPrimitive:
    points: tuple[Point, ...]
    closed: bool
    fill: Color | None
    stroke: Color | None
    stroke_width: float


@dataclass(frozen=True)
class VectorPart:
    primitives: tuple[VectorPrimitive, ...]


@dataclass(frozen=True)
class SvgCharacterDefinition:
    path: Path
    name: str
    view_box: tuple[float, float, float, float]
    anchors: dict[str, Point]
    parts: dict[str, VectorPart]


_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_PATH_TOKEN_RE = re.compile(
    r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)
_TRANSFORM_RE = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: object, *, field: str, default: float | None = None) -> float:
    text = str(value or "").strip()
    if not text:
        if default is not None:
            return default
        raise SvgCharacterError(f"missing numeric SVG value for {field}")
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


def _matrix_multiply(left: Matrix, right: Matrix) -> Matrix:
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re_, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re_ + lc * rf + le,
        lb * re_ + ld * rf + lf,
    )


def _transform_point(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def _parse_transform(text: str) -> Matrix:
    matrix = _IDENTITY
    for name, raw_args in _TRANSFORM_RE.findall(text or ""):
        try:
            args = [float(value) for value in re.split(r"[\s,]+", raw_args.strip()) if value]
        except ValueError as exc:
            raise SvgCharacterError(f"invalid SVG transform {name}({raw_args})") from exc
        op = _IDENTITY
        lower = name.casefold()
        if lower == "matrix" and len(args) == 6:
            op = tuple(args)  # type: ignore[assignment]
        elif lower == "translate" and len(args) in (1, 2):
            op = (1.0, 0.0, 0.0, 1.0, args[0], args[1] if len(args) == 2 else 0.0)
        elif lower == "scale" and len(args) in (1, 2):
            op = (args[0], 0.0, 0.0, args[1] if len(args) == 2 else args[0], 0.0, 0.0)
        elif lower == "rotate" and len(args) in (1, 3):
            radians = math.radians(args[0])
            cos_a, sin_a = math.cos(radians), math.sin(radians)
            rotate = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
            if len(args) == 3:
                cx, cy = args[1], args[2]
                op = _matrix_multiply(
                    _matrix_multiply((1.0, 0.0, 0.0, 1.0, cx, cy), rotate),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
            else:
                op = rotate
        elif lower == "skewx" and len(args) == 1:
            op = (1.0, 0.0, math.tan(math.radians(args[0])), 1.0, 0.0, 0.0)
        elif lower == "skewy" and len(args) == 1:
            op = (1.0, math.tan(math.radians(args[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            raise SvgCharacterError(f"unsupported SVG transform {name}({raw_args})")
        matrix = _matrix_multiply(matrix, op)
    return matrix


def _parse_style(element: ET.Element, parent: dict[str, str]) -> dict[str, str]:
    style = dict(parent)
    inline = element.attrib.get("style", "")
    for item in inline.split(";"):
        if ":" in item:
            key, value = item.split(":", 1)
            style[key.strip()] = value.strip()
    for key in (
        "fill",
        "fill-opacity",
        "stroke",
        "stroke-opacity",
        "stroke-width",
        "opacity",
        "display",
        "visibility",
    ):
        if key in element.attrib:
            style[key] = element.attrib[key]
    return style


def _parse_color(value: str | None, opacity: float) -> Color | None:
    text = str(value or "").strip()
    if not text or text.casefold() == "none":
        return None
    if text.casefold().startswith("url("):
        raise SvgCharacterError("SVG gradients/pattern fills are not supported in character format v1")
    if text.startswith("#"):
        raw = text[1:]
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) != 6:
            raise SvgCharacterError(f"unsupported SVG color {text!r}")
        try:
            rgb = tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4))
        except ValueError as exc:
            raise SvgCharacterError(f"unsupported SVG color {text!r}") from exc
    else:
        match = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", text)
        if not match:
            raise SvgCharacterError(
                f"unsupported SVG color {text!r}; use #RGB, #RRGGBB, rgb(), or none"
            )
        rgb = tuple(max(0, min(255, int(value))) for value in match.groups())
    alpha = max(0, min(255, int(round(255.0 * opacity))))
    return (rgb[0], rgb[1], rgb[2], alpha)


def _primitive_style(style: dict[str, str]) -> tuple[Color | None, Color | None, float]:
    opacity = max(0.0, min(1.0, _number(style.get("opacity", "1"), field="opacity")))
    fill_opacity = max(
        0.0,
        min(1.0, _number(style.get("fill-opacity", "1"), field="fill-opacity")),
    )
    stroke_opacity = max(
        0.0,
        min(1.0, _number(style.get("stroke-opacity", "1"), field="stroke-opacity")),
    )
    fill = _parse_color(style.get("fill", "#000000"), opacity * fill_opacity)
    stroke = _parse_color(style.get("stroke", "none"), opacity * stroke_opacity)
    stroke_width = max(
        0.0,
        _number(style.get("stroke-width", "1"), field="stroke-width"),
    )
    return fill, stroke, stroke_width


def _rounded_rect_points(x: float, y: float, width: float, height: float, rx: float, ry: float) -> tuple[Point, ...]:
    rx = max(0.0, min(abs(rx), abs(width) * 0.5))
    ry = max(0.0, min(abs(ry), abs(height) * 0.5))
    if rx <= 0.0 or ry <= 0.0:
        return ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
    points: list[Point] = []
    for cx, cy, start in (
        (x + width - rx, y + ry, -90.0),
        (x + width - rx, y + height - ry, 0.0),
        (x + rx, y + height - ry, 90.0),
        (x + rx, y + ry, 180.0),
    ):
        for step in range(5):
            angle = math.radians(start + 90.0 * step / 4.0)
            points.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
    return tuple(points)


def _ellipse_points(cx: float, cy: float, rx: float, ry: float) -> tuple[Point, ...]:
    return tuple(
        (
            cx + rx * math.cos(2.0 * math.pi * index / _CIRCLE_STEPS),
            cy + ry * math.sin(2.0 * math.pi * index / _CIRCLE_STEPS),
        )
        for index in range(_CIRCLE_STEPS)
    )


def _points_attribute(value: str) -> tuple[Point, ...]:
    try:
        numbers = [float(token) for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value)]
    except ValueError as exc:
        raise SvgCharacterError("invalid SVG point list") from exc
    if len(numbers) < 4 or len(numbers) % 2:
        raise SvgCharacterError("SVG point list must contain x/y pairs")
    return tuple((numbers[index], numbers[index + 1]) for index in range(0, len(numbers), 2))


def _curve_point_cubic(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    return (
        u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
        u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    )


def _curve_point_quad(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    u = 1.0 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def _path_subpaths(data: str) -> tuple[tuple[tuple[Point, ...], bool], ...]:
    tokens = _PATH_TOKEN_RE.findall(data)
    if not tokens:
        return ()
    index = 0
    command: str | None = None
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    last_cubic_control: Point | None = None
    last_quad_control: Point | None = None
    points: list[Point] = []
    subpaths: list[tuple[tuple[Point, ...], bool]] = []

    def is_command(token: str) -> bool:
        return len(token) == 1 and token.isalpha()

    def require(count: int) -> list[float]:
        nonlocal index
        if index + count > len(tokens) or any(is_command(token) for token in tokens[index : index + count]):
            raise SvgCharacterError(f"SVG path command {command!r} has too few coordinates")
        values = [float(token) for token in tokens[index : index + count]]
        index += count
        return values

    def absolute(x: float, y: float, relative: bool) -> Point:
        return (current[0] + x, current[1] + y) if relative else (x, y)

    while index < len(tokens):
        if is_command(tokens[index]):
            command = tokens[index]
            index += 1
        elif command is None:
            raise SvgCharacterError("SVG path must begin with a command")
        assert command is not None
        lower = command.casefold()
        relative = command.islower()

        if lower == "z":
            if points:
                subpaths.append((tuple(points), True))
                points = []
            current = start
            last_cubic_control = None
            last_quad_control = None
            command = None
            continue
        if lower == "a":
            raise SvgCharacterError("SVG arc path command A/a is not supported in character format v1")

        if lower == "m":
            x, y = require(2)
            target = absolute(x, y, relative)
            if points:
                subpaths.append((tuple(points), False))
            points = [target]
            current = start = target
            command = "l" if relative else "L"
            last_cubic_control = last_quad_control = None
            continue
        if lower == "l":
            x, y = require(2)
            current = absolute(x, y, relative)
            points.append(current)
            last_cubic_control = last_quad_control = None
            continue
        if lower == "h":
            (x,) = require(1)
            current = (current[0] + x if relative else x, current[1])
            points.append(current)
            last_cubic_control = last_quad_control = None
            continue
        if lower == "v":
            (y,) = require(1)
            current = (current[0], current[1] + y if relative else y)
            points.append(current)
            last_cubic_control = last_quad_control = None
            continue
        if lower == "c":
            x1, y1, x2, y2, x, y = require(6)
            p0 = current
            p1 = absolute(x1, y1, relative)
            p2 = absolute(x2, y2, relative)
            p3 = absolute(x, y, relative)
            points.extend(_curve_point_cubic(p0, p1, p2, p3, step / _CURVE_STEPS) for step in range(1, _CURVE_STEPS + 1))
            current = p3
            last_cubic_control = p2
            last_quad_control = None
            continue
        if lower == "s":
            x2, y2, x, y = require(4)
            p0 = current
            p1 = (
                (2 * p0[0] - last_cubic_control[0], 2 * p0[1] - last_cubic_control[1])
                if last_cubic_control is not None
                else p0
            )
            p2 = absolute(x2, y2, relative)
            p3 = absolute(x, y, relative)
            points.extend(_curve_point_cubic(p0, p1, p2, p3, step / _CURVE_STEPS) for step in range(1, _CURVE_STEPS + 1))
            current = p3
            last_cubic_control = p2
            last_quad_control = None
            continue
        if lower == "q":
            x1, y1, x, y = require(4)
            p0 = current
            p1 = absolute(x1, y1, relative)
            p2 = absolute(x, y, relative)
            points.extend(_curve_point_quad(p0, p1, p2, step / _CURVE_STEPS) for step in range(1, _CURVE_STEPS + 1))
            current = p2
            last_quad_control = p1
            last_cubic_control = None
            continue
        if lower == "t":
            x, y = require(2)
            p0 = current
            p1 = (
                (2 * p0[0] - last_quad_control[0], 2 * p0[1] - last_quad_control[1])
                if last_quad_control is not None
                else p0
            )
            p2 = absolute(x, y, relative)
            points.extend(_curve_point_quad(p0, p1, p2, step / _CURVE_STEPS) for step in range(1, _CURVE_STEPS + 1))
            current = p2
            last_quad_control = p1
            last_cubic_control = None
            continue
        raise SvgCharacterError(f"unsupported SVG path command {command!r}")

    if points:
        subpaths.append((tuple(points), False))
    return tuple(subpaths)


def _element_primitives(element: ET.Element, matrix: Matrix, style: dict[str, str]) -> tuple[VectorPrimitive, ...]:
    tag = _local_name(element.tag)
    fill, stroke, stroke_width = _primitive_style(style)
    if fill is None and stroke is None:
        return ()

    raw_shapes: list[tuple[tuple[Point, ...], bool]] = []
    if tag == "path":
        raw_shapes.extend(_path_subpaths(element.attrib.get("d", "")))
    elif tag == "rect":
        x = _number(element.attrib.get("x", "0"), field="rect x")
        y = _number(element.attrib.get("y", "0"), field="rect y")
        width = _number(element.attrib.get("width"), field="rect width")
        height = _number(element.attrib.get("height"), field="rect height")
        rx = _number(element.attrib.get("rx", "0"), field="rect rx")
        ry = _number(element.attrib.get("ry", str(rx)), field="rect ry")
        raw_shapes.append((_rounded_rect_points(x, y, width, height, rx, ry), True))
    elif tag == "circle":
        cx = _number(element.attrib.get("cx", "0"), field="circle cx")
        cy = _number(element.attrib.get("cy", "0"), field="circle cy")
        radius = _number(element.attrib.get("r"), field="circle r")
        raw_shapes.append((_ellipse_points(cx, cy, radius, radius), True))
    elif tag == "ellipse":
        cx = _number(element.attrib.get("cx", "0"), field="ellipse cx")
        cy = _number(element.attrib.get("cy", "0"), field="ellipse cy")
        rx = _number(element.attrib.get("rx"), field="ellipse rx")
        ry = _number(element.attrib.get("ry"), field="ellipse ry")
        raw_shapes.append((_ellipse_points(cx, cy, rx, ry), True))
    elif tag == "line":
        raw_shapes.append(
            (
                (
                    (_number(element.attrib.get("x1", "0"), field="line x1"), _number(element.attrib.get("y1", "0"), field="line y1")),
                    (_number(element.attrib.get("x2", "0"), field="line x2"), _number(element.attrib.get("y2", "0"), field="line y2")),
                ),
                False,
            )
        )
    elif tag in {"polygon", "polyline"}:
        raw_shapes.append((_points_attribute(element.attrib.get("points", "")), tag == "polygon"))
    else:
        raise SvgCharacterError(f"unsupported artwork element <{tag}> in character format v1")

    primitives = []
    for raw_points, closed in raw_shapes:
        points = tuple(_transform_point(matrix, point) for point in raw_points)
        if len(points) < 2:
            continue
        primitives.append(
            VectorPrimitive(
                points=points,
                closed=closed,
                fill=fill if closed else None,
                stroke=stroke,
                stroke_width=stroke_width,
            )
        )
    return tuple(primitives)


def _part_primitives(
    element: ET.Element,
    parent_matrix: Matrix = _IDENTITY,
    parent_style: dict[str, str] | None = None,
) -> tuple[VectorPrimitive, ...]:
    style = _parse_style(element, parent_style or {})
    if style.get("display", "").casefold() == "none" or style.get("visibility", "").casefold() == "hidden":
        return ()
    matrix = _matrix_multiply(parent_matrix, _parse_transform(element.attrib.get("transform", "")))
    primitives: list[VectorPrimitive] = []
    for child in element:
        tag = _local_name(child.tag)
        if tag in {"g", "svg"}:
            primitives.extend(_part_primitives(child, matrix, style))
        elif tag in {"path", "rect", "circle", "ellipse", "line", "polygon", "polyline"}:
            child_style = _parse_style(child, style)
            if child_style.get("display", "").casefold() == "none" or child_style.get("visibility", "").casefold() == "hidden":
                continue
            child_matrix = _matrix_multiply(matrix, _parse_transform(child.attrib.get("transform", "")))
            primitives.extend(_element_primitives(child, child_matrix, child_style))
        elif tag in {"title", "desc", "metadata"}:
            continue
        else:
            raise SvgCharacterError(f"unsupported artwork element <{tag}> in character format v1")
    return tuple(primitives)


def _validate_safe_svg(root: ET.Element) -> None:
    blocked_tags = {
        "script",
        "foreignObject",
        "image",
        "audio",
        "video",
        "iframe",
        "object",
        "use",
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
            if local_key == "href" and text:
                raise SvgCharacterError("SVG links/resources are not supported")
            lowered = text.casefold().replace(" ", "")
            if "url(" in lowered:
                raise SvgCharacterError("SVG gradients, patterns, and external resources are not supported in character format v1")


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

    missing_parts = sorted(REQUIRED_PARTS - ids.keys())
    if missing_parts:
        raise SvgCharacterError("missing artwork groups: " + ", ".join(missing_parts))

    anchors: dict[str, Point] = {}
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

    parts: dict[str, VectorPart] = {}
    for part_name in ALL_PARTS:
        element = ids.get(part_name)
        if element is None:
            continue
        primitives = _part_primitives(element)
        if part_name in REQUIRED_PARTS and not primitives:
            raise SvgCharacterError(f"artwork group {part_name!r} is empty")
        parts[part_name] = VectorPart(primitives)

    name = root.attrib.get("data-vaporstep-name", "").strip() or path.stem
    return SvgCharacterDefinition(
        path=path,
        name=name,
        view_box=_view_box(root),
        anchors=anchors,
        parts=parts,
    )


def ensure_reference_character(directory: Path | None = None) -> Path | None:
    directory = Path(directory) if directory is not None else characters_dir()
    destination = directory / REFERENCE_FILENAME
    if destination.exists():
        return destination
    source = resource_path(Path("assets") / "characters" / REFERENCE_FILENAME)
    if not source.is_file():
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    except OSError as exc:
        print(f"VaporStep: could not install reference character: {exc}", file=sys.stderr)
        return None
    return destination


def discover_character_files(directory: Path | None = None) -> tuple[Path, ...]:
    directory = Path(directory) if directory is not None else characters_dir()
    try:
        files = [path for path in directory.iterdir() if path.is_file() and path.suffix.casefold() == ".svg"]
    except OSError:
        return ()
    return tuple(sorted(files, key=lambda path: path.name.casefold()))


_active_character_filename: str | None = None


def active_character_filename() -> str | None:
    return _active_character_filename


def set_active_character_filename(filename: str | None) -> None:
    global _active_character_filename
    _active_character_filename = filename


def cycle_player_visual(value: object, directory: Path | None = None) -> str:
    """Cycle silhouette -> built-in -> each SVG -> silhouette.

    player_visual remains the existing two-value setting. The selected custom
    file is session state, so the camera/mask code keeps its existing fast path.
    """

    global _active_character_filename
    visual = str(value or "").strip().casefold()
    if visual == "silhouette":
        _active_character_filename = None
        return "character"

    files = discover_character_files(directory)
    names = [path.name for path in files]
    if _active_character_filename is None:
        if names:
            _active_character_filename = names[0]
            return "character"
        return "silhouette"
    try:
        index = names.index(_active_character_filename)
    except ValueError:
        _active_character_filename = None
        return "silhouette"
    if index + 1 < len(names):
        _active_character_filename = names[index + 1]
        return "character"
    _active_character_filename = None
    return "silhouette"


def active_character_label() -> str:
    if _active_character_filename is None:
        return "CHARACTER"
    path = characters_dir() / _active_character_filename
    try:
        return parse_svg_character(path).name.upper()
    except SvgCharacterError:
        return path.stem.upper()


def _display_color(color: Color) -> tuple[int, int, int]:
    r, g, b, alpha = color
    if alpha >= 255:
        return (r, g, b)
    amount = alpha / 255.0
    return (
        int(BG[0] + (r - BG[0]) * amount),
        int(BG[1] + (g - BG[1]) * amount),
        int(BG[2] + (b - BG[2]) * amount),
    )


def _draw_vector_part(
    screen: pygame.Surface,
    part: VectorPart,
    mapper,
    stroke_scale: float,
) -> None:
    for primitive in part.primitives:
        mapped = [mapper(point) for point in primitive.points]
        if any(not math.isfinite(value) for point in mapped for value in point):
            continue
        points = [(int(round(x)), int(round(y))) for x, y in mapped]
        if primitive.closed and primitive.fill is not None and len(points) >= 3:
            pygame.draw.polygon(screen, _display_color(primitive.fill), points)
        if primitive.stroke is not None and len(points) >= 2:
            width = max(1, int(round(primitive.stroke_width * stroke_scale)))
            pygame.draw.lines(
                screen,
                _display_color(primitive.stroke),
                primitive.closed,
                points,
                width,
            )


def _unit_torso_part(part: VectorPart, source_quad: tuple[Point, Point, Point, Point]) -> VectorPart:
    source = np.asarray(source_quad, dtype=np.float32)
    target = np.asarray(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, target)
    primitives = []
    for primitive in part.primitives:
        points = np.asarray([primitive.points], dtype=np.float32)
        transformed = cv2.perspectiveTransform(points, matrix)[0]
        primitives.append(
            VectorPrimitive(
                points=tuple((float(point[0]), float(point[1])) for point in transformed),
                closed=primitive.closed,
                fill=primitive.fill,
                stroke=primitive.stroke,
                stroke_width=primitive.stroke_width,
            )
        )
    return VectorPart(tuple(primitives))


class SvgCharacter:
    def __init__(self, definition: SvgCharacterDefinition) -> None:
        self.definition = definition
        self._view_width = definition.view_box[2]
        source_quad = (
            definition.anchors["left-shoulder"],
            definition.anchors["right-shoulder"],
            definition.anchors["right-hip"],
            definition.anchors["left-hip"],
        )
        self._torso = _unit_torso_part(definition.parts["torso"], source_quad)

    @classmethod
    def from_file(cls, path: Path) -> "SvgCharacter":
        return cls(parse_svg_character(path))

    def _draw_bone(
        self,
        renderer: CachedCharacterRenderer,
        part_name: str,
        live_a: tuple[int, int] | None,
        live_b: tuple[int, int] | None,
    ) -> None:
        if live_a is None or live_b is None:
            return
        part = self.definition.parts.get(part_name)
        if part is None:
            return
        anchor_a_name, anchor_b_name = BONE_PARTS[part_name]
        source_a = self.definition.anchors[anchor_a_name]
        source_b = self.definition.anchors[anchor_b_name]
        source_dx = source_b[0] - source_a[0]
        source_dy = source_b[1] - source_a[1]
        source_length = math.hypot(source_dx, source_dy)
        live_dx = live_b[0] - live_a[0]
        live_dy = live_b[1] - live_a[1]
        live_length = math.hypot(live_dx, live_dy)
        if source_length < 1e-6 or live_length < 1e-6:
            return
        su = (source_dx / source_length, source_dy / source_length)
        sv = (-su[1], su[0])
        lu = (live_dx / live_length, live_dy / live_length)
        lv = (-lu[1], lu[0])
        viewport_width = float(renderer._camera_rect().width)
        stroke_scale = viewport_width / self._view_width

        def mapper(point: Point) -> Point:
            rel = (point[0] - source_a[0], point[1] - source_a[1])
            along = (rel[0] * su[0] + rel[1] * su[1]) / source_length
            across = (rel[0] * sv[0] + rel[1] * sv[1]) / self._view_width
            return (
                live_a[0] + lu[0] * along * live_length + lv[0] * across * viewport_width,
                live_a[1] + lu[1] * along * live_length + lv[1] * across * viewport_width,
            )

        _draw_vector_part(renderer.screen, part, mapper, stroke_scale)

    def _draw_point_part(
        self,
        renderer: CachedCharacterRenderer,
        part_name: str,
        live_anchor: tuple[int, int] | None,
    ) -> None:
        if live_anchor is None:
            return
        part = self.definition.parts.get(part_name)
        if part is None:
            return
        source_anchor = self.definition.anchors[POINT_PARTS[part_name]]
        scale = float(renderer._camera_rect().width) / self._view_width

        def mapper(point: Point) -> Point:
            return (
                live_anchor[0] + (point[0] - source_anchor[0]) * scale,
                live_anchor[1] + (point[1] - source_anchor[1]) * scale,
            )

        _draw_vector_part(renderer.screen, part, mapper, scale)

    def _draw_head(self, renderer: CachedCharacterRenderer, figure: PoseFigure) -> None:
        geometry = renderer._head_geometry(figure)
        if geometry is None:
            return
        center, radius = geometry
        left = self.definition.anchors["left-ear"]
        right = self.definition.anchors["right-ear"]
        source_mid = ((left[0] + right[0]) * 0.5, (left[1] + right[1]) * 0.5)
        source_span = max(1e-6, math.dist(left, right))
        # Built-in head radius is 0.70 * ear span. Use the same live geometry,
        # including its nose/shoulder fallbacks, but leave the artwork upright.
        target_span = radius / 0.70
        scale = target_span / source_span

        def mapper(point: Point) -> Point:
            return (
                center[0] + (point[0] - source_mid[0]) * scale,
                center[1] + (point[1] - source_mid[1]) * scale,
            )

        _draw_vector_part(renderer.screen, self.definition.parts["head"], mapper, scale)

    def _live_torso_quad(
        self,
        renderer: CachedCharacterRenderer,
        figure: PoseFigure,
    ) -> tuple[Point, Point, Point, Point] | None:
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
            (ls[0] + shoulder_dx * shoulder_inset, ls[1] + shoulder_dy * shoulder_inset),
            (rs[0] - shoulder_dx * shoulder_inset, rs[1] - shoulder_dy * shoulder_inset),
            (rh[0] + hip_pad, rh[1] + scale * 0.010),
            (lh[0] - hip_pad, lh[1] + scale * 0.010),
        )

    def _draw_torso(self, renderer: CachedCharacterRenderer, figure: PoseFigure) -> None:
        quad = self._live_torso_quad(renderer, figure)
        if quad is None:
            return
        q0, q1, q2, q3 = quad
        scale = float(renderer._camera_rect().width) / self._view_width

        def mapper(point: Point) -> Point:
            u, v = point
            top = ((1.0 - u) * q0[0] + u * q1[0], (1.0 - u) * q0[1] + u * q1[1])
            bottom = ((1.0 - u) * q3[0] + u * q2[0], (1.0 - u) * q3[1] + u * q2[1])
            return ((1.0 - v) * top[0] + v * bottom[0], (1.0 - v) * top[1] + v * bottom[1])

        _draw_vector_part(renderer.screen, self._torso, mapper, scale)

    def draw(self, renderer: CachedCharacterRenderer, figure: PoseFigure) -> None:
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
    """Cached gameplay renderer with optional user-authored vector characters."""

    def __init__(self, screen: pygame.Surface) -> None:
        ensure_reference_character()
        super().__init__(screen)
        self._loaded_character_filename: str | None = None
        self._svg_character: SvgCharacter | None = None
        self._svg_character_error: str | None = None

    def _refresh_custom_character(self) -> None:
        desired = active_character_filename()
        if desired == self._loaded_character_filename:
            return
        self._loaded_character_filename = desired
        self._svg_character = None
        self._svg_character_error = None
        if desired is None:
            return
        path = characters_dir() / desired
        try:
            self._svg_character = SvgCharacter.from_file(path)
        except SvgCharacterError as exc:
            self._svg_character_error = str(exc)
            print(
                f"VaporStep: could not load custom character {path.name}: {exc}; using built-in character",
                file=sys.stderr,
            )

    def _draw_pose_figure(self, figure: PoseFigure) -> None:
        self._refresh_custom_character()
        if self._svg_character is not None:
            try:
                self._svg_character.draw(self, figure)
                return
            except Exception as exc:
                self._svg_character_error = str(exc)
                self._svg_character = None
                print(
                    f"VaporStep: custom character rendering failed: {exc}; using built-in character",
                    file=sys.stderr,
                )
        super()._draw_pose_figure(figure)
