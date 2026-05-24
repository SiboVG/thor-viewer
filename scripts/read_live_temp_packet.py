from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

from thor_viewer.backend.live_temperature import (
    LIVE_THERMAL_HEIGHT,
    LIVE_THERMAL_WIDTH,
    THOR_TEMP_HEADER,
    parse_live_temperature_packet,
    preview_to_thermal_xy,
)


def _is_hex_byte(token: str) -> bool:
    return len(token) == 2 and all(c in "0123456789abcdefABCDEF" for c in token)


def read_wireshark_hex_dump(path: Path) -> bytes:
    data = bytearray()

    for line in path.read_text(encoding="utf-8").splitlines():
        tokens = line.strip().split()
        if not tokens:
            continue

        if re.fullmatch(r"[0-9a-fA-F]{4,8}", tokens[0]):
            tokens = tokens[1:]

        for token in tokens:
            if not _is_hex_byte(token):
                break

            data.append(int(token, 16))

    return bytes(data)


def read_hex_stream(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    hex_chars = re.sub(r"[^0-9a-fA-F]", "", text)
    if len(hex_chars) % 2:
        raise ValueError("Hex stream has an odd number of hex digits")

    return bytes.fromhex(hex_chars)


def read_input(path: Path, input_format: str) -> bytes:
    if input_format == "raw":
        return path.read_bytes()

    if input_format == "hex-stream":
        return read_hex_stream(path)

    return read_wireshark_hex_dump(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Parse a ThermalMaster Thor live UVC temperature packet copied from "
            "Wireshark or saved as raw bytes."
        )
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument(
        "--format",
        choices=("wireshark", "hex-stream", "raw"),
        default="wireshark",
        help="Input format. Default: Wireshark hex dump with offsets.",
    )
    parser.add_argument("--preview-width", type=int, default=640)
    parser.add_argument("--preview-height", type=int, default=480)
    parser.add_argument("--x", type=int, help="Preview x coordinate to sample")
    parser.add_argument("--y", type=int, help="Preview y coordinate to sample")
    parser.add_argument("--save-npy", type=Path, help="Optional path to save Celsius array")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Parse complete rows from a truncated packet for debugging only.",
    )
    args = parser.parse_args()

    data = read_input(args.packet, args.format)
    frame = parse_live_temperature_packet(data, args.allow_partial)
    k10 = frame.k10
    celsius = frame.temperature

    min_index = int(np.argmin(celsius))
    max_index = int(np.argmax(celsius))
    min_y, min_x = np.unravel_index(min_index, celsius.shape)
    max_y, max_x = np.unravel_index(max_index, celsius.shape)

    print("input bytes:", len(data))
    print("temp header offset:", f"0x{frame.marker_offset:x}")
    print("thermal payload offset:", f"0x{frame.payload_offset:x}")
    print("shape:", f"{k10.shape[1]}x{k10.shape[0]}")
    if frame.is_partial or k10.shape != (LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH):
        print("warning:", "partial frame; full-frame min/max are not valid")
    print("encoding:", "uint16 little-endian K10")
    print("first 8 K10:", k10.reshape(-1)[:8].tolist())
    print("center C:", float(celsius[k10.shape[0] // 2, k10.shape[1] // 2]))
    print("min C:", float(celsius[min_y, min_x]), "at", (int(min_x), int(min_y)))
    print("max C:", float(celsius[max_y, max_x]), "at", (int(max_x), int(max_y)))
    print("mean C:", float(celsius.mean()))

    if (args.x is None) != (args.y is None):
        raise SystemExit("Use --x and --y together")

    if args.x is not None and args.y is not None:
        thermal_x, thermal_y = preview_to_thermal_xy(
            args.x,
            args.y,
            args.preview_width,
            args.preview_height,
        )
        if thermal_y >= k10.shape[0]:
            print(
                "hover C:",
                "not available in partial frame",
                "at thermal",
                (thermal_x, thermal_y),
            )
        else:
            print(
                "hover C:",
                float(celsius[thermal_y, thermal_x]),
                "at thermal",
                (thermal_x, thermal_y),
            )

    if args.save_npy is not None:
        np.save(args.save_npy, celsius)
        print("saved Celsius array:", args.save_npy)


if __name__ == "__main__":
    main()
