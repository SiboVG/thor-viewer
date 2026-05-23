import sys

from PySide6.QtWidgets import QApplication

from thor_viewer.gui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)

    window = MainWindow()
    window.resize(900, 700)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
