import unittest

import numpy as np

from thor_camera_driver import (
    LIVE_THERMAL_HEIGHT,
    LIVE_THERMAL_WIDTH,
    THOR_TEMP_HEADER,
)

from thor_viewer.backend.live_temperature_capture import OpenCvLiveTemperatureCapture


class OpenCvLiveTemperatureCaptureTest(unittest.TestCase):
    def test_raw_opencv_frame_parser_accepts_temperature_packet(self) -> None:
        k10 = np.full((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), 3000, dtype="<u2")
        k10[96, 128] = 3098
        data = b"\x00" * 8 + THOR_TEMP_HEADER + k10.tobytes()
        raw_frame = np.frombuffer(data, dtype=np.uint8)

        frame = OpenCvLiveTemperatureCapture.parse_raw_frame(raw_frame)

        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertAlmostEqual(frame.temperature_at_thermal_xy(128, 96), 36.65)

    def test_raw_opencv_frame_parser_rejects_decoded_video_frame(self) -> None:
        decoded_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        frame = OpenCvLiveTemperatureCapture.parse_raw_frame(decoded_frame)

        self.assertIsNone(frame)


if __name__ == "__main__":
    unittest.main()
