import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from thor_viewer.app import APP_NAME, ORGANIZATION_NAME, configure_application


class AppMetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_configure_application_sets_display_metadata(self) -> None:
        configure_application(self.app)

        self.assertEqual(self.app.applicationName(), APP_NAME)
        self.assertEqual(self.app.applicationDisplayName(), APP_NAME)
        self.assertEqual(self.app.organizationName(), ORGANIZATION_NAME)
        self.assertEqual(self.app.desktopFileName(), "thor-viewer")


if __name__ == "__main__":
    unittest.main()
