from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from threading import Event, Lock, Thread

import numpy as np

from thor_viewer.backend.live_temperature import LiveTemperatureFrame
from thor_viewer.backend.thor_stream_demuxer import (
    DemuxedTemperature,
    DemuxedVideo,
    ThorStreamDemuxer,
)

# DirectShow capture device monikers use this KS category GUID in their
# device path, while Qt/Media Foundation ids use the camera category GUID.
DSHOW_CAPTURE_CATEGORY_GUID = "{65e8773d-8f56-11d0-a3b9-00a0c9223196}"

FIRST_DATA_TIMEOUT = 8.0
READ_CHUNK_BYTES = 65536


def dshow_device_candidates(description: str, raw_id: str) -> list[str]:
    """Build dshow input names for a camera from its Qt description and id.

    On Windows the Qt camera id is the device interface symbolic link
    (\\\\?\\usb#vid_...#{guid}\\global), which maps to the dshow alternative
    name "@device_pnp_<link>". The friendly name is used as a fallback.
    """
    candidates: list[str] = []

    if description:
        candidates.append(f"video={description}")

    link = raw_id.strip()
    if link.startswith("\\\\?\\"):
        dshow_link = re.sub(
            r"\{[0-9a-fA-F-]{36}\}",
            DSHOW_CAPTURE_CATEGORY_GUID,
            link,
        )
        candidates.append(f"video=@device_pnp_{dshow_link}")
        if dshow_link != link:
            candidates.append(f"video=@device_pnp_{link}")

    return candidates


