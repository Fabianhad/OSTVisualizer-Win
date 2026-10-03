from tests.helpers.sql.strict_sql_fakes import (
    StrictLeaseProxy,
    strict_cursor,
    strict_manager,
)
import contextlib
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.database_metadata_contract import (
    DATABASE_METADATA_CURRENT_DATABASE_PREDICATE,
)
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlColumnInventory,
    SqlForeignKeyInventory,
    SqlIndexInventory,
    SqlModuleInventory,
    SqlSchemaInspector,
    SqlSchemaInventory,
)
from tests.helpers.sql.cleanup_support import (
    _InspectionCursor as _cleanup_support__InspectionCursor,
    _InspectionLease as _cleanup_support__InspectionLease,
    _InspectionManager as _cleanup_support__InspectionManager,
    _canonical_writer_permission_snapshot as _cleanup_support__canonical_writer_permission_snapshot,
)


class SchemaInspectorSqlCleanupTests(unittest.TestCase):
    def test_schema_inspector_index_query_has_canonical_from_clause(self):
        inspector = SqlSchemaInspector(
            strict_manager(_cleanup_support__InspectionManager())
        )
        inventory = inspector.inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        self.assertEqual(inventory.indexes, ())

    def test_schema_inspector_excludes_sql_server_internal_tables(self):
        manager = _cleanup_support__InspectionManager()
        inspector = SqlSchemaInspector(strict_manager(manager))
        inspector.inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        table_inventory_queries = [
            sql for sql in manager.lease.cursor_value.executed if "sys.tables" in sql
        ]
        # tables, columns, foreign keys, indexes, check constraints, change tracking
        self.assertEqual(len(table_inventory_queries), 6)
        for sql in table_inventory_queries:
            with self.subTest(sql=sql[:60]):
                self.assertIn("is_ms_shipped=0", sql.replace("[", "").replace("]", ""))
        module_queries = [
            sql
            for sql in manager.lease.cursor_value.executed
            if "sys.triggers" in sql or "sys.objects" in sql
        ]
        # views, procedures, functions, triggers
        self.assertEqual(len(module_queries), 4)
        for sql in module_queries:
            with self.subTest(sql=sql[:60]):
                self.assertIn("is_ms_shipped=0", sql)

    def test_schema_inspector_rejects_multiple_database_metadata_rows(self):
        class _MetadataCursor(_cleanup_support__InspectionCursor):
            def fetchone(self):
                if "FROM [ostv].[DatabaseMetadata]" in self._last_sql:
                    if "COUNT_BIG(*)" in self._last_sql:
                        return None
                    return (SQL_SCHEMA_V1.version, SQL_SCHEMA_V1.checksum)
                if "database_guid" in self._last_sql:
                    return ("00000000-0000-0000-0000-000000000001",)
                return None

            def fetchall(self):
                if "SELECT s.name, t.name FROM sys.tables" in self._last_sql:
                    return [
                        ("ostv", "DatabaseMetadata"),
                        ("ostv", "SchemaMigrations"),
                    ]
                return []

        class _MetadataLease(_cleanup_support__InspectionLease):
            def __init__(self):
                super().__init__()
                self.cursor_value = _MetadataCursor()

        class _MetadataManager:
            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                self.lease = _MetadataLease()
                yield self.lease

        manager = _MetadataManager()
        inventory = SqlSchemaInspector(strict_manager(manager)).inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        self.assertEqual(inventory.schema_version, 0)
        self.assertEqual(inventory.schema_checksum, "")
        metadata_sql = [
            sql
            for sql in manager.lease.cursor_value.executed
            if "FROM [ostv].[DatabaseMetadata] m" in sql
        ]
        self.assertEqual(len(metadata_sql), 1)
        self.assertTrue(
            metadata_sql[0].endswith(DATABASE_METADATA_CURRENT_DATABASE_PREDICATE)
        )
        self.assertIn("COUNT_BIG(*) FROM [ostv].[DatabaseMetadata]", metadata_sql[0])


