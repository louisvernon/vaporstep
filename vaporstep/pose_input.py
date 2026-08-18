from __future__ import annotations

import platform
import threading
import time
from dataclasses import dataclass

import cv2
import mediapipe as mp
import numpy as np

from .config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    FOOT_PLAYFIELD_LEFT,
    FOOT_PLAYFIELD_RIGHT,
    HAND_PLAYFIELD_LEFT,
    HAND_PLAYFIELD_RIGHT,
    LANDMARK_VISIBILITY_THRESHOLD,
    LOWER_BODY_ANKLE_BLEND,
    LOWER_BODY_ANKLE_CONFIDENCE_HIGH,
    LOWER_BODY_ANKLE_CONFIDENCE_LOW,
    LOWER_BODY_CONTROL_SMOOTH_ALPHA,
    LOWER_BODY_MAX_SINGLE_FRAME_X_JUMP,
    LOWER_BODY_WEIGHT_SMOOTH_ALPHA,
    LANE_COUNT,
    LANE_HYSTERESIS,
    OUTER_LANE_ASSIST,
    OUTER_LANE_EDGE_EXTENSION,
    LANE_PERSPECTIVE_STRENGTH,
    HAND_HIT_Y,
    FOOT_HIT_Y,
    VANISH_HALF_WIDTH,
    VANISH_Y,
)
from .domain import BodyPoint, BodyState
from .lanes import (
    HystereticLaneResolver,
    lower_leg_control_position,
    perspective_adjusted_x,
    zoom_normalized_x,
)


LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28


def _open_camera_capture(camera_index: int):
    """Open a camera using the preferred native backend for this platform."""
    if platform.system() == "Darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
        cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(camera_index)
    else:
        cap = cv2.VideoCapture(camera_index)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


def probe_camera(camera_index: int = 0) -> bool:
    """Briefly open and immediately release a camera.

    This is intentionally independent of MediaPipe. On macOS it is enough to
    trigger the OS camera-permission flow without leaving the camera active
    while VaporStep is sitting in its menus. A failed probe is non-fatal; the
    normal gameplay camera path retries when the device is actually needed.
    """
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


@dataclass(frozen=True)
class PoseSnapshot:
    body: BodyState
    mask: np.ndarray | None = None
    camera_ok: bool = False
    message: str = "Starting camera…"
    pose_fps: float = 0.0


@dataclass
class _LowerLegFilter:
    x: float | None = None
    y: float | None = None
    ankle_weight: float = 0.0

    def reset(self) -> None:
        self.x = None
        self.y = None
        self.ankle_weight = 0.0

    def update(
        self,
        *,
        knee: BodyPoint,
        ankle: BodyPoint,
        raw_ankle_weight: float,
    ) -> tuple[float, float, float]:
        weight_alpha = max(0.0, min(1.0, LOWER_BODY_WEIGHT_SMOOTH_ALPHA))
        self.ankle_weight += (raw_ankle_weight - self.ankle_weight) * weight_alpha

        target_x = knee.x + (ankle.x - knee.x) * self.ankle_weight
        target_y = knee.y + (ankle.y - knee.y) * self.ankle_weight
        if self.x is None or self.y is None:
            self.x = target_x
            self.y = target_y
            return self.x, self.y, self.ankle_weight

        # A person cannot plausibly move a lower leg across a large fraction of
        # the camera in one pose sample. Clamp isolated model glitches without
        # preventing a sustained real movement from catching up on later frames.
        max_jump = max(0.01, float(LOWER_BODY_MAX_SINGLE_FRAME_X_JUMP))
        dx = target_x - self.x
        if abs(dx) > max_jump:
            target_x = self.x + max_jump * (1.0 if dx > 0.0 else -1.0)

        alpha = max(0.0, min(1.0, LOWER_BODY_CONTROL_SMOOTH_ALPHA))
        self.x += (target_x - self.x) * alpha
        self.y += (target_y - self.y) * alpha
        return self.x, self.y, self.ankle_weight


