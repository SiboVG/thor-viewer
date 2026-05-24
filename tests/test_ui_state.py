import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from thor_viewer.backend.mtp_storage import CapturePair, MtpFile
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


if __name__ == "__main__":
    unittest.main()