class _CatalogCursor:
    """Answers each catalog query with scripted rows keyed by a SQL fragment."""

    def __init__(self, tracking_row=(7, "DAYS", 1), snapshot_row=(1,)):
        self._tracking_row = tracking_row
        self._snapshot_row = snapshot_row
        self._sql = ""
        self._params = ()

    def execute(self, sql, *params):
        self._sql = sql
        self._params = params
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return None

    def fetchone(self):
        if "CONVERT(nvarchar(36), database_guid)" in self._sql:
            return ("ABCDEF00-0000-0000-0000-000000000009",)
        if "FROM [ostv].[DatabaseMetadata] m" in self._sql:
            return (1, "checksum-value")
        if "snapshot_isolation_state" in self._sql:
            return self._snapshot_row
        if "FROM sys.change_tracking_databases" in self._sql:
            return self._tracking_row
        raise AssertionError(f"unexpected fetchone for {self._sql[:60]}")

    def fetchall(self):
        sql = self._sql
        if sql.startswith("SELECT s.name, t.name FROM sys.tables"):
            return [
                ("dbo", "Bids"),
                ("ostv", "DatabaseMetadata"),
                ("ostv", "SchemaMigrations"),
            ]
        if "ty.name" in sql and "sys.columns c" in sql:
            return [
                ("dbo", "Bids", "BidUid", "uniqueidentifier", 16, 0, 0, 0, 0, None),
                ("dbo", "Bids", "Name", "nvarchar", 510, 0, 1, 0, 0, "(N'x')"),
            ]
        if "FROM sys.foreign_keys fk" in sql:
            return [
                (
                    "FK_Pages_Bids",
                    "dbo",
                    "Pages",
                    "BidUid",
                    "dbo",
                    "Bids",
                    "BidUid",
                    "CASCADE",
                )
            ]
        if "FROM sys.indexes i" in sql:
            return [
                ("dbo", "Bids", "IX_Bids", 1, 0, "Name", 2, "[Name] IS NOT NULL"),
                ("dbo", "Bids", "IX_Bids", 1, 0, "BidUid", 1, "[Name] IS NOT NULL"),
            ]
        if "FROM sys.objects o" in sql:
            if self._params == ("V",):
                return [("dbo", "ViewA")]
            if self._params == ("P",):
                return [("ostv", "ProcB")]
            return [("dbo", "FuncC")]
        if "FROM sys.triggers tr" in sql:
            return [("dbo", "TrigD")]
        if "FROM sys.check_constraints cc" in sql:
            return [("dbo", "Bids", "CK_Bids", "([Name]<>N'')")]
        if "FROM sys.change_tracking_tables ct" in sql:
            return [("ostv", "ChangeTransactions")]
        raise AssertionError(f"unexpected fetchall for {sql[:60]}")


