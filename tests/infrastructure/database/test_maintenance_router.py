import os
import unittest
from unittest.mock import create_autospec

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
    IDatabaseMaintenance,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.maintenance_router import (
    DatabaseMaintenanceRouter,
)
from ost_visualizer.infrastructure.sql.database_maintenance import (
    SqlDatabaseMaintenance,
)


def _sql_descriptor():
    return DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(
            server="server",
            database="db",
            database_guid="00000000-0000-0000-0000-000000000001",
        ),
        schema_version=1,
    )


class MaintenanceBackendRoutingTests(unittest.TestCase):
    def test_backend_router_and_explicit_sql_unsupported(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = _sql_descriptor()
        registry.register(descriptor)
        access = create_autospec(IDatabaseMaintenance, instance=True)
        router = DatabaseMaintenanceRouter(registry, access, SqlDatabaseMaintenance())
        router.compact("sample.mdb")
        access.compact.assert_called_once_with("sample.mdb")
        result = router.compact(descriptor.database_id)
        self.assertFalse(result.success)
        self.assertIn("not available for SQL Server", result.message)
        self.assertEqual(access.compact.call_count, 1)

    def test_every_maintenance_operation_is_routed_to_the_matching_backend(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = _sql_descriptor()
        registry.register(descriptor)
        access = create_autospec(IDatabaseMaintenance, instance=True)
        sql = create_autospec(IDatabaseMaintenance, instance=True)
        router = DatabaseMaintenanceRouter(registry, access, sql)
        identity = object()
        for locator, selected, other in (
            ("sample.mdb", access, sql),
            (descriptor.database_id, sql, access),
        ):
            with self.subTest(locator=locator):
                selected.reset_mock()
                other.reset_mock()
                selected.capture_target.return_value = "target"
                selected.prepare.return_value = "prepared"
                selected.is_target_current.return_value = True
                selected.unavailable_reason.return_value = "reason"
                self.assertEqual(router.capture_target(locator), "target")
                self.assertEqual(router.prepare(locator, identity), "prepared")
                self.assertIs(router.is_target_current(locator, identity), True)
                self.assertEqual(router.unavailable_reason(locator), "reason")
                router.release_target(locator, identity)
                router.compact(locator)
                selected.capture_target.assert_called_once_with(locator)
                selected.prepare.assert_called_once_with(locator, identity)
                selected.is_target_current.assert_called_once_with(locator, identity)
                selected.unavailable_reason.assert_called_once_with(locator)
                selected.release_target.assert_called_once_with(locator, identity)
                selected.compact.assert_called_once_with(locator)
                self.assertEqual(other.mock_calls, [])

    def test_unregistered_non_access_locator_is_not_routed(self):
        access = create_autospec(IDatabaseMaintenance, instance=True)
        router = DatabaseMaintenanceRouter(
            DatabaseDescriptorRegistry(), access, SqlDatabaseMaintenance()
        )
        with self.assertRaises(LookupError):
            router.compact("unregistered-database-id")
        self.assertEqual(access.mock_calls, [])

    def test_sql_maintenance_never_captures_prepares_or_reports_current_targets(self):
        sql = SqlDatabaseMaintenance()
        reason = sql.unavailable_reason("any")
        self.assertIn("not available for SQL Server", reason)
        for operation in (
            lambda: sql.capture_target("any"),
            lambda: sql.prepare("any", object()),
            lambda: sql.release_target("any", object()),
        ):
            with self.assertRaisesRegex(RuntimeError, "not available for SQL Server"):
                operation()
        self.assertIs(sql.is_target_current("any", object()), False)
        self.assertEqual(
            sql.compact("any"),
            DatabaseMaintenanceResult(False, reason),
        )
