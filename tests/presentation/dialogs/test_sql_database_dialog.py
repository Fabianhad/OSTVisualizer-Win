import os
import unittest
import dataclasses
import json
from ost_visualizer.application.dtos.application_info import APPLICATION_VERSION
from ost_visualizer.presentation import config
from ost_visualizer.presentation.utils.dialog import delete_later_if_valid
from tests.presentation.dialogs.sql_dialog_support import (
    NoModalWarnings,
    RecordingIconProvider,
    form_rows,
    margins,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from PySide6 import QtWidgets
import secrets
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    SqlDatabaseCatalogEntry,
)
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
    SqlConnectionDialogResult,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
    SqlDatabasePropertiesResult,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from tests.helpers.sql.database_foundation_support import (
    _Catalog as _database_foundation_support__Catalog,
    _IconProvider as _database_foundation_support__IconProvider,
    _SqlDatabaseCreator as _database_foundation_support__SqlDatabaseCreator,
    _app as _database_foundation_support__app,
)
import threading
from dataclasses import replace
from types import SimpleNamespace
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
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
)
from tests.helpers.sql.creation_handoff_support import (
    _CREATOR as _creation_handoff_support__CREATOR,
    _GUID as _creation_handoff_support__GUID,
    _RUNTIME as _creation_handoff_support__RUNTIME,
    _error as _creation_handoff_support__error,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    validate_sql_database_creation_name,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialogResult,
)
from tests.helpers.sql.creation_handoff_support import (
    _CLIENT,
    _CREATOR,
    _GUID,
    _RUNTIME,
    _Connections,
    _error,
    _snapshot,
)
from tests.helpers.sql.creation_release_readiness_support import (
    _ImmediateProgress as _creation_release_readiness_support__ImmediateProgress,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SqlDatabaseDialogSqlCleanupTests(NoModalWarnings, unittest.TestCase):
    def test_properties_dialog_cleanup_releases_initial_connection_secret(self):
        from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
            SqlConnectionDialogResult,
        )
        from ost_visualizer.presentation.dialogs.sql_database_dialog import (
            SqlDatabasePropertiesDialog,
            SqlDatabasePropertiesMode,
        )

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        icon_provider = type(
            "IconProvider", (), {"set_window_icon": lambda self, _widget: None}
        )()
        connection = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database=""),
            "temporary-secret",
        )
        dialog = SqlDatabasePropertiesDialog(
            icon_provider,
            SqlDatabasePropertiesMode.OPEN,
            object(),
            object(),
            connection=connection,
        )
        self.assertEqual(dialog.password_input.text(), "temporary-secret")
        dialog.cleanup()
        self.assertIsNone(dialog._initial_connection)
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), "")
        dialog.deleteLater()


