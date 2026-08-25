from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pygame

from vaporstep.domain import (
    ChainMode,
    GameNote,
    HitQuality,
    ImplicitChain,
    NoteKind,
    RuntimeChain,
    SustainSource,
)


def test_renderer_module_imports() -> None:
    module = importlib.import_module("vaporstep.renderer")
    assert module.Renderer is not None


def test_renderer_public_ui_exports() -> None:
    module = importlib.import_module("vaporstep.renderer")
    for name in (
        "BG",
        "CYAN",
        "DIM",
        "GRID",
        "MAGENTA",
        "PURPLE",
        "RED",
        "WHITE",
        "_blend",
    ):
        assert hasattr(module, name)


def test_song_menu_module_imports_with_renderer() -> None:
    renderer_module = importlib.import_module("vaporstep.renderer")
    menu_module = importlib.import_module("vaporstep.menu")
    song_menu_renderer = importlib.import_module("vaporstep.song_menu_renderer")
    assert renderer_module.Renderer is not None
    assert menu_module.SongMenu is not None
    assert song_menu_renderer.install_song_menu_renderer is not None


def test_renderer_prototype_layers_and_compatibility_hacks_are_gone() -> None:
    module = importlib.import_module("vaporstep.renderer")
    base_module = importlib.import_module("vaporstep.renderer_base")
    source_path = Path(module.__file__)
    source = source_path.read_text(encoding="utf-8")

    assert module.Renderer.__bases__ == (base_module.Renderer,)
    for removed in ("renderer_previous", "renderer_tunnel_base"):
        assert removed not in source
        assert not source_path.with_name(f"{removed}.py").exists()

    assert "_suppress_legacy_hands" not in source
    assert "_ReceptorLabelFilter" not in source
    assert "super()._draw_notes" not in source
    assert "super()._draw_chains" not in source
    assert "super()._spawn_note_effects" not in source
    assert "super()._draw_particles" not in source
    assert "super()._draw_body_markers" not in source


def test_renderer_constructs_and_draws_startup_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    renderer.draw_startup_splash("TEST")

    assert screen.get_size() == (1280, 720)


def test_renderer_draws_gameplay_surfaces_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    hidden_control = SimpleNamespace(visible=False, x=0.5, y=0.5)
    body = SimpleNamespace(
        foot_lanes=frozenset({1, 3}),
        hand_lanes=frozenset({2, 4}),
        left_foot_control=hidden_control,
        right_foot_control=hidden_control,
    )

    renderer._draw_playfields(
        body,
        song_time=0.0,
        beat_pulse=0.5,
        downbeat=False,
        hand_enabled=True,
        foot_enabled=True,
    )
    renderer._draw_receptors(
        body,
        notes=[],
        song_time=0.0,
        hand_enabled=True,
        foot_enabled=True,
        strike_events=(),
    )

    assert screen.get_size() == (1280, 720)


def test_renderer_draws_explicit_foot_notes_and_chains_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    note = GameNote(
        time=1.0,
        beat=1.0,
        lanes=(2,),
        kind=NoteKind.FOOT,
    )
    hold_note = GameNote(
        time=1.0,
        beat=1.0,
        end_time=2.0,
        end_beat=2.0,
        lanes=(3,),
        kind=NoteKind.FOOT,
        chain_id=7,
    )
    chain = RuntimeChain(
        definition=ImplicitChain(
            id=7,
            kind=NoteKind.FOOT,
            lanes=(3,),
            note_indices=(1,),
            start_time=1.0,
            end_time=2.0,
            start_beat=1.0,
            end_beat=2.0,
            source=SustainSource.EXPLICIT_HOLD,
        )
    )

    renderer._draw_notes(
        [note, hold_note],
        song_time=0.5,
        song_beat=0.5,
        chain_mode=ChainMode.OFF,
    )
    renderer._draw_chains(
        (chain,),
        [note, hold_note],
        song_time=0.5,
        song_beat=0.5,
        chain_mode=ChainMode.OFF,
    )

    assert screen.get_size() == (1280, 720)


def test_renderer_generates_and_draws_mixed_effects_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    notes = [
        GameNote(
            time=1.0,
            lanes=(1,),
            kind=NoteKind.FOOT,
            judged=True,
            hit=True,
            judged_at=1.0,
            judgement=HitQuality.PERFECT,
        ),
        GameNote(
            time=1.0,
            lanes=(2,),
            kind=NoteKind.HANDS,
            judged=True,
            hit=True,
            judged_at=1.0,
            judgement=HitQuality.GREAT,
        ),
        GameNote(
            time=1.0,
            lanes=(3,),
            kind=NoteKind.FOOT,
            judged=True,
            hit=False,
            judged_at=1.0,
        ),
        GameNote(
            time=1.0,
            lanes=(4,),
            kind=NoteKind.HANDS,
            judged=True,
            hit=False,
            judged_at=1.0,
        ),
    ]

    renderer._spawn_note_effects(notes)
    assert {x["kind"] for x in renderer._impact_bursts} == {
        NoteKind.FOOT,
        NoteKind.HANDS,
    }
    assert {x["kind"] for x in renderer._miss_impacts} == {
        NoteKind.FOOT,
        NoteKind.HANDS,
    }

    renderer._draw_particles(song_time=1.05)

    assert screen.get_size() == (1280, 720)


def test_hand_arc_reuses_cached_tunnel_geometry() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    renderer.__dict__.pop("_hand_geometry_cache", None)

    original = renderer._hand_arc_geometry
    calls = 0

    def counted_geometry():
        nonlocal calls
        calls += 1
        return original()

    renderer._hand_arc_geometry = counted_geometry
    renderer._hand_arc_points(0.0, 1.0, 0.5, samples=64)
    renderer._hand_arc_points(0.0, 1.0, 0.75, samples=64)

    assert calls == 1


def test_preentry_cues_are_inside_tunnel_aperture() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    inner, _, _ = renderer._hand_tunnel_geometry()
    cx, base_y, rx, ry = inner

    for kind in (NoteKind.HANDS, NoteKind.FOOT):
        for lane in range(1, 5):
            points, _ = renderer._aperture_target_points(kind, lane)
            assert points
            for x, y in points:
                normalized = ((x - cx) / rx) ** 2 + ((y - base_y) / ry) ** 2
                assert normalized < 0.95
                assert y <= base_y
