import unittest

from thor_viewer.gui.icons import ICON_DIR


class IconAssetsTest(unittest.TestCase):
    def test_used_lucide_icons_and_license_exist(self) -> None:
        icon_names = {
            "activity",
            "camera",
            "download",
            "folder-open",
            "maximize",
            "move",
            "plug",
            "refresh-cw",
            "rotate-ccw",
            "unplug",
            "video",
            "zoom-in",
            "zoom-out",
        }

        self.assertTrue((ICON_DIR / "LICENSE").exists())
        for icon_name in icon_names:
            with self.subTest(icon_name=icon_name):
                self.assertTrue((ICON_DIR / f"{icon_name}.svg").exists())


if __name__ == "__main__":
    unittest.main()
