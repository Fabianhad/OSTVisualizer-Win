import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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


class MaintenanceBackendRoutingTests(unittest.TestCase):
    def test_backend_router_and_explicit_sql_unsupported(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="server",
                database="db",
                database_guid="00000000-0000-0000-0000-000000000001",
            ),
            schema_version=1,
        )
        registry.register(descriptor)
        access = Mock()
        router = DatabaseMaintenanceRouter(registry, access, SqlDatabaseMaintenance())
        router.compact("sample.mdb")
        access.compact.assert_called_once_with("sample.mdb")
        result = router.compact(descriptor.database_id)
        self.assertFalse(result.success)
        self.assertIn("not available for SQL Server", result.message)
        self.assertEqual(access.compact.call_count, 1)
