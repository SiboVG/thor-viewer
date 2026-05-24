import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from thor_viewer.gui.icons import app_icon
from thor_viewer.gui.main_window import MainWindow
from thor_viewer.gui.theme import APP_STYLESHEET


APP_NAME = "Thor Viewer"
ORGANIZATION_NAME = "Thor Viewer"


def install_exception_hook() -> None:
    def handle_exception(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return

        traceback.print_exception(exc_type, exc, tb)
        message = "".join(traceback.format_exception_only(exc_type, exc)).strip()
        QMessageBox.critical(None, "Thor Viewer error", message)

    sys.excepthook = handle_exception


def configure_application(app: QApplication) -> None:
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setDesktopFileName("thor-viewer")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(APP_STYLESHEET)


def main() -> None:
    install_exception_hook()
    app = QApplication(sys.argv)
    configure_application(app)

    window = MainWindow()
    window.resize(900, 700)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
