import threading
import unittest
from unittest.mock import patch

import numpy as np

from thor_viewer.backend.camera import UvcCamera


class BlockingCapture:
    def __init__(self) -> None:
        self.read_started = threading.Event()
        self.allow_read_return = threading.Event()
        self.released = threading.Event()
        self.released_during_read = False
        self.in_read = False

    def set(self, prop, value) -> bool:
        return True

    def isOpened(self) -> bool:
        return True

    def read(self):
        self.in_read = True
        self.read_started.set()
        self.allow_read_return.wait(timeout=2)
        self.in_read = False
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        return True, frame

    def release(self) -> None:
        if self.in_read:
            self.released_during_read = True

        self.released.set()


class FailingCapture:
    def __init__(self) -> None:
        self.released = False

    def set(self, prop, value) -> bool:
        return True

    def isOpened(self) -> bool:
        return False

    def release(self) -> None:
        self.released = True


class UvcCameraTest(unittest.TestCase):
    def test_close_waits_for_capture_read_before_releasing(self) -> None:
        capture = BlockingCapture()
        camera = UvcCamera(index=1, width=640, height=480, fps=25)

        with patch("thor_viewer.backend.camera.cv2.VideoCapture", return_value=capture):
            camera.open()
            self.assertTrue(capture.read_started.wait(timeout=1))

            close_thread = threading.Thread(target=camera.close)
            close_thread.start()
            self.assertFalse(capture.released.wait(timeout=0.1))

            capture.allow_read_return.set()
            close_thread.join(timeout=1)

        self.assertFalse(close_thread.is_alive())
        self.assertTrue(capture.released.is_set())
        self.assertFalse(capture.released_during_read)
        self.assertFalse(camera.is_open)
        self.assertIsNone(camera.read_latest())

    def test_failed_open_releases_capture(self) -> None:
        capture = FailingCapture()
        camera = UvcCamera(index=1, width=640, height=480, fps=25)

        with patch("thor_viewer.backend.camera.cv2.VideoCapture", return_value=capture):
            with self.assertRaisesRegex(RuntimeError, "Could not open camera index 1"):
                camera.open()

        self.assertTrue(capture.released)
        self.assertFalse(camera.is_open)


if __name__ == "__main__":
    unittest.main()
