import json
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    SqlDatabaseCatalogEntry,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
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
from tests.helpers.workspace_state import with_workspace_state
from tests.helpers.sql.database_foundation_support import (
    OpenFilesDialog as _database_foundation_support_OpenFilesDialog,
    _Catalog as _database_foundation_support__Catalog,
    _CredentialStore as _database_foundation_support__CredentialStore,
    _IconProvider as _database_foundation_support__IconProvider,
    _SqlDatabaseCreator as _database_foundation_support__SqlDatabaseCreator,
    _app as _database_foundation_support__app,
)
from unittest import mock
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.infrastructure.persistence.repositories.json_workspace_state_repository import (
    JsonWorkspaceStateRepository,
)
from tests.presentation.utils.header_support import (
    _IconProvider as _header_support__IconProvider,
    _app as _header_support__app,
)
from types import SimpleNamespace
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.presentation.dialogs.open_files_dialog import (
    OpenFilesDialog as StartupOpenFilesDialog,
)
from shiboken6 import delete
from tests.helpers.startup_database import (
    StartupOpenFilesDialog as _startup_database_StartupOpenFilesDialog,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class OpenFilesDialogSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_access_choice_delegates_to_existing_file_picker(self):
        class _AcceptedAccessDialog:
            def __init__(self, _icon_provider, _parent=None):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                return DatabaseBackend.ACCESS

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "sample.mdb")
            Path(path).touch()
            dialog = _database_foundation_support_OpenFilesDialog(
                self.icon_provider, None, [], None
            )
            try:
                with patch(
                    "ost_visualizer.presentation.dialogs.open_files_dialog."
                    "SelectDatabaseTypeDialog",
                    _AcceptedAccessDialog,
                ), patch.object(
                    QtWidgets.QFileDialog,
                    "getOpenFileName",
                    return_value=(path, "Microsoft Access Database (*.mdb)"),
                ):
                    dialog._on_find()
                self.assertEqual(len(dialog.file_entries), 1)
                self.assertEqual(dialog.file_entries[0].file_path, path)
                self.assertEqual(dialog.file_entries[0].backend, DatabaseBackend.ACCESS)
            finally:
                dialog.cleanup()
                dialog.deleteLater()

    def test_sql_selection_saves_descriptor_and_credential_separately(self):
        password = secrets.token_urlsafe(24)
        initial_location = SqlServerDatabaseLocation(
            server="localhost",
            database="",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
        )
        result = SqlConnectionDialogResult(initial_location, password)
        selected = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_123",
            database_guid="00000000-0000-0000-0000-000000000123",
            state="ONLINE",
            is_compatible=True,
        )

        class _ConnectionDialog:
            def __init__(self, _icon_provider, _parent=None):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return result

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        class _DatabaseDialog:
            def __init__(
                self,
                _icon_provider,
                _mode,
                _sql_catalog,
                _sql_database_creator,
                _parent=None,
                *,
                connection=None,
                databases=(),
                schema_change_allowed_fn=None,
            ):
                _ = connection, databases, schema_change_allowed_fn

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SqlDatabasePropertiesResult(
                    location=SqlServerDatabaseLocation(
                        server="localhost",
                        database=selected.name,
                        authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                        username="test-user",
                        database_guid=selected.database_guid,
                    ),
                    schema_version=selected.schema_version,
                    password=password,
                )

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        store = _database_foundation_support__CredentialStore()
        catalog = _database_foundation_support__Catalog([selected])
        dialog = _database_foundation_support_OpenFilesDialog(
            self.icon_provider,
            None,
            [],
            None,
            sql_catalog=catalog,
            credential_store=store,
            sql_database_creator=_database_foundation_support__SqlDatabaseCreator(),
        )
        try:
            with patch(
                "ost_visualizer.presentation.dialogs.open_files_dialog."
                "SqlConnectionDialog",
                _ConnectionDialog,
            ), patch(
                "ost_visualizer.presentation.dialogs.open_files_dialog."
                "SqlDatabasePropertiesDialog",
                _DatabaseDialog,
            ):
                dialog._open_sql_server_connection()
            self.assertEqual(len(dialog.file_entries), 1)
            entry = dialog.file_entries[0]
            self.assertEqual(entry.backend, DatabaseBackend.SQL_SERVER)
            self.assertEqual(entry.descriptor.sql_location.database, selected.name)
            serialized = json.dumps(entry.to_dict())
            self.assertNotIn(password, serialized)
            target = credential_target_for(entry.database_id)
            self.assertEqual(store.passwords[target], ("test-user", password))
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_reconnecting_duplicate_sql_descriptor_refreshes_credential(self):
        password = secrets.token_urlsafe(24)
        guid = "00000000-0000-0000-0000-000000000123"
        existing_location = SqlServerDatabaseLocation(
            server="localhost",
            database="OSTV_TEST_123",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid=guid,
        )
        result = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(
                server="localhost",
                database="",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="test-user",
            ),
            password,
        )
        selected = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_123",
            database_guid=guid,
            state="ONLINE",
            is_compatible=True,
        )

        class _ConnectionDialog:
            def __init__(self, _icon_provider, _parent=None):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return result

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        class _DatabaseDialog:
            def __init__(
                self,
                _icon_provider,
                _mode,
                _sql_catalog,
                _sql_database_creator,
                _parent=None,
                *,
                connection=None,
                databases=(),
                schema_change_allowed_fn=None,
            ):
                _ = connection, databases, schema_change_allowed_fn

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SqlDatabasePropertiesResult(
                    location=existing_location,
                    schema_version=selected.schema_version,
                    password=password,
                )

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        store = _database_foundation_support__CredentialStore()
        dialog = _database_foundation_support_OpenFilesDialog(
            self.icon_provider,
            None,
            [
                FileEntry.for_descriptor(
                    DatabaseDescriptor.for_sql_server(
                        existing_location, schema_version=SQL_SCHEMA_V1.version
                    ),
                    is_checked=False,
                )
            ],
            None,
            sql_catalog=_database_foundation_support__Catalog([selected]),
            credential_store=store,
            sql_database_creator=_database_foundation_support__SqlDatabaseCreator(),
        )
        try:
            with patch(
                "ost_visualizer.presentation.dialogs.open_files_dialog."
                "SqlConnectionDialog",
                _ConnectionDialog,
            ), patch(
                "ost_visualizer.presentation.dialogs.open_files_dialog."
                "SqlDatabasePropertiesDialog",
                _DatabaseDialog,
            ), patch(
                "ost_visualizer.presentation.dialogs.open_files_dialog.show_info"
            ):
                dialog._open_sql_server_connection()
            self.assertEqual(len(dialog.file_entries), 1)
            self.assertTrue(dialog.file_entries[0].is_checked)
            target = credential_target_for(dialog.file_entries[0].database_id)
            self.assertEqual(store.passwords[target], ("test-user", password))
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_cancelled_open_files_dialog_removes_new_sql_credential(self):
        password = secrets.token_urlsafe(24)
        location = SqlServerDatabaseLocation(
            server="localhost",
            database="OSTV_TEST_CANCELLED",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000222",
        )
        store = _database_foundation_support__CredentialStore()
        dialog = _database_foundation_support_OpenFilesDialog(
            self.icon_provider,
            None,
            [],
            None,
            credential_store=store,
        )
        target = credential_target_for(
            DatabaseDescriptor.for_sql_server(
                location, schema_version=SQL_SCHEMA_V1.version
            ).database_id
        )
        dialog._save_sql_result(
            SqlDatabasePropertiesResult(location, SQL_SCHEMA_V1.version, password)
        )
        self.assertIn(target, store.passwords)
        dialog.cleanup()
        dialog.deleteLater()
        self.assertNotIn(target, store.passwords)

    def test_cancelled_reconnect_restores_previous_sql_credential(self):
        old_password = secrets.token_urlsafe(24)
        new_password = secrets.token_urlsafe(24)
        location = SqlServerDatabaseLocation(
            server="localhost",
            database="OSTV_TEST_RECONNECT",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000223",
        )
        descriptor = DatabaseDescriptor.for_sql_server(
            location, schema_version=SQL_SCHEMA_V1.version
        )
        target = credential_target_for(descriptor.database_id)
        store = _database_foundation_support__CredentialStore()
        store.write_password(target, location.username, old_password)
        dialog = _database_foundation_support_OpenFilesDialog(
            self.icon_provider,
            None,
            [FileEntry.for_descriptor(descriptor)],
            None,
            credential_store=store,
        )
        with patch("ost_visualizer.presentation.dialogs.open_files_dialog.show_info"):
            dialog._save_sql_result(
                SqlDatabasePropertiesResult(
                    location, SQL_SCHEMA_V1.version, new_password
                )
            )
        self.assertEqual(store.passwords[target][1], new_password)
        dialog.cleanup()
        dialog.deleteLater()
        self.assertEqual(store.passwords[target][1], old_password)

    def test_committed_open_files_dialog_retains_new_sql_credential(self):
        password = secrets.token_urlsafe(24)
        location = SqlServerDatabaseLocation(
            server="localhost",
            database="OSTV_TEST_COMMITTED",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000224",
        )
        descriptor = DatabaseDescriptor.for_sql_server(
            location, schema_version=SQL_SCHEMA_V1.version
        )
        target = credential_target_for(descriptor.database_id)
        store = _database_foundation_support__CredentialStore()
        dialog = _database_foundation_support_OpenFilesDialog(
            self.icon_provider,
            None,
            [],
            None,
            credential_store=store,
        )
        dialog._save_sql_result(
            SqlDatabasePropertiesResult(location, SQL_SCHEMA_V1.version, password)
        )
        dialog.commit_credential_changes()
        dialog.cleanup()
        dialog.deleteLater()
        self.assertEqual(store.passwords[target], (location.username, password))


class OpenFilesSortedIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _header_support__app()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "workspace_state.json"
        self.model = WorkspaceStateAggregate(
            JsonWorkspaceStateRepository(self.state_path)
        )

    def tearDown(self):
        self.app.processEvents()
        self.temp_dir.cleanup()

    def test_open_databases_remove_uses_stable_identity_after_sorting(self):
        zulu_path = Path(self.temp_dir.name) / "Zulu.mdb"
        alpha_path = Path(self.temp_dir.name) / "Alpha.mdb"
        zulu_path.touch()
        alpha_path.touch()
        dialog = OpenFilesDialog(
            _header_support__IconProvider(),
            None,
            [FileEntry(str(zulu_path)), FileEntry(str(alpha_path))],
            None,
            workspace_state_model=self.model,
        )
        self.assertEqual(dialog.table.topLevelItem(0).text(2), "Alpha")
        dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
        self.assertTrue(dialog.remove_button.isEnabled())
        with mock.patch(
            "ost_visualizer.presentation.dialogs.open_files_dialog.confirm",
            return_value=True,
        ):
            dialog._on_remove()
        self.assertEqual(
            [entry.descriptor.display_name for entry in dialog.file_entries],
            ["Zulu"],
        )
        dialog.close()
        dialog.cleanup()
        dialog.deleteLater()


class OpenFilesStartupStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_saved_sql_checkbox_remains_enabled_and_interactive(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        dialog = _startup_database_StartupOpenFilesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            None,
            [FileEntry.for_descriptor(descriptor, is_checked=True)],
            None,
        )
        try:
            checkbox = dialog._checkboxes[0]
            self.assertTrue(checkbox.isEnabled())
            checkbox.click()
            self.assertFalse(dialog.get_file_entries()[0].is_checked)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_open_files_cleanup_tolerates_destroyed_parent(self):
        parent = QtWidgets.QDialog()
        dialog = _startup_database_StartupOpenFilesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            parent,
            [],
            None,
        )
        delete(parent)
        dialog.cleanup()
        dialog.cleanup()
        self.assertEqual(dialog.file_entries, [])
        self.assertIsNone(dialog.table)
