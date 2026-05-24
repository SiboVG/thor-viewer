from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
from PySide6.QtWidgets import QApplication

from thor_viewer.gui.main_window import MainWindow


@dataclass
class FrameStats:
    frames: int = 0
    last_shape: tuple[int, ...] | None = None
    last_mean: float | None = None
    last_std: float | None = None
    last_min: int | None = None
    last_max: int | None = None
    null_images: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def update_from_bgr(self, frame: np.ndarray) -> None:
        self.frames += 1
        self.last_shape = tuple(frame.shape)
        self.last_mean = float(frame.mean())
        self.last_std = float(frame.std())
        self.last_min = int(frame.min())
        self.last_max = int(frame.max())


def print_device_list() -> list:
    devices = QMediaDevices.videoInputs()
    print("Qt video inputs:", len(devices))
    for index, device in enumerate(devices):
        raw_id = bytes(device.id()).decode(errors="replace")
        normalized_id = MainWindow.normalized_camera_device_id(device)
        print(
            f"  [{index}] {device.description()!r} "
            f"id={raw_id!r} normalized={normalized_id!r} "
            f"thor={MainWindow.is_thor_camera_device(device)}"
        )
    return devices


def frame_to_bgr(video_frame) -> np.ndarray | None:
    image = video_frame.toImage()
    if image.isNull():
        return None

    rgb_image = image.convertToFormat(image.Format.Format_RGB888)
    height = rgb_image.height()
    width = rgb_image.width()
    bytes_per_line = rgb_image.bytesPerLine()
    data = np.frombuffer(rgb_image.constBits(), dtype=np.uint8)
    rgb = data.reshape((height, bytes_per_line))[:, : width * 3]
    rgb = rgb.reshape((height, width, 3)).copy()
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def debug_qt_camera(seconds: float) -> None:
    devices = print_device_list()
    thor_devices = [device for device in devices if MainWindow.is_thor_camera_device(device)]
    if not thor_devices:
        print("Qt Thor match: none")
        return

    device = thor_devices[0]
    stats = FrameStats()
    capture_session = QMediaCaptureSession()
    video_sink = QVideoSink()
    camera = QCamera(device)

    def on_frame(video_frame) -> None:
        frame = frame_to_bgr(video_frame)
        if frame is None:
            stats.null_images += 1
            return

        stats.update_from_bgr(frame)
        if stats.frames <= 3:
            print(
                "  Qt frame",
                stats.frames,
                "shape=",
                stats.last_shape,
                "mean=",
                f"{stats.last_mean:.3f}",
                "std=",
                f"{stats.last_std:.3f}",
                "min/max=",
                (stats.last_min, stats.last_max),
            )

    def on_error(error, message: str) -> None:
        stats.errors.append(message or str(error))

    video_sink.videoFrameChanged.connect(on_frame)
    camera.errorOccurred.connect(on_error)
    capture_session.setVideoSink(video_sink)
    capture_session.setCamera(camera)

    print("Qt opening:", MainWindow.camera_device_label(device))
    camera.start()
    QTimer.singleShot(int(seconds * 1000), QApplication.instance().quit)
    QApplication.instance().exec()
    camera.stop()
    capture_session.setCamera(None)

    print("Qt result:")
    print("  frames:", stats.frames)
    print("  null images:", stats.null_images)
    print("  last shape:", stats.last_shape)
    print("  last mean/std:", stats.last_mean, stats.last_std)
    print("  last min/max:", (stats.last_min, stats.last_max))
    print("  black-ish:", is_blackish(stats))
    print("  errors:", stats.errors)


def debug_opencv_camera(seconds: float, max_index: int) -> None:
    backends = [
        ("CAP_ANY", cv2.CAP_ANY),
        ("CAP_DSHOW", getattr(cv2, "CAP_DSHOW", 700)),
        ("CAP_MSMF", getattr(cv2, "CAP_MSMF", 1400)),
    ]
    fourccs: list[tuple[str | None, int | None]] = [
        (None, None),
        ("MJPG", cv2.VideoWriter_fourcc(*"MJPG")),
        ("YUY2", cv2.VideoWriter_fourcc(*"YUY2")),
        ("H264", cv2.VideoWriter_fourcc(*"H264")),
    ]

    print("OpenCV build backends:")
    print("  CAP_DSHOW:", getattr(cv2, "CAP_DSHOW", None))
    print("  CAP_MSMF:", getattr(cv2, "CAP_MSMF", None))

    for index in range(max_index + 1):
        for backend_name, backend in backends:
            for fourcc_name, fourcc in fourccs:
                cap = cv2.VideoCapture(index, backend)
                if not cap.isOpened():
                    cap.release()
                    continue

                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 25)
                if fourcc is not None:
                    cap.set(cv2.CAP_PROP_FOURCC, fourcc)

                stats = FrameStats()
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        stats.update_from_bgr(frame)
                    time.sleep(0.02)

                actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                actual_fourcc_text = "".join(
                    chr((actual_fourcc >> (8 * shift)) & 0xFF) for shift in range(4)
                )
                width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()

                print(
                    f"OpenCV index={index} backend={backend_name} "
                    f"requested_fourcc={fourcc_name or 'default'} "
                    f"actual={actual_fourcc_text!r} size={width:.0f}x{height:.0f} "
                    f"fps={fps:.2f} frames={stats.frames} "
                    f"mean={stats.last_mean} std={stats.last_std} "
                    f"minmax={(stats.last_min, stats.last_max)} "
                    f"black-ish={is_blackish(stats)}"
                )


def is_blackish(stats: FrameStats) -> bool | None:
    if stats.last_mean is None or stats.last_std is None:
        return None
    return stats.last_mean < 2.0 and stats.last_std < 3.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug Thor camera capture on this host.")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--max-index", type=int, default=4)
    parser.add_argument(
        "--skip-opencv",
        action="store_true",
        help="Only test Qt Multimedia, matching the app's live view path.",
    )
    parser.add_argument(
        "--skip-qt",
        action="store_true",
        help="Only test OpenCV indices/backends.",
    )
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv[:1])

    if not args.skip_qt:
        debug_qt_camera(args.seconds)

    if not args.skip_opencv:
        debug_opencv_camera(args.seconds, args.max_index)

    app.quit()


if __name__ == "__main__":
    main()
