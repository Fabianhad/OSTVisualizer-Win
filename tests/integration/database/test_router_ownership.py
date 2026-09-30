import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
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
