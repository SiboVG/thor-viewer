from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from thor_viewer.backend.radiometric_jpeg import load_radiometric_jpeg


class RadiometricImageViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.image = None
        self.preview_width = 640
        self.preview_height = 480
        self.ir_preview_image: QImage | None = None
        self.visual_image: QImage | None = None

        self.open_button = QPushButton("Open image")
        self.open_button.clicked.connect(self.browse_file)

        self.blend_label = QLabel("0%")
        self.blend_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.blend_label.setFixedWidth(44)
        self.blend_slider = QSlider(Qt.Horizontal)
        self.blend_slider.setRange(0, 100)
        self.blend_slider.setValue(0)
        self.blend_slider.setEnabled(False)
        self.blend_slider.setFixedWidth(180)
        self.blend_slider.valueChanged.connect(self.update_blended_preview)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMouseTracking(True)
        self.image_label.mouseMoveEvent = self.on_mouse_move

        self.info_label = QLabel("Open a radiometric IR image")
        self.info_label.setAlignment(Qt.AlignLeft)

        blend_layout = QHBoxLayout()
        blend_layout.addWidget(QLabel("Blend"))
        blend_layout.addWidget(QLabel("IR"))
        blend_layout.addWidget(self.blend_slider)
        blend_layout.addWidget(QLabel("Visual"))
        blend_layout.addWidget(self.blend_label)
        blend_layout.addStretch()

        layout = QVBoxLayout()
        layout.addWidget(self.open_button)
        layout.addLayout(blend_layout)
        layout.addWidget(self.image_label)
        layout.addWidget(self.info_label)
        self.setLayout(layout)

    def browse_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open IR or visual image",
            "",
            "Images (*.jpg *.jpeg);;All files (*)",
        )

        if not filename:
            return

        self.open_file(Path(filename))

    def open_file(self, path: Path) -> None:
        ir_path = self.ir_path_for(path)

        try:
            self.image = load_radiometric_jpeg(ir_path)
        except Exception as exc:
            QMessageBox.warning(self, "Open image", str(exc))
            return

        qimg = QImage.fromData(self.image.preview_jpeg)
        if qimg.isNull():
            QMessageBox.warning(self, "Open image", "Could not decode IR preview image.")
            return

        self.preview_width = qimg.width()
        self.preview_height = qimg.height()
        self.ir_preview_image = qimg.convertToFormat(QImage.Format_ARGB32)
        self.visual_image = self.load_visual_image(ir_path)

        self.blend_slider.blockSignals(True)
        self.blend_slider.setValue(0)
        self.blend_slider.setEnabled(self.visual_image is not None)
        self.blend_slider.blockSignals(False)
        self.update_blended_preview()

        tmin = self.image.min_temperature()
        tmax = self.image.max_temperature()
        tmin_text = "N/A" if tmin is None else f"{tmin:.2f} °C"
        tmax_text = "N/A" if tmax is None else f"{tmax:.2f} °C"

        self.info_label.setText(
            f"{ir_path.name} | "
            f"{self.preview_width}×{self.preview_height} preview | "
            f"{self.image.temperature.shape[1]}×{self.image.temperature.shape[0]} thermal | "
            f"min={tmin_text} max={tmax_text}"
        )

    def ir_path_for(self, path: Path) -> Path:
        if path.name.endswith("-DC.jpg"):
            return path.with_name(f"{path.name.removesuffix('-DC.jpg')}-IR.jpg")

        return path

    def visual_path_for(self, ir_path: Path) -> Path | None:
        if not ir_path.name.endswith("-IR.jpg"):
            return None

        return ir_path.with_name(f"{ir_path.name.removesuffix('-IR.jpg')}-DC.jpg")

    def load_visual_image(self, ir_path: Path) -> QImage | None:
        visual_path = self.visual_path_for(ir_path)
        if visual_path is None or not visual_path.exists():
            return None

        image = QImage(str(visual_path))
        if image.isNull():
            return None

        return image.scaled(
            self.preview_width,
            self.preview_height,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        ).convertToFormat(QImage.Format_ARGB32)

    def update_blended_preview(self) -> None:
        if self.ir_preview_image is None:
            return

        visual_percent = self.blend_slider.value() if self.visual_image is not None else 0
        self.blend_label.setText(
            f"{visual_percent}%"
            if self.visual_image is not None
            else "N/A"
        )

        if self.visual_image is None or visual_percent == 0:
            self.image_label.setPixmap(QPixmap.fromImage(self.ir_preview_image))
            return

        blended = self.ir_preview_image.copy()
        painter = QPainter(blended)
        painter.setOpacity(visual_percent / 100)
        painter.drawImage(0, 0, self.visual_image)
        painter.end()

        self.image_label.setPixmap(QPixmap.fromImage(blended))

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
