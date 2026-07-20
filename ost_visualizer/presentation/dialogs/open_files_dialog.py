import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    IDatabaseCatalog,
)
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...application.interfaces.i_sql_database_creator import ISqlDatabaseCreator
from ...domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    credential_target_for,
)
from ...domain.entities.file_state import FileEntry, normalize_path
from ..config import (
    COMPACT_SPACING,
    NO_MARGINS,
    OPEN_FILE_HEIGHT,
    OPEN_FILE_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.condition_tree_style import apply_tree_indentation
from ..utils.messagebox import confirm, show_info, show_warning
from ..utils.tree_widget import set_tree_item_row_height
from ..utils.windows import remove_minimize
from .select_database_type_dialog import SelectDatabaseTypeDialog
from .sql_connection_dialog import SqlConnectionDialog
from .sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
    SqlDatabasePropertiesResult,
)

logger = logging.getLogger(__name__)


class OpenFilesDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent,
        file_entries: List[FileEntry],
        working_directory_service,
        sql_catalog: Optional[IDatabaseCatalog] = None,
        credential_store: Optional[ICredentialStore] = None,
        sql_database_creator: Optional[ISqlDatabaseCreator] = None,
        schema_change_allowed_fn=None,
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._working_directory_service = working_directory_service
        self._sql_catalog = sql_catalog
        self._credential_store = credential_store
        self._sql_database_creator = sql_database_creator
        self._schema_change_allowed_fn = schema_change_allowed_fn
        self.file_entries = [e.with_checked(e.is_checked) for e in file_entries]
        self._initial_entries_by_id = {
            entry.database_id: entry for entry in self.file_entries
        }
        self._credential_rollbacks: dict[str, tuple[str, tuple[str, str] | None]] = {}
        self._credential_changes_committed = False
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
        self.table.setColumnCount(6)
        self.table.setHeaderLabels(
            ["Open", "Type", "Database", "Location", "Date Modified", "Size"]
        )
        self.table.setRootIsDecorated(False)
        apply_tree_indentation(self.table)
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
        header.resizeSection(1, 120)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 150)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(5, 100)
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
                backend_name, database_name, location = self._display_values(entry)
                date_modified = ""
                size_text = ""
                if entry.backend == DatabaseBackend.ACCESS:
                    date_modified = self._get_file_date(entry.file_path)
                    size_text = self._get_file_size(entry.file_path)
                item = QtWidgets.QTreeWidgetItem(
                    [
                        "",
                        backend_name,
                        database_name,
                        location,
                        date_modified,
                        size_text,
                    ]
                )
                flags = item.flags()
                flags &= ~QtCore.Qt.ItemFlag.ItemIsUserCheckable
                flags &= ~QtCore.Qt.ItemFlag.ItemIsEditable
                item.setFlags(flags)
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, entry.database_id)
                item.setTextAlignment(1, QtCore.Qt.AlignmentFlag.AlignCenter)
                item.setTextAlignment(4, QtCore.Qt.AlignmentFlag.AlignCenter)
                item.setTextAlignment(5, QtCore.Qt.AlignmentFlag.AlignCenter)
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

    def _display_values(self, entry: FileEntry) -> tuple[str, str, str]:
        descriptor = entry.descriptor
        if entry.backend == DatabaseBackend.SQL_SERVER:
            location = descriptor.sql_location
            return "SQL Server", descriptor.display_name, location.server
        return "Access", descriptor.display_name, str(Path(entry.file_path).absolute())

    def _get_file_date(self, file_path: str) -> str:
        try:
            path = Path(file_path)
            mtime = path.stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
            return dt.strftime("%m/%d/%Y %I:%M:%S %p")
        except (OSError, ValueError, OverflowError) as exc:
            logger.warning("Error getting file date for %s: %s", file_path, exc)
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
        except OSError as exc:
            logger.warning("Error getting file size for %s: %s", file_path, exc)
            return "N/A"

    def _make_check_handler(self, row: int):
        def handler(checked: bool) -> None:
            if 0 <= row < len(self.file_entries):
                self.file_entries[row].is_checked = checked

        return handler

    def _on_find(self) -> None:
        dialog = SelectDatabaseTypeDialog(self.icon_provider, self)
        try:
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            backend = dialog.selected_backend()
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        if backend == DatabaseBackend.ACCESS:
            self._open_access_file_picker()
        else:
            self._open_sql_server_connection()

    def _open_access_file_picker(self) -> None:
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

    def _open_sql_server_connection(self) -> None:
        if (
            self._sql_catalog is None
            or self._credential_store is None
            or self._sql_database_creator is None
        ):
            show_warning(
                self,
                "SQL Server",
                "SQL Server support is unavailable in this installation.",
            )
            return
        connection_dialog = SqlConnectionDialog(self.icon_provider, self)
        connection_result = None
        try:
            if connection_dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                connection_result = connection_dialog.result_data()
        finally:
            connection_dialog.cleanup()
            connection_dialog.deleteLater()
        if connection_result is None:
            return
        try:
            databases = self._sql_catalog.list_databases(
                connection_result.location, connection_result.password
            )
            properties_dialog = SqlDatabasePropertiesDialog(
                self.icon_provider,
                SqlDatabasePropertiesMode.OPEN,
                self._sql_catalog,
                self._sql_database_creator,
                self,
                connection=connection_result,
                databases=databases,
                schema_change_allowed_fn=self._schema_change_allowed_fn,
            )
            properties_result = None
            try:
                if properties_dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                    properties_result = properties_dialog.result_data()
            finally:
                properties_dialog.cleanup()
                properties_dialog.deleteLater()
            if properties_result is None:
                return
            self._save_sql_result(properties_result)
        except DatabaseCatalogError as exc:
            show_warning(self, "SQL Server", str(exc))
        except (OSError, ValueError):
            show_warning(
                self,
                "SQL Server",
                "The SQL Server connection could not be saved.",
            )

    def _save_sql_result(self, result: SqlDatabasePropertiesResult) -> None:
        descriptor = DatabaseDescriptor.for_sql_server(
            result.location, schema_version=result.schema_version
        )
        new_entry = FileEntry.for_descriptor(descriptor)
        target = credential_target_for(descriptor.database_id)
        existing_index = next(
            (
                index
                for index, entry in enumerate(self.file_entries)
                if entry.identity_key == new_entry.identity_key
            ),
            None,
        )
        self._remember_credential(target, descriptor.database_id)
        if (
            result.location.authentication_mode == SqlAuthenticationMode.SQL_SERVER
            and result.password
        ):
            self._credential_store.write_password(
                target, result.location.username, result.password
            )
        elif existing_index is not None:
            existing = self.file_entries[existing_index]
            if (
                existing.descriptor.sql_location.authentication_mode
                == SqlAuthenticationMode.SQL_SERVER
            ):
                self._credential_store.delete_password(target)
        if existing_index is not None:
            self.file_entries[existing_index] = new_entry
            self._populate_table()
            show_info(
                self,
                "Database Connection Updated",
                "The saved SQL Server connection was updated.",
            )
            return
        self.file_entries.append(new_entry)
        self._populate_table()

    def _remember_credential(self, target: str, database_id: str) -> None:
        if target in self._credential_rollbacks:
            return
        previous = None
        entry = self._initial_entries_by_id.get(database_id)
        if (
            entry is not None
            and entry.backend == DatabaseBackend.SQL_SERVER
            and entry.descriptor.sql_location.authentication_mode
            == SqlAuthenticationMode.SQL_SERVER
        ):
            password = self._credential_store.read_password(target)
            if password:
                previous = (entry.descriptor.sql_location.username, password)
        self._credential_rollbacks[target] = (database_id, previous)

    def commit_credential_changes(self) -> set[str]:
        changed_database_ids = {
            database_id
            for database_id, _previous in self._credential_rollbacks.values()
        }
        retained_ids = {entry.database_id for entry in self.file_entries}
        for target, (database_id, previous) in tuple(
            self._credential_rollbacks.items()
        ):
            if database_id not in retained_ids:
                self._restore_credential(target, previous)
        self._credential_rollbacks.clear()
        self._credential_changes_committed = True
        return changed_database_ids & retained_ids

    def _rollback_credential_changes(self) -> None:
        if self._credential_changes_committed:
            return
        for target, (_database_id, previous) in tuple(
            self._credential_rollbacks.items()
        ):
            try:
                self._restore_credential(target, previous)
            except OSError:
                logger.exception(
                    "Failed to restore a SQL credential after closing Open Files"
                )
        self._credential_rollbacks.clear()

    def _restore_credential(
        self, target: str, previous: tuple[str, str] | None
    ) -> None:
        if previous is None:
            self._credential_store.delete_password(target)
            return
        username, password = previous
        self._credential_store.write_password(target, username, password)

    def _on_remove(self) -> None:
        current_item = self.table.currentItem()
        row = self.table.indexOfTopLevelItem(current_item)
        if row < 0 or row >= len(self.file_entries):
            return
        entry = self.file_entries[row]
        descriptor = entry.descriptor
        item_name = descriptor.display_name
        message = f"Are you sure you want to remove '{item_name}' from the list?"
        if entry.backend == DatabaseBackend.SQL_SERVER:
            message += "\n\nThis removes only the saved connection. The server database will not be deleted."
        if confirm(
            self,
            "Confirm Removal",
            message,
        ):
            del self.file_entries[row]
            self._populate_table()

    def _on_close(self) -> None:
        self.accept()

    def cleanup(self) -> None:
        self._rollback_credential_changes()
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
        self._sql_catalog = None
        self._credential_store = None
        self._sql_database_creator = None
        self._initial_entries_by_id = {}
        self.icon_provider = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        remove_minimize(self)

    def closeEvent(self, event) -> None:
        event.accept()
        self.accept()

    def get_file_entries(self) -> List[FileEntry]:
        return [e.with_checked(e.is_checked) for e in self.file_entries]

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
                entry = self.file_entries[row]
                has_selection = (
                    entry.backend == DatabaseBackend.SQL_SERVER
                    or not self._is_in_working_dir(entry.file_path)
                )
        self.remove_button.setEnabled(has_selection)