def find_ffmpeg() -> str | None:
    override = os.environ.get("THOR_FFMPEG")
    if override:
        return override

    found = shutil.which("ffmpeg")
    if found:
        return found

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class ThorCompressedLiveCapture:
    """Read the Thor's compressed UVC H.264 stream and split out temperature.

    The Thor interleaves raw 256x192 Kelvin*10 temperature frames as separate
    UVC payloads on its only video stream (frame-based H.264). Decoding
    through Media Foundation or OpenCV discards them, so this capture grabs
    the compressed sample stream with an ffmpeg dshow subprocess
    (-c copy -copyinkf), demuxes it into temperature packets and H.264
    access units, and decodes the video in-process with PyAV.

    ffmpeg's own libavformat input cannot be used in-process: PyAV fails in
    avformat_find_stream_info because the extract_extradata pass chokes on
    the temperature packets, while the ffmpeg CLI treats that as a warning.
    """

    def __init__(
        self,
        device_candidates: list[str],
        width: int,
        height: int,
        fps: int,
    ) -> None:
        self.device_candidates = list(device_candidates)
        self.width = width
        self.height = height
        self.fps = fps
        self._lock = Lock()
        self._latest_video: np.ndarray | None = None
        self._video_sequence = 0
        self._latest_temperature: LiveTemperatureFrame | None = None
        self._temperature_count = 0
        self._error_message: str | None = None
        self._source_label: str | None = None
        self._stop_event: Event | None = None
        self._thread: Thread | None = None
        self._process: subprocess.Popen | None = None

    @property
    def is_open(self) -> bool:
        return self._thread is not None

    @property
    def error_message(self) -> str | None:
        with self._lock:
            return self._error_message

    @property
    def source_label(self) -> str | None:
        with self._lock:
            return self._source_label

    @property
    def latest_frame(self) -> LiveTemperatureFrame | None:
        """Latest temperature frame, matching the temperature capture API."""
        with self._lock:
            return self._latest_temperature

    @property
    def temperature_frame_count(self) -> int:
        with self._lock:
            return self._temperature_count

    def read_latest(self) -> tuple[int, np.ndarray] | None:
        with self._lock:
            if self._latest_video is None:
                return None
            return self._video_sequence, self._latest_video.copy()

    def open(self) -> None:
        self.close()
        with self._lock:
            self._error_message = None
        stop_event = Event()
        self._stop_event = stop_event
        self._thread = Thread(
            target=self._capture_loop, args=(stop_event,), daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        stop_event = self._stop_event
        self._stop_event = None
        if stop_event is not None:
            stop_event.set()

        self._terminate_process()

        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=3.0)

        with self._lock:
            self._latest_video = None
            self._video_sequence = 0
            self._latest_temperature = None
            self._temperature_count = 0
            self._source_label = None

    def _terminate_process(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return

        try:
            process.kill()
            process.wait(timeout=2.0)
        except Exception:
            pass

    def _ffmpeg_command(self, ffmpeg: str, device: str) -> list[str]:
        return [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-f",
            "dshow",
            "-vcodec",
            "h264",
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            str(self.fps),
            "-i",
            device,
            "-c",
            "copy",
            "-copyinkf",
            "-flush_packets",
            "1",
            "-f",
            "h264",
            "pipe:1",
        ]

    def _capture_loop(self, stop_event: Event) -> None:
        try:
            import av
        except ImportError:
            self._set_error(
                "PyAV is not installed; compressed live capture is unavailable"
            )
            return

        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            self._set_error(
                "ffmpeg executable not found (install ffmpeg or set THOR_FFMPEG)"
            )
            return

        last_error: str | None = None
        for candidate in self.device_candidates:
            if stop_event.is_set():
                return

            error = self._stream_from_device(av, ffmpeg, candidate, stop_event)
            if error is None:
                return

            last_error = f"{candidate}: {error}"

        if not stop_event.is_set():
            self._set_error(
                "Could not open Thor compressed stream: "
                + (last_error or "no device candidates")
            )

    def _stream_from_device(
        self,
        av,
        ffmpeg: str,
        device: str,
        stop_event: Event,
    ) -> str | None:
        """Stream from one dshow device. Returns an error string on failure,
        or None when streaming ended after having produced data (treated as
        success so we do not fail over to another device mid-session)."""
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                self._ffmpeg_command(ffmpeg, device),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            return f"could not start ffmpeg: {exc}"

        self._process = process
        # Drain stderr continuously so ffmpeg can never block on a full
        # stderr pipe; keep only the tail for error reporting.
        stderr_tail = bytearray()
        stderr_thread = Thread(
            target=self._drain_stderr, args=(process, stderr_tail), daemon=True
        )
        stderr_thread.start()

        decoder = av.CodecContext.create("h264", "r")
        demuxer = ThorStreamDemuxer()
        produced_data = False
        started = time.monotonic()

        try:
            while not stop_event.is_set():
                chunk = process.stdout.read1(READ_CHUNK_BYTES)
                if not chunk:
                    if process.poll() is not None:
                        break
                    if not produced_data and (
                        time.monotonic() - started > FIRST_DATA_TIMEOUT
                    ):
                        return "no data from camera"
                    time.sleep(0.01)
                    continue

                if not produced_data:
                    produced_data = True
                    with self._lock:
                        self._source_label = device

                for event in demuxer.feed(chunk):
                    if isinstance(event, DemuxedTemperature):
                        self._store_temperature(event.frame)
                    elif isinstance(event, DemuxedVideo):
                        self._decode_video(decoder, event.data)
        finally:
            self._terminate_process()
            stderr_thread.join(timeout=1.0)

        if stop_event.is_set():
            return None

        if not produced_data:
            message = bytes(stderr_tail).decode(errors="replace").strip()
            return message or "ffmpeg exited without producing data"

        self._set_error("Thor compressed stream ended")
        return None

    @staticmethod
    def _drain_stderr(process: subprocess.Popen, tail: bytearray) -> None:
        max_tail = 4096
        try:
            while True:
                chunk = process.stderr.read1(4096)
                if not chunk:
                    return
                tail.extend(chunk)
                if len(tail) > max_tail:
                    del tail[: len(tail) - max_tail]
        except Exception:
            return

    def _decode_video(self, decoder, data: bytes) -> None:
        try:
            packets = decoder.parse(data)
        except Exception:
            return

        for packet in packets:
            try:
                frames = decoder.decode(packet)
            except Exception:
                continue

            for frame in frames:
                bgr = frame.to_ndarray(format="bgr24")
                with self._lock:
                    self._latest_video = bgr
                    self._video_sequence += 1

    def _store_temperature(self, frame: LiveTemperatureFrame) -> None:
        with self._lock:
            self._latest_temperature = frame
            self._temperature_count += 1

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._error_message = message
