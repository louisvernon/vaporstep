from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import os
from pathlib import Path
import queue
import re
import shutil
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
AUDIO_SAMPLE_RATE = 44_100
AUDIO_CHANNELS = 2
AUDIO_FRAME_SAMPLES = 1024



def recording_backend_status() -> tuple[bool, str]:
    try:
        import av

        if not any(_codec_is_available(av, codec) for codec in ("libx264", "mpeg4")):
            return False, "no usable MP4 video encoder"
        av.codec.Codec("aac", "w")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _codec_is_available(av_module, name: str) -> bool:
    try:
        av_module.codec.Codec(name, "w")
        return True
    except Exception:
        return False


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
        container = None
        stream = None
        encoder_finished = False
        try:
            import av

            last_codec_error: Exception | None = None
            for codec, options in (
                ("libx264", {"preset": "veryfast", "crf": "23"}),
                ("mpeg4", {"qscale": "7"}),
            ):
                try:
                    if not _codec_is_available(av, codec):
                        raise RuntimeError(f"{codec} is unavailable")
                    container = av.open(
                        str(self._temp_video),
                        mode="w",
                        options={"movflags": "+faststart"},
                    )
                    stream = container.add_stream(codec, rate=RECORD_FPS)
                    stream.width, stream.height = RECORD_SIZE
                    stream.pix_fmt = "yuv420p"
                    stream.options = options
                    break
                except Exception as exc:
                    last_codec_error = exc
                    if container is not None:
                        try:
                            container.close()
                        except Exception:
                            pass
                    container = None
                    stream = None
                    try:
                        self._temp_video.unlink()
                    except OSError:
                        pass
            if container is None or stream is None:
                raise RuntimeError(f"no usable MP4 video encoder: {last_codec_error}")
            self._encoder_ready.set()
            frame_index = 0
            while True:
                packet = self._queue.get()
                if packet is None:
                    break
                frame_bytes, repeats = packet
                pixels = np.frombuffer(frame_bytes, dtype=np.uint8).reshape(
                    RECORD_SIZE[1], RECORD_SIZE[0], 3
                )
                for _ in range(max(1, repeats)):
                    frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                    frame.pts = frame_index
                    frame.time_base = Fraction(1, RECORD_FPS)
                    for encoded in stream.encode(frame):
                        container.mux(encoded)
                    frame_index += 1
                    with self._lock:
                        self._frames_written += 1
            for encoded in stream.encode():
                container.mux(encoded)
            encoder_finished = True
        except Exception as exc:
            with self._lock:
                self._error = f"video encoder: {exc}"
            self._encoder_failed.set()
            self._encoder_ready.set()
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception as exc:
                    with self._lock:
                        if self._error is None:
                            self._error = f"video encoder close: {exc}"
            if not encoder_finished and self._error is None:
                with self._lock:
                    self._error = "video encoder stopped before finalizing"

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
        encoding. PyAV performs decode, resampling, mixing, AAC encoding and MP4
        muxing in-process; no command-line executable or child process is used.
        """
        import av

        sample_count = max(1, int(round(max(0.0, duration) * AUDIO_SAMPLE_RATE)))
        mix = np.zeros((AUDIO_CHANNELS, sample_count), dtype=np.float32)
        if self.music_path is not None and self.music_path.is_file():
            self._mix_music(
                av,
                mix,
                self.music_path,
                chart_time_at_start=self.chart_time_at_start,
                music_stop_time=music_stop_time,
            )
        self._mix_sfx(mix, self._sfx_wav)

        limit = 0.95 * np.iinfo(np.int16).max
        pcm = np.clip(mix, -limit, limit).astype(np.int16)

        try:
            with av.open(str(self._temp_video), mode="r") as video_input:
                video_stream = video_input.streams.video[0]
                with av.open(
                    str(output),
                    mode="w",
                    options={"movflags": "+faststart"},
                ) as muxed:
                    output_video = muxed.add_stream_from_template(video_stream)
                    output_audio = muxed.add_stream("aac", rate=AUDIO_SAMPLE_RATE)
                    output_audio.layout = "stereo"
                    output_audio.bit_rate = 192_000
                    audio_packets = self._encode_audio_packets(av, output_audio, pcm)

                    audio_index = 0
                    for packet in video_input.demux(video_stream):
                        if packet.dts is None:
                            continue
                        video_time = float(packet.dts * packet.time_base)
                        while audio_index < len(audio_packets):
                            audio_packet = audio_packets[audio_index]
                            if audio_packet.dts is None:
                                muxed.mux(audio_packet)
                                audio_index += 1
                                continue
                            audio_time = float(audio_packet.dts * audio_packet.time_base)
                            if audio_time > video_time:
                                break
                            muxed.mux(audio_packet)
                            audio_index += 1
                        packet.stream = output_video
                        muxed.mux(packet)

                    for packet in audio_packets[audio_index:]:
                        muxed.mux(packet)
        except Exception:
            try:
                output.unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def _mix_music(
        av_module,
        mix: np.ndarray,
        music_path: Path,
        *,
        chart_time_at_start: float,
        music_stop_time: float | None,
    ) -> None:
        source_skip = max(0, int(round(chart_time_at_start * AUDIO_SAMPLE_RATE)))
        destination_delay = max(0, int(round(-chart_time_at_start * AUDIO_SAMPLE_RATE)))
        source_stop = (
            max(0, int(round(float(music_stop_time) * AUDIO_SAMPLE_RATE)))
            if music_stop_time is not None
            else None
        )
        if source_stop is not None and source_stop <= source_skip:
            return

        resampler = av_module.AudioResampler(
            format="s16p",
            layout="stereo",
            rate=AUDIO_SAMPLE_RATE,
        )
        source_position = 0

        def add_frame(frame) -> bool:
            nonlocal source_position
            samples = frame.to_ndarray().astype(np.float32, copy=False)
            frame_start = source_position
            frame_end = frame_start + samples.shape[1]
            source_position = frame_end

            copy_start = max(frame_start, source_skip)
            copy_end = frame_end if source_stop is None else min(frame_end, source_stop)
            if copy_end <= copy_start:
                return source_stop is not None and frame_end >= source_stop

            source_offset = copy_start - frame_start
            destination_start = destination_delay + copy_start - source_skip
            count = min(copy_end - copy_start, mix.shape[1] - destination_start)
            if count > 0:
                mix[:, destination_start : destination_start + count] += (
                    samples[:, source_offset : source_offset + count]
                    * RECORDING_MUSIC_VOLUME
                )
            return (
                destination_start + max(0, count) >= mix.shape[1]
                or (source_stop is not None and frame_end >= source_stop)
            )

        with av_module.open(str(music_path), mode="r") as source:
            audio_stream = next((stream for stream in source.streams if stream.type == "audio"), None)
            if audio_stream is None:
                raise RuntimeError(f"song has no audio stream: {music_path.name}")
            for decoded in source.decode(audio_stream):
                for frame in resampler.resample(decoded):
                    if add_frame(frame):
                        return
            for frame in resampler.resample(None):
                if add_frame(frame):
                    return

    @staticmethod
    def _mix_sfx(mix: np.ndarray, path: Path) -> None:
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise RuntimeError("recording effects must be 16-bit PCM")
            if wav.getframerate() != AUDIO_SAMPLE_RATE:
                raise RuntimeError("recording effects sample rate mismatch")
            channels = wav.getnchannels()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)

        samples = samples.reshape(-1, channels).T
        if channels == 1:
            samples = np.repeat(samples, AUDIO_CHANNELS, axis=0)
        elif channels != AUDIO_CHANNELS:
            raise RuntimeError("recording effects channel layout mismatch")
        count = min(samples.shape[1], mix.shape[1])
        mix[:, :count] += samples[:, :count].astype(np.float32) * RECORDING_SFX_VOLUME

    @staticmethod
    def _encode_audio_packets(av_module, stream, pcm: np.ndarray) -> list:
        packets = []
        for start in range(0, pcm.shape[1], AUDIO_FRAME_SAMPLES):
            chunk = np.ascontiguousarray(pcm[:, start : start + AUDIO_FRAME_SAMPLES])
            frame = av_module.AudioFrame.from_ndarray(
                chunk,
                format="s16p",
                layout="stereo",
            )
            frame.sample_rate = AUDIO_SAMPLE_RATE
            frame.pts = start
            frame.time_base = Fraction(1, AUDIO_SAMPLE_RATE)
            packets.extend(stream.encode(frame))
        packets.extend(stream.encode())
        return packets

    def snapshot(self) -> RecordingSnapshot:
        with self._lock:
            return RecordingSnapshot(
                active=self._active,
                finalizing=self._finalizing,
                saved_path=self._saved_path,
                error=self._error,
                dropped_frames=self._dropped_frames,
            )
