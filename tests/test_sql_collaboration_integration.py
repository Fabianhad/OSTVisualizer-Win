import json
import secrets
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationMutationType,
    DatabaseMutationRequest,
    MutationOutcomeStatus,
    PresenceMode,
    ResourceRef,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.collaboration_store import (
    SqlCollaborationStore,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.schema_inspector import SqlSchemaInspector
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
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


class _CommitResponseLostManager:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.commit_failures = 0

    @contextmanager
    def connection(self, request, *, autocommit=False):
        with self._inner.connection(request, autocommit=autocommit) as lease:
            manager = self

            class _Lease:
                def cursor(self):
                    return lease.cursor()

                def commit(self):
                    lease.commit()
                    manager.commit_failures += 1
                    raise RuntimeError("simulated lost commit response")

                def rollback(self):
                    return lease.rollback()

                def getinfo(self, info_type):
                    return lease.getinfo(info_type)

            yield _Lease()


class SqlCollaborationIntegrationTests(unittest.TestCase):
    def test_project_import_commits_complete_feed_and_two_sessions_hydrate(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(
            configuration
        ) as database, tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "integration.ost"
            source.write_text(
                """
                <XML_ROOT><Bid UID="1" JobName="Imported">
                  <BidAreas>
                    <BidArea UID="10" BidUID="1" Name="Area" Sequence="1"/>
                  </BidAreas>
                  <BidLayers>
                    <BidLayer UID="11" BidUID="1" Name="Layer" Sequence="1"/>
                  </BidLayers>
                  <BidConditions>
                    <BidCondition UID="12" BidUID="1" Name="Condition"/>
                  </BidConditions>
                  <BidPages>
                    <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                      <BidTakeoffs>
                        <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                          BidConditionUID="12" BidAreaUID="10"/>
                      </BidTakeoffs>
                    </BidPage>
                  </BidPages>
                </Bid></XML_ROOT>
                """,
                encoding="utf-8",
            )
            (
                descriptor,
                registry,
                credentials,
                admin,
                windows_master,
                login,
            ) = self._create_test_client(database, configuration, "IMPORT")
            self.addCleanup(self._drop_test_login, admin, windows_master, login)
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
                    f"import-client-{index}",
                    "test-machine",
                    "integration-test",
                )
                for index in (1, 2)
            )
            session_registry = DatabaseSessionRegistry()
            session_registry.register(descriptor.database_id, sessions[0].session_id)
            writer = SqlProjectWriter(
                registry, credentials, session_registry, database.connections
            )
            importer = OstImporter(writer)
            resources = (
                ResourceRef("project_bids", "orphan"),
                ResourceRef("condition_types_collection", "database"),
                ResourceRef("job_statuses_collection", "database"),
                ResourceRef("employees_collection", "database"),
                ResourceRef("pay_classes_collection", "database"),
            )
            operation_id = str(uuid.uuid4())
            request = DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id=sessions[0].session_id,
                operation_id=operation_id,
                mutation_type=CollaborationMutationType.PROJECT_IMPORT.value,
                request_hash="d" * 64,
                resources=resources,
            )
            baseline = sessions[1].last_acknowledged_version
            try:
                result = writer.execute(
                    request,
                    lambda recorder: importer.import_ost_mutation(
                        str(source), descriptor.database_id, None, recorder
                    ),
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                bid_uid = int(next(iter(result.value["bid_uids"].values())))
                self.assertEqual(len(result.value["page_uids"]), 1)
                self.assertEqual(len(result.value["condition_uids"]), 1)
                self.assertEqual(len(result.value["layer_uids"]), 1)
                self.assertEqual(len(result.value["area_uids"]), 1)
                self.assertEqual(len(result.value["takeoff_uids"]), 1)
                with database.connections.connection(
                    SqlConnectionRequest(
                        database.location,
                        password=configuration.password,
                        read_only=True,
                    ),
                    autocommit=True,
                ) as verification:
                    with verification.cursor() as cursor:
                        cursor.execute(
                            "SELECT (SELECT COUNT(*) FROM [dbo].[Bids] WHERE [UID]=?), "
                            "(SELECT COUNT(*) FROM [ostv].[ChangeTransactions] WHERE "
                            "[TransactionId]=?), (SELECT COUNT(*) FROM [ostv].[ChangeLog] "
                            "WHERE [TransactionId]=?)",
                            bid_uid,
                            operation_id,
                            operation_id,
                        )
                        row = tuple(cursor.fetchone())
                self.assertEqual(row[:2], (1, 1))
                self.assertGreaterEqual(row[2], 9)
                local = store.hydrate_operation(descriptor.database_id, operation_id)
                self.assertIn(bid_uid, local.bid_data_by_bid)
                self.assertEqual(len(local.bid_data_by_bid[bid_uid].bid_takeoffs), 1)
                remote = store.poll_changes(
                    descriptor.database_id,
                    baseline,
                    100,
                    sessions[1].session_id,
                )
                self.assertIn(
                    operation_id,
                    {
                        change.transaction_id
                        for change in remote.remote_batch.batch.changes
                    },
                )
                self.assertIn(bid_uid, remote.remote_batch.bid_data_by_bid)
                own = store.poll_changes(
                    descriptor.database_id,
                    baseline,
                    100,
                    sessions[0].session_id,
                )
                self.assertEqual(own.remote_batch.batch.changes, ())
            finally:
                for session in sessions:
                    store.close_session(
                        descriptor.database_id,
                        session.session_id,
                        "integration-test-complete",
                    )

    def test_real_commit_with_simulated_lost_response_recovers_without_duplicate(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            (
                descriptor,
                registry,
                credentials,
                admin,
                windows_master,
                login,
            ) = self._create_test_client(database, configuration, "COMMIT_RECOVERY")
            self.addCleanup(self._drop_test_login, admin, windows_master, login)
            store = SqlCollaborationStore(
                registry,
                credentials,
                SqlRemoteChangeReader(registry, credentials, database.connections),
                database.connections,
            )
            session = store.start_session(
                descriptor.database_id,
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "commit-recovery-client",
                "test-machine",
                "integration-test",
            )
            sessions = DatabaseSessionRegistry()
            sessions.register(descriptor.database_id, session.session_id)
            lossy_connections = _CommitResponseLostManager(database.connections)
            lossy_writer = SqlProjectWriter(
                registry, credentials, sessions, lossy_connections
            )
            normal_writer = SqlProjectWriter(
                registry, credentials, sessions, database.connections
            )
            operation_id = str(uuid.uuid4())
            resource = ResourceRef("projects_collection", "database")
            request = DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id=session.session_id,
                operation_id=operation_id,
                mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                request_hash="e" * 64,
                resources=(resource,),
            )

            def create_project(writer, recorder):
                uid = writer.create_project(descriptor.database_id, "Recovered")
                recorder.record(ResourceRef("project", uid), ChangeOperation.CREATE)
                recorder.record(resource, ChangeOperation.UPDATE)
                return uid

            try:
                uncertain = lossy_writer.execute(
                    request,
                    lambda recorder: create_project(lossy_writer, recorder),
                )
                self.assertEqual(
                    uncertain.outcome_status,
                    MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                )
                self.assertEqual(lossy_connections.commit_failures, 1)
                durable = store.query_operation(descriptor.database_id, operation_id)
                self.assertTrue(durable.found)
                recovered = normal_writer.execute(
                    request,
                    lambda _recorder: self.fail(
                        "a committed uncertain operation must not execute twice"
                    ),
                )
                self.assertEqual(
                    recovered.outcome_status, MutationOutcomeStatus.COMMITTED
                )
                recovered_uid = str(recovered.value)
                with database.connections.connection(
                    SqlConnectionRequest(
                        database.location,
                        password=configuration.password,
                        read_only=True,
                    ),
                    autocommit=True,
                ) as verification:
                    with verification.cursor() as cursor:
                        cursor.execute(
                            "SELECT COUNT(*) FROM [dbo].[BidProjects] WHERE "
                            "[UID]=? AND [Name]=N'Recovered'",
                            int(recovered_uid),
                        )
                        self.assertEqual(int(cursor.fetchone()[0]), 1)
                hydrated = store.hydrate_operation(descriptor.database_id, operation_id)
                self.assertIsNotNone(hydrated.hierarchy_file)
                rollback_operation = str(uuid.uuid4())
                rollback_request = replace(
                    request,
                    operation_id=rollback_operation,
                    request_hash="f" * 64,
                )

                def fail_during_dml(_recorder):
                    normal_writer.create_project(
                        descriptor.database_id, "Must Roll Back"
                    )
                    raise RuntimeError("simulated connection loss during DML")

                with self.assertRaisesRegex(RuntimeError, "during DML"):
                    normal_writer.execute(rollback_request, fail_during_dml)
                self.assertFalse(
                    store.query_operation(
                        descriptor.database_id, rollback_operation
                    ).found
                )
                with database.connections.connection(
                    SqlConnectionRequest(
                        database.location,
                        password=configuration.password,
                        read_only=True,
                    ),
                    autocommit=True,
                ) as verification:
                    with verification.cursor() as cursor:
                        cursor.execute(
                            "SELECT COUNT(*) FROM [dbo].[BidProjects] WHERE "
                            "[Name]=N'Must Roll Back'"
                        )
                        self.assertEqual(int(cursor.fetchone()[0]), 0)
            finally:
                store.close_session(
                    descriptor.database_id,
                    session.session_id,
                    "integration-test-complete",
                )

    def test_fresh_disposable_database_uses_canonical_v1_and_is_removed(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            inventory = SqlSchemaInspector(database.connections).inspect(
                database.location,
                configuration.password,
            )
            self.assertEqual(inventory.schema_version, SQL_SCHEMA_V1.version)
            self.assertEqual(inventory.schema_checksum, SQL_SCHEMA_V1.checksum)

    def test_two_clients_conflict_on_every_shared_editor_resource_family(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            (
                descriptor,
                registry,
                credentials,
                admin,
                windows_master,
                login,
            ) = self._create_test_client(database, configuration, "FAMILY_CONFLICT")
            self.addCleanup(self._drop_test_login, admin, windows_master, login)
            stores = []
            sessions = []
            for client_number in (1, 2):
                store = SqlCollaborationStore(
                    registry,
                    credentials,
                    SqlRemoteChangeReader(registry, credentials, database.connections),
                    database.connections,
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
            session_registries = (
                DatabaseSessionRegistry(),
                DatabaseSessionRegistry(),
            )
            writers = []
            for session_registry, session in zip(session_registries, sessions):
                session_registry.register(descriptor.database_id, session.session_id)
                writers.append(
                    SqlProjectWriter(
                        registry,
                        credentials,
                        session_registry,
                        database.connections,
                    )
                )
            try:
                stores[0].heartbeat(
                    descriptor.database_id,
                    sessions[0].session_id,
                    0,
                    None,
                    None,
                    PresenceMode.VIEWING,
                )
                scenarios = (
                    (
                        "database hierarchy",
                        ResourceRef("database", descriptor.database_id),
                    ),
                    (
                        "project hierarchy",
                        ResourceRef("projects_collection", descriptor.database_id),
                    ),
                    ("bid hierarchy", ResourceRef("bid", "8", 8)),
                    ("page hierarchy", ResourceRef("pages_collection", "8", 8)),
                    ("page edit", ResourceRef("page", "18", 8)),
                    (
                        "condition collection edit",
                        ResourceRef("conditions_collection", "8", 8),
                    ),
                    ("condition conflict", ResourceRef("condition", "28", 8)),
                    (
                        "layer collection edit",
                        ResourceRef("layers_collection", "8", 8),
                    ),
                    ("layer conflict", ResourceRef("layer", "38", 8)),
                    ("area edit", ResourceRef("areas_collection", "8", 8)),
                    ("cover-sheet edit", ResourceRef("cover_sheet", "8", 8)),
                    (
                        "concurrent placement",
                        ResourceRef("takeoffs_collection", "8", 8),
                    ),
                    ("paste versus paste", ResourceRef("takeoffs_collection", "8", 8)),
                    ("move versus delete", ResourceRef("takeoff", "48", 8)),
                    ("delete versus edit", ResourceRef("takeoff", "48", 8)),
                    (
                        "condition-type edit",
                        ResourceRef(
                            "condition_types_collection", descriptor.database_id
                        ),
                    ),
                    (
                        "default-layer edit",
                        ResourceRef(
                            "default_layers_collection", descriptor.database_id
                        ),
                    ),
                    (
                        "job-status edit",
                        ResourceRef("job_statuses_collection", descriptor.database_id),
                    ),
                    (
                        "employee edit",
                        ResourceRef("employees_collection", descriptor.database_id),
                    ),
                    (
                        "pay-class edit",
                        ResourceRef("pay_classes_collection", descriptor.database_id),
                    ),
                )
                for scenario, resource in scenarios:
                    with self.subTest(
                        scenario=scenario,
                        resource_type=resource.resource_type,
                    ):
                        lock = stores[0].acquire_lock(
                            descriptor.database_id,
                            sessions[0].session_id,
                            resource,
                            "integration test",
                        )
                        session_registries[0].register_lock(
                            descriptor.database_id,
                            lock.resource,
                            lock.lock_token,
                        )
                        try:
                            with self.assertRaises(DatabaseCatalogError) as conflict:
                                stores[1].acquire_lock(
                                    descriptor.database_id,
                                    sessions[1].session_id,
                                    resource,
                                    "conflicting integration test",
                                )
                            self.assertNotIn(
                                configuration.password, str(conflict.exception)
                            )
                            operation_ran = []
                            mutation = writers[1].execute(
                                DatabaseMutationRequest(
                                    database_id=descriptor.database_id,
                                    session_id=sessions[1].session_id,
                                    operation_id=str(uuid.uuid4()),
                                    mutation_type=(
                                        CollaborationMutationType.PROJECT_WRITE.value
                                    ),
                                    request_hash=(f"{len(scenario):064x}"[-64:]),
                                    resources=(resource,),
                                ),
                                lambda _recorder: operation_ran.append(True),
                            )
                            self.assertEqual(
                                mutation.outcome_status,
                                MutationOutcomeStatus.CONFLICT,
                            )
                            self.assertEqual(operation_ran, [])
                        finally:
                            session_registries[0].remove_lock(
                                descriptor.database_id, resource
                            )
                            stores[0].release_lock(
                                descriptor.database_id,
                                sessions[0].session_id,
                                lock.lock_token,
                            )
                expiring_resource = ResourceRef("takeoff", "expired-48", 8)
                expired_lock = stores[0].acquire_lock(
                    descriptor.database_id,
                    sessions[0].session_id,
                    expiring_resource,
                    "expiration integration test",
                )
                with database.connections.connection(
                    SqlConnectionRequest(
                        database.location,
                        password=configuration.password,
                    ),
                    autocommit=True,
                ) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "UPDATE [ostv].[Locks] SET [AcquiredAt]="
                            "DATEADD(second, -2, SYSUTCDATETIME()), "
                            "[LastRenewedAt]=DATEADD(second, -2, SYSUTCDATETIME()), "
                            "[ExpiresAt]=DATEADD(second, -1, SYSUTCDATETIME()) "
                            "WHERE [LockToken]=?",
                            expired_lock.lock_token,
                        )
                replacement = stores[1].acquire_lock(
                    descriptor.database_id,
                    sessions[1].session_id,
                    expiring_resource,
                    "replacement after expiration",
                )
                try:
                    self.assertNotEqual(
                        replacement.lock_token,
                        expired_lock.lock_token,
                    )
                finally:
                    stores[1].release_lock(
                        descriptor.database_id,
                        sessions[1].session_id,
                        replacement.lock_token,
                    )
            finally:
                for store, session in zip(stores, sessions):
                    store.close_session(
                        descriptor.database_id,
                        session.session_id,
                        "integration-test-complete",
                    )

    def test_two_sessions_place_and_converge_with_same_session_suppression(self):
        configuration = DisposableSqlConfiguration.from_environment()
        login = f"OSTV_IT_TMP_CONVERGENCE_{secrets.token_hex(6).upper()}"
        password = secrets.token_urlsafe(32)
        admin = SqlConnectionManager()
        windows_master = replace(
            configuration.location,
            authentication_mode=SqlAuthenticationMode.WINDOWS,
            username="",
            database="master",
        )
        with admin.connection(
            SqlConnectionRequest(windows_master, database_override="master"),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "DECLARE @secret nvarchar(128)=?; "
                    "DECLARE @statement nvarchar(max)=N'CREATE LOGIN "
                    f"[{login}] WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)) + "
                    "N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF'; "
                    "EXEC sys.sp_executesql @statement",
                    password,
                )
        self.addCleanup(self._drop_test_login, admin, windows_master, login)
        with DisposableSqlDatabase(configuration) as database:
            with database.connections.connection(
                SqlConnectionRequest(
                    database.location,
                    password=configuration.password,
                ),
                autocommit=True,
            ) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO [dbo].[Bids] OUTPUT INSERTED.[UID] "
                        "DEFAULT VALUES"
                    )
                    bid_uid = int(cursor.fetchone()[0])
                    cursor.execute(
                        "INSERT INTO [dbo].[BidConditions] ([BidUID]) "
                        "OUTPUT INSERTED.[UID] VALUES (?)",
                        bid_uid,
                    )
                    condition_uid = int(cursor.fetchone()[0])
                    cursor.execute(
                        "INSERT INTO [dbo].[BidPages] ([BidUID]) "
                        "OUTPUT INSERTED.[UID] VALUES (?)",
                        bid_uid,
                    )
                    page_uid = int(cursor.fetchone()[0])
                    cursor.execute(f"CREATE USER [{login}] FOR LOGIN [{login}]")
                    apply_sql_client_permissions(cursor, login)
            client_location = replace(
                database.location,
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username=login,
            )
            descriptor = DatabaseDescriptor.for_sql_server(
                client_location,
                schema_version=SQL_SCHEMA_V1.version,
            )
            registry = DatabaseDescriptorRegistry()
            registry.register(descriptor)
            credentials = _RuntimeCredentialStore(password)
            store = SqlCollaborationStore(
                registry,
                credentials,
                SqlRemoteChangeReader(registry, credentials, database.connections),
                database.connections,
            )
            session_rows = tuple(
                store.start_session(
                    descriptor.database_id,
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    f"convergence-client-{number}",
                    "test-machine",
                    "integration-test",
                )
                for number in (1, 2)
            )
            session_registries = (DatabaseSessionRegistry(), DatabaseSessionRegistry())
            writers = []
            for session_registry, session in zip(session_registries, session_rows):
                session_registry.register(descriptor.database_id, session.session_id)
                writers.append(
                    SqlProjectWriter(
                        registry,
                        credentials,
                        session_registry,
                        database.connections,
                    )
                )
            bid_key = str(bid_uid)
            condition_key = str(condition_uid)
            page_key = str(page_uid)
            collection = ResourceRef("takeoffs_collection", bid_key, bid_uid)
            dependencies = (
                ResourceRef("condition", condition_key, bid_uid),
                ResourceRef("page", page_key, bid_uid),
            )

            def place(client_index, x):
                session = session_rows[client_index]
                session_registry = session_registries[client_index]
                writer = writers[client_index]
                lock = store.acquire_lock(
                    descriptor.database_id,
                    session.session_id,
                    collection,
                    "two-session placement convergence",
                )
                session_registry.register_lock(
                    descriptor.database_id,
                    lock.resource,
                    lock.lock_token,
                )
                operation_id = str(uuid.uuid4())

                def mutate(recorder):
                    created = writer.insert_takeoffs(
                        descriptor.database_id,
                        bid_key,
                        [
                            InsertTakeoffSpec(
                                condition_uid=condition_key,
                                page_uid=page_key,
                                area_uid="0",
                                position=[x, 20.0],
                            )
                        ],
                    )
                    for uid in created:
                        recorder.record(
                            ResourceRef("takeoff", uid, bid_uid),
                            ChangeOperation.CREATE,
                        )
                    recorder.record(collection, ChangeOperation.UPDATE)
                    return created

                try:
                    result = writer.execute(
                        DatabaseMutationRequest(
                            database_id=descriptor.database_id,
                            session_id=session.session_id,
                            operation_id=operation_id,
                            mutation_type=(
                                CollaborationMutationType.TAKEOFF_PLACEMENT.value
                            ),
                            request_hash=("a" if client_index == 0 else "b") * 64,
                            resources=(collection, *dependencies),
                            required_lock_tokens=session_registry.lock_tokens(
                                descriptor.database_id,
                                (collection, *dependencies),
                            ),
                        ),
                        mutate,
                    )
                finally:
                    session_registry.remove_lock(descriptor.database_id, collection)
                    store.release_lock(
                        descriptor.database_id,
                        session.session_id,
                        lock.lock_token,
                    )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                return operation_id, str((result.value or ())[0])

            baseline = min(row.last_acknowledged_version for row in session_rows)
            try:
                first_operation, first_uid = place(0, 10.0)
                own_first = store.poll_changes(
                    descriptor.database_id,
                    baseline,
                    100,
                    session_rows[0].session_id,
                )
                self.assertIn(
                    first_operation,
                    {
                        change.transaction_id
                        for change in own_first.observed_batch.changes
                    },
                )
                self.assertEqual(own_first.remote_batch.batch.changes, ())
                remote_first = store.poll_changes(
                    descriptor.database_id,
                    baseline,
                    100,
                    session_rows[1].session_id,
                )
                self.assertIn(
                    first_operation,
                    {
                        change.transaction_id
                        for change in remote_first.remote_batch.batch.changes
                    },
                )
                self.assertIn(
                    first_uid,
                    {
                        takeoff.uid
                        for takeoff in remote_first.remote_batch.bid_data_by_bid[
                            bid_uid
                        ].bid_takeoffs
                    },
                )
                second_operation, second_uid = place(1, 30.0)
                remote_second = store.poll_changes(
                    descriptor.database_id,
                    own_first.observed_batch.delivered_through_version,
                    100,
                    session_rows[0].session_id,
                )
                self.assertIn(
                    second_operation,
                    {
                        change.transaction_id
                        for change in remote_second.remote_batch.batch.changes
                    },
                )
                second_local_completion = store.hydrate_operation(
                    descriptor.database_id,
                    second_operation,
                )
                expected_uids = {first_uid, second_uid}
                first_client_uids = {
                    takeoff.uid
                    for takeoff in remote_second.remote_batch.bid_data_by_bid[
                        bid_uid
                    ].bid_takeoffs
                }
                second_client_uids = {
                    takeoff.uid
                    for takeoff in second_local_completion.bid_data_by_bid[
                        bid_uid
                    ].bid_takeoffs
                }
                self.assertEqual(first_client_uids, expected_uids)
                self.assertEqual(second_client_uids, expected_uids)
                own_second = store.poll_changes(
                    descriptor.database_id,
                    remote_first.observed_batch.delivered_through_version,
                    100,
                    session_rows[1].session_id,
                )
                self.assertIn(
                    second_operation,
                    {
                        change.transaction_id
                        for change in own_second.observed_batch.changes
                    },
                )
                self.assertEqual(own_second.remote_batch.batch.changes, ())
                first_resource = ResourceRef("takeoff", first_uid, bid_uid)
                delete_lock = store.acquire_lock(
                    descriptor.database_id,
                    session_rows[0].session_id,
                    first_resource,
                    "two-session delete convergence",
                )
                session_registries[0].register_lock(
                    descriptor.database_id,
                    delete_lock.resource,
                    delete_lock.lock_token,
                )
                delete_operation = str(uuid.uuid4())

                def delete_first(recorder):
                    writers[0].verify_plan_items_exist(
                        descriptor.database_id, (first_uid,), ()
                    )
                    self.assertTrue(
                        writers[0].delete_takeoffs(descriptor.database_id, (first_uid,))
                    )
                    recorder.record(first_resource, ChangeOperation.DELETE)
                    recorder.record(collection, ChangeOperation.UPDATE)
                    return True

                try:
                    deleted = writers[0].execute(
                        DatabaseMutationRequest(
                            database_id=descriptor.database_id,
                            session_id=session_rows[0].session_id,
                            operation_id=delete_operation,
                            mutation_type=(
                                CollaborationMutationType.PLAN_ITEMS_DELETE.value
                            ),
                            request_hash="c" * 64,
                            resources=(first_resource, collection, *dependencies),
                            required_lock_tokens=session_registries[0].lock_tokens(
                                descriptor.database_id,
                                (first_resource,),
                            ),
                        ),
                        delete_first,
                    )
                finally:
                    session_registries[0].remove_lock(
                        descriptor.database_id, first_resource
                    )
                    store.release_lock(
                        descriptor.database_id,
                        session_rows[0].session_id,
                        delete_lock.lock_token,
                    )
                self.assertEqual(
                    deleted.outcome_status, MutationOutcomeStatus.COMMITTED
                )
                remote_delete = store.poll_changes(
                    descriptor.database_id,
                    own_second.observed_batch.delivered_through_version,
                    100,
                    session_rows[1].session_id,
                )
                self.assertIn(
                    delete_operation,
                    {
                        change.transaction_id
                        for change in remote_delete.remote_batch.batch.changes
                    },
                )
                self.assertEqual(
                    {
                        takeoff.uid
                        for takeoff in remote_delete.remote_batch.bid_data_by_bid[
                            bid_uid
                        ].bid_takeoffs
                    },
                    {second_uid},
                )
                stale_lock = store.acquire_lock(
                    descriptor.database_id,
                    session_rows[1].session_id,
                    first_resource,
                    "stale edit after remote delete",
                )
                session_registries[1].register_lock(
                    descriptor.database_id,
                    stale_lock.resource,
                    stale_lock.lock_token,
                )
                try:
                    stale_edit = writers[1].execute(
                        DatabaseMutationRequest(
                            database_id=descriptor.database_id,
                            session_id=session_rows[1].session_id,
                            operation_id=str(uuid.uuid4()),
                            mutation_type=(
                                CollaborationMutationType.TAKEOFF_PROPERTIES.value
                            ),
                            request_hash="d" * 64,
                            resources=(first_resource, collection, *dependencies),
                            required_lock_tokens=session_registries[1].lock_tokens(
                                descriptor.database_id,
                                (first_resource,),
                            ),
                        ),
                        lambda _recorder: writers[1].verify_plan_items_exist(
                            descriptor.database_id, (first_uid,), ()
                        ),
                    )
                finally:
                    session_registries[1].remove_lock(
                        descriptor.database_id, first_resource
                    )
                    store.release_lock(
                        descriptor.database_id,
                        session_rows[1].session_id,
                        stale_lock.lock_token,
                    )
                self.assertEqual(
                    stale_edit.outcome_status, MutationOutcomeStatus.CONFLICT
                )
            finally:
                for session in session_rows:
                    store.close_session(
                        descriptor.database_id,
                        session.session_id,
                        "integration-test-complete",
                    )

    @staticmethod
    def _drop_test_login(admin, windows_master, login):
        with admin.connection(
            SqlConnectionRequest(windows_master, database_override="master"),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute(f"DROP LOGIN [{login}]")

    @staticmethod
    def _create_test_client(database, configuration, label):
        login = f"OSTV_IT_TMP_{label}_{secrets.token_hex(6).upper()}"
        password = secrets.token_urlsafe(32)
        admin = SqlConnectionManager()
        windows_master = replace(
            configuration.location,
            authentication_mode=SqlAuthenticationMode.WINDOWS,
            username="",
            database="master",
        )
        with admin.connection(
            SqlConnectionRequest(windows_master, database_override="master"),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "DECLARE @secret nvarchar(128)=?; "
                    "DECLARE @statement nvarchar(max)=N'CREATE LOGIN "
                    f"[{login}] WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)) + "
                    "N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF'; "
                    "EXEC sys.sp_executesql @statement",
                    password,
                )
        with database.connections.connection(
            SqlConnectionRequest(
                database.location,
                password=configuration.password,
            ),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute(f"CREATE USER [{login}] FOR LOGIN [{login}]")
                apply_sql_client_permissions(cursor, login)
        client_location = replace(
            database.location,
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username=login,
        )
        descriptor = DatabaseDescriptor.for_sql_server(
            client_location,
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        return (
            descriptor,
            registry,
            _RuntimeCredentialStore(password),
            admin,
            windows_master,
            login,
        )

    def test_mutation_presents_owned_lock_across_bid_context_variants(self):
        configuration = DisposableSqlConfiguration.from_environment()
        login = f"OSTV_IT_TMP_MUTATION_{secrets.token_hex(6).upper()}"
        password = secrets.token_urlsafe(32)
        admin = SqlConnectionManager()
        windows_master = replace(
            configuration.location,
            authentication_mode=SqlAuthenticationMode.WINDOWS,
            username="",
            database="master",
        )
        with admin.connection(
            SqlConnectionRequest(windows_master, database_override="master"),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "DECLARE @secret nvarchar(128)=?; "
                    "DECLARE @statement nvarchar(max)=N'CREATE LOGIN "
                    f"[{login}] WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)) + "
                    "N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF'; "
                    "EXEC sys.sp_executesql @statement",
                    password,
                )
        try:
            with DisposableSqlDatabase(configuration) as database:
                windows_database = replace(
                    database.location,
                    authentication_mode=SqlAuthenticationMode.WINDOWS,
                    username="",
                )
                setup_stage = "opening the disposable database"
                try:
                    with database.connections.connection(
                        SqlConnectionRequest(windows_database),
                        autocommit=True,
                    ) as lease:
                        with lease.cursor() as cursor:
                            setup_stage = "seeding the bid"
                            cursor.execute(
                                "INSERT INTO [dbo].[Bids] OUTPUT INSERTED.[UID] "
                                "DEFAULT VALUES"
                            )
                            bid_uid = int(cursor.fetchone()[0])
                            setup_stage = "seeding the condition"
                            cursor.execute(
                                "INSERT INTO [dbo].[BidConditions] "
                                "([BidUID]) OUTPUT INSERTED.[UID] VALUES (?)",
                                bid_uid,
                            )
                            condition_uid = int(cursor.fetchone()[0])
                            setup_stage = "seeding the page"
                            cursor.execute(
                                "INSERT INTO [dbo].[BidPages] "
                                "([BidUID]) OUTPUT INSERTED.[UID] VALUES (?)",
                                bid_uid,
                            )
                            page_uid = int(cursor.fetchone()[0])
                            setup_stage = "creating the client user"
                            cursor.execute(f"CREATE USER [{login}] FOR LOGIN [{login}]")
                            setup_stage = "applying client permissions"
                            apply_sql_client_permissions(cursor, login)
                except DatabaseCatalogError:
                    self.fail(f"Disposable SQL setup failed while {setup_stage}.")
                client_location = replace(
                    database.location,
                    authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                    username=login,
                )
                descriptor = DatabaseDescriptor.for_sql_server(
                    client_location,
                    schema_version=SQL_SCHEMA_V1.version,
                )
                registry = DatabaseDescriptorRegistry()
                registry.register(descriptor)
                credentials = _RuntimeCredentialStore(password)
                sessions = DatabaseSessionRegistry()
                store = SqlCollaborationStore(
                    registry,
                    credentials,
                    SqlRemoteChangeReader(
                        registry,
                        credentials,
                        database.connections,
                    ),
                    database.connections,
                )
                session = store.start_session(
                    descriptor.database_id,
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    "lock-identity-client",
                    "test-machine",
                    "integration-test",
                )
                sessions.register(descriptor.database_id, session.session_id)
                bid_key = str(bid_uid)
                condition_key = str(condition_uid)
                page_key = str(page_uid)
                stored_resource = ResourceRef("takeoffs_collection", bid_key)
                requested_resource = ResourceRef(
                    "takeoffs_collection",
                    bid_key,
                    bid_uid,
                )
                dependencies = (
                    ResourceRef("condition", condition_key, bid_uid),
                    ResourceRef("page", page_key, bid_uid),
                )
                lock = store.acquire_lock(
                    descriptor.database_id,
                    session.session_id,
                    stored_resource,
                    "takeoff placement integration test",
                )
                sessions.register_lock(
                    descriptor.database_id,
                    lock.resource,
                    lock.lock_token,
                )
                writer = SqlProjectWriter(
                    registry,
                    credentials,
                    sessions,
                    database.connections,
                )

                def record_mutation(recorder):
                    new_uids = writer.insert_takeoffs(
                        descriptor.database_id,
                        bid_key,
                        [
                            InsertTakeoffSpec(
                                condition_uid=condition_key,
                                page_uid=page_key,
                                area_uid="0",
                                position=[10.0, 20.0],
                            )
                        ],
                    )
                    for new_uid in new_uids:
                        recorder.record(
                            ResourceRef("takeoff", new_uid, bid_uid),
                            ChangeOperation.CREATE,
                        )
                    recorder.record(requested_resource, ChangeOperation.UPDATE)
                    return new_uids

                operation_id = "859945fa-fbf8-4b90-bafe-735976033238"
                result = writer.execute(
                    DatabaseMutationRequest(
                        database_id=descriptor.database_id,
                        session_id=session.session_id,
                        operation_id=operation_id,
                        mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
                        request_hash="a" * 64,
                        resources=(requested_resource, *dependencies),
                        required_lock_tokens=sessions.lock_tokens(
                            descriptor.database_id,
                            (requested_resource, *dependencies),
                        ),
                    ),
                    record_mutation,
                )
                self.assertEqual(
                    result.outcome_status,
                    MutationOutcomeStatus.COMMITTED,
                    result.conflict.reason if result.conflict is not None else "",
                )
                self.assertEqual(len(result.value or ()), 1)
                self.assertIn(requested_resource, result.resulting_versions)
                with database.connections.connection(
                    SqlConnectionRequest(
                        database.location,
                        password=configuration.password,
                        read_only=True,
                    ),
                    autocommit=True,
                ) as verification:
                    with verification.cursor() as cursor:
                        cursor.execute(
                            "SELECT (SELECT COUNT(*) FROM [ostv].[ChangeTransactions] "
                            "WHERE [TransactionId]=?), (SELECT COUNT(*) FROM "
                            "[ostv].[ChangeLog] WHERE [TransactionId]=?), "
                            "(SELECT COUNT(*) FROM [dbo].[BidTakeoffs] WHERE [UID]=?)",
                            operation_id,
                            operation_id,
                            int((result.value or ())[0]),
                        )
                        self.assertEqual(tuple(cursor.fetchone()), (1, 2, 1))
                        cursor.execute(
                            "SELECT CONVERT(nvarchar(36), [TransactionId]) FROM "
                            "[ostv].[ChangeLog] WHERE [TransactionId]=?",
                            operation_id,
                        )
                        stored_transaction_ids = {
                            str(row[0]) for row in cursor.fetchall()
                        }
                        self.assertEqual(
                            {value.lower() for value in stored_transaction_ids},
                            {operation_id},
                        )
                        self.assertNotEqual(stored_transaction_ids, {operation_id})
                        cursor.execute(
                            "SELECT [OperationType], [RequestHash], "
                            "[ResultFormatVersion], [ResultPayload] FROM "
                            "[ostv].[ChangeTransactions] WHERE [TransactionId]=?",
                            operation_id,
                        )
                        marker = cursor.fetchone()
                        self.assertEqual(
                            tuple(marker)[:3],
                            (
                                CollaborationMutationType.TAKEOFF_PLACEMENT.value,
                                "a" * 64,
                                1,
                            ),
                        )
                        self.assertEqual(
                            json.loads(str(marker[3])),
                            {
                                "value_available": True,
                                "value": list(result.value or ()),
                            },
                        )
                hydrated = store.hydrate_operation(
                    descriptor.database_id,
                    operation_id,
                )
                self.assertEqual(
                    {change.transaction_id for change in hydrated.batch.changes},
                    {operation_id},
                )
                created_uid = str((result.value or ())[0])
                self.assertIn(
                    created_uid,
                    {
                        takeoff.uid
                        for takeoff in hydrated.bid_data_by_bid[bid_uid].bid_takeoffs
                    },
                )
                sessions.remove_lock(descriptor.database_id, requested_resource)
                store.release_lock(
                    descriptor.database_id,
                    session.session_id,
                    lock.lock_token,
                )
                takeoff_resource = ResourceRef("takeoff", created_uid, bid_uid)
                delete_lock = store.acquire_lock(
                    descriptor.database_id,
                    session.session_id,
                    takeoff_resource,
                    "takeoff deletion integration test",
                )
                sessions.register_lock(
                    descriptor.database_id,
                    delete_lock.resource,
                    delete_lock.lock_token,
                )
                delete_operation_id = "9b5f8bf6-f61c-48a0-b386-c8bd00ca536d"

                def delete_mutation(recorder):
                    writer.verify_plan_items_exist(
                        descriptor.database_id,
                        (created_uid,),
                        (),
                    )
                    self.assertTrue(
                        writer.delete_takeoffs(
                            descriptor.database_id,
                            [created_uid],
                        )
                    )
                    recorder.record(takeoff_resource, ChangeOperation.DELETE)
                    recorder.record(requested_resource, ChangeOperation.UPDATE)
                    return True

                delete_result = writer.execute(
                    DatabaseMutationRequest(
                        database_id=descriptor.database_id,
                        session_id=session.session_id,
                        operation_id=delete_operation_id,
                        mutation_type=(
                            CollaborationMutationType.PLAN_ITEMS_DELETE.value
                        ),
                        request_hash="b" * 64,
                        resources=(takeoff_resource, requested_resource, *dependencies),
                        required_lock_tokens=sessions.lock_tokens(
                            descriptor.database_id,
                            (takeoff_resource,),
                        ),
                    ),
                    delete_mutation,
                )
                self.assertEqual(
                    delete_result.outcome_status,
                    MutationOutcomeStatus.COMMITTED,
                )
                with database.connections.connection(
                    SqlConnectionRequest(
                        database.location,
                        password=configuration.password,
                        read_only=True,
                    ),
                    autocommit=True,
                ) as verification:
                    with verification.cursor() as cursor:
                        cursor.execute(
                            "SELECT (SELECT COUNT(*) FROM [ostv].[ChangeTransactions] "
                            "WHERE [TransactionId]=?), (SELECT COUNT(*) FROM "
                            "[ostv].[ChangeLog] WHERE [TransactionId]=?), "
                            "(SELECT COUNT(*) FROM [dbo].[BidTakeoffs] WHERE [UID]=?)",
                            delete_operation_id,
                            delete_operation_id,
                            int(created_uid),
                        )
                        self.assertEqual(tuple(cursor.fetchone()), (1, 2, 0))
                deleted_hydrated = store.hydrate_operation(
                    descriptor.database_id,
                    delete_operation_id,
                )
                self.assertEqual(
                    {
                        change.transaction_id
                        for change in deleted_hydrated.batch.changes
                    },
                    {delete_operation_id},
                )
                repeated_delete_operation_id = "5ee50afb-b47a-49b0-b9fd-a9c6b4ddc573"
                repeated_delete = writer.execute(
                    DatabaseMutationRequest(
                        database_id=descriptor.database_id,
                        session_id=session.session_id,
                        operation_id=repeated_delete_operation_id,
                        mutation_type=(
                            CollaborationMutationType.PLAN_ITEMS_DELETE.value
                        ),
                        request_hash="c" * 64,
                        resources=(takeoff_resource, requested_resource, *dependencies),
                        required_lock_tokens=sessions.lock_tokens(
                            descriptor.database_id,
                            (takeoff_resource,),
                        ),
                    ),
                    delete_mutation,
                )
                self.assertEqual(
                    repeated_delete.outcome_status,
                    MutationOutcomeStatus.CONFLICT,
                )
                self.assertIn(
                    "changed or was deleted",
                    repeated_delete.conflict.reason,
                )
                with database.connections.connection(
                    SqlConnectionRequest(
                        database.location,
                        password=configuration.password,
                        read_only=True,
                    ),
                    autocommit=True,
                ) as verification:
                    with verification.cursor() as cursor:
                        cursor.execute(
                            "SELECT COUNT(*) FROM [ostv].[ChangeTransactions] "
                            "WHERE [TransactionId]=?",
                            repeated_delete_operation_id,
                        )
                        self.assertEqual(int(cursor.fetchone()[0]), 0)
                sessions.remove_lock(descriptor.database_id, takeoff_resource)
                store.release_lock(
                    descriptor.database_id,
                    session.session_id,
                    delete_lock.lock_token,
                )
                store.close_session(
                    descriptor.database_id,
                    session.session_id,
                    "integration-test-complete",
                )
        finally:
            with admin.connection(
                SqlConnectionRequest(windows_master, database_override="master"),
                autocommit=True,
            ) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(f"DROP LOGIN [{login}]")

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
            "[SourceSessionId], [DatabaseGuid], [OperationType], [RequestHash], "
            "[ResultFormatVersion], [ResultPayload]) "
            "VALUES (?, ?, ?, N'external_test', REPLICATE('0', 64), 1, N'{}')",
            transaction_id,
            session_id,
            database_guid,
        )


if __name__ == "__main__":
    unittest.main()
