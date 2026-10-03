import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
    resolve_database_backend,
)


class DescriptorRegistryDatabaseDescriptorTests(unittest.TestCase):
    def test_registry_resolves_stable_database_id(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_access(r"C:\data\one.mdb")
        registry.register(descriptor)
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        registry.unregister(descriptor.database_id)
        self.assertIsNone(registry.resolve(descriptor.database_id))

    def test_access_descriptor_resolves_by_normalized_path_until_unregistered(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_access(r"C:\data\one.mdb")
        registry.register(descriptor)
        self.assertIs(registry.resolve(r"c:\DATA\.\one.MDB"), descriptor)
        self.assertIs(registry.resolve(r"C:\data\sub\..\one.mdb"), descriptor)
        self.assertIsNone(registry.resolve(r"C:\data\two.mdb"))
        registry.unregister(descriptor.database_id)
        self.assertIsNone(registry.resolve(r"C:\data\one.mdb"))

    def test_reregistering_a_database_id_replaces_its_previous_access_path(self):
        registry = DatabaseDescriptorRegistry()
        original = DatabaseDescriptor.for_access(
            r"C:\data\one.mdb", database_id="stable-id"
        )
        moved = DatabaseDescriptor.for_access(
            r"C:\data\moved.mdb", database_id="stable-id"
        )
        registry.register(original)
        registry.register(moved)
        self.assertIs(registry.resolve("stable-id"), moved)
        self.assertIs(registry.resolve(r"C:\data\moved.mdb"), moved)
        self.assertIsNone(registry.resolve(r"C:\data\one.mdb"))

    def test_sql_descriptor_resolves_only_by_database_id(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV"),
            schema_version=1,
        )
        registry.register_all([descriptor])
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        self.assertIsNone(registry.resolve("localhost"))
        registry.unregister(descriptor.database_id)
        self.assertIsNone(registry.resolve(descriptor.database_id))
        registry.unregister(descriptor.database_id)

    def test_backend_resolution_uses_registry_then_mdb_extension(self):
        registry = DatabaseDescriptorRegistry()
        sql = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV"),
            schema_version=1,
        )
        registry.register(sql)
        self.assertEqual(
            resolve_database_backend(registry, sql.database_id),
            DatabaseBackend.SQL_SERVER,
        )
        self.assertEqual(
            resolve_database_backend(registry, r"C:\data\unregistered.MDB"),
            DatabaseBackend.ACCESS,
        )
        with self.assertRaises(LookupError):
            resolve_database_backend(registry, "unregistered-sql-id")

    def test_sql_descriptors_never_touch_the_access_locator_index(self):
        registry = DatabaseDescriptorRegistry()
        # A SQL descriptor reports an empty Access path, which normalises to the
        # current directory; an Access database registered there must survive
        # every SQL registration, re-registration and removal.
        access = DatabaseDescriptor.for_access(os.getcwd(), database_id="cwd-access")
        sql = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV"),
            schema_version=1,
        )
        registry.register(access)
        registry.register(sql)
        self.assertIs(registry.resolve(os.getcwd()), access)
        registry.register(sql)
        self.assertIs(registry.resolve(os.getcwd()), access)
        registry.unregister(sql.database_id)
        self.assertIs(registry.resolve(os.getcwd()), access)
        self.assertIs(registry.resolve("cwd-access"), access)
