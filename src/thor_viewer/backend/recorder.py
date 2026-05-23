from pathlib import Path

import cv2
import numpy as np


class VideoRecorder:
    def __init__(self, fps: int, frame_size: tuple[int, int]) -> None:
        self.fps = fps
        self.frame_size = frame_size
        self._writer: cv2.VideoWriter | None = None

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    def start(self, path: Path) -> None:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(
            str(path),
            fourcc,
            self.fps,
            self.frame_size,
        )

        if not self._writer.isOpened():
            self._writer = None
            raise RuntimeError(f"Could not start recording to {path}")

    def write(self, frame: np.ndarray) -> None:
        if self._writer is not None:
            self._writer.write(frame)

    def stop(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None
