from __future__ import annotations
from dataclasses import dataclass, replace
from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ..config import (
    COMPACT_SPACING,
    NO_MARGINS,
    RELAXED_MARGINS,
    RELAXED_SPACING,
    SQL_CONNECTION_DIALOG_WIDTH,
)
from ..utils.messagebox import show_warning
from ..utils.windows import remove_minimize_maximize, set_fixed_width_auto_height


@dataclass(frozen=True, repr=False)
class SqlConnectionDialogResult:
    location: SqlServerDatabaseLocation
    password: str = ""

    def __repr__(self) -> str:
        return (
            "SqlConnectionDialogResult("
            f"location={self.location!r}, password=<redacted>)"
        )


class SqlConnectionFormMixin:
    def _build_connection_form(
        self,
        layout: QtWidgets.QVBoxLayout,
        *,
        read_only: bool,
    ) -> None:
        connection_form = QtWidgets.QFormLayout()
        connection_form.setSpacing(COMPACT_SPACING)
        self.server_input = QtWidgets.QLineEdit(self)
        self.server_input.setPlaceholderText(
            r"localhost, server\instance, or host,port"
        )
        self.server_input.setClearButtonEnabled(not read_only)
        self.server_input.setReadOnly(read_only)
        connection_form.addRow("SQL Server:", self.server_input)
        authentication_layout = QtWidgets.QVBoxLayout()
        authentication_layout.setSpacing(COMPACT_SPACING)
        authentication_layout.setContentsMargins(*NO_MARGINS)
        authentication_layout.addWidget(QtWidgets.QLabel("Connect using:", self))
        self.windows_auth_radio = QtWidgets.QRadioButton("Windows authentication", self)
        self.sql_auth_radio = QtWidgets.QRadioButton("SQL Server authentication", self)
        self.windows_auth_radio.setChecked(True)
        authentication_layout.addWidget(self.windows_auth_radio)
        authentication_layout.addWidget(self.sql_auth_radio)
        credentials = QtWidgets.QFormLayout()
        credentials.setSpacing(COMPACT_SPACING)
        self.username_input = QtWidgets.QLineEdit(self)
        self.username_input.setClearButtonEnabled(not read_only)
        self.password_input = QtWidgets.QLineEdit(self)
        self.password_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.password_input.setClearButtonEnabled(not read_only)
        credentials.addRow("Login name:", self.username_input)
        credentials.addRow("Password:", self.password_input)
        authentication_layout.addLayout(credentials)
        connection_form.addRow("", authentication_layout)
        layout.addLayout(connection_form)
        self.windows_auth_radio.toggled.connect(self._sync_authentication_fields)
        self.sql_auth_radio.toggled.connect(self._sync_authentication_fields)

    def _apply_connection(
        self,
        connection: SqlConnectionDialogResult,
        *,
        lock_authentication: bool,
    ) -> None:
        location = connection.location
        self.server_input.setText(location.server)
        self.username_input.setText(location.username)
        self.password_input.setText(connection.password)
        is_sql_auth = location.authentication_mode == SqlAuthenticationMode.SQL_SERVER
        self.sql_auth_radio.setChecked(is_sql_auth)
        self.windows_auth_radio.setChecked(not is_sql_auth)
        if lock_authentication:
            self.windows_auth_radio.setEnabled(False)
            self.sql_auth_radio.setEnabled(False)
            self.username_input.setReadOnly(True)
            self.password_input.setReadOnly(True)

    def _sync_authentication_fields(self) -> None:
        enabled = self.sql_auth_radio.isChecked()
        self.username_input.setEnabled(enabled)
        self.password_input.setEnabled(enabled)

    def _validated_connection(
        self,
        initial: SqlConnectionDialogResult | None = None,
    ) -> SqlConnectionDialogResult | None:
        server = self.server_input.text().strip()
        if not server:
            show_warning(self, "SQL Server", "Enter a SQL Server name.")
            self.server_input.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            return None
        auth_mode = SqlAuthenticationMode.WINDOWS
        username = ""
        password = ""
        if self.sql_auth_radio.isChecked():
            auth_mode = SqlAuthenticationMode.SQL_SERVER
            username = self.username_input.text().strip()
            password = self.password_input.text()
            if not username or not password:
                show_warning(
                    self,
                    "SQL Server Authentication",
                    "Enter both a login name and password.",
                )
                return None
        if initial is None:
            location = SqlServerDatabaseLocation(
                server=server,
                database="",
                authentication_mode=auth_mode,
                username=username,
            )
        else:
            location = replace(
                initial.location,
                server=server,
                database="",
                database_guid="",
                authentication_mode=auth_mode,
                username=username,
            )
        return SqlConnectionDialogResult(location, password)

    def _clear_connection_secret(self) -> None:
        self.password_input.clear()

    def _disconnect_connection_form(self) -> None:
        for signal in (
            self.windows_auth_radio.toggled,
            self.sql_auth_radio.toggled,
        ):
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass


class SqlConnectionDialog(SqlConnectionFormMixin, QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to SQL Server")
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        self._result_data: SqlConnectionDialogResult | None = None
        self._build_ui()
        self._sync_authentication_fields()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        self._build_connection_form(layout, read_only=False)
        layout.addStretch()
        self.button_box = QtWidgets.QDialogButtonBox(self)
        self.connect_button = self.button_box.addButton(
            "Connect", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = self.button_box.addButton(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.connect_button.setDefault(True)
        self.connect_button.clicked.connect(self._accept_if_valid)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.button_box)
        self.server_input.returnPressed.connect(self._accept_if_valid)
        self.username_input.returnPressed.connect(self._accept_if_valid)
        self.password_input.returnPressed.connect(self._accept_if_valid)
        set_fixed_width_auto_height(self, SQL_CONNECTION_DIALOG_WIDTH)

    def _accept_if_valid(self) -> None:
        result = self._validated_connection()
        if result is None:
            return
        self._result_data = result
        self.accept()

    def result_data(self) -> SqlConnectionDialogResult | None:
        return self._result_data

    def reject(self) -> None:
        self._result_data = None
        self._clear_connection_secret()
        super().reject()

    def cleanup(self) -> None:
        self._clear_connection_secret()
        self._result_data = None
        self._disconnect_connection_form()
        for signal in (
            self.connect_button.clicked,
            self.cancel_button.clicked,
            self.server_input.returnPressed,
            self.username_input.returnPressed,
            self.password_input.returnPressed,
        ):
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass
