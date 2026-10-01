import unittest
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationStatus,
    ResourceRef,
    SynchronizationState,
)
from ost_visualizer.application.services.database_capability_service import (
    DatabaseCapabilityService,
)
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from tests.helpers.sql.collaboration import _PermissionProbe


class DatabaseCapabilityServiceCollaborationTests(unittest.TestCase):
    def test_resource_lock_projection_is_targeted_and_bid_delete_sees_children(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        locked = ResourceRef("condition", "42", 8)
        capabilities.update_collaboration_resources(
            descriptor.database_id, frozenset({locked})
        )
        self.assertFalse(capabilities.is_editable(descriptor.database_id, locked))
        self.assertTrue(
            capabilities.is_editable(
                descriptor.database_id, ResourceRef("condition", "43", 8)
            )
        )
        self.assertFalse(
            capabilities.is_editable(descriptor.database_id, ResourceRef("bid", "8", 8))
        )
        self.assertTrue(
            capabilities.is_editable(descriptor.database_id, ResourceRef("bid", "9", 9))
        )
        capabilities.update_collaboration_resources(descriptor.database_id, frozenset())
        self.assertTrue(capabilities.is_editable(descriptor.database_id, locked))
        capabilities.update_collaboration_resources(
            descriptor.database_id, frozenset({ResourceRef("bid", "8", 8)})
        )
        self.assertFalse(
            capabilities.is_editable(
                descriptor.database_id, ResourceRef("page", "12", 8)
            )
        )
        self.assertTrue(
            capabilities.is_editable(
                descriptor.database_id, ResourceRef("page", "13", 9)
            )
        )

    def test_capability_check_uses_one_collaboration_status_snapshot(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        locked = ResourceRef("condition", "42", 8)

        class SnapshotChangingCapabilities(DatabaseCapabilityService):
            def __init__(self):
                super().__init__(descriptors, _PermissionProbe())
                self.status_reads = 0

            def collaboration_status(self, database_id):
                self.status_reads += 1
                if self.status_reads == 1:
                    return CollaborationStatus(
                        database_id=database_id,
                        state=SynchronizationState.HEALTHY,
                        locked_resources=frozenset({locked}),
                    )
                return CollaborationStatus(
                    database_id=database_id,
                    state=SynchronizationState.STOPPED,
                )

        capabilities = SnapshotChangingCapabilities()
        capabilities.mark_connected(descriptor.database_id)
        self.assertFalse(capabilities.is_editable(descriptor.database_id, locked))
        self.assertEqual(capabilities.status_reads, 1)

    def test_resource_conflict_is_targeted_and_cleared_by_reconciliation(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        conflicted = ResourceRef("condition", "42", 8)
        capabilities.add_collaboration_conflict(descriptor.database_id, conflicted)
        self.assertFalse(capabilities.is_editable(descriptor.database_id, conflicted))
        self.assertTrue(
            capabilities.is_editable(
                descriptor.database_id, ResourceRef("condition", "43", 8)
            )
        )
        capabilities.clear_collaboration_conflicts(descriptor.database_id)
        self.assertTrue(capabilities.is_editable(descriptor.database_id, conflicted))

    def test_state_transitions_preserve_locks_while_conflict_clear_is_targeted(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        locked = ResourceRef("condition", "42", 8)
        conflicted = ResourceRef("condition", "43", 8)
        capabilities.update_collaboration_resources(
            descriptor.database_id, frozenset({locked})
        )
        capabilities.add_collaboration_conflict(descriptor.database_id, conflicted)
        capabilities.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY, "ready"
        )
        status = capabilities.collaboration_status(descriptor.database_id)
        self.assertEqual(status.locked_resources, frozenset({locked}))
        self.assertEqual(status.conflicted_resources, frozenset({conflicted}))
        capabilities.clear_collaboration_conflicts(descriptor.database_id)
        self.assertFalse(capabilities.is_editable(descriptor.database_id, locked))
        self.assertTrue(capabilities.is_editable(descriptor.database_id, conflicted))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).message, "ready"
        )
        for state in (
            SynchronizationState.STOPPED,
            SynchronizationState.CONNECTING,
            SynchronizationState.CATCHING_UP,
            SynchronizationState.DISCONNECTED,
            SynchronizationState.CREDENTIAL_REQUIRED,
            SynchronizationState.READ_ONLY,
            SynchronizationState.CONFLICTED,
            SynchronizationState.RECONCILIATION_REQUIRED,
        ):
            with self.subTest(state=state):
                capabilities.set_collaboration_state(descriptor.database_id, state)
                self.assertFalse(capabilities.is_editable(descriptor.database_id))
        capabilities.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(capabilities.is_editable(descriptor.database_id, conflicted))


class DatabaseCapabilityServiceDatabaseDescriptorTests(unittest.TestCase):
    def test_capability_service_denies_sql_permission_even_when_collaboration_is_healthy(
        self,
    ):
        class _ReadOnlyPermissionProbe:
            def can_edit(self, _database_id):
                return False

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="Canonical"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        service = DatabaseCapabilityService(registry, _ReadOnlyPermissionProbe())
        self.assertFalse(service.mark_connected(descriptor.database_id))
        service.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertFalse(service.is_editable(descriptor.database_id))

    def test_capability_service_refreshes_immediately_after_reconnect_and_disconnect(
        self,
    ):
        class _PermissionProbe:
            editable = False

            def can_edit(self, _database_id):
                return self.editable

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="Canonical"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        probe = _PermissionProbe()
        service = DatabaseCapabilityService(registry, probe)
        service.mark_connected(descriptor.database_id)
        self.assertFalse(service.is_editable(descriptor.database_id))
        probe.editable = True
        service.mark_connected(descriptor.database_id)
        service.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(service.is_editable(descriptor.database_id))
        service.mark_disconnected(descriptor.database_id)
        self.assertFalse(service.is_editable(descriptor.database_id))
        self.assertEqual(
            service.collaboration_status(descriptor.database_id).state,
            SynchronizationState.STOPPED,
        )
        service.mark_connected(descriptor.database_id)
        self.assertFalse(service.is_editable(descriptor.database_id))
        service.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(service.is_editable(descriptor.database_id))

    def test_failed_permission_refresh_revokes_only_that_database(self):
        class Probe:
            failure = None

            def can_edit(self, database_id):
                if database_id == first.database_id and self.failure is not None:
                    raise self.failure
                return True

        registry = DatabaseDescriptorRegistry()
        first = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation("server", "first"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        second = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation("server", "second"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register_all((first, second))
        probe = Probe()
        service = DatabaseCapabilityService(registry, probe)
        for descriptor in (first, second):
            self.assertTrue(service.mark_connected(descriptor.database_id))
            service.set_collaboration_state(
                descriptor.database_id, SynchronizationState.HEALTHY
            )
            self.assertTrue(service.is_editable(descriptor.database_id))
        for failure in (OSError("offline"), DatabaseCatalogError("denied")):
            with self.subTest(failure=type(failure)):
                probe.failure = failure
                self.assertFalse(service.mark_connected(first.database_id))
                self.assertFalse(service.is_editable(first.database_id))
                self.assertTrue(service.is_editable(second.database_id))
                probe.failure = None
                self.assertTrue(service.mark_connected(first.database_id))
                self.assertTrue(service.is_editable(first.database_id))

    def test_capability_service_denies_unknown_locator_and_allows_registered_access(
        self,
    ):
        class _PermissionProbe:
            def can_edit(self, _database_id):
                raise AssertionError("Access does not require a SQL permission probe")

        registry = DatabaseDescriptorRegistry()
        service = DatabaseCapabilityService(registry, _PermissionProbe())
        self.assertFalse(service.is_editable("unknown-database-id"))
        descriptor = DatabaseDescriptor.for_access(r"C:\data\sample.mdb")
        registry.register(descriptor)
        self.assertTrue(service.is_editable(descriptor.access_path))
