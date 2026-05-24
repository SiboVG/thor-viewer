import unittest

import numpy as np

from thor_viewer.backend.live_temperature import (
    LIVE_THERMAL_HEIGHT,
    LIVE_THERMAL_WIDTH,
    THOR_TEMP_HEADER,
    LiveTemperatureFrame,
    parse_live_temperature_packet,
    parse_live_temperature_payload,
    preview_to_thermal_xy,
)
from thor_viewer.backend.live_temperature_capture import OpenCvLiveTemperatureCapture
from thor_viewer.backend.usbpcap_temperature_capture import UsbPcapLiveTemperatureCapture


class LiveTemperatureTest(unittest.TestCase):
    def test_parse_full_packet_with_prefix(self) -> None:
        k10 = np.full((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), 3000, dtype="<u2")
        k10[96, 128] = 3098
        data = b"\x00" * 0x1D + THOR_TEMP_HEADER + k10.tobytes()

        frame = parse_live_temperature_packet(data)

        self.assertEqual(frame.marker_offset, 0x1D)
        self.assertEqual(frame.payload_offset, 0x27)
        self.assertEqual(frame.k10.shape, (LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH))
        self.assertFalse(frame.is_partial)
        self.assertAlmostEqual(frame.temperature_at_thermal_xy(128, 96), 36.65)

    def test_temperature_provider_min_max_and_positions(self) -> None:
        k10 = np.full((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), 3000, dtype="<u2")
        k10[111, 4] = 2900
        k10[175, 238] = 3100

        frame = LiveTemperatureFrame(k10)

        self.assertAlmostEqual(frame.min_temperature(), 16.85, places=4)
        self.assertAlmostEqual(frame.max_temperature(), 36.85, places=4)
        self.assertEqual(frame.min_temperature_position(), (4, 111))
        self.assertEqual(frame.max_temperature_position(), (238, 175))

    def test_preview_coordinates_map_to_thermal_coordinates(self) -> None:
        self.assertEqual(preview_to_thermal_xy(320, 240, 640, 480), (128, 96))

        k10 = np.zeros((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), dtype="<u2")
        k10[96, 128] = 3098
        frame = LiveTemperatureFrame(k10)

        self.assertAlmostEqual(frame.temperature_at_preview_xy(320, 240, 640, 480), 36.65)

    def test_incomplete_packet_requires_partial_mode(self) -> None:
        row = np.full((1, LIVE_THERMAL_WIDTH), 3000, dtype="<u2")
        data = b"\x02\x83" + THOR_TEMP_HEADER + row.tobytes()

        with self.assertRaisesRegex(ValueError, "Incomplete temperature payload"):
            parse_live_temperature_packet(data)

        frame = parse_live_temperature_packet(data, allow_partial=True)

        self.assertTrue(frame.is_partial)
        self.assertEqual(frame.k10.shape, (1, LIVE_THERMAL_WIDTH))

    def test_payload_parser_rejects_incomplete_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "complete rows"):
            parse_live_temperature_payload(b"\x00\x00\x01\x00")

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

    def test_usbpcap_parser_finds_latest_temperature_packet_in_capture_bytes(
        self,
    ) -> None:
        first = np.full((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), 3000, dtype="<u2")
        second = np.full((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), 3001, dtype="<u2")
        first_packet = b"pcap-block-a" + THOR_TEMP_HEADER + first.tobytes()
        second_packet = b"pcap-block-b" + THOR_TEMP_HEADER + second.tobytes()

        frame = UsbPcapLiveTemperatureCapture.parse_capture_bytes(
            first_packet + second_packet
        )

        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertAlmostEqual(frame.temperature_at_thermal_xy(0, 0), 26.95)

    def test_usbpcap_parser_ignores_incomplete_latest_packet(self) -> None:
        complete = np.full((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), 3000, dtype="<u2")
        capture = (
            THOR_TEMP_HEADER
            + complete.tobytes()
            + b"trailing-block"
            + THOR_TEMP_HEADER
            + b"\x00\x00"
        )

        frame = UsbPcapLiveTemperatureCapture.parse_capture_bytes(capture)

        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertAlmostEqual(frame.temperature_at_thermal_xy(0, 0), 26.85)


if __name__ == "__main__":
    unittest.main()
