import contextlib
import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.infrastructure.database.connection_wrapper import ConnectionWrapper
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.database.reader_router import DatabaseProjectReader
from ost_visualizer.infrastructure.providers import RepositoryProvider
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.schema_compatibility import MdbSchemaInspector
from ost_visualizer.infrastructure.sql.connection_manager import SqlConnectionLease
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.permissions import SqlDatabasePermissionProbe
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlSchemaInspector,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_definition import LATEST_SQL_SCHEMA
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaCompatibility,
    SqlSchemaValidationReport,
)
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)


class _CredentialStore:
    def __init__(self):
        self.deleted = []

    def read_password(self, _target):
        return None

    def write_password(self, _target, _username, _password):
        return None

    def delete_password(self, target):
        self.deleted.append(target)


class _RawCursor:
    def __init__(self):
        self.close_count = 0
        self.timeout = 0

    def close(self):
        self.close_count += 1


class _RawConnection:
    def __init__(self):
        self.raw_cursor = _RawCursor()
        self.close_count = 0

    def cursor(self):
        return self.raw_cursor

    def close(self):
        self.close_count += 1


class _InspectionCursor:
    def __init__(self):
        self._last_sql = ""

    def execute(self, sql, *_params):
        self._last_sql = sql
        if "SELECT s.name, t.name, i.name" in sql:
            if "FROM sys.indexes i" not in sql:
                raise AssertionError("index inventory query has no FROM sys.indexes")
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def fetchone(self):
        if "database_guid" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


class _InspectionLease:
    def __init__(self):
        self.cursor_value = _InspectionCursor()

    def cursor(self):
        return self.cursor_value


class _InspectionManager:
    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield _InspectionLease()


class _CreationCursor:
    def __init__(self):
        self._last_sql = ""
        self.executed = []
        self.schema_record = None

    def execute(self, sql, *params):
        self._last_sql = sql
        self.executed.append(sql)
        if "INSERT INTO [ostv].[SchemaMigrations]" in sql:
            self.schema_record = (params[0], params[2])
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def fetchone(self):
        if "sp_getapplock" in self._last_sql:
            return (0,)
        if "COUNT(*) FROM sys.tables" in self._last_sql:
            return (0,)
        if "database_guid" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        if "SELECT [Version], [Checksum]" in self._last_sql:
            return self.schema_record
        return (0,)

    def close(self):
        return None


class _CreationLease:
    def __init__(self):
        self.cursor_value = _CreationCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _CreationManager:
    def __init__(self):
        self.lease = _CreationLease()

    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield self.lease


class _WriterCursor(_CreationCursor):
    def __init__(self):
        super().__init__()
        self.close_count = 0

    def fetchone(self):
        if "SchemaMigrations" in self._last_sql:
            return (LATEST_SQL_SCHEMA.version, LATEST_SQL_SCHEMA.checksum)
        if "sp_getapplock" in self._last_sql:
            return (0,)
        return None

    def close(self):
        self.close_count += 1


class _WriterLease:
    def __init__(self):
        self.cursors = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        cursor = _WriterCursor()
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _WriterManager:
    def __init__(self):
        self.lease = _WriterLease()

    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield self.lease


def _empty_inventory():
    return SqlSchemaInventory(
        database_guid="00000000-0000-0000-0000-000000000001",
        schema_version=0,
        schema_checksum="",
        tables=frozenset(),
        columns=(),
        foreign_keys=(),
        indexes=(),
        views=(),
        triggers=(),
        procedures=(),
        functions=(),
    )


