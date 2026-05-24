APP_STYLESHEET = """
QWidget {
    background: #0f1115;
    color: #e5e7eb;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #262b36;
    border-radius: 8px;
    background: #151923;
    top: -1px;
}

QTabBar::tab {
    background: #151923;
    color: #9ca3af;
    border: 1px solid #262b36;
    border-bottom: none;
    padding: 8px 14px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

QTabBar::tab:selected {
    background: #1f2937;
    color: #f9fafb;
}

QTabBar::tab:hover {
    color: #f9fafb;
}

QPushButton {
    background: #2563eb;
    color: #ffffff;
    border: 1px solid #3b82f6;
    border-radius: 6px;
    padding: 7px 12px;
}

QPushButton:hover {
    background: #1d4ed8;
}

QPushButton:pressed {
    background: #1e40af;
}

QPushButton:checked {
    background: #0f766e;
    border-color: #14b8a6;
}

QPushButton:disabled {
    background: #1f2937;
    color: #6b7280;
    border-color: #374151;
}

QComboBox,
QSpinBox {
    background: #111827;
    color: #f9fafb;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 8px;
}

QComboBox:disabled,
QSpinBox:disabled {
    color: #6b7280;
    border-color: #2b3240;
}

QScrollArea,
QListWidget {
    background: #0b0d12;
    border: 1px solid #262b36;
    border-radius: 8px;
}

QLabel#statusLabel {
    color: #9ca3af;
    background: transparent;
}

QLabel#imageSurface {
    background: #05070a;
    border: 1px solid #262b36;
    border-radius: 8px;
}

QRadioButton {
    spacing: 6px;
}

QRadioButton::indicator {
    width: 14px;
    height: 14px;
}

QSlider::groove:horizontal {
    height: 4px;
    background: #374151;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: #60a5fa;
}

QListWidget::item {
    color: #f3f4f6;
    background: #151923;
    border: 1px solid #2f3747;
    border-radius: 8px;
    padding: 10px;
}

QListWidget::item:hover {
    background: #1a2230;
}

QListWidget::item:selected {
    background: #1f2937;
    border: 2px solid #3b82f6;
}
"""
