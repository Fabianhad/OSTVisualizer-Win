import unittest
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    PresenceMode,
    ResourceRef,
)
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.domain.entities.database_descriptor import DatabaseDescriptor
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.collaboration_store import (
    SqlCollaborationStore,
)
from ost_visualizer.infrastructure.sql.schema_definition import LATEST_SQL_SCHEMA
from ost_visualizer.infrastructure.sql.schema_inspector import SqlSchemaInspector
from tests.sql_integration_support import (
    DisposableSqlConfiguration,
    DisposableSqlDatabase,
)


class _RuntimeCredentialStore:
    def __init__(self, password: str) -> None:
        self._password = password

    def read_password(self, _target: str) -> str:
        return self._password

    def write_password(self, _target: str, _username: str, password: str) -> None:
        self._password = password

    def delete_password(self, _target: str) -> None:
        self._password = ""


class SqlCollaborationIntegrationTests(unittest.TestCase):
    def test_fresh_disposable_database_uses_latest_schema_and_is_removed(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            inventory = SqlSchemaInspector(database.connections).inspect(
                database.location,
                configuration.password,
            )
            self.assertEqual(inventory.schema_version, LATEST_SQL_SCHEMA.version)
            self.assertEqual(inventory.schema_checksum, LATEST_SQL_SCHEMA.checksum)

    def test_two_independent_clients_own_distinct_sessions_and_locks(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            descriptor = DatabaseDescriptor.for_sql_server(
                database.location,
                schema_version=LATEST_SQL_SCHEMA.version,
            )
            stores = []
            sessions = []
            for client_number in (1, 2):
                registry = DatabaseDescriptorRegistry()
                registry.register(descriptor)
                store = SqlCollaborationStore(
                    registry,
                    _RuntimeCredentialStore(configuration.password),
                )
                stores.append(store)
                session = store.start_session(
                    descriptor.database_id,
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    f"test-client-{client_number}",
                    "test-machine",
                    "integration-test",
                )
                sessions.append(session)
            resource = ResourceRef("database", descriptor.database_id)
            lock = None
            try:
                stores[0].heartbeat(
                    descriptor.database_id,
                    sessions[0].session_id,
                    0,
                    None,
                    None,
                    PresenceMode.VIEWING,
                )
                lock = stores[0].acquire_lock(
                    descriptor.database_id,
                    sessions[0].session_id,
                    resource,
                    "integration test",
                )
                with self.assertRaises(DatabaseCatalogError) as conflict:
                    stores[1].acquire_lock(
                        descriptor.database_id,
                        sessions[1].session_id,
                        resource,
                        "conflicting integration test",
                    )
                self.assertNotIn(configuration.password, str(conflict.exception))
            finally:
                if lock is not None:
                    stores[0].release_lock(
                        descriptor.database_id,
                        sessions[0].session_id,
                        lock.lock_token,
                    )
                for store, session in zip(stores, sessions):
                    store.close_session(
                        descriptor.database_id,
                        session.session_id,
                        "integration-test-complete",
                    )


if __name__ == "__main__":
    unittest.main()
