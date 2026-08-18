from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
import wave

import numpy as np

from .audio_fx import (
    RECORDING_MUSIC_VOLUME,
    RECORDING_SFX_VOLUME,
    SFX_CHANNELS,
    SFX_SAMPLE_RATE,
    synthesize_gameplay_event,
)
from .domain import GameplayEvent
from .user_paths import recordings_dir

RECORD_FPS = 30
RECORD_SIZE = (1280, 720)
FRAME_QUEUE_SIZE = 6



def recording_backend_status() -> tuple[bool, str]:
    try:
        import imageio_ffmpeg

        imageio_ffmpeg.get_ffmpeg_exe()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def default_recordings_dir() -> Path:
    return recordings_dir()


def safe_filename_component(value: str, fallback: str = "VaporStep") -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    return (text[:72] or fallback)


def write_sfx_track(
    path: Path,
    events: tuple[GameplayEvent, ...] | list[GameplayEvent],
    *,
    chart_time_at_recording_start: float,
    duration: float,
    sample_rate: int = SFX_SAMPLE_RATE,
    channels: int = SFX_CHANNELS,
) -> None:
    """Render gameplay SFX into one PCM WAV aligned to the recording timeline."""
    frame_count = max(1, int(round(max(0.05, duration) * sample_rate)))
    mix = np.zeros((frame_count, channels), dtype=np.int32)

    for event in events:
        pcm = synthesize_gameplay_event(event, sample_rate=sample_rate, channels=channels)
        start = int(round((event.time - chart_time_at_recording_start) * sample_rate))
        src_start = 0
        if start < 0:
            src_start = min(len(pcm), -start)
            start = 0
        if start >= frame_count or src_start >= len(pcm):
            continue
        count = min(len(pcm) - src_start, frame_count - start)
        mix[start : start + count] += pcm[src_start : src_start + count].astype(np.int32)

    pcm_out = np.clip(mix, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_out.tobytes())


@dataclass(frozen=True)
class RecordingSnapshot:
    active: bool
    finalizing: bool
    saved_path: Path | None
    error: str | None
    dropped_frames: int

    @property
    def message(self) -> str:
        if self.active:
            suffix = f" · {self.dropped_frames} frame drops" if self.dropped_frames else ""
            return f"RECORDING{suffix}"
        if self.finalizing:
            return "SAVING RECORDING…"
        if self.saved_path is not None and self.error:
            return f"SAVED SILENT  {self.saved_path.name}  ·  AUDIO ERROR: {self.error[:120]}"
        if self.saved_path is not None:
            return f"SAVED  {self.saved_path.name}"
        if self.error:
            return f"RECORDING ERROR  {self.error[:160]}"
        return ""


