import unittest

import numpy as np

from thor_viewer.gui.main_window import MainWindow


class FakeCameraDevice:
    def __init__(self, description: str, device_id: bytes | str) -> None:
        self._description = description
        self._device_id = device_id

    def description(self) -> str:
        return self._description

    def id(self):
        return self._device_id


class CameraDetectionTest(unittest.TestCase):
    def test_rejects_non_thor_camera_names(self) -> None:
        devices = [
            FakeCameraDevice("FaceTime HD Camera", b"facetime-id"),
            FakeCameraDevice("OBS Virtual Camera", b"obs-id"),
            FakeCameraDevice("External Webcam", b"webcam-id"),
        ]

        for device in devices:
            with self.subTest(device=device.description()):
                self.assertFalse(MainWindow.is_thor_camera_device(device))

    def test_accepts_thor_by_name(self) -> None:
        device = FakeCameraDevice("ThermalMaster Thor", b"generic-id")

        self.assertTrue(MainWindow.is_thor_camera_device(device))
        self.assertEqual(MainWindow.camera_device_label(device), "ThermalMaster Thor")

    def test_accepts_macos_generic_uvc_thor_by_usb_signature(self) -> None:
        device = FakeCameraDevice("UVC Camera 0", b"0x21000001d6b1102")

        self.assertTrue(MainWindow.is_thor_camera_device(device))
        self.assertEqual(MainWindow.camera_device_label(device), "Thor (UVC Camera 0)")

    def test_black_frame_detection(self) -> None:
        black = np.zeros((8, 8, 3), dtype=np.uint8)
        visible = np.full((8, 8, 3), 32, dtype=np.uint8)

        self.assertTrue(MainWindow.is_nearly_black_frame(None, black))
        self.assertFalse(MainWindow.is_nearly_black_frame(None, visible))

    def test_selects_existing_device_id_after_refresh(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.device_combo = FakeComboBox(
            [
                FakeCameraDevice("OBS Virtual Camera", b"obs-id"),
                FakeCameraDevice("UVC Camera 0", b"0x21000001d6b1102"),
            ]
        )

        self.assertEqual(window.combo_index_for_device_id("21000001d6b1102"), 1)

    def test_selects_first_device_when_previous_device_id_disappears(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.device_combo = FakeComboBox(
            [FakeCameraDevice("UVC Camera 0", b"0x21000001d6b1102")]
        )

        self.assertEqual(window.combo_index_for_device_id("missing"), 0)

    def test_refresh_preserves_connection_when_same_device_is_present(self) -> None:
        device = FakeCameraDevice("UVC Camera 0", b"0x21000001d6b1102")
        camera = object()
        window = MainWindow.__new__(MainWindow)
        window.camera = camera
        window.connected_device_id = "21000001d6b1102"
        window.device_combo = FakeComboBox([device])
        window.populate_camera_devices = lambda: None
        window.disconnect_called = False
        window.disconnect_camera = lambda: setattr(window, "disconnect_called", True)
        statuses = []
        window.connected_camera_status = lambda: "Connected to Thor (UVC Camera 0)"
        window.set_camera_connected_ui = lambda connected, status: statuses.append(
            (connected, status)
        )

        window.refresh_camera_devices()

        self.assertIs(window.camera, camera)
        self.assertFalse(window.disconnect_called)
        self.assertEqual(statuses, [(True, "Connected to Thor (UVC Camera 0)")])

    def test_refresh_disconnects_when_connected_device_disappears(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.camera = object()
        window.connected_device_id = "21000001d6b1102"
        window.device_combo = FakeComboBox([])
        window.populate_camera_devices = lambda: None
        window.disconnect_called = False
        window.disconnect_camera = lambda: setattr(window, "disconnect_called", True)
        statuses = []
        window.set_camera_connected_ui = lambda connected, status: statuses.append(
            (connected, status)
        )

        window.refresh_camera_devices()

        self.assertTrue(window.disconnect_called)
        self.assertEqual(statuses, [(False, "No Thor camera found")])


class FakeComboBox:
    def __init__(self, devices: list[FakeCameraDevice]) -> None:
        self.devices = devices
        self.current_index = 0

    def count(self) -> int:
        return len(self.devices)

    def itemData(self, index: int):
        return self.devices[index]

    def currentData(self):
        if not self.devices:
            return None

        return self.devices[self.current_index]


if __name__ == "__main__":
    unittest.main()
