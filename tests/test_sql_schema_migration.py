import contextlib
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.database_descriptor import (
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.schema_definition import LATEST_SQL_SCHEMA
from ost_visualizer.infrastructure.sql.schema_migrator import SqlSchemaMigrator
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaCompatibility,
    SqlSchemaValidationReport,
)


class _Cursor:
    def __init__(self, statements):
        self.statements = statements
        self.last_sql = ""
        self.rowcount = -1

    def execute(self, sql, *_parameters):
        self.last_sql = sql
        self.statements.append(sql)
        self.rowcount = 1 if sql.startswith("UPDATE [ostv].[DatabaseMetadata]") else -1
        return self

    def fetchone(self):
        if "sp_getapplock" in self.last_sql:
            return (0,)
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()


class _Lease:
    def __init__(self):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self.statements)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Manager:
    def __init__(self):
        self.lease = _Lease()

    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield self.lease


class SqlSchemaMigrationTests(unittest.TestCase):
    def _migrator(self, final_compatibility):
        manager = _Manager()
        migrator = SqlSchemaMigrator(manager)
        inventories = iter(
            (
                SimpleNamespace(database_guid="guid-before"),
                SimpleNamespace(database_guid="guid-after"),
            )
        )
        migrator._inspector.inspect_connection = lambda _lease: next(inventories)
        migrator._validator.validate_versioned_schema = (
            lambda _inventory, _schema: SqlSchemaValidationReport(
                SqlSchemaCompatibility.CURRENT, 2
            )
        )
        migrator._validator.validate = lambda _inventory: SqlSchemaValidationReport(
            final_compatibility,
            LATEST_SQL_SCHEMA.version,
            (() if final_compatibility == SqlSchemaCompatibility.CURRENT else ("bad",)),
        )
        return migrator, manager

    def test_version_2_upgrade_commits_only_after_final_validation(self):
        migrator, manager = self._migrator(SqlSchemaCompatibility.CURRENT)
        result = migrator.migrate_version_2_to_latest(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            application_version="test",
            actor="tester",
        )
        self.assertEqual(result.schema_version, LATEST_SQL_SCHEMA.version)
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)
        self.assertIn("sp_getapplock", manager.lease.statements[0])
        self.assertTrue(
            any(
                statement.startswith("ALTER TABLE [ostv].[DatabaseMetadata]")
                for statement in manager.lease.statements
            )
        )

    def test_version_2_upgrade_rolls_back_failed_final_validation(self):
        migrator, manager = self._migrator(SqlSchemaCompatibility.INVALID)
        with self.assertRaisesRegex(Exception, "validation failed"):
            migrator.migrate_version_2_to_latest(
                SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
                application_version="test",
                actor="tester",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
