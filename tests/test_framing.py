import pygame

from vaporstep.character_renderer import Renderer
from vaporstep.domain import BodyPoint, BodyState
from vaporstep.framing import FramingMonitor, FramingWarnings
from vaporstep.renderer import BG, RED


def _point(*, y: float = 0.5, visible: bool = True) -> BodyPoint:
    return BodyPoint(x=0.5, y=y, visible=visible)


def _body(
    *,
    wrists: tuple[BodyPoint, BodyPoint] | None = None,
    knees: tuple[BodyPoint, BodyPoint] | None = None,
    ankles: tuple[BodyPoint, BodyPoint] | None = None,
) -> BodyState:
    wrists = wrists or (_point(y=0.15), _point(y=0.15))
    knees = knees or (_point(y=0.75), _point(y=0.75))
    ankles = ankles or (_point(y=0.95), _point(y=0.95))
    return BodyState(
        left_wrist=wrists[0],
        right_wrist=wrists[1],
        left_knee=knees[0],
        right_knee=knees[1],
        left_ankle=ankles[0],
        right_ankle=ankles[1],
    )


def test_hands_warn_only_after_both_are_lost_for_the_grace_period() -> None:
    monitor = FramingMonitor(grace_seconds=0.5)
    monitor.start(_body(), hands_enabled=True, feet_enabled=False)

    one_lost = _body(wrists=(_point(visible=False), _point(y=0.15)))
    assert not monitor.update(one_lost, now=1.0, hands_enabled=True, feet_enabled=False).top

    both_lost = _body(wrists=(_point(y=-0.1), _point(visible=False)))
    assert not monitor.update(both_lost, now=2.0, hands_enabled=True, feet_enabled=False).top
    assert monitor.update(both_lost, now=2.49, hands_enabled=True, feet_enabled=False).top is False
    assert monitor.update(both_lost, now=2.50, hands_enabled=True, feet_enabled=False).top is True


def test_transient_loss_does_not_accumulate_across_recovery() -> None:
    monitor = FramingMonitor(grace_seconds=0.5)
    visible = _body()
    lost = _body(wrists=(_point(visible=False), _point(visible=False)))
    monitor.start(visible, hands_enabled=True, feet_enabled=False)

    assert not monitor.update(lost, now=1.0, hands_enabled=True, feet_enabled=False).top
    assert not monitor.update(visible, now=1.4, hands_enabled=True, feet_enabled=False).top
    assert not monitor.update(lost, now=1.8, hands_enabled=True, feet_enabled=False).top
    assert monitor.update(lost, now=2.3, hands_enabled=True, feet_enabled=False).top


def test_ankle_warning_reference_stays_locked_while_gameplay_can_fall_back() -> None:
    monitor = FramingMonitor(grace_seconds=0.5)
    monitor.start(_body(), hands_enabled=False, feet_enabled=True)
    assert monitor.lower_source == "ankles"

    ankles_lost_knees_visible = _body(
        ankles=(_point(visible=False), _point(y=1.1)),
        knees=(_point(y=0.75), _point(y=0.75)),
    )
    assert not monitor.update(
        ankles_lost_knees_visible,
        now=3.0,
        hands_enabled=False,
        feet_enabled=True,
    ).bottom
    assert monitor.update(
        ankles_lost_knees_visible,
        now=3.5,
        hands_enabled=False,
        feet_enabled=True,
    ).bottom
    assert monitor.lower_source == "ankles"


def test_knees_are_used_when_both_ankles_are_not_in_frame_at_start() -> None:
    monitor = FramingMonitor(grace_seconds=0.5)
    initial = _body(ankles=(_point(y=0.95), _point(visible=False)))
    monitor.start(initial, hands_enabled=False, feet_enabled=True)
    assert monitor.lower_source == "knees"

    ankles_lost = _body(ankles=(_point(visible=False), _point(visible=False)))
    assert not monitor.update(
        ankles_lost,
        now=4.0,
        hands_enabled=False,
        feet_enabled=True,
    ).bottom

    knees_lost = _body(
        knees=(_point(visible=False), _point(y=1.1)),
        ankles=(_point(visible=False), _point(visible=False)),
    )
    assert not monitor.update(
        knees_lost,
        now=5.0,
        hands_enabled=False,
        feet_enabled=True,
    ).bottom
    assert monitor.update(
        knees_lost,
        now=5.5,
        hands_enabled=False,
        feet_enabled=True,
    ).bottom


def test_keyboard_started_run_arms_after_pose_is_acquired() -> None:
    monitor = FramingMonitor(grace_seconds=0.5)
    monitor.start(BodyState(), hands_enabled=True, feet_enabled=True)
    assert monitor.lower_source is None

    assert monitor.update(
        _body(),
        now=1.0,
        hands_enabled=True,
        feet_enabled=True,
    ).top is False
    assert monitor.lower_source == "ankles"

    lost = _body(
        wrists=(_point(visible=False), _point(visible=False)),
        ankles=(_point(visible=False), _point(visible=False)),
    )
    warnings = monitor.update(lost, now=1.5, hands_enabled=True, feet_enabled=True)
    assert warnings.top is False
    assert warnings.bottom is False
    warnings = monitor.update(lost, now=2.0, hands_enabled=True, feet_enabled=True)
    assert warnings.top is True
    assert warnings.bottom is True


def test_framing_warning_draws_full_width_at_physical_screen_edges() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer = Renderer(screen)
    screen.fill(BG)

    renderer._draw_framing_warning(FramingWarnings(top=True, bottom=True))

    assert screen.get_at((0, 0))[:3] == RED
    assert screen.get_at((1279, 0))[:3] == RED
    assert screen.get_at((0, 719))[:3] == RED
    assert screen.get_at((1279, 719))[:3] == RED
    assert screen.get_at((640, 7))[:3] != BG
    assert screen.get_at((640, 712))[:3] != BG
    assert screen.get_at((640, 8))[:3] == BG
    assert screen.get_at((640, 711))[:3] == BG
    assert screen.get_at((640, 360))[:3] == BG


def test_gameplay_renderer_wires_monitor_without_enabling_it_in_calibration(
    monkeypatch,
) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer = Renderer(screen)
    now = [1.0]
    visible = _body()
    lost = _body(
        wrists=(_point(visible=False), _point(visible=False)),
        ankles=(_point(visible=False), _point(visible=False)),
    )
    monkeypatch.setattr("vaporstep.character_renderer.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "vaporstep.character_renderer.GameplayRenderer.draw",
        lambda self, body, *args, **kwargs: self.screen.fill(BG),
    )

    # Calibration also runs a session, but deliberately passes no gameplay stats.
    renderer.draw(visible, running=True, stats=None)
    now[0] = 2.0
    renderer.draw(lost, running=True, stats=None)
    assert screen.get_at((0, 0))[:3] == BG

    renderer.draw(visible, running=True, stats=object())
    now[0] = 2.5
    renderer.draw(lost, running=True, stats=object())
    now[0] = 3.0
    renderer.draw(lost, running=True, stats=object())
    assert screen.get_at((0, 0))[:3] == RED
    assert screen.get_at((0, 719))[:3] == RED
