from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from thor_viewer.backend.radiometric_jpeg import load_radiometric_jpeg


class RadiometricImageViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.image = None
        self.preview_width = 640
        self.preview_height = 480

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMouseTracking(True)
        self.image_label.mouseMoveEvent = self.on_mouse_move

        self.info_label = QLabel("Open a radiometric IR image")
        self.info_label.setAlignment(Qt.AlignLeft)

        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(self.info_label)
        self.setLayout(layout)

    def open_file(self, path: Path) -> None:
        self.image = load_radiometric_jpeg(path)

        # Decode only the normal JPEG preview part for display.
        jpeg_bytes = self.image.preview_jpeg
        qimg = QImage.fromData(jpeg_bytes)

        self.preview_width = qimg.width()
        self.preview_height = qimg.height()

        self.image_label.setPixmap(QPixmap.fromImage(qimg))

        tmin = self.image.min_temperature()
        tmax = self.image.max_temperature()
        tmin_text = "N/A" if tmin is None else f"{tmin:.2f} °C"
        tmax_text = "N/A" if tmax is None else f"{tmax:.2f} °C"

        meta = self.image.metadata
        roi = meta.get("roi", [])

        self.info_label.setText(
            f"{path.name} | "
            f"{self.preview_width}×{self.preview_height} preview | "
            f"{self.image.temperature.shape[1]}×{self.image.temperature.shape[0]} thermal | "
            f"min={tmin_text} max={tmax_text}"
        )

    def on_mouse_move(self, event: QMouseEvent) -> None:
        if self.image is None:
            return

        pixmap = self.image_label.pixmap()
        if pixmap is None:
            return

        # Convert label coordinates to pixmap/image coordinates.
        label_w = self.image_label.width()
        label_h = self.image_label.height()
        pix_w = pixmap.width()
        pix_h = pixmap.height()

        offset_x = (label_w - pix_w) // 2
        offset_y = (label_h - pix_h) // 2

        x = int(event.position().x()) - offset_x
        y = int(event.position().y()) - offset_y

        if x < 0 or y < 0 or x >= pix_w or y >= pix_h:
            return

        # If displayed pixmap size differs from original preview size, scale back.
        preview_x = round(x * (self.preview_width - 1) / max(1, pix_w - 1))
        preview_y = round(y * (self.preview_height - 1) / max(1, pix_h - 1))

        temp = self.image.temperature_at_preview_xy(
            preview_x,
            preview_y,
            self.preview_width,
            self.preview_height,
        )

        if temp is None:
            temp_text = "N/A"
        else:
            temp_text = f"{temp:.2f} °C"

        tx = round(preview_x * 255 / max(1, self.preview_width - 1))
        ty = round(preview_y * 191 / max(1, self.preview_height - 1))

        self.info_label.setText(
            f"preview=({preview_x}, {preview_y}) | "
            f"thermal=({tx}, {ty}) | "
            f"temperature={temp_text}"
        )
