import os
import unittest
import dataclasses
from shiboken6 import delete, isValid
from ost_visualizer.presentation import config
from tests.presentation.dialogs.sql_dialog_support import (
    NoModalWarnings,
    RecordingIconProvider,
    form_rows,
    margins,
)
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
)
from PySide6 import QtWidgets
import json
import secrets

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
    SqlConnectionDialogResult,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from tests.helpers.sql.database_foundation_support import (
    _IconProvider as _database_foundation_support__IconProvider,
    _app as _database_foundation_support__app,
)
from dataclasses import replace
from unittest.mock import Mock, patch
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
    SqlDatabaseRuntimeCredentials,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)
from tests.helpers.sql.creation_handoff_support import (
    _CREATOR as _creation_handoff_support__CREATOR,
    _RUNTIME as _creation_handoff_support__RUNTIME,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SqlConnectionDialogSqlCleanupTests(NoModalWarnings, unittest.TestCase):
    def test_connection_dialog_cleanup_releases_result_secret(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        icon_provider = type(
            "IconProvider", (), {"set_window_icon": lambda self, _widget: None}
        )()
        dialog = SqlConnectionDialog(icon_provider)
        dialog.server_input.setText("localhost")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText("user")
        dialog.password_input.setText("temporary-secret")
        dialog._accept_if_valid()
        self.assertEqual(
            dialog.result_data(),
            SqlConnectionDialogResult(
                SqlServerDatabaseLocation(
                    server="localhost",
                    database="",
                    authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                    username="user",
                ),
                "temporary-secret",
            ),
        )
        dialog.cleanup()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), "")
        dialog.deleteLater()


