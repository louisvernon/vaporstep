from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from vaporstep.domain import (
    BodyPoint,
    BodyState,
    ChainMode,
    ChainState,
    GameNote,
    HitQuality,
    ImplicitChain,
    NoteKind,
    PoseFigure,
    RuntimeChain,
    SustainSource,
)
from vaporstep.font_support import MetadataFont
from vaporstep.scoring import RunStats


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


def test_renderer_reuses_unicode_metadata_fonts_for_gameplay_song_titles(monkeypatch) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    small = renderer._song_metadata_font(21)
    assert isinstance(small, MetadataFont)
    assert renderer._song_metadata_font(21) is small

    rendered_titles = []

    def render_title(text, antialias, color, background=None):
        rendered_titles.append(text)
        return pygame.Surface((80, 20), pygame.SRCALPHA)

    monkeypatch.setattr(small, "render", render_title)

    renderer._draw_status("READY", "CAMERA", "星空記憶", "HARD  9", None)

    assert rendered_titles == ["星空記憶"]


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


def test_failed_hold_keeps_failed_hud_instead_of_intro_metadata(monkeypatch) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    hud_calls = []
    status_calls = []
    monkeypatch.setattr(renderer, "_draw_hud", lambda *args, **kwargs: hud_calls.append(args))
    monkeypatch.setattr(
        renderer,
        "_draw_status",
        lambda *args, **kwargs: status_calls.append(args),
    )

    renderer.draw(
        body=BodyState(),
        mask=None,
        notes=[],
        song_time=1.0,
        song_beat=1.0,
        status="READY",
        debug=False,
        pose_fps=0.0,
        input_name="webcam",
        song_title="SONG TITLE",
        chart_label="HARD 9",
        stats=RunStats(total_notes=10),
        running=False,
        performance_state="failed",
    )

    assert len(hud_calls) == 1
    assert status_calls == []


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


def test_renderer_connects_heads_from_one_paired_hand_note(monkeypatch) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    connectors = []

    def record_connector(lanes, progress, color, song_time, beat_pulse, downbeat):
        connectors.append((lanes, progress, color, song_time, beat_pulse, downbeat))

    monkeypatch.setattr(renderer, "_draw_hand_note_connector", record_connector)
    renderer._draw_notes(
        [GameNote(time=1.0, beat=1.0, lanes=(1, 3), kind=NoteKind.HANDS)],
        song_time=0.5,
        song_beat=0.5,
        chain_mode=ChainMode.OFF,
        beat_pulse=0.75,
        downbeat=True,
    )

    assert len(connectors) == 1
    assert connectors[0][0] == (1, 3)
    assert connectors[0][4:] == (0.75, True)


def test_renderer_does_not_connect_paired_foot_note(monkeypatch) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    connectors = []
    monkeypatch.setattr(
        renderer,
        "_draw_hand_note_connector",
        lambda *args: connectors.append(args),
    )

    renderer._draw_notes(
        [GameNote(time=1.0, beat=1.0, lanes=(1, 3), kind=NoteKind.FOOT)],
        song_time=0.5,
        song_beat=0.5,
        chain_mode=ChainMode.OFF,
    )

    assert connectors == []


@pytest.mark.parametrize("state", [ChainState.PENDING, ChainState.ACTIVE])
def test_renderer_connects_paired_hand_hold_head(monkeypatch, state) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    connectors = []
    monkeypatch.setattr(
        renderer,
        "_draw_hand_note_connector",
        lambda *args: connectors.append(args),
    )
    hold = GameNote(
        time=1.0,
        beat=1.0,
        end_time=2.0,
        end_beat=2.0,
        lanes=(1, 3),
        kind=NoteKind.HANDS,
        chain_id=7,
    )
    preceding_note = GameNote(
        time=0.5,
        beat=0.5,
        lanes=(2,),
        kind=NoteKind.HANDS,
    )
    chain = RuntimeChain(
        definition=ImplicitChain(
            id=7,
            kind=NoteKind.HANDS,
            lanes=(1, 3),
            note_indices=(0,),
            start_time=1.0,
            end_time=2.0,
            start_beat=1.0,
            end_beat=2.0,
            source=SustainSource.EXPLICIT_HOLD,
        ),
        state=state,
    )

    renderer._draw_chains(
        (chain,),
        [preceding_note, hold],
        song_time=1.0 if state == ChainState.ACTIVE else 0.5,
        song_beat=1.0 if state == ChainState.ACTIVE else 0.5,
        chain_mode=ChainMode.OFF,
        beat_pulse=0.75,
        downbeat=True,
    )

    assert len(connectors) == 1
    assert connectors[0][0] == (1, 3)
    assert connectors[0][2] == renderer_module.HAND_PURPLE
    assert connectors[0][4:] == (0.75, True)


