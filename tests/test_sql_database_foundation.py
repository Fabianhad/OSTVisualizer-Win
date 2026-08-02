import json
import ctypes
import os
import re
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from ost_visualizer.application.dtos.application_info import APPLICATION_VERSION
from ost_visualizer.application.dtos.collaboration_dtos import SynchronizationState
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    SqlDatabaseCatalogEntry,
)
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
)
from ost_visualizer.application.use_cases.project.cleanup_deleted_files_use_case import (
    CleanupDeletedFilesUseCase,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.presentation.utils.qt_callback_bridge import QtCallbackBridge
from ost_visualizer.infrastructure.database.schema_model import (
    render_sql_server_schema,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.credential_store import (
    WindowsCredentialStore,
    _CREDENTIALW,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    classify_pyodbc_error,
)
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlColumnInventory,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidator,
    _matches_type,
    _normalize_filter,
)
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from ost_visualizer.application.services.database_capability_service import (
    DatabaseCapabilityService,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.dialogs.select_database_type_dialog import (
    SelectDatabaseTypeDialog,
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
from ost_visualizer.presentation.dialogs.new_database_type_dialog import (
    NewDatabaseTypeDialog,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    NEW_DATABASE_TYPE_DIALOG_HEIGHT,
    NEW_DATABASE_TYPE_DIALOG_WIDTH,
    SELECT_DATABASE_TYPE_DIALOG_HEIGHT,
    SELECT_DATABASE_TYPE_DIALOG_WIDTH,
    SQL_CONNECTION_DIALOG_HEIGHT,
    SQL_CONNECTION_DIALOG_WIDTH,
    SQL_DATABASE_PROPERTIES_DIALOG_HEIGHT,
    SQL_DATABASE_PROPERTIES_DIALOG_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _IconProvider:
    def set_window_icon(self, _widget):
        pass


class _CredentialStore:
    def __init__(self):
        self.passwords = {}
        self.deleted = []

    def write_password(self, target, username, password):
        self.passwords[target] = (username, password)

    def read_password(self, target):
        value = self.passwords.get(target)
        return value[1] if value else None

    def delete_password(self, target):
        self.deleted.append(target)
        self.passwords.pop(target, None)


class _Catalog:
    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def list_databases(self, location, password=""):
        self.calls.append((location, password))
        return list(self.entries)

    def get_database(self, location, database_name, password=""):
        self.calls.append((location, database_name, password))
        for entry in self.entries:
            if entry.name == database_name:
                return entry
        raise DatabaseCatalogError(
            "The selected database is no longer available to this login."
        )


class _SqlDatabaseCreator:
    def can_create_database(self, _location, _password=""):
        return False

    def create_database(self, *_args, **_kwargs):
        raise AssertionError("creation was not requested")


class _FakeApiFunction:
    def __init__(self, callback):
        self._callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self._callback(*args)


class _FakeCredentialApi:
    def __init__(self):
        self._records = {}
        self._read_buffers = []
        self.CredWriteW = _FakeApiFunction(self._write)
        self.CredReadW = _FakeApiFunction(self._read)
        self.CredDeleteW = _FakeApiFunction(self._delete)
        self.CredFree = _FakeApiFunction(lambda _pointer: None)

    def _write(self, credential_pointer, _flags):
        credential = credential_pointer._obj
        blob = ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize
        )
        self._records[credential.TargetName] = (credential.UserName, blob)
        return True

    def _read(self, target, _credential_type, _flags, result_pointer):
        username, blob_bytes = self._records[target]
        blob = (ctypes.c_ubyte * len(blob_bytes)).from_buffer_copy(blob_bytes)
        credential = _CREDENTIALW()
        credential.UserName = username
        credential.CredentialBlobSize = len(blob_bytes)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        pointer = ctypes.pointer(credential)
        ctypes.cast(
            result_pointer,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        )[0] = pointer
        self._read_buffers.append((blob, credential, pointer))
        return True

    def _delete(self, target, _credential_type, _flags):
        self._records.pop(target, None)
        return True


class DatabaseDescriptorTests(unittest.TestCase):
    def test_msi_script_extracts_version_from_application_info(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "build-msi.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("ost_visualizer\\application\\dtos\\application_info.py", script)
        pattern_match = re.search(
            r"\$VersionPattern = '([^']+)'",
            script,
        )
        self.assertIsNotNone(pattern_match)
        application_info = (
            root / "ost_visualizer/application/dtos/application_info.py"
        ).read_text(encoding="utf-8")
        version_match = re.search(pattern_match.group(1), application_info)
        self.assertIsNotNone(version_match)
        self.assertEqual(version_match.group(1), APPLICATION_VERSION)
        self.assertNotIn("Get-Command python", script)

    def test_schema_inspection_tool_uses_canonical_certificate_default(self):
        root = Path(__file__).resolve().parents[1]
        tool = (root / "tools/inspect_sql_schema.py").read_text(encoding="utf-8")
        self.assertNotIn("--trust-server-certificate", tool)
        self.assertNotIn("trust_server_certificate=", tool)

    def test_missing_access_cleanup_retains_saved_sql_descriptors(self):
        sql_entry = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation(
                    server="server\\instance",
                    database="OSTV",
                ),
                schema_version=SQL_SCHEMA_V1.version,
            )
        )
        missing_access = FileEntry(file_path="missing-database.mdb")
        cleaned, removed = CleanupDeletedFilesUseCase(object()).execute(
            [missing_access, sql_entry]
        )
        self.assertEqual(cleaned, [sql_entry])
        self.assertEqual(removed, 1)

    def test_legacy_file_state_migrates_to_stable_access_descriptor(self):
        raw = {
            "file_entries": [{"file_path": r"C:\data\sample.mdb", "is_checked": True}]
        }
        first = FileState.from_dict(raw)
        second = FileState.from_dict(raw)
        self.assertEqual(first.file_entries[0].backend, DatabaseBackend.ACCESS)
        self.assertEqual(
            first.file_entries[0].database_id,
            second.file_entries[0].database_id,
        )
        serialized = first.to_dict()
        self.assertEqual(serialized["version"], 2)
        self.assertIn("database_entries", serialized)

    def test_sql_descriptor_serialization_and_repr_never_contain_password(self):
        password = secrets.token_urlsafe(24)
        location = SqlServerDatabaseLocation(
            server=r"server\instance",
            database="OSTV_TEST_123",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000123",
        )
        descriptor = DatabaseDescriptor.for_sql_server(
            location, schema_version=SQL_SCHEMA_V1.version
        )
        payload = json.dumps(FileEntry.for_descriptor(descriptor).to_dict())
        self.assertNotIn(password, payload)
        self.assertNotIn("password", payload.casefold())
        self.assertNotIn(password, repr(descriptor))
        self.assertEqual(DatabaseDescriptor.from_dict(descriptor.to_dict()), descriptor)

    def test_sql_descriptor_requires_an_explicit_schema_version(self):
        location = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        with self.assertRaises(TypeError):
            DatabaseDescriptor.for_sql_server(location)

    def test_temporary_sql_descriptor_fields_are_rejected(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        payload = descriptor.to_dict()
        payload["location"]["credential_target"] = "obsolete"
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            DatabaseDescriptor.from_dict(payload)

    def test_saved_descriptors_reject_noncanonical_scalar_types(self):
        sql_payload = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        ).to_dict()
        sql_payload["location"]["server"] = None
        with self.assertRaisesRegex(ValueError, "server"):
            DatabaseDescriptor.from_dict(sql_payload)
        access_payload = DatabaseDescriptor.for_access(r"C:\data\sample.mdb").to_dict()
        access_payload["location"]["file_path"] = 7
        with self.assertRaisesRegex(ValueError, "file_path"):
            DatabaseDescriptor.from_dict(access_payload)
        timeout_payload = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        ).to_dict()
        timeout_payload["location"]["connection_timeout_seconds"] = True
        with self.assertRaisesRegex(ValueError, "connection_timeout_seconds"):
            DatabaseDescriptor.from_dict(timeout_payload)

    def test_canonical_file_entry_rejects_non_boolean_checked_state(self):
        descriptor = DatabaseDescriptor.for_access(r"C:\data\sample.mdb")
        with self.assertRaisesRegex(ValueError, "checked state"):
            FileEntry.from_dict(
                {"descriptor": descriptor.to_dict(), "is_checked": "false"}
            )

    def test_version_two_file_state_rejects_bare_database_paths(self):
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            FileState.from_dict(
                {
                    "version": 2,
                    "database_entries": [r"C:\data\sample.mdb"],
                }
            )

    def test_windows_credential_store_round_trip_uses_os_adapter(self):
        api = _FakeCredentialApi()
        store = WindowsCredentialStore(api)
        target = "OSTVisualizer/SqlServer/test-id"
        password = secrets.token_urlsafe(24)
        with patch(
            "ost_visualizer.infrastructure.sql.credential_store.ctypes.memset",
            wraps=ctypes.memset,
        ) as wipe:
            store.write_password(target, "test-user", password)
        wipe.assert_called_once()
        self.assertEqual(wipe.call_args.args[2], len(password.encode("utf-16-le")))
        self.assertEqual(store.read_password(target), password)
        store.delete_password(target)
        self.assertNotIn(target, api._records)

    def test_registry_resolves_stable_database_id(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_access(r"C:\data\one.mdb")
        registry.register(descriptor)
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        registry.unregister(descriptor.database_id)
        self.assertIsNone(registry.resolve(descriptor.database_id))

    def test_connection_request_repr_redacts_secret(self):
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(
                server="localhost",
                database="OSTV_TEST_123",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="test-user",
            ),
            password=secrets.token_urlsafe(24),
        )
        self.assertIn("password=<redacted>", repr(request))
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        connection_string = manager.build_connection_string(request)
        self.assertIn("DRIVER={ODBC Driver 18 for SQL Server}", connection_string)
        self.assertIn("Encrypt=yes", connection_string)
        self.assertNotIn(request.password, repr(manager))

    def test_driver_17_is_not_an_accepted_schema_client(self):
        manager = SqlConnectionManager(drivers=["ODBC Driver 17 for SQL Server"])
        with self.assertRaisesRegex(Exception, "Driver 18"):
            _ = manager.driver

    def test_shared_schema_model_covers_complete_reference_schema(self):
        model = get_reference_schema_model()
        self.assertEqual(len(model.tables), 64)
        self.assertEqual(model.column_count, 668)
        statements = render_sql_server_schema(model)
        self.assertEqual(sum(sql.startswith("CREATE TABLE") for sql in statements), 64)
        self.assertTrue(any("varbinary(max)" in sql for sql in statements))
        self.assertTrue(any("datetime2(3)" in sql for sql in statements))

    def test_current_write_schema_rejects_noncanonical_fields(self):
        schema = CurrentSqlWriteSchema(get_reference_schema_model())
        self.assertTrue(schema.column_exists("Bids", "UID"))
        with self.assertRaisesRegex(Exception, "dbo.Bids.NotAColumn"):
            schema.column_exists("Bids", "NotAColumn")

    def test_schema_validator_accepts_only_complete_canonical_v1(self):
        def inventory(version, checksum=""):
            return SqlSchemaInventory(
                database_guid="",
                schema_version=version,
                schema_checksum=checksum,
                tables=frozenset(),
                columns=(),
                foreign_keys=(),
                indexes=(),
                views=(),
                triggers=(),
                procedures=(),
                functions=(),
            )

        validator = SqlSchemaValidator(get_reference_schema_model())
        partial = validator.validate(
            inventory(SQL_SCHEMA_V1.version, SQL_SCHEMA_V1.checksum)
        )
        self.assertFalse(partial.is_valid)
        unsupported = validator.validate(inventory(99))
        self.assertFalse(unsupported.is_valid)
        self.assertEqual(
            unsupported.problems,
            ("ostv.DatabaseMetadata.SchemaVersion",),
        )

    def test_sql_schema_v1_is_the_single_complete_schema_definition(self):
        self.assertEqual(SQL_SCHEMA_V1.version, 1)
        self.assertEqual(
            SQL_SCHEMA_V1.checksum,
            "27460ffeedd5dfa47dc532968c1db7445bee3423c718aa4ef2aca2b063297dd7",
        )
        self.assertIn(
            "ALLOW_SNAPSHOT_ISOLATION=ON",
            SQL_SCHEMA_V1.canonical_database_requirements,
        )
        self.assertEqual(
            sum(
                statement.startswith("CREATE TABLE [dbo]")
                for statement in SQL_SCHEMA_V1.statements
            ),
            64,
        )
        self.assertEqual(
            {table.name for table in SQL_SCHEMA_V1.tables},
            {
                "DatabaseMetadata",
                "SchemaMigrations",
                "Sessions",
                "Presence",
                "Locks",
                "EntityVersions",
                "ChangeLog",
                "ChangeFeedState",
                "ExternalAdapterState",
                "ChangeTransactions",
            },
        )
        metadata = next(
            table for table in SQL_SCHEMA_V1.tables if table.name == "DatabaseMetadata"
        )
        self.assertIn("WriterMode", {column.name for column in metadata.columns})
        self.assertFalse(
            any("\nGO\n" in statement.upper() for statement in SQL_SCHEMA_V1.statements)
        )

    def test_canonical_schema_record_rejects_noncanonical_values(self):
        self.assertTrue(
            schema_record_is_canonical(SQL_SCHEMA_V1.version, SQL_SCHEMA_V1.checksum)
        )
        self.assertFalse(schema_record_is_canonical("1", SQL_SCHEMA_V1.checksum))
        self.assertFalse(schema_record_is_canonical(1.0, SQL_SCHEMA_V1.checksum))
        self.assertFalse(schema_record_is_canonical(1, "0" * 64))

    def test_schema_validator_rejects_noncanonical_ostv_tables_and_columns(self):
        inventory = SqlSchemaInventory(
            database_guid="",
            schema_version=SQL_SCHEMA_V1.version,
            schema_checksum=SQL_SCHEMA_V1.checksum,
            tables=frozenset(
                {
                    ("ostv", "Sessions"),
                    ("ostv", "LegacyState"),
                }
            ),
            columns=(
                SqlColumnInventory(
                    "ostv",
                    "Sessions",
                    "LegacyCheckpoint",
                    "bigint",
                    8,
                    0,
                    False,
                    False,
                    False,
                ),
            ),
            foreign_keys=(),
            indexes=(),
            views=(),
            triggers=(),
            procedures=(),
            functions=(),
        )
        problems = SqlSchemaValidator._validate_ostv_tables(inventory, SQL_SCHEMA_V1)
        self.assertIn("ostv.LegacyState.unexpected", problems)
        self.assertIn("ostv.Sessions.LegacyCheckpoint.unexpected", problems)

    def test_sql_server_schema_normalization_matches_server_inventory(self):
        rowversion = SqlColumnInventory(
            "ostv",
            "Sessions",
            "Version",
            "timestamp",
            8,
            0,
            False,
            False,
            False,
            "",
        )
        self.assertTrue(_matches_type(rowversion, "rowversion"))
        self.assertEqual(
            _normalize_filter("([DisconnectedAt] IS NULL)"),
            _normalize_filter("[DisconnectedAt] IS NULL"),
        )
        expected_checks = {
            name: expression
            for table in SQL_SCHEMA_V1.tables
            for name, expression in table.check_constraints
        }
        server_checks = {
            "CK_ostv_Presence_ActivityMode": (
                "([ActivityMode]=N'editing' OR [ActivityMode]=N'viewing')"
            ),
            "CK_ostv_ChangeLog_Operation": (
                "([Operation]=N'bulk_refresh' OR [Operation]=N'reorder' OR "
                "[Operation]=N'move' OR [Operation]=N'delete' OR "
                "[Operation]=N'update' OR [Operation]=N'create')"
            ),
            "CK_ostv_ChangeLog_ChangedFieldsJson": (
                "([ChangedFields] IS NULL OR isjson([ChangedFields])=(1))"
            ),
            "CK_ostv_ChangeLog_PayloadJson": (
                "([Payload] IS NULL OR isjson([Payload])=(1))"
            ),
            "CK_ostv_ChangeFeedState_Singleton": "([SingletonId]=(1))",
        }
        for name, actual in server_checks.items():
            self.assertEqual(
                _normalize_filter(actual),
                _normalize_filter(expected_checks[name]),
                name,
            )

    def test_capability_service_keeps_unversioned_sql_read_only(self):
        class _ReadOnlyPermissionProbe:
            def can_edit(self, _database_id):
                return False

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="Unversioned"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        service = DatabaseCapabilityService(registry, _ReadOnlyPermissionProbe())
        service.mark_connected(descriptor.database_id)
        self.assertFalse(service.is_editable(descriptor.database_id))

    def test_capability_service_refreshes_immediately_after_reconnect_and_disconnect(
        self,
    ):
        class _PermissionProbe:
            editable = False

            def can_edit(self, _database_id):
                return self.editable

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="Canonical"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        probe = _PermissionProbe()
        service = DatabaseCapabilityService(registry, probe)
        service.mark_connected(descriptor.database_id)
        self.assertFalse(service.is_editable(descriptor.database_id))
        probe.editable = True
        service.mark_connected(descriptor.database_id)
        service.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(service.is_editable(descriptor.database_id))
        service.mark_disconnected(descriptor.database_id)
        self.assertFalse(service.is_editable(descriptor.database_id))

    def test_capability_service_denies_unknown_locator_and_allows_registered_access(
        self,
    ):
        class _PermissionProbe:
            def can_edit(self, _database_id):
                raise AssertionError("Access does not require a SQL permission probe")

        registry = DatabaseDescriptorRegistry()
        service = DatabaseCapabilityService(registry, _PermissionProbe())
        self.assertFalse(service.is_editable("unknown-database-id"))
        descriptor = DatabaseDescriptor.for_access(r"C:\data\sample.mdb")
        registry.register(descriptor)
        self.assertTrue(service.is_editable(descriptor.access_path))

    def test_writer_uses_one_inherited_operation_surface(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(), registry, _CredentialStore(), DatabaseSessionRegistry()
        )
        self.assertFalse(writer._is_sql("sample.mdb"))
        self.assertTrue(writer._is_sql(descriptor.database_id))
        self.assertNotIn("delete_bids", DatabaseProjectWriter.__dict__)
        self.assertNotIn("save_takeoff_positions", DatabaseProjectWriter.__dict__)

    def test_sql_import_conversion_rejects_noncanonical_values(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        self.assertEqual(writer._convert_sql_import_value("12", "int"), 12)
        self.assertIs(writer._convert_sql_import_value("True", "bit"), True)
        with self.assertRaisesRegex(ValueError, "Boolean"):
            writer._convert_sql_import_value("maybe", "bit")
        with self.assertRaisesRegex(RuntimeError, "Unsupported SQL import type"):
            writer._convert_sql_import_value("value", "xml")


class SqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.icon_provider = _IconProvider()

    def test_thread_callback_dispatch_returns_to_qt_main_thread(self):
        bridge = QtCallbackBridge()
        callback_thread = []
        delivered = threading.Event()

        def receive(_payload):
            callback_thread.append(QtCore.QThread.currentThread())
            delivered.set()

        worker = threading.Thread(target=lambda: bridge.dispatch(receive, ()))
        worker.start()
        worker.join()
        for _ in range(20):
            self.app.processEvents()
            if delivered.is_set():
                break
            QTest.qWait(1)
        self.assertTrue(delivered.is_set())
        self.assertIs(callback_thread[0], self.app.thread())
        bridge.deleteLater()

    def test_database_type_defaults_to_access(self):
        self.assertEqual(
            (SELECT_DATABASE_TYPE_DIALOG_WIDTH, SELECT_DATABASE_TYPE_DIALOG_HEIGHT),
            (270, 110),
        )
        dialog = SelectDatabaseTypeDialog(self.icon_provider)
        try:
            margins = dialog.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                COMPACT_MARGINS,
            )
            self.assertEqual(dialog.layout().spacing(), COMPACT_SPACING)
            self.assertEqual(dialog.size().width(), SELECT_DATABASE_TYPE_DIALOG_WIDTH)
            self.assertEqual(dialog.size().height(), SELECT_DATABASE_TYPE_DIALOG_HEIGHT)
            self.assertTrue(dialog.access_radio.isChecked())
            self.assertEqual(dialog.selected_backend(), DatabaseBackend.ACCESS)
            dialog.sql_server_radio.setChecked(True)
            self.assertEqual(dialog.selected_backend(), DatabaseBackend.SQL_SERVER)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

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
            self.assertNotIn("trust_certificate_checkbox", dialog.__dict__)
            dialog.server_input.setText("localhost")
            dialog.username_input.setText("test-user")
            dialog.password_input.setText("temporary-secret")
            dialog._accept_if_valid()
            self.assertFalse(dialog.result_data().location.trust_server_certificate)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_sql_dialog_titles_dimensions_and_modes(self):
        self.assertEqual(
            (SQL_CONNECTION_DIALOG_WIDTH, SQL_CONNECTION_DIALOG_HEIGHT),
            (320, 240),
        )
        self.assertEqual(
            (
                SQL_DATABASE_PROPERTIES_DIALOG_WIDTH,
                SQL_DATABASE_PROPERTIES_DIALOG_HEIGHT,
            ),
            (320, 360),
        )
        self.assertEqual(
            (NEW_DATABASE_TYPE_DIALOG_WIDTH, NEW_DATABASE_TYPE_DIALOG_HEIGHT),
            (350, 230),
        )
        connection = SqlConnectionDialog(self.icon_provider)
        margins = connection.layout().contentsMargins()
        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            RELAXED_MARGINS,
        )
        self.assertEqual(connection.layout().spacing(), RELAXED_SPACING)
        self.assertEqual(connection.windowTitle(), "Connect to SQL Server")
        self.assertEqual(connection.size().width(), SQL_CONNECTION_DIALOG_WIDTH)
        self.assertEqual(connection.size().height(), SQL_CONNECTION_DIALOG_HEIGHT)
        connection.cleanup()
        connection.deleteLater()
        initial = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database="")
        )
        selected = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_VALID",
            database_guid="00000000-0000-0000-0000-000000000123",
            state="ONLINE",
            is_compatible=True,
            schema_version=SQL_SCHEMA_V1.version,
        )
        dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.OPEN,
            _Catalog([selected]),
            _SqlDatabaseCreator(),
            connection=initial,
            databases=[selected],
        )
        try:
            self.assertEqual(dialog.windowTitle(), "Database Properties (SQL Server)")
            self.assertEqual(
                dialog.size().width(), SQL_DATABASE_PROPERTIES_DIALOG_WIDTH
            )
            self.assertEqual(
                dialog.size().height(), SQL_DATABASE_PROPERTIES_DIALOG_HEIGHT
            )
            self.assertTrue(dialog.server_input.isReadOnly())
            self.assertFalse(dialog.database_combo.isHidden())
            self.assertTrue(dialog.database_name_input.isHidden())
            self.assertEqual(dialog.database_combo.count(), 1)
            self.assertNotIn("trust_certificate_checkbox", dialog.__dict__)
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        create_dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            _Catalog([]),
            _SqlDatabaseCreator(),
        )
        try:
            self.assertFalse(create_dialog.server_input.isReadOnly())
            self.assertTrue(create_dialog.database_combo.isHidden())
            self.assertFalse(create_dialog.database_name_input.isHidden())
            self.assertNotIn("trust_certificate_checkbox", create_dialog.__dict__)
        finally:
            create_dialog.cleanup()
            create_dialog.deleteLater()
        type_dialog = NewDatabaseTypeDialog(self.icon_provider)
        try:
            margins = type_dialog.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                RELAXED_MARGINS,
            )
            self.assertEqual(type_dialog.layout().spacing(), COMPACT_SPACING)
            option_margins = type_dialog.access_button.layout().contentsMargins()
            self.assertEqual(
                (
                    option_margins.left(),
                    option_margins.top(),
                    option_margins.right(),
                    option_margins.bottom(),
                ),
                COMPACT_MARGINS,
            )
            self.assertEqual(
                type_dialog.access_button.layout().spacing(), COMPACT_SPACING
            )
            self.assertEqual(type_dialog.windowTitle(), "New Database Type")
            self.assertEqual(type_dialog.size().width(), NEW_DATABASE_TYPE_DIALOG_WIDTH)
            self.assertEqual(
                type_dialog.size().height(), NEW_DATABASE_TYPE_DIALOG_HEIGHT
            )
        finally:
            type_dialog.cleanup()
            type_dialog.deleteLater()

    def test_certificate_error_explains_default_trust_behavior(self):
        error = RuntimeError(
            "08001",
            "SSL Provider: The certificate chain was issued by an authority "
            "that is not trusted.",
        )
        details = classify_pyodbc_error(error)
        self.assertEqual(details.code, SqlErrorCode.CERTIFICATE_FAILED)
        self.assertIn("normally trusts", details.user_message)

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

    def test_properties_open_validates_selection_and_cancel_clears_secret(self):
        password = secrets.token_urlsafe(24)
        selected = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_VALID",
            database_guid="00000000-0000-0000-0000-000000000123",
            state="ONLINE",
            is_compatible=True,
            schema_version=SQL_SCHEMA_V1.version,
        )
        catalog = _Catalog([selected])
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
            _SqlDatabaseCreator(),
            connection=connection,
            databases=[selected],
            schema_change_allowed_fn=lambda: True,
        )
        try:
            dialog._accept_if_valid()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            result = dialog.result_data()
            self.assertIsNotNone(result)
            self.assertEqual(result.location.database, selected.name)
            self.assertEqual(len(catalog.calls), 1)
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        cancelled = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.OPEN,
            catalog,
            _SqlDatabaseCreator(),
            connection=connection,
            databases=[selected],
        )
        try:
            cancelled.reject()
            self.assertIsNone(cancelled.result_data())
            self.assertEqual(cancelled.password_input.text(), "")
        finally:
            cancelled.cleanup()
            cancelled.deleteLater()

    def test_new_database_type_panels_select_expected_backend(self):
        access = NewDatabaseTypeDialog(self.icon_provider)
        try:
            access.access_button.click()
            self.assertEqual(access.selected_backend(), DatabaseBackend.ACCESS)
        finally:
            access.cleanup()
            access.deleteLater()
        sql = NewDatabaseTypeDialog(self.icon_provider)
        try:
            sql.sql_server_button.click()
            self.assertEqual(sql.selected_backend(), DatabaseBackend.SQL_SERVER)
        finally:
            sql.cleanup()
            sql.deleteLater()

    def test_new_database_type_routes_sql_and_preserves_access_name_flow(self):
        class _TypeDialog:
            backend = DatabaseBackend.SQL_SERVER

            def __init__(self, *_args):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                return self.backend

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        sql_calls = []
        controller = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            icon_provider=self.icon_provider,
            window=None,
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(
                    create_sql_database=lambda: sql_calls.append("sql")
                )
            ),
        )
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
        ):
            MenuController._new_database(controller)
        self.assertEqual(sql_calls, ["sql"])

        class _AccessNameDialog:
            instances = []
            result = QtWidgets.QDialog.DialogCode.Accepted

            def __init__(self, _parent):
                self.title = ""
                self.label = ""
                self.deleted = False
                self.instances.append(self)

            def setWindowTitle(self, title):
                self.title = title

            def setLabelText(self, label):
                self.label = label

            def setTextValue(self, _value):
                pass

            def setModal(self, _modal):
                pass

            def exec(self):
                return self.result

            def textValue(self):
                return "Access Database"

            def deleteLater(self):
                self.deleted = True

        _TypeDialog.backend = DatabaseBackend.ACCESS
        created_names = []
        loaded_paths = []
        controller._create_new_database_fn = lambda name: (
            created_names.append(name) or "access.mdb"
        )
        controller._file_loading_service = SimpleNamespace(
            load_file=lambda path: (
                loaded_paths.append(path)
                or SimpleNamespace(success=True, file_path=path)
            )
        )
        controller._event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
        ), patch.object(QtWidgets, "QInputDialog", _AccessNameDialog), patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "remove_minimize_maximize"
        ):
            MenuController._new_database(controller)
        self.assertEqual(created_names, ["Access Database"])
        self.assertEqual(loaded_paths, ["access.mdb"])
        self.assertTrue(_AccessNameDialog.instances[0].deleted)
        _AccessNameDialog.result = QtWidgets.QDialog.DialogCode.Rejected
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
        ), patch.object(QtWidgets, "QInputDialog", _AccessNameDialog), patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "remove_minimize_maximize"
        ):
            MenuController._new_database(controller)
        self.assertEqual(created_names, ["Access Database"])
        self.assertTrue(_AccessNameDialog.instances[1].deleted)
        original_icon_provider = controller.icon_provider
        controller.icon_provider = SimpleNamespace(
            set_window_icon=lambda _dialog: (_ for _ in ()).throw(
                RuntimeError("icon setup failed")
            )
        )
        _AccessNameDialog.result = QtWidgets.QDialog.DialogCode.Accepted
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
        ), patch.object(QtWidgets, "QInputDialog", _AccessNameDialog):
            with self.assertRaisesRegex(RuntimeError, "icon setup failed"):
                MenuController._new_database(controller)
        self.assertTrue(_AccessNameDialog.instances[2].deleted)
        controller.icon_provider = original_icon_provider

    def test_create_mode_initializes_before_accepting(self):
        class _Creator:
            should_fail = False

            def can_create_database(self, _location, _password=""):
                return True

            def create_database(self, location, database_name, _password="", **_kwargs):
                if self.should_fail:
                    raise DatabaseCatalogError("Database initialization failed.")
                return SqlDatabaseCreationResult(
                    SqlServerDatabaseLocation(
                        server=location.server,
                        database=database_name,
                        database_guid=("00000000-0000-0000-0000-000000000789"),
                    ),
                    1,
                )

        creator = _Creator()
        dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            _Catalog([]),
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        try:
            dialog.server_input.setText("localhost")
            dialog.database_name_input.setText("OSTV_TEST_CREATED")
            dialog._accept_if_valid()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(
                dialog.result_data().location.database, "OSTV_TEST_CREATED"
            )
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        creator.should_fail = True
        failed = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            _Catalog([]),
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        try:
            failed.server_input.setText("localhost")
            failed.database_name_input.setText("OSTV_TEST_FAILED")
            with patch(
                "ost_visualizer.presentation.dialogs.sql_database_dialog."
                "show_warning"
            ):
                failed._accept_if_valid()
            self.assertIsNone(failed.result_data())
            self.assertNotEqual(failed.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            failed.cleanup()
            failed.deleteLater()

    def test_access_choice_delegates_to_existing_file_picker(self):
        class _AcceptedAccessDialog:
            def __init__(self, *_args):
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
            dialog = OpenFilesDialog(self.icon_provider, None, [], None)
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
            def __init__(self, *_args):
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
            def __init__(self, *_args, **_kwargs):
                pass

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

        store = _CredentialStore()
        catalog = _Catalog([selected])
        dialog = OpenFilesDialog(
            self.icon_provider,
            None,
            [],
            None,
            sql_catalog=catalog,
            credential_store=store,
            sql_database_creator=_SqlDatabaseCreator(),
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
            def __init__(self, *_args):
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
            def __init__(self, *_args, **_kwargs):
                pass

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

        store = _CredentialStore()
        dialog = OpenFilesDialog(
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
            sql_catalog=_Catalog([selected]),
            credential_store=store,
            sql_database_creator=_SqlDatabaseCreator(),
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
        store = _CredentialStore()
        dialog = OpenFilesDialog(
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
        store = _CredentialStore()
        store.write_password(target, location.username, old_password)
        dialog = OpenFilesDialog(
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
        store = _CredentialStore()
        dialog = OpenFilesDialog(
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

    def test_sql_creation_persists_only_after_properties_acceptance(self):
        password = secrets.token_urlsafe(24)
        location = SqlServerDatabaseLocation(
            server="localhost",
            database="OSTV_TEST_CREATED",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000456",
        )
        properties_result = SqlDatabasePropertiesResult(
            location, SQL_SCHEMA_V1.version, password
        )

        class _State:
            def __init__(self):
                self.file_entries = []

            def update_entries(self, entries):
                self.file_entries = list(entries)

            def reload(self):
                pass

        class _PropertiesDialog:
            accepted = True

            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                if self.accepted:
                    return QtWidgets.QDialog.DialogCode.Accepted
                return QtWidgets.QDialog.DialogCode.Rejected

            def result_data(self):
                return properties_result if self.accepted else None

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        state = _State()
        store = _CredentialStore()
        handler = FileOperationHandler(
            window=None,
            icon_provider=self.icon_provider,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=None,
            file_loading_service=SimpleNamespace(
                is_loaded=lambda _locator: False,
                load_file=lambda _locator: SimpleNamespace(
                    success=True, file_path=location.database_guid
                ),
            ),
            working_directory_service=None,
            unload_file_fn=lambda _locator: False,
            deferred_persistence_manager=None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda _database_id, _reason, callback: callback(
                    True, ""
                ),
                start_database=lambda _database_id: True,
            ),
            database_catalog=_Catalog([]),
            credential_store=store,
            database_descriptor_registry=DatabaseDescriptorRegistry(),
            sql_database_creator=_SqlDatabaseCreator(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler."
            "SqlDatabasePropertiesDialog",
            _PropertiesDialog,
        ), patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ):
            self.assertTrue(handler.create_sql_database())
            self.assertEqual(len(state.file_entries), 1)
            target = credential_target_for(state.file_entries[0].database_id)
            self.assertEqual(store.passwords[target], ("test-user", password))
            self.assertFalse(handler.create_sql_database())
            self.assertEqual(len(state.file_entries), 1)
            _PropertiesDialog.accepted = False
            empty_state = _State()
            handler._file_state_model = empty_state
            self.assertFalse(handler.create_sql_database())
            self.assertEqual(empty_state.file_entries, [])


if __name__ == "__main__":
    unittest.main()
