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
        inspector = SqlSchemaInspector(_cleanup_support__InspectionManager())
        inventory = inspector.inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        self.assertEqual(inventory.indexes, ())

    def test_schema_inspector_excludes_sql_server_internal_tables(self):
        manager = _cleanup_support__InspectionManager()
        inspector = SqlSchemaInspector(manager)
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
        inventory = SqlSchemaInspector(manager).inspect(
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
        return SqlSchemaInspector.inspect_connection(_CatalogLease(cursor))

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
                yield _CatalogLease(_CatalogCursor())

        location = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        SqlSchemaInspector(_Manager()).inspect(
            location, "secret", database_override="Other"
        )
        self.assertEqual(autocommit_values, [True])
        self.assertEqual(requests[0].location, location)
        self.assertEqual(requests[0].password, "secret")
        self.assertEqual(requests[0].database_override, "Other")
        self.assertTrue(requests[0].read_only)
