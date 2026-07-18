from __future__ import annotations
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable
from PySide6 import QtWidgets
from ...application.dtos.application_info import APPLICATION_VERSION
from ...application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    IDatabaseCatalog,
    SqlDatabaseCatalogEntry,
)
from ...application.interfaces.i_sql_database_creator import ISqlDatabaseCreator
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.database_descriptor import (
    SqlServerDatabaseLocation,
    validate_sql_database_name,
)
from ..config import (
    COMPACT_SPACING,
    RELAXED_MARGINS,
    RELAXED_SPACING,
    SQL_DATABASE_PROPERTIES_DIALOG_HEIGHT,
    SQL_DATABASE_PROPERTIES_DIALOG_WIDTH,
)
from ..utils.messagebox import confirm, show_warning
from ..utils.windows import remove_minimize_maximize, set_initial_window_size
from .sql_connection_dialog import SqlConnectionDialogResult, SqlConnectionFormMixin


class SqlDatabasePropertiesMode(str, Enum):
    OPEN = "open"
    CREATE = "create"


@dataclass(frozen=True, repr=False)
class SqlDatabasePropertiesResult:
    location: SqlServerDatabaseLocation
    schema_version: int
    password: str = ""

    def __repr__(self) -> str:
        return (
            "SqlDatabasePropertiesResult("
            f"location={self.location!r}, schema_version={self.schema_version!r}, "
            "password=<redacted>)"
        )


