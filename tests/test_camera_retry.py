from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace


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


def test_pose_timestamps_remain_strictly_increasing_with_same_millisecond():
    timestamp = pose_input._strict_timestamp_ms(1.2341, -1)
    duplicate_millisecond = pose_input._strict_timestamp_ms(1.2348, timestamp)
    later = pose_input._strict_timestamp_ms(1.2360, duplicate_millisecond)

    assert timestamp == 1234
    assert duplicate_millisecond == 1235
    assert later == 1236


def test_busy_inference_skips_frame_before_rgb_conversion(monkeypatch):
    camera = PoseCameraInput("unused.task", camera_index=0)

    class OneFrameCapture:
        released = False

        @staticmethod
        def isOpened():
            return True

        def read(self):
            camera._stop.set()
            return True, object()

    camera._capture = OneFrameCapture()
    camera._inference_busy.set()
    conversions = []
    monkeypatch.setattr(pose_input.cv2, "cvtColor", lambda *args: conversions.append(args))

    camera._capture_loop()

    snapshot = camera.snapshot()
    assert conversions == []
    assert snapshot.frames_captured == 1
    assert snapshot.frames_submitted == 0
    assert snapshot.frames_dropped == 1


def test_result_callback_releases_backpressure_gate():
    camera = PoseCameraInput("unused.task", camera_index=0)
    camera._inference_busy.set()
    camera._inference_started_at = pose_input.time.monotonic()

    camera._on_result(SimpleNamespace(pose_landmarks=[]), None, 0)

    assert not camera._inference_busy.is_set()
    assert camera.snapshot().inference_latency_ms >= 0.0


def test_result_body_uses_source_capture_timestamp():
    camera = PoseCameraInput("unused.task", camera_index=0)
    camera._inference_busy.set()
    camera._inference_started_at = pose_input.time.monotonic()
    camera._inference_capture_at = 123.456

    camera._on_result(SimpleNamespace(pose_landmarks=[]), None, 0)

    body = camera.snapshot().body
    assert body.timestamp == 123.456
    assert body.timestamp_is_capture is True


def test_pose_figure_reuses_landmarks_without_segmentation():
    camera = PoseCameraInput("unused.task", output_segmentation_masks=False)
    landmarks = [
        SimpleNamespace(x=index / 100.0, y=index / 200.0, visibility=1.0, presence=1.0)
        for index in range(33)
    ]

    figure = camera._pose_figure(landmarks)

    assert camera.output_segmentation_masks is False
    assert len(figure.landmarks) == 33
    assert figure.point(13).visible
    assert figure.point(13).y == landmarks[13].y
