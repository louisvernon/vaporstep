from vaporstep.domain import BodyPoint, BodyState, HitQuality, NoteKind
from vaporstep.motion import MotionTracker


def body(ts, *, lk=None, rk=None, lw=None, rw=None):
    return BodyState(
        left_knee=lk or BodyPoint(),
        right_knee=rk or BodyPoint(),
        left_wrist=lw or BodyPoint(),
        right_wrist=rw or BodyPoint(),
        pose_visible=True,
        timestamp=ts,
    )


def point(x, y, lane):
    return BodyPoint(x=x, y=y, lane=lane, visible=True)


def test_knee_lift_does_not_strike_but_downward_stomp_does():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.70, 2)), None)

    # Knee lifts upward in the image: this is wind-up, not the stomp.
    lift = tracker.update(body(1.050, lk=point(0.40, 0.66, 2)), 2.00)
    assert lift == []

    # Reverse direction and drive downward strongly enough to fire the strike.
    tracker.update(body(1.100, lk=point(0.40, 0.67, 2)), 2.05)
    stomp = tracker.update(body(1.150, lk=point(0.40, 0.72, 2)), 2.10)
    assert len(stomp) == 1
    assert stomp[0].kind == NoteKind.FOOT
    assert stomp[0].lane == 2
    assert stomp[0].source == "strike"


def test_high_hand_downward_windup_does_not_strike_but_upward_motion_does():
    tracker = MotionTracker()
    tracker.update(body(1.000, lw=point(0.40, 0.30, 2)), None)

    down = tracker.update(body(1.050, lw=point(0.40, 0.34, 2)), 3.00)
    assert down == []

    tracker.update(body(1.100, lw=point(0.40, 0.33, 2)), 3.05)
    up = tracker.update(body(1.150, lw=point(0.40, 0.27, 2)), 3.10)
    assert len(up) == 1
    assert up[0].kind == NoteKind.HANDS
    assert up[0].lane == 2
    assert up[0].source == "strike"


def test_motion_impulse_is_debounced_until_limb_reverses_or_settles():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.60, 2)), None)
    first = tracker.update(body(1.050, lk=point(0.40, 0.65, 2)), 2.00)
    assert len(first) == 1

    # Continued downward motion is part of the same stomp.
    second = tracker.update(body(1.100, lk=point(0.40, 0.70, 2)), 2.05)
    assert second == []

    # Lift/reversal collapses directional strike speed and rearms the detector.
    tracker.update(body(1.170, lk=point(0.40, 0.66, 2)), 2.12)
    tracker.update(body(1.240, lk=point(0.40, 0.63, 2)), 2.19)
    third = tracker.update(body(1.310, lk=point(0.40, 0.69, 2)), 2.26)
    assert len(third) == 1


def test_continuing_stomp_updates_the_pending_event_toward_landing_time():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.60, 2)), None)

    started = tracker.update(body(1.050, lk=point(0.40, 0.65, 2)), 9.84)
    assert len(started) == 1
    assert started[0].song_time == 9.84

    # Continued downward travel is still the same physical stomp, but its
    # effective timing moves closer to the eventual landing.
    continued = tracker.update(body(1.100, lk=point(0.40, 0.70, 2)), 9.96)
    assert continued == []
    assert tracker.pending_events[0].song_time == 9.96

    match = tracker.match(NoteKind.FOOT, (2,), 10.00)
    assert match is not None
    assert match[0] == HitQuality.PERFECT


def test_one_motion_event_can_only_grade_one_note():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.60, 2)), None)
    tracker.update(body(1.050, lk=point(0.40, 0.65, 2)), 4.04)

    match = tracker.match(NoteKind.FOOT, (2,), 4.00)
    assert match is not None
    quality, delta = match
    assert quality == HitQuality.PERFECT
    assert delta < 0.10
    assert tracker.match(NoteKind.FOOT, (2,), 4.08) is None


def test_double_outer_hand_timing_requires_outward_impulse_in_both_lanes():
    tracker = MotionTracker()
    tracker.update(
        body(1.000, lw=point(0.26, 0.34, 1), rw=point(0.74, 0.34, 4)),
        None,
    )
    tracker.update(
        body(1.050, lw=point(0.20, 0.34, 1), rw=point(0.80, 0.34, 4)),
        5.90,
    )
    match = tracker.match(NoteKind.HANDS, (1, 4), 6.00)
    assert match is not None
    quality, _ = match
    assert quality == HitQuality.GREAT


def test_lane_entry_always_generates_input_event_and_can_grade_note():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.70, 2)), None)
    events = tracker.update(body(1.050, lk=point(0.60, 0.70, 3)), 8.00)
    assert len(events) == 1
    assert events[0].source == "entry"
    assert events[0].lane == 3

    match = tracker.match(NoteKind.FOOT, (3,), 8.00)
    assert match is not None
    assert match[0] == HitQuality.PERFECT


def test_lane_entry_feedback_can_follow_recent_strike_without_waiting_for_rearm():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.60, 2)), None)
    strike = tracker.update(body(1.050, lk=point(0.40, 0.65, 2)), 9.00)
    assert len(strike) == 1

    # A real horizontal lane transition should still be visible immediately.
    entry = tracker.update(body(1.080, lk=point(0.60, 0.65, 3)), 9.03)
    assert len(entry) == 1
    assert entry[0].source == "entry"
    assert entry[0].lane == 3


def test_great_window_is_more_forgiving_but_perfect_stays_tight():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.60, 2)), None)
    tracker.update(body(1.050, lk=point(0.40, 0.65, 2)), 9.82)
    match = tracker.match(NoteKind.FOOT, (2,), 10.00)
    assert match is not None
    quality, delta = match
    assert quality == HitQuality.GREAT
    assert 0.10 < delta < 0.20


def test_timing_window_is_wider_before_the_note_than_after_it():
    early = MotionTracker()
    early.record_input(NoteKind.FOOT, 2, 9.80, source="entry", limb="lk")
    assert early.match(NoteKind.FOOT, (2,), 10.0) is not None

    too_early = MotionTracker()
    too_early.record_input(NoteKind.FOOT, 2, 9.79, source="entry", limb="lk")
    assert too_early.match(NoteKind.FOOT, (2,), 10.0) is None

    late = MotionTracker()
    late.record_input(NoteKind.FOOT, 2, 10.10, source="strike", limb="lk")
    assert late.match(NoteKind.FOOT, (2,), 10.0) is not None

    too_late = MotionTracker()
    too_late.record_input(NoteKind.FOOT, 2, 10.11, source="strike", limb="lk")
    assert too_late.match(NoteKind.FOOT, (2,), 10.0) is None


def test_perfect_window_is_two_thirds_of_a_tenth_on_both_sides():
    for event_time in (10.0 - 1.0 / 15.0, 10.0 + 1.0 / 15.0):
        tracker = MotionTracker()
        tracker.record_input(NoteKind.FOOT, 2, event_time, source="strike", limb="lk")
        match = tracker.match(NoteKind.FOOT, (2,), 10.0)
        assert match is not None
        assert match[0] == HitQuality.PERFECT


def test_subtle_in_lane_stomp_now_registers():
    tracker = MotionTracker()
    tracker.update(body(1.000, lk=point(0.40, 0.700, 2)), None)
    # 0.025 normalized units over 50 ms => 0.5/s instantaneous; after EMA this
    # is ~0.275/s: below the old 0.30 knee threshold, above the current threshold.
    events = tracker.update(body(1.050, lk=point(0.40, 0.725, 2)), 12.00)
    assert len(events) == 1
    assert events[0].source == "strike"
    assert events[0].lane == 2
