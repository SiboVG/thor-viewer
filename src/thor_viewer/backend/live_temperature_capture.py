from __future__ import annotations

import time
from threading import Event, Lock, Thread

import cv2

from thor_viewer.backend.live_temperature import (
    LiveTemperatureFrame,
    parse_live_temperature_packet,
)


class OpenCvLiveTemperatureCapture:
    def __init__(
        self,
        indices: list[int],
        width: int,
        height: int,
        fps: int,
    ) -> None:
        self.indices = list(dict.fromkeys(index for index in indices if index >= 0))
        self.width = width
        self.height = height
        self.fps = fps
        self._lock = Lock()
        self._latest_frame: LiveTemperatureFrame | None = None
        self._source_label: str | None = None
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

    def open(self) -> None:
        self.close()
        if not self.indices:
            return

        stop_event = Event()
        self._stop_event = stop_event
        self._thread = Thread(target=self._capture_loop, args=(stop_event,), daemon=True)
        self._thread.start()

    def _capture_loop(self, stop_event: Event) -> None:
        backends = [
            ("ANY", cv2.CAP_ANY),
        ]

        while not stop_event.is_set():
            for index in self.indices:
                for backend_name, backend in backends:
                    if stop_event.is_set():
                        return

                    cap = self._open_raw_capture(index, backend)
                    if cap is None:
                        continue

                    try:
                        if self._read_temperature_stream(
                            cap,
                            f"OpenCV {backend_name} index {index}",
                            stop_event,
                        ):
                            return
                    finally:
                        cap.release()

            stop_event.wait(2.0)

    def _open_raw_capture(self, index: int, backend: int):
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            return None

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(getattr(cv2, "CAP_PROP_CONVERT_RGB", 16), 0)
        cap.set(cv2.CAP_PROP_FORMAT, -1)
        return cap

    def _read_temperature_stream(
        self,
        cap,
        source_label: str,
        stop_event: Event,
    ) -> bool:
        found_temperature = False
        failed_reads = 0
        probed_frames = 0

        while not stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                failed_reads += 1
                if not found_temperature and failed_reads >= 2:
                    return False
                time.sleep(0.02)
                continue

            failed_reads = 0
            probed_frames += 1
            temperature_frame = self.parse_raw_frame(frame)
            if temperature_frame is None:
                if not found_temperature and probed_frames >= 10:
                    return False
                continue

            found_temperature = True
            with self._lock:
                self._latest_frame = temperature_frame
                self._source_label = source_label

        return True

    @staticmethod
    def parse_raw_frame(frame) -> LiveTemperatureFrame | None:
        try:
            return parse_live_temperature_packet(frame.tobytes())
        except ValueError:
            return None

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
