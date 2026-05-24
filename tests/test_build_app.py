import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_app


class BuildAppScriptTest(unittest.TestCase):
    def test_macos_pyinstaller_command_contains_bundle_options(self) -> None:
        with (
            patch.object(build_app.platform, "system", return_value="Darwin"),
            patch.object(
                build_app,
                "build_macos_icns",
                return_value=Path("/tmp/ThorViewer.icns"),
            ),
        ):
            command = build_app.pyinstaller_command(clean=True)

        self.assertEqual(command[:3], [sys.executable, "-m", "PyInstaller"])
        self.assertIn("--windowed", command)
        self.assertIn("--clean", command)
        self.assertIn("--collect-data", command)
        self.assertIn("thor_viewer", command)
        self.assertIn("--specpath", command)
        self.assertIn(str(build_app.GENERATED_DIR), command)
        self.assertIn("--osx-bundle-identifier", command)
        self.assertIn(build_app.BUNDLE_IDENTIFIER, command)
        self.assertIn("--icon", command)
        self.assertIn("/tmp/ThorViewer.icns", command)
        self.assertEqual(command[-1], str(build_app.SOURCE_ENTRY))

    def test_project_version_matches_package_metadata(self) -> None:
        self.assertEqual(build_app.project_version(), "0.1.0")

    def test_windows_pyinstaller_command_uses_ico(self) -> None:
        with (
            patch.object(build_app.platform, "system", return_value="Windows"),
            patch.object(
                build_app,
                "build_windows_ico",
                return_value=Path("C:/tmp/ThorViewer.ico"),
            ),
        ):
            command = build_app.pyinstaller_command(clean=False)

        self.assertNotIn("--clean", command)
        self.assertIn("--windowed", command)
        self.assertIn("--icon", command)
        self.assertIn("C:/tmp/ThorViewer.ico", command)

    def test_linux_pyinstaller_command_uses_svg_icon(self) -> None:
        with patch.object(build_app.platform, "system", return_value="Linux"):
            command = build_app.pyinstaller_command(clean=True)

        self.assertIn("--clean", command)
        self.assertIn("--icon", command)
        self.assertIn(str(build_app.SVG_ICON), command)

    def test_platform_tag_normalizes_macos_and_windows_arch(self) -> None:
        with (
            patch.object(build_app.platform, "system", return_value="Darwin"),
            patch.object(build_app.platform, "machine", return_value="arm64"),
        ):
            self.assertEqual(build_app.platform_tag(), "macos-arm64")

        with (
            patch.object(build_app.platform, "system", return_value="Windows"),
            patch.object(build_app.platform, "machine", return_value="AMD64"),
        ):
            self.assertEqual(build_app.platform_tag(), "windows-x86_64")


if __name__ == "__main__":
    unittest.main()
