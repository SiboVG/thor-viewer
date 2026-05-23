from datetime import datetime

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

from thor_viewer.backend.camera import UvcCamera
from thor_viewer.backend.recorder import VideoRecorder
from thor_viewer.config.settings import (
    CAMERA_INDEX,
    CAPTURE_DIR,
    FPS,
    HEIGHT,
    RECORDING_DIR,
    WIDTH,
)
from thor_viewer.processing.overlays import draw_crosshair, draw_recording_dot
from thor_viewer.gui.storage_browser import StorageBrowser
from thor_viewer.gui.radiometric_image_viewer import RadiometricImageViewer


THOR_CAMERA_TERMS = ("thermalmaster", "thermal master", "thor", "thermal")


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("ThermalMaster Thor Viewer")

        CAPTURE_DIR.mkdir(exist_ok=True)
        RECORDING_DIR.mkdir(exist_ok=True)

        self.camera = UvcCamera(CAMERA_INDEX, WIDTH, HEIGHT, FPS)

        self.recorder = VideoRecorder(FPS, (WIDTH, HEIGHT))
        self.last_frame = None
        self.last_frame_sequence = 0
        self.pending_live_restart = False
        self.reported_camera_error: str | None = None

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)

        self.device_combo = QComboBox()
        self.refresh_devices_button = QPushButton("Refresh devices")
        self.refresh_devices_button.clicked.connect(self.refresh_camera_devices)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_selected_camera)

        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_camera)

        self.camera_status_label = QLabel("Camera disconnected")

        self.snapshot_button = QPushButton("Snapshot")
        self.snapshot_button.clicked.connect(self.save_snapshot)

        self.record_button = QPushButton("Start recording")
        self.record_button.clicked.connect(self.toggle_recording)

        buttons = QHBoxLayout()
        buttons.addWidget(self.snapshot_button)
        buttons.addWidget(self.record_button)

        device_controls = QHBoxLayout()
        device_controls.addWidget(QLabel("Device"))
        device_controls.addWidget(self.device_combo)
        device_controls.addWidget(self.refresh_devices_button)
        device_controls.addWidget(self.connect_button)
        device_controls.addWidget(self.disconnect_button)
        device_controls.addWidget(self.camera_status_label)
        device_controls.addStretch()

        self.live_widget = QWidget()
        live_layout = QVBoxLayout()
        live_layout.addLayout(device_controls)
        live_layout.addWidget(self.image_label)
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
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(round(1000 / FPS))
        self.populate_camera_devices()
        self.set_camera_connected_ui(False, "Camera disconnected")
        QTimer.singleShot(0, self.start_camera)

    def update_frame(self) -> None:
        live_visible = self.tabs.currentWidget() is self.live_widget

        if not live_visible and not self.recorder.is_recording:
            return

        latest = self.camera.read_latest()
        if latest is None:
            error = self.camera.error_message
            if error is not None and error != self.reported_camera_error:
                self.on_camera_error(error)
            return

        sequence, frame = latest
        if sequence == self.last_frame_sequence:
            return

        self.last_frame_sequence = sequence
        self.last_frame = frame

        if self.recorder.is_recording:
            self.recorder.write(frame)

        if not live_visible:
            return

        display = draw_crosshair(frame.copy(), copy=False)

        if self.recorder.is_recording:
            display = draw_recording_dot(display, copy=False)

        self.show_frame(display)

    def populate_camera_devices(self) -> None:
        selected_index = self.selected_camera_index()

        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        for index, device in enumerate(QMediaDevices.videoInputs()):
            name = device.description()
            if self.is_thor_camera_name(name):
                self.device_combo.addItem(name, index)

        if self.device_combo.count() == 0:
            self.device_combo.addItem("No Thor camera found", None)

        index_to_select = selected_index if selected_index is not None else CAMERA_INDEX
        combo_index = self.device_combo.findData(index_to_select)
        if combo_index >= 0:
            self.device_combo.setCurrentIndex(combo_index)

        self.device_combo.blockSignals(False)

    def is_thor_camera_name(self, name: str) -> bool:
        normalized = name.casefold()
        return any(term in normalized for term in THOR_CAMERA_TERMS)

    def refresh_camera_devices(self) -> None:
        connected = self.camera.is_open
        if connected:
            self.disconnect_camera()

        self.populate_camera_devices()
        status = (
            "Thor camera found"
            if self.selected_camera_index() is not None
            else "No Thor camera found"
        )
        self.set_camera_connected_ui(False, status)

    def selected_camera_index(self) -> int | None:
        if not hasattr(self, "device_combo"):
            return CAMERA_INDEX

        index = self.device_combo.currentData()
        if index is None:
            return None

        return int(index)

    def connect_selected_camera(self) -> None:
        self.start_camera()

    def disconnect_camera(self) -> None:
        if self.recorder.is_recording:
            self.recorder.stop()
            self.record_button.setText("Start recording")

        self.camera.close()
        self.last_frame_sequence = 0
        self.reported_camera_error = None
        self.image_label.clear()
        self.image_label.setText("Camera disconnected")
        self.set_camera_connected_ui(False, "Camera disconnected")

    def set_camera_connected_ui(self, connected: bool, status: str) -> None:
        self.camera_status_label.setText(status)
        self.connect_button.setEnabled(not connected and self.selected_camera_index() is not None)
        self.disconnect_button.setEnabled(connected)
        self.snapshot_button.setEnabled(connected)
        self.record_button.setEnabled(connected)

    def on_camera_error(self, message: str) -> None:
        self.reported_camera_error = message
        self.camera.close()
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

        if self.camera.is_open:
            return

        selected_index = self.selected_camera_index()
        if selected_index is None:
            self.image_label.clear()
            self.image_label.setText("No Thor camera found")
            self.set_camera_connected_ui(False, "No Thor camera found")
            return

        self.camera.set_index(selected_index)

        try:
            self.camera.open()
        except RuntimeError as exc:
            self.image_label.clear()
            self.image_label.setText(f"Camera unavailable: {exc}")
            self.set_camera_connected_ui(False, f"Camera unavailable: {exc}")
            return

        self.last_frame_sequence = 0
        self.reported_camera_error = None
        self.set_camera_connected_ui(True, f"Connected to camera {selected_index}")

    def stop_camera(self) -> None:
        if self.recorder.is_recording:
            return

        self.camera.close()
        self.set_camera_connected_ui(False, "Camera disconnected")

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
        self.camera.close()
        event.accept()