class SqlDatabasePropertiesDialog(SqlConnectionFormMixin, QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        mode: SqlDatabasePropertiesMode,
        sql_catalog: IDatabaseCatalog,
        sql_database_creator: ISqlDatabaseCreator,
        parent: QtWidgets.QWidget | None = None,
        *,
        connection: SqlConnectionDialogResult | None = None,
        databases: Iterable[SqlDatabaseCatalogEntry] = (),
        schema_change_allowed_fn=None,
    ) -> None:
        super().__init__(parent)
        if mode == SqlDatabasePropertiesMode.OPEN and connection is None:
            raise ValueError("Open mode requires authenticated SQL connection details")
        self._mode = mode
        self._catalog = sql_catalog
        self._database_creator = sql_database_creator
        self._initial_connection = connection
        self._result_data: SqlDatabasePropertiesResult | None = None
        self._schema_change_allowed_fn = schema_change_allowed_fn
        self._databases = tuple(databases)
        self.setWindowTitle("Database Properties (SQL Server)")
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        self._build_ui()
        self._apply_initial_connection()
        self._sync_authentication_fields()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        self._build_connection_form(
            layout,
            read_only=self._mode == SqlDatabasePropertiesMode.OPEN,
        )
        database_form = QtWidgets.QFormLayout()
        database_form.setSpacing(COMPACT_SPACING)
        self.database_combo = QtWidgets.QComboBox(self)
        self.database_name_input = QtWidgets.QLineEdit(self)
        self.database_name_input.setClearButtonEnabled(True)
        if self._mode == SqlDatabasePropertiesMode.OPEN:
            self.database_name_input.hide()
            database_form.addRow("Database:", self.database_combo)
            self._populate_databases()
        else:
            self.database_combo.hide()
            database_form.addRow("Database:", self.database_name_input)
        layout.addLayout(database_form)
        layout.addStretch()
        self.button_box = QtWidgets.QDialogButtonBox(self)
        self.ok_button = self.button_box.addButton(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        )
        self.cancel_button = self.button_box.addButton(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self._accept_if_valid)
        self.cancel_button.clicked.connect(self.reject)
        self.server_input.returnPressed.connect(self._accept_if_valid)
        self.username_input.returnPressed.connect(self._accept_if_valid)
        self.password_input.returnPressed.connect(self._accept_if_valid)
        self.database_name_input.returnPressed.connect(self._accept_if_valid)
        layout.addWidget(self.button_box)
        set_initial_window_size(
            self,
            SQL_DATABASE_PROPERTIES_DIALOG_WIDTH,
            SQL_DATABASE_PROPERTIES_DIALOG_HEIGHT,
        )

    def _apply_initial_connection(self) -> None:
        if self._initial_connection is None:
            return
        self._apply_connection(
            self._initial_connection,
            lock_authentication=self._mode == SqlDatabasePropertiesMode.OPEN,
        )

    def _populate_databases(self) -> None:
        self.database_combo.clear()
        for database in self._databases:
            self.database_combo.addItem(database.name, database)

    def _connection_details(self) -> SqlConnectionDialogResult | None:
        return self._validated_connection(self._initial_connection)

    def _accept_if_valid(self) -> None:
        connection = self._connection_details()
        if connection is None:
            return
        try:
            if self._mode == SqlDatabasePropertiesMode.OPEN:
                result = self._validate_open_selection(connection)
            else:
                result = self._create_database(connection)
        except (DatabaseCatalogError, OSError, ValueError) as exc:
            show_warning(self, "SQL Server", str(exc))
            return
        if result is None:
            return
        self._result_data = result
        self.accept()

    def _validate_open_selection(
        self, connection: SqlConnectionDialogResult
    ) -> SqlDatabasePropertiesResult | None:
        selected_name = self.database_combo.currentText().strip()
        if not selected_name:
            show_warning(self, "SQL Server", "Select a database.")
            return None
        selected = self._catalog.get_database(
            connection.location,
            selected_name,
            connection.password,
        )
        if not selected.is_compatible:
            show_warning(self, "SQL Server", selected.compatibility_message)
            return None
        if selected.schema_version == 0:
            if not (
                self._schema_change_allowed_fn and self._schema_change_allowed_fn()
            ):
                show_warning(
                    self,
                    "SQL Server",
                    "You do not have permission to initialize this database.",
                )
                return None
            if not confirm(
                self,
                "Enable SQL Database Editing",
                "This compatible database was created by another application. "
                "OST Visualizer must add its metadata and collaboration tables "
                "before editing is enabled. Existing database tables and data "
                "will not be rewritten. Continue?",
            ):
                return None
            external_location = replace(
                connection.location,
                database=selected.name,
                database_guid=selected.database_guid,
            )
            initialized = self._database_creator.initialize_compatible_database(
                external_location,
                connection.password,
                application_version=APPLICATION_VERSION,
                actor=connection.location.username,
            )
            return SqlDatabasePropertiesResult(
                initialized.location,
                initialized.schema_version,
                connection.password,
            )
        location = replace(
            connection.location,
            database=selected.name,
            database_guid=selected.database_guid,
        )
        return SqlDatabasePropertiesResult(
            location, selected.schema_version, connection.password
        )

    def _create_database(
        self, connection: SqlConnectionDialogResult
    ) -> SqlDatabasePropertiesResult | None:
        if not (self._schema_change_allowed_fn and self._schema_change_allowed_fn()):
            show_warning(
                self,
                "SQL Server",
                "You do not have permission to create a database.",
            )
            return None
        database_name = self.database_name_input.text().strip()
        validate_sql_database_name(database_name)
        if not self._database_creator.can_create_database(
            connection.location, connection.password
        ):
            show_warning(
                self,
                "SQL Server",
                "The current login does not have permission to create a database.",
            )
            return None
        created = self._database_creator.create_database(
            connection.location,
            database_name,
            connection.password,
            application_version=APPLICATION_VERSION,
            actor=connection.location.username,
        )
        return SqlDatabasePropertiesResult(
            created.location, created.schema_version, connection.password
        )

    def result_data(self) -> SqlDatabasePropertiesResult | None:
        return self._result_data

    def reject(self) -> None:
        self._result_data = None
        self._clear_connection_secret()
        super().reject()

    def cleanup(self) -> None:
        self._clear_connection_secret()
        self._result_data = None
        self._initial_connection = None
        self._databases = ()
        self._disconnect_connection_form()
        for signal in (
            self.ok_button.clicked,
            self.cancel_button.clicked,
            self.server_input.returnPressed,
            self.username_input.returnPressed,
            self.password_input.returnPressed,
            self.database_name_input.returnPressed,
        ):
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass
        self.database_combo.clear()
        self._catalog = None
        self._database_creator = None
