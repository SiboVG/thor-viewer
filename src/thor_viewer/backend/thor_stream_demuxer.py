from __future__ import annotations

from dataclasses import dataclass

from thor_viewer.backend.live_temperature import (
    LIVE_THERMAL_BYTES,
    THOR_TEMP_HEADER,
    LiveTemperatureFrame,
    is_plausible_live_temperature_frame,
    parse_live_temperature_payload,
)

# The Thor exposes a single UVC video stream (frame-based H.264, 640x480) and
# interleaves raw temperature frames on the same stream as separate UVC
# payloads. Each temperature payload is the 10-byte ff00 marker followed by
# 256x192 little-endian uint16 Kelvin*10 values. Video samples are complete
# Annex-B H.264 access units (SPS+PPS+IDR every frame).
TEMP_PACKET_BYTES = len(THOR_TEMP_HEADER) + LIVE_THERMAL_BYTES

H264_START_CODE = b"\x00\x00\x00\x01"


@dataclass(frozen=True)
class DemuxedTemperature:
    frame: LiveTemperatureFrame


@dataclass(frozen=True)
class DemuxedVideo:
    data: bytes


def split_compressed_sample(data: bytes) -> DemuxedTemperature | DemuxedVideo | None:
    """Classify one compressed UVC sample (one driver-assembled frame).

    Returns the parsed temperature frame when the sample is a Thor
    temperature packet, the H.264 bytes when it looks like video, or None
    for unusable samples.
    """
    if data.startswith(THOR_TEMP_HEADER):
        payload = data[len(THOR_TEMP_HEADER) : TEMP_PACKET_BYTES]
        if len(payload) < LIVE_THERMAL_BYTES:
            return None
        try:
            frame = parse_live_temperature_payload(payload)
        except ValueError:
            return None
        if not is_plausible_live_temperature_frame(frame):
            return None
        return DemuxedTemperature(frame)

    if H264_START_CODE in data[:8]:
        return DemuxedVideo(data)

    return None


class ThorStreamDemuxer:
    """Split a continuous Thor compressed byte stream into video and temperature.

    This works without packet boundaries: temperature frames are located by
    their marker, everything between them is treated as H.264 elementary
    stream bytes. Use split_compressed_sample() instead when sample
    boundaries are known (e.g. demuxed packets).
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[DemuxedTemperature | DemuxedVideo]:
        self._buffer.extend(data)
        events: list[DemuxedTemperature | DemuxedVideo] = []

        while True:
            marker_offset = self._buffer.find(THOR_TEMP_HEADER)
            if marker_offset < 0:
                events.extend(self._drain_video(self._safe_video_length()))
                return events

            events.extend(self._drain_video(marker_offset))
            if len(self._buffer) < TEMP_PACKET_BYTES:
                return events

            payload = bytes(
                self._buffer[len(THOR_TEMP_HEADER) : TEMP_PACKET_BYTES]
            )
            frame: LiveTemperatureFrame | None
            try:
                frame = parse_live_temperature_payload(payload)
            except ValueError:
                frame = None

            if frame is not None and is_plausible_live_temperature_frame(frame):
                del self._buffer[:TEMP_PACKET_BYTES]
                events.append(DemuxedTemperature(frame))
            else:
                # A marker that is not followed by a believable temperature
                # frame is treated as video bitstream bytes; rescan right
                # after it so a real temperature frame inside is not lost.
                events.extend(self._drain_video(len(THOR_TEMP_HEADER)))

    def _safe_video_length(self) -> int:
        # Keep a marker-sized tail buffered so a marker split across feed()
        # calls is not flushed out as video bytes.
        return max(0, len(self._buffer) - (len(THOR_TEMP_HEADER) - 1))

    def _drain_video(self, length: int) -> list[DemuxedVideo]:
        if length <= 0:
            return []

        chunk = bytes(self._buffer[:length])
        del self._buffer[:length]
        return [DemuxedVideo(chunk)]
