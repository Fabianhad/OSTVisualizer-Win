from tests.helpers.sql.collaboration import (
    SQL_SCHEMA_V1,
    DatabaseCapabilityService,
    DatabaseDescriptor,
    DatabaseDescriptorRegistry,
    DatabaseSessionRegistry,
    SqlServerDatabaseLocation,
    _CollaborationStore,
    _coordinator,
    _Dispatcher,
    _EventBus,
    _PermissionProbe,
    _Reconciliation,
    _RemoteReader,
    _shutdown_coordinator,
    _token_service,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from unittest.mock import Mock, patch
import unittest
import threading
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DatabaseSession,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PendingMutationState,
    PendingSqlOperationRecord,
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
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
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.application.services.pending_mutation_registry import (
    PendingMutationRegistry,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
    _QueuedMutation,
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
from tests.helpers.sql.collaboration import (
    _AlwaysUnavailableStore,
    _BatchAcquireFailureStore,
    _BlockedPollStore,
    _BlockingDraftRegistry,
    _COORDINATOR_TYPE,
    _CollaborationStore,
    _CredentialRecoveryStore,
    _DeferredProjectionReconciliation,
    _DelayedLeaseDispatcher,
    _DelayedMutationDispatcher,
    _DelayedReconciliationDispatcher,
    _DeniedPermissionProbe,
    _Dispatcher,
    _EventBus,
    _FailFirstLocalProjectionReconciliation,
    _FailedCloseStore,
    _FailingPendingOperationJournal,
    _FailingUnsubscribeEventBus,
    _InvalidCommittedHydrationStore,
    _InvalidFeedStore,
    _LockingStore,
    _PendingOperationJournal,
    _PermissionProbe,
    _RaisingReconciliation,
    _Reconciliation,
    _RecoverableProjectionStore,
    _ReleaseFailsCloseSucceedsStore,
    _RemoteReader,
    _TokenReader,
    _TransientRecoveryStore,
    _UnexpectedPollFailureStore,
    _batch,
    _change,
    _committed_execution,
    _coordinator,
    _queue_test_mutation,
    _shutdown_coordinator,
    _stop_database,
    _token_service,
)
from ost_visualizer.application.dtos.collaboration_dtos import SynchronizationState
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DurableOperationResult,
    MutationOutcomeStatus,
    PageSettingsPayload,
    PendingMutationState,
    PendingSqlOperationRecord,
    PlanPropertyPayload,
    ProjectImportPayload,
    ProjectWritePayload,
    QueuedMutationRequest,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
)


class SqlCollaborationStartupCancellationTests(unittest.TestCase):
    def test_late_startup_result_does_not_start_more_work(self):
        for outcome in ("committed", "cancelled", "os_error", "login_timeout"):
            with self.subTest(outcome=outcome):
                entered = threading.Event()
                release = threading.Event()
                finished = threading.Event()

                class Store(_CollaborationStore):
                    def start_session(self, *args, **kwargs):
                        entered.set()
                        if not release.wait(5):
                            raise AssertionError("Startup probe was not released")
                        if outcome == "cancelled":
                            return None
                        if outcome == "os_error":
                            raise OSError("connection failed after stop")
                        if outcome == "login_timeout":
                            raise SqlInfrastructureError(
                                SqlErrorDetails(SqlErrorCode.TIMEOUT, "Login timed out")
                            )
                        return super().start_session(*args, **kwargs)

                descriptors = DatabaseDescriptorRegistry()
                descriptor = DatabaseDescriptor.for_sql_server(
                    SqlServerDatabaseLocation(server="localhost", database="TEST"),
                    schema_version=SQL_SCHEMA_V1.version,
                )
                descriptors.register(descriptor)
                store = Store()
                tokens, drafts = _token_service()
                reader = _RemoteReader()
                coordinator = _coordinator(
                    descriptors,
                    store,
                    reader,
                    _Dispatcher(),
                    _Reconciliation(),
                    DatabaseCapabilityService(descriptors, _PermissionProbe()),
                    DatabaseSessionRegistry(),
                    tokens,
                    drafts,
                    _EventBus(),
                    SQL_SCHEMA_V1.version,
                )
                try:
                    with (
                        patch.object(
                            tokens, "load_database", wraps=tokens.load_database
                        ) as load,
                        patch.object(
                            reader,
                            "initial_reconciliation",
                            wraps=reader.initial_reconciliation,
                        ) as hydrate,
                        patch.object(coordinator, "_on_session_started") as started,
                        patch.object(
                            store, "start_session", wraps=store.start_session
                        ) as connect,
                    ):
                        self.assertTrue(
                            coordinator.start_database(descriptor.database_id)
                        )
                        self.assertTrue(entered.wait(2))
                        coordinator.request_shutdown(lambda *_: finished.set())
                        self.assertFalse(finished.is_set())
                        release.set()
                        self.assertTrue(finished.wait(2))
                        self.assertEqual(connect.call_count, 1)
                        load.assert_not_called()
                        hydrate.assert_not_called()
                        started.assert_not_called()
                        self.assertFalse(store.polled.is_set())
                        self.assertEqual(store.closed.is_set(), outcome == "committed")
                finally:
                    release.set()
                    _shutdown_coordinator(coordinator)


class _SqlCollaborationCoordinatorCollaborationFixture(unittest.TestCase):
    pass


class SqlCollaborationCoordinatorCollaborationTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator: lifecycle and combined contracts."""

    def test_local_projection_failure_keeps_exception_diagnostic(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _RaisingReconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        result = QueuedMutationResult(
            database_id=descriptor.database_id,
            runtime_generation=runtime.generation,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as captured:
            coordinator._apply_local_mutation_result(
                (results.append, result, object(), runtime.session_generation, None)
            )
        self.assertIn(
            "SQL local-completion reconciliation failed",
            captured.output[0],
        )
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        _shutdown_coordinator(coordinator)

    def test_granted_lease_is_released_when_ui_callback_fails(self):
        resource = ResourceRef("condition", "11", 7)
        lock = ResourceLock("sql-db", resource, "lock-token")
        handle = EditLeaseHandle(
            database_id="sql-db",
            draft_id="draft-1",
            runtime_generation=3,
            operation_id="edit-condition",
            owning_surface="condition-sidebar",
            resources=(resource,),
            locks=(lock,),
        )
        runtime = _DatabaseRuntime("sql-db", 3)
        runtime.draft_ids[frozenset((resource.lease_identity,))] = handle.draft_id
        coordinator = SqlCollaborationCoordinator.__new__(SqlCollaborationCoordinator)
        coordinator._shutting_down = False
        coordinator._runtime = lambda database_id, generation=None: (
            runtime if database_id == "sql-db" and generation in (None, 3) else None
        )
        released = []
        coordinator.end_edit_lease = released.append

        def broken_callback(_result):
            raise RuntimeError("closed editor")

        coordinator._complete_runtime_lease_request(
            (
                "sql-db",
                3,
                handle.draft_id,
                broken_callback,
                EditLeaseResult(True, handle=handle),
            )
        )
        self.assertEqual(released, [handle])

    def test_immediate_lease_callback_failure_is_contained(self):
        result = EditLeaseResult(False, "not available")
        with patch(
            "ost_visualizer.application.services."
            "sql_collaboration_coordinator.logger.exception"
        ) as logged:
            SqlCollaborationCoordinator._complete_lease_request(
                (
                    lambda _result: (_ for _ in ()).throw(
                        RuntimeError("UI callback failed")
                    ),
                    result,
                )
            )
        logged.assert_called_once_with(
            "SQL immediate edit-lease completion callback failed"
        )

    def test_queued_geometry_consumes_existing_edit_lease_without_reacquiring(self):
        resource = ResourceRef("takeoff", "42", 8)
        dependency = ResourceRef("page", "20", 8)
        lock = ResourceLock("database", resource, "lock-token")
        drafts = LocalDraftRegistry()
        draft = drafts.begin(
            draft_type="takeoffs_gesture",
            database_id="database",
            bid_uid=8,
            page_uid=20,
            owning_surface="main-plan",
            affected_resources=(resource,),
            dependency_resources=(dependency,),
            operation_id="gesture-operation",
        )
        drafts.activate(draft.draft_id, (lock,), runtime_generation=4)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id=draft.draft_id,
            runtime_generation=4,
            operation_id="gesture-operation",
            owning_surface="main-plan",
            resources=(resource,),
            dependency_resources=(dependency,),
            locks=(lock,),
        )
        runtime = _DatabaseRuntime("database", 4)
        runtime.session = DatabaseSession("database", "session")
        resource_key = frozenset((resource.lease_identity,))
        runtime.draft_ids[resource_key] = draft.draft_id
        runtime.owned_locks[resource.lease_identity] = lock
        runtime.edit_depth = 1
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            owning_surface="main-plan",
            resources=(resource,),
            dependency_resources=(dependency,),
            payload={"takeoff_uid": "42"},
        )
        queued = _QueuedMutation(
            database_id="database",
            runtime_generation=4,
            operation_id=request.operation_id,
            owning_surface="main-plan",
            resources=(resource,),
            dependency_resources=(dependency,),
            operation=lambda: _committed_execution(),
            callback=lambda _result: None,
            typed_request=request,
            edit_lease_handle=handle,
        )
        released = []
        coordinator = SqlCollaborationCoordinator.__new__(SqlCollaborationCoordinator)
        coordinator._local_drafts = drafts
        coordinator._sessions = SimpleNamespace(
            remove_lock=lambda database_id, removed: released.append(
                ("session", database_id, removed)
            )
        )
        coordinator._store = SimpleNamespace(
            release_lock=lambda database_id, session_id, token: released.append(
                ("store", database_id, session_id, token)
            )
        )
        self.assertIs(
            coordinator._validated_mutation_edit_lease(runtime, queued, handle),
            drafts.get(draft.draft_id),
        )
        self.assertIsNone(
            coordinator._consume_mutation_edit_lease(
                runtime,
                runtime.session,
                handle,
                (lock.lock_token,),
            )
        )
        self.assertIsNone(drafts.get(draft.draft_id))
        self.assertEqual(runtime.draft_ids, {})
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.edit_depth, 0)
        self.assertEqual(runtime.mode, PresenceMode.VIEWING)
        self.assertEqual(
            released,
            [
                ("session", "database", resource),
            ],
        )

    def test_condition_editor_lease_can_transfer_one_owned_navigable_condition(self):
        edited = ResourceRef("condition", "42", 8)
        navigable = ResourceRef("condition", "43", 8)
        edited_lock = ResourceLock("database", edited, "edited-token")
        navigable_lock = ResourceLock("database", navigable, "navigable-token")
        drafts = LocalDraftRegistry()
        draft = drafts.begin(
            draft_type="conditions_editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="condition-sidebar",
            affected_resources=(edited, navigable),
            operation_id="edit-condition-dialog",
        )
        drafts.activate(
            draft.draft_id,
            (edited_lock, navigable_lock),
            runtime_generation=4,
        )
        handle = EditLeaseHandle(
            database_id="database",
            draft_id=draft.draft_id,
            runtime_generation=4,
            operation_id="edit-condition-dialog",
            owning_surface="condition-sidebar",
            resources=(edited, navigable),
            locks=(edited_lock, navigable_lock),
        )
        runtime = _DatabaseRuntime("database", 4)
        runtime.draft_ids[
            frozenset((edited.lease_identity, navigable.lease_identity))
        ] = draft.draft_id
        runtime.owned_locks = {
            edited.lease_identity: edited_lock,
            navigable.lease_identity: navigable_lock,
        }
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE,
            owning_surface="condition-sidebar",
            resources=(edited,),
            payload={"condition_uid": "42"},
            edit_lease_handle=handle,
        )
        queued = _QueuedMutation(
            database_id="database",
            runtime_generation=4,
            operation_id=request.operation_id,
            owning_surface="condition-sidebar",
            resources=request.resources,
            dependency_resources=(),
            operation=lambda: _committed_execution(),
            callback=lambda _result: None,
            typed_request=request,
            edit_lease_handle=handle,
        )
        coordinator = SqlCollaborationCoordinator.__new__(SqlCollaborationCoordinator)
        coordinator._local_drafts = drafts
        self.assertIs(
            coordinator._validated_mutation_edit_lease(runtime, queued, handle),
            drafts.get(draft.draft_id),
        )

    def test_feed_blocking_resource_conflict_enters_database_conflict_state(self):
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
        tokens, drafts = _token_service()
        events = _EventBus()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        self.assertEqual(
            status.message,
            "A pending remote transaction overlaps this draft.",
        )
        self.assertIn(conflicted, status.conflicted_resources)
        self.assertTrue(runtime.recovery_requested)
        self.assertEqual(
            [event for event, _payload in events.published],
            [
                AppEvents.COLLABORATION_STATE_CHANGED,
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
            ],
        )
        _shutdown_coordinator(coordinator)

    def test_self_change_checkpoint_waits_for_main_thread_reconciliation_gate(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _CollaborationStore()
        store.change = _change(
            descriptor.database_id,
            ResourceRef("condition", "42", 8),
            source="session",
        )
        dispatcher = _DelayedReconciliationDispatcher()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session")
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._poll_once(runtime)
        self.assertEqual(runtime.acknowledged_version, 0)
        self.assertTrue(runtime.pending_delivery)
        dispatcher.deliver_pending()
        self.assertEqual(runtime.acknowledged_version, 1)
        self.assertFalse(runtime.pending_delivery)
        coordinator._runtimes.clear()
        _shutdown_coordinator(coordinator)

    def test_malformed_session_start_has_distinct_failure_classification(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        reconciliation = _Reconciliation()
        reconciliation.result = False
        reconciliation.failure_kind = ReconciliationFailureKind.MALFORMED_PAYLOAD
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._on_session_started(
            (
                descriptor.database_id,
                runtime.generation,
                runtime.session_generation,
                HydratedDatabaseChangeBatch(
                    _batch(descriptor.database_id, "epoch", 0, 0)
                ),
                None,
            )
        )
        failure_payload = next(
            payload
            for event, payload in events.published
            if event is AppEvents.FULL_RECONCILIATION_REQUIRED
        )
        self.assertIn("session-start", failure_payload["reason"])
        _shutdown_coordinator(coordinator)

    def test_queued_mutation_can_be_cancelled_before_worker_execution(self):
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
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        calls = []
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: calls.append(True) or _committed_execution("501"),
            results.append,
            operation_id="cancel-placement",
        )
        operation_id = coordinator._pending_mutations.for_database(
            descriptor.database_id
        )[0].request.operation_id
        self.assertTrue(
            coordinator.cancel_queued_mutation(descriptor.database_id, operation_id)
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.CANCELLED_BEFORE_START],
        )
        self.assertEqual(
            coordinator._pending_mutations.for_database(descriptor.database_id), ()
        )
        _shutdown_coordinator(coordinator)

    def test_queued_mutation_capacity_rejects_only_the_sixty_fifth_request(self):
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
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(
            database_id=descriptor.database_id,
            session_id="session-1",
            last_acknowledged_version=7,
        )
        runtime.established = True
        runtime.healthy = False
        runtime.pending_delivery = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        for index in range(65):
            _queue_test_mutation(
                coordinator,
                descriptor.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda index=index: _committed_execution(str(501 + index)),
                results.append,
                expected_id_count=1,
                operation_id=f"placement-{index}",
                owning_surface="main-plan",
            )
        self.assertEqual(runtime.mutation_requests.qsize(), 64)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome_status, MutationOutcomeStatus.REJECTED)
        uuid.UUID(results[0].operation_id)
        self.assertIn("queue is full", results[0].message.lower())
        self.assertNotIn("stopped", results[0].message.lower())
        _shutdown_coordinator(coordinator)

    def test_queue_rejects_mutation_when_initial_journal_write_fails(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        pending = PendingMutationRegistry()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
            operation_journal=_FailingPendingOperationJournal(1),
        )
        results = []
        sequence = _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: _committed_execution("501"),
            results.append,
            expected_id_count=1,
            operation_id="journal-initial-failure",
            owning_surface="main-plan",
        )
        self.assertEqual(sequence, -1)
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.REJECTED,
        )
        self.assertIn("recorded safely", results[0].message)
        self.assertEqual(pending.for_database(descriptor.database_id), ())
        _shutdown_coordinator(coordinator)

    def test_recovered_commit_projects_while_editing_is_temporarily_disabled(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        pending = PendingMutationRegistry()
        journal = _PendingOperationJournal()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
            operation_journal=journal,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        coordinator._runtimes[descriptor.database_id] = runtime
        request = QueuedMutationRequest(
            database_id=descriptor.database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoffs_collection", "8", 8),),
            payload={"test_operation": "recovered-projection"},
        )
        pending.begin(request, runtime_generation=runtime.generation)
        pending.transition(request.operation_id, PendingMutationState.RECOVERING)
        pending.transition(request.operation_id, PendingMutationState.PROJECTING)
        journal.save(
            PendingSqlOperationRecord.from_request(
                request,
                PendingMutationState.PROJECTING,
            )
        )
        results = []
        coordinator._complete_mutation_request(
            (
                results.append,
                QueuedMutationResult(
                    database_id=descriptor.database_id,
                    runtime_generation=runtime.generation,
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    created_resource_ids=("501",),
                    commit_attempted=True,
                ),
            )
        )
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED],
        )
        self.assertEqual(pending.for_database(descriptor.database_id), ())
        self.assertEqual(journal.records, {})
        _shutdown_coordinator(coordinator)

    def test_committed_projection_failure_without_runtime_still_notifies_ui(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            SQL_SCHEMA_V1.version,
        )
        coordinator._request_committed_projection_recovery(
            descriptor.database_id,
            "The committed projection could not be attached to a runtime.",
        )
        self.assertEqual(
            [
                payload
                for event, payload in events.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            [
                {
                    "database_id": descriptor.database_id,
                    "reason": (
                        "The committed projection could not be attached to a runtime."
                    ),
                }
            ],
        )
        _shutdown_coordinator(coordinator)

    def test_recovered_completion_waits_for_its_exact_session(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        pending = PendingMutationRegistry()
        journal = _PendingOperationJournal()
        store = _RecoverableProjectionStore()
        dispatcher = _DelayedMutationDispatcher()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
            operation_journal=journal,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        first_session_generation = coordinator._install_session(
            runtime,
            DatabaseSession(descriptor.database_id, "session-1"),
        )
        coordinator._runtimes[descriptor.database_id] = runtime
        request = QueuedMutationRequest(
            database_id=descriptor.database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoffs_collection", "8", 8),),
            payload={"test_operation": "session-scoped-recovery"},
        )
        pending.begin(request, runtime_generation=runtime.generation)
        pending.transition(request.operation_id, PendingMutationState.RECOVERING)
        journal.save(
            PendingSqlOperationRecord.from_request(
                request,
                PendingMutationState.RECOVERING,
            )
        )
        results = []
        coordinator._uncertain_callbacks[request.operation_id] = (
            request,
            results.append,
        )
        store.durable_results[request.operation_id] = DurableOperationResult(
            database_id=descriptor.database_id,
            operation_id=request.operation_id,
            found=True,
            mutation_type=request.mutation_type.value,
            request_hash=request.request_hash,
            result_format_version=1,
            result_payload=json.dumps(
                {"value": ["501"], "value_available": True},
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(descriptor.database_id, "epoch", 0, 0)
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                descriptor.database_id,
                runtime.generation,
                first_session_generation,
                hydrated,
                None,
            )
        )
        second_session_generation = coordinator._install_session(
            runtime,
            DatabaseSession(descriptor.database_id, "session-2"),
        )
        dispatcher.deliver_pending()
        self.assertEqual(results, [])
        self.assertIsNotNone(pending.get(request.operation_id))
        self.assertIn(request.operation_id, coordinator._uncertain_callbacks)
        self.assertIn(request.operation_id, journal.records)
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                descriptor.database_id,
                runtime.generation,
                second_session_generation,
                hydrated,
                None,
            )
        )
        dispatcher.deliver_pending()
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED],
        )
        self.assertIsNone(pending.get(request.operation_id))
        self.assertNotIn(request.operation_id, coordinator._uncertain_callbacks)
        self.assertNotIn(request.operation_id, journal.records)
        _shutdown_coordinator(coordinator)

    def test_recovered_operation_rejects_non_authoritative_identity_sets(self):
        request = QueuedMutationRequest(
            database_id="database",
            operation_id="b4d0e10f-1547-4c68-8a42-4526fd23a188",
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoffs_collection", "8", 8),),
        )
        malformed_values = (
            None,
            "501",
            [None],
            ["501", "501"],
            {
                "takeoff_uids": {"preview-1": None},
                "annotation_uids": {},
                "condition_uids": {},
            },
            {
                "takeoff_uids": {"preview-1": "501", "preview-2": "501"},
                "annotation_uids": {},
                "condition_uids": {},
            },
        )
        for value in malformed_values:
            with self.subTest(value=value):
                durable = DurableOperationResult(
                    database_id="database",
                    operation_id=request.operation_id,
                    found=True,
                    mutation_type=request.mutation_type.value,
                    request_hash=request.request_hash,
                    result_format_version=1,
                    result_payload=json.dumps(
                        {"value": value, "value_available": True},
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                )
                self.assertIsNone(
                    SqlCollaborationCoordinator._recovered_authoritative_result(
                        request, durable
                    )
                )

    def test_lifecycle_drain_waits_for_critical_mutation_completion(self):
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
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        mutation_results = []
        drain_results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: _committed_execution("501"),
            mutation_results.append,
            operation_id="critical-drain",
        )
        coordinator.drain_database_mutations_async(
            descriptor.database_id,
            lambda success, message: drain_results.append((success, message)),
        )
        self.assertEqual(drain_results, [])
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(
            [result.outcome_status for result in mutation_results],
            [MutationOutcomeStatus.COMMITTED],
        )
        self.assertEqual(drain_results, [(True, "")])
        _shutdown_coordinator(coordinator)

    def test_lifecycle_drain_ignores_noncritical_view_state(self):
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
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("page", "107", 8),),
            lambda: _committed_execution("501"),
            lambda _result: None,
            operation_id="noncritical-view-state",
            lifecycle_critical=False,
        )
        coordinator.drain_database_mutations_async(
            descriptor.database_id,
            lambda success, message: results.append((success, message)),
        )
        self.assertEqual(results, [(True, "")])
        coordinator._process_mutation_requests(runtime)
        _shutdown_coordinator(coordinator)

    def test_queued_mutation_release_value_error_finishes_draft_and_all_locks(self):
        class _ValueErrorReleaseStore(_LockingStore):
            def release_lock(self, database_id, session_id, lock_token):
                super().release_lock(database_id, session_id, lock_token)
                if lock_token == "first":
                    raise ValueError("lock ownership changed")

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _ValueErrorReleaseStore()
        sessions = DatabaseSessionRegistry()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            sessions,
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        resource_a = ResourceRef("takeoff", "1", 8)
        resource_b = ResourceRef("takeoff", "2", 8)
        draft = drafts.begin(
            draft_type="takeoffs_mutation",
            database_id=descriptor.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="main-plan",
            affected_resources=(resource_a, resource_b),
            dependency_resources=(),
            operation_id="placement",
        )
        session = DatabaseSession(descriptor.database_id, "session")
        locks = (
            ResourceLock(descriptor.database_id, resource_a, "first"),
            ResourceLock(descriptor.database_id, resource_b, "second"),
        )
        for lock in locks:
            sessions.register_lock(
                descriptor.database_id, lock.resource, lock.lock_token
            )
        failure = coordinator._release_queued_mutation_resources(
            _DatabaseRuntime(descriptor.database_id, 1),
            session,
            draft.draft_id,
            locks,
        )
        self.assertIsInstance(failure, ValueError)
        self.assertEqual([entry[2] for entry in store.released], ["first", "second"])
        self.assertEqual(drafts._drafts, {})
        self.assertEqual(
            sessions.lock_tokens(descriptor.database_id, (resource_a, resource_b)), ()
        )
        _shutdown_coordinator(coordinator)

    def test_new_session_clears_previous_session_pending_delivery(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-before")
        runtime.session_generation = 1
        runtime.acknowledged_version = 7
        runtime.observed_high_water_version = 12
        runtime.feed_epoch = "old-epoch"
        runtime.pending_delivery = True
        runtime.healthy = True
        session_generation = coordinator._install_session(
            runtime,
            DatabaseSession(
                descriptor.database_id,
                "session-after",
                last_acknowledged_version=20,
            ),
        )
        self.assertEqual(session_generation, 2)
        self.assertEqual(runtime.acknowledged_version, 20)
        self.assertEqual(runtime.observed_high_water_version, 20)
        self.assertEqual(runtime.feed_epoch, "")
        self.assertFalse(runtime.pending_delivery)
        self.assertFalse(runtime.healthy)
        _shutdown_coordinator(coordinator)

    def test_sql_lease_request_denies_when_collaboration_is_not_editable(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        self.assertTrue(capabilities.mark_connected(descriptor.database_id))
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _shutdown_coordinator(coordinator)

    def test_capability_reprobe_does_not_restart_after_failed_session_cleanup(self):
        coordinator = _coordinator(
            DatabaseDescriptorRegistry(),
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(DatabaseDescriptorRegistry(), _PermissionProbe()),
            DatabaseSessionRegistry(),
            *_token_service(),
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime("database", 1)
        runtime.thread = type(
            "StoppedThread",
            (),
            {"ident": 1, "is_alive": lambda self: False},
        )()
        coordinator._runtimes["database"] = runtime
        starts = []
        coordinator.stop_database_async = (
            lambda _database_id, _reason, callback: callback(False, "cleanup failed")
        )
        coordinator.start_database = lambda database_id: starts.append(database_id)
        coordinator._on_database_capabilities_changed("database")
        self.assertEqual(starts, [])

    def test_heartbeat_does_not_open_a_second_permission_probe_connection(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _CollaborationStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session")
        runtime.healthy = True
        coordinator._heartbeat(runtime)
        self.assertEqual(runtime.session.session_id, "session")
        _shutdown_coordinator(coordinator)

    def test_pending_edit_callback_failure_cannot_skip_worker_session_cleanup(self):
        coordinator = SqlCollaborationCoordinator.__new__(SqlCollaborationCoordinator)
        runtime = _DatabaseRuntime("database", 1)
        runtime.session = DatabaseSession("database", "session")
        removed_sessions = []
        closed_sessions = []
        coordinator._run_worker = lambda _runtime: None
        coordinator._reject_pending_edits = lambda *_args: (_ for _ in ()).throw(
            RuntimeError("Qt dispatcher unavailable")
        )
        coordinator._local_drafts = SimpleNamespace(finish=lambda _draft_id: None)
        coordinator._dispatcher = SimpleNamespace(dispatch=lambda *_args: None)
        coordinator._sessions = SimpleNamespace(
            remove=lambda database_id, session_id: removed_sessions.append(
                (database_id, session_id)
            ),
            remove_lock=lambda *_args: None,
        )
        coordinator._store = SimpleNamespace(
            close_session=lambda database_id, session_id, reason: closed_sessions.append(
                (database_id, session_id, reason)
            )
        )
        coordinator._worker(runtime)
        self.assertIsNone(runtime.session)
        self.assertEqual(removed_sessions, [("database", "session")])
        self.assertEqual(closed_sessions, [("database", "session", "closed")])
        self.assertEqual(len(runtime.cleanup_errors), 1)

    def test_lease_loss_dispatch_failure_cannot_skip_session_cleanup(self):
        coordinator = SqlCollaborationCoordinator.__new__(SqlCollaborationCoordinator)
        runtime = _DatabaseRuntime("database", 1)
        runtime.session = DatabaseSession("database", "session")
        resource = ResourceRef("takeoff", "10", bid_uid=1)
        lock = ResourceLock("database", resource, "lock-token")
        runtime.owned_locks[resource.lease_identity] = lock
        runtime.draft_ids[frozenset((resource.lease_identity,))] = "draft"
        draft = SimpleNamespace(
            draft_id="draft",
            operation_id="move",
            owning_surface="main",
            affected_resources=(resource,),
        )
        finished_drafts = []
        removed_locks = []
        closed_sessions = []
        coordinator._reject_pending_edits = lambda *_args: None
        coordinator._local_drafts = SimpleNamespace(
            get=lambda draft_id: draft if draft_id == "draft" else None,
            finish=lambda draft_id: finished_drafts.append(draft_id),
        )
        coordinator._dispatcher = SimpleNamespace(
            dispatch=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("Qt dispatcher unavailable")
            )
        )
        coordinator._sessions = SimpleNamespace(
            remove=lambda *_args: None,
            remove_lock=lambda database_id, removed_resource: removed_locks.append(
                (database_id, removed_resource)
            ),
        )
        coordinator._store = SimpleNamespace(
            release_lock=lambda *_args: True,
            close_session=lambda database_id, session_id, reason: closed_sessions.append(
                (database_id, session_id, reason)
            ),
        )
        coordinator._reset_session(runtime, close_reason="closed")
        self.assertIsNone(runtime.session)
        self.assertEqual(finished_drafts, ["draft"])
        self.assertEqual(removed_locks, [("database", resource)])
        self.assertEqual(closed_sessions, [("database", "session", "closed")])
        self.assertEqual(len(runtime.cleanup_errors), 1)

    def test_shutdown_reports_unsubscribe_failure_after_attempting_all_events(self):
        event_bus = _FailingUnsubscribeEventBus()
        coordinator = _coordinator(
            DatabaseDescriptorRegistry(),
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(DatabaseDescriptorRegistry(), _PermissionProbe()),
            DatabaseSessionRegistry(),
            *_token_service(),
            event_bus,
            SQL_SCHEMA_V1.version,
        )
        results = []
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ):
            coordinator.request_shutdown(
                lambda success, message: results.append((success, message))
            )
        self.assertEqual(
            event_bus.unsubscribe_attempts,
            [
                AppEvents.FILE_OPENED,
                AppEvents.FILE_UNLOADED,
                AppEvents.DATABASE_REFRESHED,
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
            ],
        )
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0][0])
        self.assertIn("event unsubscription failed", results[0][1])
        self.assertEqual(
            coordinator.shutdown_state,
            CollaborationShutdownState.CLEANUP_FAILED,
        )

    def test_database_drain_reports_a_worker_that_exceeds_sql_timeouts(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="localhost",
                database="TEST",
                connection_timeout_seconds=2,
                command_timeout_seconds=3,
            ),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            *_token_service(),
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )

        class _StuckThread:
            def __init__(self):
                self.join_timeout = None

            def join(self, timeout):
                self.join_timeout = timeout

            @staticmethod
            def is_alive():
                return True

        payloads = []
        coordinator._dispatcher = SimpleNamespace(
            dispatch=lambda _callback, payload: payloads.append(payload)
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.thread = _StuckThread()
        coordinator._drain_database(runtime)
        self.assertEqual(runtime.thread.join_timeout, 10.0)
        self.assertEqual(payloads[0][:3], (descriptor.database_id, 1, False))
        self.assertIn("did not stop", payloads[0][3])

    def test_closed_shutdown_callback_runs_outside_the_coordinator_lock(self):
        coordinator = _coordinator(
            DatabaseDescriptorRegistry(),
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(DatabaseDescriptorRegistry(), _PermissionProbe()),
            DatabaseSessionRegistry(),
            *_token_service(),
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        _shutdown_coordinator(coordinator)
        callback_lock_access = []

        def completed(_success, _message):
            acquired = coordinator._lock.acquire(blocking=False)
            callback_lock_access.append(acquired)
            if acquired:
                coordinator._lock.release()

        coordinator.request_shutdown(completed)
        self.assertEqual(callback_lock_access, [True])

    def test_stale_database_drain_cannot_clear_a_reopened_runtime(self):
        cleared = []

        class _Tokens:
            def clear_database(self, database_id):
                cleared.append(database_id)

        descriptors = DatabaseDescriptorRegistry()
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            _Tokens(),
            LocalDraftRegistry(),
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        coordinator._runtimes["database"] = _DatabaseRuntime("database", 2)
        completed = []
        coordinator._database_drains[("database", 1)] = [
            lambda success, _message: completed.append(success)
        ]
        coordinator._complete_database_drain(
            (
                "database",
                1,
                True,
                "",
            )
        )
        self.assertEqual(cleared, [])
        self.assertEqual(completed, [True])
        self.assertEqual(coordinator._runtime("database").generation, 2)
        _shutdown_coordinator(coordinator)

    def test_database_drain_callback_failure_cannot_interrupt_shutdown_completion(self):
        coordinator = _coordinator(
            DatabaseDescriptorRegistry(),
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(DatabaseDescriptorRegistry(), _PermissionProbe()),
            DatabaseSessionRegistry(),
            *_token_service(),
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        shutdown_results = []
        coordinator._shutting_down = True
        coordinator._shutdown_state = CollaborationShutdownState.DRAINING
        coordinator._shutdown_callbacks.append(
            lambda success, message: shutdown_results.append((success, message))
        )
        coordinator._database_drains[("database", 1)] = [
            lambda _success, _message: (_ for _ in ()).throw(
                RuntimeError("callback failed")
            )
        ]
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ):
            coordinator._complete_database_drain(("database", 1, True, ""))
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)
        self.assertEqual(shutdown_results, [(True, "")])


class SqlCollaborationCoordinatorProcessMutationRequestsTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator._process_mutation_requests."""

    def test_successful_placement_and_deletion_emit_no_timing_info_log(self):
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
        tokens, drafts = _token_service()
        sessions = DatabaseSessionRegistry()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            sessions,
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        with self.assertNoLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="INFO",
        ):
            _queue_test_mutation(
                coordinator,
                descriptor.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda: _committed_execution("501"),
                results.append,
                operation_id="placement-without-timing-log",
            )
            coordinator._process_mutation_requests(runtime)
            _queue_test_mutation(
                coordinator,
                descriptor.database_id,
                (ResourceRef("takeoff", "501", 8),),
                _committed_execution,
                results.append,
                expected_id_count=0,
                operation_id="deletion-without-timing-log",
                mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE,
            )
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED, MutationOutcomeStatus.COMMITTED],
        )
        _shutdown_coordinator(coordinator)

    def test_committed_mutation_becomes_projection_failed_when_journal_update_fails(
        self,
    ):
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
        pending = PendingMutationRegistry()
        journal = _FailingPendingOperationJournal(3)
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
            operation_journal=journal,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: _committed_execution("501"),
            results.append,
            expected_id_count=1,
            operation_id="journal-projecting-failure",
            owning_surface="main-plan",
        )
        with self.assertRaisesRegex(DatabaseCatalogError, "recovery record"):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        pending_entry = pending.for_database(descriptor.database_id)[0]
        self.assertEqual(pending_entry.state, PendingMutationState.RECOVERING)
        self.assertEqual(
            journal.records[pending_entry.request.operation_id].state,
            PendingMutationState.RECOVERING,
        )
        _shutdown_coordinator(coordinator)

    def test_stop_race_after_dequeue_cannot_execute_queued_mutation(self):
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
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(
            descriptor.database_id,
            "session-1",
        )
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        calls = []
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: (calls.append(True) or _committed_execution("501")),
            results.append,
            expected_id_count=1,
            operation_id="placement",
            owning_surface="main-plan",
        )
        queued_requests = runtime.mutation_requests

        class _StopOnGetQueue:
            def get_nowait(self):
                request = queued_requests.get_nowait()
                runtime.stop_event.set()
                return request

            def empty(self):
                return queued_requests.empty()

        runtime.mutation_requests = _StopOnGetQueue()
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.CANCELLED_BEFORE_START,
        )
        self.assertEqual(drafts._drafts, {})
        _shutdown_coordinator(coordinator)

    def test_failed_queued_mutation_does_not_corrupt_the_next_request(self):
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
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        calls = []
        results = []
        resource = ResourceRef("takeoffs_collection", "8", 8)
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            lambda: (
                calls.append("failed")
                or MutationExecutionResult(
                    outcome_status=MutationOutcomeStatus.REJECTED,
                    message="conflict",
                )
            ),
            results.append,
            expected_id_count=1,
            operation_id="failed",
            owning_surface="main-plan",
        )
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            lambda: (calls.append("succeeded") or _committed_execution("501")),
            results.append,
            expected_id_count=1,
            operation_id="succeeded",
            owning_surface="main-plan",
        )
        coordinator._process_mutation_requests(runtime)
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["failed", "succeeded"])
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.REJECTED, MutationOutcomeStatus.COMMITTED],
        )
        self.assertEqual(results[1].created_resource_ids, ("501",))
        self.assertEqual(runtime.mutation_requests.qsize(), 0)
        self.assertEqual(len(store.released), 2)
        self.assertEqual(drafts._drafts, {})
        _shutdown_coordinator(coordinator)

    def test_queued_mutation_cleanup_failure_preserves_original_result(self):
        class _FailedReleaseStore(_LockingStore):
            def release_lock(self, database_id, session_id, lock_token):
                super().release_lock(database_id, session_id, lock_token)
                raise ValueError("lock cleanup failed")

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
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _FailedReleaseStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        resource = ResourceRef("takeoffs_collection", "8", 8)
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            lambda: MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.REJECTED,
                message="the authoritative mutation conflict",
            ),
            results.append,
            expected_id_count=1,
            operation_id="placement",
            owning_surface="main-plan",
        )
        with self.assertRaisesRegex(ValueError, "lock cleanup failed"):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "the authoritative mutation conflict")
        self.assertEqual(drafts._drafts, {})
        _shutdown_coordinator(coordinator)


