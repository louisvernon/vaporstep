from __future__ import annotations

from pathlib import Path

import pytest

from vaporstep.svg_character_renderer import (
    REQUIRED_ANCHORS,
    REQUIRED_PARTS,
    SvgCharacter,
    SvgCharacterError,
    active_character_filename,
    cycle_player_visual,
    discover_character_files,
    ensure_reference_character,
    parse_svg_character,
    set_active_character_filename,
)


REFERENCE = Path(__file__).parents[1] / "assets" / "characters" / "reference-robot.svg"


def test_reference_robot_matches_v1_schema_and_keeps_vector_primitives() -> None:
    definition = parse_svg_character(REFERENCE)

    assert definition.name == "Reference Robot"
    assert REQUIRED_PARTS <= definition.parts.keys()
    assert REQUIRED_ANCHORS <= definition.anchors.keys()
    assert all(part.primitives for name, part in definition.parts.items() if name in REQUIRED_PARTS)
    assert all(
        primitive.points
        for part in definition.parts.values()
        for primitive in part.primitives
    )


def test_reference_robot_builds_vector_character() -> None:
    character = SvgCharacter.from_file(REFERENCE)

    assert character.definition.name == "Reference Robot"
    assert character.definition.parts["torso"].primitives


def test_reference_robot_is_installed_once_without_overwriting(tmp_path: Path) -> None:
    installed = ensure_reference_character(tmp_path)

    assert installed == tmp_path / "reference-robot.svg"
    assert installed.read_text(encoding="utf-8") == REFERENCE.read_text(encoding="utf-8")

    installed.write_text("user-edited", encoding="utf-8")
    assert ensure_reference_character(tmp_path) == installed
    assert installed.read_text(encoding="utf-8") == "user-edited"


def test_character_cycle_walks_builtin_then_sorted_svgs_then_silhouette(tmp_path: Path) -> None:
    set_active_character_filename(None)
    try:
        for name in ("zebra.svg", "alpha.svg"):
            (tmp_path / name).write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")

        assert [path.name for path in discover_character_files(tmp_path)] == ["alpha.svg", "zebra.svg"]

        # Silhouette -> built-in character.
        assert cycle_player_visual("silhouette", tmp_path) == "character"
        assert active_character_filename() is None

        # Built-in -> each user SVG alphabetically.
        assert cycle_player_visual("character", tmp_path) == "character"
        assert active_character_filename() == "alpha.svg"
        assert cycle_player_visual("character", tmp_path) == "character"
        assert active_character_filename() == "zebra.svg"

        # Final SVG -> silhouette, ready to begin the cycle again.
        assert cycle_player_visual("character", tmp_path) == "silhouette"
        assert active_character_filename() is None
    finally:
        set_active_character_filename(None)


def test_cycle_without_custom_files_preserves_existing_binary_toggle(tmp_path: Path) -> None:
    set_active_character_filename(None)
    try:
        assert cycle_player_visual("silhouette", tmp_path) == "character"
        assert cycle_player_visual("character", tmp_path) == "silhouette"
    finally:
        set_active_character_filename(None)


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


def test_parser_rejects_unsupported_vector_features(tmp_path: Path) -> None:
    text = REFERENCE.read_text(encoding="utf-8").replace(
        'fill="#176b83"',
        'fill="url(#gradient)"',
        1,
    )
    path = tmp_path / "gradient.svg"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SvgCharacterError, match="gradients"):
        parse_svg_character(path)
