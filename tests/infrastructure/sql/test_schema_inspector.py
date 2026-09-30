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
from ost_visualizer.infrastructure.sql.schema_inspector import (
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
        self.assertTrue(table_inventory_queries)
        self.assertTrue(
            all(
                "is_ms_shipped" in sql.replace("[", "").replace("]", "") and "=0" in sql
                for sql in table_inventory_queries
            )
        )

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

        inventory = SqlSchemaInspector(_MetadataManager()).inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        self.assertEqual(inventory.schema_version, 0)
        self.assertEqual(inventory.schema_checksum, "")