class SqlCollaborationCoordinatorStartDatabaseTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator.start_database."""

    def test_same_sql_principal_still_creates_distinct_client_sessions(self):
        class _RecordingStore(_CollaborationStore):
            def __init__(self):
                super().__init__()
                self.starts = []

            def start_session(self, *args, **kwargs):
                self.starts.append((args[1], args[2], args[3]))
                return super().start_session(*args, **kwargs)

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        coordinators = []
        stores = []
        for _index in range(2):
            store = _RecordingStore()
            stores.append(store)
            tokens, drafts = _token_service()
            coordinator = _coordinator(
                descriptors,
                store,
                _RemoteReader(),
                _Dispatcher(),
                _Reconciliation(),
                DatabaseCapabilityService(descriptors, _PermissionProbe()),
                DatabaseSessionRegistry(),
                tokens,
                drafts,
                _EventBus(),
                SQL_SCHEMA_V1.version,
            )
            coordinators.append(coordinator)
            self.assertTrue(coordinator.start_database(descriptor.database_id))
            self.assertTrue(store.started.wait(2))
        try:
            first, second = stores[0].starts[0], stores[1].starts[0]
            self.assertEqual(first[2], second[2])
            self.assertNotEqual(first[0], second[0])
            self.assertNotEqual(first[1], second[1])
        finally:
            for coordinator in coordinators:
                _shutdown_coordinator(coordinator)

    def test_normal_remote_poll_never_reenters_session_start_callback(self):
        class _RoutingCoordinator(SqlCollaborationCoordinator):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault("pending_mutations", PendingMutationRegistry())
                kwargs.setdefault("operation_journal", _PendingOperationJournal())
                super().__init__(*args, **kwargs)
                self.session_started_calls = 0
                self.remote_batch_calls = 0
                self.remote_batch_seen = threading.Event()

            def _on_session_started(self, payload):
                self.session_started_calls += 1
                super()._on_session_started(payload)

            def _on_remote_batch(self, payload):
                self.remote_batch_calls += 1
                super()._on_remote_batch(payload)
                self.remote_batch_seen.set()

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _CollaborationStore()
        tokens, drafts = _token_service()
        coordinator = _RoutingCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                selected_database_seconds=0.05,
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        store.change = _change(
            descriptor.database_id,
            ResourceRef("takeoff", "30", 8),
            sequence=2,
            source="other-session",
        )
        self.assertTrue(coordinator.remote_batch_seen.wait(2))
        self.assertEqual(coordinator.session_started_calls, 1)
        self.assertGreaterEqual(coordinator.remote_batch_calls, 1)
        _shutdown_coordinator(coordinator)

    def test_coordinator_starts_only_for_sql_and_closes_session(self):
        descriptors = DatabaseDescriptorRegistry()
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        access_descriptor = DatabaseDescriptor.for_access("C:/test.mdb")
        unversioned_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="EXTERNAL"),
            schema_version=0,
        )
        future_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="FUTURE"),
            schema_version=SQL_SCHEMA_V1.version + 1,
        )
        descriptors.register_all(
            (
                sql_descriptor,
                access_descriptor,
                unversioned_descriptor,
                future_descriptor,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertFalse(coordinator.start_database(access_descriptor.database_id))
        self.assertFalse(coordinator.start_database(unversioned_descriptor.database_id))
        self.assertFalse(coordinator.start_database(future_descriptor.database_id))
        initial_results = []
        initial_complete = threading.Event()

        def initial_open(ready, message):
            initial_results.append(
                (ready, message, capabilities.is_editable(sql_descriptor.database_id))
            )
            initial_complete.set()

        self.assertTrue(
            coordinator.start_database(
                sql_descriptor.database_id, on_initial_open=initial_open
            )
        )
        runtime = coordinator._runtime(sql_descriptor.database_id)
        try:
            self.assertTrue(store.started.wait(5))
            self.assertTrue(store.polled.wait(5))
            self.assertTrue(healthy.wait(5))
            self.assertTrue(initial_complete.wait(5))
            self.assertEqual(initial_results, [(True, "", True)])
            _stop_database(coordinator, sql_descriptor.database_id)
            self.assertTrue(store.closed.wait(5))
            self.assertEqual(sessions.get(sql_descriptor.database_id), "")
            self.assertIsNotNone(runtime)
            self.assertFalse(runtime.thread.is_alive())
            self.assertEqual(len(initial_results), 1)
        finally:
            _shutdown_coordinator(coordinator)

    def test_coordinator_suppresses_own_change_application(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CollaborationStore()
        reconciliation = _Reconciliation()
        sessions = DatabaseSessionRegistry()
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
            source=store.session_id.upper(),
        )
        self.assertTrue(store.change_seen.wait(3))
        _stop_database(coordinator, descriptor.database_id)
        self.assertEqual(len(reconciliation.batches), 2)
        self.assertEqual(reconciliation.batches[-1].batch.changes, ())
        _shutdown_coordinator(coordinator)

    def test_authoritative_recovery_can_trust_a_lower_feed_version(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        try:
            self.assertTrue(first_healthy.wait(5))
            runtime = coordinator._runtime(descriptor.database_id)
            self.assertEqual(runtime.observed_high_water_version, 25)
            coordinator._on_reconciliation_required(
                (descriptor.database_id, runtime.generation, "feed restored")
            )
            store.initial_version = 5
            store.batch = _batch(descriptor.database_id, "new-epoch", 1, 5)
            events.publish(
                AppEvents.DATABASE_REFRESHED,
                file_path=descriptor.database_id,
            )
            self.assertTrue(store.restarted.wait(5))
            self.assertTrue(second_healthy.wait(5))
            self.assertEqual(runtime.acknowledged_version, 5)
            self.assertEqual(runtime.observed_high_water_version, 5)
        finally:
            _shutdown_coordinator(coordinator)

    def test_failed_main_thread_reconciliation_does_not_acknowledge_batch(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        failure_payload = next(
            payload
            for event, payload in reversed(events.published)
            if event is AppEvents.FULL_RECONCILIATION_REQUIRED
        )
        self.assertNotIn("session start", failure_payload["reason"].lower())
        _shutdown_coordinator(coordinator)

    def test_queued_mutations_run_serially_off_the_calling_thread(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        sessions = DatabaseSessionRegistry()
        resource = ResourceRef("takeoffs_collection", "8", 8)
        tokens, drafts = _token_service(
            _TokenReader({resource: ConcurrencyToken((1).to_bytes(8, "big"))})
        )
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            sessions,
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        calling_thread = threading.get_ident()
        operation_threads = []
        operation_order = []
        expected_tokens = []
        results = []
        completed = threading.Event()

        def operation(index):
            operation_threads.append(threading.get_ident())
            operation_order.append(index)
            expected_tokens.append(
                tokens.expected_versions(descriptor.database_id, (resource,))[
                    0
                ].expected
            )
            tokens.apply_result(
                descriptor.database_id,
                {resource: ConcurrencyToken((index + 1).to_bytes(8, "big"))},
            )
            return _committed_execution(f"created-{index}")

        def complete(result):
            results.append(result)
            if len(results) == 2:
                completed.set()

        for index in (1, 2):
            _queue_test_mutation(
                coordinator,
                descriptor.database_id,
                (resource,),
                lambda index=index: operation(index),
                complete,
                expected_id_count=1,
                operation_id=f"placement-{index}",
                owning_surface="main-plan",
            )
        self.assertTrue(completed.wait(2))
        self.assertEqual(operation_order, [1, 2])
        self.assertEqual(
            expected_tokens,
            [
                ConcurrencyToken((1).to_bytes(8, "big")),
                ConcurrencyToken((2).to_bytes(8, "big")),
            ],
        )
        self.assertTrue(
            all(thread_id != calling_thread for thread_id in operation_threads)
        )
        self.assertEqual(
            [result.created_resource_ids for result in results],
            [("created-1",), ("created-2",)],
        )
        self.assertTrue(
            all(
                result.outcome_status == MutationOutcomeStatus.COMMITTED
                for result in results
            )
        )
        self.assertEqual(len(store.released), 2)
        self.assertEqual(drafts._drafts, {})
        _stop_database(coordinator, descriptor.database_id)
        _shutdown_coordinator(coordinator)

    def test_queued_mutation_presents_lock_when_store_omits_bid_context(self):
        class _CanonicalLockStore(_LockingStore):
            def acquire_lock(self, database_id, _session_id, resource, _description):
                return ResourceLock(
                    database_id,
                    ResourceRef(resource.resource_type, resource.resource_id),
                    "lock-token",
                )

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        sessions = DatabaseSessionRegistry()
        tokens, drafts = _token_service()
        store = _CanonicalLockStore()
        events = _EventBus()
        reconciliation = _Reconciliation()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        requested = ResourceRef("takeoffs_collection", "8", 8)
        results = []
        completed = threading.Event()

        def operation():
            self.assertEqual(
                sessions.lock_tokens(descriptor.database_id, (requested,)),
                ("lock-token",),
            )
            return _committed_execution("501")

        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (requested,),
            operation,
            lambda result: (results.append(result), completed.set()),
            expected_id_count=1,
            operation_id="takeoff-placement",
            owning_surface="main-plan",
        )
        self.assertTrue(completed.wait(2))
        self.assertEqual(results[0].outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            reconciliation.projection_barriers[-1].resource_uid_aliases_by_family,
            {"takeoffs": (queued_takeoff_preview_uid(results[0].operation_id, 0),)},
        )
        self.assertEqual(
            sessions.lock_tokens(descriptor.database_id, (requested,)),
            (),
        )
        self.assertTrue(sessions.get(descriptor.database_id))
        self.assertFalse(
            any(
                event
                in (
                    AppEvents.SYNCHRONIZATION_CONFLICT,
                    AppEvents.FULL_RECONCILIATION_REQUIRED,
                )
                for event, _payload in events.published
            )
        )
        _stop_database(coordinator, descriptor.database_id)
        _shutdown_coordinator(coordinator)

    def test_database_stop_rejects_queued_mutations_without_retrying_inflight_write(
        self,
    ):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        entered = threading.Event()
        release = threading.Event()
        calls = []
        results = []
        completed = threading.Event()

        def first_operation():
            calls.append("first")
            entered.set()
            if not release.wait(2):
                raise AssertionError("in-flight test mutation was not released")
            return _committed_execution("created-1")

        def second_operation():
            calls.append("second")
            return _committed_execution("created-2")

        def complete(result):
            results.append(result)
            if len(results) == 2:
                completed.set()

        resource = ResourceRef("takeoffs_collection", "8", 8)
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            first_operation,
            complete,
            expected_id_count=1,
            operation_id="placement-1",
            owning_surface="main-plan",
        )
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            second_operation,
            complete,
            expected_id_count=1,
            operation_id="placement-2",
            owning_surface="main-plan",
        )
        self.assertTrue(entered.wait(2))
        stopped = threading.Event()
        coordinator.stop_database_async(
            descriptor.database_id,
            callback=lambda success, message: (
                self.assertTrue(success, message),
                stopped.set(),
            ),
        )
        release.set()
        self.assertTrue(completed.wait(2))
        self.assertTrue(stopped.wait(2))
        self.assertEqual(calls, ["first"])
        self.assertEqual(
            [result.outcome_status for result in results],
            [
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                MutationOutcomeStatus.CANCELLED_BEFORE_START,
            ],
        )
        self.assertEqual(drafts._drafts, {})
        _shutdown_coordinator(coordinator)

    def test_worker_services_heartbeat_between_queued_mutations(self):
        class _OrderedHeartbeatStore(_LockingStore):
            def __init__(self):
                super().__init__()
                self.order = []

            def heartbeat(self, *args):
                self.order.append("heartbeat")
                return super().heartbeat(*args)

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _OrderedHeartbeatStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                heartbeat_seconds=0.0,
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        store.order.clear()
        first_entered = threading.Event()
        release_first = threading.Event()
        completed = threading.Event()
        result_count = 0

        def first_operation():
            store.order.append("first")
            first_entered.set()
            if not release_first.wait(2):
                raise AssertionError("first mutation was not released")
            return _committed_execution("501")

        def second_operation():
            store.order.append("second")
            return _committed_execution("502")

        def complete(_result):
            nonlocal result_count
            result_count += 1
            if result_count == 2:
                completed.set()

        resource = ResourceRef("takeoffs_collection", "8", 8)
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            first_operation,
            complete,
            expected_id_count=1,
            operation_id="first",
            owning_surface="main-plan",
        )
        self.assertTrue(first_entered.wait(2))
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            second_operation,
            complete,
            expected_id_count=1,
            operation_id="second",
            owning_surface="main-plan",
        )
        release_first.set()
        self.assertTrue(completed.wait(2))
        first_index = store.order.index("first")
        second_index = store.order.index("second")
        self.assertIn("heartbeat", store.order[first_index + 1 : second_index])
        _stop_database(coordinator, descriptor.database_id)
        _shutdown_coordinator(coordinator)

    def test_worker_releases_finished_edit_lease_before_overlapping_mutation(self):
        class _ControllablePollStore(_LockingStore):
            def __init__(self):
                super().__init__()
                self.block_poll = threading.Event()
                self.poll_blocked = threading.Event()
                self.release_poll = threading.Event()

            def poll_changes(self, *args):
                if self.block_poll.is_set():
                    self.poll_blocked.set()
                    if not self.release_poll.wait(2):
                        raise AssertionError(
                            "test poll did not receive its release signal"
                        )
                return super().poll_changes(*args)

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _ControllablePollStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        resource = ResourceRef("takeoff", "42", 8)
        lease_completed = threading.Event()
        lease_results = []
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: (lease_results.append(result), lease_completed.set()),
        )
        self.assertTrue(lease_completed.wait(2))
        self.assertTrue(lease_results[0].granted)
        handle = lease_results[0].handle
        store.block_poll.set()
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertIsNotNone(runtime)
        runtime.command_event.set()
        self.assertTrue(store.poll_blocked.wait(2))
        coordinator.end_edit_lease(handle)
        mutation_completed = threading.Event()
        mutation_results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (resource,),
            lambda: _committed_execution("42"),
            lambda result: (
                mutation_results.append(result),
                mutation_completed.set(),
            ),
            operation_id="delete-after-selection-lease",
        )
        store.release_poll.set()
        self.assertTrue(mutation_completed.wait(2))
        self.assertEqual(
            mutation_results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED,
        )
        self.assertEqual(len(store.released), 2)
        _stop_database(coordinator, descriptor.database_id)
        _shutdown_coordinator(coordinator)

    def test_incomplete_queued_insert_identity_set_forces_read_only_cleanup(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        sessions = DatabaseSessionRegistry()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            sessions,
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        completed = threading.Event()
        results = []
        operation_calls = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: (operation_calls.append(True) or _committed_execution()),
            lambda result: (results.append(result), completed.set()),
            expected_id_count=1,
            operation_id="placement",
            owning_surface="main-plan",
        )
        self.assertTrue(completed.wait(2))
        self.assertEqual(operation_calls, [True])
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        self.assertEqual(results[0].created_resource_ids, ())
        self.assertEqual(drafts._drafts, {})
        self.assertTrue(store.release_event.wait(2))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.READ_ONLY,
        )
        self.assertEqual(sessions.get(descriptor.database_id), "")
        _shutdown_coordinator(coordinator)

    def test_retention_gap_enters_controlled_read_only_reconciliation(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _shutdown_coordinator(coordinator)

    def test_reconciliation_releases_local_edit_locks(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _shutdown_coordinator(coordinator)

    def test_entering_conflict_releases_edit_locks_on_worker_thread(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        # The store signals inside start_session, before startup reconciliation.
        # Lease requests are valid only after the coordinator publishes readiness.
        self.assertTrue(healthy.wait(2))
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

    def test_batch_lease_rejection_has_no_partial_cleanup(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _BatchAcquireFailureStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        results = []
        first = ResourceRef("condition", "42", 8)
        second = ResourceRef("condition", "43", 8)
        try:
            coordinator.request_local_edit(
                descriptor.database_id,
                (first, second),
                results.append,
            )
            self.assertTrue(store.acquire_failed.wait(2))
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].granted)
            self.assertFalse(store.closed.is_set())
            replacement = drafts.begin(
                draft_type="condition_editor",
                database_id=descriptor.database_id,
                bid_uid=8,
                page_uid=None,
                owning_surface="test",
                affected_resources=(first, second),
            )
            drafts.finish(replacement.draft_id)
        finally:
            _shutdown_coordinator(coordinator)

    def test_database_stop_releases_active_lease_and_publishes_loss(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _LockingStore()
        events = _EventBus()
        lease_lost = threading.Event()
        events.subscribe(AppEvents.EDIT_LEASE_LOST, lambda **_payload: lease_lost.set())
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _stop_database(coordinator, descriptor.database_id)
        self.assertTrue(store.release_event.is_set())
        self.assertTrue(lease_lost.is_set())
        _shutdown_coordinator(coordinator)

    def test_stopped_database_cannot_deliver_a_stale_lease_grant(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _LockingStore()
        dispatcher = _DelayedLeaseDispatcher()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _stop_database(coordinator, descriptor.database_id)
        dispatcher.deliver_pending()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].granted)
        _shutdown_coordinator(coordinator)

    def test_edit_request_cannot_queue_after_database_drain_finishes(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        drafts = _BlockingDraftRegistry()
        tokens = DatabaseConcurrencyTokenService(_TokenReader(), drafts)
        store = _CollaborationStore()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        self.assertTrue(capabilities.mark_connected(descriptor.database_id))
        results = []
        resource = ResourceRef("condition", "42", 8)
        requester = threading.Thread(
            target=coordinator.request_local_edit,
            args=(descriptor.database_id, (resource,), results.append),
        )
        requester.start()
        self.assertTrue(drafts.entered.wait(2))
        _stop_database(coordinator, descriptor.database_id)
        drafts.proceed.set()
        requester.join(2)
        try:
            self.assertFalse(requester.is_alive())
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].granted)
            replacement = drafts.begin(
                draft_type="condition_editor",
                database_id=descriptor.database_id,
                bid_uid=8,
                page_uid=None,
                owning_surface="test",
                affected_resources=(resource,),
            )
            drafts.finish(replacement.draft_id)
        finally:
            _shutdown_coordinator(coordinator)

    def test_edit_request_cannot_survive_trust_loss_during_draft_creation(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        drafts = _BlockingDraftRegistry()
        tokens = DatabaseConcurrencyTokenService(_TokenReader(), drafts)
        store = _CollaborationStore()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        self.assertTrue(capabilities.mark_connected(descriptor.database_id))
        results = []
        resource = ResourceRef("condition", "42", 8)
        requester = threading.Thread(
            target=coordinator.request_local_edit,
            args=(descriptor.database_id, (resource,), results.append),
        )
        requester.start()
        self.assertTrue(drafts.entered.wait(2))
        coordinator.enter_conflict(descriptor.database_id, "trust lost")
        drafts.proceed.set()
        requester.join(2)
        try:
            self.assertFalse(requester.is_alive())
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].granted)
            replacement = drafts.begin(
                draft_type="condition_editor",
                database_id=descriptor.database_id,
                bid_uid=8,
                page_uid=None,
                owning_surface="test",
                affected_resources=(resource,),
            )
            drafts.finish(replacement.draft_id)
        finally:
            _shutdown_coordinator(coordinator)

    def test_trust_loss_cannot_deliver_a_stale_lease_grant(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _LockingStore()
        dispatcher = _DelayedLeaseDispatcher()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _shutdown_coordinator(coordinator)

    def test_sql_edit_lease_is_acquired_and_released_on_worker_thread(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        self.assertIsNotNone(results[0].handle)
        self.assertEqual(results[0].handle.resources, (resource,))
        self.assertEqual(results[0].handle.locks[0].lock_token, "lock-token")
        self.assertGreater(results[0].handle.runtime_generation, 0)
        self.assertNotEqual(store.acquire_thread, caller_thread)
        coordinator.end_edit_lease(results[0].handle)
        self.assertTrue(store.release_event.wait(2))
        _shutdown_coordinator(coordinator)

    def test_capability_reprobe_restarts_stopped_credential_worker(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _CredentialRecoveryStore()
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _shutdown_coordinator(coordinator)

    def test_retryable_disconnect_creates_a_new_trusted_session(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        store = _TransientRecoveryStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
        _shutdown_coordinator(coordinator)

    def test_startup_connection_failure_does_not_retry_until_user_reconnects(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _AlwaysUnavailableStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                jitter_ratio=0.0,
                reconnect_backoff_seconds=(0.0,),
            ),
        )
        initial_results = []
        initial_complete = threading.Event()

        def initial_open(ready, message):
            initial_results.append((ready, message))
            initial_complete.set()

        caller_thread = threading.get_ident()
        self.assertTrue(
            coordinator.start_database(
                descriptor.database_id,
                retry_initial_failure=False,
                on_initial_open=initial_open,
            )
        )
        self.assertTrue(store.first_failure.wait(2))
        self.assertTrue(initial_complete.wait(2))
        self.assertFalse(initial_results[0][0])
        self.assertTrue(initial_results[0][1])
        self.assertFalse(store.repeated_failure.wait(0.1))
        self.assertEqual(store.start_count, 1)
        self.assertNotEqual(store.start_threads, [caller_thread])
        self.assertEqual(
            coordinator.status(descriptor.database_id).state,
            SynchronizationState.DISCONNECTED,
        )
        _shutdown_coordinator(coordinator)

    def test_invalid_feed_enters_controlled_reconciliation(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(reconciliation_required.wait(2))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        _shutdown_coordinator(coordinator)

    def test_shutdown_does_not_start_later_polling_phases(self):
        for held_phase in ("heartbeat", "locks"):
            with self.subTest(held_phase=held_phase):
                entered = threading.Event()
                release = threading.Event()
                calls = []

                def record(phase):
                    calls.append(phase)
                    if phase == held_phase:
                        entered.set()
                        if not release.wait(5):
                            raise AssertionError("Shutdown probe was not released")

                class Store(_CollaborationStore):
                    def heartbeat(self, *args):
                        record("heartbeat")
                        return super().heartbeat(*args)

                    def list_locks(self, *args):
                        record("locks")
                        return super().list_locks(*args)

                    def poll_changes(self, *args):
                        record("changes")
                        return super().poll_changes(*args)

                    def close_session(self, *args):
                        record("close")
                        return super().close_session(*args)

                descriptors = DatabaseDescriptorRegistry()
                descriptor = DatabaseDescriptor.for_sql_server(
                    SqlServerDatabaseLocation(server="localhost", database="TEST"),
                    schema_version=SQL_SCHEMA_V1.version,
                )
                descriptors.register(descriptor)
                store = Store()
                tokens, drafts = _token_service()
                coordinator = _coordinator(
                    descriptors,
                    store,
                    _RemoteReader(),
                    _Dispatcher(),
                    _Reconciliation(),
                    DatabaseCapabilityService(descriptors, _PermissionProbe()),
                    DatabaseSessionRegistry(),
                    tokens,
                    drafts,
                    _EventBus(),
                    SQL_SCHEMA_V1.version,
                )
                completed = threading.Event()
                results = []
                try:
                    self.assertTrue(coordinator.start_database(descriptor.database_id))
                    self.assertTrue(entered.wait(2))
                    coordinator.request_shutdown(
                        lambda success, message: (
                            results.append((success, message)),
                            completed.set(),
                        )
                    )
                    self.assertFalse(completed.is_set())
                    release.set()
                    self.assertTrue(completed.wait(2))
                    expected = ["heartbeat"]
                    if held_phase == "locks":
                        expected.append("locks")
                    self.assertEqual(calls, expected + ["close"])
                    self.assertEqual(results, [(True, "")])
                finally:
                    release.set()
                    _shutdown_coordinator(coordinator)

    def test_shutdown_drains_a_blocked_poll_without_blocking_the_caller(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _BlockedPollStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.poll_entered.wait(2))
        completed = threading.Event()
        results = []
        coordinator.request_shutdown(
            lambda success, message: (
                results.append((success, message)),
                completed.set(),
            )
        )
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.DRAINING
        )
        self.assertFalse(completed.is_set())
        store.release_poll.set()
        self.assertTrue(completed.wait(2))
        self.assertEqual(results, [(True, "")])
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)

    def test_unexpected_worker_failure_closes_session_and_projects_disconnect(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _UnexpectedPollFailureStore()
        tokens, drafts = _token_service()
        sessions = DatabaseSessionRegistry()
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            sessions,
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.failed.wait(2))
        self.assertTrue(store.closed.wait(2))
        self.assertFalse(sessions.get(descriptor.database_id))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.DISCONNECTED,
        )
        _stop_database(coordinator, descriptor.database_id)
        _shutdown_coordinator(coordinator)

    def test_shutdown_waits_for_a_database_drain_already_in_progress(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _BlockedPollStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.poll_entered.wait(2))
        coordinator.stop_database_async(descriptor.database_id)
        completed = threading.Event()
        coordinator.request_shutdown(lambda _success, _message: completed.set())
        self.assertFalse(completed.is_set())
        store.release_poll.set()
        self.assertTrue(completed.wait(2))
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)

    def test_database_cannot_reopen_until_its_previous_session_is_drained(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _BlockedPollStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.poll_entered.wait(2))
        drained = threading.Event()
        coordinator.stop_database_async(
            descriptor.database_id,
            callback=lambda _success, _message: drained.set(),
        )
        self.assertFalse(coordinator.start_database(descriptor.database_id))
        store.release_poll.set()
        self.assertTrue(drained.wait(2))
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        _shutdown_coordinator(coordinator)

    def test_repeated_shutdown_requests_share_one_drain(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _BlockedPollStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.poll_entered.wait(2))
        completed = threading.Event()
        results = []

        def record(label):
            return lambda success, _message: (
                results.append((label, success)),
                completed.set() if len(results) == 2 else None,
            )

        coordinator.request_shutdown(record("first"))
        coordinator.request_shutdown(record("second"))
        store.release_poll.set()
        self.assertTrue(completed.wait(2))
        self.assertCountEqual(results, [("first", True), ("second", True)])
        self.assertEqual(store.start_count, 1)

    def test_shutdown_reports_session_cleanup_failure(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _FailedCloseStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        completed = threading.Event()
        results = []
        coordinator.request_shutdown(
            lambda success, message: (
                results.append((success, message)),
                completed.set(),
            )
        )
        self.assertTrue(completed.wait(2))
        self.assertFalse(results[0][0])
        self.assertIn("session could not be closed", results[0][1])
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.CLEANUP_FAILED
        )

    def test_successful_session_close_supersedes_individual_lock_release_failure(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _ReleaseFailsCloseSucceedsStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        resource = ResourceRef("condition", "42", 8)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        lease_completed = threading.Event()
        lease_results = []
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: (lease_results.append(result), lease_completed.set()),
        )
        self.assertTrue(lease_completed.wait(2))
        self.assertTrue(lease_results[0].granted)
        shutdown_completed = threading.Event()
        shutdown_results = []
        coordinator.request_shutdown(
            lambda success, message: (
                shutdown_results.append((success, message)),
                shutdown_completed.set(),
            )
        )
        self.assertTrue(shutdown_completed.wait(2))
        self.assertTrue(store.closed.is_set())
        self.assertEqual(shutdown_results, [(True, "")])
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)
        self.assertIsNone(drafts.get(lease_results[0].handle.draft_id))

    def test_offline_database_unload_abandons_expiring_remote_cleanup(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _FailedCloseStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.started.wait(2))
        unloaded = threading.Event()
        unload_results = []
        coordinator.stop_database_async(
            descriptor.database_id,
            callback=lambda success, message: (
                unload_results.append((success, message)),
                unloaded.set(),
            ),
        )
        self.assertTrue(unloaded.wait(2))
        self.assertEqual(unload_results, [(True, "")])
        self.assertEqual(coordinator._database_cleanup_failures, {})
        shutdown = threading.Event()
        shutdown_results = []
        coordinator.request_shutdown(
            lambda success, message: (
                shutdown_results.append((success, message)),
                shutdown.set(),
            )
        )
        self.assertTrue(shutdown.wait(2))
        self.assertEqual(shutdown_results, [(True, "")])
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)
        repeated_results = []
        coordinator.request_shutdown(
            lambda success, message: repeated_results.append((success, message))
        )
        self.assertEqual(len(repeated_results), 1)
        self.assertEqual(repeated_results, [(True, "")])


class SqlCollaborationCoordinatorDispatchMutationResultTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator._dispatch_mutation_result."""

    def test_stale_queued_mutation_conflict_cannot_open_dialog_for_new_runtime(self):
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
        dispatcher = _DelayedMutationDispatcher()
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            dispatcher,
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            SQL_SCHEMA_V1.version,
        )
        old_runtime = _DatabaseRuntime(descriptor.database_id, 1)
        old_runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = old_runtime
        conflict = SynchronizationConflict(
            descriptor.database_id,
            ResourceRef("takeoffs_collection", "8", 8),
            "stale takeoff collection",
        )
        callbacks = []
        coordinator._dispatch_mutation_result(
            callbacks.append,
            QueuedMutationResult(
                database_id=descriptor.database_id,
                runtime_generation=old_runtime.generation,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
                message=conflict.reason,
                conflict=conflict,
            ),
        )
        new_runtime = _DatabaseRuntime(descriptor.database_id, 2)
        new_runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = new_runtime
        dispatcher.deliver_pending()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(events.published, [])
        _shutdown_coordinator(coordinator)

    def test_stale_runtime_cannot_deliver_successful_queued_mutation_result(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        dispatcher = _DelayedMutationDispatcher()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            dispatcher,
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        first_runtime = _DatabaseRuntime(descriptor.database_id, 1)
        coordinator._runtimes[descriptor.database_id] = first_runtime
        results = []
        coordinator._dispatch_mutation_result(
            results.append,
            QueuedMutationResult(
                database_id=descriptor.database_id,
                runtime_generation=first_runtime.generation,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            ),
        )
        coordinator._runtimes[descriptor.database_id] = _DatabaseRuntime(
            descriptor.database_id, 2
        )
        dispatcher.deliver_pending()
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        self.assertEqual(results[0].created_resource_ids, ())
        _shutdown_coordinator(coordinator)

    def test_trust_loss_before_ui_delivery_rejects_committed_projection(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        dispatcher = _DelayedMutationDispatcher()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            dispatcher,
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        coordinator._dispatch_mutation_result(
            results.append,
            QueuedMutationResult(
                database_id=descriptor.database_id,
                runtime_generation=runtime.generation,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            ),
        )
        with runtime.lock:
            runtime.healthy = False
            runtime.recovery_requested = True
        dispatcher.deliver_pending()
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        self.assertEqual(results[0].created_resource_ids, ())
        _shutdown_coordinator(coordinator)

    def test_transient_self_feed_does_not_reject_committed_projection(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        dispatcher = _DelayedMutationDispatcher()
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            dispatcher,
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        coordinator._dispatch_mutation_result(
            results.append,
            QueuedMutationResult(
                database_id=descriptor.database_id,
                runtime_generation=runtime.generation,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            ),
        )
        with runtime.lock:
            runtime.healthy = False
            runtime.pending_delivery = True
        dispatcher.deliver_pending()
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED,
        )
        self.assertEqual(results[0].created_resource_ids, ("501",))
        _shutdown_coordinator(coordinator)


class SqlCollaborationCoordinatorResumeControlledRecoveryTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator.resume_controlled_recovery."""

    def test_reconciliation_checkpoint_advances_only_after_worker_owned_recovery(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda database_id="", **_payload: (
                coordinator.resume_controlled_recovery(database_id)
            ),
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
                AppEvents.COLLABORATION_STATE_CHANGED,
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
            ],
        )
        store.initial_version = 25
        store.batch = _batch(descriptor.database_id, "epoch", 0, 25)
        self.assertTrue(store.restarted.wait(2))
        self.assertEqual(runtime.acknowledged_version, 25)
        _shutdown_coordinator(coordinator)

    def test_committed_hydration_validation_error_is_not_precommit_failure(self):
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
        pending = PendingMutationRegistry()
        tokens, drafts = _token_service()
        event_bus = _EventBus()
        coordinator = _coordinator(
            descriptors,
            _InvalidCommittedHydrationStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            event_bus,
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
        )
        recovery_started = []
        event_bus.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda database_id="", **_payload: recovery_started.append(
                coordinator.resume_controlled_recovery(database_id)
            ),
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: _committed_execution("501"),
            results.append,
            expected_id_count=1,
            operation_id="committed-invalid-hydration",
            owning_surface="main-plan",
        )
        with self.assertRaisesRegex(DatabaseCatalogError, "ChangeLog"):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        self.assertTrue(results[0].commit_attempted)
        self.assertEqual(results[0].created_resource_ids, ("501",))
        self.assertIsNotNone(results[0].authoritative_result)
        self.assertEqual(
            pending.for_database(descriptor.database_id)[0].state,
            PendingMutationState.RECOVERING,
        )
        self.assertTrue(
            any(
                event == AppEvents.FULL_RECONCILIATION_REQUIRED
                for event, _payload in event_bus.published
            )
        )
        self.assertEqual(recovery_started, [True])
        self.assertTrue(runtime.recovery_requested)
        self.assertTrue(runtime.recovery_ready)
        self.assertTrue(runtime.recovery_attempted)
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.CONNECTING,
        )
        _shutdown_coordinator(coordinator)

    def test_reconciliation_request_is_idempotent_after_recovery_starts(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        coordinator._runtimes[descriptor.database_id] = runtime
        recovery_started = []
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda database_id="", **_payload: recovery_started.append(
                coordinator.resume_controlled_recovery(database_id)
            ),
        )
        payload = (descriptor.database_id, runtime.generation, "projection failed")
        coordinator._on_reconciliation_required(payload)
        coordinator._on_reconciliation_required(payload)
        self.assertEqual(recovery_started, [True])
        self.assertTrue(runtime.recovery_requested)
        self.assertTrue(runtime.recovery_ready)
        self.assertEqual(
            sum(
                event is AppEvents.FULL_RECONCILIATION_REQUIRED
                for event, _payload in events.published
            ),
            1,
        )
        _shutdown_coordinator(coordinator)

    def test_recovery_cancels_queued_noncritical_page_state_exactly_once(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id,
            SynchronizationState.HEALTHY,
        )
        pending = PendingMutationRegistry()
        journal = _PendingOperationJournal()
        events = _EventBus()
        tokens, drafts = _token_service()
        store = _CollaborationStore()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
            operation_journal=journal,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda database_id="", **_payload: coordinator.resume_controlled_recovery(
                database_id
            ),
        )
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("page", "8", 8),),
            lambda: _committed_execution(),
            results.append,
            expected_id_count=0,
            operation_id="noncritical-page-view",
            owning_surface="main-plan",
            lifecycle_critical=False,
        )
        self.assertEqual(len(pending.for_database(descriptor.database_id)), 1)
        coordinator._on_reconciliation_required(
            (descriptor.database_id, runtime.generation, "projection failed")
        )
        coordinator._reset_session(runtime)
        coordinator._reset_session(runtime)
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.CANCELLED_BEFORE_START],
        )
        self.assertEqual(pending.for_database(descriptor.database_id), ())
        self.assertEqual(journal.records, {})
        _shutdown_coordinator(coordinator)

    def test_projection_failure_recovers_committed_operation_exactly_once(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id,
            SynchronizationState.HEALTHY,
        )
        pending = PendingMutationRegistry()
        journal = _PendingOperationJournal()
        events = _EventBus()
        store = _RecoverableProjectionStore()
        reconciliation = _FailFirstLocalProjectionReconciliation()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
            operation_journal=journal,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda database_id="", **_payload: coordinator.resume_controlled_recovery(
                database_id
            ),
        )
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: _committed_execution("501"),
            results.append,
            expected_id_count=1,
            operation_id="recoverable-projection",
            owning_surface="main-plan",
        )
        request = pending.for_database(descriptor.database_id)[0].request
        store.durable_results[request.operation_id] = DurableOperationResult(
            database_id=descriptor.database_id,
            operation_id=request.operation_id,
            found=True,
            mutation_type=request.mutation_type.value,
            request_hash=request.request_hash,
            result_format_version=1,
            result_payload=json.dumps(
                {"value": ["501"], "value_available": True},
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        coordinator._process_mutation_requests(runtime)
        self.assertTrue(reconciliation.local_projection_started.is_set())
        reconciliation.token.complete(False)
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED],
        )
        self.assertEqual(
            pending.get(request.operation_id).state,
            PendingMutationState.RECOVERING,
        )
        self.assertTrue(runtime.recovery_ready)
        coordinator._reset_session(runtime)
        with runtime.lock:
            runtime.recovery_requested = False
            runtime.recovery_ready = False
            runtime.pending_delivery = False
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                descriptor.database_id,
                runtime.generation,
                runtime.session_generation,
                HydratedDatabaseChangeBatch(
                    _batch(descriptor.database_id, "epoch", 0, 0)
                ),
                None,
            )
        )
        self.assertTrue(store.recovery_queried.is_set())
        self.assertEqual(
            [result.outcome_status for result in results],
            [
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                MutationOutcomeStatus.COMMITTED,
            ],
        )
        self.assertEqual(pending.for_database(descriptor.database_id), ())
        self.assertEqual(journal.records, {})
        self.assertNotIn(request.operation_id, coordinator._uncertain_callbacks)
        _shutdown_coordinator(coordinator)

    def test_stale_committed_projection_recovers_through_replacement_runtime(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        capabilities.mark_connected(descriptor.database_id)
        capabilities.set_collaboration_state(
            descriptor.database_id,
            SynchronizationState.HEALTHY,
        )
        pending = PendingMutationRegistry()
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
        )
        first_runtime = _DatabaseRuntime(descriptor.database_id, 1)
        first_runtime.session = DatabaseSession(descriptor.database_id, "session-1")
        first_runtime.established = True
        first_runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = first_runtime
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: _committed_execution("501"),
            results.append,
            operation_id="stale-projection-recovery",
        )
        request = pending.for_database(descriptor.database_id)[0].request
        replacement_runtime = _DatabaseRuntime(descriptor.database_id, 2)
        coordinator._runtimes[descriptor.database_id] = replacement_runtime
        recovery_started = []
        events.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda database_id="", **_payload: recovery_started.append(
                coordinator.resume_controlled_recovery(database_id)
            ),
        )
        coordinator._complete_mutation_request(
            (
                results.append,
                QueuedMutationResult(
                    database_id=descriptor.database_id,
                    runtime_generation=first_runtime.generation,
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                    message="The committed projection arrived after reconnecting.",
                    commit_attempted=True,
                ),
            )
        )
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED],
        )
        self.assertEqual(
            pending.get(request.operation_id).state,
            PendingMutationState.RECOVERING,
        )
        self.assertEqual(recovery_started, [True])
        self.assertTrue(replacement_runtime.recovery_requested)
        self.assertTrue(replacement_runtime.recovery_ready)
        _shutdown_coordinator(coordinator)


class SqlCollaborationCoordinatorOnRemoteBatchTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator._on_remote_batch."""

    def test_reconciliation_exception_keeps_checkpoint_and_requests_recovery(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
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
                (
                    descriptor.database_id,
                    runtime.generation,
                    runtime.session_generation,
                    hydrated,
                    None,
                )
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
        _shutdown_coordinator(coordinator)

    def test_remote_batch_exception_does_not_reuse_stale_malformed_failure_kind(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        reconciliation = _RaisingReconciliation()
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            SQL_SCHEMA_V1.version,
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
                        ResourceRef("takeoff", "30", 8),
                        sequence=12,
                    ),
                ),
            )
        )
        coordinator._on_remote_batch(
            (
                descriptor.database_id,
                runtime.generation,
                runtime.session_generation,
                hydrated,
                None,
            )
        )
        failure_payload = next(
            payload
            for event, payload in events.published
            if event is AppEvents.FULL_RECONCILIATION_REQUIRED
        )
        self.assertNotIn("malformed", failure_payload["reason"].lower())
        self.assertIn("catch-up", failure_payload["reason"].lower())
        self.assertEqual(runtime.acknowledged_version, 7)
        _shutdown_coordinator(coordinator)

    def test_checkpoint_waits_for_successful_plan_projection(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        events = _EventBus()
        tokens, drafts = _token_service()
        reconciliation = _DeferredProjectionReconciliation()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.acknowledged_version = 7
        runtime.pending_delivery = True
        coordinator._runtimes[descriptor.database_id] = runtime
        hydrated = HydratedDatabaseChangeBatch(
            _batch(descriptor.database_id, "epoch", 1, 12)
        )
        coordinator._on_remote_batch(
            (
                descriptor.database_id,
                runtime.generation,
                runtime.session_generation,
                hydrated,
                None,
            )
        )
        self.assertEqual(runtime.acknowledged_version, 7)
        self.assertTrue(runtime.pending_delivery)
        reconciliation.token.complete(True)
        self.assertEqual(runtime.acknowledged_version, 12)
        self.assertFalse(runtime.pending_delivery)
        reconciliation.token.complete(True)
        self.assertEqual(runtime.acknowledged_version, 12)
        _shutdown_coordinator(coordinator)

    def test_previous_session_projection_cannot_ack_reconnected_session(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        reconciliation = _DeferredProjectionReconciliation()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(descriptor.database_id, "session-before")
        runtime.session_generation = 1
        runtime.acknowledged_version = 7
        runtime.pending_delivery = True
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._on_remote_batch(
            (
                descriptor.database_id,
                runtime.generation,
                runtime.session_generation,
                HydratedDatabaseChangeBatch(
                    _batch(descriptor.database_id, "epoch", 1, 12)
                ),
                None,
            )
        )
        runtime.session = DatabaseSession(descriptor.database_id, "session-after")
        runtime.session_generation = 3
        runtime.acknowledged_version = 20
        runtime.observed_high_water_version = 20
        runtime.pending_delivery = False
        runtime.healthy = True
        reconciliation.token.complete(True)
        self.assertEqual(runtime.acknowledged_version, 20)
        self.assertFalse(runtime.pending_delivery)
        self.assertTrue(runtime.healthy)
        _shutdown_coordinator(coordinator)

    def test_failed_plan_projection_does_not_acknowledge_batch(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        events = _EventBus()
        tokens, drafts = _token_service()
        reconciliation = _DeferredProjectionReconciliation()
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.acknowledged_version = 7
        runtime.pending_delivery = True
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._on_remote_batch(
            (
                descriptor.database_id,
                runtime.generation,
                runtime.session_generation,
                HydratedDatabaseChangeBatch(
                    _batch(descriptor.database_id, "epoch", 1, 12)
                ),
                None,
            )
        )
        reconciliation.token.complete(False)
        self.assertEqual(runtime.acknowledged_version, 7)
        self.assertTrue(runtime.recovery_requested)
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        _shutdown_coordinator(coordinator)


class SqlCollaborationCoordinatorFinishRemoteBatchTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator._finish_remote_batch."""

    def test_rapid_queued_mutations_wait_for_inflight_reconciliation(self):
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
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.session = DatabaseSession(
            database_id=descriptor.database_id,
            session_id="session-1",
            last_acknowledged_version=7,
        )
        runtime.established = True
        runtime.healthy = False
        runtime.pending_delivery = True
        runtime.acknowledged_version = 7
        runtime.observed_high_water_version = 8
        coordinator._runtimes[descriptor.database_id] = runtime
        calls = []
        results = []
        for index in range(3):
            _queue_test_mutation(
                coordinator,
                descriptor.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda index=index: (
                    calls.append(index) or _committed_execution(str(501 + index))
                ),
                results.append,
                expected_id_count=1,
                operation_id=f"placement-{index}",
                owning_surface="main-plan",
            )
        self.assertEqual(calls, [])
        self.assertEqual(results, [])
        self.assertEqual(runtime.mutation_requests.qsize(), 3)
        coordinator._finish_remote_batch(
            descriptor.database_id,
            runtime.generation,
            runtime.session_generation,
            8,
            time.perf_counter(),
            None,
            True,
        )
        for _index in range(3):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [0, 1, 2])
        self.assertEqual(len(results), 3)
        self.assertTrue(
            all(
                result.outcome_status == MutationOutcomeStatus.COMMITTED
                for result in results
            )
        )
        self.assertEqual(
            [result.created_resource_ids for result in results],
            [("501",), ("502",), ("503",)],
        )
        self.assertEqual(runtime.mutation_requests.qsize(), 0)
        self.assertEqual(drafts._drafts, {})
        _shutdown_coordinator(coordinator)

    def test_caught_up_empty_runtime_does_not_wake_worker_again(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            _LockingStore(),
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.pending_delivery = True
        runtime.acknowledged_version = 7
        runtime.observed_high_water_version = 8
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._finish_remote_batch(
            descriptor.database_id,
            runtime.generation,
            runtime.session_generation,
            8,
            time.perf_counter(),
            None,
            True,
        )
        self.assertTrue(runtime.healthy)
        self.assertFalse(runtime.command_event.is_set())
        _shutdown_coordinator(coordinator)

    def test_failed_projection_keeps_delivery_blocked_during_recovery_handoff(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
        events = _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.acknowledged_version = 7
        runtime.pending_delivery = True
        coordinator._runtimes[descriptor.database_id] = runtime
        pending_at_handoff = []
        coordinator._on_reconciliation_required = (
            lambda _payload: pending_at_handoff.append(runtime.pending_delivery)
        )
        coordinator._finish_remote_batch(
            descriptor.database_id,
            runtime.generation,
            runtime.session_generation,
            12,
            0.0,
            None,
            False,
        )
        self.assertEqual(runtime.acknowledged_version, 7)
        self.assertEqual(pending_at_handoff, [True])
        self.assertTrue(runtime.pending_delivery)
        _shutdown_coordinator(coordinator)


class SqlCollaborationCoordinatorEndEditLeaseTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator.end_edit_lease."""

    def test_duplicate_release_does_not_decrement_an_unrelated_edit(self):
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        first = ResourceRef("condition", "42", 8)
        second = ResourceRef("condition", "43", 8)
        first_lock = ResourceLock("database", first, "first-lock")
        second_lock = ResourceLock("database", second, "second-lock")
        first_draft = drafts.begin(
            draft_type="condition_editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(first,),
        )
        second_draft = drafts.begin(
            draft_type="condition_editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(second,),
        )
        drafts.activate(first_draft.draft_id, (first_lock,), runtime_generation=1)
        drafts.activate(second_draft.draft_id, (second_lock,), runtime_generation=1)
        runtime = _DatabaseRuntime("database", 1)
        runtime.session = DatabaseSession("database", "session")
        runtime.edit_depth = 2
        runtime.mode = PresenceMode.EDITING
        runtime.owned_locks = {
            first.lease_identity: first_lock,
            second.lease_identity: second_lock,
        }
        runtime.draft_ids = {
            frozenset((first.lease_identity,)): first_draft.draft_id,
            frozenset((second.lease_identity,)): second_draft.draft_id,
        }
        coordinator._runtimes["database"] = runtime
        first_handle = EditLeaseHandle(
            database_id="database",
            draft_id=first_draft.draft_id,
            runtime_generation=1,
            operation_id=first_draft.operation_id,
            owning_surface="test",
            resources=(first,),
            locks=(first_lock,),
        )
        coordinator.end_edit_lease(first_handle)
        coordinator._process_release_requests(runtime)
        coordinator.end_edit_lease(first_handle)
        coordinator._process_release_requests(runtime)
        self.assertEqual(runtime.edit_depth, 1)
        self.assertEqual(runtime.mode, PresenceMode.EDITING)
        self.assertIn(second.lease_identity, runtime.owned_locks)
        _shutdown_coordinator(coordinator)

    def test_edit_lease_release_requires_the_exact_owned_handle(self):
        store = _LockingStore()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
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
            SQL_SCHEMA_V1.version,
        )
        resource = ResourceRef("condition", "42", 8)
        owned_lock = ResourceLock("database", resource, "owned-lock")
        draft = drafts.begin(
            draft_type="condition_editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
            operation_id="edit-condition",
        )
        drafts.activate(draft.draft_id, (owned_lock,), runtime_generation=1)
        runtime = _DatabaseRuntime("database", 1)
        runtime.session = DatabaseSession("database", "session")
        runtime.edit_depth = 1
        runtime.mode = PresenceMode.EDITING
        runtime.owned_locks = {resource.lease_identity: owned_lock}
        runtime.draft_ids = {frozenset((resource.lease_identity,)): draft.draft_id}
        coordinator._runtimes["database"] = runtime
        forged = EditLeaseHandle(
            database_id="database",
            draft_id=draft.draft_id,
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(resource,),
            locks=(ResourceLock("database", resource, "forged-lock"),),
        )
        coordinator.end_edit_lease(forged)
        coordinator._process_release_requests(runtime)
        self.assertEqual(runtime.owned_locks, {resource.lease_identity: owned_lock})
        self.assertIsNotNone(drafts.get(draft.draft_id))
        self.assertEqual(store.released, [])
        _shutdown_coordinator(coordinator)

    def test_edit_lease_release_ignores_optional_bid_context_in_lock_identity(self):
        store = _LockingStore()
        sessions = DatabaseSessionRegistry()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            DatabaseDescriptorRegistry(),
            store,
            _RemoteReader(),
            _Dispatcher(),
            _Reconciliation(),
            DatabaseCapabilityService(DatabaseDescriptorRegistry(), _PermissionProbe()),
            sessions,
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
        )
        requested = ResourceRef("condition", "42", 8)
        stored = ResourceRef("condition", "42")
        owned_lock = ResourceLock("database", stored, "owned-lock")
        draft = drafts.begin(
            draft_type="condition_editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(requested,),
            operation_id="edit-condition",
        )
        drafts.activate(draft.draft_id, (owned_lock,), runtime_generation=1)
        runtime = _DatabaseRuntime("database", 1)
        runtime.session = DatabaseSession("database", "session")
        runtime.edit_depth = 1
        runtime.mode = PresenceMode.EDITING
        runtime.owned_locks = {stored.lease_identity: owned_lock}
        runtime.draft_ids = {frozenset((requested.lease_identity,)): draft.draft_id}
        coordinator._runtimes["database"] = runtime
        sessions.register("database", "session")
        sessions.register_lock("database", stored, owned_lock.lock_token)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id=draft.draft_id,
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(requested,),
            locks=(owned_lock,),
        )
        coordinator.end_edit_lease(handle)
        coordinator._process_release_requests(runtime)
        self.assertEqual(len(store.released), 1)
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.draft_ids, {})
        self.assertEqual(runtime.edit_depth, 0)
        self.assertIsNone(drafts.get(draft.draft_id))
        self.assertEqual(sessions.lock_tokens("database", (requested,)), ())
        _shutdown_coordinator(coordinator)


