import threading
import unittest
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseMutationResult,
    DatabaseSession,
    HydratedDatabaseChangeBatch,
    PresenceMode,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationState,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.database_capability_service import (
    DatabaseCapabilityService,
)
from ost_visualizer.application.services.database_concurrency_token_service import (
    DatabaseConcurrencyTokenService,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.entity_version_reader import (
    DatabaseEntityVersionReader,
)
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.infrastructure.sql.schema_definition import LATEST_SQL_SCHEMA
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)


class _EventBus:
    def __init__(self):
        self.subscribers = {}
        self.published = []

    def subscribe(self, event, callback):
        self.subscribers.setdefault(event, []).append(callback)

    def unsubscribe(self, event, callback):
        self.subscribers.get(event, []).remove(callback)

    def publish(self, event, **payload):
        self.published.append((event, payload))
        for callback in tuple(self.subscribers.get(event, ())):
            callback(**payload)


class _PermissionProbe:
    def can_edit(self, _database_id):
        return True


class _ConflictingMutationExecutor:
    def __init__(self, conflict):
        self._conflict = conflict

    def execute(self, _request, _operation):
        return DatabaseMutationResult(success=False, conflict=self._conflict)


class _TokenReader:
    def __init__(self, resources=None):
        self.resources = resources or {}

    def read_database_versions(self, _database_id):
        return {
            resource: token
            for resource, token in self.resources.items()
            if resource.bid_uid is None
        }

    def read_bid_versions(self, _database_id, bid_uid):
        return {
            resource: token
            for resource, token in self.resources.items()
            if resource.bid_uid == int(bid_uid)
        }


class _Dispatcher:
    def dispatch(self, callback, payload=()):
        callback(payload)


class _Reconciliation:
    def __init__(self):
        self.batches = []

    def apply(self, batch):
        self.batches.append(batch)
        return True


class _RemoteReader:
    def initial_reconciliation(self, database_id, _bid_uid, checkpoint):
        return HydratedDatabaseChangeBatch(
            DatabaseChangeBatch(
                database_id,
                "",
                checkpoint,
                checkpoint,
            )
        )

    def hydrate(self, batch):
        return HydratedDatabaseChangeBatch(batch)


class _CollaborationStore:
    def __init__(self):
        self.started = threading.Event()
        self.polled = threading.Event()
        self.change_seen = threading.Event()
        self.closed = threading.Event()
        self.session_id = ""
        self.change = None

    def start_session(
        self,
        database_id,
        session_id,
        client_instance_id,
        display_name,
        machine_name,
        application_version,
    ):
        self.session_id = session_id
        self.started.set()
        return DatabaseSession(
            database_id=database_id,
            session_id=session_id,
        )

    def heartbeat(
        self,
        database_id,
        session_id,
        acknowledged_sequence,
        _bid_uid,
        _page_uid,
        _mode,
    ):
        return DatabaseSession(
            database_id=database_id,
            session_id=session_id,
            last_acknowledged_sequence=acknowledged_sequence,
        )

    def close_session(self, _database_id, _session_id, _reason):
        self.closed.set()

    def list_presence(self, *_args):
        return ()

    def list_locks(self, *_args):
        return ()

    def acquire_lock(self, *_args):
        raise AssertionError("No edit lock was requested")

    def renew_lock(self, *_args):
        raise AssertionError("No edit lock was requested")

    def release_lock(self, *_args):
        raise AssertionError("No edit lock was requested")

    def poll_changes(self, database_id, _after_sequence, _limit):
        self.polled.set()
        changes = (self.change,) if self.change is not None else ()
        if changes:
            self.change_seen.set()
        return DatabaseChangeBatch(
            database_id, "epoch", 0, 1 if changes else 0, changes
        )


class _CredentialRecoveryStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.attempts = 0
        self.failed = threading.Event()
        self.restarted = threading.Event()

    def start_session(self, *args):
        self.attempts += 1
        if self.attempts == 1:
            self.failed.set()
            raise DatabaseCatalogError("Sign in again.", credential_required=True)
        self.restarted.set()
        return super().start_session(*args)


class _LockingStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.released = []

    def acquire_lock(self, database_id, _session_id, resource, _description):
        return ResourceLock(database_id, resource, "lock-token")

    def renew_lock(self, database_id, _session_id, _lock_token):
        return ResourceLock(
            database_id,
            ResourceRef("condition", "42", 8),
            "lock-token",
        )

    def release_lock(self, database_id, session_id, lock_token):
        self.released.append((database_id, session_id, lock_token))
        return True


