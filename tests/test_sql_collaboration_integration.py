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
from ost_visualizer.infrastructure.sql.connection_manager import SqlConnectionRequest
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
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
    def test_fresh_disposable_database_uses_canonical_v1_and_is_removed(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            inventory = SqlSchemaInspector(database.connections).inspect(
                database.location,
                configuration.password,
            )
            self.assertEqual(inventory.schema_version, SQL_SCHEMA_V1.version)
            self.assertEqual(inventory.schema_checksum, SQL_SCHEMA_V1.checksum)

    def test_two_independent_clients_own_distinct_sessions_and_locks(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            descriptor = DatabaseDescriptor.for_sql_server(
                database.location,
                schema_version=SQL_SCHEMA_V1.version,
            )
            stores = []
            sessions = []
            for client_number in (1, 2):
                registry = DatabaseDescriptorRegistry()
                registry.register(descriptor)
                credentials = _RuntimeCredentialStore(configuration.password)
                store = SqlCollaborationStore(
                    registry,
                    credentials,
                    SqlRemoteChangeReader(registry, credentials),
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

    def test_inverse_identity_commit_order_is_delivered_without_splitting(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            descriptor = DatabaseDescriptor.for_sql_server(
                database.location,
                schema_version=SQL_SCHEMA_V1.version,
            )
            registry = DatabaseDescriptorRegistry()
            registry.register(descriptor)
            credentials = _RuntimeCredentialStore(configuration.password)
            store = SqlCollaborationStore(
                registry,
                credentials,
                SqlRemoteChangeReader(registry, credentials, database.connections),
                database.connections,
            )
            sessions = tuple(
                store.start_session(
                    descriptor.database_id,
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    f"commit-order-client-{number}",
                    "test-machine",
                    "integration-test",
                )
                for number in (1, 2)
            )
            request = SqlConnectionRequest(
                database.location,
                password=configuration.password,
            )
            transaction_a = str(uuid.uuid4())
            transaction_b = str(uuid.uuid4())
            rolled_back_transaction = str(uuid.uuid4())
            baseline = sessions[0].last_acknowledged_version
            try:
                with database.connections.connection(
                    request, autocommit=False
                ) as lease_a:
                    with lease_a.cursor() as cursor_a:
                        database_guid = self._database_guid(cursor_a)
                        sequence_a = self._insert_change(
                            cursor_a,
                            transaction_a,
                            sessions[0].session_id,
                            database_guid,
                            "inverse-a",
                        )
                    with database.connections.connection(
                        request, autocommit=False
                    ) as lease_b:
                        with lease_b.cursor() as cursor_b:
                            sequence_b1 = self._insert_change(
                                cursor_b,
                                transaction_b,
                                sessions[1].session_id,
                                database_guid,
                                "inverse-b-1",
                            )
                            sequence_b2 = self._insert_change(
                                cursor_b,
                                transaction_b,
                                sessions[1].session_id,
                                database_guid,
                                "inverse-b-2",
                            )
                            self._insert_marker(
                                cursor_b,
                                transaction_b,
                                sessions[1].session_id,
                                database_guid,
                            )
                        lease_b.commit()
                    first = store.poll_changes(
                        descriptor.database_id, baseline, 1, "test-observer"
                    ).observed_batch
                    self.assertEqual(
                        tuple(change.sequence for change in first.changes),
                        (sequence_b1, sequence_b2),
                    )
                    self.assertEqual(
                        {change.commit_version for change in first.changes},
                        {first.delivered_through_version},
                    )
                    with lease_a.cursor() as cursor_a:
                        self._insert_marker(
                            cursor_a,
                            transaction_a,
                            sessions[0].session_id,
                            database_guid,
                        )
                    lease_a.commit()
                second = store.poll_changes(
                    descriptor.database_id,
                    first.delivered_through_version,
                    1,
                    "test-observer",
                ).observed_batch
                self.assertEqual(
                    tuple(change.sequence for change in second.changes),
                    (sequence_a,),
                )
                self.assertLess(sequence_a, sequence_b1)
                self.assertGreater(
                    second.changes[0].commit_version,
                    first.delivered_through_version,
                )
                with database.connections.connection(
                    request, autocommit=False
                ) as rolled_back:
                    with rolled_back.cursor() as cursor:
                        self._insert_change(
                            cursor,
                            rolled_back_transaction,
                            sessions[0].session_id,
                            database_guid,
                            "rolled-back",
                        )
                        self._insert_marker(
                            cursor,
                            rolled_back_transaction,
                            sessions[0].session_id,
                            database_guid,
                        )
                    rolled_back.rollback()
                after_rollback = store.poll_changes(
                    descriptor.database_id,
                    second.delivered_through_version,
                    10,
                    "test-observer",
                ).observed_batch
                self.assertEqual(after_rollback.changes, ())
                with database.connections.connection(
                    request, autocommit=True
                ) as verification:
                    with verification.cursor() as cursor:
                        cursor.execute(
                            "SELECT (SELECT COUNT(*) FROM [ostv].[ChangeLog] "
                            "WHERE [TransactionId]=?), (SELECT COUNT(*) FROM "
                            "[ostv].[ChangeTransactions] WHERE [TransactionId]=?)",
                            rolled_back_transaction,
                            rolled_back_transaction,
                        )
                        self.assertEqual(tuple(cursor.fetchone()), (0, 0))
            finally:
                for session in sessions:
                    store.close_session(
                        descriptor.database_id,
                        session.session_id,
                        "integration-test-complete",
                    )

    @staticmethod
    def _database_guid(cursor):
        cursor.execute("SELECT [DatabaseGuid] FROM [ostv].[DatabaseMetadata]")
        return cursor.fetchone()[0]

    @staticmethod
    def _insert_change(
        cursor,
        transaction_id,
        session_id,
        database_guid,
        resource_id,
    ):
        cursor.execute(
            "INSERT INTO [ostv].[ChangeLog] ([TransactionId], "
            "[SourceSessionId], [DatabaseGuid], [ResourceType], [ResourceId], "
            "[Operation], [SourceKind]) OUTPUT INSERTED.[Sequence] VALUES "
            "(?, ?, ?, N'database', ?, N'update', N'ost_visualizer')",
            transaction_id,
            session_id,
            database_guid,
            resource_id,
        )
        return int(cursor.fetchone()[0])

    @staticmethod
    def _insert_marker(cursor, transaction_id, session_id, database_guid):
        cursor.execute(
            "INSERT INTO [ostv].[ChangeTransactions] ([TransactionId], "
            "[SourceSessionId], [DatabaseGuid]) VALUES (?, ?, ?)",
            transaction_id,
            session_id,
            database_guid,
        )


if __name__ == "__main__":
    unittest.main()
