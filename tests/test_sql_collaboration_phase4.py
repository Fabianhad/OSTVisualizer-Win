import threading
import unittest
from contextlib import contextmanager
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG,
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
    CollaborationResourceFamily,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
    coalesced_resource_type,
)
from ost_visualizer.application.dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
)
from ost_visualizer.application.dtos.local_draft_dtos import LocalDraftConflict
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationPollingPolicy,
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
from ost_visualizer.application.services.conflict_resolution_service import (
    ConflictResolutionService,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
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
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.remote_change_reader import (
    SqlRemoteChangeReader,
)
from ost_visualizer.infrastructure.sql.collaboration_store import (
    SqlCollaborationStore,
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


class _DeniedPermissionProbe:
    def can_edit(self, _database_id):
        return False


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


def _token_service(reader=None):
    drafts = LocalDraftRegistry()
    return DatabaseConcurrencyTokenService(reader or _TokenReader(), drafts), drafts


class _Dispatcher:
    def dispatch(self, callback, payload=()):
        callback(payload)


class _DelayedLeaseDispatcher:
    def __init__(self):
        self.pending = []
        self.lease_queued = threading.Event()

    def dispatch(self, callback, payload=()):
        if callback.__name__ in {
            "_complete_lease_request",
            "_complete_runtime_lease_request",
        }:
            self.pending.append((callback, payload))
            self.lease_queued.set()
            return
        callback(payload)

    def deliver_pending(self):
        for callback, payload in tuple(self.pending):
            callback(payload)
        self.pending.clear()


class _Reconciliation:
    def __init__(self):
        self.batches = []
        self.result = True

    def apply(self, batch):
        self.batches.append(batch)
        return self.result


class _RaisingReconciliation:
    def apply(self, _batch):
        raise RuntimeError("reconciliation callback failed")


class _RemoteReader:
    def initial_reconciliation(self, database_id, _bid_uid, checkpoint):
        return HydratedDatabaseChangeBatch(
            _batch(
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
        self.initial_version = 0
        self.batch = None
        self.start_count = 0
        self.restarted = threading.Event()

    def start_session(
        self,
        database_id,
        session_id,
        client_instance_id,
        display_name,
        machine_name,
        application_version,
    ):
        self.start_count += 1
        self.session_id = session_id
        self.started.set()
        if self.start_count > 1:
            self.restarted.set()
        return DatabaseSession(
            database_id=database_id,
            session_id=session_id,
            last_acknowledged_version=self.initial_version,
        )

    def heartbeat(
        self,
        database_id,
        session_id,
        acknowledged_version,
        _bid_uid,
        _page_uid,
        _mode,
    ):
        return DatabaseSession(
            database_id=database_id,
            session_id=session_id,
            last_acknowledged_version=acknowledged_version,
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

    def poll_changes(self, database_id, _after_version, _limit):
        self.polled.set()
        if self.batch is not None:
            return self.batch
        changes = (self.change,) if self.change is not None else ()
        if changes:
            self.change_seen.set()
        high_water = changes[-1].commit_version if changes else 0
        return _batch(database_id, "epoch", 0, high_water, changes)


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


class _TransientRecoveryStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.failed_once = False

    def start_session(self, *args):
        session = super().start_session(*args)
        return session

    def heartbeat(self, *args):
        if not self.failed_once:
            self.failed_once = True
            raise DatabaseCatalogError("connection lost", retryable=True)
        return super().heartbeat(*args)


class _InvalidFeedStore(_CollaborationStore):
    def poll_changes(self, *_args):
        raise ValueError("invalid transaction marker")


class _LockingStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.released = []
        self.release_threads = []
        self.release_event = threading.Event()

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
        self.release_threads.append(threading.get_ident())
        self.release_event.set()
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
        commit_version=sequence,
        transaction_id="transaction-1",
        source_session_id=source,
        resource=resource,
        operation=ChangeOperation.UPDATE,
        resulting_version=ConcurrencyToken(sequence.to_bytes(8, "big")),
    )


def _batch(database_id, feed_epoch, minimum_version, high_water_version, changes=()):
    return DatabaseChangeBatch(
        database_id=database_id,
        feed_epoch=feed_epoch,
        minimum_valid_version=minimum_version,
        high_water_version=high_water_version,
        delivered_through_version=high_water_version,
        changes=changes,
    )


class SqlCollaborationPhase4Tests(unittest.TestCase):
    def test_feed_uses_commit_version_when_earlier_identity_commits_last(self):
        transaction_id = "00000000-0000-0000-0000-000000000012"

        class _Cursor:
            def __init__(self):
                self.statements = []
                self.last_sql = ""

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                self.statements.append(sql)
                return self

            def fetchone(self):
                if "ChangeFeedState" in self.last_sql:
                    return ("epoch", 1)
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.last_sql:
                    return (12, 1)
                raise AssertionError(f"Unexpected fetchone query: {self.last_sql}")

            def fetchall(self):
                if "CHANGETABLE" in self.last_sql:
                    return [(12, "I", transaction_id)]
                return [
                    (
                        1,
                        12,
                        transaction_id,
                        "other-session",
                        8,
                        "condition",
                        "42",
                        "update",
                        None,
                        None,
                        None,
                        "ost_visualizer",
                    )
                ]

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

        class _Connections:
            def __init__(self):
                self.cursor = _Cursor()

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                if not autocommit:
                    raise AssertionError("Feed reads must use autocommit.")
                yield type("Lease", (), {"cursor": lambda _self: self.cursor})()

        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = type(
            "Requests",
            (),
            {"request": lambda _self, _database_id, *, read_only: object()},
        )()
        store._connections = _Connections()
        batch = store.poll_changes("database", 11, 10)
        statements = " ".join(store._connections.cursor.statements)
        self.assertIn("CHANGETABLE", statements)
        self.assertNotIn("[Sequence] > ?", statements)
        marker_query = next(
            statement
            for statement in store._connections.cursor.statements
            if "CHANGETABLE" in statement
        )
        self.assertRegex(
            marker_query,
            r"ORDER BY ct\.\[SYS_CHANGE_VERSION\]$",
            "Pagination must include every transaction sharing the checkpoint version.",
        )
        change_query = next(
            statement
            for statement in store._connections.cursor.statements
            if "MarkerVersions" in statement
        )
        self.assertNotIn(
            "READPAST",
            change_query,
            "A committed transaction must never be delivered with locked rows omitted.",
        )
        self.assertEqual(batch.changes[0].sequence, 1)
        self.assertEqual(batch.changes[0].commit_version, 12)

    def test_remote_condition_and_area_hydration_uses_current_reader_contract(self):
        condition = object()
        folder = object()
        area = object()

        class _Requests:
            def request(self, database_id, *, read_only):
                if (database_id, read_only) != ("database", True):
                    raise AssertionError("Remote hydration must use a read request.")
                return object()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                if not autocommit:
                    raise AssertionError("Remote hydration must use autocommit reads.")
                yield object()

        class _Reader:
            logger = None

            def _parse_cdn_types(self, _connection):
                return {"4": object()}

            def _parse_bid_layers_for_bid(self, _connection, bid_uid):
                return {"3": object()}

            def _parse_bid_conditions_for_bid(
                self, _connection, bid_uid, layers, cdn_types, schema
            ):
                return {"42": condition}

            def _parse_bid_condition_folders_for_bid(
                self, _connection, bid_uid, schema
            ):
                return {"5": folder}

            def _parse_bid_areas_for_bid(self, _connection, bid_uid, schema):
                return {"6": area}

        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._requests = _Requests()
        remote_reader._connections = _Connections()
        remote_reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("conditions_collection", "8", 8),
                    1,
                ),
                _change(
                    "database",
                    ResourceRef("areas_collection", "8", 8),
                    2,
                ),
            ),
        )
        hydrated = remote_reader.hydrate(batch)
        self.assertEqual(hydrated.conditions_by_bid, {8: {"42": condition}})
        self.assertEqual(hydrated.condition_folders_by_bid, {8: {"5": folder}})
        self.assertEqual(hydrated.areas_by_bid, {8: (area,)})

    def test_resource_catalog_is_canonical_and_rejects_removed_aliases(self):
        self.assertEqual(len(COLLABORATION_RESOURCE_CATALOG_CHECKSUM), 64)
        self.assertNotIn("folder", COLLABORATION_RESOURCE_CATALOG)
        self.assertNotIn("folders_collection", COLLABORATION_RESOURCE_CATALOG)
        self.assertEqual(
            COLLABORATION_RESOURCE_CATALOG["condition"].family,
            CollaborationResourceFamily.CONDITIONS,
        )
        self.assertEqual(coalesced_resource_type("condition"), "conditions_collection")
        with self.assertRaisesRegex(ValueError, "Unknown collaboration resource"):
            ResourceRef("obsolete_resource", "1")

    def test_large_hierarchy_change_coalesces_to_global_hierarchy_resource(self):
        records = [
            _RecordedMutation(ResourceRef("project", str(uid)), ChangeOperation.UPDATE)
            for uid in range(451)
        ]
        self.assertEqual(
            SqlProjectWriter._coalesce_records(records),
            (
                _RecordedMutation(
                    ResourceRef("projects_collection", "database"),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_cross_bid_bulk_change_remains_bounded(self):
        records = [
            _RecordedMutation(
                ResourceRef("condition", str(uid), uid),
                ChangeOperation.UPDATE,
            )
            for uid in range(451)
        ]
        self.assertEqual(
            SqlProjectWriter._coalesce_records(records),
            (
                _RecordedMutation(
                    ResourceRef("conditions_collection", "database"),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_first_release_conflict_plan_never_auto_merges_geometry(self):
        plan = ConflictResolutionService().plan(
            LocalDraftConflict(
                draft_id="draft",
                changed_resource=ResourceRef("takeoff", "42", 8),
                draft_type="vertex_drag",
                owning_surface="plan",
            )
        )
        self.assertEqual(
            plan.actions,
            (
                ConflictResolutionAction.RELOAD,
                ConflictResolutionAction.DISCARD_DRAFT,
                ConflictResolutionAction.CANCEL_READ_ONLY,
            ),
        )

    def test_collaboration_failures_classify_credentials_and_schema_read_only(self):
        credential = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.AUTHENTICATION_FAILED, "Sign in again.")
        )
        schema = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.UNSUPPORTED_SCHEMA, "Upgrade required.")
        )
        permission = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.PERMISSION_DENIED, "Permission revoked.")
        )
        self.assertTrue(credential.credential_required)
        self.assertFalse(credential.read_only_required)
        self.assertTrue(schema.read_only_required)
        self.assertTrue(permission.read_only_required)
        self.assertFalse(schema.credential_required)

    def test_latest_schema_has_canonical_collaboration_objects(self):
        self.assertEqual(LATEST_SQL_SCHEMA.version, 4)
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
                "ExternalAdapterState",
                "ChangeTransactions",
            },
        )
        self.assertIn(
            "Token", {column.name for column in tables["EntityVersions"].columns}
        )
        self.assertIn("BidUID", {column.name for column in tables["Locks"].columns})
        self.assertEqual(
            LATEST_SQL_SCHEMA.change_tracking_tables,
            (("ostv", "ChangeTransactions"),),
        )
        feed_columns = {column.name for column in tables["ChangeFeedState"].columns}
        self.assertEqual(feed_columns, {"SingletonId", "FeedEpoch"})
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
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid("database", "8")
        draft = drafts.begin(
            draft_type="condition",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
            base_tokens=tokens.tokens_for_resources("database", (resource,)),
        )
        conflicts = drafts.conflicts_for_changes(
            "database", (_change("database", resource, 2),)
        )
        self.assertEqual(conflicts[0].draft_id, draft.draft_id)
        self.assertEqual(
            tokens.expected_versions("database", (resource,))[0].expected,
            initial,
        )

    def test_local_drafts_cannot_overlap_an_existing_dependency(self):
        condition = ResourceRef("condition", "42", 8)
        takeoff = ResourceRef("takeoff", "395", 8)
        drafts = LocalDraftRegistry()
        drafts.begin(
            draft_type="takeoff-geometry",
            database_id="database",
            bid_uid=8,
            page_uid=3,
            owning_surface="plan-view",
            affected_resources=(takeoff,),
            dependency_resources=(condition,),
        )
        with self.assertRaisesRegex(ValueError, "already owns"):
            drafts.begin(
                draft_type="condition-properties",
                database_id="database",
                bid_uid=8,
                page_uid=None,
                owning_surface="condition-dialog",
                affected_resources=(condition,),
            )

    def test_authoritative_reload_uses_current_token_after_drafts_are_cancelled(self):
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        current = ConcurrencyToken(b"\x00" * 7 + b"\x02")
        reader = _TokenReader({resource: initial})
        tokens, drafts = _token_service(reader)
        tokens.load_bid("database", "8")
        drafts.begin(
            draft_type="condition",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
            base_tokens=tokens.tokens_for_resources("database", (resource,)),
        )
        reader.resources[resource] = current
        drafts.clear_database("database")
        tokens.load_bid("database", "8")
        self.assertEqual(
            tokens.expected_versions("database", (resource,))[0].expected,
            current,
        )

    def test_new_session_reloads_bid_tokens_before_the_next_edit(self):
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        current = ConcurrencyToken(b"\x00" * 7 + b"\x02")
        reader = _TokenReader({resource: initial})
        tokens, _drafts = _token_service(reader)
        tokens.load_bid("database", "8")
        reader.resources[resource] = current
        tokens.load_database("database")
        tokens.ensure_resources_loaded("database", (resource,))
        self.assertEqual(
            tokens.expected_versions("database", (resource,))[0].expected,
            current,
        )

    def test_successful_local_save_advances_active_draft_base_token(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        current = ConcurrencyToken(b"\x00" * 7 + b"\x02")
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        drafts.begin(
            draft_type="condition",
            database_id=database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
            base_tokens=tokens.tokens_for_resources(database_id, (resource,)),
        )
        tokens.apply_result(database_id, {resource: current})
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
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

    def test_feed_blocking_resource_conflict_enters_database_conflict_state(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        tokens, drafts = _token_service()
        events = _EventBus()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        coordinator._runtimes[descriptor.database_id] = runtime
        conflicted = ResourceRef("condition", "42", 8)
        coordinator.enter_resource_conflict(
            descriptor.database_id,
            conflicted,
            "A pending remote transaction overlaps this draft.",
        )
        status = capabilities.collaboration_status(descriptor.database_id)
        self.assertEqual(status.state, SynchronizationState.CONFLICTED)
        self.assertIn(conflicted, status.conflicted_resources)
        self.assertTrue(runtime.recovery_requested)
        self.assertEqual(
            [event for event, _payload in events.published],
            [
                AppEvents.COLLABORATION_STATE_CHANGED,
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
            ],
        )
        coordinator.shutdown()

    def test_condition_and_area_remote_batch_merges_once(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        condition_resource = ResourceRef("condition", "42", 8)
        area_resource = ResourceRef("area", "6", 8)
        batch = _batch(
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

    def test_remote_events_publish_only_after_all_model_merges(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)

        def switch_active_bid(**_payload):
            project_data.bid_ref = BidRef(database_id, "9")

        events.subscribe(AppEvents.REMOTE_CONDITIONS_CHANGED, switch_active_bid)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (
                _change(database_id, ResourceRef("condition", "42", 8), 1),
                _change(database_id, ResourceRef("area", "6", 8), 2),
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
        self.assertEqual([area.uid for area in project_data.areas], ["6"])

    def test_incomplete_remote_batch_does_not_advance_tokens_or_partial_merge(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        project_data = _ProjectData(database_id)
        project_data.conditions = {"old": Condition(uid="old", name="Old")}
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (_change(database_id, resource, 2),),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)))
        self.assertEqual(set(project_data.conditions), {"old"})
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
            initial,
        )

    def test_remote_bid_change_is_acknowledged_when_no_bid_is_active(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.bid_ref = None
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            1,
            (_change(database_id, ResourceRef("condition", "42", 8)),),
        )
        self.assertTrue(service.apply(HydratedDatabaseChangeBatch(batch)))
        self.assertEqual(events.published, [])

    def test_default_layer_change_requires_controlled_reconciliation(self):
        self.assertNotIn("default_layers_collection", SUPPORTED_REMOTE_RESOURCE_TYPES)
        database_id = "database"
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            _ProjectData(database_id),
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        resource = ResourceRef("default_layers_collection", "database")
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (_change(database_id, resource, 2),),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)))
        self.assertEqual(tokens.expected_versions(database_id, (resource,)), ())

    def test_inactive_database_does_not_acknowledge_unsupported_resource(self):
        project_data = _ProjectData("other-database")
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("default_layers_collection", "database"),
                    2,
                ),
            ),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)))

    def test_remote_local_edit_conflict_is_resource_scoped(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        drafts.begin(
            draft_type="condition",
            database_id=database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
            base_tokens=tokens.tokens_for_resources(database_id, (resource,)),
        )
        events = _EventBus()
        service = RemoteChangeReconciliationService(
            _ProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        batch = _batch(
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
        service._concurrency_tokens, _drafts = _token_service()
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
            schema_version=LATEST_SQL_SCHEMA.version,
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
        tokens, drafts = _token_service()
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
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
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
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CollaborationStore()
        reconciliation = _Reconciliation()
        sessions = DatabaseSessionRegistry()
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            capabilities,
            sessions,
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
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
            schema_version=LATEST_SQL_SCHEMA.version,
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
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertIsNotNone(runtime)
        initial_checkpoint = runtime.acknowledged_version
        events.published.clear()
        coordinator._on_reconciliation_required(
            (descriptor.database_id, runtime.generation, "retention gap")
        )
        self.assertEqual(runtime.acknowledged_version, initial_checkpoint)
        self.assertEqual(
            [event for event, _payload in events.published],
            [
                AppEvents.COLLABORATION_STATE_CHANGED,
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
                AppEvents.FULL_RECONCILIATION_REQUIRED,
            ],
        )
        store.initial_version = 25
        store.batch = _batch(descriptor.database_id, "epoch", 0, 25)
        events.publish(AppEvents.DATABASE_REFRESHED, file_path=descriptor.database_id)
        self.assertTrue(store.restarted.wait(2))
        self.assertEqual(runtime.acknowledged_version, 25)
        coordinator.shutdown()

    def test_authoritative_recovery_can_trust_a_lower_feed_version(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CollaborationStore()
        store.initial_version = 25
        store.batch = _batch(descriptor.database_id, "old-epoch", 1, 25)
        events = _EventBus()
        first_healthy = threading.Event()
        second_healthy = threading.Event()
        healthy_count = []

        def observe(database_id="", state="", **_payload):
            if database_id != descriptor.database_id or state != "healthy":
                return
            healthy_count.append(state)
            (first_healthy if len(healthy_count) == 1 else second_healthy).set()

        events.subscribe(AppEvents.COLLABORATION_STATE_CHANGED, observe)
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(first_healthy.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertEqual(runtime.observed_high_water_version, 25)
        coordinator._on_reconciliation_required(
            (descriptor.database_id, runtime.generation, "feed restored")
        )
        store.initial_version = 5
        store.batch = _batch(descriptor.database_id, "new-epoch", 1, 5)
        events.publish(AppEvents.DATABASE_REFRESHED, file_path=descriptor.database_id)
        self.assertTrue(store.restarted.wait(2))
        self.assertTrue(second_healthy.wait(1))
        self.assertEqual(runtime.acknowledged_version, 5)
        self.assertEqual(runtime.observed_high_water_version, 5)
        coordinator.shutdown()

    def test_failed_main_thread_reconciliation_does_not_acknowledge_batch(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CollaborationStore()
        reconciliation = _Reconciliation()
        events = _EventBus()
        reconciliation_required = threading.Event()
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda **_payload: reconciliation_required.set(),
        )
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertIsNotNone(runtime)
        initial_version = runtime.acknowledged_version
        reconciliation.result = False
        store.change = _change(
            descriptor.database_id,
            ResourceRef("condition", "42", 8),
            sequence=25,
        )
        self.assertTrue(reconciliation_required.wait(2))
        self.assertEqual(runtime.acknowledged_version, initial_version)
        coordinator.shutdown()

    def test_reconciliation_exception_keeps_checkpoint_and_requests_recovery(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _RaisingReconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.acknowledged_version = 7
        runtime.pending_delivery = True
        coordinator._runtimes[descriptor.database_id] = runtime
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                descriptor.database_id,
                "epoch",
                1,
                12,
                (
                    _change(
                        descriptor.database_id,
                        ResourceRef("condition", "42", 8),
                        sequence=12,
                    ),
                ),
            )
        )
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ):
            coordinator._on_remote_batch(
                (descriptor.database_id, runtime.generation, hydrated)
            )
        self.assertEqual(runtime.acknowledged_version, 7)
        self.assertTrue(runtime.recovery_requested)
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        self.assertIn(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            [event for event, _payload in events.published],
        )
        coordinator.shutdown()

    def test_retention_gap_enters_controlled_read_only_reconciliation(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CollaborationStore()
        store.initial_version = 10
        store.batch = DatabaseChangeBatch(
            database_id=descriptor.database_id,
            feed_epoch="epoch",
            minimum_valid_version=20,
            high_water_version=25,
            delivered_through_version=10,
        )
        events = _EventBus()
        reconciliation_required = threading.Event()
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda **_payload: reconciliation_required.set(),
        )
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(reconciliation_required.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertIsNotNone(runtime)
        self.assertEqual(runtime.acknowledged_version, 10)
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        coordinator.shutdown()

    def test_reconciliation_releases_local_edit_locks(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
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
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            sessions,
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        resource = ResourceRef("condition", "42", 8)
        acquired = threading.Event()
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: acquired.set() if result.granted else None,
        )
        self.assertTrue(acquired.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        coordinator._on_reconciliation_required(
            (descriptor.database_id, runtime.generation, "conflict")
        )
        self.assertTrue(store.release_event.wait(2))
        self.assertEqual(
            store.released,
            [(descriptor.database_id, store.session_id, "lock-token")],
        )
        self.assertEqual(sessions.lock_tokens(descriptor.database_id, (resource,)), ())
        self.assertEqual(runtime.owned_locks, {})
        coordinator.shutdown()

    def test_entering_conflict_releases_edit_locks_on_worker_thread(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        acquired = threading.Event()
        resource = ResourceRef("condition", "42", 8)
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: acquired.set() if result.granted else None,
        )
        self.assertTrue(acquired.wait(2))
        caller_thread = threading.get_ident()
        coordinator.enter_conflict(descriptor.database_id, "conflict")
        self.assertTrue(store.release_event.wait(2))
        self.assertNotEqual(store.release_threads[-1], caller_thread)
        coordinator.shutdown()

    def test_duplicate_release_does_not_decrement_an_unrelated_edit(self):
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            DatabaseDescriptorRegistry(),
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(DatabaseDescriptorRegistry(), _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
        )
        first = ResourceRef("condition", "42", 8)
        second = ResourceRef("condition", "43", 8)
        runtime = _DatabaseRuntime("database", 1)
        runtime.session = DatabaseSession("database", "session")
        runtime.edit_depth = 2
        runtime.mode = PresenceMode.EDITING
        runtime.owned_locks = {
            first: ResourceLock("database", first, "first-lock"),
            second: ResourceLock("database", second, "second-lock"),
        }
        runtime.draft_ids = {
            frozenset((first,)): "first-draft",
            frozenset((second,)): "second-draft",
        }
        runtime.release_requests.put((first,))
        coordinator._process_release_requests(runtime)
        runtime.release_requests.put((first,))
        coordinator._process_release_requests(runtime)
        self.assertEqual(runtime.edit_depth, 1)
        self.assertEqual(runtime.mode, PresenceMode.EDITING)
        self.assertIn(second, runtime.owned_locks)
        coordinator.shutdown()

    def test_database_stop_releases_active_lease_and_publishes_loss(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        events = _EventBus()
        lease_lost = threading.Event()
        events.subscribe(AppEvents.EDIT_LEASE_LOST, lambda **_payload: lease_lost.set())
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        acquired = threading.Event()
        resource = ResourceRef("condition", "42", 8)
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: acquired.set() if result.granted else None,
        )
        self.assertTrue(acquired.wait(2))
        coordinator.stop_database(descriptor.database_id)
        self.assertTrue(store.release_event.is_set())
        self.assertTrue(lease_lost.is_set())
        coordinator.shutdown()

    def test_stopped_database_cannot_deliver_a_stale_lease_grant(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        store = _LockingStore()
        dispatcher = _DelayedLeaseDispatcher()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            dispatcher,
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        results = []
        coordinator.request_local_edit(
            descriptor.database_id,
            (ResourceRef("condition", "42", 8),),
            results.append,
        )
        self.assertTrue(dispatcher.lease_queued.wait(2))
        coordinator.stop_database(descriptor.database_id)
        dispatcher.deliver_pending()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].granted)
        coordinator.shutdown()

    def test_trust_loss_cannot_deliver_a_stale_lease_grant(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        store = _LockingStore()
        dispatcher = _DelayedLeaseDispatcher()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            dispatcher,
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        results = []
        coordinator.request_local_edit(
            descriptor.database_id,
            (ResourceRef("condition", "42", 8),),
            results.append,
        )
        self.assertTrue(dispatcher.lease_queued.wait(2))
        coordinator.enter_conflict(descriptor.database_id, "trust lost")
        self.assertTrue(store.release_event.wait(2))
        dispatcher.deliver_pending()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].granted)
        coordinator.shutdown()

    def test_sql_lease_request_denies_when_collaboration_is_not_editable(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        self.assertTrue(capabilities.mark_connected(descriptor.database_id))
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session")
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        coordinator.request_local_edit(
            descriptor.database_id,
            (ResourceRef("condition", "42", 8),),
            results.append,
        )
        coordinator._process_edit_requests(runtime)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].granted)
        self.assertEqual(runtime.owned_locks, {})
        coordinator.shutdown()

    def test_sql_edit_lease_is_acquired_and_released_on_worker_thread(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        store.acquire_thread = None
        original_acquire = store.acquire_lock
        original_release = store.release_lock

        def acquire(*args):
            store.acquire_thread = threading.get_ident()
            return original_acquire(*args)

        def release(*args):
            result = original_release(*args)
            store.release_event.set()
            return result

        store.acquire_lock = acquire
        store.release_lock = release
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        resource = ResourceRef("condition", "42", 8)
        completed = threading.Event()
        results = []
        caller_thread = threading.get_ident()
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: (results.append(result), completed.set()),
        )
        self.assertTrue(completed.wait(2))
        self.assertTrue(results[0].granted)
        self.assertNotEqual(store.acquire_thread, caller_thread)
        coordinator.end_local_edit(descriptor.database_id, (resource,))
        self.assertTrue(store.release_event.wait(2))
        coordinator.shutdown()

    def test_capability_reprobe_restarts_stopped_credential_worker(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CredentialRecoveryStore()
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
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

    def test_heartbeat_reprobes_permissions_for_a_healthy_session(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        store = _CollaborationStore()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _DeniedPermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session")
        runtime.healthy = True
        with self.assertRaisesRegex(DatabaseCatalogError, "permissions") as failure:
            coordinator._heartbeat(runtime)
        self.assertTrue(failure.exception.read_only_required)
        coordinator.shutdown()

    def test_retryable_disconnect_creates_a_new_trusted_session(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _TransientRecoveryStore()
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            LATEST_SQL_SCHEMA.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
                reconnect_backoff_seconds=(0.05,),
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.restarted.wait(2))
        self.assertEqual(store.start_count, 2)
        self.assertEqual(coordinator.metrics(descriptor.database_id).reconnect_count, 1)
        coordinator.shutdown()

    def test_invalid_feed_enters_controlled_reconciliation(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=LATEST_SQL_SCHEMA.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        events = _EventBus()
        reconciliation_required = threading.Event()
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda **_payload: reconciliation_required.set(),
        )
        tokens, drafts = _token_service()
        coordinator = SqlCollaborationCoordinator(
            descriptors,
            _InvalidFeedStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            LATEST_SQL_SCHEMA.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(reconciliation_required.wait(2))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        coordinator.shutdown()


if __name__ == "__main__":
    unittest.main()