class _ProjectData:
    def __init__(self, database_id):
        self.bid_ref = BidRef(database_id, "8")
        self.conditions = {}
        self.areas = ()

    def get_current_bid_ref(self):
        return self.bid_ref

    def replace_condition_family(self, bid_ref, conditions, _folders):
        if bid_ref != self.bid_ref:
            return False
        self.conditions = dict(conditions)
        return True

    def replace_bid_areas(self, bid_ref, areas):
        if bid_ref != self.bid_ref:
            return False
        self.areas = tuple(areas)
        return True

    def replace_database_hierarchy(self, _file_entry):
        raise AssertionError("No hierarchy change was requested")

    def replace_remote_bid_families(self, *_args):
        return True


def _change(database_id, resource, sequence=1, source="other-session"):
    return DatabaseChange(
        sequence=sequence,
        transaction_id="transaction-1",
        source_session_id=source,
        resource=resource,
        operation=ChangeOperation.UPDATE,
        resulting_version=ConcurrencyToken(sequence.to_bytes(8, "big")),
    )


class SqlCollaborationPhase4Tests(unittest.TestCase):
    def test_collaboration_failures_classify_credentials_and_schema_read_only(self):
        credential = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.AUTHENTICATION_FAILED, "Sign in again.")
        )
        schema = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.UNSUPPORTED_SCHEMA, "Upgrade required.")
        )
        self.assertTrue(credential.credential_required)
        self.assertFalse(credential.read_only_required)
        self.assertTrue(schema.read_only_required)
        self.assertFalse(schema.credential_required)

    def test_schema_v2_has_canonical_collaboration_objects(self):
        self.assertEqual(LATEST_SQL_SCHEMA.version, 2)
        tables = {table.name: table for table in LATEST_SQL_SCHEMA.tables}
        self.assertEqual(
            set(tables),
            {
                "DatabaseMetadata",
                "SchemaMigrations",
                "Sessions",
                "Presence",
                "Locks",
                "EntityVersions",
                "ChangeLog",
                "ChangeFeedState",
            },
        )
        self.assertIn(
            "Token", {column.name for column in tables["EntityVersions"].columns}
        )
        self.assertIn("BidUID", {column.name for column in tables["Locks"].columns})
        self.assertEqual(len(LATEST_SQL_SCHEMA.checksum), 64)

    def test_entity_seed_includes_empty_bid_collections_and_annotations(self):
        sql = "\n".join(LATEST_SQL_SCHEMA.collaboration_initialization_statements)
        self.assertIn("N'annotations_collection'", sql)
        self.assertIn("FROM [dbo].[Bids]", sql)
        self.assertIn("N'projects_collection'", sql)
        self.assertIn("BidALines", sql)
        self.assertNotIn("BidComments", sql)

    def test_session_registry_tracks_owned_lock_tokens_and_clears_them(self):
        registry = DatabaseSessionRegistry()
        resource = ResourceRef("condition", "42", 8)
        registry.register("database", "session")
        registry.register_lock("database", resource, "lock-token")
        self.assertEqual(registry.lock_tokens("database", (resource,)), ("lock-token",))
        registry.remove("database", "session")
        self.assertEqual(registry.lock_tokens("database", (resource,)), ())

    def test_remote_change_during_local_edit_returns_conflict(self):
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens = DatabaseConcurrencyTokenService(_TokenReader({resource: initial}))
        tokens.load_bid("database", "8")
        tokens.begin_edit("database", (resource,))
        conflict = tokens.apply_remote_changes(
            "database", (_change("database", resource, 2),)
        )
        self.assertEqual(conflict, (resource,))
        self.assertEqual(
            tokens.expected_versions("database", (resource,))[0].expected,
            initial,
        )

    def test_authoritative_bid_reload_clears_stale_local_edit_token(self):
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        current = ConcurrencyToken(b"\x00" * 7 + b"\x02")
        reader = _TokenReader({resource: initial})
        tokens = DatabaseConcurrencyTokenService(reader)
        tokens.load_bid("database", "8")
        tokens.begin_edit("database", (resource,))
        reader.resources[resource] = current
        tokens.load_bid("database", "8")
        self.assertEqual(
            tokens.expected_versions("database", (resource,))[0].expected,
            current,
        )

    def test_resource_lock_projection_is_targeted_and_bid_delete_sees_children(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST")
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

    def test_resource_conflict_is_targeted_and_cleared_by_reconciliation(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST")
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

    def test_condition_and_area_remote_batch_merges_once(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        service = RemoteChangeReconciliationService(
            project_data, events, DatabaseConcurrencyTokenService(_TokenReader())
        )
        condition_resource = ResourceRef("condition", "42", 8)
        area_resource = ResourceRef("area", "6", 8)
        batch = DatabaseChangeBatch(
            database_id,
            "epoch",
            1,
            2,
            (
                _change(database_id, condition_resource, 1),
                _change(database_id, area_resource, 2),
            ),
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            conditions_by_bid={8: {"42": Condition(uid="42", name="Remote")}},
            condition_folders_by_bid={8: {}},
            areas_by_bid={
                8: (
                    BidArea(
                        uid="6",
                        bid_uid="8",
                        parent_uid="0",
                        name="Remote Area",
                        sequence=1,
                    ),
                )
            },
        )
        self.assertTrue(service.apply(hydrated))
        self.assertEqual(set(project_data.conditions), {"42"})
        self.assertEqual([area.uid for area in project_data.areas], ["6"])
        names = [event for event, _payload in events.published]
        self.assertEqual(names.count(AppEvents.REMOTE_CONDITIONS_CHANGED), 1)
        self.assertEqual(names.count(AppEvents.REMOTE_AREAS_CHANGED), 1)

    def test_remote_bid_change_is_acknowledged_when_no_bid_is_active(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.bid_ref = None
        service = RemoteChangeReconciliationService(
            project_data, events, DatabaseConcurrencyTokenService(_TokenReader())
        )
        batch = DatabaseChangeBatch(
            database_id,
            "epoch",
            1,
            1,
            (_change(database_id, ResourceRef("condition", "42", 8)),),
        )
        self.assertTrue(service.apply(HydratedDatabaseChangeBatch(batch)))
        self.assertEqual(events.published, [])

    def test_remote_local_edit_conflict_is_resource_scoped(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens = DatabaseConcurrencyTokenService(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        tokens.begin_edit(database_id, (resource,))
        events = _EventBus()
        service = RemoteChangeReconciliationService(
            _ProjectData(database_id), events, tokens
        )
        batch = DatabaseChangeBatch(
            database_id,
            "epoch",
            1,
            2,
            (_change(database_id, resource, 2),),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)))
        event, payload = events.published[-1]
        self.assertIs(event, AppEvents.SYNCHRONIZATION_CONFLICT)
        self.assertFalse(payload["blocks_database"])
        self.assertEqual(payload["bid_uid"], "8")

    def test_project_write_conflict_publishes_typed_event(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        events = _EventBus()
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._event_bus = events
        service._mutation_executor = _ConflictingMutationExecutor(
            SynchronizationConflict(database_id, resource, "stale update")
        )
        service._session_registry = DatabaseSessionRegistry()
        service._concurrency_tokens = DatabaseConcurrencyTokenService(_TokenReader())
        result = service._execute_database_mutation(
            database_id, (resource,), lambda _recorder: True
        )
        self.assertFalse(result.success)
        event, payload = events.published[-1]
        self.assertIs(event, AppEvents.SYNCHRONIZATION_CONFLICT)
        self.assertEqual(payload["resource_id"], "42")

    def test_coordinator_starts_only_for_sql_and_closes_session(self):
        descriptors = DatabaseDescriptorRegistry()
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=2,
        )
        access_descriptor = DatabaseDescriptor.for_access("C:/test.mdb")
        unversioned_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="EXTERNAL")
        )
        outdated_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OUTDATED"),
            schema_version=1,
        )
        descriptors.register_all(
            (
                sql_descriptor,
                access_descriptor,
                unversioned_descriptor,
                outdated_descriptor,
            )
        )
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(sql_descriptor.database_id)
        store = _CollaborationStore()
        sessions = DatabaseSessionRegistry()
        tokens = DatabaseConcurrencyTokenService(_TokenReader())
        events = _EventBus()
        healthy = threading.Event()

        def observe(database_id="", state="", **_payload):
            if database_id == sql_descriptor.database_id and state == "healthy":
                healthy.set()

        events.subscribe(AppEvents.COLLABORATION_STATE_CHANGED, observe)
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            sessions,
            tokens,
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertFalse(coordinator.start_database(access_descriptor.database_id))
        self.assertFalse(coordinator.start_database(unversioned_descriptor.database_id))
        self.assertFalse(coordinator.start_database(outdated_descriptor.database_id))
        self.assertTrue(coordinator.start_database(sql_descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        self.assertTrue(store.polled.wait(2))
        self.assertTrue(healthy.wait(2))
        coordinator.stop_database(sql_descriptor.database_id)
        self.assertTrue(store.closed.wait(2))
        self.assertEqual(sessions.get(sql_descriptor.database_id), "")
        self.assertFalse(
            any(
                thread.name.startswith("SqlCollaboration-") and thread.is_alive()
                for thread in threading.enumerate()
            )
        )
        coordinator.shutdown()

    def test_unversioned_sql_does_not_read_collaboration_versions(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="EXTERNAL")
        )
        descriptors.register(descriptor)

        class _NoConnectionManager:
            def connection(self, *_args, **_kwargs):
                raise AssertionError("unversioned SQL must not query ostv tables")

        reader = DatabaseEntityVersionReader(
            descriptors,
            object(),
            _NoConnectionManager(),
        )
        self.assertEqual(reader.read_database_versions(descriptor.database_id), {})
        self.assertEqual(reader.read_bid_versions(descriptor.database_id, "8"), {})

    def test_coordinator_suppresses_own_change_application(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=2,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CollaborationStore()
        reconciliation = _Reconciliation()
        sessions = DatabaseSessionRegistry()
        events = _EventBus()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            capabilities,
            sessions,
            DatabaseConcurrencyTokenService(_TokenReader()),
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        store.change = _change(
            descriptor.database_id,
            ResourceRef("condition", "42", 8),
            source=store.session_id,
        )
        self.assertTrue(store.change_seen.wait(3))
        coordinator.stop_database(descriptor.database_id)
        self.assertEqual(len(reconciliation.batches), 1)
        coordinator.shutdown()

    def test_reconciliation_checkpoint_advances_only_after_successful_reload(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=2,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CollaborationStore()
        events = _EventBus()
        healthy = threading.Event()

        def observe(database_id="", state="", **_payload):
            if database_id == descriptor.database_id and state == "healthy":
                healthy.set()

        events.subscribe(AppEvents.COLLABORATION_STATE_CHANGED, observe)
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            DatabaseConcurrencyTokenService(_TokenReader()),
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertIsNotNone(runtime)
        initial_checkpoint = runtime.acknowledged_sequence
        coordinator._on_reconciliation_required(
            (descriptor.database_id, runtime.generation, 25, "retention gap")
        )
        self.assertEqual(runtime.acknowledged_sequence, initial_checkpoint)
        self.assertEqual(runtime.reconciliation_high_water, 25)
        events.publish(AppEvents.DATABASE_REFRESHED, file_path=descriptor.database_id)
        self.assertEqual(runtime.acknowledged_sequence, 25)
        self.assertEqual(runtime.reconciliation_high_water, 0)
        coordinator.shutdown()

    def test_reconciliation_releases_local_edit_locks(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=2,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        sessions = DatabaseSessionRegistry()
        events = _EventBus()
        healthy = threading.Event()
        events.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED,
            lambda database_id="", state="", **_payload: (
                healthy.set()
                if database_id == descriptor.database_id and state == "healthy"
                else None
            ),
        )
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            sessions,
            DatabaseConcurrencyTokenService(_TokenReader()),
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        resource = ResourceRef("condition", "42", 8)
        self.assertTrue(
            coordinator.begin_local_edit(descriptor.database_id, (resource,))
        )
        runtime = coordinator._runtime(descriptor.database_id)
        coordinator._on_reconciliation_required(
            (descriptor.database_id, runtime.generation, 10, "conflict")
        )
        self.assertEqual(
            store.released,
            [(descriptor.database_id, store.session_id, "lock-token")],
        )
        self.assertEqual(sessions.lock_tokens(descriptor.database_id, (resource,)), ())
        self.assertEqual(runtime.owned_locks, {})
        coordinator.shutdown()

    def test_capability_reprobe_restarts_stopped_credential_worker(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=2,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CredentialRecoveryStore()
        events = _EventBus()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            DatabaseConcurrencyTokenService(_TokenReader()),
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.failed.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertIsNotNone(runtime)
        runtime.thread.join(2)
        self.assertFalse(runtime.thread.is_alive())
        events.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            file_path=descriptor.database_id,
        )
        self.assertTrue(store.restarted.wait(2))
        coordinator.shutdown()


if __name__ == "__main__":
    unittest.main()