class _CatalogLease:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class SchemaInspectorInventoryParsingTests(unittest.TestCase):
    @staticmethod
    def _inspect(cursor):
        return SqlSchemaInspector.inspect_connection(
            StrictLeaseProxy(_CatalogLease(cursor), autocommit=True)
        )

    def test_inventory_converts_every_catalog_row_into_typed_values(self):
        inventory = self._inspect(_CatalogCursor())
        self.assertEqual(
            inventory.database_guid, "ABCDEF00-0000-0000-0000-000000000009"
        )
        self.assertEqual(inventory.schema_version, 1)
        self.assertEqual(inventory.schema_checksum, "checksum-value")
        self.assertEqual(
            inventory.tables,
            frozenset(
                {
                    ("dbo", "Bids"),
                    ("ostv", "DatabaseMetadata"),
                    ("ostv", "SchemaMigrations"),
                }
            ),
        )
        self.assertEqual(
            inventory.columns,
            (
                SqlColumnInventory(
                    "dbo",
                    "Bids",
                    "BidUid",
                    "uniqueidentifier",
                    16,
                    0,
                    False,
                    False,
                    False,
                    "",
                ),
                SqlColumnInventory(
                    "dbo",
                    "Bids",
                    "Name",
                    "nvarchar",
                    510,
                    0,
                    True,
                    False,
                    False,
                    "(N'x')",
                ),
            ),
        )
        self.assertEqual(
            inventory.foreign_keys,
            (
                SqlForeignKeyInventory(
                    "FK_Pages_Bids",
                    "dbo",
                    "Pages",
                    "BidUid",
                    "dbo",
                    "Bids",
                    "BidUid",
                    "CASCADE",
                ),
            ),
        )
        self.assertEqual(
            inventory.indexes,
            (
                SqlIndexInventory(
                    "dbo",
                    "Bids",
                    "IX_Bids",
                    True,
                    False,
                    ("BidUid", "Name"),
                    "[Name] IS NOT NULL",
                ),
            ),
        )
        self.assertEqual(inventory.views, (SqlModuleInventory("dbo", "ViewA"),))
        self.assertEqual(inventory.procedures, (SqlModuleInventory("ostv", "ProcB"),))
        self.assertEqual(inventory.functions, (SqlModuleInventory("dbo", "FuncC"),))
        self.assertEqual(inventory.triggers, (SqlModuleInventory("dbo", "TrigD"),))
        self.assertEqual(
            [(c.table_name, c.name, c.definition) for c in inventory.check_constraints],
            [("Bids", "CK_Bids", "([Name]<>N'')")],
        )
        self.assertTrue(inventory.snapshot_isolation_enabled)
        self.assertTrue(inventory.change_tracking_enabled)
        self.assertEqual(inventory.change_tracking_retention_days, 7)
        self.assertTrue(inventory.change_tracking_auto_cleanup)
        self.assertEqual(
            inventory.change_tracking_tables,
            frozenset({("ostv", "ChangeTransactions")}),
        )

    def test_change_tracking_and_snapshot_states_are_reported_exactly(self):
        disabled = self._inspect(_CatalogCursor(tracking_row=None, snapshot_row=(0,)))
        self.assertFalse(disabled.change_tracking_enabled)
        self.assertFalse(disabled.snapshot_isolation_enabled)
        self.assertEqual(disabled.change_tracking_retention_days, 0)
        self.assertFalse(disabled.change_tracking_auto_cleanup)
        hours = self._inspect(_CatalogCursor(tracking_row=(48, "HOURS", 0)))
        self.assertTrue(hours.change_tracking_enabled)
        # A non-day retention unit can never satisfy the canonical retention days.
        self.assertEqual(hours.change_tracking_retention_days, -1)
        self.assertFalse(hours.change_tracking_auto_cleanup)
        # SQL Server reports 2 while snapshot isolation is still transitioning.
        transitioning = self._inspect(_CatalogCursor(snapshot_row=(2,)))
        self.assertFalse(transitioning.snapshot_isolation_enabled)

    def test_inspect_opens_read_only_autocommit_request(self):
        requests = []
        autocommit_values = []

        class _Manager:
            @contextlib.contextmanager
            def connection(self, request, *, autocommit=False):
                requests.append(request)
                autocommit_values.append(autocommit)
                yield StrictLeaseProxy(
                    _CatalogLease(_CatalogCursor()), autocommit=autocommit
                )

        location = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        SqlSchemaInspector(_Manager()).inspect(
            location, "secret", database_override="Other"
        )
        self.assertEqual(autocommit_values, [True])
        self.assertEqual(requests[0].location, location)
        self.assertEqual(requests[0].password, "secret")
        self.assertEqual(requests[0].database_override, "Other")
        self.assertTrue(requests[0].read_only)


from ost_visualizer.infrastructure.sql.errors import (  # noqa: E402
    SqlErrorCode,
    SqlInfrastructureError,
)
from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    EXPECTED_DATABASE_METADATA_PREDICATE,
    Reply,
    StrictSqlServer,
    sql_server_error,
)
from ost_visualizer.infrastructure.sql.database_metadata_contract import (  # noqa: E402
    DATABASE_METADATA_SINGLETON_PREDICATE,
)


