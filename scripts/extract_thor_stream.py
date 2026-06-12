"""Extract and validate the Thor compressed UVC stream from a USBPcap capture.

Reads a .pcap/.pcapng USBPcap file, collects the bulk IN payloads of the
Thor video endpoint, strips the UVC payload headers, and demuxes the result
into H.264 access units and temperature frames using both the per-sample
classifier and the continuous-stream demuxer.

Usage:
    uv run python scripts/extract_thor_stream.py <capture.pcapng>
        [--endpoint 0x85] [--save-h264 out.h264] [--save-temps out_dir]
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np

from thor_viewer.backend.live_temperature import THOR_TEMP_HEADER
from thor_viewer.backend.thor_stream_demuxer import (
    DemuxedTemperature,
    DemuxedVideo,
    ThorStreamDemuxer,
    split_compressed_sample,
)

USBPCAP_HEADER_STRUCT = struct.Struct("<HQIHBHHBBI")
PCAPNG_SECTION_HEADER = 0x0A0D0D0A
PCAPNG_ENHANCED_PACKET = 6
PCAPNG_SIMPLE_PACKET = 3


def iter_pcapng_packets(data: bytes):
    offset = 0
    endian = "<"

    while offset + 12 <= len(data):
        block_type = int.from_bytes(data[offset : offset + 4], "little")
        if block_type == PCAPNG_SECTION_HEADER:
            magic = data[offset + 8 : offset + 12]
            endian = "<" if magic == b"\x4d\x3c\x2b\x1a" else ">"

        if endian == "<":
            block_type = int.from_bytes(data[offset : offset + 4], "little")
            block_length = int.from_bytes(data[offset + 4 : offset + 8], "little")
        else:
            block_type = int.from_bytes(data[offset : offset + 4], "big")
            block_length = int.from_bytes(data[offset + 4 : offset + 8], "big")

        if block_length < 12 or offset + block_length > len(data):
            return

        if block_type == PCAPNG_ENHANCED_PACKET:
            captured_len = int.from_bytes(
                data[offset + 20 : offset + 24],
                "little" if endian == "<" else "big",
            )
            packet = data[offset + 28 : offset + 28 + captured_len]
            yield packet
        elif block_type == PCAPNG_SIMPLE_PACKET:
            packet = data[offset + 12 : offset + block_length - 4]
            yield packet

        offset += block_length


def iter_pcap_packets(data: bytes):
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise ValueError("Not a classic pcap file")

    offset = 24
    while offset + 16 <= len(data):
        captured_len = int.from_bytes(
            data[offset + 8 : offset + 12], "little" if endian == "<" else "big"
        )
        yield data[offset + 16 : offset + 16 + captured_len]
        offset += 16 + captured_len


def iter_capture_packets(path: Path):
    data = path.read_bytes()
    if data[:4] == b"\x0a\x0d\x0d\x0a":
        yield from iter_pcapng_packets(data)
    else:
        yield from iter_pcap_packets(data)


def iter_thor_payloads(path: Path, endpoint: int):
    """Yield UVC payloads (header stripped) from device-to-host bulk packets."""
    for packet in iter_capture_packets(path):
        if len(packet) < USBPCAP_HEADER_STRUCT.size:
            continue

        (
            header_len,
            _irp_id,
            _status,
            _function,
            info,
            _bus,
            _device,
            pkt_endpoint,
            transfer,
            data_length,
        ) = USBPCAP_HEADER_STRUCT.unpack_from(packet)

        is_from_device = bool(info & 0x01)
        if transfer != 3 or pkt_endpoint != endpoint or not is_from_device:
            continue
        if data_length == 0 or header_len + data_length > len(packet):
            continue

        payload = packet[header_len : header_len + data_length]
        uvc_header_len = payload[0]
        if uvc_header_len < 2 or uvc_header_len > 12 or uvc_header_len > len(payload):
            continue

        yield payload[uvc_header_len:]


def summarize_temperature(event: DemuxedTemperature) -> str:
    celsius = event.frame.temperature
    center = float(celsius[celsius.shape[0] // 2, celsius.shape[1] // 2])
    return (
        f"center={center:.2f}C min={float(celsius.min()):.2f}C "
        f"max={float(celsius.max()):.2f}C mean={float(celsius.mean()):.2f}C"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--endpoint", type=lambda v: int(v, 0), default=0x85)
    parser.add_argument("--save-h264", type=Path)
    parser.add_argument("--save-temps", type=Path)
    parser.add_argument("--feed-chunk", type=int, default=4096,
                        help="Chunk size for the continuous-stream demuxer test")
    args = parser.parse_args()

    payloads = list(iter_thor_payloads(args.capture, args.endpoint))
    print(f"bulk IN payloads on endpoint 0x{args.endpoint:02x}: {len(payloads)}")
    if not payloads:
        return

    # Mode 1: classify each driver-assembled sample.
    sample_temps: list[DemuxedTemperature] = []
    sample_videos: list[DemuxedVideo] = []
    unclassified = 0
    for payload in payloads:
        event = split_compressed_sample(payload)
        if isinstance(event, DemuxedTemperature):
            sample_temps.append(event)
        elif isinstance(event, DemuxedVideo):
            sample_videos.append(event)
        else:
            unclassified += 1

    print("\nper-sample classification:")
    print(f"  temperature frames: {len(sample_temps)}")
    print(f"  video samples:      {len(sample_videos)}")
    print(f"  unclassified:       {unclassified}")

    # False-positive check: marker bytes inside video samples.
    marker_in_video = sum(
        video.data.count(THOR_TEMP_HEADER) for video in sample_videos
    )
    print(f"  temp markers inside video bytes: {marker_in_video}")

    for event in sample_temps[:3]:
        print("  temp", summarize_temperature(event))

    if sample_temps:
        centers = np.array(
            [
                float(e.frame.temperature[96, 128])
                for e in sample_temps
            ]
        )
        print(
            f"  center over {len(centers)} frames: "
            f"min={centers.min():.2f}C max={centers.max():.2f}C"
        )

    # Mode 2: continuous byte stream through ThorStreamDemuxer.
    demuxer = ThorStreamDemuxer()
    stream = b"".join(payloads)
    stream_temps = 0
    stream_video_bytes = 0
    for start in range(0, len(stream), args.feed_chunk):
        for event in demuxer.feed(stream[start : start + args.feed_chunk]):
            if isinstance(event, DemuxedTemperature):
                stream_temps += 1
            else:
                stream_video_bytes += len(event.data)

    print("\ncontinuous-stream demuxer:")
    print(f"  temperature frames: {stream_temps}")
    print(f"  video bytes:        {stream_video_bytes}")
    total_video_bytes = sum(len(v.data) for v in sample_videos)
    print(f"  video bytes (per-sample reference): {total_video_bytes}")

    if args.save_h264:
        args.save_h264.write_bytes(b"".join(v.data for v in sample_videos))
        print(f"\nsaved H.264 elementary stream: {args.save_h264}")

    if args.save_temps:
        args.save_temps.mkdir(parents=True, exist_ok=True)
        for index, event in enumerate(sample_temps):
            np.save(args.save_temps / f"temp_{index:04d}.npy", event.frame.temperature)
        print(f"saved {len(sample_temps)} temperature frames: {args.save_temps}")


if __name__ == "__main__":
    main()
