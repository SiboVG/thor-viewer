from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton


ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "lucide"


def lucide_icon(name: str) -> QIcon:
    return QIcon(str(ICON_DIR / f"{name}.svg"))


def set_button_icon(button: QPushButton, name: str, size: int = 18) -> None:
    button.setIcon(lucide_icon(name))
    button.setIconSize(QSize(size, size))
