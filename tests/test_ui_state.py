import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel

from thor_viewer.backend.live_temperature import (
    LIVE_THERMAL_HEIGHT,
    LIVE_THERMAL_WIDTH,
    LiveTemperatureFrame,
)
from thor_viewer.backend.mtp_storage import CapturePair, MtpFile
from thor_viewer.gui.main_window import MainWindow
from thor_viewer.gui.radiometric_image_viewer import RadiometricImageViewer
from thor_viewer.gui.storage_browser import StorageBrowser


class UiStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_storage_actions_require_device_and_selection(self) -> None:
        browser = StorageBrowser()

        self.assertFalse(browser.sync_button.isEnabled())
        self.assertFalse(browser.analyse_button.isEnabled())
        self.assertFalse(browser.save_button.isEnabled())

        browser.set_device_connected(True)
        self.assertTrue(browser.sync_button.isEnabled())
        self.assertFalse(browser.analyse_button.isEnabled())
        self.assertFalse(browser.save_button.isEnabled())

        browser.selected_pair_obj = CapturePair(
            base="20260101010101",
            ir=MtpFile(file_id=1, filename="20260101010101-IR.jpg", size=10),
            dc=MtpFile(file_id=2, filename="20260101010101-DC.jpg", size=20),
        )
        browser.update_action_buttons()

        self.assertTrue(browser.analyse_button.isEnabled())
        self.assertTrue(browser.save_button.isEnabled())

        browser.syncing = True
        browser.update_action_buttons()

        self.assertTrue(browser.sync_button.isEnabled())
        self.assertEqual(browser.sync_button.text(), "Stop syncing")
        self.assertTrue(browser.analyse_button.isEnabled())
        self.assertTrue(browser.save_button.isEnabled())

        browser.syncing = False
        browser.update_action_buttons()

        self.assertEqual(browser.sync_button.text(), "Sync SD card")

    def test_stop_sync_cancels_active_tasks(self) -> None:
        class DummyTask:
            def __init__(self) -> None:
                self.cancelled = False

            def cancel(self) -> None:
                self.cancelled = True

        browser = StorageBrowser()
        refresh_task = DummyTask()
        sync_task = DummyTask()
        browser.current_refresh_task = refresh_task
        browser.current_sync_task = sync_task
        browser.syncing = True
        browser.set_device_connected(True)

        browser.stop_sync()

        self.assertTrue(refresh_task.cancelled)
        self.assertTrue(sync_task.cancelled)
        self.assertEqual(browser.status_label.text(), "Stopping sync...")
        self.assertEqual(browser.sync_button.text(), "Stop syncing")

    def test_analysis_controls_are_disabled_until_image_is_loaded(self) -> None:
        viewer = RadiometricImageViewer()

        self.assertTrue(viewer.open_button.isEnabled())
        self.assertFalse(viewer.overlay_button.isEnabled())
        self.assertFalse(viewer.split_button.isEnabled())
        self.assertFalse(viewer.blend_slider.isEnabled())
        self.assertFalse(viewer.align_button.isEnabled())
        self.assertFalse(viewer.zoom_in_button.isEnabled())
        self.assertIn("Open an image", viewer.image_label.text())
        self.assertIn("Storage", viewer.image_label.text())

    def test_live_hover_maps_label_position_to_preview_coordinates(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.image_label = QLabel()
        window.image_label.resize(800, 600)
        window.image_label.setPixmap(QPixmap(640, 480))
        window.last_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        self.assertEqual(
            window.live_preview_xy_from_label_position(QPointF(400, 300)),
            (320, 240),
        )
        self.assertIsNone(window.live_preview_xy_from_label_position(QPointF(10, 10)))

    def test_live_hover_temperature_label_uses_latest_temperature_frame(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.live_temperature_label = QLabel()
        window.latest_live_hover_preview_xy = None
        window.last_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        k10 = np.zeros((LIVE_THERMAL_HEIGHT, LIVE_THERMAL_WIDTH), dtype="<u2")
        k10[96, 128] = 3098
        window.latest_live_temperature_frame = LiveTemperatureFrame(k10)

        window.update_live_temperature_label((320, 240))

        self.assertIn("thermal=(128, 96)", window.live_temperature_label.text())
        self.assertIn("temperature=36.65 C", window.live_temperature_label.text())

    def test_live_hover_temperature_label_reports_unavailable_data(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.live_temperature_label = QLabel()
        window.last_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        window.latest_live_temperature_frame = None

        window.update_live_temperature_label((320, 240))

        self.assertIn(
            "temperature data unavailable",
            window.live_temperature_label.text(),
        )

    def test_live_temperature_capture_file_replaces_existing_capture(self) -> None:
        class FakeCapture:
            def __init__(self, path: Path) -> None:
                self.path = path
                self.opened = False
                self.closed = False
                self.latest_frame = None

            def open(self) -> None:
                self.opened = True

            def close(self) -> None:
                self.closed = True

        window = MainWindow.__new__(MainWindow)
        window.live_temperature_label = QLabel()
        window.latest_live_temperature_frame = object()
        old_capture = FakeCapture(Path("old.pcapng"))
        window.live_temperature_capture = old_capture

        with patch("thor_viewer.gui.main_window.UsbPcapLiveTemperatureCapture", FakeCapture):
            window.set_live_temperature_capture_file(Path("new.pcapng"))

        self.assertTrue(old_capture.closed)
        self.assertIsNone(window.latest_live_temperature_frame)
        self.assertEqual(window.live_temperature_capture.path, Path("new.pcapng"))
        self.assertTrue(window.live_temperature_capture.opened)


if __name__ == "__main__":
    unittest.main()
