import unittest

import numpy as np

from thor_viewer.backend.live_temperature import (
    LIVE_THERMAL_HEIGHT,
    LIVE_THERMAL_WIDTH,
    THOR_TEMP_HEADER,
)
from thor_viewer.backend.thor_stream_demuxer import (
    DemuxedTemperature,
    DemuxedVideo,
    ThorStreamDemuxer,
    split_compressed_sample,
)


def make_temp_packet(k10_value: int = 3000) -> bytes:
    k10 = np.full((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), k10_value, dtype="<u2")
    return THOR_TEMP_HEADER + k10.tobytes()


def make_video_sample(payload: bytes = b"\x67\x42\x00\x1f") -> bytes:
    return b"\x00\x00\x00\x01" + payload


class SplitCompressedSampleTest(unittest.TestCase):
    def test_temperature_sample(self) -> None:
        event = split_compressed_sample(make_temp_packet(3098))

        self.assertIsInstance(event, DemuxedTemperature)
        self.assertAlmostEqual(
            event.frame.temperature_at_thermal_xy(0, 0), 36.65
        )

    def test_video_sample(self) -> None:
        sample = make_video_sample()
        event = split_compressed_sample(sample)

        self.assertIsInstance(event, DemuxedVideo)
        self.assertEqual(event.data, sample)

    def test_truncated_temperature_sample_is_rejected(self) -> None:
        truncated = make_temp_packet()[:-100]
        self.assertIsNone(split_compressed_sample(truncated))

    def test_garbage_sample_is_rejected(self) -> None:
        self.assertIsNone(split_compressed_sample(b"\xff\xfe\xfd\xfc" * 8))


class ThorStreamDemuxerTest(unittest.TestCase):
    def collect(self, demuxer: ThorStreamDemuxer, chunks: list[bytes]):
        temps = []
        video = bytearray()
        for chunk in chunks:
            for event in demuxer.feed(chunk):
                if isinstance(event, DemuxedTemperature):
                    temps.append(event)
                else:
                    video.extend(event.data)
        return temps, bytes(video)

    def test_interleaved_stream(self) -> None:
        video_a = make_video_sample(b"a" * 50)
        video_b = make_video_sample(b"b" * 80)
        stream = video_a + make_temp_packet(3000) + video_b + make_temp_packet(3100)

        temps, video = self.collect(ThorStreamDemuxer(), [stream])

        self.assertEqual(len(temps), 2)
        self.assertAlmostEqual(temps[0].frame.temperature_at_thermal_xy(5, 5), 26.85)
        self.assertAlmostEqual(temps[1].frame.temperature_at_thermal_xy(5, 5), 36.85)
        # All video bytes are eventually flushed except the marker-sized tail.
        self.assertTrue(video_a + video_b[: len(video)] == video)
        self.assertGreaterEqual(len(video), len(video_a))

    def test_single_byte_feeding(self) -> None:
        stream = (
            make_video_sample(b"x" * 30)
            + make_temp_packet(2980)
            + make_video_sample(b"y" * 30)
        )
        chunks = [stream[i : i + 1] for i in range(len(stream))]

        temps, video = self.collect(ThorStreamDemuxer(), chunks)

        self.assertEqual(len(temps), 1)
        self.assertIn(b"x" * 30, video)

    def test_temperature_split_across_chunks(self) -> None:
        packet = make_temp_packet(3050)
        # Split inside the marker and inside the payload.
        chunks = [packet[:4], packet[4:7], packet[7:5000], packet[5000:]]

        temps, _video = self.collect(ThorStreamDemuxer(), chunks)

        self.assertEqual(len(temps), 1)
        self.assertAlmostEqual(
            temps[0].frame.temperature_at_thermal_xy(0, 0), 31.85
        )

    def test_video_only_stream_is_flushed(self) -> None:
        sample = make_video_sample(b"z" * 5000)

        temps, video = self.collect(ThorStreamDemuxer(), [sample])

        self.assertEqual(temps, [])
        # Up to len(marker) - 1 bytes may stay buffered for marker detection.
        self.assertGreaterEqual(len(video), len(sample) - (len(THOR_TEMP_HEADER) - 1))

    def test_implausible_marker_is_treated_as_video(self) -> None:
        # A stray marker inside video data followed by implausible values
        # (all zero Kelvin) must not produce a temperature frame, and the
        # surrounding bytes must stay in the video stream.
        fake = THOR_TEMP_HEADER + b"\x00" * (LIVE_THERMAL_WIDTH * LIVE_THERMAL_HEIGHT * 2)
        stream = make_video_sample(b"v" * 40) + fake + make_temp_packet(3010)

        temps, video = self.collect(ThorStreamDemuxer(), [stream])

        self.assertEqual(len(temps), 1)
        self.assertAlmostEqual(temps[0].frame.temperature_at_thermal_xy(0, 0), 27.85)
        self.assertIn(THOR_TEMP_HEADER + b"\x00\x00", video)

    def test_implausible_sample_is_rejected(self) -> None:
        fake = THOR_TEMP_HEADER + b"\x00" * (LIVE_THERMAL_WIDTH * LIVE_THERMAL_HEIGHT * 2)
        self.assertIsNone(split_compressed_sample(fake))


if __name__ == "__main__":
    unittest.main()
