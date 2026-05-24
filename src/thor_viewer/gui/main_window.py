from datetime import datetime
import os
import platform
import re
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtMultimedia import (
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoSink,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

from thor_viewer.backend.camera import UvcCamera
from thor_viewer.backend.live_temperature import (
    LiveTemperatureFrame,
    parse_live_temperature_packet,
    preview_to_thermal_xy,
)
from thor_viewer.backend.live_temperature_capture import OpenCvLiveTemperatureCapture
from thor_viewer.backend.recorder import VideoRecorder
from thor_viewer.backend.usbpcap_temperature_capture import UsbPcapLiveTemperatureCapture
from thor_viewer.config.settings import (
    CAPTURE_DIR,
    FPS,
    HEIGHT,
    RECORDING_DIR,
    WIDTH,
)
from thor_viewer.processing.overlays import draw_crosshair, draw_recording_dot
from thor_viewer.gui.storage_browser import StorageBrowser
from thor_viewer.gui.radiometric_image_viewer import RadiometricImageViewer
from thor_viewer.gui.icons import app_icon, set_button_icon


THOR_CAMERA_TERMS = ("thermalmaster", "thermal master", "thor", "thermal")
THOR_CAMERA_USB_SIGNATURES = (
    "1d6b1102",  # RAYSENSE Thor reports as generic "UVC Camera 0" on macOS.
    "vid1d6bpid1102",  # Windows Qt device id: usb#vid_1d6b&pid_1102...
)


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("ThermalMaster Thor Viewer")
        self.setWindowIcon(app_icon())

        CAPTURE_DIR.mkdir(exist_ok=True)
        RECORDING_DIR.mkdir(exist_ok=True)

        self.camera: QCamera | None = None
        self.opencv_camera: UvcCamera | None = None
        self.live_temperature_capture: (
            OpenCvLiveTemperatureCapture
            | UsbPcapLiveTemperatureCapture
            | None
        ) = None
        self.opencv_frame_timer = QTimer(self)
        self.opencv_frame_timer.timeout.connect(self.poll_opencv_camera)
        self.last_opencv_sequence = 0
        self.capture_session = QMediaCaptureSession(self)
        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self.on_video_frame)
        self.capture_session.setVideoSink(self.video_sink)

        self.recorder = VideoRecorder(FPS, (WIDTH, HEIGHT))
        self.last_frame = None
        self.last_frame_sequence = 0
        self.pending_live_restart = False
        self.reported_camera_error: str | None = None
        self.dark_frame_count = 0
        self.connected_device_id: str | None = None
        self.latest_live_temperature_frame: LiveTemperatureFrame | None = None
        self.latest_live_hover_preview_xy: tuple[int, int] | None = None

        self.image_label = QLabel()
        self.image_label.setObjectName("imageSurface")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(640, 360)
        self.image_label.setMouseTracking(True)
        self.image_label.mouseMoveEvent = self.on_live_mouse_move
        self.image_label.leaveEvent = self.on_live_mouse_leave

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(220)
        self.refresh_devices_button = QPushButton("Refresh devices")
        set_button_icon(self.refresh_devices_button, "refresh-cw")
        self.refresh_devices_button.clicked.connect(self.refresh_camera_devices)

        self.live_temperature_file_button = QPushButton("Load temp capture")
        set_button_icon(self.live_temperature_file_button, "folder-open")
        self.live_temperature_file_button.clicked.connect(
            self.select_live_temperature_capture_file
        )

        self.connect_button = QPushButton("Connect")
        set_button_icon(self.connect_button, "plug")
        self.connect_button.clicked.connect(self.connect_selected_camera)

        self.disconnect_button = QPushButton("Disconnect")
        set_button_icon(self.disconnect_button, "unplug")
        self.disconnect_button.clicked.connect(self.disconnect_camera)

        self.camera_status_label = QLabel("Camera disconnected")

        self.snapshot_button = QPushButton("Snapshot")
        set_button_icon(self.snapshot_button, "camera")
        self.snapshot_button.clicked.connect(self.save_snapshot)

        self.record_button = QPushButton("Start recording")
        set_button_icon(self.record_button, "video")
        self.record_button.clicked.connect(self.toggle_recording)

        self.live_temperature_label = QLabel("Hover live image for temperature")
        self.live_temperature_label.setObjectName("statusLabel")

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self.snapshot_button)
        buttons.addWidget(self.record_button)
        buttons.addStretch()

        device_controls = QHBoxLayout()
        device_controls.setContentsMargins(0, 0, 0, 0)
        device_controls.setSpacing(8)
        device_controls.addWidget(QLabel("Device"))
        device_controls.addWidget(self.device_combo)
        device_controls.addWidget(self.refresh_devices_button)
        device_controls.addWidget(self.live_temperature_file_button)
        device_controls.addWidget(self.connect_button)
        device_controls.addWidget(self.disconnect_button)
        device_controls.addWidget(self.camera_status_label)
        device_controls.addStretch()

        self.live_widget = QWidget()
        live_layout = QVBoxLayout()
        live_layout.setContentsMargins(12, 12, 12, 12)
        live_layout.setSpacing(10)
        live_layout.addLayout(device_controls)
        live_layout.addWidget(self.image_label, 1)
        live_layout.addWidget(self.live_temperature_label)
        live_layout.addLayout(buttons)
        self.live_widget.setLayout(live_layout)

        self.radiometric_viewer = RadiometricImageViewer()

        self.storage_browser = StorageBrowser()
        self.storage_browser.open_ir_requested.connect(self.open_ir_image)
        self.storage_browser.sync_finished.connect(self.on_storage_sync_finished)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.live_widget, "Live")
        self.tabs.addTab(self.storage_browser, "Storage")
        self.tabs.addTab(self.radiometric_viewer, "Analysis")
        self.tabs.currentChanged.connect(self.on_tab_changed)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        self.populate_camera_devices()
        self.set_camera_connected_ui(False, "Camera disconnected")
        QTimer.singleShot(0, self.start_camera)

    def on_video_frame(self, video_frame) -> None:
        image = video_frame.toImage()
        if image.isNull():
            return

        rgb_image = image.convertToFormat(QImage.Format_RGB888)
        height = rgb_image.height()
        width = rgb_image.width()
        bytes_per_line = rgb_image.bytesPerLine()
        data = np.frombuffer(rgb_image.constBits(), dtype=np.uint8)
        rgb = data.reshape((height, bytes_per_line))[:, : width * 3]
        rgb = rgb.reshape((height, width, 3)).copy()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        self.handle_camera_frame(frame)

    def handle_camera_frame(self, frame) -> None:
        live_visible = self.tabs.currentWidget() is self.live_widget

        if not live_visible and not self.recorder.is_recording:
            return

        self.last_frame_sequence += 1
        self.last_frame = frame
        self.update_live_temperature_from_frame(frame)

        if self.recorder.is_recording:
            self.recorder.write(frame)

        if not live_visible:
            return

        if self.is_nearly_black_frame(frame):
            self.dark_frame_count += 1
            if self.dark_frame_count >= FPS:
                self.image_label.clear()
                self.image_label.setText("Thor connected, but video stream is black")
                self.set_camera_connected_ui(
                    True,
                    "Thor connected, but video stream is black",
                )
                return
        else:
            if self.dark_frame_count >= FPS:
                self.set_camera_connected_ui(True, self.connected_camera_status())
            self.dark_frame_count = 0

        display = draw_crosshair(frame.copy(), copy=False)

        if self.recorder.is_recording:
            display = draw_recording_dot(display, copy=False)

        self.show_frame(display)

    def populate_camera_devices(self) -> None:
        selected_device_id = self.selected_camera_device_id()

        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        for device in QMediaDevices.videoInputs():
            if self.is_thor_camera_device(device):
                self.device_combo.addItem(
                    self.camera_device_label(device),
                    device,
                )

        if self.device_combo.count() == 0:
            self.device_combo.addItem("No Thor camera found", None)

        combo_index = self.combo_index_for_device_id(selected_device_id)
        if combo_index >= 0:
            self.device_combo.setCurrentIndex(combo_index)

        self.device_combo.blockSignals(False)
        self.update_storage_device_state()

    def update_storage_device_state(self) -> None:
        if hasattr(self, "storage_browser"):
            self.storage_browser.set_device_connected(
                self.selected_camera_device() is not None
            )

    @staticmethod
    def is_thor_camera_device(device) -> bool:
        normalized = device.description().casefold()
        device_id = MainWindow.normalized_camera_device_id(device)
        name_matches = any(term in normalized for term in THOR_CAMERA_TERMS)
        id_matches = any(
            signature in device_id for signature in THOR_CAMERA_USB_SIGNATURES
        )
        return name_matches or id_matches

    @staticmethod
    def normalized_camera_device_id(device) -> str:
        try:
            raw_id = bytes(device.id()).decode(errors="replace")
        except Exception:
            raw_id = str(device.id())

        return re.sub(r"[^a-z0-9]", "", raw_id.casefold().replace("0x", ""))

    @staticmethod
    def camera_device_label(device) -> str:
        name = device.description()
        if any(term in name.casefold() for term in THOR_CAMERA_TERMS):
            return name

        return f"Thor ({name})"

    def combo_index_for_device_id(self, device_id: str | None) -> int:
        if device_id is None:
            return 0 if self.device_combo.count() > 0 else -1

        for index in range(self.device_combo.count()):
            device = self.device_combo.itemData(index)
            if device is None:
                continue

            if self.normalized_camera_device_id(device) == device_id:
                return index

        return 0 if self.device_combo.count() > 0 else -1

    def refresh_camera_devices(self) -> None:
        connected_device_id = self.connected_device_id

        self.populate_camera_devices()
        refreshed_device_id = self.selected_camera_device_id()
        still_connected = (
            self.has_active_camera()
            and connected_device_id is not None
            and connected_device_id == refreshed_device_id
        )
        if still_connected:
            self.set_camera_connected_ui(True, self.connected_camera_status())
            return

        if self.has_active_camera():
            self.disconnect_camera()

        status = (
            "Thor camera found"
            if refreshed_device_id is not None
            else "No Thor camera found"
        )
        self.set_camera_connected_ui(False, status)

    def select_live_temperature_capture_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Thor USBPcap capture",
            str(Path.home()),
            "Capture files (*.pcap *.pcapng);;All files (*)",
        )
        if not file_path:
            return

        self.set_live_temperature_capture_file(Path(file_path))

    def set_live_temperature_capture_file(self, path: Path) -> None:
        self.latest_live_temperature_frame = None

        capture = getattr(self, "live_temperature_capture", None)
        if capture is not None:
            capture.close()

        self.live_temperature_capture = UsbPcapLiveTemperatureCapture(path)
        self.live_temperature_capture.open()
        self.live_temperature_label.setText(self.live_temperature_idle_text())

    def selected_camera_device(self):
        if not hasattr(self, "device_combo"):
            return None

        return self.device_combo.currentData()

    def selected_camera_device_id(self) -> str | None:
        device = self.selected_camera_device()
        if device is None:
            return None

        return self.normalized_camera_device_id(device)

    def connect_selected_camera(self) -> None:
        self.start_camera()

    def disconnect_camera(self) -> None:
        if self.recorder.is_recording:
            self.recorder.stop()
            self.record_button.setText("Start recording")

        self.close_camera()
        self.last_frame_sequence = 0
        self.reported_camera_error = None
        self.dark_frame_count = 0
        self.connected_device_id = None
        self.reset_live_temperature_state()
        self.image_label.clear()
        self.image_label.setText("Camera disconnected")
        self.set_camera_connected_ui(False, "Camera disconnected")

    def set_camera_connected_ui(self, connected: bool, status: str) -> None:
        self.camera_status_label.setText(status)
        self.connect_button.setEnabled(
            not connected and self.selected_camera_device() is not None
        )
        self.disconnect_button.setEnabled(connected)
        self.snapshot_button.setEnabled(connected)
        self.record_button.setEnabled(connected)

    def on_camera_error(self, message: str) -> None:
        self.reported_camera_error = message
        self.dark_frame_count = 0
        self.connected_device_id = None
        self.reset_live_temperature_state()
        self.close_camera()
        self.image_label.clear()
        self.image_label.setText(message)
        self.set_camera_connected_ui(False, message)

    def show_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        height, width, channels = rgb.shape
        bytes_per_line = channels * width

        image = QImage(
            rgb.data,
            width,
            height,
            bytes_per_line,
            QImage.Format_RGB888,
        )

        self.image_label.setPixmap(QPixmap.fromImage(image))

    def reset_live_temperature_state(self) -> None:
        self.latest_live_temperature_frame = None
        self.latest_live_hover_preview_xy = None
        if hasattr(self, "live_temperature_label"):
            self.live_temperature_label.setText(self.live_temperature_idle_text())

    def update_live_temperature_from_frame(self, frame) -> None:
        temperature_frame = self.parse_live_temperature_from_frame(frame)
        if temperature_frame is None:
            return

        self.latest_live_temperature_frame = temperature_frame
        if self.latest_live_hover_preview_xy is not None:
            self.update_live_temperature_label(self.latest_live_hover_preview_xy)

    def parse_live_temperature_from_frame(
        self,
        frame: np.ndarray,
    ) -> LiveTemperatureFrame | None:
        try:
            temperature_frame = parse_live_temperature_packet(frame.tobytes())
        except ValueError:
            return None

        if not self.is_plausible_live_temperature_frame(temperature_frame):
            return None

        return temperature_frame

    @staticmethod
    def is_plausible_live_temperature_frame(frame: LiveTemperatureFrame) -> bool:
        valid = frame.valid_temperature_values()
        return valid.size >= int(frame.k10.size * 0.8)

    def on_live_mouse_move(self, event) -> None:
        preview_xy = self.live_preview_xy_from_label_position(event.position())
        self.update_live_temperature_label(preview_xy)
        event.accept()

    def on_live_mouse_leave(self, event) -> None:
        self.latest_live_hover_preview_xy = None
        self.live_temperature_label.setText("Hover live image for temperature")
        event.accept()

    def live_preview_xy_from_label_position(self, position) -> tuple[int, int] | None:
        pixmap = self.image_label.pixmap()
        frame = self.last_frame
        if pixmap is None or frame is None:
            return None

        pixmap_width = pixmap.width()
        pixmap_height = pixmap.height()
        if pixmap_width <= 0 or pixmap_height <= 0:
            return None

        left = (self.image_label.width() - pixmap_width) / 2
        top = (self.image_label.height() - pixmap_height) / 2
        pixmap_x = float(position.x()) - left
        pixmap_y = float(position.y()) - top

        if (
            pixmap_x < 0
            or pixmap_y < 0
            or pixmap_x >= pixmap_width
            or pixmap_y >= pixmap_height
        ):
            return None

        frame_height, frame_width = frame.shape[:2]
        preview_x = round(pixmap_x * (frame_width - 1) / max(1, pixmap_width - 1))
        preview_y = round(pixmap_y * (frame_height - 1) / max(1, pixmap_height - 1))

        return (
            min(frame_width - 1, max(0, preview_x)),
            min(frame_height - 1, max(0, preview_y)),
        )

    def update_live_temperature_label(
        self,
        preview_xy: tuple[int, int] | None,
    ) -> None:
        self.latest_live_hover_preview_xy = preview_xy
        if preview_xy is None:
            self.live_temperature_label.setText("Hover live image for temperature")
            return

        preview_x, preview_y = preview_xy
        frame = self.last_frame
        if frame is None:
            self.live_temperature_label.setText("No live frame")
            return

        frame_height, frame_width = frame.shape[:2]
        thermal_x, thermal_y = preview_to_thermal_xy(
            preview_x,
            preview_y,
            frame_width,
            frame_height,
        )

        temperature_frame = self.latest_live_temperature_frame
        if temperature_frame is None:
            self.live_temperature_label.setText(
                f"preview=({preview_x}, {preview_y}) | "
                f"thermal=({thermal_x}, {thermal_y}) | "
                f"temperature data unavailable | {self.live_temperature_idle_text()}"
            )
            return

        temperature = temperature_frame.temperature_at_preview_xy(
            preview_x,
            preview_y,
            frame_width,
            frame_height,
        )
        temperature_text = "N/A" if temperature is None else f"{temperature:.2f} C"
        self.live_temperature_label.setText(
            f"preview=({preview_x}, {preview_y}) | "
            f"thermal=({thermal_x}, {thermal_y}) | "
            f"temperature={temperature_text}"
        )

    def is_nearly_black_frame(self, frame) -> bool:
        return frame.mean() < 2 and frame.std() < 3

    def on_tab_changed(self, index: int) -> None:
        current = self.tabs.currentWidget()

        if current is self.storage_browser:
            self.pending_live_restart = False
            self.stop_camera()
            self.storage_browser.activate()
            return

        self.storage_browser.deactivate()

        if current is self.live_widget:
            if self.storage_browser.syncing:
                self.pending_live_restart = True
                self.image_label.clear()
                self.image_label.setText("Pausing storage sync...")
                return

            self.start_camera()
            return

        self.pending_live_restart = False
        self.stop_camera()

    def on_storage_sync_finished(self) -> None:
        if self.pending_live_restart and self.tabs.currentWidget() is self.live_widget:
            self.pending_live_restart = False
            self.start_camera()

    def start_camera(self) -> None:
        if self.tabs.currentWidget() is not self.live_widget:
            return

        if self.storage_browser.syncing:
            self.pending_live_restart = True
            return

        if self.has_active_camera():
            return

        selected_device = self.selected_camera_device()
        if selected_device is None:
            self.image_label.clear()
            self.image_label.setText("No Thor camera found")
            self.set_camera_connected_ui(False, "No Thor camera found")
            return

        if self.should_use_opencv_live_camera():
            try:
                camera_index = self.camera_index_for_device(selected_device)
                opencv_camera = UvcCamera(camera_index, WIDTH, HEIGHT, FPS)
                opencv_camera.open()
            except Exception as exc:
                self.on_camera_error(str(exc))
                return

            self.opencv_camera = opencv_camera
            self.live_temperature_capture = self.create_live_temperature_capture(
                camera_index,
                len(QMediaDevices.videoInputs()),
            )
            if self.live_temperature_capture is not None:
                self.live_temperature_capture.open()
            self.last_opencv_sequence = 0
            self.opencv_frame_timer.start(max(1, round(1000 / FPS)))
            self.last_frame_sequence = 0
            self.reported_camera_error = None
            self.dark_frame_count = 0
            self.reset_live_temperature_state()
            self.connected_device_id = self.normalized_camera_device_id(selected_device)
            self.set_camera_connected_ui(True, self.connected_camera_status())
            return

        self.camera = QCamera(selected_device, self)
        self.camera.errorOccurred.connect(self.on_qcamera_error)
        self.capture_session.setCamera(self.camera)
        self.camera.start()

        self.last_frame_sequence = 0
        self.reported_camera_error = None
        self.dark_frame_count = 0
        self.reset_live_temperature_state()
        self.connected_device_id = self.normalized_camera_device_id(selected_device)
        self.set_camera_connected_ui(True, self.connected_camera_status())

    def on_qcamera_error(self, error, message: str) -> None:
        if message:
            self.on_camera_error(message)
        else:
            self.on_camera_error(str(error))

    def poll_opencv_camera(self) -> None:
        opencv_camera = self.opencv_camera
        if opencv_camera is None:
            return

        error_message = opencv_camera.error_message
        if error_message is not None:
            self.on_camera_error(error_message)
            return

        latest = opencv_camera.read_latest()
        if latest is None:
            return

        sequence, frame = latest
        if sequence == self.last_opencv_sequence:
            self.update_live_temperature_from_capture()
            return

        self.last_opencv_sequence = sequence
        self.update_live_temperature_from_capture()
        self.handle_camera_frame(frame)

    def update_live_temperature_from_capture(self) -> None:
        capture = self.live_temperature_capture
        if capture is None:
            return

        temperature_frame = capture.latest_frame
        if temperature_frame is None:
            if self.latest_live_hover_preview_xy is None:
                self.live_temperature_label.setText(self.live_temperature_idle_text())
            else:
                self.update_live_temperature_label(self.latest_live_hover_preview_xy)
            return

        self.latest_live_temperature_frame = temperature_frame
        if self.latest_live_hover_preview_xy is not None:
            self.update_live_temperature_label(self.latest_live_hover_preview_xy)
        else:
            self.live_temperature_label.setText("Temperature stream ready; hover live image")

    def has_active_camera(self) -> bool:
        return (
            getattr(self, "camera", None) is not None
            or getattr(self, "opencv_camera", None) is not None
        )

    def should_use_opencv_live_camera(self) -> bool:
        return platform.system() == "Windows"

    def should_probe_opencv_live_temperature(self) -> bool:
        return os.environ.get("THOR_PROBE_LIVE_TEMPERATURE") == "1"

    def create_live_temperature_capture(
        self,
        camera_index: int,
        device_count: int,
    ) -> OpenCvLiveTemperatureCapture | UsbPcapLiveTemperatureCapture | None:
        usbpcap_path = self.live_temperature_pcap_path()
        if usbpcap_path is not None:
            return UsbPcapLiveTemperatureCapture(usbpcap_path)

        if self.should_probe_opencv_live_temperature():
            return OpenCvLiveTemperatureCapture(
                self.live_temperature_candidate_indices(camera_index, device_count),
                WIDTH,
                HEIGHT,
                FPS,
            )

        return None

    def live_temperature_pcap_path(self) -> Path | None:
        raw_path = os.environ.get("THOR_LIVE_TEMPERATURE_PCAP")
        if not raw_path:
            return None

        return Path(raw_path)

    def live_temperature_idle_text(self) -> str:
        capture = getattr(self, "live_temperature_capture", None)
        if capture is None:
            return "Hover live image for temperature"

        status = getattr(capture, "status", None)
        if status is None:
            return "Temperature stream probing; hover live image"

        return (
            f"Temperature: {status.message} | "
            f"bytes={status.bytes_read} | "
            f"marker={'yes' if status.marker_seen else 'no'} | "
            f"frame={'yes' if status.frame_seen else 'no'}"
        )

    def camera_index_for_device(self, selected_device) -> int:
        selected_id = self.normalized_camera_device_id(selected_device)
        for index, device in enumerate(QMediaDevices.videoInputs()):
            if self.normalized_camera_device_id(device) == selected_id:
                return index

        return 0

    @staticmethod
    def live_temperature_candidate_indices(
        camera_index: int,
        device_count: int | None = None,
    ) -> list[int]:
        candidates = [
            camera_index + 1,
            camera_index + 2,
            camera_index - 1,
            camera_index - 2,
            camera_index,
        ]
        return list(
            dict.fromkeys(
                index
                for index in candidates
                if index >= 0 and (device_count is None or index < device_count)
            )
        )

    def connected_camera_status(self) -> str:
        device_name = self.device_combo.currentText()
        if device_name:
            return f"Connected to {device_name}"

        return "Connected to camera"

    def stop_camera(self) -> None:
        if self.recorder.is_recording:
            return

        self.close_camera()
        self.dark_frame_count = 0
        self.connected_device_id = None
        self.set_camera_connected_ui(False, "Camera disconnected")

    def close_camera(self) -> None:
        camera = self.camera
        self.camera = None

        opencv_camera = getattr(self, "opencv_camera", None)
        self.opencv_camera = None
        self.last_opencv_sequence = 0
        if hasattr(self, "opencv_frame_timer"):
            self.opencv_frame_timer.stop()
        if opencv_camera is not None:
            opencv_camera.close()

        live_temperature_capture = getattr(self, "live_temperature_capture", None)
        self.live_temperature_capture = None
        if live_temperature_capture is not None:
            live_temperature_capture.close()

        if camera is None:
            return

        camera.stop()
        self.capture_session.setCamera(None)
        camera.deleteLater()

    def save_snapshot(self) -> None:
        if self.last_frame is None:
            return

        filename = datetime.now().strftime("thor_%Y%m%d_%H%M%S.png")
        path = CAPTURE_DIR / filename

        cv2.imwrite(str(path), self.last_frame)
        print(f"Saved {path}")

    def toggle_recording(self) -> None:
        if self.recorder.is_recording:
            self.recorder.stop()
            self.record_button.setText("Start recording")
            print("Recording stopped")
            return

        filename = datetime.now().strftime("thor_%Y%m%d_%H%M%S.mp4")
        path = RECORDING_DIR / filename

        self.recorder.start(path)
        self.record_button.setText("Stop recording")
        print(f"Recording {path}")

    def open_ir_image(self, path) -> None:
        self.radiometric_viewer.open_file(path)

        # Switch to Analysis tab if you store tabs as self.tabs
        self.tabs.setCurrentWidget(self.radiometric_viewer)

    def closeEvent(self, event) -> None:
        self.recorder.stop()
        self.close_camera()
        event.accept()
