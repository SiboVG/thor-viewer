import unittest
from pathlib import Path

from thor_viewer.backend.mtp_storage import CapturePair, MtpFile
from thor_viewer.gui.storage_browser import StorageBrowser


class StorageExportTest(unittest.TestCase):
    def test_export_paths_use_selected_filename_as_base(self) -> None:
        pair = CapturePair(
            base="20260101010101",
            ir=MtpFile(file_id=1, filename="20260101010101-IR.jpg", size=10),
            dc=MtpFile(file_id=2, filename="20260101010101-DC.jpg", size=20),
        )

        paths = StorageBrowser.export_paths_for_pair(
            Path("/tmp/custom-name.jpg"),
            pair,
        )

        self.assertEqual(paths["ir"], Path("/tmp/custom-name-IR.jpg"))
        self.assertEqual(paths["dc"], Path("/tmp/custom-name-DC.jpg"))

    def test_export_paths_default_to_jpg_suffix(self) -> None:
        pair = CapturePair(
            base="20260101010101",
            ir=MtpFile(file_id=1, filename="20260101010101-IR.jpg", size=10),
            dc=MtpFile(file_id=2, filename="20260101010101-DC.jpg", size=20),
        )

        paths = StorageBrowser.export_paths_for_pair(Path("/tmp/custom-name"), pair)

        self.assertEqual(paths["ir"], Path("/tmp/custom-name-IR.jpg"))
        self.assertEqual(paths["dc"], Path("/tmp/custom-name-DC.jpg"))

    def test_export_paths_skip_missing_visual_image(self) -> None:
        pair = CapturePair(
            base="20260101010101",
            ir=MtpFile(file_id=1, filename="20260101010101-IR.jpg", size=10),
            dc=None,
        )

        paths = StorageBrowser.export_paths_for_pair(
            Path("/tmp/custom-name.jpeg"),
            pair,
        )

        self.assertEqual(paths, {"ir": Path("/tmp/custom-name-IR.jpeg")})


if __name__ == "__main__":
    unittest.main()