class SqlConnectionDialogSqlDialogTests(NoModalWarnings, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_sql_authentication_controls_and_password_masking(self):
        dialog = SqlConnectionDialog(self.icon_provider)
        try:
            self.assertTrue(dialog.windows_auth_radio.isChecked())
            self.assertFalse(dialog.username_input.isEnabled())
            self.assertFalse(dialog.password_input.isEnabled())
            self.assertEqual(
                dialog.password_input.echoMode(),
                QtWidgets.QLineEdit.EchoMode.Password,
            )
            dialog.sql_auth_radio.setChecked(True)
            self.assertTrue(dialog.username_input.isEnabled())
            self.assertTrue(dialog.password_input.isEnabled())
            self.assertTrue(dialog.trust_certificate_checkbox.isChecked())
            dialog.server_input.setText("localhost")
            dialog.username_input.setText("test-user")
            dialog.password_input.setText("temporary-secret")
            dialog._accept_if_valid()
            result = dialog.result_data()
            self.assertTrue(result.location.trust_server_certificate)
            self.assertEqual(
                result.location.authentication_mode, SqlAuthenticationMode.SQL_SERVER
            )
            self.assertEqual(result.location.username, "test-user")
            self.assertEqual(result.password, "temporary-secret")
            self.assertNotIn("temporary-secret", repr(result))
            dialog.sql_auth_radio.setChecked(False)
            dialog.windows_auth_radio.setChecked(True)
            self.assertFalse(dialog.username_input.isEnabled())
            self.assertFalse(dialog.password_input.isEnabled())
            dialog._accept_if_valid()
            windows_result = dialog.result_data()
            self.assertEqual(
                windows_result.location.authentication_mode,
                SqlAuthenticationMode.WINDOWS,
            )
            self.assertEqual(windows_result.location.username, "")
            self.assertEqual(windows_result.password, "")
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_incomplete_connection_is_rejected_with_warning(self):
        cases = (
            ("blank server", "   ", False, "", ""),
            ("missing login", "localhost", True, "", "temporary-secret"),
            ("missing password", "localhost", True, "test-user", ""),
        )
        for label, server, sql_auth, username, password in cases:
            with self.subTest(label):
                dialog = SqlConnectionDialog(self.icon_provider)
                try:
                    dialog.server_input.setText(server)
                    dialog.sql_auth_radio.setChecked(sql_auth)
                    dialog.username_input.setText(username)
                    dialog.password_input.setText(password)
                    with patch(
                        "ost_visualizer.presentation.dialogs.sql_connection_dialog."
                        "show_warning"
                    ) as warning:
                        dialog._accept_if_valid()
                    warning.assert_called_once()
                    self.assertIsNone(dialog.result_data())
                    self.assertNotEqual(
                        dialog.result(), QtWidgets.QDialog.DialogCode.Accepted
                    )
                finally:
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_enter_connects_and_cancel_discards_state(self):
        dialog = SqlConnectionDialog(self.icon_provider)
        try:
            dialog.server_input.setText("localhost")
            QTest.keyClick(dialog.server_input, QtCore.Qt.Key.Key_Return)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            result = dialog.result_data()
            self.assertIsNotNone(result)
            self.assertEqual(result.location.server, "localhost")
            self.assertEqual(
                result.location.authentication_mode, SqlAuthenticationMode.WINDOWS
            )
            self.assertEqual(result.password, "")
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        cancelled = SqlConnectionDialog(self.icon_provider)
        try:
            cancelled.server_input.setText("localhost")
            cancelled.password_input.setText(secrets.token_urlsafe(24))
            cancelled.reject()
            self.assertIsNone(cancelled.result_data())
            self.assertEqual(cancelled.password_input.text(), "")
        finally:
            cancelled.cleanup()
            cancelled.deleteLater()


class SqlConnectionDialogCreationDialogIdentityTests(
    NoModalWarnings, unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_creator_prompt_reuses_connection_dialog_without_runtime_secret(self):
        runtime = replace(
            _creation_handoff_support__CREATOR,
            username=_creation_handoff_support__RUNTIME.username,
        )
        dialog = SqlConnectionDialog(Mock(), creator_for=runtime)
        try:
            self.assertEqual(
                dialog.windowTitle(), "Connect to SQL Server - Database Creator"
            )
            self.assertEqual(dialog.server_input.text(), runtime.server)
            self.assertTrue(dialog.server_input.isReadOnly())
            self.assertTrue(dialog.windows_auth_radio.isChecked())
            self.assertEqual(dialog.username_input.text(), "")
            self.assertEqual(dialog.password_input.text(), "")
            self.assertFalse(dialog.encrypt_checkbox.isEnabled())
            self.assertFalse(dialog.trust_certificate_checkbox.isEnabled())
            self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
            self.assertTrue(dialog.encrypt_checkbox.isChecked())
            self.assertFalse(hasattr(dialog, "options_button"))
            dialog.sql_auth_radio.setChecked(True)
            dialog.username_input.setText(_creation_handoff_support__CREATOR.username)
            dialog.password_input.setText("creator-test-secret")
            dialog._accept_if_valid()
            self.assertEqual(
                dialog.result_data(),
                SqlConnectionDialogResult(
                    _creation_handoff_support__CREATOR, "creator-test-secret"
                ),
            )
            self.assertNotIn("creator-test-secret", repr(dialog.result_data()))
        finally:
            dialog.cleanup()
            self.assertEqual(dialog.password_input.text(), "")
            self.assertIsNone(dialog.result_data())
            dialog.deleteLater()


class SqlConnectionFormContractTests(NoModalWarnings, unittest.TestCase):
    """The connection form shared by the connection and database-properties dialogs."""

    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()

    def make(self, **kwargs):
        self.icons = RecordingIconProvider()
        dialog = SqlConnectionDialog(self.icons, **kwargs)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        return dialog

    def test_dialog_chrome_is_modal_titled_iconed_and_fixed_width(self):
        dialog = self.make()
        self.assertTrue(dialog.isModal())
        self.assertEqual(dialog.windowTitle(), "Connect to SQL Server")
        self.assertEqual(self.icons.widgets, [dialog])
        flags = dialog.windowFlags()
        self.assertFalse(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
        self.assertFalse(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.assertEqual(dialog.width(), config.SQL_CONNECTION_DIALOG_WIDTH)
        self.assertEqual(dialog.minimumWidth(), dialog.maximumWidth())
        self.assertEqual(dialog.height(), dialog.layout().sizeHint().height())
        layout = dialog.layout()
        self.assertEqual(margins(layout), config.RELAXED_MARGINS)
        self.assertEqual(layout.spacing(), config.RELAXED_SPACING)

    def test_layout_order_is_form_transport_options_stretch_then_buttons(self):
        dialog = self.make()
        layout = dialog.layout()
        self.assertEqual(layout.count(), 4)
        self.assertIsInstance(layout.itemAt(0).layout(), QtWidgets.QFormLayout)
        self.assertIs(layout.itemAt(1).widget(), dialog.encrypt_checkbox.parentWidget())
        self.assertIsNotNone(layout.itemAt(2).spacerItem())
        self.assertIs(layout.itemAt(3).widget(), dialog.button_box)

    def test_form_rows_labels_placeholders_and_spacing(self):
        dialog = self.make()
        form = dialog.layout().itemAt(0).layout()
        self.assertEqual(form.spacing(), config.COMPACT_SPACING)
        rows = form_rows(form)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ("SQL Server:", dialog.server_input))
        self.assertEqual(
            dialog.server_input.placeholderText(),
            r"localhost, server\instance, or host,port",
        )
        self.assertIsNone(rows[1][0])
        authentication = rows[1][1]
        self.assertEqual(authentication.spacing(), config.COMPACT_SPACING)
        self.assertEqual(margins(authentication), config.NO_MARGINS)
        self.assertEqual(authentication.count(), 4)
        self.assertEqual(authentication.itemAt(0).widget().text(), "Connect using:")
        self.assertIs(authentication.itemAt(1).widget(), dialog.windows_auth_radio)
        self.assertIs(authentication.itemAt(2).widget(), dialog.sql_auth_radio)
        credentials = authentication.itemAt(3).layout()
        self.assertEqual(credentials.spacing(), config.COMPACT_SPACING)
        self.assertEqual(
            form_rows(credentials),
            [
                ("Login name:", dialog.username_input),
                ("Password:", dialog.password_input),
            ],
        )
        self.assertEqual(dialog.windows_auth_radio.text(), "Windows authentication")
        self.assertEqual(dialog.sql_auth_radio.text(), "SQL Server authentication")
        for radio in (dialog.windows_auth_radio, dialog.sql_auth_radio):
            self.assertIs(radio.parentWidget(), dialog)

    def test_transport_options_defaults_texts_and_spacing(self):
        dialog = self.make()
        options = dialog.encrypt_checkbox.parentWidget()
        layout = options.layout()
        self.assertEqual(margins(layout), config.NO_MARGINS)
        self.assertEqual(layout.spacing(), config.COMPACT_SPACING)
        self.assertIs(layout.itemAt(0).widget(), dialog.encrypt_checkbox)
        self.assertIs(layout.itemAt(1).widget(), dialog.trust_certificate_checkbox)
        self.assertEqual(dialog.encrypt_checkbox.text(), "Encrypt connection")
        self.assertEqual(
            dialog.trust_certificate_checkbox.text(), "Trust server certificate"
        )
        self.assertTrue(dialog.encrypt_checkbox.isChecked())
        self.assertTrue(dialog.trust_certificate_checkbox.isChecked())
        self.assertEqual(
            dialog.trust_certificate_checkbox.toolTip(),
            "Clear this to validate the server certificate and hostname. "
            "Keep encryption enabled for the deployment's validated TLS policy.",
        )
        self.assertIs(dialog.encrypt_checkbox.parentWidget(), options)
        self.assertIs(dialog.trust_certificate_checkbox.parentWidget(), options)

    def test_editable_form_fields_offer_clear_buttons_and_password_masking(self):
        dialog = self.make()
        for field in (
            dialog.server_input,
            dialog.username_input,
            dialog.password_input,
        ):
            self.assertTrue(field.isClearButtonEnabled())
            self.assertFalse(field.isReadOnly())
        self.assertEqual(
            dialog.password_input.echoMode(), QtWidgets.QLineEdit.EchoMode.Password
        )
        self.assertEqual(
            dialog.username_input.echoMode(), QtWidgets.QLineEdit.EchoMode.Normal
        )

    def test_authentication_fields_follow_the_selected_radio(self):
        dialog = self.make()
        self.assertTrue(dialog.windows_auth_radio.isChecked())
        self.assertFalse(dialog.sql_auth_radio.isChecked())
        self.assertFalse(dialog.username_input.isEnabled())
        self.assertFalse(dialog.password_input.isEnabled())
        dialog.sql_auth_radio.setChecked(True)
        self.assertTrue(dialog.username_input.isEnabled())
        self.assertTrue(dialog.password_input.isEnabled())
        self.assertFalse(dialog.windows_auth_radio.isChecked())
        dialog.windows_auth_radio.setChecked(True)
        self.assertFalse(dialog.username_input.isEnabled())
        self.assertFalse(dialog.password_input.isEnabled())

    def test_buttons_are_connect_default_and_cancel_in_a_button_box(self):
        dialog = self.make()
        self.assertEqual(dialog.connect_button.text(), "Connect")
        self.assertTrue(dialog.connect_button.isDefault())
        self.assertEqual(
            dialog.button_box.buttonRole(dialog.connect_button),
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.assertEqual(
            dialog.button_box.standardButton(dialog.cancel_button),
            QtWidgets.QDialogButtonBox.StandardButton.Cancel,
        )
        self.assertEqual(
            dialog.button_box.buttons(), [dialog.connect_button, dialog.cancel_button]
        )

    def test_connect_enter_and_cancel_are_wired(self):
        triggers = {
            "connect click": lambda d: d.connect_button.click(),
            "server enter": lambda d: d.server_input.returnPressed.emit(),
            "login enter": lambda d: d.username_input.returnPressed.emit(),
            "password enter": lambda d: d.password_input.returnPressed.emit(),
        }
        for label, trigger in triggers.items():
            with self.subTest(label):
                dialog = self.make()
                dialog.server_input.setText("localhost")
                trigger(dialog)
                self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
                self.assertEqual(dialog.result_data().location.server, "localhost")
        dialog = self.make()
        dialog.server_input.setText("localhost")
        # A fresh dialog already reports Rejected: start from an accepted dialog so
        # that the click is the only thing that can turn the result into Rejected.
        dialog.setResult(QtWidgets.QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.cancel_button.click()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertIsNone(dialog.result_data())

    def test_validation_blocks_acceptance_and_reports_the_reason(self):
        dialog = self.make()
        dialog.server_input.setText("  ")
        dialog.cancel_button.setFocus()
        dialog._accept_if_valid()
        self.assertEqual(
            self.shown_warnings, [(dialog, "SQL Server", "Enter a SQL Server name.")]
        )
        self.assertIs(dialog.focusWidget(), dialog.server_input)
        self.shown_warnings.clear()
        dialog.server_input.setText("localhost")
        dialog.sql_auth_radio.setChecked(True)
        for username, password in (("", "pw"), ("user", ""), ("  ", "pw")):
            dialog.username_input.setText(username)
            dialog.password_input.setText(password)
            dialog._accept_if_valid()
        self.assertEqual(
            self.shown_warnings,
            [
                (
                    dialog,
                    "SQL Server Authentication",
                    "Enter both a login name and password.",
                )
            ]
            * 3,
        )
        self.assertIsNone(dialog.result_data())
        dialog.username_input.setText("  user  ")
        dialog.password_input.setText(" pw ")
        dialog._accept_if_valid()
        # The login name is trimmed; the password is kept exactly as typed.
        self.assertEqual(dialog.result_data().location.username, "user")
        self.assertEqual(dialog.result_data().password, " pw ")

    def test_result_carries_trimmed_server_and_the_transport_choices(self):
        dialog = self.make()
        dialog.server_input.setText("  server\\instance  ")
        dialog.encrypt_checkbox.setChecked(False)
        dialog.trust_certificate_checkbox.setChecked(False)
        dialog._accept_if_valid()
        location = dialog.result_data().location
        self.assertEqual(location.server, "server\\instance")
        self.assertEqual(location.database, "")
        self.assertEqual(
            (location.encrypt, location.trust_server_certificate), (False, False)
        )
        self.assertEqual(self.shown_warnings, [])

    def test_the_result_secret_is_redacted_and_the_result_is_immutable(self):
        result = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="s", database=""), "topsecret"
        )
        self.assertEqual(
            repr(result),
            f"SqlConnectionDialogResult(location={result.location!r}, password=<redacted>)",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.password = "other"

    def test_creator_mode_prompts_for_a_separate_account_and_locks_the_server(self):
        dialog = self.make(creator_for=_creation_handoff_support__CREATOR)
        self.assertEqual(
            dialog.windowTitle(), "Connect to SQL Server - Database Creator"
        )
        purpose = dialog.layout().itemAt(0).widget()
        self.assertIsInstance(purpose, QtWidgets.QLabel)
        self.assertTrue(purpose.wordWrap())
        self.assertEqual(
            purpose.text(),
            "Use a separate account with permission to create databases. "
            "These credentials are used only for setup.",
        )
        self.assertEqual(dialog.layout().count(), 5)
        self.assertTrue(dialog.server_input.isReadOnly())
        self.assertFalse(dialog.server_input.isClearButtonEnabled())
        self.assertTrue(dialog.username_input.isClearButtonEnabled())
        self.assertFalse(dialog.encrypt_checkbox.isEnabled())
        self.assertFalse(dialog.trust_certificate_checkbox.isEnabled())
        # Creator authentication is not locked: the account is chosen here.
        self.assertTrue(dialog.windows_auth_radio.isEnabled())
        self.assertTrue(dialog.sql_auth_radio.isEnabled())
        self.assertFalse(dialog.username_input.isReadOnly())
        self.assertFalse(dialog.password_input.isReadOnly())

    def test_creator_mode_adopts_the_servers_connection_settings(self):
        dialog = self.make(creator_for=_creation_handoff_support__CREATOR)
        self.assertEqual(
            dialog.server_input.text(), _creation_handoff_support__CREATOR.server
        )
        self.assertTrue(dialog.encrypt_checkbox.isChecked())
        self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText("setup-admin")
        dialog.password_input.setText("pw")
        dialog._accept_if_valid()
        location = dialog.result_data().location
        self.assertEqual(location.connection_timeout_seconds, 7)
        self.assertEqual(location.command_timeout_seconds, 17)
        self.assertEqual(location.database, "")
        self.assertEqual(location.database_guid, "")

    def test_cancel_clears_the_secret_and_result_but_is_idempotent(self):
        dialog = self.make()
        dialog.server_input.setText("localhost")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText("user")
        dialog.password_input.setText("secret")
        dialog._accept_if_valid()
        self.assertIsNotNone(dialog.result_data())
        dialog.reject()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), "")
        dialog.password_input.setText("typed again")
        dialog.reject()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), "")
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)

    def test_cleanup_releases_secrets_and_disconnects_every_signal(self):
        dialog = self.make()
        dialog.server_input.setText("localhost")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText("user")
        dialog.password_input.setText("secret")
        dialog._accept_if_valid()
        self.assertIsNotNone(dialog.result_data())
        dialog.cleanup()
        self.assertIsNone(dialog.result_data())
        self.assertIsNone(dialog._initial_connection)
        self.assertEqual(dialog.password_input.text(), "")
        # None of the dialog's own signals reach it any more.
        dialog.password_input.setText("typed after cleanup")
        for emit in (
            dialog.connect_button.clicked.emit,
            dialog.server_input.returnPressed.emit,
            dialog.username_input.returnPressed.emit,
            dialog.password_input.returnPressed.emit,
        ):
            emit()
        dialog.cancel_button.clicked.emit()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.username_input.setEnabled(True)
        dialog.windows_auth_radio.setChecked(True)
        self.assertTrue(dialog.username_input.isEnabled())
        self.assertEqual(self.shown_warnings, [])

    def test_cleanup_tolerates_a_destroyed_dialog_and_can_run_twice(self):
        dialog = SqlConnectionDialog(RecordingIconProvider())
        parent = QtWidgets.QWidget()
        dialog.setParent(parent)
        delete(parent)
        self.assertFalse(isValid(dialog))
        dialog.cleanup()
        dialog.cleanup()
        self.assertIsNone(dialog.result_data())


