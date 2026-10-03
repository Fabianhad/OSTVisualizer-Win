import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.reader_router import DatabaseProjectReader
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from tests.helpers.sql.cleanup_support import (
    _CredentialStore as _cleanup_support__CredentialStore,
)


class RouterOwnershipSqlCleanupTests(unittest.TestCase):
    def test_missing_sql_descriptor_never_falls_through_to_access(self):
        registry = DatabaseDescriptorRegistry()
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with self.assertRaisesRegex(LookupError, "not registered"):
            writer._is_sql("unregistered-database-id")
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        with self.assertRaisesRegex(LookupError, "not registered"):
            reader._is_sql("unregistered-database-id")

    def test_registered_descriptors_and_legacy_mdb_paths_route_to_their_backend(self):
        # Positive controls for the LookupError test above: the same routers that
        # refuse an unknown non-MDB id do route registered and legacy locators.
        registry = DatabaseDescriptorRegistry()
        sql = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="server",
                database="db",
                database_guid="00000000-0000-0000-0000-000000000001",
            ),
            schema_version=1,
        )
        access = DatabaseDescriptor.for_access("C:/jobs/registered.mdb")
        registry.register(sql)
        registry.register(access)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        for router in (writer, reader):
            with self.subTest(router=type(router).__name__):
                self.assertTrue(router._is_sql(sql.database_id))
                self.assertFalse(router._is_sql(access.database_id))
                self.assertFalse(router._is_sql("C:/jobs/registered.mdb"))
                self.assertFalse(router._is_sql("C:/jobs/legacy-unregistered.MDB"))
