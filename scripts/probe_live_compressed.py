"""Probe the Thor live compressed stream (H.264 + temperature) end to end.

Finds the Thor camera, opens its compressed UVC stream via PyAV/dshow, and
reports decoded video frames and live temperature frames for a few seconds.
Run this with the Thor connected to verify live temperature works without
USBPcap:

    uv run python scripts/probe_live_compressed.py [--seconds 10]
    uv run python scripts/probe_live_compressed.py --device "video=UVC Camera"
"""

from __future__ import annotations

import argparse
import sys
import time

from thor_viewer.backend.thor_compressed_capture import (
    ThorCompressedLiveCapture,
    dshow_device_candidates,
)
from thor_viewer.config.settings import FPS, HEIGHT, WIDTH


def thor_device_candidates() -> list[str]:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtMultimedia import QMediaDevices

    from thor_viewer.gui.main_window import MainWindow

    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    _ = app

    candidates: list[str] = []
    for device in QMediaDevices.videoInputs():
        raw_id = bytes(device.id()).decode(errors="replace")
        is_thor = MainWindow.is_thor_camera_device(device)
        print(
            f"camera: {device.description()!r} id={raw_id!r} thor={is_thor}"
        )
        if is_thor:
            candidates.extend(
                dshow_device_candidates(device.description(), raw_id)
            )

    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument(
        "--device",
        action="append",
        help="dshow input name, e.g. video=UVC Camera (repeatable)",
    )
    args = parser.parse_args()

    candidates = args.device or thor_device_candidates()
    if not candidates:
        raise SystemExit("No Thor camera found and no --device given")

    print("device candidates:", candidates)

    capture = ThorCompressedLiveCapture(candidates, WIDTH, HEIGHT, FPS)
    capture.open()

    deadline = time.monotonic() + args.seconds
    last_video_sequence = 0
    last_temp_count = 0
    try:
        while time.monotonic() < deadline:
            time.sleep(0.5)

            error = capture.error_message
            if error is not None:
                raise SystemExit(f"capture error: {error}")

            latest_video = capture.read_latest()
            if latest_video is not None:
                last_video_sequence, frame = latest_video
                video_text = f"video #{last_video_sequence} {frame.shape}"
            else:
                video_text = "video: none yet"

            temperature = capture.latest_frame
            last_temp_count = capture.temperature_frame_count
            if temperature is not None:
                celsius = temperature.temperature
                temp_text = (
                    f"temp #{last_temp_count} "
                    f"center={float(celsius[96, 128]):.2f}C "
                    f"min={temperature.min_temperature():.2f}C "
                    f"max={temperature.max_temperature():.2f}C"
                )
            else:
                temp_text = "temp: none yet"

            print(f"[{capture.source_label}] {video_text} | {temp_text}")
    finally:
        capture.close()

    print()
    print("result:")
    print(f"  decoded video frames: {last_video_sequence}")
    print(f"  temperature frames:   {last_temp_count}")
    if last_video_sequence and last_temp_count:
        print("  SUCCESS: live video + temperature without USBPcap")
    elif last_video_sequence:
        print(
            "  video works but no temperature frames arrived. The camera may "
            "need an enable command (UVC extension unit or CDC serial)."
        )
    else:
        print("  no video decoded; check device name and that no other app uses the camera")


if __name__ == "__main__":
    main()