class RunRecorder:
    """Capture one gameplay run without blocking the game/render thread.

    Video frames are copied from the rendered pygame surface on the main thread
    at 30 fps and encoded by a worker. At run end, a second worker reconstructs
    gameplay SFX and muxes them with the original song audio.
    """

    def __init__(
        self,
        *,
        song_title: str,
        chart_label: str,
        music_path: Path | None,
        chart_time_at_start: float,
        output_dir: Path | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self.song_title = song_title
        self.chart_label = chart_label
        self.music_path = Path(music_path) if music_path is not None else None
        self.chart_time_at_start = float(chart_time_at_start)
        self.output_dir = output_dir or default_recordings_dir()
        self.started_at = started_at or datetime.now()

        self._events: list[GameplayEvent] = []
        self._queue: queue.Queue[tuple[bytes, int] | None] = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._finalizer: threading.Thread | None = None
        self._temp_dir = Path(tempfile.mkdtemp(prefix="vaporstep-recording-"))
        self._temp_video = self._temp_dir / "video.mp4"
        self._sfx_wav = self._temp_dir / "effects.wav"

        self._capture_started_at: float | None = None
        self._last_scheduled_index = -1
        self._pending_repeats = 0
        self._last_frame: bytes | None = None
        self._tail_frame: bytes | None = None
        self._tail_repeats = 0
        self._frames_written = 0
        self._dropped_frames = 0
        self._error: str | None = None
        self._saved_path: Path | None = None
        self._active = True
        self._finalizing = False
        self._encoder_ready = threading.Event()
        self._encoder_failed = threading.Event()
        self._start_encoder()

    def _start_encoder(self) -> None:
        self._worker = threading.Thread(target=self._encode_worker, name="VaporStepRecorder", daemon=True)
        self._worker.start()

    def _encode_worker(self) -> None:
        writer = None
        try:
            import imageio_ffmpeg

            last_codec_error: Exception | None = None
            for codec, extra_params in (
                ("libx264", ["-preset", "veryfast"]),
                ("mpeg4", []),
            ):
                try:
                    writer = imageio_ffmpeg.write_frames(
                        str(self._temp_video),
                        RECORD_SIZE,
                        pix_fmt_in="rgb24",
                        pix_fmt_out="yuv420p",
                        fps=RECORD_FPS,
                        codec=codec,
                        quality=7,
                        macro_block_size=2,
                        ffmpeg_log_level="error",
                        output_params=extra_params + ["-movflags", "+faststart", "-an"],
                    )
                    writer.send(None)
                    break
                except Exception as exc:
                    last_codec_error = exc
                    if writer is not None:
                        try:
                            writer.close()
                        except Exception:
                            pass
                    writer = None
                    try:
                        self._temp_video.unlink()
                    except OSError:
                        pass
            if writer is None:
                raise RuntimeError(f"no usable MP4 video encoder: {last_codec_error}")
            self._encoder_ready.set()
            while True:
                packet = self._queue.get()
                if packet is None:
                    break
                frame, repeats = packet
                for _ in range(max(1, repeats)):
                    writer.send(frame)
                    with self._lock:
                        self._frames_written += 1
        except Exception as exc:
            with self._lock:
                self._error = f"video encoder: {exc}"
            self._encoder_failed.set()
            self._encoder_ready.set()
        finally:
            if writer is not None:
                try:
                    writer.close()
                except Exception as exc:
                    with self._lock:
                        if self._error is None:
                            self._error = f"video encoder close: {exc}"

    def add_events(self, events: tuple[GameplayEvent, ...] | list[GameplayEvent]) -> None:
        if events:
            self._events.extend(events)

    def capture(self, surface, now: float) -> None:
        if not self._active or self._encoder_failed.is_set():
            return
        if self._capture_started_at is None:
            self._capture_started_at = float(now)

        elapsed = max(0.0, float(now) - self._capture_started_at)
        target_index = int(elapsed * RECORD_FPS + 1e-6)
        if target_index <= self._last_scheduled_index:
            return
        repeats = target_index - self._last_scheduled_index
        self._last_scheduled_index = target_index

        try:
            import pygame

            frame_surface = surface
            if surface.get_size() != RECORD_SIZE:
                frame_surface = pygame.transform.smoothscale(surface, RECORD_SIZE)
            frame = pygame.image.tobytes(frame_surface, "RGB")
        except Exception as exc:
            with self._lock:
                self._error = f"frame capture: {exc}"
            return

        self._last_frame = frame
        repeats += self._pending_repeats
        try:
            self._queue.put_nowait((frame, repeats))
            self._pending_repeats = 0
        except queue.Full:
            self._pending_repeats += repeats
            with self._lock:
                self._dropped_frames += repeats

    def append_static_tail(self, surface, seconds: float) -> None:
        """Append a clean static frame to the end of the exported clip.

        This does not block the render thread or alter the live UI.  The finalizer
        writes the repeated frame after all real-time gameplay frames have drained,
        which is ideal for a short results-card hold at the end of a recording.
        """
        if not self._active or seconds <= 0.0 or self._encoder_failed.is_set():
            return
        try:
            import pygame

            frame_surface = surface
            if surface.get_size() != RECORD_SIZE:
                frame_surface = pygame.transform.smoothscale(surface, RECORD_SIZE)
            frame = pygame.image.tobytes(frame_surface, "RGB")
        except Exception as exc:
            with self._lock:
                self._error = f"tail frame capture: {exc}"
            return

        self._tail_frame = frame
        self._tail_repeats = max(1, int(round(float(seconds) * RECORD_FPS)))

    def finish(self, *, grade: str, failed: bool = False, music_stop_time: float | None = None) -> None:
        if not self._active:
            return
        self._active = False
        self._finalizing = True
        self._finalizer = threading.Thread(
            target=self._finish_worker,
            kwargs={"grade": grade, "failed": failed, "music_stop_time": music_stop_time},
            name="VaporStepRecordingFinalizer",
            daemon=True,
        )
        self._finalizer.start()

    def abort(self) -> None:
        if not self._active:
            return
        self._active = False
        threading.Thread(target=self._abort_worker, name="VaporStepRecordingAbort", daemon=True).start()

    def _abort_worker(self) -> None:
        try:
            self._queue.put(None)
            if self._worker is not None:
                self._worker.join()
        finally:
            with self._lock:
                self._finalizing = False
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _finish_worker(self, *, grade: str, failed: bool, music_stop_time: float | None) -> None:
        try:
            # Preserve timeline duration if the encoder briefly fell behind by
            # duplicating the most recent rendered frame rather than shortening
            # the output and drifting away from audio.
            if self._pending_repeats and self._last_frame is not None:
                self._queue.put((self._last_frame, self._pending_repeats))
                self._pending_repeats = 0
            if self._tail_frame is not None and self._tail_repeats > 0:
                self._queue.put((self._tail_frame, self._tail_repeats))
                self._tail_frame = None
                self._tail_repeats = 0
            self._queue.put(None)
            if self._worker is not None:
                self._worker.join()

            with self._lock:
                existing_error = self._error
                frame_count = self._frames_written
            if existing_error:
                raise RuntimeError(existing_error)
            if frame_count <= 0 or not self._temp_video.exists():
                raise RuntimeError("no video frames were encoded")

            duration = frame_count / RECORD_FPS
            write_sfx_track(
                self._sfx_wav,
                self._events,
                chart_time_at_recording_start=self.chart_time_at_start,
                duration=duration,
            )

            self.output_dir.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                try:
                    os.chmod(self.output_dir, 0o700)
                except OSError:
                    pass
            stamp = self.started_at.strftime("%Y%m%d-%H%M%S")
            status = "FAILED" if failed else safe_filename_component(grade, "RUN")
            filename = "_".join(
                (
                    "VaporStep",
                    stamp,
                    safe_filename_component(self.song_title, "Song"),
                    safe_filename_component(self.chart_label, "Chart"),
                    status,
                )
            ) + ".mp4"
            output = self.output_dir / filename
            output = self._dedupe_path(output)

            self._mux_audio(output, duration=duration, music_stop_time=music_stop_time)
            with self._lock:
                self._saved_path = output
        except Exception as exc:
            # If muxing fails but video encoding succeeded, preserve a silent
            # clip rather than throwing away the whole run.
            fallback = None
            if self._temp_video.exists():
                try:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    stamp = self.started_at.strftime("%Y%m%d-%H%M%S")
                    fallback = self._dedupe_path(
                        self.output_dir
                        / f"VaporStep_{stamp}_{safe_filename_component(self.song_title, 'Song')}_silent.mp4"
                    )
                    shutil.copy2(self._temp_video, fallback)
                except Exception:
                    fallback = None
            with self._lock:
                self._error = str(exc)
                if fallback is not None:
                    self._saved_path = fallback
        finally:
            with self._lock:
                self._finalizing = False
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    @staticmethod
    def _dedupe_path(path: Path) -> Path:
        if not path.exists():
            return path
        for i in range(2, 1000):
            candidate = path.with_name(f"{path.stem}-{i}{path.suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{path.stem}-{os.getpid()}{path.suffix}")

    def _mux_audio(self, output: Path, *, duration: float, music_stop_time: float | None) -> None:
        """Mux the original song and reconstructed VaporStep effects onto video.

        Keep this as a post-run operation so gameplay never waits on audio
        encoding. Explicit resampling/channel layout makes the filter graph
        behave consistently for OGG/MP3/WAV inputs across bundled FFmpeg builds.
        """
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(self._temp_video)]
        has_music = self.music_path is not None and self.music_path.is_file()
        if has_music:
            cmd += ["-i", str(self.music_path), "-i", str(self._sfx_wav)]
            delay_ms = max(0, int(round(-self.chart_time_at_start * 1000.0)))
            music_filters = [
                "aresample=44100",
                f"volume={RECORDING_MUSIC_VOLUME:.3f}",
            ]
            if music_stop_time is not None:
                music_filters.append(f"atrim=duration={max(0.0, float(music_stop_time)):.6f}")
            if delay_ms:
                music_filters.append(f"adelay={delay_ms}:all=1")
            music_chain = ",".join(music_filters)
            filter_complex = (
                f"[1:a:0]{music_chain}[music];"
                f"[2:a:0]aresample=44100,volume={RECORDING_SFX_VOLUME:.3f}[sfx];"
                "[music][sfx]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                "alimiter=limit=0.95[a]"
            )
            cmd += ["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[a]"]
        else:
            filter_complex = (
                f"[1:a:0]aresample=44100,volume={RECORDING_SFX_VOLUME:.3f},"
                "alimiter=limit=0.95[a]"
            )
            cmd += ["-i", str(self._sfx_wav), "-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[a]"]

        cmd += [
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-t",
            f"{duration:.6f}",
            "-movflags",
            "+faststart",
            str(output),
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, shell=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "ffmpeg mux failed").strip()
            raise RuntimeError(detail[-600:])

    def snapshot(self) -> RecordingSnapshot:
        with self._lock:
            return RecordingSnapshot(
                active=self._active,
                finalizing=self._finalizing,
                saved_path=self._saved_path,
                error=self._error,
                dropped_frames=self._dropped_frames,
            )
