from __future__ import annotations
from dataclasses import dataclass, replace
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
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
from ..texts import (
    SQL_CONNECTION_DIALOG_BUTTON_CONNECT,
    SQL_CONNECTION_DIALOG_LABEL_CONNECT_USING,
    SQL_CONNECTION_DIALOG_LABEL_LOGIN_NAME,
    SQL_CONNECTION_DIALOG_LABEL_PASSWORD,
    SQL_CONNECTION_DIALOG_LABEL_SQL_SERVER,
    SQL_CONNECTION_DIALOG_LABEL_USE_A_SEPARATE_ACCOUNT_WITH_PERMISSION,
    SQL_CONNECTION_DIALOG_MESSAGE_ENTER_A_SQL_SERVER_NAME,
    SQL_CONNECTION_DIALOG_MESSAGE_ENTER_BOTH_A_LOGIN_NAME_AND,
    SQL_CONNECTION_DIALOG_OPTION_ENCRYPT_CONNECTION,
    SQL_CONNECTION_DIALOG_OPTION_SQL_SERVER_AUTHENTICATION,
    SQL_CONNECTION_DIALOG_OPTION_TRUST_SERVER_CERTIFICATE,
    SQL_CONNECTION_DIALOG_OPTION_WINDOWS_AUTHENTICATION,
    SQL_CONNECTION_DIALOG_PLACEHOLDER_LOCALHOST_SERVER_INSTANCE_OR_HOST_PORT,
    SQL_CONNECTION_DIALOG_TITLE_CONNECT_TO_SQL_SERVER,
    SQL_CONNECTION_DIALOG_TITLE_CONNECT_TO_SQL_SERVER_DATABASE_CREATOR,
    SQL_CONNECTION_DIALOG_TITLE_SQL_SERVER,
    SQL_CONNECTION_DIALOG_TITLE_SQL_SERVER_AUTHENTICATION,
    SQL_CONNECTION_DIALOG_TOOLTIP_CLEAR_THIS_TO_VALIDATE_THE_SERVER,
)


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
            SQL_CONNECTION_DIALOG_PLACEHOLDER_LOCALHOST_SERVER_INSTANCE_OR_HOST_PORT
        )
        self.server_input.setClearButtonEnabled(not read_only)
        self.server_input.setReadOnly(read_only)
        connection_form.addRow(
            SQL_CONNECTION_DIALOG_LABEL_SQL_SERVER, self.server_input
        )
        authentication_layout = QtWidgets.QVBoxLayout()
        authentication_layout.setSpacing(COMPACT_SPACING)
        authentication_layout.setContentsMargins(*NO_MARGINS)
        authentication_layout.addWidget(
            QtWidgets.QLabel(SQL_CONNECTION_DIALOG_LABEL_CONNECT_USING, self)
        )
        self.windows_auth_radio = QtWidgets.QRadioButton(
            SQL_CONNECTION_DIALOG_OPTION_WINDOWS_AUTHENTICATION, self
        )
        self.sql_auth_radio = QtWidgets.QRadioButton(
            SQL_CONNECTION_DIALOG_OPTION_SQL_SERVER_AUTHENTICATION, self
        )
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
        credentials.addRow(SQL_CONNECTION_DIALOG_LABEL_LOGIN_NAME, self.username_input)
        credentials.addRow(SQL_CONNECTION_DIALOG_LABEL_PASSWORD, self.password_input)
        authentication_layout.addLayout(credentials)
        connection_form.addRow("", authentication_layout)
        layout.addLayout(connection_form)
        self.windows_auth_radio.toggled.connect(self._sync_authentication_fields)
        self.sql_auth_radio.toggled.connect(self._sync_authentication_fields)

    def _build_transport_options(self) -> QtWidgets.QWidget:
        options = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(options)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        self.encrypt_checkbox = QtWidgets.QCheckBox(
            SQL_CONNECTION_DIALOG_OPTION_ENCRYPT_CONNECTION, options
        )
        self.trust_certificate_checkbox = QtWidgets.QCheckBox(
            SQL_CONNECTION_DIALOG_OPTION_TRUST_SERVER_CERTIFICATE, options
        )
        self.encrypt_checkbox.setChecked(True)
        self.trust_certificate_checkbox.setChecked(True)
        self.trust_certificate_checkbox.setToolTip(
            SQL_CONNECTION_DIALOG_TOOLTIP_CLEAR_THIS_TO_VALIDATE_THE_SERVER
        )
        layout.addWidget(self.encrypt_checkbox)
        layout.addWidget(self.trust_certificate_checkbox)
        return options

    def _apply_connection(
        self,
        connection: SqlConnectionDialogResult,
        *,
        lock_authentication: bool,
    ) -> None:
        location = connection.location
        self.server_input.setText(location.server)
        self.encrypt_checkbox.setChecked(location.encrypt)
        self.trust_certificate_checkbox.setChecked(location.trust_server_certificate)
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
            show_warning(
                self,
                SQL_CONNECTION_DIALOG_TITLE_SQL_SERVER,
                SQL_CONNECTION_DIALOG_MESSAGE_ENTER_A_SQL_SERVER_NAME,
                validation=True,
            )
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
                    SQL_CONNECTION_DIALOG_TITLE_SQL_SERVER_AUTHENTICATION,
                    SQL_CONNECTION_DIALOG_MESSAGE_ENTER_BOTH_A_LOGIN_NAME_AND,
                    validation=True,
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
        location = replace(
            location,
            encrypt=self.encrypt_checkbox.isChecked(),
            trust_server_certificate=self.trust_certificate_checkbox.isChecked(),
        )
        return SqlConnectionDialogResult(location, password)

    def _clear_connection_secret(self) -> None:
        if isValid(self.password_input):
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
        *,
        creator_for: SqlServerDatabaseLocation | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial_connection = (
            SqlConnectionDialogResult(
                replace(
                    creator_for,
                    database="",
                    database_guid="",
                    authentication_mode=SqlAuthenticationMode.WINDOWS,
                    username="",
                )
            )
            if creator_for is not None
            else None
        )
        self.setWindowTitle(
            SQL_CONNECTION_DIALOG_TITLE_CONNECT_TO_SQL_SERVER_DATABASE_CREATOR
            if creator_for is not None
            else SQL_CONNECTION_DIALOG_TITLE_CONNECT_TO_SQL_SERVER
        )
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        self._result_data: SqlConnectionDialogResult | None = None
        self._build_ui()
        if self._initial_connection is not None:
            self._apply_connection(self._initial_connection, lock_authentication=False)
            self.server_input.setReadOnly(True)
            self.server_input.setClearButtonEnabled(False)
            self.encrypt_checkbox.setEnabled(False)
            self.trust_certificate_checkbox.setEnabled(False)
        self._sync_authentication_fields()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        if self._initial_connection is not None:
            purpose = QtWidgets.QLabel(
                SQL_CONNECTION_DIALOG_LABEL_USE_A_SEPARATE_ACCOUNT_WITH_PERMISSION,
                self,
            )
            purpose.setWordWrap(True)
            layout.addWidget(purpose)
        self._build_connection_form(layout, read_only=False)
        layout.addWidget(self._build_transport_options())
        layout.addStretch()
        self.button_box = QtWidgets.QDialogButtonBox(self)
        self.connect_button = self.button_box.addButton(
            SQL_CONNECTION_DIALOG_BUTTON_CONNECT,
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
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
        result = self._validated_connection(self._initial_connection)
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
        self._initial_connection = None
        if isValid(self):
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