class SqlCollaborationCoordinatorInitialOpeningCompletionTests(unittest.TestCase):
    def _coordinator(self):
        callback = Mock()
        runtime = _DatabaseRuntime("database", 1, initial_open_callback=callback)
        coordinator = object.__new__(SqlCollaborationCoordinator)
        coordinator._lock = threading.Lock()
        coordinator._runtimes = {"database": runtime}
        coordinator._event_bus = Mock()
        coordinator._capabilities = Mock()
        coordinator._capabilities.is_editable.return_value = True
        return coordinator, runtime, callback

    def test_initial_completion_waits_for_healthy_and_fires_once(self):
        coordinator, runtime, callback = self._coordinator()
        coordinator._set_state("database", SynchronizationState.CONNECTING)
        coordinator._set_state("database", SynchronizationState.CATCHING_UP)
        callback.assert_not_called()
        coordinator._on_connection_restored(("database", runtime.generation + 1, 0))
        callback.assert_not_called()
        coordinator._set_state("database", SynchronizationState.HEALTHY)
        callback.assert_called_once_with(True, "")
        coordinator._set_state(
            "database", SynchronizationState.DISCONNECTED, "later outage"
        )
        callback.assert_called_once()

    def test_initial_failure_or_denied_editability_cannot_report_success(self):
        for state in (
            SynchronizationState.DISCONNECTED,
            SynchronizationState.READ_ONLY,
            SynchronizationState.RECONCILIATION_REQUIRED,
            SynchronizationState.HEALTHY,
        ):
            coordinator, runtime, callback = self._coordinator()
            coordinator._capabilities.is_editable.return_value = False
            coordinator._set_state("database", state, "not ready")
            callback.assert_called_once_with(False, "not ready")
            self.assertIsNone(runtime.initial_open_callback)

    def test_reentrant_state_publication_cannot_complete_replacement_runtime(self):
        coordinator, runtime, callback = self._coordinator()
        replacement_callback = Mock()
        replacement = _DatabaseRuntime(
            "database", 2, initial_open_callback=replacement_callback
        )
        coordinator._event_bus.publish.side_effect = (
            lambda *_args, **_kwargs: coordinator._runtimes.update(database=replacement)
        )
        coordinator._set_state("database", SynchronizationState.HEALTHY)
        callback.assert_not_called()
        replacement_callback.assert_not_called()


