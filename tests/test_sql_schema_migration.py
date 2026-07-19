import contextlib
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.database_descriptor import (
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.schema_definition import (
    LATEST_SQL_SCHEMA,
    SQL_SCHEMA_V3,
)
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
    def _migrator(self, final_compatibility, *, change_tracking_enabled=False):
        manager = _Manager()
        migrator = SqlSchemaMigrator(manager)
        inventories = iter(
            (
                SimpleNamespace(
                    database_guid="guid-before",
                    change_tracking_enabled=change_tracking_enabled,
                ),
                SimpleNamespace(
                    database_guid="guid-after",
                    change_tracking_enabled=change_tracking_enabled,
                ),
            )
        )
        migrator._inspector.inspect_connection = lambda _lease: next(inventories)
        validations = iter(
            (
                SqlSchemaValidationReport(SqlSchemaCompatibility.CURRENT, 2),
                SqlSchemaValidationReport(
                    final_compatibility,
                    LATEST_SQL_SCHEMA.version,
                    (
                        ()
                        if final_compatibility == SqlSchemaCompatibility.CURRENT
                        else ("bad",)
                    ),
                ),
            )
        )
        migrator._validator.validate_versioned_schema = (
            lambda _inventory, _schema: next(validations)
        )
        return migrator, manager

    def test_version_2_to_3_commits_only_after_final_validation(self):
        migrator, manager = self._migrator(SqlSchemaCompatibility.CURRENT)
        result = migrator.migrate_version_2_to_3(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            application_version="test",
            actor="tester",
        )
        self.assertEqual(result.schema_version, SQL_SCHEMA_V3.version)
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)
        self.assertIn("sp_getapplock", manager.lease.statements[0])
        self.assertTrue(
            any(
                statement.startswith("ALTER TABLE [ostv].[DatabaseMetadata]")
                for statement in manager.lease.statements
            )
        )

    def test_version_2_to_3_rolls_back_failed_final_validation(self):
        migrator, manager = self._migrator(SqlSchemaCompatibility.INVALID)
        with self.assertRaisesRegex(Exception, "validation failed"):
            migrator.migrate_version_2_to_3(
                SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
                application_version="test",
                actor="tester",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_version_3_to_4_is_transactional_and_enables_marker_tracking(self):
        migrator, manager = self._migrator(
            SqlSchemaCompatibility.CURRENT,
            change_tracking_enabled=True,
        )
        result = migrator.migrate_version_3_to_4(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            application_version="test",
            actor="tester",
        )
        self.assertEqual(result.schema_version, LATEST_SQL_SCHEMA.version)
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)
        self.assertTrue(
            any(
                statement.startswith(
                    "ALTER TABLE [ostv].[ChangeTransactions] ENABLE CHANGE_TRACKING"
                )
                for statement in manager.lease.statements
            )
        )

    def test_version_3_to_4_rolls_back_failed_final_validation(self):
        migrator, manager = self._migrator(
            SqlSchemaCompatibility.INVALID,
            change_tracking_enabled=True,
        )
        with self.assertRaisesRegex(Exception, "validation failed"):
            migrator.migrate_version_3_to_4(
                SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
                application_version="test",
                actor="tester",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_version_3_to_4_requires_database_change_tracking_precondition(self):
        migrator, manager = self._migrator(SqlSchemaCompatibility.CURRENT)
        with self.assertRaisesRegex(Exception, "Enable SQL Server Change Tracking"):
            migrator.migrate_version_3_to_4(
                SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
                application_version="test",
                actor="tester",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