class SqlCleanupCorrectnessTests(unittest.TestCase):
    def test_sql_edit_probe_requires_every_core_table_and_change_log_permission(self):
        class _PermissionCursor:
            def __init__(self, core_result, metadata_result):
                self._core_result = core_result
                self._metadata_result = metadata_result
                self._last_sql = ""

            def execute(self, sql, *_params):
                self._last_sql = sql
                return self

            def fetchone(self):
                if "FROM sys.tables" in self._last_sql:
                    return self._core_result
                return self._metadata_result

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        class _PermissionManager:
            def __init__(self, core_result, metadata_result):
                self._cursor = _PermissionCursor(core_result, metadata_result)

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield SimpleNamespace(cursor=lambda: self._cursor)

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        current = (
            LATEST_SQL_SCHEMA.version,
            LATEST_SQL_SCHEMA.checksum,
            1,
            "READ_WRITE",
        )
        table_count = len(LATEST_SQL_SCHEMA.core_schema.tables)
        complete = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager((table_count, 0), current),
        )
        self.assertTrue(complete.can_edit(descriptor.database_id))
        missing_table = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager((table_count - 1, 0), current),
        )
        self.assertFalse(missing_table.can_edit(descriptor.database_id))
        denied_table = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager((table_count, 1), current),
        )
        self.assertFalse(denied_table.can_edit(descriptor.database_id))
        denied_change_log = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager(
                (table_count, 0),
                (
                    LATEST_SQL_SCHEMA.version,
                    LATEST_SQL_SCHEMA.checksum,
                    0,
                    "READ_WRITE",
                ),
            ),
        )
        self.assertFalse(denied_change_log.can_edit(descriptor.database_id))
        read_only_database = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager(
                (table_count, 0),
                (
                    LATEST_SQL_SCHEMA.version,
                    LATEST_SQL_SCHEMA.checksum,
                    1,
                    "READ_ONLY",
                ),
            ),
        )
        self.assertFalse(read_only_database.can_edit(descriptor.database_id))

    def test_sql_edit_probe_treats_connection_failure_as_read_only(self):
        class _UnavailableManager:
            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                del autocommit
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CONNECTION_FAILED,
                        "The SQL Server is unavailable.",
                    )
                )
                yield

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        probe = SqlDatabasePermissionProbe(
            registry, _CredentialStore(), connection_manager=_UnavailableManager()
        )
        self.assertFalse(probe.can_edit(descriptor.database_id))

    def test_repository_uses_the_composed_database_reader(self):
        manager = object()
        reader = object()
        calls = []
        provider = RepositoryProvider(
            logging.getLogger("test"),
            project_reader_factory=lambda connection_manager: (
                calls.append(connection_manager) or reader
            ),
        )
        repository = provider.get_project_repository(manager)
        self.assertIs(repository.parser.parser, reader)
        self.assertEqual(calls, [manager])

    def test_access_writer_uses_access_schema_inspector(self):
        writer = DatabaseProjectWriter(
            object(), DatabaseDescriptorRegistry(), _CredentialStore()
        )
        with writer._backend_scope("example.mdb"):
            self.assertIsInstance(writer._schema(object()), MdbSchemaInspector)

    def test_writer_requires_an_explicit_backend_scope(self):
        writer = DatabaseProjectWriter(
            object(), DatabaseDescriptorRegistry(), _CredentialStore()
        )
        with self.assertRaisesRegex(RuntimeError, "backend scope"):
            writer._current_backend()

    def test_missing_sql_descriptor_never_falls_through_to_access(self):
        registry = DatabaseDescriptorRegistry()
        writer = DatabaseProjectWriter(object(), registry, _CredentialStore())
        with self.assertRaisesRegex(LookupError, "not registered"):
            writer._is_sql("unregistered-database-id")
        reader = DatabaseProjectReader(object(), registry, _CredentialStore())
        with self.assertRaisesRegex(LookupError, "not registered"):
            reader._is_sql("unregistered-database-id")

    def test_schema_inspector_index_query_has_canonical_from_clause(self):
        inspector = SqlSchemaInspector(_InspectionManager())
        inventory = inspector.inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        self.assertEqual(inventory.indexes, ())

    def test_sql_reader_rejects_invalid_schema_before_domain_queries(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        reader = SqlProjectReader(registry, _CredentialStore(), _InspectionManager())
        reader._inspector.inspect_request = lambda _request: _empty_inventory()
        with patch.object(
            MdbReader,
            "parse_file",
            side_effect=AssertionError("domain query ran before schema validation"),
        ):
            with self.assertRaisesRegex(Exception, "Schema mismatch"):
                reader.parse_file(descriptor.database_id)

    def test_sql_cursor_has_one_owner_and_is_closed_once(self):
        raw_connection = _RawConnection()
        lease = SqlConnectionLease(raw_connection, 30)
        wrapper = ConnectionWrapper(lease, accepts_cursor_options=False)
        cursor = wrapper.cursor()
        cursor.close()
        lease.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 1)

    def test_repeated_sql_connection_cycles_close_every_resource_once(self):
        connections = []

        def connect(*_args, **_kwargs):
            connection = _RawConnection()
            connections.append(connection)
            return connection

        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=connect,
        ):
            for _ in range(50):
                with manager.connection(request, autocommit=True) as lease:
                    with lease.cursor():
                        pass
        self.assertEqual(len(connections), 50)
        self.assertTrue(all(conn.close_count == 1 for conn in connections))
        self.assertTrue(all(conn.raw_cursor.close_count == 1 for conn in connections))

    def test_sql_write_failure_rolls_back_and_closes_all_cursors(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        writer = SqlProjectWriter(
            registry, _CredentialStore(), connection_manager=manager
        )
        with self.assertRaisesRegex(RuntimeError, "mid-operation"):
            with writer._connection(descriptor.database_id):
                raise RuntimeError("mid-operation failure")
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)
        self.assertTrue(
            all(cursor.close_count == 1 for cursor in manager.lease.cursors)
        )

    def test_sql_import_table_metadata_comes_from_canonical_schema(self):
        writer = DatabaseProjectWriter(
            object(), DatabaseDescriptorRegistry(), _CredentialStore()
        )

        class _NoMetadataConnection:
            def cursor(self):
                raise AssertionError("writer queried a second schema inventory")

        columns, types = writer._get_table_info(_NoMetadataConnection(), "Bids")
        self.assertIn("UID", columns)
        self.assertEqual(types["UID"], "int")

    def test_schema_validation_failure_rolls_back_before_commit(self):
        manager = _CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = (
            lambda *_args, **_kwargs: _empty_inventory()
        )
        with self.assertRaisesRegex(Exception, "validation failed"):
            creator.initialize_blank_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="OSTV_TEST_AUDIT"
                ),
                application_version="test",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_schema_creation_rejects_unversioned_read_only_validation(self):
        manager = _CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = lambda *_args: _empty_inventory()
        creator._validator.validate = lambda _inventory: SqlSchemaValidationReport(
            SqlSchemaCompatibility.UNVERSIONED_READ_ONLY,
            0,
        )
        with self.assertRaisesRegex(Exception, "validation failed"):
            creator.initialize_blank_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="OSTV_TEST_AUDIT"
                ),
                application_version="test",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_compatible_external_database_adoption_adds_only_ostv_schema(self):
        manager = _CreationManager()
        creator = SqlDatabaseCreator(manager)
        inventories = iter(
            (
                _empty_inventory(),
                SqlSchemaInventory(
                    database_guid="00000000-0000-0000-0000-000000000001",
                    schema_version=LATEST_SQL_SCHEMA.version,
                    schema_checksum=LATEST_SQL_SCHEMA.checksum,
                    tables=frozenset(),
                    columns=(),
                    foreign_keys=(),
                    indexes=(),
                    views=(),
                    triggers=(),
                    procedures=(),
                    functions=(),
                ),
            )
        )
        creator._inspector.inspect_connection = lambda _lease: next(inventories)
        creator._validator.validate_adoption_candidate = (
            lambda _inventory: SqlSchemaValidationReport(
                SqlSchemaCompatibility.UNVERSIONED_READ_ONLY, 0
            )
        )
        creator._validator.validate = lambda inventory: SqlSchemaValidationReport(
            (
                SqlSchemaCompatibility.CURRENT
                if inventory.schema_version == LATEST_SQL_SCHEMA.version
                else SqlSchemaCompatibility.UNVERSIONED_READ_ONLY
            ),
            inventory.schema_version,
        )
        result = creator.initialize_compatible_database(
            SqlServerDatabaseLocation(server="localhost", database="EXTERNAL_OST_TEST"),
            application_version="test",
        )
        statements = manager.lease.cursor_value.executed
        self.assertTrue(
            any(sql.startswith("CREATE SCHEMA [ostv]") for sql in statements)
        )
        self.assertFalse(
            any(sql.startswith("CREATE TABLE [dbo]") for sql in statements)
        )
        self.assertEqual(result.schema_version, LATEST_SQL_SCHEMA.version)
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)
        SqlProjectWriter._require_current_schema(manager.lease)

    def test_external_database_adoption_rejects_structural_mismatch(self):
        manager = _CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = lambda _lease: _empty_inventory()
        creator._validator.validate_adoption_candidate = (
            lambda _inventory: SqlSchemaValidationReport(
                SqlSchemaCompatibility.INVALID,
                0,
                ("dbo.Bids.Name",),
            )
        )
        with self.assertRaisesRegex(Exception, "cannot be enabled"):
            creator.initialize_compatible_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="EXTERNAL_OST_INVALID"
                ),
                application_version="test",
            )
        self.assertFalse(
            any(
                sql.startswith("CREATE SCHEMA [ostv]")
                for sql in manager.lease.cursor_value.executed
            )
        )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_failed_unload_retains_removed_checked_descriptor(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        entry = FileEntry.for_descriptor(descriptor)
        updates = []
        state = type(
            "State",
            (),
            {
                "file_entries": [entry],
                "reload": lambda self: None,
                "update_entries": lambda self, entries: updates.append(list(entries)),
            },
        )()

        class _Dialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return []

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=state,
            cleanup_deleted_files_use_case=type(
                "Cleanup", (), {"execute_and_save": lambda self: 0}
            )(),
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda _locator: False,
            deferred_persistence_manager=type(
                "Deferred",
                (),
                {
                    "flush_for_file": lambda self, _locator: True,
                    "cancel_for_file": lambda self, _locator: None,
                },
            )(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            credential_store=_CredentialStore(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler."
            "OpenFilesDialog",
            _Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ):
            handler.open_files()
        self.assertEqual(updates[-1], [entry])

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
        dialog.cleanup()
        self.assertIsNone(dialog._initial_connection)
        self.assertEqual(dialog.password_input.text(), "")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