class SqlDatabaseDialogSqlDialogTests(NoModalWarnings, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_sql_database_dialog_cleanup_tolerates_destroyed_parent(self):
        parent = QtWidgets.QDialog()
        dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            _database_foundation_support__Catalog([]),
            _database_foundation_support__SqlDatabaseCreator(),
            parent,
        )
        delete(parent)
        self.assertFalse(isValid(dialog))
        dialog.cleanup()
        dialog.cleanup()
        self.assertIsNone(dialog._catalog)
        self.assertIsNone(dialog._database_creator)
        self.assertIsNone(dialog._icon_provider)
        self.assertIsNone(dialog.result_data())

    def test_properties_open_validates_selection_and_cancel_clears_secret(self):
        password = secrets.token_urlsafe(24)
        selected = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_VALID",
            database_guid="00000000-0000-0000-0000-000000000123",
            state="ONLINE",
            is_compatible=True,
            schema_version=SQL_SCHEMA_V1.version,
        )
        catalog = _database_foundation_support__Catalog([selected])
        connection = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(
                server="localhost",
                database="",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="test-user",
            ),
            password,
        )
        dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.OPEN,
            catalog,
            _database_foundation_support__SqlDatabaseCreator(),
            connection=connection,
            databases=[selected],
            schema_change_allowed_fn=lambda: True,
        )
        try:
            dialog._accept_if_valid()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            result = dialog.result_data()
            self.assertEqual(
                result,
                SqlDatabasePropertiesResult(
                    replace(
                        connection.location,
                        database=selected.name,
                        database_guid=selected.database_guid,
                    ),
                    SQL_SCHEMA_V1.version,
                    password,
                ),
            )
            self.assertEqual(
                catalog.calls, [(connection.location, selected.name, password)]
            )
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        cancelled = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.OPEN,
            catalog,
            _database_foundation_support__SqlDatabaseCreator(),
            connection=connection,
            databases=[selected],
        )
        try:
            self.assertEqual(cancelled.password_input.text(), password)
            cancelled.reject()
            self.assertIsNone(cancelled.result_data())
            self.assertEqual(cancelled.password_input.text(), "")
        finally:
            cancelled.cleanup()
            cancelled.deleteLater()

    def test_properties_open_rejects_unusable_selection_with_warning(self):
        incompatible = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_OLD",
            database_guid="00000000-0000-0000-0000-000000000124",
            state="ONLINE",
            is_compatible=False,
            compatibility_message="Schema version is not supported.",
            schema_version=0,
        )
        vanished = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_GONE",
            database_guid="00000000-0000-0000-0000-000000000125",
            state="ONLINE",
            is_compatible=True,
            schema_version=SQL_SCHEMA_V1.version,
        )
        connection = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database="")
        )
        cases = (
            (
                "incompatible",
                [incompatible],
                [incompatible],
                "Schema version is not supported.",
            ),
            (
                "vanished from catalog",
                [],
                [vanished],
                "The selected database is no longer available to this login.",
            ),
            ("nothing listed", [], [], "Select a database."),
        )
        for label, catalog_entries, listed, message in cases:
            with self.subTest(label):
                dialog = SqlDatabasePropertiesDialog(
                    self.icon_provider,
                    SqlDatabasePropertiesMode.OPEN,
                    _database_foundation_support__Catalog(catalog_entries),
                    _database_foundation_support__SqlDatabaseCreator(),
                    connection=connection,
                    databases=listed,
                )
                try:
                    with patch(
                        "ost_visualizer.presentation.dialogs.sql_database_dialog."
                        "show_warning"
                    ) as warning:
                        dialog._accept_if_valid()
                    warning.assert_called_once_with(dialog, "SQL Server", message)
                    self.assertIsNone(dialog.result_data())
                    self.assertNotEqual(
                        dialog.result(), QtWidgets.QDialog.DialogCode.Accepted
                    )
                finally:
                    dialog.cleanup()
                    dialog.deleteLater()

    @patch.object(
        SqlDatabasePropertiesDialog,
        "_request_creator_connection",
        new=lambda _dialog, _location: SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database="")
        ),
    )
    def test_create_mode_initializes_before_accepting(self):
        class _Creator:
            should_fail = False

            def create_database_for_client(
                self,
                location,
                database_name,
                _password="",
                *,
                runtime_credentials,
                application_version,
                actor="",
                progress=None,
            ):
                _ = application_version, actor
                if self.should_fail:
                    raise DatabaseCatalogError("Database initialization failed.")
                return SqlDatabaseCreationResult(
                    SqlServerDatabaseLocation(
                        server=location.server,
                        database=database_name,
                        authentication_mode=runtime_credentials.authentication_mode,
                        username=runtime_credentials.username,
                        database_guid=("00000000-0000-0000-0000-000000000789"),
                    ),
                    1,
                )

        creator = _Creator()
        dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            _database_foundation_support__Catalog([]),
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        try:
            dialog.server_input.setText("localhost")
            dialog.database_name_input.setText("OSTV_TEST_CREATED")
            dialog._accept_if_valid()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            created = dialog.result_data()
            self.assertEqual(created.location.database, "OSTV_TEST_CREATED")
            self.assertEqual(
                created.location.database_guid, "00000000-0000-0000-0000-000000000789"
            )
            self.assertEqual(created.schema_version, 1)
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        creator.should_fail = True
        failed = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            _database_foundation_support__Catalog([]),
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        try:
            failed.server_input.setText("localhost")
            failed.database_name_input.setText("OSTV_TEST_FAILED")
            with patch(
                "ost_visualizer.presentation.dialogs.sql_database_dialog."
                "show_warning"
            ) as warning:
                failed._accept_if_valid()
            warning.assert_called_once_with(
                failed, "SQL Server", "Database initialization failed."
            )
            self.assertIsNone(failed.result_data())
            self.assertNotEqual(failed.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            failed.cleanup()
            failed.deleteLater()


class SqlDatabaseDialogCreationDialogIdentityTests(NoModalWarnings, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _dialog(self, creator, *, own_cleanup=True, prompt_creator=False):
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            None,
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        if own_cleanup:
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.cleanup)
        dialog.server_input.setText(_creation_handoff_support__CREATOR.server)
        dialog.database_name_input.setText("Test database")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText(_creation_handoff_support__RUNTIME.username)
        dialog.password_input.setText(_creation_handoff_support__RUNTIME.password)
        if not prompt_creator:
            prompt = patch.object(
                dialog,
                "_request_creator_connection",
                return_value=(
                    SqlConnectionDialogResult(
                        _creation_handoff_support__CREATOR, "creator-test-secret"
                    )
                ),
            )
            prompt.start()
            self.addCleanup(prompt.stop)
        return dialog

    def test_create_uses_canonical_properties_width_and_content_height(self):
        from ost_visualizer.presentation import config
        from ost_visualizer.presentation.dialogs import sql_database_dialog

        dialog = self._dialog(Mock())
        self.assertIs(type(dialog), SqlDatabasePropertiesDialog)
        self.assertEqual(dialog.width(), config.SQL_DATABASE_PROPERTIES_DIALOG_WIDTH)
        self.assertEqual(dialog.height(), dialog.layout().sizeHint().height())
        for name in (
            "SQL_DATABASE_CREATION_DIALOG_WIDTH",
            "SQL_DATABASE_CREATION_DIALOG_HEIGHT",
            "SQL_DATABASE_PROPERTIES_DIALOG_HEIGHT",
        ):
            self.assertFalse(hasattr(config, name))
        self.assertFalse(hasattr(sql_database_dialog, "_RuntimeConnectionForm"))
        self.assertEqual(dialog.findChildren(QtWidgets.QTabWidget), [])
        self.assertEqual(dialog.findChildren(QtWidgets.QGroupBox), [])
        self.assertEqual(
            dialog.button_box.buttons(), [dialog.ok_button, dialog.cancel_button]
        )
        self.assertFalse(hasattr(dialog, "runtime_auth_combo"))
        self.assertFalse(hasattr(dialog, "options_button"))
        self.assertFalse(dialog.encrypt_checkbox.isHidden())
        self.assertTrue(dialog.username_input.isEnabled())
        self.assertTrue(dialog.password_input.isEnabled())
        dialog.windows_auth_radio.setChecked(True)
        self.assertFalse(dialog.username_input.isEnabled())
        self.assertFalse(dialog.password_input.isEnabled())

    def test_cancel_before_submission_does_not_provision(self):
        creator = Mock()
        dialog = self._dialog(creator)
        self.assertEqual(
            dialog.password_input.text(), _creation_handoff_support__RUNTIME.password
        )
        dialog.reject()
        creator.create_database_for_client.assert_not_called()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertEqual(dialog.password_input.text(), "")

    def test_creation_properties_accept_server_authentication_and_database_directly(
        self,
    ):
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            Mock(),
            Mock(),
        )
        try:
            self.assertEqual(dialog.windowTitle(), "Database Properties (SQL Server)")
            self.assertEqual(dialog.server_input.text(), "")
            self.assertTrue(dialog.windows_auth_radio.isChecked())
            self.assertFalse(dialog.server_input.isReadOnly())
            self.assertFalse(dialog.username_input.isReadOnly())
            self.assertFalse(dialog.password_input.isReadOnly())
            self.assertTrue(dialog.sql_auth_radio.isEnabled())
            self.assertFalse(dialog.database_name_input.isReadOnly())
            dialog.server_input.setText("chosen-server")
            dialog.database_name_input.setText("New database")
            dialog.sql_auth_radio.setChecked(True)
            dialog.username_input.setText(_creation_handoff_support__RUNTIME.username)
            dialog.password_input.setText(_creation_handoff_support__RUNTIME.password)
            selected = dialog._connection_details()
            self.assertEqual(selected.location.server, "chosen-server")
            self.assertEqual(
                selected.location.authentication_mode, SqlAuthenticationMode.SQL_SERVER
            )
            self.assertEqual(
                selected.location.username, _creation_handoff_support__RUNTIME.username
            )
            self.assertEqual(
                selected.password, _creation_handoff_support__RUNTIME.password
            )
            self.assertEqual(dialog.findChildren(QtWidgets.QTabWidget), [])
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_creator_prompt_cancel_leaves_runtime_form_and_database_untouched(self):
        creator = Mock()
        properties = self._dialog(creator, prompt_creator=True)
        prompts = []

        def cancel(dialog):
            prompts.append(dialog)
            self.assertTrue(properties._creation_in_progress)
            properties.reject()
            properties._accept_if_valid()  # Reentrant submission cannot open another prompt.
            dialog.password_input.setText("temporary-creator-secret")
            dialog.reject()
            return dialog.result()

        with patch.object(SqlConnectionDialog, "exec", new=cancel):
            properties._accept_if_valid()
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0].password_input.text(), "")
        self.assertIsNone(prompts[0].result_data())
        self.assertFalse(properties._creation_in_progress)
        self.assertEqual(
            properties.password_input.text(),
            _creation_handoff_support__RUNTIME.password,
        )
        self.assertIsNone(properties.result_data())
        creator.create_database_for_client.assert_not_called()

    def test_creator_prompt_accept_keeps_selected_runtime_for_both_authentication_modes(
        self,
    ):
        for windows in (False, True):
            with self.subTest(windows=windows):
                creator = Mock()
                properties = self._dialog(creator, prompt_creator=True)
                if windows:
                    properties.windows_auth_radio.setChecked(True)
                runtime = properties._connection_details()
                creator.create_database_for_client.return_value = (
                    SqlDatabaseCreationResult(
                        replace(
                            runtime.location,
                            database="Test database",
                            database_guid=_creation_handoff_support__GUID,
                        ),
                        1,
                    )
                )
                prompts = []

                def accept(dialog):
                    prompts.append(dialog)
                    self.assertEqual(dialog.password_input.text(), "")
                    dialog.sql_auth_radio.setChecked(True)
                    dialog.username_input.setText(
                        _creation_handoff_support__CREATOR.username
                    )
                    dialog.password_input.setText("creator-test-secret")
                    dialog._accept_if_valid()
                    return dialog.result()

                with patch.object(SqlConnectionDialog, "exec", new=accept):
                    properties._accept_if_valid()
                self.assertEqual(len(prompts), 1)
                self.assertIsNone(prompts[0].result_data())
                args, kwargs = creator.create_database_for_client.call_args
                self.assertEqual(
                    args[0],
                    replace(
                        runtime.location,
                        authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                        username=_creation_handoff_support__CREATOR.username,
                    ),
                )
                self.assertEqual(args[2], "creator-test-secret")
                self.assertEqual(
                    kwargs["runtime_credentials"],
                    (
                        SqlDatabaseRuntimeCredentials()
                        if windows
                        else _creation_handoff_support__RUNTIME
                    ),
                )
                self.assertEqual(properties.result_data().password, runtime.password)
                self.assertEqual(
                    properties.result_data().location.authentication_mode,
                    runtime.location.authentication_mode,
                )
                self.assertEqual(
                    properties.result_data().location,
                    replace(
                        runtime.location,
                        database="Test database",
                        database_guid=_creation_handoff_support__GUID,
                    ),
                )
                self.assertEqual(properties.result_data().schema_version, 1)

    def test_destroyed_or_cleaned_properties_cannot_continue_after_creator_prompt(self):
        from shiboken6 import delete

        for destroy in (False, True):
            with self.subTest(destroy=destroy):
                creator = Mock()
                properties = self._dialog(
                    creator, prompt_creator=True, own_cleanup=False
                )
                from ost_visualizer.presentation.utils.dialog import (
                    delete_later_if_valid,
                )

                self.addCleanup(delete_later_if_valid, properties)
                self.addCleanup(properties.cleanup)

                def accept_after_close(dialog):
                    dialog.sql_auth_radio.setChecked(True)
                    dialog.username_input.setText(
                        _creation_handoff_support__CREATOR.username
                    )
                    dialog.password_input.setText("creator-test-secret")
                    dialog._accept_if_valid()
                    self.assertEqual(
                        dialog.result_data().password, "creator-test-secret"
                    )
                    if destroy:
                        delete(properties)
                    else:
                        properties.cleanup()
                    return QtWidgets.QDialog.DialogCode.Accepted

                with patch.object(SqlConnectionDialog, "exec", new=accept_after_close):
                    properties._accept_if_valid()
                creator.create_database_for_client.assert_not_called()
                self.assertIsNone(properties.result_data())
                self.assertFalse(properties._creation_in_progress)

    def test_creation_worker_keeps_gui_responsive_and_cannot_be_cancelled_mid_setup(
        self,
    ):
        caller = threading.get_ident()
        entered, release = threading.Event(), threading.Event()
        worker_threads = []
        creator = Mock()

        def create(location, name, password, **kwargs):
            worker_threads.append(threading.get_ident())
            kwargs["progress"]("Verifying runtime permissions")
            entered.set()
            if not release.wait(3):
                raise AssertionError("The Qt event loop did not remain responsive")
            return SqlDatabaseCreationResult(
                replace(
                    location,
                    database=name,
                    database_guid=_creation_handoff_support__GUID,
                    authentication_mode=SqlAuthenticationMode.WINDOWS,
                    username="",
                ),
                1,
            )

        creator.create_database_for_client.side_effect = create
        dialog = self._dialog(creator)
        gui_callbacks = []

        def release_from_gui():
            if not entered.is_set():
                QtCore.QTimer.singleShot(1, release_from_gui)
                return
            gui_callbacks.append(threading.get_ident())
            dialog.reject()
            dialog._accept_if_valid()
            release.set()

        QtCore.QTimer.singleShot(0, release_from_gui)
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
        ) as warning:
            dialog._accept_if_valid()
        warning.assert_not_called()
        self.assertEqual(gui_callbacks, [caller])
        self.assertNotEqual(worker_threads, [caller])
        creator.create_database_for_client.assert_called_once()
        created = dialog.result_data()
        self.assertEqual(created.location.database, "Test database")
        self.assertEqual(
            created.location.database_guid, _creation_handoff_support__GUID
        )
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        self.assertFalse(dialog._creation_in_progress)

    def test_tls_controls_preserve_timeouts_and_reach_creator_request(self):
        for encrypt, trust in ((True, False), (False, True), (False, False)):
            with self.subTest(encrypt=encrypt, trust=trust):
                creator = Mock()
                creator.create_database_for_client.return_value = (
                    SqlDatabaseCreationResult(
                        replace(
                            _creation_handoff_support__CREATOR,
                            database="Test database",
                            database_guid=_creation_handoff_support__GUID,
                        ),
                        1,
                    )
                )
                dialog = self._dialog(creator)
                dialog._initial_connection = SqlConnectionDialogResult(
                    _creation_handoff_support__CREATOR, "creator-test-secret"
                )
                dialog._apply_initial_connection()
                self.assertTrue(dialog.encrypt_checkbox.isChecked())
                self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
                dialog.encrypt_checkbox.setChecked(encrypt)
                dialog.trust_certificate_checkbox.setChecked(trust)
                dialog._accept_if_valid()
                location = creator.create_database_for_client.call_args.args[0]
                self.assertEqual(location.encrypt, encrypt)
                self.assertEqual(location.trust_server_certificate, trust)
                self.assertEqual(location.connection_timeout_seconds, 7)
                self.assertEqual(location.command_timeout_seconds, 17)

    def test_existing_properties_restore_transport_without_creator_controls(self):
        from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
            SqlConnectionDialogResult,
        )

        selected = SimpleNamespace(
            name="Existing",
            database_guid=_creation_handoff_support__GUID,
            schema_version=1,
            is_compatible=True,
        )
        catalog = Mock()
        catalog.get_database.return_value = selected
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.OPEN,
            catalog,
            Mock(),
            connection=SqlConnectionDialogResult(
                _creation_handoff_support__CREATOR, "existing-runtime-secret"
            ),
            databases=(selected,),
        )
        try:
            self.assertEqual(dialog.findChildren(QtWidgets.QTabWidget), [])
            self.assertFalse(hasattr(dialog, "options_button"))
            self.assertFalse(hasattr(dialog, "runtime_auth_combo"))
            self.assertTrue(dialog.server_input.isReadOnly())
            self.assertTrue(dialog.password_input.isReadOnly())
            self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
            dialog.trust_certificate_checkbox.setChecked(True)
            dialog._accept_if_valid()
            self.assertTrue(dialog.result_data().location.trust_server_certificate)
            self.assertEqual(
                dialog.result_data().location.database_guid,
                _creation_handoff_support__GUID,
            )
            self.assertEqual(dialog.result_data().location.command_timeout_seconds, 17)
            self.assertEqual(dialog.result_data().password, "existing-runtime-secret")
            self.assertEqual(dialog.result_data().location.database, "Existing")
            self.assertEqual(
                dialog.result_data().location.server,
                _creation_handoff_support__CREATOR.server,
            )
            self.assertEqual(dialog.result_data().schema_version, 1)
            self.assertTrue(
                catalog.get_database.call_args.args[0].trust_server_certificate
            )
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_creation_preserves_selected_sql_runtime_and_never_returns_creator_secret(
        self,
    ):
        creator = Mock()
        creator.create_database_for_client.return_value = SqlDatabaseCreationResult(
            replace(
                _creation_handoff_support__CREATOR,
                database="Test database",
                database_guid=_creation_handoff_support__GUID,
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username=_creation_handoff_support__RUNTIME.username,
            ),
            1,
        )
        dialog = self._dialog(creator)
        self.assertFalse(hasattr(dialog, "runtime_password_input"))
        self.assertEqual(
            dialog.password_input.echoMode(), QtWidgets.QLineEdit.EchoMode.Password
        )
        dialog._accept_if_valid()
        args, kwargs = creator.create_database_for_client.call_args
        self.assertEqual(args[0].authentication_mode, SqlAuthenticationMode.SQL_SERVER)
        self.assertEqual(args[0].username, _creation_handoff_support__CREATOR.username)
        self.assertEqual(args[2], "creator-test-secret")
        self.assertEqual(
            kwargs["runtime_credentials"], _creation_handoff_support__RUNTIME
        )
        self.assertEqual(
            dialog.result_data().password, _creation_handoff_support__RUNTIME.password
        )
        self.assertEqual(
            dialog.result_data().location.username,
            _creation_handoff_support__RUNTIME.username,
        )
        self.assertEqual(
            dialog.result_data().location.authentication_mode,
            SqlAuthenticationMode.SQL_SERVER,
        )
        self.assertNotIn("creator-test-secret", repr(dialog.result_data()))
        self.assertEqual(
            dialog.password_input.text(), _creation_handoff_support__RUNTIME.password
        )
        dialog.reject()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), "")

    def test_failed_handoff_cannot_accept_or_return_a_descriptor(self):
        creator = Mock()
        creator.create_database_for_client.side_effect = (
            _creation_handoff_support__error()
        )
        dialog = self._dialog(creator)
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
        ) as warning:
            dialog._accept_if_valid()
        self.assertIsNone(dialog.result_data())
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        warning.assert_called_once_with(
            dialog, "SQL Server", "Client permission denied."
        )
        self.assertFalse(dialog._creation_in_progress)

    def test_unexpected_setup_failure_reports_safe_message_without_descriptor(self):
        creator = Mock()
        creator.create_database_for_client.side_effect = RuntimeError(
            "raw driver detail"
        )
        dialog = self._dialog(creator)
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
        ) as warning:
            dialog._accept_if_valid()
        self.assertIsNone(dialog.result_data())
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        message = warning.call_args.args[2]
        self.assertIn("SQL database setup failed unexpectedly", message)
        self.assertNotIn("raw driver detail", message)

    def test_creation_requires_schema_permission_and_valid_name_before_prompting(self):
        cases = (
            (
                "no permission",
                lambda: False,
                "Test database",
                "You do not have permission",
            ),
            (
                "blank name",
                lambda: True,
                "   ",
                "Database names must be 1 to 128 characters",
            ),
        )
        for label, allowed, name, message in cases:
            with self.subTest(label):
                creator = Mock()
                dialog = self._dialog(creator, prompt_creator=True)
                dialog._schema_change_allowed_fn = allowed
                dialog.database_name_input.setText(name)
                with patch.object(SqlConnectionDialog, "exec") as prompt, patch(
                    "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
                ) as warning:
                    dialog._accept_if_valid()
                prompt.assert_not_called()
                creator.create_database_for_client.assert_not_called()
                warning.assert_called_once()
                self.assertTrue(warning.call_args.args[2].startswith(message))
                self.assertIsNone(dialog.result_data())


