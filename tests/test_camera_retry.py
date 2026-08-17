from __future__ import annotations

import importlib
import sys
import types


# The container test environment intentionally does not install MediaPipe.  The
# retry behavior under test happens before inference, so a minimal import stub
# is sufficient and keeps this a pure camera-lifecycle test.
if "mediapipe" not in sys.modules:
    sys.modules["mediapipe"] = types.ModuleType("mediapipe")

pose_input = importlib.import_module("vaporstep.pose_input")
PoseCameraInput = pose_input.PoseCameraInput


class FakeCapture:
    def __init__(self, opened: bool, *, stop_on_read=None) -> None:
        self.opened = opened
        self.released = False
        self.stop_on_read = stop_on_read

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def release(self) -> None:
        self.released = True

    def read(self):
        if self.stop_on_read is not None:
            self.stop_on_read.set()
        return False, None


def test_camera_retries_same_device_after_initial_open_failure(monkeypatch):
    camera = PoseCameraInput("unused.task", camera_index=0)
    first = FakeCapture(False)
    second = FakeCapture(True, stop_on_read=camera._stop)
    attempts = iter((first, second))
    calls = []

    def fake_open_camera():
        calls.append(camera.camera_index)
        return next(attempts)

    monkeypatch.setattr(camera, "_open_camera", fake_open_camera)
    # Avoid a real half-second sleep after the deliberately failed first open.
    monkeypatch.setattr(camera._stop, "wait", lambda timeout: camera._stop.is_set())

    camera._capture_loop()

    assert calls == [0, 0]
    assert first.released
    assert camera.snapshot().camera_ok is True


def test_camera_probe_releases_device_immediately(monkeypatch):
    capture = FakeCapture(True)
    monkeypatch.setattr(pose_input, "_open_camera_capture", lambda index: capture)

    assert pose_input.probe_camera(0) is True
    assert capture.released is True
