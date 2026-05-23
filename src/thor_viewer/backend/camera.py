import time

import cv2
import numpy as np
from threading import Event, Lock, Thread


class UvcCamera:
    def __init__(self, index: int, width: int, height: int, fps: int) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self._cap: cv2.VideoCapture | None = None
        self._lock = Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_sequence = 0
        self._error_message: str | None = None
        self._stop_event: Event | None = None
        self._thread: Thread | None = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None

    @property
    def error_message(self) -> str | None:
        with self._lock:
            return self._error_message

    def set_index(self, index: int) -> None:
        if self.is_open:
            raise RuntimeError("Disconnect before changing camera")

        self.index = index

    def open(self) -> None:
        self.close()

        cap = cv2.VideoCapture(self.index)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)

        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Could not open camera index {self.index}")

        stop_event = Event()
        with self._lock:
            self._error_message = None

        self._cap = cap
        self._stop_event = stop_event
        self._thread = Thread(target=self._capture_loop, args=(cap, stop_event), daemon=True)
        self._thread.start()

    def _capture_loop(self, cap: cv2.VideoCapture, stop_event: Event) -> None:
        failed_reads = 0
        failed_read_limit = max(10, self.fps)

        try:
            while not stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    failed_reads += 1
                    if failed_reads >= failed_read_limit:
                        with self._lock:
                            self._error_message = (
                                "Camera disconnected or stopped sending frames"
                            )

                        if self._cap is cap:
                            self._cap = None

                        return

                    time.sleep(0.02)
                    continue

                failed_reads = 0

                with self._lock:
                    self._latest_frame = frame
                    self._latest_sequence += 1
        finally:
            cap.release()

    def read_latest(self) -> tuple[int, np.ndarray] | None:
        if self._cap is None:
            return None

        with self._lock:
            if self._latest_frame is None:
                return None

            sequence = self._latest_sequence
            frame = self._latest_frame.copy()

        return sequence, frame

    def read(self) -> np.ndarray | None:
        latest = self.read_latest()
        if latest is None:
            return None

        _, frame = latest
        return frame

    def close(self) -> None:
        stop_event = self._stop_event
        self._stop_event = None

        if stop_event is not None:
            stop_event.set()

        thread = self._thread
        self._thread = None

        cap = self._cap
        self._cap = None

        if thread is not None:
            thread.join(timeout=1.0)
        elif cap is not None:
            cap.release()

        with self._lock:
            self._latest_frame = None
            self._latest_sequence = 0
            self._error_message = None
