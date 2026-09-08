from __future__ import annotations

from dataclasses import replace

from . import session_base as _base
from .camera_samples import clear_capture_bodies, drain_capture_bodies
from .session_base import *  # noqa: F401,F403


# Preserve the private helper for compatibility with existing imports/tests.
_stop_music = _base._stop_music


def _sync_base_hooks() -> None:
    # Existing tests and callers monkeypatch vaporstep.session._stop_music. The
    # preserved implementation now lives in session_base, so mirror that hook
    # before entering any base method that can stop audio.
    _base._stop_music = _stop_music


class GameSession(_base.GameSession):
    """Game session that consumes every completed camera inference result.

    Rendering still receives only the latest pose snapshot. Camera results that
    complete between rendered frames are drained here and passed through the
    existing scoring/motion update path in chronological order.
    """

    def restart(self) -> None:
        _sync_base_hooks()
        clear_capture_bodies()
        super().restart()

    def stop(self) -> None:
        _sync_base_hooks()
        super().stop()

    def finish_music_outro(self) -> bool:
        _sync_base_hooks()
        return super().finish_music_outro()

    def _input_scoring_time(self, body: BodyState, current_time: float, now: float) -> float:
        """Map completed camera evidence to capture-time song position.

        Keyboard support is always enabled in the app, so ``keyboard_mode`` is
        not evidence that the current body came from the keyboard. Only an
        actually used keyboard switches the run to immediate/current-time input;
        otherwise capture-timestamped camera bodies retain historical scoring.
        """
        if self.keyboard_used or not body.timestamp_is_capture or body.timestamp <= 0.0:
            return float(current_time)

        timestamp = float(body.timestamp)
        if (
            timestamp == self._camera_input_timestamp
            and self._camera_scoring_time is not None
        ):
            return self._camera_scoring_time

        sample_time = float(current_time) - max(0.0, float(now) - timestamp)
        if self._camera_scoring_time is None:
            self._camera_scoring_time = sample_time
        else:
            self._camera_scoring_time = max(self._camera_scoring_time, sample_time)
        self._camera_input_timestamp = timestamp
        return self._camera_scoring_time

    @staticmethod
    def _with_keyboard_supplements(sample: BodyState, current: BodyState) -> BodyState:
        hand = sample.supplemental_hand_lanes | current.supplemental_hand_lanes
        foot = sample.supplemental_foot_lanes | current.supplemental_foot_lanes
        if hand == sample.supplemental_hand_lanes and foot == sample.supplemental_foot_lanes:
            return sample
        return replace(
            sample,
            supplemental_hand_lanes=hand,
            supplemental_foot_lanes=foot,
        )

    def update(
        self,
        body: BodyState,
        ready_to_start: bool,
        *,
        start_immediately: bool = False,
    ) -> None:
        _sync_base_hooks()

        # Keyboard/synthetic input remains one immediate sample per game-loop
        # update. Clear any stale camera evidence left by a mode/camera switch.
        if not body.timestamp_is_capture:
            clear_capture_bodies()
            super().update(
                body,
                ready_to_start=ready_to_start,
                start_immediately=start_immediately,
            )
            return

        # Before gameplay begins we only need the latest body for readiness and
        # motion warm-up. Discard older pre-start camera results so they can never
        # become scoring evidence after chart time zero.
        if not self.running:
            drain_capture_bodies()
            was_running = self.running
            super().update(
                body,
                ready_to_start=ready_to_start,
                start_immediately=start_immediately,
            )
            if not was_running and self.running:
                clear_capture_bodies()
            return

        samples = drain_capture_bodies()
        if not samples:
            # No new inference completed since the previous rendered frame. The
            # base session deduplicates the repeated capture timestamp, so this
            # preserves non-input bookkeeping without inventing new evidence.
            super().update(
                body,
                ready_to_start=ready_to_start,
                start_immediately=start_immediately,
            )
            return

        for sample in samples:
            sample = self._with_keyboard_supplements(sample, body)
            super().update(
                sample,
                ready_to_start=ready_to_start,
                start_immediately=start_immediately,
            )
            if self.failed or self.finished:
                break