class SqlCollaborationRecoveryIdentityTests(unittest.TestCase):
    def test_recovered_paste_reconstructs_complete_authoritative_uid_maps(self):
        operation_id = str(uuid.uuid4())
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PLAN_ITEMS_PASTE,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoffs_collection", "7", 7),),
            bid_uid=7,
            page_uid="20",
            payload={"source": "clipboard"},
        )
        durable = DurableOperationResult(
            database_id="database",
            operation_id=operation_id,
            found=True,
            mutation_type=request.mutation_type.value,
            request_hash=request.request_hash,
            result_format_version=1,
            result_payload=(
                '{"value":{"annotation_uids":{"rect/a":"200"},'
                '"condition_uids":{"c":"300"},'
                '"takeoff_uids":{"t":"100"}},"value_available":true}'
            ),
        )
        recovered = SqlCollaborationCoordinator._recovered_authoritative_result(
            request,
            durable,
        )
        self.assertEqual(recovered.created_resource_ids, ("100", "200"))
        self.assertEqual(
            dict(recovered.created_uid_maps),
            {
                "takeoffs": (("t", "100"),),
                "annotations": (("rect/a", "200"),),
                "conditions": (("c", "300"),),
            },
        )
        self.assertEqual(recovered.affected_condition_uids, ("300",))

    def test_recovered_import_reconstructs_every_authoritative_identity_family(self):
        operation_id = str(uuid.uuid4())
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PROJECT_IMPORT,
            owning_surface="project-import",
            resources=(ResourceRef("project_bids", "9"),),
            payload=ProjectImportPayload(
                source_path="C:/imports/project.ost",
                source_kind="ost",
                source_size=123,
                source_modified_ns=456,
                target_project_uid="9",
            ),
        )
        durable = DurableOperationResult(
            database_id="database",
            operation_id=operation_id,
            found=True,
            mutation_type=request.mutation_type.value,
            request_hash=request.request_hash,
            result_format_version=1,
            result_payload=json.dumps(
                {
                    "value": {
                        "project_uids": {"target": "9"},
                        "bid_uids": {"b": "10"},
                        "page_uids": {"p": "20"},
                        "condition_uids": {"c": "30"},
                        "layer_uids": {"l": "40"},
                        "area_uids": {"r": "50"},
                        "takeoff_uids": {"t": "60"},
                        "annotation_uids": {"rect/a": "70"},
                    },
                    "value_available": True,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        recovered = SqlCollaborationCoordinator._recovered_authoritative_result(
            request, durable
        )
        self.assertEqual(recovered.affected_page_uids, ("20",))
        self.assertEqual(recovered.affected_condition_uids, ("30",))
        self.assertEqual(
            set(dict(recovered.created_uid_maps)),
            {
                "projects",
                "bids",
                "pages",
                "conditions",
                "layers",
                "areas",
                "takeoffs",
                "annotations",
            },
        )
        self.assertEqual(
            recovered.affected_families,
            (
                "hierarchy",
                "conditions",
                "areas",
                "pages",
                "layers",
                "takeoffs",
                "annotations",
                "cover_sheet",
                "master_data",
            ),
        )

    def test_recovered_annotations_allow_target_uid_collision_across_types(self):
        operation_id = str(uuid.uuid4())
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PLAN_ITEMS_PASTE,
            owning_surface="main-plan",
            resources=(ResourceRef("annotation", "rect/a", 7),),
            bid_uid=7,
            page_uid="20",
            payload={"source": "clipboard"},
        )

        def recover(annotation_uids):
            durable = DurableOperationResult(
                database_id="database",
                operation_id=operation_id,
                found=True,
                mutation_type=request.mutation_type.value,
                request_hash=request.request_hash,
                result_format_version=1,
                result_payload=json.dumps(
                    {
                        "value": {
                            "annotation_uids": annotation_uids,
                            "condition_uids": {},
                            "takeoff_uids": {},
                        },
                        "value_available": True,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
            return SqlCollaborationCoordinator._recovered_authoritative_result(
                request,
                durable,
            )

        recovered = recover({"rect/a": "200", "oval/b": "200"})
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.created_resource_ids, ("200", "200"))
        self.assertEqual(
            dict(recovered.created_uid_maps)["annotations"],
            (("oval/b", "200"), ("rect/a", "200")),
        )
        self.assertIsNone(recover({"rect/a": "200", "rect/b": "200"}))
