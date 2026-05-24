from __future__ import annotations

import shutil
from collections import deque
from pathlib import Path
from threading import Event

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thor_viewer.backend.mtp_storage import (
    CapturePair,
    MtpCancelledError,
    MtpDisconnectedError,
    MtpNotFoundError,
    MtpStorage,
)
from thor_viewer.gui.icons import set_button_icon


DOWNLOAD_DIR = Path("thor_downloads")
THUMB_WIDTH = 180
THUMB_HEIGHT = 135
ITEM_WIDTH = THUMB_WIDTH + 44
ITEM_HEIGHT = THUMB_HEIGHT + 78
EXPORT_DIR_SETTING = "storage/export_dir"
EXPORT_FILENAME_SETTING = "storage/export_filename"


class TaskSignals(QObject):
    pairs_loaded = Signal(list)
    download_done = Signal(list)
    download_progress = Signal(object, list)
    cancelled = Signal()
    error = Signal(str)


class RefreshTask(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = TaskSignals()
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            pairs = MtpStorage().list_capture_pairs(cancel_event=self.cancel_event)
            self.signals.pairs_loaded.emit(pairs)
        except MtpCancelledError:
            self.signals.cancelled.emit()
        except MtpNotFoundError:
            self.signals.error.emit("No Thor MTP device found. Wake or power-cycle the Thor.")
        except Exception as exc:
            self.signals.error.emit(str(exc))


class SyncMissingTask(QRunnable):
    def __init__(self, pairs: list[CapturePair], output_dir: Path) -> None:
        super().__init__()
        self.pairs = pairs
        self.output_dir = output_dir
        self.signals = TaskSignals()
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            storage = MtpStorage()
            paths: list[Path] = []

            for pair in self.pairs:
                if self.cancel_event.is_set():
                    self.signals.cancelled.emit()
                    return

                pair_paths: list[Path] = []

                for file in (pair.ir, pair.dc):
                    if self.cancel_event.is_set():
                        self.signals.cancelled.emit()
                        return

                    if file is None:
                        continue

                    output_path = self.output_dir / file.filename
                    if output_path.exists() and output_path.stat().st_size == file.size:
                        continue

                    path = storage.download_file(
                        file,
                        self.output_dir,
                        cancel_event=self.cancel_event,
                    )
                    if self.cancel_event.is_set():
                        self.signals.cancelled.emit()
                        return

                    if path is not None:
                        paths.append(path)
                        pair_paths.append(path)

                if pair_paths:
                    self.signals.download_progress.emit(pair, pair_paths)

            self.signals.download_done.emit(paths)
        except MtpDisconnectedError:
            self.signals.error.emit(
                "Thor disconnected during transfer. Wake/power-cycle it and retry."
            )
        except Exception as exc:
            self.signals.error.emit(str(exc))


class StorageBrowser(QWidget):
    open_ir_requested = Signal(Path)
    sync_finished = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.thread_pool = QThreadPool.globalInstance()
        self.pairs: list[CapturePair] = []
        self.items_by_pair: dict[CapturePair, QListWidgetItem] = {}
        self.selected_pair_obj: CapturePair | None = None
        self.thumbnail_queue: deque[CapturePair] = deque()
        self.text_icons: dict[tuple[str, str], QIcon] = {}
        self.has_synced = False
        self.syncing = False
        self.current_refresh_task: RefreshTask | None = None
        self.current_sync_task: SyncMissingTask | None = None
        self.active = False
        self.device_connected = False
        self.settings = QSettings("ThorViewer", "ThorViewer")

        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.timeout.connect(self.load_next_thumbnail_batch)

        self.status_label = QLabel("Open Storage to sync Thor SD card")
        self.status_label.setObjectName("statusLabel")

        self.sync_button = QPushButton("Sync SD card")
        set_button_icon(self.sync_button, "refresh-cw")
        self.sync_button.clicked.connect(self.sync)

        self.analyse_button = QPushButton("Analyse selected")
        set_button_icon(self.analyse_button, "activity")
        self.analyse_button.clicked.connect(self.analyse_selected)

        self.save_button = QPushButton("Save selected...")
        set_button_icon(self.save_button, "download")
        self.save_button.clicked.connect(self.save_selected)
        self.update_action_buttons()

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(self.sync_button)
        top.addWidget(self.analyse_button)
        top.addWidget(self.save_button)
        top.addStretch()

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setMovement(QListView.Static)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setFlow(QListView.LeftToRight)
        self.grid.setWrapping(True)
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.setIconSize(QSize(THUMB_WIDTH, THUMB_HEIGHT))
        self.grid.setGridSize(QSize(ITEM_WIDTH, ITEM_HEIGHT))
        self.grid.setSpacing(14)
        self.grid.setWordWrap(True)
        self.grid.setTextElideMode(Qt.ElideRight)
        self.grid.itemSelectionChanged.connect(self.on_selection_changed)
        self.grid.itemDoubleClicked.connect(self.analyse_item)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(self.grid)
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def activate(self) -> None:
        self.active = True
        if not self.device_connected:
            self.status_label.setText("Connect a Thor device to sync the SD card")
            self.update_action_buttons()
            return

        if not self.has_synced and not self.syncing:
            self.sync()

    def deactivate(self) -> None:
        self.active = False
        if self.current_refresh_task is not None:
            self.current_refresh_task.cancel()
        if self.current_sync_task is not None:
            self.current_sync_task.cancel()

    def sync(self) -> None:
        if self.syncing or not self.device_connected:
            if not self.device_connected:
                self.status_label.setText("Connect a Thor device to sync the SD card")
                self.update_action_buttons()
            return

        self.status_label.setText("Syncing Thor SD card...")
        self.syncing = True
        self.update_action_buttons()

        task = RefreshTask()
        self.current_refresh_task = task
        task.signals.pairs_loaded.connect(self.set_pairs)
        task.signals.cancelled.connect(self.on_sync_cancelled)
        task.signals.error.connect(self.on_error)

        self.thread_pool.start(task)

    def set_pairs(self, pairs: list[CapturePair]) -> None:
        self.current_refresh_task = None
        self.pairs = pairs
        self.selected_pair_obj = None
        self.rebuild_grid()
        self.update_action_buttons()

        if not self.active:
            self.syncing = False
            self.update_action_buttons()
            self.status_label.setText("Sync paused; open Storage to continue")
            self.sync_finished.emit()
            return

        missing = self.missing_file_count()
        self.status_label.setText(
            f"Found {len(pairs)} captures; downloading {missing} missing file(s)..."
            if missing
            else f"Found {len(pairs)} captures; all files are local"
        )

        if missing:
            task = SyncMissingTask(self.pairs, DOWNLOAD_DIR)
            self.current_sync_task = task
            task.signals.download_progress.connect(self.on_download_progress)
            task.signals.download_done.connect(self.on_sync_done)
            task.signals.cancelled.connect(self.on_sync_cancelled)
            task.signals.error.connect(self.on_error)

            self.thread_pool.start(task)
            return

        self.on_sync_done([])

    def rebuild_grid(self) -> None:
        self.thumbnail_timer.stop()
        self.items_by_pair = {}
        self.thumbnail_queue.clear()

        self.grid.setUpdatesEnabled(False)
        try:
            self.grid.clear()

            for pair in self.pairs:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, pair)
                item.setText(self.item_text(pair))
                item.setIcon(self.placeholder_icon(pair))
                item.setSizeHint(QSize(ITEM_WIDTH, ITEM_HEIGHT))

                self.grid.addItem(item)
                self.items_by_pair[pair] = item
        finally:
            self.grid.setUpdatesEnabled(True)

        self.thumbnail_queue = deque(
            pair
            for pair in self.pairs
            if pair.ir is not None and (DOWNLOAD_DIR / pair.ir.filename).exists()
        )

        self.thumbnail_timer.start(20)

    def item_text(self, pair: CapturePair) -> str:
        if pair.ir is None:
            status = "No IR image"
        elif self.is_pair_downloaded(pair):
            status = "Ready"
        else:
            status = "Syncing..."

        return f"{pair.base}\n{status}"

    def placeholder_icon(self, pair: CapturePair) -> QIcon:
        if pair.ir is None:
            return self.text_icon("No IR", "#aaaaaa")

        if (DOWNLOAD_DIR / pair.ir.filename).exists():
            return self.text_icon("Downloaded", "#aaaaaa")

        return self.text_icon("Syncing...", "#aaaaaa")

    def text_icon(self, text: str, color: str) -> QIcon:
        key = (text, color)
        icon = self.text_icons.get(key)
        if icon is not None:
            return icon

        pixmap = QPixmap(THUMB_WIDTH, THUMB_HEIGHT)
        pixmap.fill(QColor("#222222"))

        painter = QPainter(pixmap)
        painter.setPen(QColor(color))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
        painter.end()

        icon = QIcon(pixmap)
        self.text_icons[key] = icon

        return icon

    def on_selection_changed(self) -> None:
        selected_items = self.grid.selectedItems()
        if not selected_items:
            self.selected_pair_obj = None
            self.update_action_buttons()
            return

        pair = selected_items[0].data(Qt.UserRole)
        self.selected_pair_obj = pair
        self.status_label.setText(f"Selected {pair.base}")
        self.update_action_buttons()

    def selected_pair(self) -> CapturePair | None:
        return self.selected_pair_obj

    def set_device_connected(self, connected: bool) -> None:
        self.device_connected = connected
        if not connected:
            if self.current_refresh_task is not None:
                self.current_refresh_task.cancel()
            if self.current_sync_task is not None:
                self.current_sync_task.cancel()
            self.syncing = False
            self.current_refresh_task = None
            self.current_sync_task = None
            self.status_label.setText("Connect a Thor device to sync the SD card")

        self.update_action_buttons()

    def update_action_buttons(self) -> None:
        has_selection = self.selected_pair_obj is not None
        self.sync_button.setEnabled(self.device_connected and not self.syncing)
        self.analyse_button.setEnabled(has_selection)
        self.save_button.setEnabled(has_selection)

    def on_download_progress(self, pair: CapturePair, paths: list[Path]) -> None:
        item = self.items_by_pair.get(pair)
        if item is None:
            return

        item.setText(self.item_text(pair))

        if pair.ir is not None and any(path.name == pair.ir.filename for path in paths):
            self.update_thumbnail(pair, item)

    def on_sync_done(self, paths: list[Path]) -> None:
        self.has_synced = True
        self.syncing = False
        self.current_sync_task = None
        self.update_action_buttons()

        for pair, item in self.items_by_pair.items():
            item.setText(self.item_text(pair))
            if pair.ir is not None and (DOWNLOAD_DIR / pair.ir.filename).exists():
                self.update_thumbnail(pair, item)

        if paths:
            self.status_label.setText(f"Ready; downloaded {len(paths)} file(s)")
        else:
            self.status_label.setText("Ready; all files are local")

        self.sync_finished.emit()

    def on_sync_cancelled(self) -> None:
        self.syncing = False
        self.current_refresh_task = None
        self.current_sync_task = None
        self.update_action_buttons()
        self.status_label.setText("Sync paused; open Storage to continue")
        self.sync_finished.emit()

    def missing_file_count(self) -> int:
        return sum(
            1
            for pair in self.pairs
            for file in (pair.ir, pair.dc)
            if file is not None
            and not (
                (DOWNLOAD_DIR / file.filename).exists()
                and (DOWNLOAD_DIR / file.filename).stat().st_size == file.size
            )
        )

    def is_pair_downloaded(self, pair: CapturePair) -> bool:
        return all(
            file is None
            or (
                (DOWNLOAD_DIR / file.filename).exists()
                and (DOWNLOAD_DIR / file.filename).stat().st_size == file.size
            )
            for file in (pair.ir, pair.dc)
        )

    def load_next_thumbnail_batch(self) -> None:
        batch_size = 4

        for _ in range(batch_size):
            if not self.thumbnail_queue:
                self.thumbnail_timer.stop()
                return

            pair = self.thumbnail_queue.popleft()
            item = self.items_by_pair.get(pair)
            if item is not None:
                self.update_thumbnail(pair, item)

    def update_thumbnail(self, pair: CapturePair, item: QListWidgetItem) -> None:
        if pair.ir is None:
            item.setIcon(self.placeholder_icon(pair))
            return

        path = DOWNLOAD_DIR / pair.ir.filename

        if not path.exists():
            item.setIcon(self.placeholder_icon(pair))
            return

        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        reader.setScaledSize(QSize(THUMB_WIDTH, THUMB_HEIGHT))

        image = reader.read()

        if image.isNull():
            item.setIcon(self.text_icon("Preview error", "#ffb4b4"))
            return

        item.setIcon(QIcon(QPixmap.fromImage(image)))

    def analyse_item(self, item: QListWidgetItem) -> None:
        pair = item.data(Qt.UserRole)
        self.analyse_pair(pair)

    def analyse_selected(self) -> None:
        pair = self.selected_pair()
        if pair is None:
            QMessageBox.information(self, "No selection", "Select a capture first.")
            return

        self.analyse_pair(pair)

    def save_selected(self) -> None:
        pair = self.selected_pair()
        if pair is None:
            QMessageBox.information(self, "No selection", "Select a capture first.")
            return

        source_paths = self.local_pair_paths(pair)
        expected_roles = self.expected_pair_roles(pair)
        missing_roles = expected_roles - source_paths.keys()
        if missing_roles:
            QMessageBox.warning(
                self,
                "Not downloaded",
                "The selected capture has not finished downloading yet.",
            )
            return

        default_path = self.default_export_path(pair)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save capture pair",
            str(default_path),
            "JPEG images (*.jpg *.jpeg);;All files (*)",
        )

        if not filename:
            return

        destination_path = Path(filename)
        export_paths = self.export_paths_for_pair(destination_path, pair)
        if not export_paths:
            QMessageBox.warning(
                self,
                "Nothing to save",
                "The selected capture has no IR or visual image.",
            )
            return

        try:
            for role, source_path in source_paths.items():
                shutil.copy2(source_path, export_paths[role])
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return

        self.settings.setValue(EXPORT_DIR_SETTING, str(destination_path.parent))
        self.settings.setValue(EXPORT_FILENAME_SETTING, destination_path.name)
        self.status_label.setText(
            f"Saved {', '.join(export_paths[role].name for role in source_paths)}"
        )

    def expected_pair_roles(self, pair: CapturePair) -> set[str]:
        roles: set[str] = set()

        if pair.ir is not None:
            roles.add("ir")

        if pair.dc is not None:
            roles.add("dc")

        return roles

    def local_pair_paths(self, pair: CapturePair) -> dict[str, Path]:
        paths: dict[str, Path] = {}

        for role, file in (("ir", pair.ir), ("dc", pair.dc)):
            if file is None:
                continue

            path = DOWNLOAD_DIR / file.filename
            if path.exists():
                paths[role] = path

        return paths

    def default_export_path(self, pair: CapturePair) -> Path:
        export_dir = Path(
            self.settings.value(EXPORT_DIR_SETTING, str(Path.home()), str)
        )
        export_filename = self.settings.value(
            EXPORT_FILENAME_SETTING,
            f"{pair.base}.jpg",
            str,
        )
        return export_dir / export_filename

    @staticmethod
    def export_paths_for_pair(
        destination_path: Path,
        pair: CapturePair,
    ) -> dict[str, Path]:
        suffix = destination_path.suffix or ".jpg"
        base_path = destination_path.with_suffix("")
        paths: dict[str, Path] = {}

        if pair.ir is not None:
            paths["ir"] = base_path.with_name(f"{base_path.name}-IR").with_suffix(suffix)

        if pair.dc is not None:
            paths["dc"] = base_path.with_name(f"{base_path.name}-DC").with_suffix(suffix)

        return paths

    def analyse_pair(self, pair: CapturePair) -> None:
        if pair.ir is None:
            QMessageBox.warning(self, "No IR image", "This capture has no IR image.")
            return

        path = DOWNLOAD_DIR / pair.ir.filename

        if not path.exists():
            if self.syncing:
                QMessageBox.information(
                    self,
                    "Still syncing",
                    f"{pair.ir.filename} is still downloading. Try again when it is ready.",
                )
                return

            QMessageBox.warning(
                self,
                "Not downloaded",
                f"{pair.ir.filename} has not been downloaded yet.",
            )
            return

        self.open_ir_requested.emit(path)

    def on_error(self, message: str) -> None:
        self.current_refresh_task = None
        self.status_label.setText(message)
        self.syncing = False
        self.current_sync_task = None
        self.update_action_buttons()

        if not self.active:
            self.sync_finished.emit()
            return

        self.sync_finished.emit()
        QMessageBox.warning(self, "MTP error", message)
