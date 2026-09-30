import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)


class DescriptorRegistryDatabaseDescriptorTests(unittest.TestCase):
    def test_registry_resolves_stable_database_id(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_access(r"C:\data\one.mdb")
        registry.register(descriptor)
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        registry.unregister(descriptor.database_id)
        self.assertIsNone(registry.resolve(descriptor.database_id))
