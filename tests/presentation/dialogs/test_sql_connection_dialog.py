import os
import unittest
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
)
from PySide6 import QtWidgets
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


class SqlConnectionDialogSqlCleanupTests(unittest.TestCase):
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
        self.assertIsNotNone(dialog.result_data())
        dialog.cleanup()
        self.assertIsNone(dialog.result_data())
        dialog.deleteLater()


class SqlConnectionDialogSqlDialogTests(unittest.TestCase):
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
            self.assertTrue(dialog.result_data().location.trust_server_certificate)
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


class SqlConnectionDialogCreationDialogIdentityTests(unittest.TestCase):
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
