from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from vaporstep.svg_character_runtime import (
    REQUIRED_ANCHORS,
    REQUIRED_PARTS,
    SvgCharacter,
    SvgCharacterError,
    parse_svg_character,
    select_custom_character_file,
)


REFERENCE = Path(__file__).parents[1] / "docs" / "characters" / "reference-robot.svg"


def test_reference_robot_matches_v1_schema() -> None:
    definition = parse_svg_character(REFERENCE)

    assert definition.name == "Reference Robot"
    assert REQUIRED_PARTS <= definition.parts.keys()
    assert REQUIRED_ANCHORS <= definition.anchors.keys()


def test_reference_robot_rasterizes_through_runtime_loader() -> None:
    pygame.init()
    character = SvgCharacter.from_file(REFERENCE)

    assert character.definition.name == "Reference Robot"


def test_single_svg_is_selected_and_multiple_require_active(tmp_path: Path) -> None:
    robot = tmp_path / "robot.svg"
    robot.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    assert select_custom_character_file(tmp_path) == robot

    other = tmp_path / "other.svg"
    other.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    assert select_custom_character_file(tmp_path) is None

    active = tmp_path / "active.svg"
    active.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    assert select_custom_character_file(tmp_path) == active


def test_parser_rejects_external_resources(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-vaporstep-version="1" '
        'viewBox="0 0 10 10"><image href="https://example.com/a.png"/></svg>',
        encoding="utf-8",
    )

    with pytest.raises(SvgCharacterError, match="unsupported SVG element"):
        parse_svg_character(path)


def test_parser_reports_missing_rig_parts(tmp_path: Path) -> None:
    path = tmp_path / "empty.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-vaporstep-version="1" '
        'viewBox="0 0 10 10"/>',
        encoding="utf-8",
    )

    with pytest.raises(SvgCharacterError, match="missing artwork groups"):
        parse_svg_character(path)
