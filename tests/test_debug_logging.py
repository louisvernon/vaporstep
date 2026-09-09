from __future__ import annotations

import time

import pygame

from vaporstep.calibration_renderer import Renderer
from vaporstep.camera_samples import (
    clear_capture_bodies,
    drain_capture_bodies,
    publish_capture_body,
)
from vaporstep.debug_state import debug_enabled, set_debug_enabled
from vaporstep.domain import BodyState, HitQuality
from vaporstep.motion import MotionTracker
from vaporstep.scoring import RunStats


def _draw(renderer: Renderer, *, debug: bool) -> None:
    renderer.draw(
        body=BodyState(),
        mask=None,
        notes=[],
        song_time=0.0,
        song_beat=0.0,
        status="TEST",
        debug=debug,
        pose_fps=0.0,
        input_name="test",
    )


def test_renderer_publishes_f3_as_runtime_debug_state() -> None:
    pygame.font.init()
    renderer = Renderer(pygame.Surface((640, 360), depth=32))

    _draw(renderer, debug=True)
    assert debug_enabled() is True

    _draw(renderer, debug=False)
    assert debug_enabled() is False


def test_buffered_pose_logs_only_when_it_directly_scores_a_hit(capsys) -> None:
    clear_capture_bodies()
    set_debug_enabled(True)
    tracker = MotionTracker()
    stats = RunStats(total_notes=2)
    now = time.monotonic()
    older = BodyState(timestamp=now - 0.050, timestamp_is_capture=True)
    newest = BodyState(timestamp=now, timestamp_is_capture=True)
    publish_capture_body(older)
    publish_capture_body(newest)

    samples = drain_capture_bodies()
    assert samples == (older, newest)

    tracker.update(samples[0], song_time=1.0)
    stats.register_hit(HitQuality.PERFECT)
    output = capsys.readouterr().out
    assert "DEBUG buffered scoring contribution" in output
    assert "PERFECT" in output
    assert "50.0ms older" in output

    tracker.update(samples[1], song_time=1.05)
    stats.register_hit(HitQuality.GREAT)
    assert capsys.readouterr().out == ""

    clear_capture_bodies()
    set_debug_enabled(False)


def test_buffered_pose_log_is_silent_when_f3_is_off(capsys) -> None:
    clear_capture_bodies()
    set_debug_enabled(False)
    tracker = MotionTracker()
    stats = RunStats(total_notes=1)
    now = time.monotonic()
    older = BodyState(timestamp=now - 0.040, timestamp_is_capture=True)
    newest = BodyState(timestamp=now, timestamp_is_capture=True)
    publish_capture_body(older)
    publish_capture_body(newest)

    samples = drain_capture_bodies()
    tracker.update(samples[0], song_time=1.0)
    stats.register_hit(HitQuality.HIT)

    assert capsys.readouterr().out == ""
    clear_capture_bodies()