class SchemaInspectorStrictServerTests(unittest.TestCase):
    LOCATION = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")

    def _server(self, tables=()):
        server = StrictSqlServer()
        server.on(
            "SELECT CONVERT(nvarchar(36), database_guid)", Reply.rows(("GUID-1",))
        )
        server.on("SELECT s.name, t.name FROM sys.tables", Reply.rows(*tables))
        server.on("FROM [ostv].[DatabaseMetadata] m", Reply.rows((1, "checksum")))
        server.on("snapshot_isolation_state", Reply.rows((1,)))
        server.on("FROM sys.change_tracking_databases", Reply.rows((7, "DAYS", 1)))
        server.on(
            "FROM sys.change_tracking_tables",
            Reply.rows(("ostv", "ChangeTransactions")),
        )
        server.on("SELECT", Reply.rows())
        return server

    def test_inspection_is_one_read_only_autocommit_connection_with_every_cursor_closed(
        self,
    ):
        server = self._server()
        with server.patched():
            inventory = SqlSchemaInspector(server.manager()).inspect(self.LOCATION)
        self.assertEqual(inventory.database_guid, "GUID-1")
        self.assertEqual(len(server.connections), 1)
        self.assertTrue(server.connect_calls[0]["autocommit"])
        self.assertIn(
            "ApplicationIntent=ReadOnly", server.connect_calls[0]["connection_string"]
        )
        raw = server.connections[0]
        # inspection is read-only: it never begins, commits or rolls back
        self.assertEqual((raw.commits, raw.rollbacks), (0, 0))
        # the three module reads bind exactly their type-code placeholders
        modules = [
            params
            for cursor in raw.cursors
            for sql, params in cursor.executed
            if "FROM sys.objects o" in sql
        ]
        self.assertEqual(modules, [("V",), ("P",), ("FN", "IF", "TF", "FS", "FT")])
        server.assert_everything_closed()

    def test_driver_failure_mid_inspection_is_classified_and_releases_the_connection(
        self,
    ):
        server = self._server()

        def fail(_call):
            raise sql_server_error("08S01", "Communication link failure")

        server.rules.insert(0, (lambda sql: "FROM sys.foreign_keys fk" in sql, fail))
        with server.patched():
            with self.assertRaises(SqlInfrastructureError) as raised:
                SqlSchemaInspector(server.manager()).inspect(self.LOCATION)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        server.assert_everything_closed()

    def test_database_metadata_predicate_is_exactly_one_row_for_this_database(self):
        self.assertEqual(
            DATABASE_METADATA_CURRENT_DATABASE_PREDICATE,
            EXPECTED_DATABASE_METADATA_PREDICATE,
        )
        self.assertTrue(
            EXPECTED_DATABASE_METADATA_PREDICATE.startswith(
                DATABASE_METADATA_SINGLETON_PREDICATE
            )
        )
        self.assertEqual(
            DATABASE_METADATA_SINGLETON_PREDICATE,
            "m.[Product]=N'OST Visualizer' AND (SELECT COUNT_BIG(*) FROM "
            "[ostv].[DatabaseMetadata] metadata_count WHERE "
            "metadata_count.[Product]=N'OST Visualizer')=1",
        )

    def test_schema_version_is_read_only_through_the_single_row_identity_predicate(
        self,
    ):
        tables = (("ostv", "DatabaseMetadata"), ("ostv", "SchemaMigrations"))
        server = self._server(tables)
        with server.patched():
            inventory = SqlSchemaInspector(server.manager()).inspect(self.LOCATION)
        self.assertEqual(
            (inventory.schema_version, inventory.schema_checksum), (1, "checksum")
        )
        statements = [
            sql
            for number, kind, sql in server.events
            if kind == "execute" and "FROM [ostv].[DatabaseMetadata] m" in sql
        ]
        self.assertEqual(len(statements), 1)
        self.assertTrue(
            statements[0].endswith("WHERE " + EXPECTED_DATABASE_METADATA_PREDICATE)
        )
        # the metadata read is skipped entirely when the ledger tables are absent
        empty = self._server(())
        with empty.patched():
            absent = SqlSchemaInspector(empty.manager()).inspect(self.LOCATION)
        self.assertEqual((absent.schema_version, absent.schema_checksum), (0, ""))
        self.assertFalse(any("DatabaseMetadata" in s for s in empty.statements()))


class SchemaInspectorRowMappingTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over schema_inspector.py."""

    def test_inventory_values_are_immutable_and_default_to_an_unconfigured_database(
        self,
    ):
        import dataclasses

        empty = SqlSchemaInventory(
            database_guid="",
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
        self.assertEqual(empty.check_constraints, ())
        self.assertIs(empty.change_tracking_enabled, False)
        self.assertEqual(empty.change_tracking_tables, frozenset())
        self.assertIs(empty.snapshot_isolation_enabled, False)
        self.assertEqual(empty.change_tracking_retention_days, 0)
        self.assertIs(empty.change_tracking_auto_cleanup, False)
        from ost_visualizer.infrastructure.sql.schema_inspector import (
            SqlCheckConstraintInventory,
        )

        for value in (
            empty,
            SqlColumnInventory("dbo", "T", "C", "int", 4, 0, False, False, False),
            SqlForeignKeyInventory("fk", "dbo", "C", "a", "dbo", "P", "a"),
            SqlIndexInventory("dbo", "T", "ix", False, False, ("a",), ""),
            SqlModuleInventory("dbo", "v"),
            SqlCheckConstraintInventory("dbo", "T", "ck", "(1=1)"),
        ):
            with self.subTest(kind=type(value).__name__):
                first_field = dataclasses.fields(value)[0].name
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(value, first_field, "changed")
        self.assertEqual(
            SqlForeignKeyInventory(
                "fk", "dbo", "C", "a", "dbo", "P", "a"
            ).on_delete_action,
            "NO_ACTION",
        )
        self.assertEqual(
            SqlColumnInventory(
                "dbo", "T", "C", "int", 4, 0, False, False, False
            ).default_definition,
            "",
        )

    def test_default_connection_manager_is_created_when_none_is_injected(self):
        from ost_visualizer.infrastructure.sql.connection_manager import (
            SqlConnectionManager,
        )

        self.assertIsInstance(SqlSchemaInspector()._connections, SqlConnectionManager)

    def test_missing_guid_or_ledger_values_default_without_failing(self):
        class _Cursor(_CatalogCursor):
            def __init__(self, guid_row, metadata_row, tables):
                super().__init__()
                self._guid_row = guid_row
                self._metadata_row = metadata_row
                self._tables = tables

            def fetchone(self):
                if "CONVERT(nvarchar(36), database_guid)" in self._sql:
                    return self._guid_row
                if "FROM [ostv].[DatabaseMetadata] m" in self._sql:
                    return self._metadata_row
                return super().fetchone()

            def fetchall(self):
                if self._sql.startswith("SELECT s.name, t.name FROM sys.tables"):
                    return list(self._tables)
                return super().fetchall()

        both = (("ostv", "DatabaseMetadata"), ("ostv", "SchemaMigrations"))
        for guid_row, expected_guid in (
            (None, ""),
            ((None,), ""),
            (("",), ""),
            (("G",), "G"),
        ):
            with self.subTest(guid_row=guid_row):
                inventory = SqlSchemaInspector.inspect_connection(
                    _CatalogLease(_Cursor(guid_row, (1, "sum"), both))
                )
                self.assertEqual(inventory.database_guid, expected_guid)
        for metadata_row, expected in (
            (None, (0, "")),
            ((None, None), (0, "")),
            ((1, None), (1, "")),
            ((2, "abc"), (2, "abc")),
        ):
            with self.subTest(metadata_row=metadata_row):
                inventory = SqlSchemaInspector.inspect_connection(
                    _CatalogLease(_Cursor(("G",), metadata_row, both))
                )
                self.assertEqual(
                    (inventory.schema_version, inventory.schema_checksum), expected
                )

    def test_ledger_is_only_read_when_both_ledger_tables_exist(self):
        class _Cursor(_CatalogCursor):
            def __init__(self, tables):
                super().__init__()
                self._tables = tables
                self.metadata_reads = 0

            def fetchone(self):
                if "FROM [ostv].[DatabaseMetadata] m" in self._sql:
                    self.metadata_reads += 1
                return super().fetchone()

            def fetchall(self):
                if self._sql.startswith("SELECT s.name, t.name FROM sys.tables"):
                    return list(self._tables)
                return super().fetchall()

        for label, tables, reads in (
            ("only metadata", (("ostv", "DatabaseMetadata"),), 0),
            ("only migrations", (("ostv", "SchemaMigrations"),), 0),
            (
                "dbo copies are not the ledger",
                (("dbo", "DatabaseMetadata"), ("dbo", "SchemaMigrations")),
                0,
            ),
            ("both", (("ostv", "DatabaseMetadata"), ("ostv", "SchemaMigrations")), 1),
        ):
            with self.subTest(label=label):
                cursor = _Cursor(tables)
                inventory = SqlSchemaInspector.inspect_connection(_CatalogLease(cursor))
                self.assertEqual(cursor.metadata_reads, reads)
                self.assertEqual(inventory.schema_version, 1 if reads else 0)

    def test_each_column_flag_and_index_flag_is_read_from_its_own_catalog_column(self):
        class _Cursor(_CatalogCursor):
            def fetchall(self):
                sql = self._sql
                if "ty.name" in sql and "sys.columns c" in sql:
                    return [
                        ("dbo", "T", "Identity", "int", 4, 0, 0, 1, 0, None),
                        ("dbo", "T", "Computed", "int", 4, 0, 0, 0, 1, None),
                        ("dbo", "T", "Nullable", "int", 4, 0, 1, 0, 0, None),
                    ]
                if "FROM sys.indexes i" in sql:
                    return [
                        ("dbo", "T", "UQ", 1, 0, "a", 1, ""),
                        ("dbo", "T", "PK", 0, 1, "a", 1, ""),
                        ("dbo", "T", "PK_UQ", 1, 1, "a", 1, ""),
                    ]
                return super().fetchall()

        inventory = SqlSchemaInspector.inspect_connection(_CatalogLease(_Cursor()))
        flags = {
            c.column_name: (c.nullable, c.identity, c.computed)
            for c in inventory.columns
        }
        self.assertEqual(
            flags,
            {
                "Identity": (False, True, False),
                "Computed": (False, False, True),
                "Nullable": (True, False, False),
            },
        )
        by_name = {i.index_name: (i.unique, i.primary_key) for i in inventory.indexes}
        self.assertEqual(
            by_name, {"UQ": (True, False), "PK": (False, True), "PK_UQ": (True, True)}
        )