class PoseCameraInput:
    """OpenCV camera capture + asynchronous MediaPipe pose inference."""

    def __init__(self, model_path: str, camera_index: int = 0, horizontal_zoom: float = 1.10) -> None:
        self.model_path = model_path
        self.camera_index = camera_index
        self.horizontal_zoom = float(horizontal_zoom)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._landmarker = None
        self._capture = None
        self._last_result_time = 0.0
        self._pose_fps_ema = 0.0
        self._snapshot = PoseSnapshot(body=BodyState())
        self._lower_leg_filters = {
            "left": _LowerLegFilter(),
            "right": _LowerLegFilter(),
        }

        self._resolvers = {
            "lw": HystereticLaneResolver(
                HAND_PLAYFIELD_LEFT, HAND_PLAYFIELD_RIGHT, LANE_COUNT, LANE_HYSTERESIS, OUTER_LANE_ASSIST, OUTER_LANE_EDGE_EXTENSION
            ),
            "rw": HystereticLaneResolver(
                HAND_PLAYFIELD_LEFT, HAND_PLAYFIELD_RIGHT, LANE_COUNT, LANE_HYSTERESIS, OUTER_LANE_ASSIST, OUTER_LANE_EDGE_EXTENSION
            ),
            "lk": HystereticLaneResolver(
                FOOT_PLAYFIELD_LEFT, FOOT_PLAYFIELD_RIGHT, LANE_COUNT, LANE_HYSTERESIS, OUTER_LANE_ASSIST, OUTER_LANE_EDGE_EXTENSION
            ),
            "rk": HystereticLaneResolver(
                FOOT_PLAYFIELD_LEFT, FOOT_PLAYFIELD_RIGHT, LANE_COUNT, LANE_HYSTERESIS, OUTER_LANE_ASSIST, OUTER_LANE_EDGE_EXTENSION
            ),
        }

    def set_horizontal_zoom(self, value: float) -> None:
        self.horizontal_zoom = float(value)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        # mediapipe==0.10.35 is pinned in pyproject.toml because a fresh 1.x
        # install caused a native macOS graph/Metal abort during task startup.
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=self.model_path),
            running_mode=mp.tasks.vision.RunningMode.LIVE_STREAM,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_segmentation_masks=True,
            result_callback=self._on_result,
        )
        self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self._stop.clear()
        self._thread = threading.Thread(target=self._capture_loop, name="pose-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def snapshot(self) -> PoseSnapshot:
        with self._lock:
            return self._snapshot

    def _open_camera(self):
        return _open_camera_capture(self.camera_index)

    def _capture_loop(self) -> None:
        # Opening a camera can legitimately fail on first launch while macOS is
        # waiting for the user to answer its camera-permission dialog. Keep the
        # capture thread alive and retry the same selected device.
        t0 = time.monotonic()
        failed_reads = 0
        retry_count = 0

        while not self._stop.is_set():
            if self._capture is None or not self._capture.isOpened():
                try:
                    cap = self._open_camera()
                except Exception:
                    cap = None

                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    self._capture = None
                    retry_count += 1
                    with self._lock:
                        self._snapshot = PoseSnapshot(
                            body=BodyState(),
                            camera_ok=False,
                            message=(
                                "Waiting for camera permission / camera…"
                                if retry_count <= 12
                                else "Camera unavailable — retrying automatically"
                            ),
                        )
                    self._stop.wait(0.5 if retry_count <= 12 else 1.5)
                    continue

                self._capture = cap
                retry_count = 0
                failed_reads = 0
                with self._lock:
                    self._snapshot = PoseSnapshot(
                        body=BodyState(),
                        camera_ok=True,
                        message="Looking for wrists and lower legs…",
                    )

            ok, bgr = self._capture.read()
            if not ok:
                failed_reads += 1
                if failed_reads >= 20:
                    self._capture.release()
                    self._capture = None
                    failed_reads = 0
                    with self._lock:
                        self._snapshot = PoseSnapshot(
                            body=BodyState(),
                            camera_ok=False,
                            message="Camera interrupted — reconnecting…",
                        )
                    self._stop.wait(0.25)
                else:
                    self._stop.wait(0.01)
                continue

            failed_reads = 0
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int((time.monotonic() - t0) * 1000)
            self._landmarker.detect_async(mp_image, timestamp_ms)

    @staticmethod
    def _confidence(lm) -> float:
        visibility = max(0.0, min(1.0, float(lm.visibility or 0.0)))
        presence = max(0.0, min(1.0, float(lm.presence or 0.0)))
        return min(visibility, presence)

    @classmethod
    def _visible(cls, lm) -> bool:
        return cls._confidence(lm) >= LANDMARK_VISIBILITY_THRESHOLD

    def _camera_point(self, lm, *, visible: bool | None = None) -> BodyPoint:
        """Return a displayed camera-space point without resolving a lane."""
        if visible is None:
            visible = self._visible(lm)
        # Detection is on the unmirrored image; invert x for the mirrored view.
        x = zoom_normalized_x(1.0 - float(lm.x), self.horizontal_zoom)
        return BodyPoint(x=x, y=float(lm.y), visible=bool(visible))

    def _resolve_point(
        self,
        point: BodyPoint,
        resolver: HystereticLaneResolver,
        *,
        hit_y: float,
    ) -> BodyPoint:
        """Resolve a camera-space point through the perspective lane map."""
        if not point.visible:
            resolver.current_lane = None
            return point
        lane_x = perspective_adjusted_x(
            point.x,
            point.y,
            playfield_left=resolver.left,
            playfield_right=resolver.right,
            hit_y=hit_y,
            vanish_y=VANISH_Y,
            vanish_half_width=VANISH_HALF_WIDTH,
            strength=LANE_PERSPECTIVE_STRENGTH,
        )
        return BodyPoint(
            x=point.x,
            y=point.y,
            lane=resolver.resolve(lane_x),
            visible=True,
            source_weight=point.source_weight,
        )

    def _point(
        self,
        lm,
        resolver: HystereticLaneResolver,
        *,
        hit_y: float,
    ) -> BodyPoint:
        return self._resolve_point(self._camera_point(lm), resolver, hit_y=hit_y)

    def _lower_body_points(
        self,
        knee_lm,
        ankle_lm,
        resolver: HystereticLaneResolver,
        *,
        leg: str,
    ) -> tuple[BodyPoint, BodyPoint, BodyPoint]:
        """Return raw knee/ankle sources and a stable shin lane-control point.

        Lane occupancy follows the virtual point. Stomp velocity continues to
        use the actual knee coordinates, but the knee carries the control point's
        resolved lane so timing events line up with lower-body occupancy.
        """
        knee = self._camera_point(knee_lm)
        ankle_confidence = self._confidence(ankle_lm)
        ankle = self._camera_point(ankle_lm, visible=ankle_confidence > 0.10)
        tracker = self._lower_leg_filters[leg]
        if not knee.visible:
            tracker.reset()
            resolver.current_lane = None
            return knee, ankle, BodyPoint()

        _, _, raw_weight = lower_leg_control_position(
            knee.x,
            knee.y,
            ankle.x,
            ankle.y,
            ankle_confidence=ankle_confidence,
            ankle_blend=LOWER_BODY_ANKLE_BLEND,
            confidence_low=LOWER_BODY_ANKLE_CONFIDENCE_LOW,
            confidence_high=LOWER_BODY_ANKLE_CONFIDENCE_HIGH,
        )
        control_x, control_y, weight = tracker.update(
            knee=knee,
            ankle=ankle,
            raw_ankle_weight=raw_weight,
        )
        control = self._resolve_point(
            BodyPoint(
                x=control_x,
                y=control_y,
                visible=True,
                source_weight=weight,
            ),
            resolver,
            hit_y=FOOT_HIT_Y,
        )
        knee_for_motion = BodyPoint(
            x=knee.x,
            y=knee.y,
            lane=control.lane,
            visible=knee.visible,
        )
        return knee_for_motion, ankle, control

    def _on_result(self, result, output_image, timestamp_ms: int) -> None:
        now = time.monotonic()
        if self._last_result_time:
            inst = 1.0 / max(now - self._last_result_time, 1e-6)
            self._pose_fps_ema = (
                inst if not self._pose_fps_ema else (0.9 * self._pose_fps_ema + 0.1 * inst)
            )
        self._last_result_time = now

        if not result.pose_landmarks:
            for resolver in self._resolvers.values():
                resolver.current_lane = None
            for tracker in self._lower_leg_filters.values():
                tracker.reset()
            snapshot = PoseSnapshot(
                body=BodyState(timestamp=now),
                mask=None,
                camera_ok=True,
                message="Move into view so your wrists and lower legs are visible",
                pose_fps=self._pose_fps_ema,
            )
            with self._lock:
                self._snapshot = snapshot
            return

        lm = result.pose_landmarks[0]
        lw = self._point(lm[LEFT_WRIST], self._resolvers["lw"], hit_y=HAND_HIT_Y)
        rw = self._point(lm[RIGHT_WRIST], self._resolvers["rw"], hit_y=HAND_HIT_Y)
        lk, la, lfc = self._lower_body_points(
            lm[LEFT_KNEE], lm[LEFT_ANKLE], self._resolvers["lk"], leg="left"
        )
        rk, ra, rfc = self._lower_body_points(
            lm[RIGHT_KNEE], lm[RIGHT_ANKLE], self._resolvers["rk"], leg="right"
        )

        body = BodyState(
            left_wrist=lw,
            right_wrist=rw,
            left_knee=lk,
            right_knee=rk,
            left_ankle=la,
            right_ankle=ra,
            left_foot_control=lfc,
            right_foot_control=rfc,
            pose_visible=True,
            timestamp=now,
        )

        mask = None
        if result.segmentation_masks:
            raw = result.segmentation_masks[0].numpy_view()
            mask = np.flip(raw.copy(), axis=1)

        keypoints = (lw, rw, lfc, rfc)
        if not all(p.visible for p in keypoints):
            message = "Keep both wrists and lower legs visible"
        elif any(p.lane is None for p in keypoints):
            message = "Move into the hand / foot play areas"
        else:
            message = "READY"

        with self._lock:
            self._snapshot = PoseSnapshot(
                body=body,
                mask=mask,
                camera_ok=True,
                message=message,
                pose_fps=self._pose_fps_ema,
            )
