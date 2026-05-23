from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QScrollArea,
    QSlider,
    QButtonGroup,
    QVBoxLayout,
    QWidget,
)

from thor_viewer.backend.radiometric_jpeg import load_radiometric_jpeg


class ImageDisplayLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.preferred_size = QSize(640, 480)

    def set_preferred_size(self, size: QSize) -> None:
        self.preferred_size = size
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return self.preferred_size


class RadiometricImageViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.image = None
        self.preview_width = 640
        self.preview_height = 480
        self.ir_preview_image: QImage | None = None
        self.visual_image: QImage | None = None
        self.display_image: QImage | None = None
        self.zoom_factor = 1.0
        self.fit_to_view = True

        self.open_button = QPushButton("Open image")
        self.open_button.clicked.connect(self.browse_file)

        self.overlay_button = QRadioButton("Overlay")
        self.overlay_button.setChecked(True)
        self.split_button = QRadioButton("Split view")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.overlay_button)
        self.mode_group.addButton(self.split_button)
        self.overlay_button.toggled.connect(self.update_preview)
        self.split_button.toggled.connect(self.update_preview)

        self.blend_label = QLabel("0%")
        self.blend_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.blend_label.setFixedWidth(44)
        self.blend_slider = QSlider(Qt.Horizontal)
        self.blend_slider.setRange(0, 100)
        self.blend_slider.setValue(0)
        self.blend_slider.setEnabled(False)
        self.blend_slider.setFixedWidth(180)
        self.blend_slider.valueChanged.connect(self.update_preview)

        self.zoom_out_button = QPushButton("-")
        self.zoom_out_button.setFixedWidth(32)
        self.zoom_out_button.clicked.connect(self.zoom_out)

        self.zoom_label = QLabel("Fit")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setFixedWidth(48)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setFixedWidth(32)
        self.zoom_in_button.clicked.connect(self.zoom_in)

        self.fit_button = QPushButton("Fit")
        self.fit_button.setFixedWidth(44)
        self.fit_button.clicked.connect(self.fit_zoom)

        self.image_label = ImageDisplayLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMouseTracking(True)
        self.image_label.setMinimumSize(1, 1)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.installEventFilter(self)
        self.image_label.mouseMoveEvent = self.on_mouse_move

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignCenter)
        self.image_scroll.setMinimumSize(640, 360)
        self.image_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.viewport().installEventFilter(self)

        self.info_label = QLabel("Open a radiometric IR image")
        self.info_label.setAlignment(Qt.AlignLeft)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.open_button)
        controls_layout.addWidget(self.overlay_button)
        controls_layout.addWidget(self.split_button)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(QLabel("Blend"))
        controls_layout.addWidget(QLabel("IR"))
        controls_layout.addWidget(self.blend_slider)
        controls_layout.addWidget(QLabel("Visual"))
        controls_layout.addWidget(self.blend_label)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.zoom_out_button)
        controls_layout.addWidget(self.zoom_label)
        controls_layout.addWidget(self.zoom_in_button)
        controls_layout.addWidget(self.fit_button)
        controls_layout.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(controls_layout)
        layout.addWidget(self.image_scroll, 1)
        layout.addWidget(self.info_label)
        self.setLayout(layout)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_display_pixmap()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.image_scroll.viewport() and event.type() == QEvent.Resize:
            self.update_display_pixmap()

        return super().eventFilter(watched, event)

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
        self.blend_slider.blockSignals(False)
        self.fit_to_view = True
        self.zoom_factor = 1.0
        self.update_blend_controls()
        self.update_preview()

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

    def update_preview(self) -> None:
        if self.ir_preview_image is None:
            return

        self.update_blend_controls()
        visual_percent = self.blend_slider.value() if self.visual_image is not None else 0
        self.blend_label.setText(
            f"{visual_percent}%"
            if self.visual_image is not None
            else "N/A"
        )

        if self.split_button.isChecked() and self.visual_image is not None:
            self.display_image = self.split_view_image()
            self.update_image_preferred_size()
            self.update_display_pixmap()
            return

        if self.visual_image is None or visual_percent == 0:
            self.display_image = self.ir_preview_image
            self.update_image_preferred_size()
            self.update_display_pixmap()
            return

        blended = self.ir_preview_image.copy()
        painter = QPainter(blended)
        painter.setOpacity(visual_percent / 100)
        painter.drawImage(0, 0, self.visual_image)
        painter.end()

        self.display_image = blended
        self.update_image_preferred_size()
        self.update_display_pixmap()

    def update_image_preferred_size(self) -> None:
        if self.display_image is None:
            return

        screen = self.screen()
        max_width = 1400
        max_height = 900

        if screen is not None:
            available = screen.availableGeometry()
            max_width = max(640, available.width() - 160)
            max_height = max(360, available.height() - 220)

        source_size = self.display_image.size()
        preferred = source_size.scaled(
            QSize(max_width, max_height),
            Qt.KeepAspectRatio,
        )
        self.image_label.set_preferred_size(preferred)

    def update_display_pixmap(self) -> None:
        if self.display_image is None:
            return

        if self.fit_to_view:
            target_size = self.image_scroll.viewport().size()
        else:
            target_size = self.display_image.size() * self.zoom_factor

        if target_size.width() <= 0 or target_size.height() <= 0:
            return

        pixmap = QPixmap.fromImage(self.display_image).scaled(
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.size())
        self.update_zoom_label()

    def zoom_in(self) -> None:
        if self.display_image is None:
            return

        if self.fit_to_view:
            self.zoom_factor = self.current_fit_scale()

        self.fit_to_view = False
        self.zoom_factor = min(self.zoom_factor * 1.25, 8.0)
        self.update_display_pixmap()

    def zoom_out(self) -> None:
        if self.display_image is None:
            return

        if self.fit_to_view:
            self.zoom_factor = self.current_fit_scale()

        self.fit_to_view = False
        self.zoom_factor = max(self.zoom_factor / 1.25, 0.1)
        self.update_display_pixmap()

    def fit_zoom(self) -> None:
        self.fit_to_view = True
        self.zoom_factor = 1.0
        self.update_display_pixmap()

    def update_zoom_label(self) -> None:
        if self.display_image is None or self.fit_to_view:
            self.zoom_label.setText("Fit")
            return

        self.zoom_label.setText(f"{round(self.zoom_factor * 100)}%")

    def current_fit_scale(self) -> float:
        if self.display_image is None:
            return 1.0

        source_size = self.display_image.size()
        target_size = self.image_scroll.viewport().size()

        if source_size.width() <= 0 or source_size.height() <= 0:
            return 1.0

        return min(
            target_size.width() / source_size.width(),
            target_size.height() / source_size.height(),
        )

    def update_blend_controls(self) -> None:
        self.blend_slider.setEnabled(
            self.visual_image is not None and self.overlay_button.isChecked()
        )

    def split_view_image(self) -> QImage:
        if self.ir_preview_image is None:
            return QImage()

        if self.visual_image is None:
            return self.ir_preview_image

        width = self.preview_width * 2
        height = self.preview_height
        split_image = QImage(width, height, QImage.Format_ARGB32)
        split_image.fill(Qt.black)

        painter = QPainter(split_image)
        painter.drawImage(0, 0, self.ir_preview_image)
        painter.drawImage(self.preview_width, 0, self.visual_image)
        painter.end()

        return split_image

    def on_mouse_move(self, event: QMouseEvent) -> None:
        if self.image is None:
            return

        pixmap = self.image_label.pixmap()
        if pixmap is None:
            return

        pix_w = pixmap.width()
        pix_h = pixmap.height()

        x = int(event.position().x())
        y = int(event.position().y())

        if x < 0 or y < 0 or x >= pix_w or y >= pix_h:
            return

        source_width = self.preview_width
        source_height = self.preview_height

        if self.split_button.isChecked() and self.visual_image is not None:
            source_width = self.preview_width * 2

        source_x = round(x * (source_width - 1) / max(1, pix_w - 1))
        source_y = round(y * (source_height - 1) / max(1, pix_h - 1))

        if self.split_button.isChecked() and self.visual_image is not None:
            if source_x >= self.preview_width:
                return

        preview_x = min(source_x, self.preview_width - 1)
        preview_y = min(source_y, self.preview_height - 1)

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