class SqlConnectionDialogLayoutConstantsTests(NoModalWarnings, unittest.TestCase):
    """Every spacing, margin and width must come from the configured constants.
    The constants are replaced by distinctive values while the dialog is built, so a
    layout that silently falls back to the style default is detected (the real values
    equal common style defaults and could not be told apart)."""

    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()

    def test_the_connection_dialog_layouts_use_the_configured_constants(self):
        module = "ost_visualizer.presentation.dialogs.sql_connection_dialog"
        with patch(f"{module}.COMPACT_SPACING", 23), patch(
            f"{module}.RELAXED_SPACING", 29
        ), patch(f"{module}.NO_MARGINS", (1, 2, 3, 4)), patch(
            f"{module}.RELAXED_MARGINS", (7, 8, 9, 10)
        ), patch(
            f"{module}.SQL_CONNECTION_DIALOG_WIDTH", 411
        ):
            dialog = SqlConnectionDialog(
                RecordingIconProvider(), creator_for=_creation_handoff_support__CREATOR
            )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        self.assertEqual(dialog.width(), 411)
        layout = dialog.layout()
        self.assertEqual((margins(layout), layout.spacing()), ((7, 8, 9, 10), 29))
        form = layout.itemAt(1).layout()
        self.assertEqual(form.spacing(), 23)
        authentication = form.itemAt(
            1, QtWidgets.QFormLayout.ItemRole.FieldRole
        ).layout()
        self.assertEqual(
            (margins(authentication), authentication.spacing()), ((1, 2, 3, 4), 23)
        )
        credentials = authentication.itemAt(3).layout()
        self.assertEqual(credentials.spacing(), 23)
        options = dialog.encrypt_checkbox.parentWidget().layout()
        self.assertEqual((margins(options), options.spacing()), ((1, 2, 3, 4), 23))

    def test_window_buttons_are_removed_through_the_shared_window_helper(self):
        module = "ost_visualizer.presentation.dialogs.sql_connection_dialog"
        with patch(f"{module}.remove_minimize_maximize") as remove:
            dialog = SqlConnectionDialog(RecordingIconProvider())
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        remove.assert_called_once_with(dialog)

    def test_creator_prompt_honours_the_servers_transport_settings(self):
        location = replace(
            _creation_handoff_support__CREATOR,
            encrypt=False,
            trust_server_certificate=True,
        )
        dialog = SqlConnectionDialog(RecordingIconProvider(), creator_for=location)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        self.assertFalse(dialog.encrypt_checkbox.isChecked())
        self.assertTrue(dialog.trust_certificate_checkbox.isChecked())
        self.assertFalse(dialog.encrypt_checkbox.isEnabled())
        dialog.cleanup()
        self.assertIsNone(dialog._initial_connection)

    def test_cancel_discards_the_typed_secret(self):
        dialog = SqlConnectionDialog(RecordingIconProvider())
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        dialog.password_input.setText("typed-secret")
        dialog.cancel_button.click()
        self.assertEqual(dialog.password_input.text(), "")
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)


