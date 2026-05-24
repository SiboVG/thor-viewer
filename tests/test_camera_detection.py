import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from thor_viewer.gui.main_window import MainWindow
from thor_viewer.backend.usbpcap_temperature_capture import UsbPcapLiveTemperatureCapture


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

    def test_accepts_windows_generic_uvc_thor_by_usb_signature(self) -> None:
        device = FakeCameraDevice(
            "UVC Camera 0",
            rb"\\?\usb#vid_1d6b&pid_1102&mi_03#b&9913074&0&0003#",
        )

        self.assertTrue(MainWindow.is_thor_camera_device(device))
        self.assertEqual(MainWindow.camera_device_label(device), "Thor (UVC Camera 0)")

    def test_black_frame_detection(self) -> None:
        black = np.zeros((8, 8, 3), dtype=np.uint8)
        visible = np.full((8, 8, 3), 32, dtype=np.uint8)

        self.assertTrue(MainWindow.is_nearly_black_frame(None, black))
        self.assertFalse(MainWindow.is_nearly_black_frame(None, visible))

    def test_windows_live_camera_uses_opencv_backend(self) -> None:
        window = MainWindow.__new__(MainWindow)

        with patch("thor_viewer.gui.main_window.platform.system", return_value="Windows"):
            self.assertTrue(window.should_use_opencv_live_camera())

    def test_non_windows_live_camera_uses_qt_backend(self) -> None:
        window = MainWindow.__new__(MainWindow)

        with patch("thor_viewer.gui.main_window.platform.system", return_value="Darwin"):
            self.assertFalse(window.should_use_opencv_live_camera())

    def test_live_temperature_probe_is_opt_in(self) -> None:
        window = MainWindow.__new__(MainWindow)

        with patch.dict("thor_viewer.gui.main_window.os.environ", {}, clear=True):
            self.assertFalse(window.should_probe_opencv_live_temperature())

        with patch.dict(
            "thor_viewer.gui.main_window.os.environ",
            {"THOR_PROBE_LIVE_TEMPERATURE": "1"},
            clear=True,
        ):
            self.assertTrue(window.should_probe_opencv_live_temperature())

    def test_live_temperature_pcap_file_source_is_opt_in(self) -> None:
        window = MainWindow.__new__(MainWindow)

        with patch.dict("thor_viewer.gui.main_window.os.environ", {}, clear=True):
            self.assertIsNone(window.live_temperature_pcap_path())

        with patch.dict(
            "thor_viewer.gui.main_window.os.environ",
            {"THOR_LIVE_TEMPERATURE_PCAP": "C:\\Temp\\thor-live.pcapng"},
            clear=True,
        ):
            self.assertEqual(
                window.live_temperature_pcap_path(),
                Path("C:\\Temp\\thor-live.pcapng"),
            )

    def test_usbpcap_file_source_takes_precedence_over_opencv_probe(self) -> None:
        window = MainWindow.__new__(MainWindow)

        with patch.dict(
            "thor_viewer.gui.main_window.os.environ",
            {
                "THOR_LIVE_TEMPERATURE_PCAP": "C:\\Temp\\thor-live.pcapng",
                "THOR_PROBE_LIVE_TEMPERATURE": "1",
            },
            clear=True,
        ):
            capture = window.create_live_temperature_capture(0, 1)

        self.assertIsInstance(capture, UsbPcapLiveTemperatureCapture)

    def test_camera_index_for_device_uses_qt_device_order(self) -> None:
        window = MainWindow.__new__(MainWindow)
        webcam = FakeCameraDevice("External Webcam", b"webcam-id")
        thor = FakeCameraDevice(
            "UVC Camera 0",
            rb"\\?\usb#vid_1d6b&pid_1102&mi_03#b&9913074&0&0003#",
        )

        with patch(
            "thor_viewer.gui.main_window.QMediaDevices.videoInputs",
            return_value=[webcam, thor],
        ):
            self.assertEqual(window.camera_index_for_device(thor), 1)

    def test_live_temperature_candidates_prefer_adjacent_interfaces(self) -> None:
        self.assertEqual(
            MainWindow.live_temperature_candidate_indices(2),
            [3, 4, 1, 0, 2],
        )
        self.assertEqual(
            MainWindow.live_temperature_candidate_indices(0),
            [1, 2, 0],
        )

    def test_live_temperature_candidates_stay_inside_device_count(self) -> None:
        self.assertEqual(
            MainWindow.live_temperature_candidate_indices(0, device_count=1),
            [0],
        )
        self.assertEqual(
            MainWindow.live_temperature_candidate_indices(1, device_count=3),
            [2, 0, 1],
        )

    def test_has_active_camera_accepts_qt_or_opencv_backend(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.camera = None
        window.opencv_camera = None

        self.assertFalse(window.has_active_camera())

        window.opencv_camera = object()
        self.assertTrue(window.has_active_camera())

        window.opencv_camera = None
        window.camera = object()
        self.assertTrue(window.has_active_camera())

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
