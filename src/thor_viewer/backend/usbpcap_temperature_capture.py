from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread

from thor_viewer.backend.live_temperature import (
    LIVE_THERMAL_BYTES,
    THOR_TEMP_HEADER,
    LiveTemperatureFrame,
    parse_live_temperature_packet,
)


@dataclass(frozen=True)
class UsbPcapTemperatureStatus:
    path: Path
    exists: bool = False
    bytes_read: int = 0
    buffered_bytes: int = 0
    marker_seen: bool = False
    frame_seen: bool = False
    message: str = "not started"


class UsbPcapLiveTemperatureCapture:
    def __init__(self, path: Path, poll_interval: float = 0.1) -> None:
        self.path = path
        self.poll_interval = poll_interval
        self._lock = Lock()
        self._latest_frame: LiveTemperatureFrame | None = None
        self._source_label: str | None = None
        self._status = UsbPcapTemperatureStatus(path=self.path)
        self._stop_event: Event | None = None
        self._thread: Thread | None = None

    @property
    def latest_frame(self) -> LiveTemperatureFrame | None:
        with self._lock:
            return self._latest_frame

    @property
    def source_label(self) -> str | None:
        with self._lock:
            return self._source_label

    @property
    def status(self) -> UsbPcapTemperatureStatus:
        with self._lock:
            return self._status

    def open(self) -> None:
        self.close()
        self._set_status(message="waiting for capture file")
        stop_event = Event()
        self._stop_event = stop_event
        self._thread = Thread(target=self._capture_loop, args=(stop_event,), daemon=True)
        self._thread.start()

    def _capture_loop(self, stop_event: Event) -> None:
        offset = 0
        buffer = bytearray()
        max_buffer = (LIVE_THERMAL_BYTES + len(THOR_TEMP_HEADER)) * 2

        while not stop_event.is_set():
            if not self.path.exists():
                offset = 0
                buffer.clear()
                self._set_status(
                    exists=False,
                    bytes_read=0,
                    buffered_bytes=0,
                    marker_seen=False,
                    frame_seen=False,
                    message="capture file not found",
                )
                stop_event.wait(self.poll_interval)
                continue

            try:
                size = self.path.stat().st_size
            except OSError:
                self._set_status(exists=True, message="capture file is temporarily unavailable")
                stop_event.wait(self.poll_interval)
                continue

            if size < offset:
                offset = 0
                buffer.clear()

            if size == offset:
                self._set_status(exists=True, bytes_read=offset, message="waiting for new capture bytes")
                stop_event.wait(self.poll_interval)
                continue

            try:
                with self.path.open("rb") as file:
                    file.seek(offset)
                    chunk = file.read()
                    offset = file.tell()
            except OSError:
                self._set_status(exists=True, message="capture file is temporarily unavailable")
                stop_event.wait(self.poll_interval)
                continue

            if not chunk:
                self._set_status(exists=True, bytes_read=offset, message="waiting for new capture bytes")
                stop_event.wait(self.poll_interval)
                continue

            buffer.extend(chunk)
            if len(buffer) > max_buffer:
                del buffer[: len(buffer) - max_buffer]

            marker_seen = THOR_TEMP_HEADER in buffer
            frame = self.parse_capture_bytes(bytes(buffer))
            self._set_status(
                exists=True,
                bytes_read=offset,
                buffered_bytes=len(buffer),
                marker_seen=marker_seen,
                frame_seen=frame is not None,
                message=(
                    "temperature frame found"
                    if frame is not None
                    else (
                        "temperature marker found, waiting for full frame"
                        if marker_seen
                        else "scanning capture bytes for temperature marker"
                    )
                ),
            )
            if frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._source_label = str(self.path)

    @staticmethod
    def parse_capture_bytes(data: bytes) -> LiveTemperatureFrame | None:
        latest_frame: LiveTemperatureFrame | None = None
        start = 0

        while True:
            marker_offset = data.find(THOR_TEMP_HEADER, start)
            if marker_offset < 0:
                return latest_frame

            packet = data[marker_offset:]
            if len(packet) < len(THOR_TEMP_HEADER) + LIVE_THERMAL_BYTES:
                return latest_frame

            try:
                latest_frame = parse_live_temperature_packet(packet)
            except ValueError:
                pass

            start = marker_offset + 1

    def _set_status(
        self,
        exists: bool | None = None,
        bytes_read: int | None = None,
        buffered_bytes: int | None = None,
        marker_seen: bool | None = None,
        frame_seen: bool | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            current = self._status
            self._status = UsbPcapTemperatureStatus(
                path=self.path,
                exists=current.exists if exists is None else exists,
                bytes_read=current.bytes_read if bytes_read is None else bytes_read,
                buffered_bytes=(
                    current.buffered_bytes
                    if buffered_bytes is None
                    else buffered_bytes
                ),
                marker_seen=(
                    current.marker_seen if marker_seen is None else marker_seen
                ),
                frame_seen=current.frame_seen if frame_seen is None else frame_seen,
                message=current.message if message is None else message,
            )

    def close(self) -> None:
        stop_event = self._stop_event
        self._stop_event = None
        if stop_event is not None:
            stop_event.set()

        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=1.5)

        with self._lock:
            self._latest_frame = None
            self._source_label = None
            self._status = UsbPcapTemperatureStatus(path=self.path)