class SqlConnectionDialogSecretAndApplyTests(NoModalWarnings, unittest.TestCase):
    """Password hygiene of the connection dialog and direct use of the shared form."""

    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()

    def make(self, **kwargs):
        dialog = SqlConnectionDialog(RecordingIconProvider(), **kwargs)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        return dialog

    def visible_texts(self, dialog):
        """Every label, button text, tooltip and placeholder (not the typed field values)."""
        texts = [dialog.windowTitle(), dialog.toolTip()]
        for widget in dialog.findChildren(QtWidgets.QWidget):
            texts.append(widget.toolTip())
            if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
                texts.append(widget.text())
            if isinstance(widget, QtWidgets.QLineEdit):
                texts.append(widget.placeholderText())
        return texts

    def test_a_sentinel_password_stays_out_of_warnings_reprs_labels_and_descriptors(
        self,
    ):
        secret = "Sentinel-" + secrets.token_urlsafe(24)
        dialog = self.make()
        dialog.server_input.setText("localhost")
        dialog.sql_auth_radio.setChecked(True)
        dialog.password_input.setText(secret)
        dialog._accept_if_valid()
        # Failure path: no login name, so a warning is shown and nothing is returned.
        self.assertEqual(len(self.shown_warnings), 1)
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), secret)
        dialog.username_input.setText("user")
        dialog._accept_if_valid()
        result = dialog.result_data()
        self.assertEqual(result.password, secret)
        descriptor = DatabaseDescriptor.for_sql_server(
            result.location, schema_version=1
        )
        leaks = [
            *(f"{title} {message}" for _parent, title, message in self.shown_warnings),
            repr(result),
            str(result),
            f"{result}",
            repr(result.location),
            json.dumps(result.location.to_dict()),
            json.dumps(descriptor.to_dict()),
            repr(dialog),
            *self.visible_texts(dialog),
        ]
        for text in leaks:
            self.assertNotIn(secret, text)
        dialog.cleanup()
        self.assertEqual(dialog.password_input.text(), "")
        self.assertIsNone(dialog.result_data())

    def test_apply_connection_switches_authentication_in_both_directions(self):
        dialog = self.make()
        sql = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(
                server="srv",
                database="",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="login",
                encrypt=False,
                trust_server_certificate=False,
            ),
            "pw",
        )
        dialog._apply_connection(sql, lock_authentication=False)
        self.assertEqual(dialog.server_input.text(), "srv")
        self.assertEqual(dialog.username_input.text(), "login")
        self.assertEqual(dialog.password_input.text(), "pw")
        self.assertTrue(dialog.sql_auth_radio.isChecked())
        self.assertFalse(dialog.windows_auth_radio.isChecked())
        self.assertTrue(dialog.username_input.isEnabled())
        self.assertFalse(dialog.encrypt_checkbox.isChecked())
        self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
        self.assertTrue(dialog.windows_auth_radio.isEnabled())
        self.assertFalse(dialog.username_input.isReadOnly())
        windows = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="other", database="")
        )
        dialog._apply_connection(windows, lock_authentication=True)
        self.assertTrue(dialog.windows_auth_radio.isChecked())
        self.assertFalse(dialog.sql_auth_radio.isChecked())
        self.assertEqual(dialog.server_input.text(), "other")
        self.assertEqual(dialog.username_input.text(), "")
        self.assertEqual(dialog.password_input.text(), "")
        self.assertFalse(dialog.username_input.isEnabled())
        self.assertFalse(dialog.password_input.isEnabled())
        self.assertTrue(dialog.encrypt_checkbox.isChecked())
        self.assertTrue(dialog.trust_certificate_checkbox.isChecked())
        self.assertFalse(dialog.windows_auth_radio.isEnabled())
        self.assertFalse(dialog.sql_auth_radio.isEnabled())
        self.assertTrue(dialog.username_input.isReadOnly())
        self.assertTrue(dialog.password_input.isReadOnly())
