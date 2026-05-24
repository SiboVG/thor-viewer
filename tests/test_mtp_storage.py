import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thor_viewer.backend.mtp_storage import (
    LibMtpCliStorage,
    MtpFile,
    MtpStorage,
    MtpToolMissingError,
    WindowsShellMtpStorage,
    _clean_powershell_output,
    _parse_windows_files,
    run_command,
)


class MtpStorageTest(unittest.TestCase):
    def test_missing_mtp_files_reports_installable_dependency(self) -> None:
        with patch("thor_viewer.backend.mtp_storage.shutil.which", return_value=None):
            with self.assertRaisesRegex(
                MtpToolMissingError,
                "Storage sync needs MTP support",
            ):
                run_command(["mtp-files"])

    def test_missing_mtp_getfile_reports_installable_dependency(self) -> None:
        file = MtpFile(file_id=1, filename="capture-IR.jpg", size=10)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("thor_viewer.backend.mtp_storage.shutil.which", return_value=None):
                with self.assertRaisesRegex(
                    MtpToolMissingError,
                    "Storage sync needs MTP support",
                ):
                    LibMtpCliStorage().download_file(file, Path(temp_dir))

    def test_launch_file_not_found_is_converted_to_mtp_tool_error(self) -> None:
        with patch("thor_viewer.backend.mtp_storage.shutil.which", return_value="mtp-files"):
            with patch(
                "thor_viewer.backend.mtp_storage.subprocess.run",
                side_effect=FileNotFoundError(),
            ):
                with self.assertRaisesRegex(
                    MtpToolMissingError,
                    "Storage sync needs MTP support",
                ):
                    run_command(["mtp-files"])

    def test_windows_file_parser_preserves_source_path_and_size(self) -> None:
        files = _parse_windows_files(
            {
                "FileId": 1,
                "Filename": "20260222202529-IR.jpg",
                "Size": 336045,
                "SourcePath": "STORAGE/DCIM/20260222202529-IR.jpg",
            }
        )

        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, "20260222202529-IR.jpg")
        self.assertEqual(files[0].size, 336045)
        self.assertEqual(files[0].source_path, "STORAGE/DCIM/20260222202529-IR.jpg")

    def test_storage_uses_windows_backend_on_windows(self) -> None:
        with patch("thor_viewer.backend.mtp_storage.platform.system", return_value="Windows"):
            self.assertIsInstance(MtpStorage()._backend, WindowsShellMtpStorage)

    def test_storage_uses_cli_backend_on_non_windows(self) -> None:
        with patch("thor_viewer.backend.mtp_storage.platform.system", return_value="Linux"):
            self.assertIsInstance(MtpStorage()._backend, LibMtpCliStorage)

    def test_windows_download_resolves_relative_output_dir(self) -> None:
        file = MtpFile(
            file_id=1,
            filename="capture-IR.jpg",
            size=4,
            source_path="STORAGE/DCIM/capture-IR.jpg",
        )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            relative_dir = Path(temp_dir).relative_to(Path.cwd())
            expected_dir = str(relative_dir.resolve())
            expected_encoded = base64.b64encode(expected_dir.encode("utf-8")).decode("ascii")

            def fake_powershell(script: str, cancel_event=None) -> dict[str, int]:
                self.assertIn(expected_encoded, script)
                (relative_dir / file.filename).write_bytes(b"test")
                return {"Size": 4}

            with patch(
                "thor_viewer.backend.mtp_storage.run_windows_powershell_json",
                side_effect=fake_powershell,
            ):
                output = WindowsShellMtpStorage().download_file(file, relative_dir)

        self.assertIsNotNone(output)

    def test_clean_powershell_output_decodes_clixml_errors(self) -> None:
        output = _clean_powershell_output(
            '#< CLIXML\n'
            '<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
            '<S S="Error">Destination folder is unavailable: thor_downloads_x000D__x000A_</S>'
            "</Objs>"
        )

        self.assertEqual(output, "Destination folder is unavailable: thor_downloads")


if __name__ == "__main__":
    unittest.main()