def test_active_hand_hold_keeps_color_when_head_note_leaves_render_window(monkeypatch) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    connectors = []
    monkeypatch.setattr(
        renderer,
        "_draw_hand_note_connector",
        lambda *args: connectors.append(args),
    )
    chain = RuntimeChain(
        definition=ImplicitChain(
            id=9,
            kind=NoteKind.HANDS,
            lanes=(1, 4),
            note_indices=(0,),
            start_time=1.0,
            end_time=10.0,
            start_beat=2.0,
            end_beat=20.0,
            source=SustainSource.EXPLICIT_HOLD,
        ),
        state=ChainState.ACTIVE,
        visual_ordinal=1,
    )

    renderer._draw_chains(
        (chain,),
        [],
        song_time=5.0,
        song_beat=10.0,
        chain_mode=ChainMode.OFF,
    )

    assert connectors
    assert connectors[0][2] == renderer_module.HAND_PURPLE


def test_hand_note_connector_ignores_single_lane_notes() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    before = pygame.image.tostring(screen, "RGBA")

    renderer._draw_hand_note_connector(
        (2,),
        0.5,
        renderer_module.MAGENTA,
        0.0,
        1.0,
        False,
    )

    assert pygame.image.tostring(screen, "RGBA") == before


def test_note_breath_is_slow_and_anchored_to_its_target_time() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    note = GameNote(time=10.0, lanes=(1,), kind=NoteKind.HANDS)

    assert renderer._note_breathe(note, 10.0) == pytest.approx(1.0)
    assert renderer._note_breathe(note, 9.6) == pytest.approx(0.5)
    assert renderer._note_breathe(note, 9.2) == pytest.approx(0.0)


def test_note_breath_has_a_clearly_visible_brightness_range() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    trough = renderer._breathing_note_color(renderer_module.MAGENTA, 0.0, 0.25)
    peak = renderer._breathing_note_color(renderer_module.MAGENTA, 1.0, 0.25)

    assert sum(peak) > sum(trough) * 1.8


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


def test_static_playfield_caches_are_reused_and_size_scoped() -> None:
    pygame.font.init()
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(pygame.Surface((1280, 720)))

    band = renderer._hand_depth_band(0.0, 0.125)
    depth_surface = renderer._hand_depth_surface()
    gutter_surface = renderer._floor_gutter_fill_surface()
    assert renderer._hand_depth_band(0.0, 0.125) is band
    assert renderer._hand_depth_surface() is depth_surface
    assert renderer._floor_gutter_fill_surface() is gutter_surface

    renderer.replace_screen(pygame.Surface((1024, 600)))
    assert renderer._hand_depth_band(0.0, 0.125) is not band
    assert renderer._hand_depth_surface() is not depth_surface
    assert renderer._floor_gutter_fill_surface() is not gutter_surface


def test_playfield_key_labels_are_rendered_once() -> None:
    pygame.font.init()
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(pygame.Surface((1280, 720)))
    base_font = renderer.small_font
    rendered = []

    class CountingFont:
        def render(self, *args, **kwargs):
            rendered.append(args[0])
            return base_font.render(*args, **kwargs)

    renderer.small_font = CountingFont()
    renderer._draw_key_labels(hand_enabled=True, foot_enabled=True)
    renderer._draw_key_labels(hand_enabled=True, foot_enabled=True)

    assert len(rendered) == 8


def test_silhouette_processing_uses_cropped_mask_resolution(monkeypatch) -> None:
    pygame.font.init()
    renderer_module = importlib.import_module("vaporstep.renderer")
    base_module = importlib.import_module("vaporstep.renderer_base")
    renderer = renderer_module.Renderer(pygame.Surface((1280, 720)))
    processed_shapes = []

    def fake_canny(binary, _low, _high):
        processed_shapes.append(binary.shape)
        return np.zeros_like(binary)

    monkeypatch.setattr(base_module.cv2, "Canny", fake_canny)
    renderer._draw_silhouette(np.zeros((480, 640), dtype=np.float32))

    expected_width = round(640 / renderer.player_horizontal_zoom)
    assert processed_shapes == [(480, expected_width)]
    assert renderer._silhouette_surface is not None
    assert renderer._silhouette_surface.get_size() == renderer._camera_rect().size


def test_primitive_pose_figure_draws_from_landmarks_without_a_mask() -> None:
    pygame.font.init()
    renderer_module = importlib.import_module("vaporstep.renderer")
    screen = pygame.Surface((1280, 720))
    renderer = renderer_module.Renderer(screen)
    screen.fill((2, 2, 8))
    landmarks = [BodyPoint() for _ in range(33)]
    coordinates = {
        0: (0.50, 0.13),
        7: (0.47, 0.15),
        8: (0.53, 0.15),
        11: (0.42, 0.27),
        12: (0.58, 0.27),
        13: (0.36, 0.42),
        14: (0.64, 0.42),
        15: (0.31, 0.57),
        16: (0.69, 0.57),
        23: (0.45, 0.53),
        24: (0.55, 0.53),
        25: (0.43, 0.72),
        26: (0.57, 0.72),
        27: (0.41, 0.91),
        28: (0.59, 0.91),
    }
    for index, (x, y) in coordinates.items():
        landmarks[index] = BodyPoint(x=x, y=y, visible=True)

    renderer._draw_pose_figure(PoseFigure(tuple(landmarks)))

    pixels = pygame.surfarray.array3d(screen)
    assert np.any(pixels != np.array((2, 2, 8), dtype=np.uint8))