class SqlDatabaseDialogCreationReleaseBoundaryTests(NoModalWarnings, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _entry(self):
        return FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                replace(
                    _CREATOR,
                    username=_RUNTIME.username,
                    database="Created",
                    database_guid=_GUID,
                ),
                schema_version=1,
            )
        )

    def test_properties_cleanup_while_setup_completes_cannot_accept_result(self):
        creator = Mock()
        creator.create_database_for_client.return_value = SqlDatabaseCreationResult(
            self._entry().descriptor.sql_location, 1
        )
        properties = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            Mock(),
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        self.addCleanup(properties.deleteLater)
        self.addCleanup(properties.cleanup)
        properties.server_input.setText(_CREATOR.server)
        properties.database_name_input.setText("Created")
        properties.sql_auth_radio.setChecked(True)
        properties.username_input.setText(_RUNTIME.username)
        properties.password_input.setText(_RUNTIME.password)

        class _CleanedOwner(_creation_release_readiness_support__ImmediateProgress):
            def exec(self):
                super().exec()
                properties.cleanup()

        with patch.object(
            properties,
            "_request_creator_connection",
            return_value=SqlConnectionDialogResult(_CREATOR, "creator-test-secret"),
        ), patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.ProgressDialog",
            _CleanedOwner,
        ):
            properties._accept_if_valid()
        creator.create_database_for_client.assert_called_once()
        self.assertIsNone(properties.result_data())
        self.assertNotEqual(properties.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_close_request_during_creation_keeps_dialog_owned(self):
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            Mock(),
            Mock(),
        )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        dialog.show()
        dialog._creation_in_progress = True
        self.assertFalse(dialog.close())
        self.assertTrue(dialog.isVisible())
        self.assertIsNone(dialog.result_data())
        dialog._creation_in_progress = False
        dialog.reject()
        self.assertFalse(dialog.isVisible())

    def test_cleanup_while_the_real_worker_runs_cannot_accept_the_result(self):
        entered, release = threading.Event(), threading.Event()
        creator = Mock()

        def create(location, name, password, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("The Qt event loop did not remain responsive")
            return SqlDatabaseCreationResult(self._entry().descriptor.sql_location, 1)

        creator.create_database_for_client.side_effect = create
        properties = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            Mock(),
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        self.addCleanup(properties.deleteLater)
        self.addCleanup(properties.cleanup)
        properties.server_input.setText(_CREATOR.server)
        properties.database_name_input.setText("Created")
        properties.sql_auth_radio.setChecked(True)
        properties.username_input.setText(_RUNTIME.username)
        properties.password_input.setText(_RUNTIME.password)
        cleaned_from = []

        def cleanup_from_gui():
            if not entered.is_set():
                QtCore.QTimer.singleShot(1, cleanup_from_gui)
                return
            cleaned_from.append(threading.get_ident())
            properties.cleanup()
            release.set()

        QtCore.QTimer.singleShot(0, cleanup_from_gui)
        with patch.object(
            properties,
            "_request_creator_connection",
            return_value=SqlConnectionDialogResult(_CREATOR, "creator-test-secret"),
        ), patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
        ) as warning:
            properties._accept_if_valid()
        self.assertEqual(cleaned_from, [threading.get_ident()])
        creator.create_database_for_client.assert_called_once()
        warning.assert_not_called()
        self.assertIsNone(properties.result_data())
        self.assertNotEqual(properties.result(), QtWidgets.QDialog.DialogCode.Accepted)
        self.assertEqual(properties.password_input.text(), "")
        self.assertFalse(properties._creation_in_progress)


