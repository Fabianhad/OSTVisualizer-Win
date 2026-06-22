import logging
from datetime import datetime
from pathlib import Path
from typing import List
from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.file_state import FileEntry, normalize_path
from ..config import (
    COMPACT_SPACING,
    NO_MARGINS,
    OPEN_FILE_HEIGHT,
    OPEN_FILE_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.messagebox import confirm, show_info
from ..utils.tree_widget import set_tree_item_row_height
from ..utils.windows import remove_minimize

logger = logging.getLogger(__name__)


class OpenFilesDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent,
        file_entries: List[FileEntry],
        working_directory_service,
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._working_directory_service = working_directory_service
        self.file_entries = [FileEntry(e.file_path, e.is_checked) for e in file_entries]
        self._setup_ui()
        self._populate_table()
        self._update_remove_button_state()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Open Databases")
        self.setModal(True)
        self.resize(OPEN_FILE_WIDTH, OPEN_FILE_HEIGHT)
        self.icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        self.table = QtWidgets.QTreeWidget(self)
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["Open", "File Name", "Date Modified", "Size"])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table.itemSelectionChanged.connect(self._update_remove_button_state)
        header = self.table.header()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 50)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 300)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 150)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, 100)
        content_layout = QtWidgets.QHBoxLayout()
        content_layout.addWidget(self.table)
        right_buttons = QtWidgets.QVBoxLayout()
        right_buttons.setSpacing(COMPACT_SPACING)
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.close_button.clicked.connect(self._on_close)
        right_buttons.addWidget(self.close_button)
        self.find_button = QtWidgets.QPushButton("Find...", self)
        self.find_button.clicked.connect(self._on_find)
        right_buttons.addWidget(self.find_button)
        self.remove_button = QtWidgets.QPushButton("Remove", self)
        self.remove_button.clicked.connect(self._on_remove)
        self.remove_button.setEnabled(False)
        right_buttons.addWidget(self.remove_button)
        right_buttons.addStretch()
        content_layout.addLayout(right_buttons)
        main_layout.addLayout(content_layout)

    def _populate_table(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.clear()
            self._checkboxes = []
            for row, entry in enumerate(self.file_entries):
                file_name = self._format_file_name(entry.file_path)
                date_modified = self._get_file_date(entry.file_path)
                size_text = self._get_file_size(entry.file_path)
                item = QtWidgets.QTreeWidgetItem(
                    ["", file_name, date_modified, size_text]
                )
                flags = item.flags()
                flags &= ~QtCore.Qt.ItemFlag.ItemIsUserCheckable
                flags &= ~QtCore.Qt.ItemFlag.ItemIsEditable
                item.setFlags(flags)
                item.setTextAlignment(2, QtCore.Qt.AlignmentFlag.AlignCenter)
                item.setTextAlignment(3, QtCore.Qt.AlignmentFlag.AlignCenter)
                set_tree_item_row_height(item, self.table.columnCount())
                self.table.addTopLevelItem(item)
                cb = QtWidgets.QCheckBox()
                cb.setChecked(entry.is_checked)
                cb.clicked.connect(self._make_check_handler(row))
                container = QtWidgets.QWidget()
                container_layout = QtWidgets.QHBoxLayout(container)
                container_layout.setContentsMargins(*NO_MARGINS)
                container_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                container_layout.addWidget(cb)
                self.table.setItemWidget(item, 0, container)
                self._checkboxes.append(cb)
        finally:
            self.table.blockSignals(False)
        self._update_remove_button_state()

    def _format_file_name(self, file_path: str) -> str:
        path = Path(file_path)
        name_no_ext = path.stem
        full_path = str(path.absolute())
        return f"{name_no_ext} ({full_path})"

    def _get_file_date(self, file_path: str) -> str:
        try:
            path = Path(file_path)
            mtime = path.stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
            return dt.strftime("%m/%d/%Y %I:%M:%S %p")
        except Exception as e:
            logger.warning(f"Error getting file date for {file_path}: {e}")
            return "N/A"

    def _get_file_size(self, file_path: str) -> str:
        try:
            path = Path(file_path)
            size_bytes = path.stat().st_size
            size_kb = size_bytes / 1024
            if size_kb.is_integer():
                return f"{int(size_kb):,} KB"
            else:
                return f"{size_kb:,.2f} KB"
        except Exception as e:
            logger.warning(f"Error getting file size for {file_path}: {e}")
            return "N/A"

    def _make_check_handler(self, row: int):
        def handler(checked: bool) -> None:
            if 0 <= row < len(self.file_entries):
                self.file_entries[row].is_checked = checked

        return handler

    def _on_find(self) -> None:
        file_filter = "Microsoft Access Database (*.mdb)"
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Database File", "", file_filter
        )
        if file_path:
            norm = normalize_path(file_path)
            if any(entry.normalized_path == norm for entry in self.file_entries):
                show_info(
                    self, "File Already Added", "This file is already in the list."
                )
                return
            new_entry = FileEntry(file_path=file_path, is_checked=True)
            self.file_entries.append(new_entry)
            self._populate_table()

    def _on_remove(self) -> None:
        current_item = self.table.currentItem()
        row = self.table.indexOfTopLevelItem(current_item)
        file_path = self.file_entries[row].file_path
        file_name = Path(file_path).name
        if confirm(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove '{file_name}' from the list?",
        ):
            del self.file_entries[row]
            self._populate_table()

    def _on_close(self) -> None:
        self.accept()

    def cleanup(self) -> None:
        try:
            self.table.itemSelectionChanged.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self.close_button.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self.find_button.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self.remove_button.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.table.clear()
        if self.file_entries:
            self.file_entries.clear()
        self.close_button = None
        self.find_button = None
        self.remove_button = None
        self.table = None
        self._working_directory_service = None
        self.icon_provider = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        remove_minimize(self)

    def closeEvent(self, event) -> None:
        event.accept()
        self.accept()

    def get_file_entries(self) -> List[FileEntry]:
        return [FileEntry(e.file_path, e.is_checked) for e in self.file_entries]

    def _is_in_working_dir(self, file_path: str) -> bool:
        if self._working_directory_service is None:
            return False
        try:
            resolved = Path(file_path).resolve()
            wd_resolved = self._working_directory_service.working_dir.resolve()
            return resolved.parent == wd_resolved
        except OSError:
            return False

    def _update_remove_button_state(self) -> None:
        selection_model = self.table.selectionModel()
        has_selection = bool(selection_model and selection_model.hasSelection())
        if has_selection:
            row = self.table.indexOfTopLevelItem(self.table.currentItem())
            if 0 <= row < len(self.file_entries):
                has_selection = not self._is_in_working_dir(
                    self.file_entries[row].file_path
                )
        self.remove_button.setEnabled(has_selection)