def test_preentry_glows_are_centered_on_the_entry_boundaries() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    inner, _, _ = renderer._hand_tunnel_geometry()
    cx, base_y, rx, ry = inner

    for kind in (NoteKind.HANDS, NoteKind.FOOT):
        for lane in range(1, 5):
            points = renderer._preentry_glow_arc(kind, lane)
            assert len(points) == 13

            if kind == NoteKind.HANDS:
                assert len({y for _, y in points}) > 1
                assert all(
                    0.95
                    < ((x - cx) / rx) ** 2 + ((y - base_y) / ry) ** 2
                    < 1.05
                    for x, y in points
                )
            else:
                entry_y = int(renderer._field_y(NoteKind.FOOT, 0.0))
                assert {y for _, y in points} == {entry_y}


def test_preentry_glow_brightens_smoothly_toward_entry() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    brightness = [
        renderer._preentry_brightness(distance, 1.0)
        for distance in (1.0, 0.75, 0.50, 0.25, 0.0)
    ]
    assert brightness[0] == 0.0
    assert brightness[-1] == 1.0
    assert all(a < b for a, b in zip(brightness, brightness[1:]))


def test_preentry_glow_is_a_broad_bright_bloom_without_a_hard_core() -> None:
    pygame.font.init()
    renderer_module = importlib.import_module("vaporstep.renderer")
    surface = pygame.Surface((200, 200))
    renderer = renderer_module.Renderer(surface)

    renderer._draw_preentry_glow(
        surface,
        [(60, 100), (140, 100)],
        renderer_module.MAGENTA,
        1.0,
    )

    center = surface.get_at((100, 100)).r
    inner_haze = surface.get_at((100, 107)).r
    outer_haze = surface.get_at((100, 117)).r
    beyond_glow = surface.get_at((100, 130)).r

    assert center > 75
    assert center > inner_haze > outer_haze > 0
    assert beyond_glow == 0


def test_hand_note_colors_alternate_by_event() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    assert renderer._hand_note_color(0) == renderer_module.MAGENTA
    assert renderer._hand_note_color(1) == renderer_module.HAND_PURPLE
    assert renderer._hand_note_color(2) == renderer_module.MAGENTA
    assert sum(renderer_module.HAND_PURPLE) > sum(renderer_module.PURPLE)


def test_abandoned_hold_fades_across_grace_period() -> None:
    renderer_module = importlib.import_module("vaporstep.renderer")
    chain = RuntimeChain(
        definition=ImplicitChain(
            id=1,
            kind=NoteKind.HANDS,
            lanes=(2, 3),
            note_indices=(0,),
            start_time=0.0,
            end_time=2.0,
            start_beat=0.0,
            end_beat=4.0,
        ),
        state=ChainState.ACTIVE,
        last_occupancy_at=1.0,
    )

    assert renderer_module.Renderer._sustain_presence(chain, 1.0) == 1.0
    assert renderer_module.Renderer._sustain_presence(chain, 1.25) == pytest.approx(0.5)
    assert renderer_module.Renderer._sustain_presence(chain, 1.5) == 0.0


def test_prestart_hand_guide_highlights_upper_channels(monkeypatch) -> None:
    pygame.font.init()
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(pygame.Surface((1280, 720)))
    colors = []
    original = pygame.draw.lines

    def capture(surface, color, closed, points, width=1):
        colors.append(color)
        return original(surface, color, closed, points, width)

    monkeypatch.setattr(pygame.draw, "lines", capture)
    renderer._draw_hand_receptor_feedback(
        BodyState(),
        [],
        0.0,
        True,
        (),
        show_start_hand_guide=True,
    )

    assert colors.count(renderer_module.GREEN) == 2


def test_note_glow_converges_smoothly_into_target() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    separations = []
    for progress in (0.0, 0.25, 0.50, 0.75, 1.0):
        body, reflection = renderer._glow_projection_progress(progress)
        separations.append(reflection - body)

    assert all(a > b for a, b in zip(separations, separations[1:]))
    assert separations[-1] == 0.0


def test_keyboard_mode_can_suppress_body_markers() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)
    marker_calls = 0

    def counted_markers(*args, **kwargs):
        nonlocal marker_calls
        marker_calls += 1

    renderer._draw_body_markers = counted_markers
    renderer.draw(
        body=BodyState(),
        mask=None,
        notes=[],
        song_time=0.0,
        song_beat=0.0,
        status="KEYBOARD ONLY",
        debug=False,
        pose_fps=0.0,
        input_name="keyboard",
        show_body_markers=False,
    )

    assert marker_calls == 0