class _RecordingProgressDialog:
    """ProgressDialog stand-in: runs the task synchronously and records its lifecycle."""

    instances = []
    on_exec = None

    def __init__(self, name, task, **kwargs):
        self.name, self.task, self.kwargs = name, task, kwargs
        self.result = None
        self.error = None
        self.cleaned = 0
        self.deleted = 0
        type(self).instances.append(self)

    def exec(self):
        if type(self).on_exec is not None:
            type(self).on_exec(self)
        try:
            self.result = self.task()
        except Exception as exc:
            self.error = exc

    def cleanup(self):
        self.cleaned += 1

    def deleteLater(self):
        self.deleted += 1


class _SpyCreator:
    """Explicit creator fake with the real create_database_for_client signature."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def create_database_for_client(
        self,
        location,
        database_name,
        password="",
        *,
        runtime_credentials,
        application_version,
        actor="",
        progress=None,
    ):
        self.calls.append(
            dict(
                location=location,
                database_name=database_name,
                password=password,
                runtime_credentials=runtime_credentials,
                application_version=application_version,
                actor=actor,
                progress=progress,
            )
        )
        if self.error is not None:
            raise self.error
        return self.result


class _RaisingCatalog:
    def __init__(self, error):
        self.error = error

    def get_database(self, location, database_name, password=""):
        raise self.error


class SqlDatabasePropertiesDialogChromeTests(NoModalWarnings, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()

    def make(self, mode, *, connection=None, databases=(), creator=None, allowed=None):
        self.icons = RecordingIconProvider()
        dialog = SqlDatabasePropertiesDialog(
            self.icons,
            mode,
            _database_foundation_support__Catalog(list(databases)),
            creator or _SpyCreator(),
            connection=connection,
            databases=databases,
            schema_change_allowed_fn=allowed,
        )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        return dialog

    def entries(self):
        return [
            SqlDatabaseCatalogEntry(
                name=name,
                database_guid=f"00000000-0000-0000-0000-00000000000{index}",
                state="ONLINE",
                is_compatible=True,
                schema_version=1,
            )
            for index, name in enumerate(("Alpha", "Beta"), 1)
        ]

    def connection(self):
        return SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database=""), ""
        )

    def test_open_mode_requires_an_authenticated_connection(self):
        with self.assertRaisesRegex(
            ValueError,
            "^Open mode requires authenticated SQL connection details$",
        ):
            SqlDatabasePropertiesDialog(
                RecordingIconProvider(),
                SqlDatabasePropertiesMode.OPEN,
                object(),
                object(),
            )

    def test_chrome_title_icon_modality_and_fixed_width(self):
        dialog = self.make(SqlDatabasePropertiesMode.CREATE)
        self.assertEqual(dialog.windowTitle(), "Database Properties (SQL Server)")
        self.assertEqual(self.icons.widgets, [dialog])
        self.assertTrue(dialog.isModal())
        flags = dialog.windowFlags()
        self.assertFalse(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
        self.assertFalse(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.assertEqual(dialog.width(), config.SQL_DATABASE_PROPERTIES_DIALOG_WIDTH)
        self.assertEqual(dialog.minimumWidth(), dialog.maximumWidth())
        layout = dialog.layout()
        self.assertEqual(margins(layout), config.RELAXED_MARGINS)
        self.assertEqual(layout.spacing(), config.RELAXED_SPACING)

    def test_layout_is_connection_form_database_row_options_stretch_buttons(self):
        for mode, connection in (
            (SqlDatabasePropertiesMode.CREATE, None),
            (SqlDatabasePropertiesMode.OPEN, self.connection()),
        ):
            with self.subTest(mode=mode):
                dialog = self.make(
                    mode, connection=connection, databases=self.entries()
                )
                layout = dialog.layout()
                self.assertEqual(layout.count(), 5)
                self.assertIsInstance(layout.itemAt(0).layout(), QtWidgets.QFormLayout)
                database_form = layout.itemAt(1).layout()
                self.assertIsInstance(database_form, QtWidgets.QFormLayout)
                self.assertEqual(database_form.spacing(), config.COMPACT_SPACING)
                expected = (
                    dialog.database_combo
                    if mode == SqlDatabasePropertiesMode.OPEN
                    else dialog.database_name_input
                )
                self.assertEqual(form_rows(database_form), [("Database:", expected)])
                self.assertIs(
                    layout.itemAt(2).widget(), dialog.encrypt_checkbox.parentWidget()
                )
                self.assertIsNotNone(layout.itemAt(3).spacerItem())
                self.assertIs(layout.itemAt(4).widget(), dialog.button_box)

    def test_open_mode_lists_the_catalog_databases_and_hides_the_name_field(self):
        dialog = self.make(
            SqlDatabasePropertiesMode.OPEN,
            connection=self.connection(),
            databases=self.entries(),
        )
        self.assertFalse(dialog.database_combo.isHidden())
        self.assertTrue(dialog.database_name_input.isHidden())
        self.assertEqual(
            [
                dialog.database_combo.itemText(i)
                for i in range(dialog.database_combo.count())
            ],
            ["Alpha", "Beta"],
        )
        self.assertEqual(
            [dialog.database_combo.itemData(i).name for i in range(2)],
            ["Alpha", "Beta"],
        )
        self.assertIsNone(dialog.ok_button.toolTip() or None)

    def test_repopulating_the_database_list_replaces_the_previous_entries(self):
        dialog = self.make(
            SqlDatabasePropertiesMode.OPEN,
            connection=self.connection(),
            databases=self.entries(),
        )
        beta = self.entries()[1]
        dialog._databases = (beta,)
        dialog._populate_databases()
        self.assertEqual(
            [
                dialog.database_combo.itemText(i)
                for i in range(dialog.database_combo.count())
            ],
            ["Beta"],
        )
        self.assertEqual(dialog.database_combo.itemData(0), beta)

    def test_create_mode_shows_the_name_field_and_explains_the_account_used(self):
        dialog = self.make(SqlDatabasePropertiesMode.CREATE)
        self.assertTrue(dialog.database_combo.isHidden())
        self.assertFalse(dialog.database_name_input.isHidden())
        self.assertEqual(dialog.database_combo.count(), 0)
        self.assertTrue(dialog.database_name_input.isClearButtonEnabled())
        self.assertEqual(
            dialog.ok_button.toolTip(),
            "The account selected here is used for normal access. "
            "You will be asked for separate temporary database-creator credentials.",
        )

    def test_buttons_are_ok_default_and_cancel(self):
        dialog = self.make(SqlDatabasePropertiesMode.CREATE)
        self.assertTrue(dialog.ok_button.isDefault())
        self.assertEqual(
            dialog.button_box.standardButton(dialog.ok_button),
            QtWidgets.QDialogButtonBox.StandardButton.Ok,
        )
        self.assertEqual(
            dialog.button_box.standardButton(dialog.cancel_button),
            QtWidgets.QDialogButtonBox.StandardButton.Cancel,
        )
        self.assertEqual(
            dialog.button_box.buttons(), [dialog.ok_button, dialog.cancel_button]
        )

    def test_fields_are_read_only_when_a_connection_is_supplied_or_in_open_mode(self):
        cases = {
            "create without connection": (
                SqlDatabasePropertiesMode.CREATE,
                None,
                False,
            ),
            "create with connection": (
                SqlDatabasePropertiesMode.CREATE,
                self.connection(),
                True,
            ),
            "open": (SqlDatabasePropertiesMode.OPEN, self.connection(), True),
        }
        for label, (mode, connection, locked) in cases.items():
            with self.subTest(label):
                dialog = self.make(
                    mode, connection=connection, databases=self.entries()
                )
                for field in (
                    dialog.server_input,
                    dialog.username_input,
                    dialog.password_input,
                ):
                    self.assertEqual(field.isClearButtonEnabled(), not locked)
                self.assertEqual(dialog.server_input.isReadOnly(), locked)
                self.assertEqual(dialog.windows_auth_radio.isEnabled(), not locked)
                self.assertEqual(dialog.sql_auth_radio.isEnabled(), not locked)
                self.assertEqual(dialog.username_input.isReadOnly(), locked)
                self.assertEqual(dialog.password_input.isReadOnly(), locked)

    def test_authentication_fields_are_synchronized_from_the_start(self):
        sql = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(
                server="localhost",
                database="",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="login",
            ),
            "secret",
        )
        for connection, enabled in ((self.connection(), False), (sql, True)):
            with self.subTest(sql=enabled):
                dialog = self.make(
                    SqlDatabasePropertiesMode.OPEN,
                    connection=connection,
                    databases=self.entries(),
                )
                self.assertEqual(dialog.username_input.isEnabled(), enabled)
                self.assertEqual(dialog.password_input.isEnabled(), enabled)
                self.assertEqual(dialog.sql_auth_radio.isChecked(), enabled)
                self.assertEqual(dialog.windows_auth_radio.isChecked(), not enabled)

    def test_ok_enter_and_cancel_are_wired_in_open_mode(self):
        triggers = {
            "ok click": lambda d: d.ok_button.click(),
            "server enter": lambda d: d.server_input.returnPressed.emit(),
            "login enter": lambda d: d.username_input.returnPressed.emit(),
            "password enter": lambda d: d.password_input.returnPressed.emit(),
            "database name enter": lambda d: d.database_name_input.returnPressed.emit(),
        }
        for label, trigger in triggers.items():
            with self.subTest(label):
                dialog = self.make(
                    SqlDatabasePropertiesMode.OPEN,
                    connection=self.connection(),
                    databases=self.entries(),
                )
                trigger(dialog)
                self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
                self.assertEqual(dialog.result_data().location.database, "Alpha")
        dialog = self.make(
            SqlDatabasePropertiesMode.OPEN,
            connection=SqlConnectionDialogResult(
                self.connection().location, "typed-secret"
            ),
            databases=self.entries(),
        )
        self.assertEqual(dialog.password_input.text(), "typed-secret")
        dialog.cancel_button.click()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), "")

    def test_open_mode_submits_the_current_combo_selection(self):
        dialog = self.make(
            SqlDatabasePropertiesMode.OPEN,
            connection=self.connection(),
            databases=self.entries(),
        )
        dialog.database_combo.setCurrentIndex(1)
        dialog._accept_if_valid()
        self.assertEqual(dialog.result_data().location.database, "Beta")
        self.assertEqual(
            dialog.result_data().location.database_guid,
            "00000000-0000-0000-0000-000000000002",
        )

    def test_cleanup_releases_everything_and_disconnects_the_dialog_signals(self):
        dialog = self.make(
            SqlDatabasePropertiesMode.OPEN,
            connection=self.connection(),
            databases=self.entries(),
        )
        dialog._accept_if_valid()
        self.assertIsNotNone(dialog.result_data())
        dialog.cleanup()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog._databases, ())
        self.assertEqual(dialog.database_combo.count(), 0)
        self.assertIsNone(dialog._catalog)
        self.assertIsNone(dialog._database_creator)
        self.assertIsNone(dialog._icon_provider)
        self.assertIsNone(dialog._initial_connection)
        dialog.windows_auth_radio.setEnabled(True)
        for emit in (
            dialog.ok_button.clicked.emit,
            dialog.server_input.returnPressed.emit,
            dialog.username_input.returnPressed.emit,
            dialog.password_input.returnPressed.emit,
            dialog.database_name_input.returnPressed.emit,
        ):
            emit()
        dialog.cancel_button.clicked.emit()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.username_input.setEnabled(False)
        dialog.sql_auth_radio.setChecked(True)
        self.assertFalse(dialog.username_input.isEnabled())
        self.assertEqual(self.shown_warnings, [])

    def test_the_result_secret_is_redacted_and_the_result_is_immutable(self):
        result = SqlDatabasePropertiesResult(
            SqlServerDatabaseLocation(server="s", database="d"), 1, "topsecret"
        )
        self.assertEqual(
            repr(result),
            f"SqlDatabasePropertiesResult(location={result.location!r}, "
            "schema_version=1, password=<redacted>)",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.schema_version = 2

    def test_open_mode_reports_database_catalog_failures_as_warnings(self):
        for error in (
            DatabaseCatalogError("catalog down"),
            OSError("network down"),
            ValueError("bad name"),
        ):
            with self.subTest(error=type(error).__name__):
                self.shown_warnings.clear()
                dialog = self.make(
                    SqlDatabasePropertiesMode.OPEN,
                    connection=self.connection(),
                    databases=self.entries(),
                )
                dialog._catalog = _RaisingCatalog(error)
                dialog._accept_if_valid()
                self.assertEqual(
                    self.shown_warnings, [(dialog, "SQL Server", str(error))]
                )
                self.assertIsNone(dialog.result_data())
                self.assertNotEqual(
                    dialog.result(), QtWidgets.QDialog.DialogCode.Accepted
                )


class SqlDatabaseCreationFlowContractTests(NoModalWarnings, unittest.TestCase):
    """_create_database / _request_creator_connection with a synchronous progress fake."""

    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()

    def setUp(self):
        super().setUp()
        _RecordingProgressDialog.instances = []
        _RecordingProgressDialog.on_exec = None
        patcher = patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.ProgressDialog",
            _RecordingProgressDialog,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.creator_connection = SqlConnectionDialogResult(
            _creation_handoff_support__CREATOR, "creator-secret"
        )
        self.created = SqlDatabaseCreationResult(
            replace(
                _creation_handoff_support__CREATOR,
                database="Created",
                database_guid=_creation_handoff_support__GUID,
            ),
            1,
        )

    def dialog(self, creator=None, *, allowed=lambda: True, prompt=True):
        self.creator = creator or _SpyCreator(self.created)
        dialog = SqlDatabasePropertiesDialog(
            RecordingIconProvider(),
            SqlDatabasePropertiesMode.CREATE,
            None,
            self.creator,
            schema_change_allowed_fn=allowed,
        )
        self.addCleanup(delete_later_if_valid, dialog)
        self.addCleanup(dialog.cleanup)
        dialog.server_input.setText("sql-host")
        dialog.database_name_input.setText("  New database  ")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText("runtime-user")
        dialog.password_input.setText("runtime-secret")
        if prompt:
            self.prompted = []
            dialog._request_creator_connection = lambda location: (
                self.prompted.append(location) or self.creator_connection
            )
        return dialog

    def test_creation_submits_the_exact_request_to_the_creator(self):
        dialog = self.dialog()
        dialog._accept_if_valid()
        (call,) = self.creator.calls
        self.assertEqual(call["database_name"], "New database")
        self.assertEqual(call["password"], "creator-secret")
        self.assertEqual(call["application_version"], APPLICATION_VERSION)
        self.assertEqual(call["actor"], _creation_handoff_support__CREATOR.username)
        self.assertEqual(
            call["runtime_credentials"],
            SqlDatabaseRuntimeCredentials(
                SqlAuthenticationMode.SQL_SERVER, "runtime-user", "runtime-secret"
            ),
        )
        self.assertTrue(callable(call["progress"]))
        # The creator reports through the very reporter the progress dialog listens to.
        (progress_dialog,) = _RecordingProgressDialog.instances
        self.assertEqual(call["progress"], progress_dialog.kwargs["reporter"].report)
        (prompted,) = self.prompted
        self.assertEqual(prompted.server, "sql-host")
        self.assertEqual(
            call["location"],
            replace(
                prompted,
                authentication_mode=_creation_handoff_support__CREATOR.authentication_mode,
                username=_creation_handoff_support__CREATOR.username,
            ),
        )
        result = dialog.result_data()
        self.assertEqual(
            (result.location, result.schema_version, result.password),
            (self.created.location, 1, "runtime-secret"),
        )
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_progress_dialog_is_titled_by_the_database_and_always_released(self):
        dialog = self.dialog()
        dialog._accept_if_valid()
        (progress,) = _RecordingProgressDialog.instances
        self.assertEqual(progress.name, "New database")
        self.assertIs(progress.kwargs["parent"], dialog)
        self.assertEqual(progress.kwargs["action_text"], "SQL database setup")
        self.assertIn("reporter", progress.kwargs)
        self.assertEqual((progress.cleaned, progress.deleted), (1, 1))
        self.assertFalse(dialog._creation_in_progress)

    def test_submit_and_cancel_are_ignored_while_the_creation_runs(self):
        dialog = self.dialog()
        seen = {}

        def during(progress):
            seen["in_progress"] = dialog._creation_in_progress
            dialog.reject()
            dialog._accept_if_valid()
            seen["password_while_running"] = dialog.password_input.text()

        _RecordingProgressDialog.on_exec = during
        dialog._accept_if_valid()
        self.assertTrue(seen["in_progress"])
        # Cancel is ignored mid-setup: the secret is not wiped and nothing restarts.
        self.assertEqual(seen["password_while_running"], "runtime-secret")
        self.assertEqual(len(self.creator.calls), 1)
        self.assertEqual(len(self.prompted), 1)
        self.assertIsNotNone(dialog.result_data())
        self.assertFalse(dialog._creation_in_progress)

    def test_a_missing_or_denying_permission_check_refuses_creation(self):
        for label, allowed in (("none", None), ("denies", lambda: False)):
            with self.subTest(label):
                self.shown_warnings.clear()
                dialog = self.dialog(allowed=allowed)
                dialog._accept_if_valid()
                self.assertEqual(
                    self.shown_warnings,
                    [
                        (
                            dialog,
                            "SQL Server",
                            "You do not have permission to create a database.",
                        )
                    ],
                )
                self.assertEqual((self.creator.calls, self.prompted), ([], []))
                self.assertIsNone(dialog.result_data())

    def test_a_declined_creator_prompt_creates_nothing(self):
        dialog = self.dialog()
        dialog._request_creator_connection = lambda location: None
        dialog._accept_if_valid()
        self.assertEqual(self.creator.calls, [])
        self.assertEqual(_RecordingProgressDialog.instances, [])
        self.assertIsNone(dialog.result_data())
        self.assertEqual(self.shown_warnings, [])

    def test_setup_that_returns_nothing_warns_to_inspect_the_server(self):
        dialog = self.dialog(_SpyCreator(None))
        dialog._accept_if_valid()
        self.assertEqual(
            self.shown_warnings,
            [
                (
                    dialog,
                    "SQL Server",
                    "Database setup did not complete. Inspect the server before "
                    "retrying creation.",
                )
            ],
        )
        self.assertIsNone(dialog.result_data())
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_known_setup_errors_show_their_own_message_unknown_ones_a_safe_one(self):
        for error in (
            DatabaseCatalogError("catalog says no"),
            OSError("disk says no"),
            ValueError("name says no"),
        ):
            with self.subTest(error=type(error).__name__):
                self.shown_warnings.clear()
                dialog = self.dialog(_SpyCreator(error=error))
                dialog._accept_if_valid()
                self.assertEqual(
                    self.shown_warnings, [(dialog, "SQL Server", str(error))]
                )
                self.assertFalse(dialog._creation_in_progress)
        self.shown_warnings.clear()
        dialog = self.dialog(_SpyCreator(error=RuntimeError("raw driver detail")))
        dialog._accept_if_valid()
        ((_parent, _title, message),) = self.shown_warnings
        self.assertTrue(message.startswith("SQL database setup failed unexpectedly."))
        self.assertNotIn("raw driver detail", message)

    def test_blank_database_names_are_rejected_before_the_creator_prompt(self):
        dialog = self.dialog()
        dialog.database_name_input.setText("   ")
        dialog._accept_if_valid()
        self.assertEqual(self.prompted, [])
        self.assertEqual(len(self.shown_warnings), 1)
        self.assertIn(
            "Database names must be 1 to 128 characters", self.shown_warnings[0][2]
        )

    def test_a_dialog_destroyed_during_the_setup_cannot_be_completed(self):
        dialog = self.dialog()
        _RecordingProgressDialog.on_exec = lambda _progress: delete(dialog)
        dialog._accept_if_valid()
        self.assertEqual(len(self.creator.calls), 1)
        (progress,) = _RecordingProgressDialog.instances
        self.assertEqual((progress.cleaned, progress.deleted), (1, 1))
        self.assertEqual(self.shown_warnings, [])

    def test_a_dialog_cleaned_up_during_the_setup_cannot_accept_the_result(self):
        dialog = self.dialog()
        _RecordingProgressDialog.on_exec = lambda _progress: dialog.cleanup()
        dialog._accept_if_valid()
        self.assertIsNone(dialog.result_data())
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        # The setup that was already submitted still runs against the creator captured
        # when it started (cleanup() released the dialog's own reference), and the
        # discarded completion neither warns nor registers anything.
        self.assertEqual(len(self.creator.calls), 1)
        self.assertEqual(self.shown_warnings, [])

    def prompt_dialog_class(self, on_exec, accepted=True):
        outer = self

        class _Prompt(QtWidgets.QDialog):
            instances = []

            def __init__(inner, icon_provider, parent=None, *, creator_for=None):
                # Deliberately not parented: destroying the owner must not also
                # destroy this prompt, so the owner check is tested on its own.
                super().__init__(None)
                inner.args = (icon_provider, parent, creator_for)
                inner.cleaned = 0
                type(inner).instances.append(inner)

            def exec(inner):
                on_exec(inner)
                return (
                    QtWidgets.QDialog.DialogCode.Accepted
                    if accepted
                    else QtWidgets.QDialog.DialogCode.Rejected
                )

            def result_data(inner):
                return outer.creator_connection

            def cleanup(inner):
                inner.cleaned += 1

        return _Prompt

    def test_the_creator_prompt_receives_the_server_and_is_always_released(self):
        dialog = self.dialog(prompt=False)
        prompt = self.prompt_dialog_class(lambda inner: None)
        deleted = []
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.SqlConnectionDialog",
            prompt,
        ), patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.delete_later_if_valid",
            deleted.append,
        ):
            location = dialog._connection_details().location
            self.assertIs(
                dialog._request_creator_connection(location), self.creator_connection
            )
        (instance,) = prompt.instances
        self.assertIs(instance.args[1], dialog)
        self.assertEqual(instance.args[2], location)
        self.assertEqual(instance.cleaned, 1)
        self.assertEqual(deleted, [instance])
        self.assertFalse(dialog._creation_in_progress)

    def test_a_rejected_creator_prompt_yields_nothing_and_clears_the_flag(self):
        dialog = self.dialog(prompt=False)
        seen = []
        prompt = self.prompt_dialog_class(
            lambda inner: seen.append(dialog._creation_in_progress), accepted=False
        )
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.SqlConnectionDialog",
            prompt,
        ):
            location = dialog._connection_details().location
            self.assertIsNone(dialog._request_creator_connection(location))
        self.assertEqual(seen, [True])
        self.assertFalse(dialog._creation_in_progress)

    def test_a_creator_prompt_whose_owner_or_own_dialog_is_gone_yields_nothing(self):
        for label in ("owner destroyed", "prompt destroyed", "owner cleaned up"):
            with self.subTest(label):
                dialog = self.dialog(prompt=False)

                def on_exec(inner, label=label, dialog=dialog):
                    if label == "owner destroyed":
                        delete(dialog)
                    elif label == "prompt destroyed":
                        delete(inner)
                    else:
                        dialog.cleanup()

                prompt = self.prompt_dialog_class(on_exec)
                with patch(
                    "ost_visualizer.presentation.dialogs.sql_database_dialog.SqlConnectionDialog",
                    prompt,
                ):
                    location = _creation_handoff_support__CREATOR
                    self.assertIsNone(dialog._request_creator_connection(location))
                self.assertFalse(dialog._creation_in_progress)

    def test_a_blank_server_is_reported_before_any_creation_step(self):
        dialog = self.dialog()
        dialog.server_input.setText("   ")
        dialog._accept_if_valid()
        self.assertEqual(
            self.shown_warnings, [(dialog, "SQL Server", "Enter a SQL Server name.")]
        )
        self.assertEqual((self.creator.calls, self.prompted), ([], []))
        self.assertEqual(_RecordingProgressDialog.instances, [])
        self.assertIsNone(dialog.result_data())


class SqlDatabaseDialogSecretHandlingTests(NoModalWarnings, unittest.TestCase):
    """SQL passwords never reach warnings, reprs, labels, saved descriptors or error chains."""

    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()

    def setUp(self):
        super().setUp()
        _RecordingProgressDialog.instances = []
        _RecordingProgressDialog.on_exec = None
        patcher = patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.ProgressDialog",
            _RecordingProgressDialog,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime_secret = "Runtime-" + secrets.token_urlsafe(24)
        self.creator_secret = "Creator-" + secrets.token_urlsafe(24)
        self.creator_connection = SqlConnectionDialogResult(
            _creation_handoff_support__CREATOR, self.creator_secret
        )

    def creation_dialog(self, creator):
        dialog = SqlDatabasePropertiesDialog(
            RecordingIconProvider(),
            SqlDatabasePropertiesMode.CREATE,
            None,
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        self.addCleanup(delete_later_if_valid, dialog)
        self.addCleanup(dialog.cleanup)
        dialog.server_input.setText("sql-host")
        dialog.database_name_input.setText("Secret database")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText("runtime-user")
        dialog.password_input.setText(self.runtime_secret)
        dialog._request_creator_connection = lambda _location: self.creator_connection
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

    def test_unexpected_setup_failures_never_expose_either_password(self):
        leaky = RuntimeError(
            f"login failed for {self.creator_secret} / {self.runtime_secret}"
        )
        dialog = self.creation_dialog(_SpyCreator(error=leaky))
        dialog._accept_if_valid()
        ((_parent, title, message),) = self.shown_warnings
        self.assertEqual(
            message,
            "SQL database setup failed unexpectedly. Inspect the server before "
            "retrying; no connection was registered or database dropped.",
        )
        for secret in (self.creator_secret, self.runtime_secret):
            self.assertNotIn(secret, f"{title} {message}")
        self.assertIsNone(dialog.result_data())
        connection = dialog._connection_details()
        with self.assertRaises(DatabaseCatalogError) as raised:
            dialog._create_database(connection)
        error = raised.exception
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        for secret in (self.creator_secret, self.runtime_secret):
            for text in (str(error), repr(error), repr(error.args)):
                self.assertNotIn(secret, text)

    def test_a_successful_creation_returns_only_the_runtime_password(self):
        created = SqlDatabaseCreationResult(
            replace(
                _creation_handoff_support__CREATOR,
                database="Secret database",
                database_guid=_creation_handoff_support__GUID,
                username="runtime-user",
            ),
            1,
        )
        creator = _SpyCreator(created)
        dialog = self.creation_dialog(creator)
        dialog._accept_if_valid()
        result = dialog.result_data()
        self.assertEqual(result.password, self.runtime_secret)
        (call,) = creator.calls
        self.assertEqual(call["password"], self.creator_secret)
        descriptor = DatabaseDescriptor.for_sql_server(
            result.location, schema_version=result.schema_version
        )
        texts = [
            *(f"{title} {message}" for _parent, title, message in self.shown_warnings),
            repr(result),
            str(result),
            f"{result}",
            repr(result.location),
            json.dumps(descriptor.to_dict()),
            repr(call["runtime_credentials"]),
            repr(dialog),
            *self.visible_texts(dialog),
        ]
        for text in texts:
            self.assertNotIn(self.runtime_secret, text)
            self.assertNotIn(self.creator_secret, text)
        self.assertNotEqual(result.password, self.creator_secret)

    def test_the_same_login_refusal_is_shown_and_returns_no_descriptor(self):
        refusal = SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.PERMISSION_DENIED,
                "Creator and normal-use access must be different logins on the "
                "same SQL Server.",
            )
        )
        creator = _SpyCreator(error=refusal)
        dialog = self.creation_dialog(creator)
        dialog.username_input.setText(_creation_handoff_support__CREATOR.username)
        dialog._accept_if_valid()
        self.assertEqual(self.shown_warnings, [(dialog, "SQL Server", str(refusal))])
        self.assertEqual(len(creator.calls), 1)
        self.assertEqual(
            creator.calls[0]["runtime_credentials"].username,
            _creation_handoff_support__CREATOR.username,
        )
        self.assertIsNone(dialog.result_data())
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        self.assertFalse(dialog._creation_in_progress)
        (progress,) = _RecordingProgressDialog.instances
        self.assertEqual((progress.cleaned, progress.deleted), (1, 1))
        for secret in (self.creator_secret, self.runtime_secret):
            self.assertNotIn(secret, self.shown_warnings[0][2])

    def test_the_open_mode_result_keeps_its_password_out_of_every_text(self):
        selected = SqlDatabaseCatalogEntry(
            name="Alpha",
            database_guid="00000000-0000-0000-0000-000000000001",
            state="ONLINE",
            is_compatible=True,
            schema_version=1,
        )
        catalog = _database_foundation_support__Catalog([selected])
        connection = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(
                server="sql-host",
                database="",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="runtime-user",
            ),
            self.runtime_secret,
        )
        dialog = SqlDatabasePropertiesDialog(
            RecordingIconProvider(),
            SqlDatabasePropertiesMode.OPEN,
            catalog,
            _SpyCreator(),
            connection=connection,
            databases=[selected],
        )
        self.addCleanup(delete_later_if_valid, dialog)
        self.addCleanup(dialog.cleanup)
        dialog._accept_if_valid()
        result = dialog.result_data()
        self.assertEqual(result.password, self.runtime_secret)
        self.assertEqual(
            catalog.calls, [(connection.location, "Alpha", self.runtime_secret)]
        )
        descriptor = DatabaseDescriptor.for_sql_server(
            result.location, schema_version=result.schema_version
        )
        for text in (
            repr(result),
            str(result),
            repr(connection),
            repr(dialog),
            json.dumps(descriptor.to_dict()),
            *self.visible_texts(dialog),
        ):
            self.assertNotIn(self.runtime_secret, text)
        dialog.cleanup()
        self.assertEqual(dialog.password_input.text(), "")


class SqlDatabasePropertiesDialogLayoutConstantsTests(
    NoModalWarnings, unittest.TestCase
):
    """Spacing, margins and width come from the configured constants (see the
    connection dialog twin of this test for the reasoning)."""

    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()

    def build(self, mode, **kwargs):
        module = "ost_visualizer.presentation.dialogs.sql_database_dialog"
        form_module = "ost_visualizer.presentation.dialogs.sql_connection_dialog"
        with patch(f"{module}.COMPACT_SPACING", 23), patch(
            f"{module}.RELAXED_SPACING", 29
        ), patch(f"{module}.RELAXED_MARGINS", (7, 8, 9, 10)), patch(
            f"{module}.SQL_DATABASE_PROPERTIES_DIALOG_WIDTH", 433
        ), patch(
            f"{form_module}.COMPACT_SPACING", 23
        ), patch(
            f"{form_module}.NO_MARGINS", (1, 2, 3, 4)
        ):
            dialog = SqlDatabasePropertiesDialog(
                RecordingIconProvider(), mode, None, _SpyCreator(), **kwargs
            )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        return dialog

    def test_layouts_use_the_configured_constants_in_both_modes(self):
        connection = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database=""), ""
        )
        for mode, kwargs in (
            (SqlDatabasePropertiesMode.CREATE, {}),
            (SqlDatabasePropertiesMode.OPEN, {"connection": connection}),
        ):
            with self.subTest(mode=mode):
                dialog = self.build(mode, **kwargs)
                self.assertEqual(dialog.width(), 433)
                layout = dialog.layout()
                self.assertEqual(
                    (margins(layout), layout.spacing()), ((7, 8, 9, 10), 29)
                )
                self.assertEqual(layout.itemAt(0).layout().spacing(), 23)
                self.assertEqual(layout.itemAt(1).layout().spacing(), 23)
                options = dialog.encrypt_checkbox.parentWidget().layout()
                self.assertEqual(
                    (margins(options), options.spacing()), ((1, 2, 3, 4), 23)
                )

    def test_window_buttons_are_removed_through_the_shared_window_helper(self):
        module = "ost_visualizer.presentation.dialogs.sql_database_dialog"
        with patch(f"{module}.remove_minimize_maximize") as remove:
            dialog = SqlDatabasePropertiesDialog(
                RecordingIconProvider(),
                SqlDatabasePropertiesMode.CREATE,
                None,
                _SpyCreator(),
            )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        remove.assert_called_once_with(dialog)
