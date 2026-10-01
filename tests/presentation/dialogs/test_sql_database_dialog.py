import os
import unittest
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


class SqlDatabaseDialogSqlCleanupTests(unittest.TestCase):
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


class SqlDatabaseDialogSqlDialogTests(unittest.TestCase):
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


class SqlDatabaseDialogCreationDialogIdentityTests(unittest.TestCase):
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


class SqlDatabaseDialogCreationReleaseBoundaryTests(unittest.TestCase):
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
