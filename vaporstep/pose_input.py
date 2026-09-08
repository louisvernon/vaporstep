from __future__ import annotations

from . import pose_input_base as _base
from .camera_samples import clear_capture_bodies, publish_capture_body
from .pose_input_base import *  # noqa: F401,F403


# Preserve private names used by focused tests and diagnostics.
_QueuedFrame = _base._QueuedFrame
_LowerLegFilter = _base._LowerLegFilter
_strict_timestamp_ms = _base._strict_timestamp_ms
_open_camera_capture = _base._open_camera_capture


def probe_camera(camera_index: int = 0) -> bool:
    """Probe through this module so tests/callers can still patch camera opening."""
    cap = None
    try:
        cap = _open_camera_capture(max(0, int(camera_index)))
        return bool(cap is not None and cap.isOpened())
    except Exception:
        return False
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


class PoseCameraInput(_base.PoseCameraInput):
    """Pose input that also preserves every completed body for scoring."""

    def start(self) -> None:
        clear_capture_bodies()
        super().start()

    def stop(self) -> None:
        try:
            super().stop()
        finally:
            clear_capture_bodies()

    def _open_camera(self):
        return _open_camera_capture(self.camera_index)

    def _handle_result(self, result, output_image, timestamp_ms: int) -> None:
        super()._handle_result(result, output_image, timestamp_ms)
        with self._lock:
            body = self._snapshot.body
        publish_capture_body(body)
