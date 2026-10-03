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
from dataclasses import replace
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
    MutationRejectionReason,
    PageSettingsPayload,
    PendingMutationState,
    PendingSqlOperationRecord,
    PlanPropertyPayload,
    PresenceMode,
    ProjectImportPayload,
    ProjectWritePayload,
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
    _OwnPublicationGuard,
    _QueuedMutation,
    _WorkerEndReason,
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
    _ServerBackedStore,
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
import queue
from dataclasses import (
    FrozenInstanceError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    COLLABORATION_LOCK_SECONDS,
    COLLABORATION_STALE_SECONDS,
    EditLeaseRequest,
)
from ost_visualizer.application.dtos.local_draft_dtos import (
    LocalDraftState,
)
from tests.helpers.sql.collaboration import (
    _FakeSqlServerState,
    _ThreadRecordingEventBus,
    _UiThreadDispatcher,
)


class _CheckpointAwareStore(_CollaborationStore):
    """Model the feed's after-version contract for repeated worker polls."""

    def __init__(self):
        super().__init__()
        self.checkpoint_seen = threading.Event()

    def poll_changes(self, database_id, after_version, limit, excluding_session_id):
        result = super().poll_changes(
            database_id, after_version, limit, excluding_session_id
        )
        observed = replace(
            result.observed_batch,
            changes=tuple(
                change
                for change in result.observed_batch.changes
                if change.commit_version > after_version
            ),
        )
        remote = replace(
            result.remote_batch,
            batch=replace(
                result.remote_batch.batch,
                changes=tuple(
                    change
                    for change in result.remote_batch.batch.changes
                    if change.commit_version > after_version
                ),
            ),
        )
        if self.change is not None and after_version >= self.change.commit_version:
            self.checkpoint_seen.set()
        return DatabaseChangePollResult(observed_batch=observed, remote_batch=remote)


def _state_signal(events, database_id, state):
    """Return an Event set once the coordinator publishes `state` for the database.
    Waiting on the published state is the readiness contract for worker-thread
    tests: `store.started` and `store.polled` fire before the runtime is editable.
    """
    reached = threading.Event()

    def observe(**payload):
        if payload["database_id"] == database_id and payload["state"] == state.value:
            reached.set()

    events.subscribe(AppEvents.COLLABORATION_STATE_CHANGED, observe)
    return reached


class SqlCollaborationStartupCancellationTests(unittest.TestCase):
    def test_late_startup_result_does_not_start_more_work(self):
        for outcome in ("committed", "cancelled", "os_error", "login_timeout"):
            with self.subTest(outcome=outcome):
                entered = threading.Event()
                release = threading.Event()
                finished = threading.Event()
                shutdown_results = []

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
                        self.assertNoLogs(
                            "ost_visualizer.application.services."
                            "sql_collaboration_coordinator",
                            level="ERROR",
                        ),
                        patch.object(
                            tokens, "load_database", wraps=tokens.load_database
                        ) as load,
                        patch.object(
                            reader,
                            "initial_reconciliation",
                            wraps=reader.initial_reconciliation,
                        ) as hydrate,
                        patch.object(
                            coordinator,
                            "_on_session_started",
                            wraps=coordinator._on_session_started,
                        ) as started,
                        patch.object(
                            store, "start_session", wraps=store.start_session
                        ) as connect,
                        patch.object(
                            store, "close_session", wraps=store.close_session
                        ) as close,
                    ):
                        self.assertTrue(
                            coordinator.start_database(descriptor.database_id)
                        )
                        self.assertTrue(entered.wait(2))
                        runtime = coordinator._runtime(descriptor.database_id)
                        coordinator.request_shutdown(
                            lambda *result: (
                                shutdown_results.append(result),
                                finished.set(),
                            )
                        )
                        self.assertFalse(finished.is_set())
                        release.set()
                        self.assertTrue(finished.wait(2))
                        self.assertEqual(shutdown_results, [(True, "")])
                        self.assertEqual(
                            coordinator.shutdown_state,
                            CollaborationShutdownState.CLOSED,
                        )
                        self.assertEqual(connect.call_count, 1)
                        self.assertEqual(runtime.cleanup_errors, [])
                        load.assert_not_called()
                        hydrate.assert_not_called()
                        started.assert_not_called()
                        self.assertFalse(store.polled.is_set())
                        self.assertEqual(store.closed.is_set(), outcome == "committed")
                        self.assertEqual(close.call_count, int(outcome == "committed"))
                        if outcome == "committed":
                            self.assertEqual(
                                close.call_args.args[:2],
                                (descriptor.database_id, store.session_id),
                            )
                finally:
                    release.set()
                    _shutdown_coordinator(coordinator)


class _SqlCollaborationCoordinatorCollaborationFixture(unittest.TestCase):
    def ready_coordinator(
        self,
        *,
        store=None,
        reconciliation=None,
        journal=None,
        cleanup_success=True,
        dispatcher=None,
        event_bus=None,
        polling_policy=None,
    ):
        """Install an editable runtime without starting a background polling loop."""
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
            store if store is not None else _LockingStore(),
            _RemoteReader(),
            dispatcher if dispatcher is not None else _Dispatcher(),
            reconciliation if reconciliation is not None else _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            event_bus if event_bus is not None else _EventBus(),
            SQL_SCHEMA_V1.version,
            *(() if polling_policy is None else (polling_policy,)),
            operation_journal=(
                journal if journal is not None else _PendingOperationJournal()
            ),
        )
        if cleanup_success:
            self.addCleanup(_shutdown_coordinator, coordinator)
        else:
            self.addCleanup(self.assert_failed_shutdown, coordinator)
        runtime = _DatabaseRuntime(descriptor.database_id, 4)
        runtime.session = DatabaseSession(descriptor.database_id, str(uuid.uuid4()))
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._sessions.register(
            descriptor.database_id, runtime.session.session_id
        )
        if isinstance(coordinator._store, _ServerBackedStore):
            coordinator._store.state.start(runtime.session.session_id)
        return coordinator, runtime

    def assert_failed_shutdown(self, coordinator):
        expected_message = "; ".join(
            error
            for runtime in coordinator._runtimes.values()
            for error in runtime.cleanup_errors
        )
        self.assertTrue(
            expected_message, "The test must establish its expected cleanup failure"
        )
        finished = threading.Event()
        results = []
        coordinator.request_shutdown(
            lambda *result: (results.append(result), finished.set())
        )
        self.assertTrue(finished.wait(2), "Failed shutdown was not reported")
        self.assertEqual(results, [(False, expected_message)])
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.CLEANUP_FAILED
        )


class SqlCollaborationCoordinatorCollaborationTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator: lifecycle and combined contracts."""

    def test_local_projection_failure_keeps_exception_diagnostic(self):
        reconciliation = _RaisingReconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        results = []
        authoritative = AuthoritativeMutationResult(created_resource_ids=("501",))
        result = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=str(uuid.uuid4()),
            created_resource_ids=("501",),
            authoritative_result=authoritative,
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(runtime.database_id, "epoch", 0, 1)
        )
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as captured:
            coordinator._apply_local_mutation_result(
                (results.append, result, hydrated, runtime.session_generation, None)
            )
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(
            captured.records[0].getMessage(),
            "SQL local-completion reconciliation failed",
        )
        self.assertIsInstance(captured.records[0].exc_info[1], RuntimeError)
        self.assertEqual(
            str(captured.records[0].exc_info[1]), "reconciliation callback failed"
        )
        self.assertEqual(
            results,
            [
                replace(
                    result,
                    outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                    message="The SQL mutation committed, but its local projection failed.",
                    commit_attempted=True,
                )
            ],
        )
        self.assertIs(results[0].authoritative_result, authoritative)

    def test_granted_lease_is_released_when_ui_callback_fails(self):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        resource = ResourceRef("condition", "11", 7)
        delivered = []

        def broken_callback(result):
            delivered.append(result)
            raise RuntimeError("closed editor")

        coordinator.request_local_edit(
            runtime.database_id,
            (resource,),
            broken_callback,
            operation_id="edit-condition",
            owning_surface="condition-sidebar",
        )
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as captured:
            coordinator._process_edit_requests(runtime)
        self.assertEqual(len(delivered), 1)
        self.assertTrue(delivered[0].granted)
        handle = delivered[0].handle
        self.assertIsNotNone(handle)
        self.assertEqual(handle.resources, (resource,))
        self.assertEqual(handle.database_id, runtime.database_id)
        self.assertEqual(str(captured.records[0].exc_info[1]), "closed editor")
        self.assertEqual(runtime.release_requests.qsize(), 1)
        self.assertEqual(store.released, [])
        coordinator._process_release_requests(runtime)
        self.assertEqual(
            store.released,
            [(runtime.database_id, runtime.session.session_id, "lock-token")],
        )
        self.assertIsNone(coordinator._local_drafts.get(handle.draft_id))
        self.assertEqual(runtime.draft_ids, {})
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.edit_depth, 0)
        self.assertEqual(runtime.mode, PresenceMode.VIEWING)
        self.assertEqual(
            coordinator._sessions.lock_tokens(runtime.database_id, (resource,)), ()
        )
        coordinator._process_release_requests(runtime)
        self.assertEqual(len(store.released), 1)
        self.assertEqual(len(delivered), 1)

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
        store = _CollaborationStore()  # Acquiring or releasing a lock is an error.
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            store=store, reconciliation=reconciliation
        )
        database_id = runtime.database_id
        resource = ResourceRef("takeoff", "42", 8)
        dependency = ResourceRef("page", "20", 8)
        lock = ResourceLock(database_id, resource, "lock-token")
        drafts = coordinator._local_drafts
        draft = drafts.begin(
            draft_type="takeoffs_gesture",
            database_id=database_id,
            bid_uid=8,
            page_uid=20,
            owning_surface="main-plan",
            affected_resources=(resource,),
            dependency_resources=(dependency,),
            operation_id="gesture-operation",
        )
        drafts.activate(draft.draft_id, (lock,), runtime_generation=runtime.generation)
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id=draft.draft_id,
            runtime_generation=runtime.generation,
            operation_id="gesture-operation",
            owning_surface="main-plan",
            resources=(resource,),
            dependency_resources=(dependency,),
            locks=(lock,),
        )
        runtime.draft_ids[frozenset((resource.lease_identity,))] = draft.draft_id
        runtime.owned_locks[resource.lease_identity] = lock
        runtime.edit_depth = 1
        runtime.mode = PresenceMode.EDITING
        coordinator._sessions.register_lock(database_id, resource, lock.lock_token)
        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            owning_surface="main-plan",
            resources=(resource,),
            dependency_resources=(dependency,),
            payload={"takeoff_uid": "42"},
            edit_lease_handle=handle,
        )
        calls = []
        results = []

        def operation():
            calls.append("write")
            return replace(
                _committed_execution(), consumed_lock_tokens=(lock.lock_token,)
            )

        self.assertGreaterEqual(
            coordinator.queue_request(request, operation, results.append), 0
        )
        self.assertEqual(calls, [])
        self.assertEqual(results, [])
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["write"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(results[0].operation_id, request.operation_id)
        self.assertEqual(len(reconciliation.batches), 1)
        self.assertEqual(reconciliation.batches[0].batch.database_id, database_id)
        self.assertIsNone(drafts.get(draft.draft_id))
        self.assertEqual(runtime.draft_ids, {})
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.edit_depth, 0)
        self.assertEqual(runtime.mode, PresenceMode.VIEWING)
        self.assertEqual(
            coordinator._sessions.lock_tokens(database_id, (resource,)), ()
        )
        self.assertEqual(coordinator._pending_mutations.for_database(database_id), ())
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["write"])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(reconciliation.batches), 1)

    def test_condition_editor_lease_validates_navigation_subset_and_rejects_stale_ownership(
        self,
    ):
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
        for changes in (
            {"database_id": "another-database"},
            {"owning_surface": "detached-plan"},
            {"resources": (ResourceRef("condition", "44", 8),)},
            {"resources": (ResourceRef("condition", "42", 9),)},
        ):
            with self.subTest(request_changes=changes):
                self.assertIsNone(
                    coordinator._validated_mutation_edit_lease(
                        runtime, replace(queued, **changes), handle
                    )
                )
        for changes in (
            {"draft_id": "missing-draft"},
            {"resources": (edited,)},
            {"dependency_resources": (ResourceRef("page", "20", 8),)},
            {
                "locks": (
                    replace(edited_lock, lock_token="replaced-token"),
                    navigable_lock,
                )
            },
        ):
            with self.subTest(handle_changes=changes):
                self.assertIsNone(
                    coordinator._validated_mutation_edit_lease(
                        runtime, queued, replace(handle, **changes)
                    )
                )
        runtime.generation += 1
        self.assertIsNone(
            coordinator._validated_mutation_edit_lease(runtime, queued, handle)
        )
        runtime.generation -= 1
        runtime.owned_locks[edited.lease_identity] = replace(
            edited_lock, lock_token="new-lock"
        )
        self.assertIsNone(
            coordinator._validated_mutation_edit_lease(runtime, queued, handle)
        )
        runtime.owned_locks[edited.lease_identity] = edited_lock
        self.assertIs(
            coordinator._validated_mutation_edit_lease(runtime, queued, handle),
            drafts.get(draft.draft_id),
        )
        drafts.finish(draft.draft_id)
        self.assertIsNone(
            coordinator._validated_mutation_edit_lease(runtime, queued, handle)
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
        self.addCleanup(_shutdown_coordinator, coordinator)
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
        self.assertEqual(status.conflicted_resources, frozenset((conflicted,)))
        self.assertTrue(runtime.recovery_requested)
        self.assertFalse(runtime.healthy)
        self.assertTrue(runtime.pending_delivery)
        self.assertFalse(capabilities.is_editable(descriptor.database_id))
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.COLLABORATION_STATE_CHANGED,
                    {
                        "database_id": descriptor.database_id,
                        "state": SynchronizationState.CONFLICTED.value,
                        "message": "A pending remote transaction overlaps this draft.",
                    },
                ),
                (
                    AppEvents.DATABASE_CAPABILITIES_CHANGED,
                    {"file_path": descriptor.database_id},
                ),
            ],
        )
        coordinator.enter_resource_conflict("not-open", conflicted, "stale conflict")
        self.assertEqual(len(events.published), 2)

    def test_self_change_checkpoint_waits_for_main_thread_reconciliation_gate(self):
        store = _CollaborationStore()
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            store=store, reconciliation=reconciliation
        )
        store.change = _change(
            runtime.database_id,
            ResourceRef("condition", "42", 8),
            source=runtime.session.session_id,
        )
        dispatcher = _DelayedReconciliationDispatcher()
        coordinator._dispatcher = dispatcher
        coordinator._poll_once(runtime)
        self.assertEqual(runtime.acknowledged_version, 0)
        self.assertEqual(runtime.observed_high_water_version, 1)
        self.assertTrue(runtime.pending_delivery)
        self.assertEqual(len(dispatcher.pending), 1)
        self.assertEqual(reconciliation.batches, [])
        coordinator._poll_once(runtime)
        self.assertEqual(len(dispatcher.pending), 1)
        dispatcher.deliver_pending()
        self.assertEqual(runtime.acknowledged_version, 1)
        self.assertFalse(runtime.pending_delivery)
        self.assertEqual(len(reconciliation.batches), 1)
        self.assertEqual(
            reconciliation.batches[0].batch.database_id, runtime.database_id
        )
        self.assertEqual(reconciliation.batches[0].batch.changes, ())
        self.assertEqual(reconciliation.batches[0].batch.delivered_through_version, 1)
        dispatcher.deliver_pending()
        self.assertEqual(len(reconciliation.batches), 1)

    def test_malformed_session_start_has_distinct_failure_classification(self):
        for failure_kind, reason in (
            (
                ReconciliationFailureKind.MALFORMED_PAYLOAD,
                "The SQL session-start reconciliation payload was malformed.",
            ),
            (None, "The SQL database could not be reconciled at session start."),
        ):
            with self.subTest(failure_kind=failure_kind):
                reconciliation = _Reconciliation()
                reconciliation.result = False
                reconciliation.failure_kind = failure_kind
                coordinator, runtime = self.ready_coordinator(
                    reconciliation=reconciliation
                )
                opened = []
                runtime.initial_open_callback = lambda *args: opened.append(args)
                hydrated = HydratedDatabaseChangeBatch(
                    _batch(runtime.database_id, "epoch", 0, 7)
                )
                coordinator._on_session_started(
                    (
                        runtime.database_id,
                        runtime.generation,
                        runtime.session_generation,
                        hydrated,
                        None,
                    )
                )
                self.assertEqual(reconciliation.batches, [hydrated])
                self.assertEqual(opened, [(False, reason)])
                self.assertTrue(runtime.ready_event.is_set())
                self.assertFalse(runtime.healthy)
                self.assertTrue(runtime.pending_delivery)
                self.assertTrue(runtime.recovery_requested)
                self.assertEqual(runtime.acknowledged_version, 0)
                self.assertEqual(
                    coordinator._event_bus.published,
                    [
                        (
                            AppEvents.COLLABORATION_STATE_CHANGED,
                            {
                                "database_id": runtime.database_id,
                                "state": SynchronizationState.RECONCILIATION_REQUIRED.value,
                                "message": reason,
                            },
                        ),
                        (
                            AppEvents.DATABASE_CAPABILITIES_CHANGED,
                            {"file_path": runtime.database_id},
                        ),
                        (
                            AppEvents.FULL_RECONCILIATION_REQUIRED,
                            {
                                "database_id": runtime.database_id,
                                "reason": reason,
                            },
                        ),
                    ],
                )

    def test_queued_mutation_can_be_cancelled_before_worker_execution(self):
        journal = _PendingOperationJournal()
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            journal=journal, reconciliation=reconciliation
        )
        calls = []
        results = []
        sequence = _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: calls.append(True) or _committed_execution("501"),
            results.append,
            operation_id="cancel-placement",
        )
        self.assertEqual(sequence, runtime.generation)
        pending = coordinator._pending_mutations.for_database(runtime.database_id)
        self.assertEqual(len(pending), 1)
        operation_id = pending[0].request.operation_id
        self.assertEqual(set(journal.records), {operation_id})
        self.assertTrue(
            coordinator.cancel_queued_mutation(runtime.database_id, operation_id)
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status, MutationOutcomeStatus.CANCELLED_BEFORE_START
        )
        self.assertEqual(results[0].operation_id, operation_id)
        self.assertEqual(results[0].database_id, runtime.database_id)
        self.assertFalse(results[0].commit_attempted)
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})
        self.assertEqual(runtime.cancelled_mutation_ids, set())
        self.assertEqual(reconciliation.batches, [])
        self.assertFalse(
            coordinator.cancel_queued_mutation(runtime.database_id, operation_id)
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(len(results), 1)

    def test_queued_mutation_capacity_rejects_only_the_sixty_fifth_request(self):
        journal = _PendingOperationJournal()
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            journal=journal, reconciliation=reconciliation
        )
        runtime.healthy = False
        runtime.pending_delivery = True
        results = []
        calls = []
        requests = [
            QueuedMutationRequest(
                database_id=runtime.database_id,
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
                owning_surface="main-plan",
                resources=(ResourceRef("takeoffs_collection", "8", 8),),
                payload={"index": index},
            )
            for index in range(65)
        ]

        def submit(index):
            def operation():
                calls.append(index)
                return _committed_execution(str(501 + index))

            return coordinator.queue_request(requests[index], operation, results.append)

        for index in range(64):
            self.assertEqual(submit(index), runtime.generation)
        self.assertEqual(submit(64), -1)
        self.assertEqual(runtime.mutation_requests.qsize(), 64)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].operation_id, requests[64].operation_id)
        self.assertEqual(results[0].outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertIn("queue is full", results[0].message.lower())
        self.assertEqual(
            set(journal.records), {request.operation_id for request in requests[:64]}
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(reconciliation.batches, [])
        runtime.healthy = True
        runtime.pending_delivery = False
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [0])
        self.assertEqual(submit(64), runtime.generation)
        for _ in range(64):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, list(range(65)))
        self.assertEqual(
            [result.operation_id for result in results[1:]],
            [request.operation_id for request in requests],
        )
        self.assertEqual(
            [result.outcome_status for result in results[1:]],
            [MutationOutcomeStatus.COMMITTED] * 65,
        )
        self.assertEqual(
            [result.created_resource_ids for result in results[1:]],
            [(str(501 + index),) for index in range(65)],
        )
        self.assertEqual(len(reconciliation.batches), 65)
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})
        self.assertTrue(runtime.mutation_requests.empty())

    def test_queue_rejects_mutation_when_initial_journal_write_fails(self):
        journal = _FailingPendingOperationJournal(1)
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            journal=journal, reconciliation=reconciliation
        )
        results = []
        calls = []
        request = QueuedMutationRequest(
            database_id=runtime.database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoffs_collection", "8", 8),),
            payload={"test_operation": "journal-initial-failure"},
        )

        def operation():
            calls.append("write")
            return _committed_execution("501")

        sequence = coordinator.queue_request(request, operation, results.append)
        self.assertEqual(sequence, -1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].operation_id, request.operation_id)
        self.assertEqual(results[0].outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertIn("recorded safely", results[0].message)
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})
        self.assertTrue(runtime.mutation_requests.empty())
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(reconciliation.batches, [])
        # The same otherwise-valid request is accepted once durable recording recovers.
        self.assertGreaterEqual(
            coordinator.queue_request(request, operation, results.append), 0
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["write"])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1].outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(results[1].created_resource_ids, ("501",))
        self.assertEqual(results[1].operation_id, request.operation_id)
        self.assertEqual(len(reconciliation.batches), 1)
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})

    def test_recovered_completion_preserves_committed_result_while_editing_disabled(
        self,
    ):
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(journal=journal)
        coordinator._capabilities.set_collaboration_state(
            runtime.database_id, SynchronizationState.RECONCILIATION_REQUIRED
        )
        self.assertFalse(coordinator._capabilities.is_editable(runtime.database_id))
        request = QueuedMutationRequest(
            database_id=runtime.database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoffs_collection", "8", 8),),
            payload={"test_operation": "recovered-projection"},
        )
        pending = coordinator._pending_mutations
        pending.begin(request, runtime_generation=runtime.generation)
        pending.transition(request.operation_id, PendingMutationState.RECOVERING)
        pending.transition(request.operation_id, PendingMutationState.PROJECTING)
        journal.save(
            PendingSqlOperationRecord.from_request(
                request, PendingMutationState.PROJECTING
            )
        )
        results = []
        result = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            created_resource_ids=("501",),
            authoritative_result=AuthoritativeMutationResult(
                created_resource_ids=("501",), affected_families=("takeoffs",)
            ),
            commit_attempted=True,
        )
        coordinator._complete_mutation_request((results.append, result))
        self.assertEqual(results, [result])
        self.assertIs(results[0], result)
        self.assertEqual(pending.for_database(runtime.database_id), ())
        self.assertEqual(journal.records, {})
        self.assertFalse(coordinator._capabilities.is_editable(runtime.database_id))
        self.assertEqual(
            coordinator._event_bus.published,
            [
                (
                    AppEvents.COLLABORATION_MUTATION_STATE_CHANGED,
                    {
                        "database_id": runtime.database_id,
                        "operation_id": request.operation_id,
                        "mutation_type": request.mutation_type.value,
                        "state": PendingMutationState.QUEUED.value,
                        "message": "",
                        "pending_count": 0,
                    },
                )
            ],
        )

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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertIsNone(coordinator._runtime(descriptor.database_id))
        coordinator._request_committed_projection_recovery(
            descriptor.database_id,
            "The committed projection could not be attached to a runtime.",
        )
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.FULL_RECONCILIATION_REQUIRED,
                    {
                        "database_id": descriptor.database_id,
                        "reason": (
                            "The committed projection could not be attached to a runtime."
                        ),
                    },
                )
            ],
        )
        self.assertEqual(coordinator._runtimes, {})

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
        reconciliation = _Reconciliation()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            dispatcher,
            reconciliation,
            DatabaseCapabilityService(descriptors, _PermissionProbe()),
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
            pending_mutations=pending,
            operation_journal=journal,
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        first_session_generation = coordinator._install_session(
            runtime,
            DatabaseSession(descriptor.database_id, str(uuid.uuid4())),
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
        self.assertEqual(len(dispatcher.pending), 1)
        self.assertEqual(results, [])
        self.assertEqual(reconciliation.batches, [hydrated])
        second_session_generation = coordinator._install_session(
            runtime,
            DatabaseSession(descriptor.database_id, str(uuid.uuid4())),
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
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0],
            QueuedMutationResult(
                database_id=descriptor.database_id,
                runtime_generation=runtime.generation,
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("501",), affected_families=("takeoffs",)
                ),
                commit_attempted=True,
            ),
        )
        self.assertEqual(reconciliation.batches, [hydrated, hydrated])
        self.assertTrue(runtime.mutation_requests.empty())
        self.assertIsNone(pending.get(request.operation_id))
        self.assertNotIn(request.operation_id, coordinator._uncertain_callbacks)
        self.assertNotIn(request.operation_id, journal.records)
        coordinator._complete_recovered_mutation_request(
            (request, results[0], second_session_generation)
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(reconciliation.batches, [hydrated, hydrated])

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
            [""],
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
        valid = replace(
            durable,
            result_payload=json.dumps(
                {"value": ["501", "502"], "value_available": True}
            ),
        )
        self.assertEqual(
            SqlCollaborationCoordinator._recovered_authoritative_result(request, valid),
            AuthoritativeMutationResult(
                created_resource_ids=("501", "502"), affected_families=("takeoffs",)
            ),
        )
        for malformed in (
            "{",
            "[]",
            "null",
            json.dumps({"value": ["501"]}),
            json.dumps({"value": ["501"], "value_available": 1}),
            json.dumps({"value": ["501"], "value_available": True, "extra": 1}),
        ):
            with self.subTest(envelope=malformed):
                self.assertIsNone(
                    SqlCollaborationCoordinator._recovered_authoritative_result(
                        request, replace(valid, result_payload=malformed)
                    )
                )

    def test_lifecycle_drain_waits_for_critical_mutation_completion(self):
        reconciliation = _DeferredProjectionReconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        order = []
        mutation_results = []
        drain_results = []

        def operation():
            order.append("write")
            return _committed_execution("501")

        def completed(result):
            mutation_results.append(result)
            order.append("completion")

        def drained(success, message):
            drain_results.append((success, message))
            order.append("drain")

        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                operation,
                completed,
                operation_id="critical-drain",
            ),
            runtime.generation,
        )
        coordinator.drain_database_mutations_async(runtime.database_id, drained)
        self.assertEqual(drain_results, [])
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(order, ["write"])
        self.assertEqual(mutation_results, [])
        self.assertEqual(drain_results, [])
        self.assertIsNotNone(reconciliation.token)
        reconciliation.token.complete(True)
        self.assertEqual(order, ["write", "completion", "drain"])
        self.assertEqual(len(mutation_results), 1)
        self.assertEqual(
            mutation_results[0].outcome_status, MutationOutcomeStatus.COMMITTED
        )
        self.assertEqual(mutation_results[0].created_resource_ids, ("501",))
        self.assertEqual(drain_results, [(True, "")])
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        reconciliation.token.complete(True)
        self.assertEqual(order, ["write", "completion", "drain"])

    def test_lifecycle_drain_ignores_noncritical_view_state(self):
        coordinator, runtime = self.ready_coordinator()
        calls = []
        results = []
        drain_results = []
        request = QueuedMutationRequest(
            database_id=runtime.database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PAGE_SETTINGS,
            owning_surface="main-plan",
            resources=(ResourceRef("page", "107", 8),),
            page_uid="107",
            payload=PageSettingsPayload.from_updates("show_mode", [("107", 0)]),
            lifecycle_critical=False,
        )

        def operation():
            calls.append("write")
            return _committed_execution()

        self.assertEqual(
            coordinator.queue_request(request, operation, results.append),
            runtime.generation,
        )
        coordinator.drain_database_mutations_async(
            runtime.database_id, lambda *result: drain_results.append(result)
        )
        self.assertEqual(drain_results, [(True, "")])
        self.assertEqual(calls, [])
        self.assertEqual(results, [])
        self.assertIsNotNone(coordinator._pending_mutations.get(request.operation_id))
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["write"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].operation_id, request.operation_id)
        self.assertEqual(results[0].outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(results[0].created_resource_ids, ())
        self.assertEqual(drain_results, [(True, "")])
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )

    def test_queued_mutation_release_value_error_finishes_draft_and_all_locks(self):
        release_failure = ValueError("lock ownership changed")

        class _ValueErrorReleaseStore(_LockingStore):
            def release_lock(self, database_id, session_id, lock_token):
                super().release_lock(database_id, session_id, lock_token)
                if lock_token == "first":
                    raise release_failure

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
        self.addCleanup(_shutdown_coordinator, coordinator)
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
        drafts.activate(draft.draft_id, locks, runtime_generation=1)
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
        self.assertIs(failure, release_failure)
        self.assertEqual(
            store.released,
            [
                (descriptor.database_id, session.session_id, "first"),
                (descriptor.database_id, session.session_id, "second"),
            ],
        )
        self.assertIsNone(drafts.get(draft.draft_id))
        self.assertEqual(
            sessions.lock_tokens(descriptor.database_id, (resource_a, resource_b)), ()
        )

    def test_new_session_clears_previous_session_pending_delivery(self):
        runtime = _DatabaseRuntime("database", 1)
        runtime.session = DatabaseSession("database", str(uuid.uuid4()))
        runtime.session_generation = 1
        runtime.acknowledged_version = 7
        runtime.observed_high_water_version = 12
        runtime.feed_epoch = "old-epoch"
        runtime.pending_delivery = True
        runtime.healthy = True
        replacement = DatabaseSession(
            "database", str(uuid.uuid4()), last_acknowledged_version=20
        )
        session_generation = SqlCollaborationCoordinator._install_session(
            runtime, replacement
        )
        self.assertIs(runtime.session, replacement)
        self.assertEqual((session_generation, runtime.session_generation), (2, 2))
        self.assertEqual(runtime.acknowledged_version, 20)
        self.assertEqual(runtime.observed_high_water_version, 20)
        self.assertEqual(runtime.feed_epoch, "")
        self.assertFalse(runtime.pending_delivery)
        self.assertFalse(runtime.healthy)

    def test_sql_lease_request_denies_when_collaboration_is_not_editable(self):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        resource = ResourceRef("condition", "42", 8)
        with patch.object(store, "acquire_locks", wraps=store.acquire_locks) as acquire:
            for state in (
                SynchronizationState.CONNECTING,
                SynchronizationState.CATCHING_UP,
                SynchronizationState.READ_ONLY,
                SynchronizationState.RECONCILIATION_REQUIRED,
            ):
                with self.subTest(state=state):
                    coordinator._capabilities.set_collaboration_state(
                        runtime.database_id, state
                    )
                    results = []
                    coordinator.request_local_edit(
                        runtime.database_id, (resource,), results.append
                    )
                    self.assertEqual(
                        results,
                        [
                            EditLeaseResult(
                                False, "SQL collaboration is not ready for editing."
                            )
                        ],
                    )
                    self.assertTrue(runtime.edit_requests.empty())
                    coordinator._process_edit_requests(runtime)
                    self.assertEqual(len(results), 1)
                    self.assertEqual(runtime.owned_locks, {})
                    self.assertEqual(coordinator._local_drafts._drafts, {})
                    acquire.assert_not_called()
            coordinator._capabilities.set_collaboration_state(
                runtime.database_id, SynchronizationState.HEALTHY
            )
            granted = []
            coordinator.request_local_edit(
                runtime.database_id, (resource,), granted.append
            )
            self.assertEqual(granted, [])
            coordinator._process_edit_requests(runtime)
            self.assertEqual(len(granted), 1)
            self.assertTrue(granted[0].granted)
            self.assertEqual(granted[0].handle.resources, (resource,))
            self.assertEqual(acquire.call_count, 1)
            coordinator.end_edit_lease(granted[0].handle)
            coordinator._process_release_requests(runtime)
            self.assertEqual(coordinator._local_drafts._drafts, {})
            self.assertEqual(runtime.owned_locks, {})

    def test_capability_reprobe_restarts_only_after_successful_session_cleanup(self):
        class StoppedThread:
            ident = 1

            def is_alive(self):
                return False

        coordinator, runtime = self.ready_coordinator()
        clock = _ManualClock(100.0)
        coordinator._clock = clock
        for success in (False, True):
            # D13: a re-probe restart is admitted at most once per backoff step;
            # the second re-probe comes after the first one's 1 s step.
            clock.now += 2.0
            with self.subTest(success=success):
                completions = []
                with (
                    patch.object(runtime, "thread", StoppedThread()),
                    patch.object(
                        coordinator,
                        "stop_database_async",
                        side_effect=lambda database_id, reason, callback: completions.append(
                            callback
                        ),
                    ) as stop,
                    patch.object(
                        coordinator, "start_database", return_value=True
                    ) as start,
                ):
                    coordinator._on_database_capabilities_changed(runtime.database_id)
                    self.assertEqual(stop.call_count, 1)
                    self.assertEqual(
                        stop.call_args.args[:2], (runtime.database_id, "reconfigured")
                    )
                    self.assertEqual(len(completions), 1)
                    start.assert_not_called()
                    completions[0](success, "" if success else "cleanup failed")
                    if success:
                        start.assert_called_once_with(runtime.database_id)
                    else:
                        start.assert_not_called()

    def test_heartbeat_does_not_open_a_second_permission_probe_connection(self):
        class Probe:
            def can_edit(self, _database_id):
                raise AssertionError(
                    "Heartbeat must not open another permission connection"
                )

        store = _CollaborationStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        coordinator._capabilities = DatabaseCapabilityService(
            coordinator._registry, Probe()
        )
        previous = runtime.session
        runtime.acknowledged_version = 13
        runtime.bid_uid = 8
        runtime.page_uid = 20
        runtime.mode = PresenceMode.EDITING
        with patch.object(store, "heartbeat", wraps=store.heartbeat) as heartbeat:
            coordinator._heartbeat(runtime)
        heartbeat.assert_called_once_with(
            runtime.database_id, previous.session_id, 13, 8, 20, PresenceMode.EDITING
        )
        self.assertEqual(store.start_count, 0)
        self.assertIsNot(runtime.session, previous)
        self.assertEqual(runtime.session.database_id, runtime.database_id)
        self.assertEqual(runtime.session.session_id, previous.session_id)
        self.assertEqual(runtime.session.last_acknowledged_version, 13)
        self.assertEqual(
            coordinator._event_bus.published,
            [
                (
                    AppEvents.PRESENCE_CHANGED,
                    {"database_id": runtime.database_id, "bid_uid": "8", "users": []},
                )
            ],
        )

    def test_pending_edit_dispatch_failure_cannot_skip_other_drafts_or_session_cleanup(
        self,
    ):
        for failures in ((1,), (2,), (1, 2)):
            with self.subTest(failed_dispatches=failures):
                store = _CollaborationStore()
                coordinator, runtime = self.ready_coordinator(
                    store=store, cleanup_success=False
                )
                delivered = []
                resources = (
                    ResourceRef("condition", "42", 8),
                    ResourceRef("condition", "43", 8),
                )
                for resource in resources:
                    coordinator.request_local_edit(
                        runtime.database_id,
                        (resource,),
                        lambda result, resource=resource: delivered.append(
                            (resource, result)
                        ),
                        owning_surface="condition-sidebar",
                    )
                requests = tuple(runtime.edit_requests.queue)
                self.assertEqual(len(requests), 2)
                session = runtime.session
                attempted = []

                def dispatch(callback, payload=()):
                    attempted.append((callback, payload))
                    if len(attempted) in failures:
                        raise RuntimeError("Qt dispatcher unavailable")
                    callback(payload)

                runtime.stop_event.set()
                with (
                    patch.object(
                        coordinator._dispatcher, "dispatch", side_effect=dispatch
                    ),
                    patch.object(
                        store, "close_session", wraps=store.close_session
                    ) as closed,
                ):
                    coordinator._worker(runtime)
                self.assertIsNone(runtime.session)
                closed.assert_called_once_with(
                    runtime.database_id, session.session_id, "closed"
                )
                self.assertEqual(coordinator._sessions.get(runtime.database_id), "")
                self.assertTrue(runtime.edit_requests.empty())
                self.assertEqual(
                    [
                        coordinator._local_drafts.get(request.draft_id)
                        for request, _callback in requests
                    ],
                    [None, None],
                )
                self.assertEqual(len(attempted), 2)
                self.assertEqual(
                    [resource for resource, _result in delivered],
                    [
                        resource
                        for position, resource in enumerate(resources, 1)
                        if position not in failures
                    ],
                )
                for _resource, result in delivered:
                    self.assertFalse(result.granted)
                    self.assertIsNone(result.handle)
                self.assertEqual(
                    runtime.cleanup_errors,
                    ["The SQL collaboration worker could not reject pending edits."],
                )

    def test_lease_loss_dispatch_failure_cannot_skip_session_cleanup(self):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(
            store=store, cleanup_success=False
        )
        resource = ResourceRef("takeoff", "10", bid_uid=1)
        grants = []
        coordinator.request_local_edit(
            runtime.database_id,
            (resource,),
            grants.append,
            operation_id="move",
            owning_surface="main",
        )
        coordinator._process_edit_requests(runtime)
        self.assertEqual(len(grants), 1)
        self.assertTrue(grants[0].granted)
        handle = grants[0].handle
        session = runtime.session
        with (
            patch.object(
                coordinator._dispatcher,
                "dispatch",
                side_effect=RuntimeError("Qt dispatcher unavailable"),
            ) as dispatch,
            patch.object(store, "close_session", wraps=store.close_session) as close,
        ):
            coordinator._reset_session(runtime, close_reason="closed")
        dispatch.assert_called_once_with(
            coordinator._publish_lease_loss,
            (
                EditLeaseLoss(
                    database_id=runtime.database_id,
                    draft_id=handle.draft_id,
                    runtime_generation=runtime.generation,
                    operation_id="move",
                    owning_surface="main",
                    resources=(resource,),
                    reason="closed",
                ),
            ),
        )
        self.assertIsNone(runtime.session)
        self.assertIsNone(coordinator._local_drafts.get(handle.draft_id))
        self.assertEqual(runtime.draft_ids, {})
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.edit_depth, 0)
        self.assertEqual(runtime.mode, PresenceMode.VIEWING)
        self.assertEqual(coordinator._sessions.get(runtime.database_id), "")
        self.assertEqual(
            coordinator._sessions.lock_tokens(runtime.database_id, (resource,)), ()
        )
        self.assertEqual(
            store.released, [(runtime.database_id, session.session_id, "lock-token")]
        )
        close.assert_called_once_with(runtime.database_id, session.session_id, "closed")
        self.assertEqual(
            runtime.cleanup_errors,
            ["The SQL collaboration worker could not publish edit-lease loss."],
        )

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
        self.assertEqual(
            results[0][1],
            "SQL collaboration event unsubscription failed for "
            f"{AppEvents.FILE_OPENED}: listener registry unavailable",
        )
        self.assertEqual(
            coordinator.shutdown_state,
            CollaborationShutdownState.CLEANUP_FAILED,
        )
        self.assertEqual(
            {
                event: callbacks
                for event, callbacks in event_bus.subscribers.items()
                if callbacks
            },
            {AppEvents.FILE_OPENED: [coordinator._on_file_opened]},
        )
        previous_result = results[0]
        coordinator.request_shutdown(lambda *result: results.append(result))
        self.assertEqual(results, [previous_result, previous_result])
        self.assertEqual(len(event_bus.unsubscribe_attempts), 4)

    def test_database_drain_uses_configured_timeout_and_reports_worker_state(self):
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
        self.addCleanup(_shutdown_coordinator, coordinator)

        class Thread:
            def __init__(self, alive, failure):
                self.alive = alive
                self.failure = failure
                self.timeouts = []

            def join(self, timeout):
                self.timeouts.append(timeout)
                if self.failure is not None:
                    raise self.failure

            def is_alive(self):
                return self.alive

        for alive, failure, message in (
            (
                True,
                None,
                "The SQL collaboration worker did not stop before the configured database-operation timeout.",
            ),
            (False, None, ""),
            (False, RuntimeError("join failed"), "join failed"),
        ):
            with self.subTest(alive=alive, join_error=failure):
                runtime = _DatabaseRuntime(descriptor.database_id, 1)
                runtime.thread = Thread(alive, failure)
                with patch.object(coordinator._dispatcher, "dispatch") as dispatch:
                    coordinator._drain_database(runtime)
                self.assertEqual(runtime.thread.timeouts, [10.0])
                dispatch.assert_called_once_with(
                    coordinator._complete_database_drain,
                    (descriptor.database_id, 1, not message, message),
                )
        with self.subTest(cleanup_errors=True):
            runtime = _DatabaseRuntime(descriptor.database_id, 1)
            runtime.thread = Thread(False, None)
            runtime.cleanup_errors.extend(
                ["The session could not be closed.", "A lock could not be released."]
            )
            with patch.object(coordinator._dispatcher, "dispatch") as dispatch:
                coordinator._drain_database(runtime)
            self.assertEqual(runtime.thread.timeouts, [10.0])
            dispatch.assert_called_once_with(
                coordinator._complete_database_drain,
                (
                    descriptor.database_id,
                    1,
                    False,
                    "The session could not be closed.; A lock could not be released.",
                ),
            )
        with self.subTest(unregistered_database=True):
            # Without a SQL descriptor the drain falls back to the grace period.
            runtime = _DatabaseRuntime("unregistered-database", 1)
            runtime.thread = Thread(False, None)
            with patch.object(coordinator._dispatcher, "dispatch") as dispatch:
                coordinator._drain_database(runtime)
            self.assertEqual(runtime.thread.timeouts, [5.0])
            dispatch.assert_called_once_with(
                coordinator._complete_database_drain,
                ("unregistered-database", 1, True, ""),
            )

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
        callback_lock_access = []

        def recorder(target):
            def completed(success, message):
                acquired = target._lock.acquire(blocking=False)
                callback_lock_access.append((success, message, acquired))
                if acquired:
                    target._lock.release()

            return completed

        # The callback registered by the initiating request is completed after
        # the drain and must not hold the lock either.
        coordinator.request_shutdown(recorder(coordinator))
        self.assertEqual(callback_lock_access, [(True, "", True)])
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)
        # A repeated request is answered from the terminal CLOSED state.
        coordinator.request_shutdown(recorder(coordinator))
        self.assertEqual(callback_lock_access, [(True, "", True)] * 2)
        callback_lock_access.clear()
        failed = _coordinator(
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
        failed._shutdown_state = CollaborationShutdownState.CLEANUP_FAILED
        failed._shutdown_cleanup_errors.append("cleanup failed")
        failed.request_shutdown(recorder(failed))
        self.assertEqual(callback_lock_access, [(False, "cleanup failed", True)])

    def test_stale_database_drain_cannot_clear_a_reopened_runtime(self):
        coordinator, runtime = self.ready_coordinator()
        completed = []
        old_generation = runtime.generation - 1
        coordinator._database_drains[(runtime.database_id, old_generation)] = [
            lambda *result: completed.append(result)
        ]
        before = coordinator.status(runtime.database_id)
        with patch.object(
            coordinator._concurrency_tokens,
            "clear_database",
            wraps=coordinator._concurrency_tokens.clear_database,
        ) as clear:
            coordinator._complete_database_drain(
                (runtime.database_id, old_generation, True, "")
            )
        clear.assert_not_called()
        self.assertEqual(completed, [(True, "")])
        self.assertIs(coordinator._runtime(runtime.database_id), runtime)
        self.assertEqual(coordinator.status(runtime.database_id), before)
        self.assertEqual(coordinator._event_bus.published, [])
        self.assertEqual(coordinator._database_drains, {})
        # The guard is generation-specific: the runtime's own drain still stops it.
        completed.clear()
        coordinator._database_drains[(runtime.database_id, runtime.generation)] = [
            lambda *result: completed.append(result)
        ]
        with patch.object(
            coordinator._concurrency_tokens,
            "clear_database",
            wraps=coordinator._concurrency_tokens.clear_database,
        ) as clear:
            coordinator._complete_database_drain(
                (runtime.database_id, runtime.generation, True, "")
            )
        clear.assert_called_once_with(runtime.database_id)
        self.assertEqual(completed, [(True, "")])
        self.assertEqual(
            coordinator.status(runtime.database_id).state,
            SynchronizationState.STOPPED,
        )

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
            ),
            lambda success, message: database_results.append((success, message)),
        ]
        database_results = []
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logs:
            coordinator._complete_database_drain(("database", 1, True, ""))
        self.assertEqual(len(logs.records), 1)
        self.assertIn("completion callback failed", logs.output[0])
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)
        self.assertEqual(shutdown_results, [(True, "")])
        self.assertEqual(database_results, [(True, "")])
        self.assertEqual(coordinator._database_drains, {})
        self.assertEqual(coordinator._shutdown_callbacks, [])


class SqlCollaborationCoordinatorProcessMutationRequestsTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator._process_mutation_requests."""

    def test_failed_cancellation_dispatch_does_not_strand_other_queued_mutations(self):
        for failures in ((1,), (2,), (1, 2)):
            with self.subTest(failed_dispatches=failures):
                journal = _PendingOperationJournal()
                store = _RecoverableProjectionStore()
                coordinator, runtime = self.ready_coordinator(
                    journal=journal, store=store, cleanup_success=False
                )
                results = []
                writes = []
                for index in range(2):
                    self.assertEqual(
                        _queue_test_mutation(
                            coordinator,
                            runtime.database_id,
                            (ResourceRef("takeoffs_collection", "8", 8),),
                            lambda: writes.append("unexpected write")
                            or _committed_execution("501"),
                            results.append,
                            operation_id=f"cancel-on-stop-{index}",
                        ),
                        runtime.generation,
                    )
                requests = tuple(runtime.mutation_requests.queue)
                session = runtime.session
                attempted = []

                def dispatch(callback, payload=()):
                    attempted.append((callback, payload))
                    if len(attempted) in failures:
                        raise RuntimeError("UI bridge unavailable")
                    callback(payload)

                runtime.stop_event.set()
                with (
                    patch.object(
                        coordinator._dispatcher, "dispatch", side_effect=dispatch
                    ),
                    patch.object(
                        store, "close_session", wraps=store.close_session
                    ) as close,
                ):
                    coordinator._worker(runtime)
                self.assertEqual(writes, [])
                close.assert_called_once_with(
                    runtime.database_id, session.session_id, "closed"
                )
                self.assertIsNone(runtime.session)
                self.assertTrue(runtime.mutation_requests.empty())
                self.assertEqual(len(attempted), 2)
                delivered_ids = [
                    request.operation_id
                    for index, request in enumerate(requests, 1)
                    if index not in failures
                ]
                retained_ids = [
                    request.operation_id
                    for index, request in enumerate(requests, 1)
                    if index in failures
                ]
                self.assertEqual(
                    [result.operation_id for result in results], delivered_ids
                )
                for result in results:
                    self.assertEqual(
                        result.outcome_status,
                        MutationOutcomeStatus.CANCELLED_BEFORE_START,
                    )
                    self.assertFalse(result.commit_attempted)
                # Only undeliverable completions retain existing recovery metadata.
                self.assertEqual(
                    {
                        pending.request.operation_id
                        for pending in coordinator._pending_mutations.for_database(
                            runtime.database_id
                        )
                    },
                    set(retained_ids),
                )
                self.assertEqual(set(journal.records), set(retained_ids))
                self.assertEqual(
                    runtime.cleanup_errors,
                    ["The SQL collaboration worker could not reject queued mutations."],
                )
                with patch.object(
                    store, "query_operation", wraps=store.query_operation
                ) as query:
                    coordinator._recover_journaled_operations(runtime)
                self.assertEqual(
                    [call.args for call in query.call_args_list],
                    [
                        (runtime.database_id, operation_id)
                        for operation_id in retained_ids
                    ],
                )
                self.assertEqual(journal.records, {})
                self.assertEqual(
                    coordinator._pending_mutations.for_database(runtime.database_id), ()
                )
                self.assertEqual(writes, [])
                self.assertEqual(
                    [result.operation_id for result in results], delivered_ids
                )

    def _retain_undelivered_cancellations(self, store):
        """Stop a worker whose UI bridge cannot deliver queued cancellations."""
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(
            journal=journal, store=store, cleanup_success=False
        )
        results = []
        writes = []
        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda: (
                    writes.append("unexpected write") or _committed_execution("501")
                ),
                results.append,
                operation_id="undeliverable-cancellation",
            ),
            runtime.generation,
        )
        request = coordinator._pending_mutations.for_database(runtime.database_id)[
            0
        ].request
        runtime.stop_event.set()
        with patch.object(
            coordinator._dispatcher,
            "dispatch",
            side_effect=RuntimeError("UI bridge unavailable"),
        ):
            coordinator._worker(runtime)
        self.assertEqual(results, [])
        self.assertEqual(
            [
                pending.request.operation_id
                for pending in coordinator._pending_mutations.for_database(
                    runtime.database_id
                )
            ],
            [request.operation_id],
        )
        self.assertEqual(set(journal.records), {request.operation_id})
        return coordinator, runtime, journal, request, results, writes

    def _complete_session_start(self, coordinator, runtime):
        coordinator._on_session_started(
            (
                runtime.database_id,
                runtime.generation,
                runtime.session_generation,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
                None,
            )
        )

    def test_retained_cancellation_with_durable_record_resolves_without_replay(self):
        store = _RecoverableProjectionStore()
        coordinator, runtime, journal, request, results, writes = (
            self._retain_undelivered_cancellations(store)
        )
        store.durable_results[request.operation_id] = DurableOperationResult(
            database_id=runtime.database_id,
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
        coordinator._recover_journaled_operations(runtime)
        self.assertEqual(runtime.recovered_operation_ids, {request.operation_id})
        self._complete_session_start(coordinator, runtime)
        # The operation has no live completion callback, so its durable outcome
        # only clears the retained metadata; the write is never replayed.
        self.assertEqual(writes, [])
        self.assertEqual(results, [])
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})
        self.assertEqual(coordinator._uncertain_callbacks, {})

    def test_recovery_releases_lifecycle_drain_blocked_by_retained_cancellation(self):
        store = _RecoverableProjectionStore()
        coordinator, runtime, journal, request, _results, writes = (
            self._retain_undelivered_cancellations(store)
        )
        drained = []
        coordinator.drain_database_mutations_async(
            runtime.database_id, lambda *result: drained.append(result)
        )
        # The undelivered operation is still lifecycle-critical until recovery.
        self.assertEqual(drained, [])
        coordinator._recover_journaled_operations(runtime)
        self._complete_session_start(coordinator, runtime)
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(drained, [(True, "")])
        self.assertEqual(writes, [])

    def test_stopped_runtime_cancellation_metadata_is_bounded_and_never_leaks_forward(
        self,
    ):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(journal=journal, store=store)
        database_id = runtime.database_id
        hydrated = HydratedDatabaseChangeBatch(_batch(database_id, "epoch", 0, 0))
        writes = []
        retained_counts = []
        stopped_operation_ids = []
        for cycle in range(50):
            operation_id = f"cancel-metadata-cycle-{cycle}"
            self.assertEqual(
                _queue_test_mutation(
                    coordinator,
                    database_id,
                    (ResourceRef("takeoffs_collection", "8", 8),),
                    lambda: (
                        writes.append("unexpected write") or _committed_execution("501")
                    ),
                    lambda _result: None,
                    operation_id=operation_id,
                ),
                runtime.generation,
            )
            queued = coordinator._pending_mutations.for_database(database_id)
            self.assertEqual(len(queued), 1)
            stopped = queued[0]
            runtime.stop_event.set()
            with patch.object(
                coordinator._dispatcher,
                "dispatch",
                side_effect=RuntimeError("UI bridge unavailable"),
            ):
                coordinator._worker(runtime)
            # The undeliverable cancellation keeps exactly its own recovery
            # metadata, tagged with the stopped runtime's generation.
            self.assertEqual(
                coordinator._pending_mutations.for_database(database_id), (stopped,)
            )
            self.assertEqual(stopped.state, PendingMutationState.QUEUED)
            self.assertEqual(stopped.runtime_generation, runtime.generation)
            self.assertEqual(set(journal.records), {stopped.request.operation_id})
            retained_counts.append(
                len(coordinator._pending_mutations.for_database(database_id))
            )
            stopped_operation_ids.append(stopped.request.operation_id)
            # A restarted runtime (new generation and session) must not inherit,
            # cancel, or replay the stopped runtime's operation.
            runtime = _DatabaseRuntime(database_id, runtime.generation + 1)
            coordinator._runtimes[database_id] = runtime
            session_generation = coordinator._install_session(
                runtime, DatabaseSession(database_id, str(uuid.uuid4()))
            )
            runtime.established = True
            self.assertFalse(
                coordinator.cancel_queued_mutation(
                    database_id, stopped.request.operation_id
                )
            )
            self.assertEqual(runtime.cancelled_mutation_ids, set())
            self.assertEqual(
                coordinator._pending_mutations.for_database(database_id), (stopped,)
            )
            with patch.object(
                store, "query_operation", wraps=store.query_operation
            ) as query:
                coordinator._recover_journaled_operations(runtime)
            self.assertEqual(
                [call.args for call in query.call_args_list],
                [(database_id, stopped.request.operation_id)],
            )
            coordinator._on_session_started(
                (database_id, runtime.generation, session_generation, hydrated, None)
            )
            # The restarted runtime resolves the stopped runtime's metadata
            # instead of accumulating it.
            self.assertEqual(
                coordinator._pending_mutations.for_database(database_id), ()
            )
            self.assertEqual(journal.records, {})
            self.assertEqual(coordinator._uncertain_callbacks, {})
            self.assertEqual(writes, [])
            # Session start leaves the database catching up; the worker's
            # next poll would mark it healthy again.
            coordinator._capabilities.set_collaboration_state(
                database_id, SynchronizationState.HEALTHY
            )
            with runtime.lock:
                runtime.healthy = True
        self.assertEqual(retained_counts, [1] * 50)
        self.assertEqual(len(set(stopped_operation_ids)), 50)
        # The newest runtime is not blocked by any earlier runtime's metadata.
        drained = []
        coordinator.drain_database_mutations_async(
            database_id, lambda *result: drained.append(result)
        )
        self.assertEqual(drained, [(True, "")])
        results = []
        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda: writes.append("final write") or _committed_execution("501"),
                results.append,
                operation_id="cancel-metadata-final",
            ),
            runtime.generation,
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(writes, ["final write"])
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED],
        )

    def test_successful_placement_and_deletion_emit_no_timing_info_log(self):
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        results = []
        writes = []

        def placed():
            writes.append("placement")
            return _committed_execution("501")

        def deleted():
            writes.append("deletion")
            return _committed_execution()

        with self.assertNoLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="INFO",
        ):
            self.assertEqual(
                _queue_test_mutation(
                    coordinator,
                    runtime.database_id,
                    (ResourceRef("takeoffs_collection", "8", 8),),
                    placed,
                    results.append,
                    operation_id="placement-without-timing-log",
                ),
                runtime.generation,
            )
            coordinator._process_mutation_requests(runtime)
            self.assertEqual(
                _queue_test_mutation(
                    coordinator,
                    runtime.database_id,
                    (ResourceRef("takeoff", "501", 8),),
                    deleted,
                    results.append,
                    expected_id_count=0,
                    operation_id="deletion-without-timing-log",
                    mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE,
                ),
                runtime.generation,
            )
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(writes, ["placement", "deletion"])
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED] * 2,
        )
        self.assertEqual(
            [result.created_resource_ids for result in results], [("501",), ()]
        )
        self.assertEqual(len(reconciliation.batches), 2)
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(coordinator._operation_journal.records, {})

    def test_committed_mutation_becomes_projection_failed_when_journal_update_fails(
        self,
    ):
        journal = _FailingPendingOperationJournal(3)
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            journal=journal, reconciliation=reconciliation
        )
        calls = []
        results = []

        def operation():
            calls.append("committed")
            return _committed_execution("501")

        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                operation,
                results.append,
                operation_id="journal-projecting-failure",
            ),
            runtime.generation,
        )
        request = coordinator._pending_mutations.for_database(runtime.database_id)[
            0
        ].request
        with (
            self.assertRaisesRegex(DatabaseCatalogError, "recovery record") as failure,
            self.assertLogs(
                "ost_visualizer.application.services.sql_collaboration_coordinator",
                level="ERROR",
            ) as logged,
        ):
            coordinator._process_mutation_requests(runtime)
        self.assertTrue(failure.exception.read_only_required)
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            [
                f"Could not persist SQL operation {request.operation_id} "
                "state projecting"
            ],
        )
        self.assertEqual(calls, ["committed"])
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status, MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED
        )
        self.assertEqual(results[0].operation_id, request.operation_id)
        self.assertEqual(results[0].created_resource_ids, ("501",))
        self.assertEqual(
            results[0].authoritative_result,
            AuthoritativeMutationResult(created_resource_ids=("501",)),
        )
        self.assertTrue(results[0].commit_attempted)
        self.assertEqual(reconciliation.batches, [])
        pending = coordinator._pending_mutations.for_database(runtime.database_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].state, PendingMutationState.RECOVERING)
        self.assertEqual(
            journal.records[request.operation_id].state, PendingMutationState.RECOVERING
        )
        self.assertEqual(set(coordinator._uncertain_callbacks), {request.operation_id})
        self.assertTrue(runtime.recovery_requested)
        self.assertFalse(runtime.healthy)
        self.assertEqual(
            results[0].message,
            "The SQL mutation committed, but its recovery record could not be updated.",
        )
        self.assertEqual(
            coordinator.status(runtime.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        self.assertEqual(
            [
                payload["reason"]
                for event, payload in coordinator._event_bus.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            ["A committed SQL mutation could not be projected locally."],
        )
        # The recovering runtime is read-only: a follow-up edit is rejected
        # without re-running the committed write.
        follow_up = []
        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                operation,
                follow_up.append,
                operation_id="journal-projecting-follow-up",
            ),
            -1,
        )
        self.assertEqual(
            [result.outcome_status for result in follow_up],
            [MutationOutcomeStatus.REJECTED],
        )
        self.assertEqual(
            follow_up[0].message, "SQL collaboration is not ready for editing."
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["committed"])
        self.assertEqual(len(results), 1)

    def test_stop_race_after_dequeue_cannot_execute_queued_mutation(self):
        coordinator, runtime = self.ready_coordinator(store=_CollaborationStore())
        calls = []
        results = []
        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda: calls.append("write") or _committed_execution("501"),
                results.append,
                operation_id="placement",
            ),
            runtime.generation,
        )
        request = coordinator._pending_mutations.for_database(runtime.database_id)[
            0
        ].request
        original_get = runtime.mutation_requests.get_nowait

        def stop_on_get():
            request = original_get()
            runtime.stop_event.set()
            return request

        with patch.object(
            runtime.mutation_requests, "get_nowait", side_effect=stop_on_get
        ):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].operation_id, request.operation_id)
        self.assertEqual(results[0].database_id, runtime.database_id)
        self.assertEqual(
            results[0].outcome_status, MutationOutcomeStatus.CANCELLED_BEFORE_START
        )
        self.assertEqual(
            results[0].message, "SQL collaboration is not ready for editing."
        )
        self.assertFalse(results[0].commit_attempted)
        self.assertEqual(coordinator._local_drafts._drafts, {})
        self.assertTrue(runtime.mutation_requests.empty())
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(coordinator._operation_journal.records, {})

    def test_failed_queued_mutation_does_not_corrupt_the_next_request(self):
        for failure in ("rejected", "value_error", "unexpected_error"):
            with self.subTest(failure=failure):
                store = _LockingStore()
                reconciliation = _Reconciliation()
                coordinator, runtime = self.ready_coordinator(
                    store=store, reconciliation=reconciliation
                )
                calls = []
                results = []
                resource = ResourceRef("takeoffs_collection", "8", 8)

                def first():
                    calls.append("failed")
                    if failure == "value_error":
                        raise ValueError("invalid geometry")
                    if failure == "unexpected_error":
                        raise KeyError("internal detail")
                    return MutationExecutionResult(
                        outcome_status=MutationOutcomeStatus.REJECTED,
                        message="rejected geometry",
                    )

                def second():
                    calls.append("succeeded")
                    return _committed_execution("501")

                for name, operation in (("failed", first), ("succeeded", second)):
                    self.assertEqual(
                        _queue_test_mutation(
                            coordinator,
                            runtime.database_id,
                            (resource,),
                            operation,
                            results.append,
                            operation_id=name,
                        ),
                        runtime.generation,
                    )
                requests = tuple(runtime.mutation_requests.queue)
                if failure == "unexpected_error":
                    # Unclassified exceptions are logged but never leak internals.
                    with self.assertLogs(
                        "ost_visualizer.application.services.sql_collaboration_coordinator",
                        level="ERROR",
                    ) as logs:
                        coordinator._process_mutation_requests(runtime)
                    self.assertEqual(len(logs.records), 1)
                    self.assertIn("failed before commit", logs.output[0])
                else:
                    coordinator._process_mutation_requests(runtime)
                self.assertEqual(calls, ["failed"])
                self.assertEqual(len(results), 1)
                self.assertEqual(reconciliation.batches, [])
                self.assertEqual(coordinator._local_drafts._drafts, {})
                self.assertEqual(
                    coordinator._sessions.lock_tokens(runtime.database_id, (resource,)),
                    (),
                )
                self.assertEqual(runtime.mutation_requests.qsize(), 1)
                coordinator._process_mutation_requests(runtime)
                self.assertEqual(calls, ["failed", "succeeded"])
                self.assertEqual(
                    [result.operation_id for result in results],
                    [request.operation_id for request in requests],
                )
                self.assertEqual(
                    [result.outcome_status for result in results],
                    [
                        (
                            MutationOutcomeStatus.REJECTED
                            if failure == "rejected"
                            else MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                        ),
                        MutationOutcomeStatus.COMMITTED,
                    ],
                )
                self.assertEqual(
                    results[0].message,
                    {
                        "rejected": "rejected geometry",
                        "value_error": "invalid geometry",
                        "unexpected_error": (
                            "The SQL mutation failed before it could be committed."
                        ),
                    }[failure],
                )
                self.assertFalse(results[0].commit_attempted)
                self.assertEqual(results[1].created_resource_ids, ("501",))
                self.assertEqual(len(reconciliation.batches), 1)
                self.assertTrue(runtime.mutation_requests.empty())
                self.assertEqual(
                    store.released,
                    [(runtime.database_id, runtime.session.session_id, "lock-token")]
                    * 2,
                )
                self.assertEqual(coordinator._local_drafts._drafts, {})
                self.assertEqual(
                    coordinator._pending_mutations.for_database(runtime.database_id), ()
                )
                self.assertEqual(coordinator._operation_journal.records, {})

    def test_queued_mutation_cleanup_failure_preserves_original_result(self):
        cleanup_failure = ValueError("lock cleanup failed")

        class FailedReleaseStore(_LockingStore):
            def release_lock(self, database_id, session_id, lock_token):
                super().release_lock(database_id, session_id, lock_token)
                raise cleanup_failure

        store = FailedReleaseStore()
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            store=store, reconciliation=reconciliation
        )
        calls = []
        results = []
        resource = ResourceRef("takeoffs_collection", "8", 8)

        def rejected():
            calls.append("rejected")
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.REJECTED,
                message="the authoritative mutation conflict",
            )

        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (resource,),
                rejected,
                results.append,
                operation_id="placement",
            ),
            runtime.generation,
        )
        request = coordinator._pending_mutations.for_database(runtime.database_id)[
            0
        ].request
        with self.assertRaises(ValueError) as failure:
            coordinator._process_mutation_requests(runtime)
        self.assertIs(failure.exception, cleanup_failure)
        self.assertEqual(calls, ["rejected"])
        self.assertEqual(
            results,
            [
                QueuedMutationResult(
                    database_id=runtime.database_id,
                    runtime_generation=runtime.generation,
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.REJECTED,
                    message="the authoritative mutation conflict",
                )
            ],
        )
        self.assertEqual(
            store.released,
            [(runtime.database_id, runtime.session.session_id, "lock-token")],
        )
        self.assertEqual(reconciliation.batches, [])
        self.assertEqual(coordinator._local_drafts._drafts, {})
        self.assertEqual(
            coordinator._sessions.lock_tokens(runtime.database_id, (resource,)), ()
        )
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(coordinator._operation_journal.records, {})

    def test_queued_mutation_cleanup_failure_cannot_discard_committed_result(self):
        cleanup_failure = ValueError("lock cleanup failed")

        class FailedReleaseStore(_LockingStore):
            def release_lock(self, database_id, session_id, lock_token):
                super().release_lock(database_id, session_id, lock_token)
                raise cleanup_failure

        store = FailedReleaseStore()
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(
            store=store, reconciliation=reconciliation
        )
        calls = []
        results = []
        resource = ResourceRef("takeoffs_collection", "8", 8)

        def committed():
            calls.append("committed")
            return _committed_execution("501")

        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (resource,),
                committed,
                results.append,
                operation_id="placement",
            ),
            runtime.generation,
        )
        request = coordinator._pending_mutations.for_database(runtime.database_id)[
            0
        ].request
        with self.assertRaises(ValueError) as failure:
            coordinator._process_mutation_requests(runtime)
        self.assertIs(failure.exception, cleanup_failure)
        self.assertEqual(calls, ["committed"])
        self.assertEqual(
            [
                (
                    result.operation_id,
                    result.outcome_status,
                    result.created_resource_ids,
                )
                for result in results
            ],
            [(request.operation_id, MutationOutcomeStatus.COMMITTED, ("501",))],
        )
        self.assertEqual(len(reconciliation.batches), 1)
        self.assertEqual(coordinator._local_drafts._drafts, {})
        self.assertEqual(
            coordinator._sessions.lock_tokens(runtime.database_id, (resource,)), ()
        )
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(coordinator._operation_journal.records, {})


class SqlCollaborationCoordinatorStartDatabaseTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """SqlCollaborationCoordinator.start_database."""

    def test_same_display_user_gets_distinct_client_and_session_ids(self):
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
        # Two application instances of the same Windows user share a display name.
        with patch(
            "ost_visualizer.application.services.sql_collaboration_coordinator."
            "getpass.getuser",
            return_value="shared.user",
        ):
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
                self.addCleanup(_shutdown_coordinator, coordinator)
                coordinators.append(coordinator)
                self.assertTrue(coordinator.start_database(descriptor.database_id))
                self.assertTrue(store.started.wait(2))
        try:
            first, second = stores[0].starts[0], stores[1].starts[0]
            self.assertEqual([len(store.starts) for store in stores], [1, 1])
            for session_id, client_id, _user in (first, second):
                self.assertEqual(str(uuid.UUID(session_id)), session_id)
                self.assertEqual(str(uuid.UUID(client_id)), client_id)
            self.assertEqual([first[2], second[2]], ["shared.user", "shared.user"])
            self.assertNotEqual(first[0], second[0])
            self.assertNotEqual(first[1], second[1])
            # Each coordinator keeps one client identity for its whole lifetime.
            self.assertEqual(
                [coordinator._client_instance_id for coordinator in coordinators],
                [first[1], second[1]],
            )
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
        store = _CheckpointAwareStore()
        reconciliation = _Reconciliation()
        tokens, drafts = _token_service()
        coordinator = _RoutingCoordinator(
            descriptors,
            store,
            _RemoteReader(),
            _Dispatcher(),
            reconciliation,
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.polled.wait(2))
        store.change = _change(
            descriptor.database_id,
            ResourceRef("takeoff", "30", 8),
            sequence=2,
            source=str(uuid.uuid4()),
        )
        self.assertTrue(coordinator.remote_batch_seen.wait(2))
        self.assertTrue(store.checkpoint_seen.wait(2))
        self.assertEqual(coordinator.session_started_calls, 1)
        self.assertEqual(coordinator.remote_batch_calls, 1)
        self.assertEqual(
            coordinator._runtime(descriptor.database_id).acknowledged_version, 2
        )
        # One session-start hydration, then exactly the remote change.
        self.assertEqual(len(reconciliation.batches), 2)
        self.assertEqual(reconciliation.batches[0].batch.changes, ())
        self.assertEqual(
            [change.resource for change in reconciliation.batches[1].batch.changes],
            [ResourceRef("takeoff", "30", 8)],
        )
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertIs(coordinator.start_database("not-registered"), False)
        self.assertIs(coordinator.start_database(access_descriptor.database_id), False)
        self.assertIs(
            coordinator.start_database(unversioned_descriptor.database_id), False
        )
        self.assertIs(coordinator.start_database(future_descriptor.database_id), False)
        self.assertEqual(coordinator._runtimes, {})
        self.assertEqual(store.start_count, 0)
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
            self.assertIs(coordinator.start_database(sql_descriptor.database_id), False)
            self.assertEqual(store.start_count, 1)
            self.assertIs(coordinator._runtime(sql_descriptor.database_id), runtime)
            session_id = store.session_id
            self.assertEqual(sessions.get(sql_descriptor.database_id), session_id)
            with patch.object(
                store, "close_session", wraps=store.close_session
            ) as close:
                _stop_database(coordinator, sql_descriptor.database_id)
            close.assert_called_once_with(
                sql_descriptor.database_id, session_id, "closed"
            )
            self.assertTrue(store.closed.wait(5))
            self.assertEqual(sessions.get(sql_descriptor.database_id), "")
            self.assertFalse(runtime.thread.is_alive())
            self.assertEqual(len(initial_results), 1)
            self.assertIsNone(coordinator._runtime(sql_descriptor.database_id))
            self.assertEqual(
                coordinator.status(sql_descriptor.database_id).state,
                SynchronizationState.STOPPED,
            )
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
        store = _CheckpointAwareStore()
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        with patch.object(
            store, "poll_changes", wraps=store.poll_changes
        ) as poll_changes:
            self.assertTrue(coordinator.start_database(descriptor.database_id))
            self.assertTrue(store.started.wait(2))
            store.change = _change(
                descriptor.database_id,
                ResourceRef("condition", "42", 8),
                source=store.session_id.upper(),
            )
            self.assertTrue(store.change_seen.wait(3))
            self.assertTrue(store.checkpoint_seen.wait(2))
            runtime = coordinator._runtime(descriptor.database_id)
            # The checkpoint advanced through the suppressed own change.
            self.assertEqual(runtime.acknowledged_version, 1)
            # Suppression relies on every poll naming this session as the excluded
            # source, whatever the case of the identity stored in the feed.
            self.assertEqual(
                {call.args[3] for call in poll_changes.call_args_list},
                {store.session_id},
            )
        _stop_database(coordinator, descriptor.database_id)
        self.assertEqual(len(reconciliation.batches), 2)
        self.assertEqual(reconciliation.batches[-1].batch.changes, ())
        self.assertEqual(reconciliation.batches[-1].batch.delivered_through_version, 1)
        self.assertEqual(
            reconciliation.batches[-1].batch.database_id, descriptor.database_id
        )
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
        reader = _RemoteReader()
        coordinator = _coordinator(
            descriptors,
            store,
            reader,
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        with patch.object(
            reader, "initial_reconciliation", wraps=reader.initial_reconciliation
        ) as hydrate:
            self.assertTrue(coordinator.start_database(descriptor.database_id))
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
            # Recovery hydrates from the lower authoritative checkpoint.
            self.assertEqual(
                [call.args for call in hydrate.call_args_list],
                [
                    (descriptor.database_id, None, 25),
                    (descriptor.database_id, None, 5),
                ],
            )

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
        self.addCleanup(_shutdown_coordinator, coordinator)
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
        self.assertEqual(
            failure_payload,
            {
                "database_id": descriptor.database_id,
                "reason": (
                    "A remote SQL catch-up change requires a controlled "
                    "database refresh."
                ),
            },
        )
        self.assertEqual(
            coordinator.status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        self.assertEqual(runtime.acknowledged_version, initial_version)
        self.assertTrue(runtime.recovery_requested)
        self.assertTrue(runtime.pending_delivery)

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
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
            events,
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        calling_thread = threading.get_ident()
        runtime = coordinator._runtime(descriptor.database_id)
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
            self.assertEqual(
                _queue_test_mutation(
                    coordinator,
                    descriptor.database_id,
                    (resource,),
                    lambda index=index: operation(index),
                    complete,
                    expected_id_count=1,
                    operation_id=f"placement-{index}",
                    owning_surface="main-plan",
                ),
                runtime.generation,
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
        self.assertNotIn(calling_thread, operation_threads)
        # Both writes run serially on the database's single worker thread.
        self.assertEqual(operation_threads, [runtime.thread.ident] * 2)
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
        self.assertEqual(
            store.released,
            [(descriptor.database_id, runtime.session.session_id, "lock-token")] * 2,
        )
        self.assertEqual(drafts._drafts, {})
        _stop_database(coordinator, descriptor.database_id)

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
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
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
        self.assertEqual(results[0].created_resource_ids, ("501",))
        self.assertEqual(
            reconciliation.projection_barriers[-1].resource_uid_aliases_by_family,
            {"takeoffs": (queued_takeoff_preview_uid(results[0].operation_id, 0),)},
        )
        self.assertEqual(
            sessions.lock_tokens(descriptor.database_id, (requested,)),
            (),
        )
        self.assertEqual(sessions.get(descriptor.database_id), store.session_id)
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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
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
        self.assertEqual(
            [(result.message, result.commit_attempted) for result in results],
            [
                (
                    "The SQL mutation committed after its UI runtime changed.",
                    True,
                ),
                (
                    "SQL collaboration stopped before the queued mutation was "
                    "executed.",
                    False,
                ),
            ],
        )
        self.assertEqual(drafts._drafts, {})
        # Only the committed write keeps its recovery metadata (the stopped runtime
        # cannot project it); the never-started write is fully released.
        self.assertEqual(
            [
                (pending.request.payload["test_operation"], pending.state)
                for pending in coordinator._pending_mutations.for_database(
                    descriptor.database_id
                )
            ],
            [("placement-1", PendingMutationState.RECOVERING)],
        )
        self.assertEqual(
            [
                (record.state, record.operation_id)
                for record in coordinator._operation_journal.records.values()
            ],
            [(PendingMutationState.RECOVERING, results[0].operation_id)],
        )
        self.assertEqual(
            [
                payload["reason"]
                for event, payload in events.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            ["A committed SQL mutation could not be projected locally."],
        )

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
                heartbeat_seconds=0.0,
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        store.order.clear()
        first_entered = threading.Event()
        release_first = threading.Event()
        completed = threading.Event()
        results = []

        def first_operation():
            store.order.append("first")
            first_entered.set()
            if not release_first.wait(2):
                raise AssertionError("first mutation was not released")
            return _committed_execution("501")

        def second_operation():
            store.order.append("second")
            return _committed_execution("502")

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
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED] * 2,
        )
        self.assertEqual(
            [result.created_resource_ids for result in results],
            [("501",), ("502",)],
        )
        _stop_database(coordinator, descriptor.database_id)

    def test_worker_releases_finished_edit_lease_before_overlapping_mutation(self):
        class _ControllablePollStore(_LockingStore):
            def __init__(self):
                super().__init__()
                self.block_poll = threading.Event()
                self.poll_blocked = threading.Event()
                self.release_poll = threading.Event()
                self.holders = 0
                self.lock_events = []

            def poll_changes(self, *args):
                if self.block_poll.is_set():
                    self.poll_blocked.set()
                    if not self.release_poll.wait(2):
                        raise AssertionError(
                            "test poll did not receive its release signal"
                        )
                return super().poll_changes(*args)

            def acquire_lock(self, database_id, session_id, resource, description):
                # Model the server: a held resource cannot be locked a second time.
                if self.holders:
                    raise DatabaseCatalogError("The resource is already locked.")
                self.holders += 1
                self.lock_events.append("acquire")
                return super().acquire_lock(
                    database_id, session_id, resource, description
                )

            def release_lock(self, database_id, session_id, lock_token):
                self.holders -= 1
                self.lock_events.append("release")
                return super().release_lock(database_id, session_id, lock_token)

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _ControllablePollStore()
        tokens, drafts = _token_service()
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
            events,
            SQL_SCHEMA_V1.version,
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
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
        self.assertEqual(
            mutation_results[0].created_resource_ids,
            ("42",),
        )
        # The finished selection lease is released before the mutation locks the
        # same resource; each lock is released exactly once.
        self.assertEqual(
            store.lock_events, ["acquire", "release", "acquire", "release"]
        )
        self.assertEqual(len(store.released), 2)
        self.assertEqual(runtime.owned_locks, {})
        _stop_database(coordinator, descriptor.database_id)

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        read_only = _state_signal(
            events, descriptor.database_id, SynchronizationState.READ_ONLY
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
            events,
            SQL_SCHEMA_V1.version,
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
            ),
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
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
        self.assertTrue(results[0].commit_attempted)
        self.assertEqual(
            results[0].message,
            "The test mutation returned an incomplete authoritative result.",
        )
        self.assertEqual(drafts._drafts, {})
        self.assertTrue(store.release_event.wait(2))
        # The completion callback runs on the worker before it tears the session
        # down, so wait for the published read-only state.
        self.assertTrue(read_only.wait(2))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.READ_ONLY,
        )
        self.assertFalse(capabilities.is_editable(descriptor.database_id))
        self.assertEqual(sessions.get(descriptor.database_id), "")
        self.assertTrue(store.closed.is_set())

    def test_retention_gap_enters_controlled_read_only_reconciliation(self):
        gaps = (
            # The checkpoint predates the oldest retained version.
            ("below retained range", 10, 20, 25),
            # Decision D3: checkpoint 0 is a real checkpoint, not "no checkpoint".
            ("zero below retained range", 0, 5, 25),
            # The checkpoint is ahead of the feed's high-water mark.
            ("above high water", 30, 1, 25),
        )
        for label, checkpoint, minimum_valid, high_water in gaps:
            with self.subTest(gap=label):
                descriptors = DatabaseDescriptorRegistry()
                descriptor = DatabaseDescriptor.for_sql_server(
                    SqlServerDatabaseLocation(server="localhost", database="TEST"),
                    schema_version=SQL_SCHEMA_V1.version,
                )
                descriptors.register(descriptor)
                capabilities = DatabaseCapabilityService(
                    descriptors, _PermissionProbe()
                )
                capabilities.mark_connected(descriptor.database_id)
                store = _CollaborationStore()
                store.initial_version = checkpoint
                store.batch = DatabaseChangeBatch(
                    database_id=descriptor.database_id,
                    feed_epoch="epoch",
                    minimum_valid_version=minimum_valid,
                    high_water_version=high_water,
                    delivered_through_version=checkpoint,
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
                self.addCleanup(_shutdown_coordinator, coordinator)
                self.assertTrue(coordinator.start_database(descriptor.database_id))
                self.assertTrue(reconciliation_required.wait(2))
                runtime = coordinator._runtime(descriptor.database_id)
                self.assertIsNotNone(runtime)
                self.assertEqual(runtime.acknowledged_version, checkpoint)
                self.assertEqual(
                    capabilities.collaboration_status(descriptor.database_id).state,
                    SynchronizationState.RECONCILIATION_REQUIRED,
                )
                self.assertFalse(capabilities.is_editable(descriptor.database_id))
                self.assertEqual(
                    [
                        payload["reason"]
                        for event, payload in events.published
                        if event is AppEvents.FULL_RECONCILIATION_REQUIRED
                    ],
                    ["The SQL Change Tracking checkpoint is no longer valid."],
                )
                self.assertEqual(
                    coordinator.metrics(descriptor.database_id).retention_gap_count, 1
                )
                self.assertTrue(runtime.pending_delivery)
                self.assertTrue(runtime.recovery_requested)

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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        resource = ResourceRef("condition", "42", 8)
        acquired = threading.Event()
        grants = []
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: (grants.append(result), acquired.set()),
        )
        self.assertTrue(acquired.wait(2))
        self.assertTrue(grants[0].granted)
        handle = grants[0].handle
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
        self.assertEqual(runtime.draft_ids, {})
        self.assertIsNone(drafts.get(handle.draft_id))
        # The edit owner is told its lease was lost with the trust-loss reason.
        self.assertEqual(
            [
                payload["loss"]
                for event, payload in events.published
                if event is AppEvents.EDIT_LEASE_LOST
            ],
            [
                EditLeaseLoss(
                    database_id=descriptor.database_id,
                    draft_id=handle.draft_id,
                    runtime_generation=runtime.generation,
                    operation_id=handle.operation_id,
                    owning_surface="desktop",
                    resources=(resource,),
                    reason="trust-lost",
                )
            ],
        )

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
        runtime = coordinator._runtime(descriptor.database_id)
        coordinator.enter_conflict(descriptor.database_id, "conflict")
        self.assertTrue(store.release_event.wait(2))
        self.assertNotEqual(store.release_threads[-1], caller_thread)
        self.assertEqual(store.release_threads, [runtime.thread.ident])
        self.assertEqual(
            coordinator.status(descriptor.database_id).state,
            SynchronizationState.CONFLICTED,
        )
        self.assertEqual(coordinator.status(descriptor.database_id).message, "conflict")

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
        self.assertTrue(healthy.wait(2))
        results = []
        delivered = threading.Event()
        first = ResourceRef("condition", "42", 8)
        second = ResourceRef("condition", "43", 8)
        coordinator.request_local_edit(
            descriptor.database_id,
            (first, second),
            lambda result: (results.append(result), delivered.set()),
        )
        self.assertTrue(store.acquire_failed.wait(2))
        # The store signals before the worker reports the denial.
        self.assertTrue(delivered.wait(2))
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].granted)
        self.assertIsNone(results[0].handle)
        self.assertEqual(results[0].message, "second lock was denied")
        # A denied batch leaves the session, locks and runtime ownership intact.
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertFalse(store.closed.is_set())
        self.assertIsNotNone(runtime.session)
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.draft_ids, {})
        self.assertEqual(runtime.edit_depth, 0)
        self.assertEqual(
            coordinator.status(descriptor.database_id).state,
            SynchronizationState.HEALTHY,
        )
        replacement = drafts.begin(
            draft_type="condition_editor",
            database_id=descriptor.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(first, second),
        )
        drafts.finish(replacement.draft_id)

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
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
        self.assertTrue(healthy.wait(2))
        acquired = threading.Event()
        grants = []
        resource = ResourceRef("condition", "42", 8)
        coordinator.request_local_edit(
            descriptor.database_id,
            (resource,),
            lambda result: (grants.append(result), acquired.set()),
        )
        self.assertTrue(acquired.wait(2))
        self.assertTrue(grants[0].granted)
        handle = grants[0].handle
        runtime = coordinator._runtime(descriptor.database_id)
        session_id = runtime.session.session_id
        _stop_database(coordinator, descriptor.database_id)
        self.assertEqual(
            store.released, [(descriptor.database_id, session_id, "lock-token")]
        )
        self.assertTrue(lease_lost.is_set())
        self.assertIsNone(drafts.get(handle.draft_id))
        # Closing the database reports the loss to the lease owner with its reason.
        self.assertEqual(
            [
                payload["loss"]
                for event, payload in events.published
                if event is AppEvents.EDIT_LEASE_LOST
            ],
            [
                EditLeaseLoss(
                    database_id=descriptor.database_id,
                    draft_id=handle.draft_id,
                    runtime_generation=handle.runtime_generation,
                    operation_id=handle.operation_id,
                    owning_surface="desktop",
                    resources=(resource,),
                    reason="closed",
                )
            ],
        )

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
            events,
            SQL_SCHEMA_V1.version,
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        results = []
        coordinator.request_local_edit(
            descriptor.database_id,
            (ResourceRef("condition", "42", 8),),
            results.append,
        )
        self.assertTrue(dispatcher.lease_queued.wait(2))
        _stop_database(coordinator, descriptor.database_id)
        dispatcher.deliver_pending()
        self.assertEqual(
            results,
            [
                EditLeaseResult(
                    False,
                    "SQL collaboration stopped before the edit lease became active.",
                )
            ],
        )
        # The lock acquired for the undelivered grant was released with the stop.
        self.assertEqual(len(store.released), 1)
        self.assertEqual(drafts._drafts, {})

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
        self.assertTrue(healthy.wait(2))
        results = []
        resource = ResourceRef("condition", "42", 8)
        runtime = coordinator._runtime(descriptor.database_id)
        requester = threading.Thread(
            target=coordinator.request_local_edit,
            args=(descriptor.database_id, (resource,), results.append),
        )
        requester.start()
        self.addCleanup(requester.join, 2)
        self.addCleanup(drafts.proceed.set)
        self.assertTrue(drafts.entered.wait(2))
        _stop_database(coordinator, descriptor.database_id)
        drafts.proceed.set()
        requester.join(2)
        self.assertFalse(requester.is_alive())
        self.assertEqual(
            results,
            [
                EditLeaseResult(
                    False, "SQL collaboration stopped before the edit could be queued."
                )
            ],
        )
        self.assertTrue(runtime.edit_requests.empty())
        replacement = drafts.begin(
            draft_type="condition_editor",
            database_id=descriptor.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
        )
        drafts.finish(replacement.draft_id)

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
        self.assertTrue(healthy.wait(2))
        results = []
        resource = ResourceRef("condition", "42", 8)
        runtime = coordinator._runtime(descriptor.database_id)
        requester = threading.Thread(
            target=coordinator.request_local_edit,
            args=(descriptor.database_id, (resource,), results.append),
        )
        requester.start()
        self.addCleanup(requester.join, 2)
        self.addCleanup(drafts.proceed.set)
        self.assertTrue(drafts.entered.wait(2))
        coordinator.enter_conflict(descriptor.database_id, "trust lost")
        drafts.proceed.set()
        requester.join(2)
        self.assertFalse(requester.is_alive())
        self.assertEqual(
            results,
            [
                EditLeaseResult(
                    False, "SQL collaboration stopped before the edit could be queued."
                )
            ],
        )
        self.assertTrue(runtime.edit_requests.empty())
        self.assertEqual(runtime.owned_locks, {})
        replacement = drafts.begin(
            draft_type="condition_editor",
            database_id=descriptor.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
        )
        drafts.finish(replacement.draft_id)

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
            events,
            SQL_SCHEMA_V1.version,
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
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
        self.assertEqual(
            results,
            [
                EditLeaseResult(
                    False,
                    "SQL collaboration stopped before the edit lease became active.",
                )
            ],
        )
        self.assertEqual(len(store.released), 1)
        self.assertEqual(drafts._drafts, {})

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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
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
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertNotEqual(store.acquire_thread, caller_thread)
        self.assertEqual(store.acquire_thread, runtime.thread.ident)
        coordinator.end_edit_lease(results[0].handle)
        self.assertTrue(store.release_event.wait(2))
        self.assertEqual(store.release_threads, [runtime.thread.ident])
        self.assertEqual(
            store.released,
            [(descriptor.database_id, store.session_id, "lock-token")],
        )

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
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
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
        self.assertTrue(store.failed.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertIsNotNone(runtime)
        runtime.thread.join(2)
        self.assertFalse(runtime.thread.is_alive())
        self.assertEqual(
            coordinator.status(descriptor.database_id).state,
            SynchronizationState.CREDENTIAL_REQUIRED,
        )
        self.assertFalse(healthy.is_set())
        events.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            file_path=descriptor.database_id,
        )
        self.assertTrue(store.restarted.wait(2))
        # The re-probe replaced the stopped worker with a new, healthy runtime.
        self.assertTrue(healthy.wait(2))
        replacement = coordinator._runtime(descriptor.database_id)
        self.assertIsNot(replacement, runtime)
        self.assertGreater(replacement.generation, runtime.generation)
        self.assertEqual(store.attempts, 2)
        self.assertEqual(
            coordinator.status(descriptor.database_id).state,
            SynchronizationState.HEALTHY,
        )

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
        sessions = DatabaseSessionRegistry()
        events = _EventBus()
        reconnected = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
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
            CollaborationPollingPolicy(
                inactive_database_seconds=0.05,
                jitter_ratio=0.0,
                reconnect_backoff_seconds=(0.05,),
            ),
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        with patch.object(
            store, "start_session", wraps=store.start_session
        ) as start_session:
            self.assertTrue(coordinator.start_database(descriptor.database_id))
            self.assertTrue(store.restarted.wait(2))
            self.assertTrue(reconnected.wait(2))
            runtime = coordinator._runtime(descriptor.database_id)
            self.assertEqual(store.start_count, 2)
        first_session, second_session = (
            call.args[1] for call in start_session.call_args_list
        )
        self.assertNotEqual(first_session, second_session)
        self.assertEqual(coordinator.metrics(descriptor.database_id).reconnect_count, 1)
        states = [
            payload["state"]
            for event, payload in tuple(events.published)
            if event is AppEvents.COLLABORATION_STATE_CHANGED
        ]
        # The heartbeat failure disconnects the first session before any healthy
        # state; only the replacement session is announced as healthy.
        self.assertIn("disconnected", states)
        self.assertEqual(states.count("healthy"), 1)
        self.assertLess(states.index("disconnected"), states.index("healthy"))
        self.assertEqual(sessions.get(descriptor.database_id), second_session)
        self.assertEqual(runtime.session.session_id, second_session)

    def test_startup_connection_failure_does_not_retry_until_user_reconnects(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        store = _AlwaysUnavailableStore()
        events = _EventBus()
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
            events,
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(
            coordinator.start_database(
                descriptor.database_id,
                retry_initial_failure=False,
                on_initial_open=initial_open,
            )
        )
        self.assertTrue(store.first_failure.wait(2))
        self.assertTrue(initial_complete.wait(2))
        self.assertEqual(initial_results, [(False, "server unavailable")])
        runtime = coordinator._runtime(descriptor.database_id)
        runtime.thread.join(2)
        self.assertFalse(runtime.thread.is_alive())
        self.assertFalse(store.repeated_failure.wait(0.1))
        self.assertEqual(store.start_count, 1)
        self.assertNotEqual(store.start_threads, [caller_thread])
        self.assertEqual(store.start_threads, [runtime.thread.ident])
        self.assertEqual(
            coordinator.status(descriptor.database_id).state,
            SynchronizationState.DISCONNECTED,
        )
        self.assertEqual(coordinator.metrics(descriptor.database_id).reconnect_count, 0)
        # Only an explicit capability re-probe (the user reconnecting) tries again.
        events.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            file_path=descriptor.database_id,
        )
        self.assertTrue(store.repeated_failure.wait(2))
        self.assertGreaterEqual(store.start_count, 2)

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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(reconciliation_required.wait(2))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        self.assertFalse(capabilities.is_editable(descriptor.database_id))
        self.assertEqual(
            [
                payload
                for event, payload in events.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            [
                {
                    "database_id": descriptor.database_id,
                    "reason": "invalid transaction marker",
                }
            ],
        )
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertTrue(runtime.recovery_requested)
        self.assertTrue(runtime.pending_delivery)

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
        self.addCleanup(store.release_poll.set)
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
        self.assertTrue(store.closed.is_set())
        self.assertEqual(coordinator._runtimes, {})

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
        events = _EventBus()
        disconnected = _state_signal(
            events, descriptor.database_id, SynchronizationState.DISCONNECTED
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
            events,
            SQL_SCHEMA_V1.version,
        )
        self.addCleanup(_shutdown_coordinator, coordinator)
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logs:
            self.assertTrue(coordinator.start_database(descriptor.database_id))
            self.assertTrue(store.failed.wait(2))
            self.assertTrue(store.closed.wait(2))
            # The close precedes the projected state, so wait for the state itself.
            self.assertTrue(disconnected.wait(2))
        self.assertIn("worker stopped after an unexpected RuntimeError", logs.output[0])
        self.assertFalse(sessions.get(descriptor.database_id))
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.DISCONNECTED,
        )
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).message,
            "SQL collaboration stopped after an unexpected internal error.",
        )
        self.assertFalse(capabilities.is_editable(descriptor.database_id))
        runtime = coordinator._runtime(descriptor.database_id)
        runtime.thread.join(2)
        self.assertFalse(runtime.thread.is_alive())
        self.assertIsNone(runtime.session)
        self.assertEqual(runtime.cleanup_errors, [])
        _stop_database(coordinator, descriptor.database_id)

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
        self.addCleanup(store.release_poll.set)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.poll_entered.wait(2))
        coordinator.stop_database_async(descriptor.database_id)
        completed = threading.Event()
        results = []
        coordinator.request_shutdown(
            lambda success, message: (
                results.append((success, message)),
                completed.set(),
            )
        )
        self.assertFalse(completed.is_set())
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.DRAINING
        )
        store.release_poll.set()
        self.assertTrue(completed.wait(2))
        self.assertEqual(results, [(True, "")])
        self.assertTrue(store.closed.is_set())
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
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.addCleanup(store.release_poll.set)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.poll_entered.wait(2))
        drained = threading.Event()
        drain_results = []
        coordinator.stop_database_async(
            descriptor.database_id,
            callback=lambda success, message: (
                drain_results.append((success, message)),
                drained.set(),
            ),
        )
        self.assertIs(coordinator.start_database(descriptor.database_id), False)
        self.assertEqual(store.start_count, 1)
        store.release_poll.set()
        self.assertTrue(drained.wait(2))
        self.assertEqual(drain_results, [(True, "")])
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        # The reopened database starts its own session once the old one drained.
        self.assertTrue(store.restarted.wait(2))
        self.assertEqual(store.start_count, 2)

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
        self.addCleanup(store.release_poll.set)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.poll_entered.wait(2))
        completed = threading.Event()
        results = []

        def record(label):
            return lambda success, message: (
                results.append((label, success, message)),
                completed.set() if len(results) == 2 else None,
            )

        with patch.object(store, "close_session", wraps=store.close_session) as close:
            coordinator.request_shutdown(record("first"))
            coordinator.request_shutdown(record("second"))
            store.release_poll.set()
            self.assertTrue(completed.wait(2))
        self.assertCountEqual(results, [("first", True, ""), ("second", True, "")])
        self.assertEqual(store.start_count, 1)
        # Both requests were answered by the same drain: one session close.
        self.assertEqual(close.call_count, 1)
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)

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
        failure = "The SQL collaboration session could not be closed."
        self.assertEqual(results, [(False, failure)])
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.CLEANUP_FAILED
        )
        # The failure is terminal: repeated requests report it and the database
        # cannot be restarted behind the unclosed remote session.
        repeated = []
        coordinator.request_shutdown(lambda *result: repeated.append(result))
        self.assertEqual(repeated, [(False, failure)])
        self.assertIs(coordinator.start_database(descriptor.database_id), False)
        self.assertEqual(
            coordinator._database_cleanup_failures, {descriptor.database_id: failure}
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
        events = _EventBus()
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
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
            events,
            SQL_SCHEMA_V1.version,
        )
        resource = ResourceRef("condition", "42", 8)
        self.addCleanup(_shutdown_coordinator, coordinator)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
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
        with patch.object(
            store, "release_lock", wraps=store.release_lock
        ) as release_lock:
            coordinator.request_shutdown(
                lambda success, message: (
                    shutdown_results.append((success, message)),
                    shutdown_completed.set(),
                )
            )
            self.assertTrue(shutdown_completed.wait(2))
        # The lock release was attempted and failed; the session close covers it.
        release_lock.assert_called_once()
        self.assertTrue(store.closed.is_set())
        self.assertEqual(shutdown_results, [(True, "")])
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)
        self.assertIsNone(drafts.get(lease_results[0].handle.draft_id))

    def test_offline_database_unload_abandons_expiring_remote_cleanup(self):
        for reason in ("closed", "unchecked", "connection-removed"):
            with self.subTest(reason=reason):
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
                session_id = store.session_id
                unloaded = threading.Event()
                unload_results = []
                with patch.object(
                    store, "close_session", wraps=store.close_session
                ) as close:
                    coordinator.stop_database_async(
                        descriptor.database_id,
                        reason,
                        callback=lambda success, message: (
                            unload_results.append((success, message)),
                            unloaded.set(),
                        ),
                    )
                    self.assertTrue(unloaded.wait(2))
                # The remote close was attempted and failed, but a local detach
                # abandons it because the session expires on its own.
                close.assert_called_once_with(
                    descriptor.database_id, session_id, reason
                )
                self.assertEqual(unload_results, [(True, "")])
                self.assertEqual(coordinator._database_cleanup_failures, {})
                self.assertEqual(
                    coordinator.status(descriptor.database_id).state,
                    SynchronizationState.STOPPED,
                )
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
                self.assertEqual(
                    coordinator.shutdown_state, CollaborationShutdownState.CLOSED
                )
                repeated_results = []
                coordinator.request_shutdown(
                    lambda success, message: repeated_results.append((success, message))
                )
                self.assertEqual(len(repeated_results), 1)
                self.assertEqual(repeated_results, [(True, "")])

    def test_non_local_database_stop_reports_failed_remote_cleanup(self):
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
        stopped = threading.Event()
        stop_results = []
        coordinator.stop_database_async(
            descriptor.database_id,
            "reconfigured",
            callback=lambda success, message: (
                stop_results.append((success, message)),
                stopped.set(),
            ),
        )
        self.assertTrue(stopped.wait(2))
        failure = "The SQL collaboration session could not be closed."
        self.assertEqual(stop_results, [(False, failure)])
        self.assertEqual(
            coordinator._database_cleanup_failures, {descriptor.database_id: failure}
        )
        # The unreleased remote session blocks reopening and fails shutdown.
        self.assertIs(coordinator.start_database(descriptor.database_id), False)
        shutdown = threading.Event()
        shutdown_results = []
        coordinator.request_shutdown(
            lambda success, message: (
                shutdown_results.append((success, message)),
                shutdown.set(),
            )
        )
        self.assertTrue(shutdown.wait(2))
        self.assertEqual(shutdown_results, [(False, failure)])
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.CLEANUP_FAILED
        )


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
        # The stale submitter still learns its outcome, but no dialog is opened.
        self.assertEqual(
            [(result.outcome_status, result.conflict) for result in callbacks],
            [(MutationOutcomeStatus.CONFLICT, conflict)],
        )
        self.assertEqual(events.published, [])
        _shutdown_coordinator(coordinator)

    def test_current_runtime_queued_mutation_conflict_opens_dialog(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        dispatcher = _DelayedMutationDispatcher()
        events = _EventBus()
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
            events,
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
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
                runtime_generation=runtime.generation,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
                message=conflict.reason,
                conflict=conflict,
            ),
        )
        self.assertEqual(callbacks, [])
        dispatcher.deliver_pending()
        self.assertEqual(
            [(result.outcome_status, result.conflict) for result in callbacks],
            [(MutationOutcomeStatus.CONFLICT, conflict)],
        )
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.SYNCHRONIZATION_CONFLICT,
                    {
                        "database_id": descriptor.database_id,
                        "resource_type": "takeoffs_collection",
                        "resource_id": "8",
                        "bid_uid": "8",
                        "message": "stale takeoff collection",
                        "blocks_database": False,
                    },
                )
            ],
        )
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
        self.assertEqual(
            results[0].message,
            "The SQL runtime changed before the mutation completed.",
        )
        self.assertTrue(results[0].commit_attempted)
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
        self.assertEqual(
            results[0].message,
            "The SQL runtime changed before the mutation completed.",
        )
        self.assertTrue(results[0].commit_attempted)
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
        self.assertEqual(results[0].message, "")
        self.assertFalse(runtime.recovery_requested)
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

        class _GatedRestartStore(_CollaborationStore):
            """Hold the recovery session start until the test has observed it."""

            def __init__(self):
                super().__init__()
                self.restart_gate = threading.Event()

            def start_session(self, *args, **kwargs):
                if self.start_count and not self.restart_gate.wait(2):
                    raise AssertionError("The recovery session was never released")
                return super().start_session(*args, **kwargs)

        store = _GatedRestartStore()
        events = _EventBus()
        healthy = threading.Event()
        recovered = threading.Event()
        healthy_count = []

        def observe(database_id="", state="", **_payload):
            if database_id == descriptor.database_id and state == "healthy":
                healthy_count.append(state)
                (healthy if len(healthy_count) == 1 else recovered).set()

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
        self.addCleanup(store.restart_gate.set)
        self.addCleanup(_shutdown_coordinator, coordinator)
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
        self.assertEqual(
            [
                payload["reason"]
                for event, payload in events.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            ["retention gap"],
        )
        # The request itself never moves the checkpoint; the worker does, once it
        # has started the replacement session at the authoritative version.
        store.initial_version = 25
        store.batch = _batch(descriptor.database_id, "epoch", 0, 25)
        self.assertEqual(runtime.acknowledged_version, initial_checkpoint)
        store.restart_gate.set()
        self.assertTrue(store.restarted.wait(2))
        self.assertTrue(recovered.wait(2))
        self.assertEqual(runtime.acknowledged_version, 25)

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
        with self.assertRaisesRegex(DatabaseCatalogError, "ChangeLog") as failure:
            coordinator._process_mutation_requests(runtime)
        # A retryable disconnect, not a read-only trust loss: recovery re-reads it.
        self.assertTrue(failure.exception.retryable)
        self.assertFalse(failure.exception.read_only_required)
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        self.assertEqual(
            results[0].message,
            "The SQL mutation committed, but its authoritative result could not "
            "be loaded.",
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
        # The repeated request published no further state changes either.
        self.assertEqual(
            [
                payload["state"]
                for event, payload in events.published
                if event is AppEvents.COLLABORATION_STATE_CHANGED
            ],
            ["reconciliation_required", "connecting"],
        )
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.CONNECTING,
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
        self.assertEqual(
            results[0].message,
            "SQL collaboration stopped before the queued mutation was executed.",
        )
        self.assertFalse(results[0].commit_attempted)
        self.assertTrue(runtime.mutation_requests.empty())
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
        writes = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: writes.append("write") or _committed_execution("501"),
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
        # Recovery resolves the durable outcome without replaying the write.
        self.assertEqual(writes, ["write"])
        self.assertEqual(results[1].operation_id, request.operation_id)
        self.assertEqual(results[1].created_resource_ids, ("501",))
        self.assertEqual(results[1].authoritative_result.created_resource_ids, ("501",))
        self.assertTrue(results[1].commit_attempted)
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
        # The first runtime is gone: only the replacement is asked to recover and
        # the callback stays retained for the recovered durable outcome.
        self.assertFalse(first_runtime.recovery_requested)
        self.assertIn(request.operation_id, coordinator._uncertain_callbacks)
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
        self.assertTrue(runtime.pending_delivery)
        self.assertFalse(runtime.healthy)
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        self.assertEqual(
            [
                payload["reason"]
                for event, payload in events.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            ["A remote SQL catch-up change requires a controlled database " "refresh."],
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
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logs:
            coordinator._on_remote_batch(
                (
                    descriptor.database_id,
                    runtime.generation,
                    runtime.session_generation,
                    hydrated,
                    None,
                )
            )
        self.assertIn("main-thread reconciliation failed", logs.output[0])
        failure_payload = next(
            payload
            for event, payload in events.published
            if event is AppEvents.FULL_RECONCILIATION_REQUIRED
        )
        self.assertEqual(
            failure_payload["reason"],
            "A remote SQL catch-up change requires a controlled database refresh.",
        )
        self.assertEqual(runtime.acknowledged_version, 7)
        _shutdown_coordinator(coordinator)

    def test_malformed_remote_payload_reports_malformed_refresh_reason(self):
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
        runtime.acknowledged_version = 7
        runtime.pending_delivery = True
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._on_remote_batch(
            (
                descriptor.database_id,
                runtime.generation,
                runtime.session_generation,
                HydratedDatabaseChangeBatch(
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
                ),
                None,
            )
        )
        self.assertEqual(
            [
                payload["reason"]
                for event, payload in events.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            [
                "A malformed SQL reconciliation payload requires a controlled "
                "database refresh."
            ],
        )
        self.assertEqual(runtime.acknowledged_version, 7)
        self.assertTrue(runtime.recovery_requested)
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
        self.assertEqual(reconciliation.batches, [hydrated])
        self.assertEqual(len(reconciliation.projection_barriers), 1)
        self.assertEqual(runtime.acknowledged_version, 7)
        self.assertTrue(runtime.pending_delivery)
        self.assertFalse(runtime.healthy)
        reconciliation.token.complete(True)
        self.assertEqual(runtime.acknowledged_version, 12)
        self.assertFalse(runtime.pending_delivery)
        self.assertTrue(runtime.healthy)
        self.assertFalse(runtime.recovery_requested)
        reconciliation.token.complete(True)
        self.assertEqual(runtime.acknowledged_version, 12)
        self.assertEqual(runtime.reconciliation_count, 1)
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
        self.assertTrue(runtime.pending_delivery)
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        self.assertEqual(
            [
                payload["reason"]
                for event, payload in events.published
                if event is AppEvents.FULL_RECONCILIATION_REQUIRED
            ],
            ["A remote SQL catch-up change requires a controlled database " "refresh."],
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
        # While the remote batch is still being reconciled the worker leaves every
        # queued mutation untouched.
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, [])
        self.assertEqual(results, [])
        self.assertEqual(runtime.mutation_requests.qsize(), 3)
        runtime.command_event.clear()
        coordinator._finish_remote_batch(
            descriptor.database_id,
            runtime.generation,
            runtime.session_generation,
            8,
            time.perf_counter(),
            None,
            True,
        )
        # Reconciliation finished with work queued: the worker is woken to run it.
        self.assertTrue(runtime.healthy)
        self.assertTrue(runtime.command_event.is_set())
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
        # (observed high-water version, expected healthy, expected worker wake-up)
        for observed, healthy, wakes_worker in ((8, True, False), (9, False, True)):
            with self.subTest(observed_high_water_version=observed):
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
                self.addCleanup(_shutdown_coordinator, coordinator)
                runtime = _DatabaseRuntime(descriptor.database_id, 1)
                runtime.pending_delivery = True
                runtime.acknowledged_version = 7
                runtime.observed_high_water_version = observed
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
                self.assertEqual(runtime.acknowledged_version, 8)
                self.assertFalse(runtime.pending_delivery)
                self.assertEqual(runtime.healthy, healthy)
                # Only a runtime that is still behind the feed needs another poll.
                self.assertEqual(runtime.command_event.is_set(), wakes_worker)

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
        handoff_payloads = []

        def on_reconciliation_required(payload):
            handoff_payloads.append(payload)
            pending_at_handoff.append(runtime.pending_delivery)

        coordinator._on_reconciliation_required = on_reconciliation_required
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
        self.assertEqual(
            handoff_payloads,
            [
                (
                    descriptor.database_id,
                    runtime.generation,
                    "A remote SQL catch-up change requires a controlled database "
                    "refresh.",
                )
            ],
        )
        self.assertTrue(runtime.pending_delivery)
        self.assertFalse(runtime.healthy)
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
        self.assertEqual(runtime.owned_locks, {second.lease_identity: second_lock})
        self.assertEqual(
            runtime.draft_ids,
            {frozenset((second.lease_identity,)): second_draft.draft_id},
        )
        # The duplicate neither released the first lock again nor touched the second.
        self.assertEqual(store.released, [("database", "session", "first-lock")])
        self.assertIsNone(drafts.get(first_draft.draft_id))
        self.assertIsNotNone(drafts.get(second_draft.draft_id))
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
        self.assertEqual(runtime.edit_depth, 1)
        # A handle that matches the draft but not the runtime's held lock is
        # equally rejected (for example one issued before a lock was renewed).
        drafts.finish(draft.draft_id)
        replacement = drafts.begin(
            draft_type="condition_editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
            operation_id="edit-condition",
        )
        drafts.activate(replacement.draft_id, (forged.locks[0],), runtime_generation=1)
        runtime.draft_ids = {
            frozenset((resource.lease_identity,)): replacement.draft_id
        }
        stale = EditLeaseHandle(
            database_id="database",
            draft_id=replacement.draft_id,
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(resource,),
            locks=forged.locks,
        )
        coordinator.end_edit_lease(stale)
        coordinator._process_release_requests(runtime)
        self.assertEqual(runtime.owned_locks, {resource.lease_identity: owned_lock})
        self.assertIsNotNone(drafts.get(replacement.draft_id))
        self.assertEqual(store.released, [])
        self.assertEqual(runtime.edit_depth, 1)
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
        self.assertEqual(store.released, [("database", "session", "owned-lock")])
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.draft_ids, {})
        self.assertEqual(runtime.edit_depth, 0)
        self.assertEqual(runtime.mode, PresenceMode.VIEWING)
        self.assertIsNone(drafts.get(draft.draft_id))
        self.assertEqual(sessions.lock_tokens("database", (requested,)), ())
        _shutdown_coordinator(coordinator)


class SqlCollaborationCoordinatorInitialOpeningCompletionTests(unittest.TestCase):
    def _coordinator(self):
        callback = Mock()
        runtime = _DatabaseRuntime("database", 1, initial_open_callback=callback)
        coordinator = object.__new__(SqlCollaborationCoordinator)
        coordinator._lock = threading.Lock()
        coordinator._own_publication = _OwnPublicationGuard()
        coordinator._runtimes = {"database": runtime}
        coordinator._event_bus = Mock(spec=_EventBus)
        coordinator._capabilities = Mock(spec=DatabaseCapabilityService)
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
        coordinator._capabilities.is_editable.assert_called_once_with("database")
        self.assertIsNone(runtime.initial_open_callback)

    def test_initial_failure_or_denied_editability_cannot_report_success(self):
        for state, editable in (
            (SynchronizationState.DISCONNECTED, True),
            (SynchronizationState.DISCONNECTED, False),
            (SynchronizationState.READ_ONLY, True),
            (SynchronizationState.READ_ONLY, False),
            (SynchronizationState.RECONCILIATION_REQUIRED, True),
            (SynchronizationState.RECONCILIATION_REQUIRED, False),
            (SynchronizationState.CONFLICTED, True),
            (SynchronizationState.HEALTHY, False),
        ):
            with self.subTest(state=state, editable=editable):
                coordinator, runtime, callback = self._coordinator()
                coordinator._capabilities.is_editable.return_value = editable
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
        # Neither runtime was completed: each keeps its own pending callback.
        self.assertIs(runtime.initial_open_callback, callback)
        self.assertIs(replacement.initial_open_callback, replacement_callback)


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
        self.assertEqual(recovered.affected_page_uids, ("20",))
        self.assertEqual(recovered.affected_families, ("takeoffs",))

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
        # Every created identity except the pre-existing target project is reported.
        self.assertCountEqual(
            recovered.created_resource_ids,
            ("10", "20", "30", "40", "50", "60", "70"),
        )
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

    def test_recovered_results_reject_malformed_durable_payloads(self):
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

        def recover(result_payload):
            return SqlCollaborationCoordinator._recovered_authoritative_result(
                request,
                DurableOperationResult(
                    database_id="database",
                    operation_id=operation_id,
                    found=True,
                    mutation_type=request.mutation_type.value,
                    request_hash=request.request_hash,
                    result_format_version=1,
                    result_payload=result_payload,
                ),
            )

        def paste(**overrides):
            value = {
                "takeoff_uids": {"t": "100"},
                "annotation_uids": {"rect/a": "200"},
                "condition_uids": {"c": "300"},
            }
            value.update(overrides)
            return json.dumps({"value": value, "value_available": True})

        malformed = {
            "not json": "{",
            "not an object": "[]",
            "missing availability flag": json.dumps({"value": []}),
            "extra payload field": json.dumps(
                {"value": [], "value_available": True, "extra": 1}
            ),
            "unavailable value": json.dumps({"value": [], "value_available": False}),
            "truthy but not true availability": json.dumps(
                {"value": [], "value_available": "true"}
            ),
            "scalar value": json.dumps({"value": 5, "value_available": True}),
            "null created id": json.dumps({"value": [None], "value_available": True}),
            "empty created id": json.dumps({"value": [""], "value_available": True}),
            "duplicate created ids": json.dumps(
                {"value": ["501", "501"], "value_available": True}
            ),
            "missing condition map": json.dumps(
                {
                    "value": {
                        "takeoff_uids": {"t": "100"},
                        "annotation_uids": {"rect/a": "200"},
                    },
                    "value_available": True,
                }
            ),
            "map is not an object": paste(takeoff_uids=["100"]),
            "null target uid": paste(takeoff_uids={"t": None}),
            "non-string (null) object key is not valid JSON": json.dumps(
                {
                    "value": {
                        "takeoff_uids": {"t": "100"},
                        "annotation_uids": {"rect/a": "200"},
                        "condition_uids": {"c": "300"},
                    },
                    "value_available": True,
                }
            ).replace('"t":', "null:"),
            "empty source uid": paste(takeoff_uids={"": "100"}),
            "empty target uid": paste(takeoff_uids={"t": ""}),
            "duplicate takeoff targets": paste(takeoff_uids={"a": "100", "b": "100"}),
            "duplicate condition targets": paste(
                condition_uids={"a": "300", "b": "300"}
            ),
            "annotation source without a type": paste(annotation_uids={"a": "200"}),
            "annotation source without a uid": paste(annotation_uids={"rect/": "200"}),
            "optional map is not an object": paste(page_uids=["20"]),
        }
        for label, result_payload in malformed.items():
            with self.subTest(payload=label):
                self.assertIsNone(recover(result_payload))
        recovered = recover(
            json.dumps({"value": [501, "502"], "value_available": True})
        )
        self.assertEqual(recovered.created_resource_ids, ("501", "502"))
        self.assertEqual(recovered.created_uid_maps, ())
        self.assertEqual(recover(paste()).created_resource_ids, ("100", "200"))


_FAST_POLLING = CollaborationPollingPolicy(
    inactive_database_seconds=0.05,
    jitter_ratio=0.0,
    reconnect_backoff_seconds=(0.05,),
)


class _SecondPassBase(_SqlCollaborationCoordinatorCollaborationFixture):
    def published(self, coordinator, event):
        return [
            payload
            for published_event, payload in coordinator._event_bus.published
            if published_event is event
        ]

    def _shutdown_pumped(self, coordinator, dispatcher):
        done = threading.Event()
        results = []
        coordinator.request_shutdown(
            lambda success, message: (results.append((success, message)), done.set())
        )
        self.assertTrue(dispatcher.pump_until(done.is_set, 5))
        self.assertEqual(results, [(True, "")])

    @staticmethod
    def _await(dispatcher, event, timeout=3):
        """Wait for `event`; with a UI-thread dispatcher the test thread is the UI
        thread, so it must pump the bridge while it waits."""
        if dispatcher is None:
            return event.wait(timeout)
        return dispatcher.pump_until(event.is_set, timeout)

    def add_ready_runtime(self, coordinator, database_name, generation):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database=database_name),
            schema_version=SQL_SCHEMA_V1.version,
        )
        coordinator._registry.register(descriptor)
        coordinator._capabilities.mark_connected(descriptor.database_id)
        coordinator._capabilities.set_collaboration_state(
            descriptor.database_id, SynchronizationState.HEALTHY
        )
        runtime = _DatabaseRuntime(descriptor.database_id, generation)
        runtime.session = DatabaseSession(descriptor.database_id, str(uuid.uuid4()))
        runtime.established = True
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        coordinator._sessions.register(
            descriptor.database_id, runtime.session.session_id
        )
        return runtime

    def threaded_coordinator(
        self,
        *,
        store=None,
        dispatcher=None,
        events=None,
        polling_policy=_FAST_POLLING,
        reconciliation=None,
        journal=None,
        capabilities=None,
        descriptor=None,
        register_cleanup=True,
        **coordinator_kwargs,
    ):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = descriptor or DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        if capabilities is None:
            capabilities = DatabaseCapabilityService(descriptors, _PermissionProbe())
            capabilities.mark_connected(descriptor.database_id)
        store = store if store is not None else _LockingStore()
        events = events if events is not None else _EventBus()
        tokens, drafts = _token_service()
        coordinator = _coordinator(
            descriptors,
            store,
            _RemoteReader(),
            dispatcher if dispatcher is not None else _Dispatcher(),
            reconciliation if reconciliation is not None else _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            events,
            SQL_SCHEMA_V1.version,
            polling_policy,
            operation_journal=(
                journal if journal is not None else _PendingOperationJournal()
            ),
            **coordinator_kwargs,
        )
        if register_cleanup:
            self.addCleanup(_shutdown_coordinator, coordinator)
        return coordinator, descriptor, store, events, capabilities


class SqlCollaborationServerBackedFakeTests(unittest.TestCase):
    """The server model the lock/lease tests below rely on must itself be strict."""

    def test_locks_are_exclusive_across_sessions_and_expire_on_the_server_clock(self):
        state = _FakeSqlServerState()
        first = ResourceRef("condition", "42", 8)
        for session in ("alice", "bob"):
            state.start(session)
        ((resource, token),) = state.acquire("alice", (first,))
        self.assertEqual(resource, first)
        # Exclusive whatever the optional Bid context says.
        with self.assertRaises(SqlInfrastructureError) as denied:
            state.acquire("bob", (ResourceRef("condition", "42"),))
        self.assertEqual(denied.exception.details.code, SqlErrorCode.LOCKED)
        self.assertFalse(denied.exception.retryable)
        # Re-acquiring an owned row returns the same token and renews it.
        state.advance(COLLABORATION_LOCK_SECONDS - 1)
        state.heartbeat("alice")
        state.heartbeat("bob")
        self.assertEqual(state.acquire("alice", (first,))[0][1], token)
        state.advance(COLLABORATION_LOCK_SECONDS - 1)
        state.heartbeat("alice")
        state.heartbeat("bob")
        with self.assertRaises(SqlInfrastructureError):
            state.acquire("bob", (first,))
        # One second past the renewed expiry the row is free for the other session.
        state.advance(2)
        state.heartbeat("alice")
        state.heartbeat("bob")
        ((_resource, other_token),) = state.acquire("bob", (first,))
        self.assertNotEqual(other_token, token)
        self.assertFalse(state.release("alice", token))
        self.assertTrue(state.release("bob", other_token))
        self.assertFalse(state.release("bob", other_token))

    def test_acquisition_is_sorted_and_all_or_nothing(self):
        state = _FakeSqlServerState()
        for session in ("alice", "bob"):
            state.start(session)
        held = ResourceRef("condition", "43", 8)
        state.acquire("alice", (held,))
        wanted = (
            ResourceRef("condition", "44", 8),
            held,
            ResourceRef("condition", "42", 8),
            ResourceRef("condition", "42", 8),
        )
        with self.assertRaises(SqlInfrastructureError):
            state.acquire("bob", wanted)
        self.assertEqual(state.live_lock_tokens().keys(), {("condition", "43")})
        self.assertEqual(
            state.acquire_orders[-1],
            (("condition", "42"), ("condition", "43"), ("condition", "44")),
        )
        granted = state.acquire(
            "bob",
            (ResourceRef("condition", "44", 8), ResourceRef("condition", "42", 8)),
        )
        self.assertEqual(
            [resource.resource_id for resource, _token in granted], ["42", "44"]
        )
        self.assertEqual(len({token for _resource, token in granted}), 2)

    def test_stale_sessions_cannot_heartbeat_acquire_or_renew(self):
        state = _FakeSqlServerState()
        state.start("alice")
        resource = ResourceRef("condition", "42", 8)
        ((_resource, token),) = state.acquire("alice", (resource,))
        state.advance(COLLABORATION_STALE_SECONDS)
        state.heartbeat("alice")
        state.advance(COLLABORATION_STALE_SECONDS + 1)
        for call in (
            lambda: state.heartbeat("alice"),
            lambda: state.acquire("alice", (resource,)),
            lambda: state.renew("alice", token),
        ):
            with self.assertRaises(SqlInfrastructureError) as expired:
                call()
            self.assertTrue(expired.exception.session_expired)
            self.assertFalse(expired.exception.retryable)
        # A lock that is still live cannot be renewed by a different owner.
        state.start("bob")
        with self.assertRaises(SqlInfrastructureError):
            state.renew("bob", token)
        # Disconnecting drops every lock of the session.
        state.start("carol")
        state.acquire("carol", (ResourceRef("condition", "50", 8),))
        state.disconnect("carol", "closed")
        self.assertEqual(state.live_lock_tokens().keys(), set())
        self.assertEqual(state.closed_reasons, [("carol", "closed")])


class SqlCollaborationLeaseExclusivityTests(_SecondPassBase):
    def test_second_session_is_denied_until_the_first_releases_without_losing_its_session(
        self,
    ):
        state = _FakeSqlServerState()
        first_store = _ServerBackedStore(state)
        second_store = _ServerBackedStore(state)
        first, first_runtime = self.ready_coordinator(store=first_store)
        second, second_runtime = self.ready_coordinator(store=second_store)
        database_id = first_runtime.database_id
        unsorted = (
            ResourceRef("condition", "43", 8),
            ResourceRef("condition", "42", 8),
            ResourceRef("condition", "43", 8),
        )
        grants = []
        first.request_local_edit(database_id, unsorted, grants.append)
        first._process_edit_requests(first_runtime)
        self.assertTrue(grants[0].granted)
        # The coordinator forwards one sorted, de-duplicated batch.
        self.assertEqual(
            first_store.acquire_requests,
            [(ResourceRef("condition", "42", 8), ResourceRef("condition", "43", 8))],
        )
        self.assertEqual(
            state.acquire_orders, [(("condition", "42"), ("condition", "43"))]
        )
        first_tokens = dict(state.live_lock_tokens())
        self.assertEqual(len(first_tokens), 2)
        # The other session is denied as a whole (no partial lock on 44) and the
        # denial is not a trust loss: its session, health and drafts stay intact.
        denied = []
        second.request_local_edit(
            database_id,
            (ResourceRef("condition", "44", 8), ResourceRef("condition", "43")),
            denied.append,
        )
        second._process_edit_requests(second_runtime)
        self.assertEqual(
            denied,
            [
                EditLeaseResult(
                    False, "condition 43 is being edited by another session."
                )
            ],
        )
        self.assertEqual(state.live_lock_tokens(), first_tokens)
        self.assertIsNotNone(second_runtime.session)
        self.assertTrue(second_runtime.healthy)
        self.assertEqual(second_runtime.owned_locks, {})
        self.assertEqual(second._local_drafts._drafts, {})
        self.assertFalse(second_store.closed.is_set())
        # Independent resources are still granted to the second session.
        independent = []
        second.request_local_edit(
            database_id, (ResourceRef("condition", "44", 8),), independent.append
        )
        second._process_edit_requests(second_runtime)
        self.assertTrue(independent[0].granted)
        # Once the first session releases, the contested resources are free again.
        first.end_edit_lease(grants[0].handle)
        first._process_release_requests(first_runtime)
        self.assertEqual(set(state.live_lock_tokens()), {("condition", "44")})
        retry = []
        second.request_local_edit(
            database_id,
            (ResourceRef("condition", "42", 8), ResourceRef("condition", "43", 8)),
            retry.append,
        )
        second._process_edit_requests(second_runtime)
        self.assertTrue(retry[0].granted)
        self.assertTrue(
            {lock.lock_token for lock in retry[0].handle.locks}.isdisjoint(
                first_tokens.values()
            )
        )

    def test_mutation_denied_by_another_sessions_lock_keeps_the_session(self):
        state = _FakeSqlServerState()
        holder = ResourceRef("takeoffs_collection", "8", 8)
        state.start("other-client")
        state.acquire("other-client", (holder,))
        coordinator, runtime = self.ready_coordinator(store=_ServerBackedStore(state))
        results = []
        writes = []
        _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (holder,),
            lambda: writes.append("write") or _committed_execution("501"),
            results.append,
            operation_id="denied-by-other-session",
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(writes, [])
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.FAILED_BEFORE_COMMIT],
        )
        self.assertEqual(
            results[0].message,
            "takeoffs_collection 8 is being edited by another session.",
        )
        self.assertFalse(results[0].commit_attempted)
        self.assertIsNotNone(runtime.session)
        self.assertTrue(runtime.healthy)
        self.assertEqual(coordinator._local_drafts._drafts, {})
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        # The same session can run the mutation once the other client lets go.
        state.release(
            "other-client", state.live_lock_tokens()[("takeoffs_collection", "8")]
        )
        retry = []
        _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (holder,),
            lambda: writes.append("write") or _committed_execution("501"),
            retry.append,
            operation_id="retry-after-release",
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(writes, ["write"])
        self.assertEqual(
            [result.outcome_status for result in retry],
            [MutationOutcomeStatus.COMMITTED],
        )

    def test_mutation_lock_denial_leaves_the_worker_connected(self):
        state = _FakeSqlServerState()
        holder = ResourceRef("takeoffs_collection", "8", 8)
        state.start("other-client")
        state.acquire("other-client", (holder,))
        store = _ServerBackedStore(state)
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(store=store)
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        denied = threading.Event()
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (holder,),
            lambda: _committed_execution("501"),
            lambda result: (results.append(result), denied.set()),
            operation_id="worker-denied",
        )
        self.assertTrue(denied.wait(2))
        self.assertEqual(
            results[0].outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        # The conflict is the user's answer; the collaboration session survives it.
        self.assertTrue(runtime.thread.is_alive())
        self.assertIsNotNone(runtime.session)
        self.assertFalse(store.closed.is_set())
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.HEALTHY,
        )
        self.assertEqual(store.start_count, 1)


class _HeartbeatGateStore(_ServerBackedStore):
    """Holds the next heartbeat on the worker thread until the test releases it.
    The held heartbeat has not reached the server yet, so a test can queue work
    and move a clock deterministically before the worker learns of the loss."""

    def __init__(self, state):
        super().__init__(state)
        self.armed = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def heartbeat(self, *args):
        if self.armed:
            self.armed = False
            self.entered.set()
            if not self.release.wait(5):
                raise AssertionError("The held heartbeat was never released")
        return super().heartbeat(*args)

    def query_operation(self, database_id, operation_id):
        # A reconnect that outruns the UI thread (callbacks delivered later by the
        # bridge) recovers the journal before the cancelled operation's record was
        # removed; the server has no marker for an operation that never ran.
        return DurableOperationResult(
            database_id=database_id, operation_id=operation_id, found=False
        )


class SqlCollaborationLeaseExpiryTests(_SecondPassBase):
    def test_heartbeat_renews_owned_leases_and_expiry_follows_the_server_clock(self):
        state = _FakeSqlServerState()
        store = _ServerBackedStore(state)
        coordinator, runtime = self.ready_coordinator(store=store)
        database_id = runtime.database_id
        resource = ResourceRef("takeoff", "7", 8)
        grants = []
        coordinator.request_local_edit(database_id, (resource,), grants.append)
        coordinator._process_edit_requests(runtime)
        lock = grants[0].handle.locks[0]
        session_id = runtime.session.session_id
        state.start("other-client")

        def other_client_can_lock():
            state.heartbeat("other-client")
            try:
                state.acquire("other-client", (resource,))
            except SqlInfrastructureError as denied:
                self.assertEqual(denied.details.code, SqlErrorCode.LOCKED)
                return False
            return True

        # A heartbeat 30 server-seconds in renews the lease through the store.
        state.advance(COLLABORATION_LOCK_SECONDS - 15)
        state.heartbeat("other-client")
        coordinator._heartbeat(runtime)
        self.assertEqual(store.renewals, [(session_id, lock.lock_token)])
        self.assertEqual(runtime.owned_locks, {resource.lease_identity: lock})
        self.assertEqual(
            coordinator._sessions.lock_tokens(database_id, (resource,)),
            (lock.lock_token,),
        )
        # 60 server-seconds after acquisition the original expiry has passed,
        # yet the renewed lease still blocks the other client.
        state.advance(COLLABORATION_LOCK_SECONDS - 15)
        self.assertFalse(other_client_can_lock())
        # Without another heartbeat the server expires the lease by itself.
        state.advance(COLLABORATION_LOCK_SECONDS - 30 + 1)
        self.assertTrue(other_client_can_lock())
        # The silent owner now finds its session and lease gone.
        with self.assertRaises(SqlInfrastructureError) as expired:
            coordinator._heartbeat(runtime)
        self.assertTrue(expired.exception.session_expired)
        self.assertFalse(expired.exception.retryable)

    def test_lease_lost_on_the_server_while_the_session_lives_fails_the_heartbeat(self):
        state = _FakeSqlServerState()
        store = _ServerBackedStore(state)
        coordinator, runtime = self.ready_coordinator(store=store)
        resource = ResourceRef("takeoff", "7", 8)
        grants = []
        coordinator.request_local_edit(runtime.database_id, (resource,), grants.append)
        coordinator._process_edit_requests(runtime)
        state.locks.clear()  # the server-side cleanup removed the row
        with self.assertRaises(DatabaseCatalogError) as lost:
            coordinator._heartbeat(runtime)
        self.assertTrue(lost.exception.session_expired)
        self.assertEqual(
            str(lost.exception), "The edit lock expired and can no longer be renewed."
        )
        # The coordinator did not pretend the lease was renewed.
        self.assertEqual(store.renewals, [])
        self.assertEqual(
            runtime.owned_locks, {resource.lease_identity: grants[0].handle.locks[0]}
        )

    def _start_with_a_lease_and_a_queued_mutation_behind_a_held_heartbeat(
        self, dispatcher=None
    ):
        """Healthy threaded worker, one granted lease and a heartbeat held on the
        worker. While the heartbeat is held a mutation is queued, so the trust
        loss the test then causes meets a lease and a pending operation. The
        optional `dispatcher` (a _UiThreadDispatcher) delivers every callback
        later, on the test thread, like the Qt bridge."""
        state = _FakeSqlServerState()
        store = _HeartbeatGateStore(state)
        events = _EventBus()
        journal = _PendingOperationJournal()
        polling = CollaborationPollingPolicy(
            heartbeat_seconds=0.0,
            inactive_database_seconds=0.05,
            jitter_ratio=0.0,
            reconnect_backoff_seconds=(0.05,),
        )
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(
                store=store,
                events=events,
                polling_policy=polling,
                journal=journal,
                dispatcher=dispatcher,
                register_cleanup=dispatcher is None,
            )
        )
        if dispatcher is not None:
            self.addCleanup(self._shutdown_pumped, coordinator, dispatcher)
        database_id = descriptor.database_id
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.assertTrue(coordinator.start_database(database_id))
        self.assertTrue(self._await(dispatcher, healthy, 2))
        runtime = coordinator._runtime(database_id)
        resource = ResourceRef("condition", "42", 8)
        granted = threading.Event()
        grants = []
        coordinator.request_local_edit(
            database_id,
            (resource,),
            lambda result: (grants.append(result), granted.set()),
            owning_surface="condition-sidebar",
        )
        self.assertTrue(self._await(dispatcher, granted, 2))
        self.assertTrue(grants[0].granted)
        store.armed = True
        self.assertTrue(store.entered.wait(3))
        mutation_results = []
        mutation_writes = []
        self.assertEqual(
            _queue_test_mutation(
                coordinator,
                database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda: mutation_writes.append("unexpected write")
                or _committed_execution("501"),
                mutation_results.append,
                operation_id="queued-behind-the-trust-loss",
            ),
            runtime.generation,
        )
        self.assertEqual(
            len(coordinator._pending_mutations.for_database(database_id)), 1
        )
        self.assertEqual(len(journal.records), 1)
        # The healthy session (id, generation) every assertion below compares to.
        self.assertEqual((runtime.generation, runtime.session_generation), (1, 1))
        return SimpleNamespace(
            coordinator=coordinator,
            dispatcher=dispatcher,
            database_id=database_id,
            state=state,
            store=store,
            events=events,
            journal=journal,
            capabilities=capabilities,
            runtime=runtime,
            thread=runtime.thread,
            first_session=runtime.session.session_id,
            resource=resource,
            grant=grants[0],
            mutation_results=mutation_results,
            mutation_writes=mutation_writes,
        )

    def _assert_trust_loss_cleanup(self, run):
        """What every trust loss must leave behind, whichever way it reconnects."""
        coordinator = run.coordinator
        # The session was closed once, with the trust-lost reason, and the server
        # lease went with it.
        self.assertEqual(run.state.closed_reasons, [(run.first_session, "trust-lost")])
        self.assertEqual(run.state.live_lock_tokens(), {})
        # The granted lease was reported lost exactly once, with its draft.
        losses = [
            payload["loss"]
            for payload in self.published(coordinator, AppEvents.EDIT_LEASE_LOST)
        ]
        self.assertEqual(
            [(loss.draft_id, loss.reason, loss.resources) for loss in losses],
            [(run.grant.handle.draft_id, "trust-lost", (run.resource,))],
        )
        self.assertEqual(losses[0].runtime_generation, 1)
        self.assertIsNone(coordinator._local_drafts.get(run.grant.handle.draft_id))
        self.assertEqual(
            coordinator._sessions.lock_tokens(run.database_id, (run.resource,)), ()
        )
        # The queued mutation never ran: it was cancelled before start and both
        # its pending entry and its journal record were dropped.
        self.assertEqual(run.mutation_writes, [])
        self.assertEqual(
            [
                (result.outcome_status, result.message, result.runtime_generation)
                for result in run.mutation_results
            ],
            [
                (
                    MutationOutcomeStatus.CANCELLED_BEFORE_START,
                    "SQL collaboration stopped before the queued mutation was "
                    "executed.",
                    1,
                )
            ],
        )
        self.assertEqual(
            coordinator._pending_mutations.for_database(run.database_id), ()
        )
        self.assertEqual(run.journal.records, {})

    def _collaboration_states(self, run):
        return [
            (payload["state"], payload["message"])
            for payload in self.published(
                run.coordinator, AppEvents.COLLABORATION_STATE_CHANGED
            )
        ]

    def test_session_expired_heartbeat_ends_the_worker_until_an_explicit_reprobe(
        self,
    ):
        # D9: a non-retryable SESSION_EXPIRED heartbeat error ends the worker for
        # good (no backoff, no automatic reconnect); only an explicit capability
        # re-probe (DATABASE_CAPABILITIES_CHANGED after the worker has stopped)
        # starts a replacement runtime. The synchronous test dispatcher runs the
        # disconnect callback while the dying worker is still alive.
        self._session_expired_ends_the_worker_until_an_explicit_reprobe(None)

    def test_session_expired_heartbeat_ends_the_worker_until_an_explicit_reprobe_under_the_ui_dispatcher(
        self,
    ):
        # D9b: the same contract when the disconnect callback is delivered LATER on
        # the UI thread, after the worker thread has exited (the real
        # QtCallbackBridge order). Before D13 the disconnect state change
        # published DATABASE_CAPABILITIES_CHANGED, which restarted the dead worker
        # without any re-probe.
        self._session_expired_ends_the_worker_until_an_explicit_reprobe(
            _UiThreadDispatcher()
        )

    def _session_expired_ends_the_worker_until_an_explicit_reprobe(self, dispatcher):
        run = self._start_with_a_lease_and_a_queued_mutation_behind_a_held_heartbeat(
            dispatcher
        )
        coordinator = run.coordinator
        database_id = run.database_id
        # The server clock passes the session timeout while the client keeps its
        # own clock: the held heartbeat is rejected by the server.
        run.state.advance(COLLABORATION_STALE_SECONDS + 1)
        run.store.release.set()
        run.thread.join(3)
        self.assertFalse(run.thread.is_alive())
        if dispatcher is None:
            time.sleep(0.3)  # ample for a (wrongly) scheduled 0.05 s backoff reconnect
        else:
            # Deliver the queued disconnect and everything it triggers (a wrongly
            # restarted worker needs a drain thread and more callbacks); the
            # runaway guard keeps a restart loop from spinning.
            self.assertLess(dispatcher.pump_idle(), 200)
        expired_message = (
            "The SQL collaboration session expired. Reconnecting is required "
            "before editing."
        )
        self.assertEqual(
            self._collaboration_states(run),
            [
                ("connecting", ""),
                ("catching_up", ""),
                ("healthy", ""),
                ("disconnected", expired_message),
            ],
        )
        status = run.capabilities.collaboration_status(database_id)
        self.assertEqual(
            (status.state, status.message),
            (SynchronizationState.DISCONNECTED, expired_message),
        )
        # No reconnect: one session ever started, no backoff attempt counted, the
        # same stopped runtime stays registered with its session gone and its
        # session generation advanced once (install, then reset).
        self.assertEqual(run.store.start_count, 1)
        self.assertIs(coordinator._runtime(database_id), run.runtime)
        self.assertIs(run.runtime.thread, run.thread)
        self.assertEqual(run.runtime.reconnect_count, 0)
        self.assertIsNone(run.runtime.session)
        self.assertEqual(
            (run.runtime.generation, run.runtime.session_generation), (1, 2)
        )
        self.assertEqual(coordinator._sessions.get(database_id), "")
        self._assert_trust_loss_cleanup(run)
        # Another client takes the freed resource while this one is disconnected.
        run.state.start("other-client")
        ((_resource, other_token),) = run.state.acquire("other-client", (run.resource,))
        # The explicit re-probe replaces the stopped runtime with a new one.
        healthy_again = _state_signal(
            run.events, database_id, SynchronizationState.HEALTHY
        )
        run.events.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id
        )
        self.assertTrue(self._await(dispatcher, healthy_again))
        self.assertEqual(run.store.start_count, 2)
        replacement = coordinator._runtime(database_id)
        self.assertIsNot(replacement, run.runtime)
        self.assertIsNot(replacement.thread, run.thread)
        self.assertEqual(
            (replacement.generation, replacement.session_generation), (2, 1)
        )
        self.assertNotEqual(replacement.session.session_id, run.first_session)
        self.assertEqual(
            self._collaboration_states(run)[4:],
            [
                ("read_only", "SQL collaboration is closing."),
                ("stopped", ""),
                ("connecting", ""),
                ("catching_up", ""),
                ("healthy", ""),
            ],
        )
        # The reconnected session is denied while the other client holds the
        # resource and is granted a NEW lease after the holder releases it.
        denied = threading.Event()
        denials = []
        coordinator.request_local_edit(
            database_id,
            (run.resource,),
            lambda result: (denials.append(result), denied.set()),
        )
        self.assertTrue(self._await(dispatcher, denied, 2))
        self.assertFalse(denials[0].granted)
        run.state.release("other-client", other_token)
        regrant = threading.Event()
        regrants = []
        coordinator.request_local_edit(
            database_id,
            (run.resource,),
            lambda result: (regrants.append(result), regrant.set()),
        )
        self.assertTrue(self._await(dispatcher, regrant, 2))
        self.assertTrue(regrants[0].granted)
        self.assertNotEqual(
            regrants[0].handle.locks[0].lock_token, run.grant.handle.locks[0].lock_token
        )
        self.assertEqual(regrants[0].handle.runtime_generation, replacement.generation)

    def test_suspension_gap_reconnects_in_the_same_worker_with_a_new_session(
        self,
    ):
        # D9: a local suspension gap longer than the session lifetime is the
        # opposite case: the same worker thread drops the session and starts a new
        # one at once (no re-probe, no backoff, same runtime).
        self._suspension_gap_reconnects_in_the_same_worker(None)

    def test_suspension_gap_reconnects_in_the_same_worker_under_the_ui_dispatcher(
        self,
    ):
        # D9b: the same contract with every callback delivered later on the UI
        # thread. The worker never exits, so the capability-change restart rule
        # must stay out of the way: same thread, same runtime, no extra runtime.
        self._suspension_gap_reconnects_in_the_same_worker(_UiThreadDispatcher())

    def _suspension_gap_reconnects_in_the_same_worker(self, dispatcher):
        run = self._start_with_a_lease_and_a_queued_mutation_behind_a_held_heartbeat(
            dispatcher
        )
        coordinator = run.coordinator
        database_id = run.database_id
        restored = threading.Event()
        run.events.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED,
            lambda database_id="", state="", **_payload: (
                restored.set()
                if state == "healthy" and run.store.start_count == 2
                else None
            ),
        )
        real_monotonic = time.monotonic
        offset = [0.0]
        with patch.object(time, "monotonic", lambda: real_monotonic() + offset[0]):
            # The computer was suspended for longer than the session lifetime.
            offset[0] = COLLABORATION_STALE_SECONDS + 5
            run.store.release.set()
            self.assertTrue(self._await(dispatcher, restored))
            offset[0] = 0.0
        if dispatcher is None:
            time.sleep(0.2)  # a wrongly repeated disconnect/reconnect would show here
        else:
            dispatcher.pump_until(lambda: False, 0.2)
        suspended_message = (
            "The collaboration session expired while the computer was suspended."
        )
        expected_states = [
            ("connecting", ""),
            ("catching_up", ""),
            ("healthy", ""),
            ("disconnected", suspended_message),
            ("catching_up", ""),
            ("healthy", ""),
        ]
        if dispatcher is not None:
            # The worker had already installed the new session when the UI thread
            # got the disconnect, so the stale (old session generation) callback
            # is dropped instead of regressing the state to disconnected.
            del expected_states[3]
        self.assertEqual(self._collaboration_states(run), expected_states)
        # The very same worker thread and runtime reconnected: no backoff attempt
        # was counted and the session generation advanced twice (reset, install).
        self.assertEqual(run.store.start_count, 2)
        self.assertTrue(run.thread.is_alive())
        self.assertIs(coordinator._runtime(database_id), run.runtime)
        self.assertIs(run.runtime.thread, run.thread)
        self.assertEqual(run.runtime.reconnect_count, 0)
        self.assertEqual(
            (run.runtime.generation, run.runtime.session_generation), (1, 3)
        )
        self.assertNotEqual(run.runtime.session.session_id, run.first_session)
        self.assertEqual(
            coordinator._sessions.get(database_id), run.runtime.session.session_id
        )
        self.assertEqual(
            coordinator.status(database_id).state, SynchronizationState.HEALTHY
        )
        self._assert_trust_loss_cleanup(run)
        # The new session is usable: the resource is granted again as a NEW lease.
        regrant = threading.Event()
        regrants = []
        coordinator.request_local_edit(
            database_id,
            (run.resource,),
            lambda result: (regrants.append(result), regrant.set()),
        )
        self.assertTrue(self._await(dispatcher, regrant, 2))
        self.assertTrue(regrants[0].granted)
        self.assertNotEqual(
            regrants[0].handle.locks[0].lock_token, run.grant.handle.locks[0].lock_token
        )
        self.assertEqual(regrants[0].handle.runtime_generation, run.runtime.generation)


class SqlCollaborationUiAffinityTests(_SecondPassBase):
    def test_worker_results_cross_the_bridge_before_events_or_callbacks_run(self):
        worker_threads = {"heartbeat": set(), "poll": set(), "operation": set()}
        apply_threads = []

        class _RecordingStore(_ServerBackedStore):
            def heartbeat(self, *args):
                worker_threads["heartbeat"].add(threading.get_ident())
                return super().heartbeat(*args)

            def poll_changes(self, *args):
                worker_threads["poll"].add(threading.get_ident())
                return super().poll_changes(*args)

        class _RecordingReconciliation(_Reconciliation):
            def apply(
                self, hydrated, projection_barrier=None, *, local_completion=False
            ):
                apply_threads.append(threading.get_ident())
                return super().apply(
                    hydrated, projection_barrier, local_completion=local_completion
                )

        ui_thread = threading.get_ident()
        dispatcher = _UiThreadDispatcher()
        events = _ThreadRecordingEventBus()
        store = _RecordingStore()
        polling = CollaborationPollingPolicy(
            heartbeat_seconds=0.0,
            inactive_database_seconds=0.05,
            jitter_ratio=0.0,
        )
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(
                store=store,
                dispatcher=dispatcher,
                events=events,
                polling_policy=polling,
                reconciliation=_RecordingReconciliation(),
            )
        )
        database_id = descriptor.database_id
        callback_threads = {}
        opened = []

        def record(name, sink):
            def callback(*values):
                callback_threads[name] = threading.get_ident()
                sink.append(values)

            return callback

        self.assertTrue(
            coordinator.start_database(
                database_id, on_initial_open=record("initial-open", opened)
            )
        )
        self.assertTrue(dispatcher.pump_until(lambda: opened))
        self.assertEqual(opened, [(True, "")])
        coordinator.update_presence(database_id, "8", "20", PresenceMode.EDITING)
        resource = ResourceRef("takeoff", "7", 8)
        grants = []
        coordinator.request_local_edit(
            database_id, (resource,), record("lease", grants)
        )
        self.assertTrue(dispatcher.pump_until(lambda: grants))
        self.assertTrue(grants[0][0].granted)
        mutation_results = []

        def operation():
            worker_threads["operation"].add(threading.get_ident())
            return _committed_execution("501")

        _queue_test_mutation(
            coordinator,
            database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            operation,
            record("mutation", mutation_results),
            operation_id="affinity",
        )
        self.assertTrue(dispatcher.pump_until(lambda: mutation_results))
        self.assertEqual(
            mutation_results[0][0].outcome_status, MutationOutcomeStatus.COMMITTED
        )
        applied_before = len(apply_threads)
        store.change = _change(
            database_id,
            ResourceRef("takeoff", "30", 8),
            sequence=2,
            source=str(uuid.uuid4()),
        )
        self.assertTrue(
            dispatcher.pump_until(lambda: len(apply_threads) > applied_before)
        )
        self.assertTrue(
            dispatcher.pump_until(
                lambda: any(
                    payload["bid_uid"] == "8"
                    for payload in self.published(
                        coordinator, AppEvents.PRESENCE_CHANGED
                    )
                )
            )
        )
        stopped = []
        coordinator.stop_database_async(database_id, callback=record("stop", stopped))
        self.assertTrue(dispatcher.pump_until(lambda: stopped))
        self.assertEqual(stopped, [(True, "")])
        # Positive controls: SQL work really happened on a worker thread and the
        # worker handed results to the bridge instead of running them itself.
        for name, threads in worker_threads.items():
            with self.subTest(worker_phase=name):
                self.assertTrue(threads)
                self.assertNotIn(ui_thread, threads)
        self.assertNotEqual(set(dispatcher.dispatched_from), {ui_thread})
        # Everything the UI observes - every EventBus publication, every caller
        # callback, every projection - happened on the thread that pumped the bridge.
        published_events = {event for event, _thread in events.publish_threads}
        for expected in (
            AppEvents.COLLABORATION_STATE_CHANGED,
            AppEvents.PRESENCE_CHANGED,
            AppEvents.EDIT_LEASE_LOST,
            AppEvents.COLLABORATION_MUTATION_STATE_CHANGED,
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
        ):
            self.assertIn(expected, published_events)
        self.assertEqual(
            {thread for _event, thread in events.publish_threads}, {ui_thread}
        )
        self.assertEqual(
            callback_threads,
            {
                "initial-open": ui_thread,
                "lease": ui_thread,
                "mutation": ui_thread,
                "stop": ui_thread,
            },
        )
        self.assertEqual({thread for thread in apply_threads}, {ui_thread})
        self.assertEqual(
            {thread for _name, thread in dispatcher.executed_on}, {ui_thread}
        )


class SqlCollaborationUiBridgeLifecycleTests(_SecondPassBase):
    """Reconnect and recovery with the UI bridge between worker and projection."""

    polling = CollaborationPollingPolicy(
        heartbeat_seconds=0.0,
        inactive_database_seconds=0.05,
        jitter_ratio=0.0,
        reconnect_backoff_seconds=(0.05,),
    )

    def started(self, store):
        dispatcher = _UiThreadDispatcher()
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(
                store=store, dispatcher=dispatcher, polling_policy=self.polling
            )
        )
        database_id = descriptor.database_id

        def state():
            return capabilities.collaboration_status(database_id).state

        self.assertTrue(coordinator.start_database(database_id))
        self.assertTrue(
            dispatcher.pump_until(lambda: state() == SynchronizationState.HEALTHY, 5)
        )
        return coordinator, dispatcher, capabilities, database_id, state

    def states(self, coordinator):
        return [
            p["state"]
            for p in self.published(coordinator, AppEvents.COLLABORATION_STATE_CHANGED)
        ]

    def stop(self, coordinator, dispatcher, database_id):
        done = threading.Event()
        coordinator.stop_database_async(database_id, callback=lambda *_r: done.set())
        self.assertTrue(dispatcher.pump_until(done.is_set, 5))

    def test_reconnect_and_controlled_recovery_restore_health_and_the_writer_session(
        self,
    ):
        store = _ScriptedStore()
        coordinator, dispatcher, capabilities, database_id, state = self.started(store)
        first_session = coordinator._sessions.get(database_id)
        store.fail_once["heartbeat"] = DatabaseCatalogError("lost", retryable=True)
        self.assertTrue(
            dispatcher.pump_until(lambda: store.calls["start_session"] >= 2, 5)
        )
        self.assertTrue(
            dispatcher.pump_until(
                lambda: state() == SynchronizationState.HEALTHY
                and coordinator._runtime(database_id).healthy,
                5,
            )
        )
        runtime = coordinator._runtime(database_id)
        second_session = coordinator._sessions.get(database_id)
        self.assertNotEqual(first_session, second_session)
        self.assertEqual(second_session, runtime.session.session_id)
        self.assertTrue(capabilities.is_editable(database_id))
        self.assertEqual(
            self.states(coordinator),
            [
                "connecting",
                "catching_up",
                "healthy",
                "disconnected",
                "catching_up",
                "healthy",
            ],
        )
        # Controlled recovery: requested, resumed, then a third healthy session.
        coordinator._on_reconciliation_required(
            (database_id, runtime.generation, "probe")
        )
        dispatcher.pump_until(lambda: False, 0.3)
        self.assertEqual(state(), SynchronizationState.RECONCILIATION_REQUIRED)
        self.assertFalse(capabilities.is_editable(database_id))
        self.assertIs(coordinator.resume_controlled_recovery(database_id), True)
        self.assertTrue(
            dispatcher.pump_until(
                lambda: store.calls["start_session"] >= 3
                and state() == SynchronizationState.HEALTHY,
                5,
            )
        )
        self.assertTrue(capabilities.is_editable(database_id))
        self.assertEqual(
            coordinator._sessions.get(database_id), runtime.session.session_id
        )
        self.assertNotIn(
            coordinator._sessions.get(database_id), (first_session, second_session)
        )
        self.stop(coordinator, dispatcher, database_id)

    def test_an_uncertain_commit_is_resolved_through_the_bridge_after_reconnecting(
        self,
    ):
        class _Store(_RecoverableProjectionStore, _ScriptedStore):
            pass

        store = _Store()
        coordinator, dispatcher, capabilities, database_id, state = self.started(store)
        writes = []
        statuses = []
        _queue_test_mutation(
            coordinator,
            database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: writes.append("write") or _unknown_commit(),
            lambda result: statuses.append(result.outcome_status),
            operation_id="uncertain-through-the-bridge",
        )
        request = coordinator._pending_mutations.for_database(database_id)[0].request
        store.durable_results[request.operation_id] = _durable_result(request, "501")
        self.assertTrue(dispatcher.pump_until(lambda: len(statuses) >= 2, 5))
        self.assertTrue(
            dispatcher.pump_until(lambda: state() == SynchronizationState.HEALTHY, 5)
        )
        self.assertEqual(
            statuses,
            [
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED,
            ],
        )
        self.assertEqual(writes, ["write"])
        self.assertTrue(capabilities.is_editable(database_id))
        self.assertEqual(coordinator._pending_mutations.for_database(database_id), ())
        self.assertEqual(coordinator._operation_journal.records, {})
        self.stop(coordinator, dispatcher, database_id)


def _durable_result(request, *created_ids):
    return DurableOperationResult(
        database_id=request.database_id,
        operation_id=request.operation_id,
        found=True,
        mutation_type=request.mutation_type.value,
        request_hash=request.request_hash,
        result_format_version=1,
        result_payload=json.dumps(
            {"value": list(created_ids), "value_available": True},
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def _unknown_commit(message="The connection was lost while committing."):
    return MutationExecutionResult(
        outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
        message=message,
        commit_attempted=True,
    )


class SqlCollaborationUncertainCommitTests(_SecondPassBase):
    def queue_uncertain_write(self, coordinator, runtime, writes, observe=None):
        results = []

        def callback(result):
            results.append(result)
            if observe is not None:
                observe(result)

        _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: writes.append("write") or _unknown_commit(),
            callback,
            operation_id="uncertain-commit",
        )
        request = coordinator._pending_mutations.for_database(runtime.database_id)[
            0
        ].request
        return request, results

    def reconnect(self, coordinator, runtime):
        """Do what the worker does after the retryable failure: new session, recovery."""
        coordinator._reset_session(runtime)
        session_generation = coordinator._install_session(
            runtime, DatabaseSession(runtime.database_id, str(uuid.uuid4()))
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                runtime.database_id,
                runtime.generation,
                session_generation,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
                None,
            )
        )

    def test_unknown_commit_is_reported_then_resolved_from_the_marker_without_replay(
        self,
    ):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        writes = []
        seen = []

        def observe(result):
            pending = coordinator._pending_mutations.get(result.operation_id)
            record = journal.records.get(result.operation_id)
            seen.append((result.outcome_status, pending.state, record.state))

        request, results = self.queue_uncertain_write(
            coordinator, runtime, writes, observe
        )
        with self.assertRaises(DatabaseCatalogError) as failure:
            coordinator._process_mutation_requests(runtime)
        # A reconnect (never a retry of the write) is required to learn the outcome.
        self.assertTrue(failure.exception.retryable)
        self.assertFalse(failure.exception.read_only_required)
        self.assertEqual(writes, ["write"])
        self.assertEqual(
            [
                (result.outcome_status, result.commit_attempted, result.message)
                for result in results
            ],
            [
                (
                    MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                    True,
                    "The connection was lost while committing.",
                )
            ],
        )
        pending = coordinator._pending_mutations.get(request.operation_id)
        self.assertEqual(pending.state, PendingMutationState.UNCERTAIN)
        self.assertEqual(
            journal.records[request.operation_id].state, PendingMutationState.UNCERTAIN
        )
        self.assertEqual(set(coordinator._uncertain_callbacks), {request.operation_id})
        self.assertEqual(
            [
                payload["state"]
                for payload in self.published(
                    coordinator, AppEvents.COLLABORATION_MUTATION_STATE_CHANGED
                )
            ],
            ["queued", "executing", "uncertain"],
        )
        # The marker was not consulted before reconnecting.
        store.durable_results[request.operation_id] = _durable_result(request, "501")
        with patch.object(
            store, "query_operation", wraps=store.query_operation
        ) as query:
            self.reconnect(coordinator, runtime)
        self.assertEqual(
            [call.args for call in query.call_args_list],
            [(runtime.database_id, request.operation_id)],
        )
        self.assertEqual(writes, ["write"])
        self.assertEqual(
            [
                (
                    result.outcome_status,
                    result.created_resource_ids,
                    result.commit_attempted,
                )
                for result in results
            ],
            [
                (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, (), True),
                (MutationOutcomeStatus.COMMITTED, ("501",), True),
            ],
        )
        self.assertEqual(results[1].authoritative_result.created_resource_ids, ("501",))
        # The recovered result is delivered while the operation is PROJECTING in
        # both the registry and the journal (never a replayed EXECUTING write).
        self.assertEqual(
            seen,
            [
                (
                    MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                    PendingMutationState.EXECUTING,
                    PendingMutationState.EXECUTING,
                ),
                (
                    MutationOutcomeStatus.COMMITTED,
                    PendingMutationState.PROJECTING,
                    PendingMutationState.PROJECTING,
                ),
            ],
        )
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})
        self.assertEqual(coordinator._uncertain_callbacks, {})
        self.assertEqual(
            [
                payload["state"]
                for payload in self.published(
                    coordinator, AppEvents.COLLABORATION_MUTATION_STATE_CHANGED
                )
            ],
            ["queued", "executing", "uncertain", "projecting", "queued"],
        )

    def test_unknown_commit_without_a_marker_is_reported_as_not_committed(self):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        writes = []
        request, results = self.queue_uncertain_write(coordinator, runtime, writes)
        with self.assertRaises(DatabaseCatalogError):
            coordinator._process_mutation_requests(runtime)
        self.reconnect(coordinator, runtime)
        # No durable marker: the transaction rolled back. The write is not re-run.
        self.assertEqual(writes, ["write"])
        self.assertEqual(
            [(result.outcome_status, result.commit_attempted) for result in results],
            [
                (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, True),
                (MutationOutcomeStatus.FAILED_BEFORE_COMMIT, False),
            ],
        )
        self.assertEqual(
            results[1].message,
            "The SQL operation did not commit before the connection was lost.",
        )
        self.assertEqual(results[1].runtime_generation, runtime.generation)
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})
        self.assertEqual(coordinator._uncertain_callbacks, {})

    def test_unknown_commit_with_a_foreign_marker_goes_read_only_and_keeps_its_record(
        self,
    ):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        writes = []
        request, results = self.queue_uncertain_write(coordinator, runtime, writes)
        with self.assertRaises(DatabaseCatalogError):
            coordinator._process_mutation_requests(runtime)
        store.durable_results[request.operation_id] = replace(
            _durable_result(request, "501"), request_hash="f" * 64
        )
        coordinator._reset_session(runtime)
        coordinator._install_session(
            runtime, DatabaseSession(runtime.database_id, str(uuid.uuid4()))
        )
        with self.assertRaises(DatabaseCatalogError) as mismatch:
            coordinator._recover_journaled_operations(runtime)
        self.assertTrue(mismatch.exception.read_only_required)
        self.assertEqual(
            str(mismatch.exception),
            "A durable SQL operation does not match its local recovery record.",
        )
        self.assertEqual(writes, ["write"])
        self.assertEqual(len(results), 1)
        self.assertEqual(runtime.recovered_operation_ids, set())
        # The undecided operation keeps its recovery metadata and callback.
        self.assertEqual(
            coordinator._pending_mutations.get(request.operation_id).state,
            PendingMutationState.UNCERTAIN,
        )
        self.assertIn(request.operation_id, journal.records)
        self.assertIn(request.operation_id, coordinator._uncertain_callbacks)

    def test_worker_reconnects_after_an_unknown_commit_and_never_replays_the_write(
        self,
    ):
        store = _RecoverableProjectionStore()
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(store=store)
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        first_session = store.session_id
        writes = []
        done = threading.Event()
        results = []
        _queue_test_mutation(
            coordinator,
            descriptor.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: writes.append("write") or _unknown_commit(),
            lambda result: (
                results.append(result),
                done.set() if len(results) == 2 else None,
            ),
            operation_id="uncertain-worker",
        )
        request = coordinator._pending_mutations.for_database(descriptor.database_id)[
            0
        ].request
        store.durable_results[request.operation_id] = _durable_result(request, "501")
        self.assertTrue(done.wait(3))
        self.assertEqual(writes, ["write"])
        self.assertEqual(store.start_count, 2)
        self.assertNotEqual(store.session_id, first_session)
        self.assertEqual(
            [result.outcome_status for result in results],
            [
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED,
            ],
        )
        self.assertEqual(coordinator._uncertain_callbacks, {})
        self.assertEqual(coordinator._operation_journal.records, {})
        self.assertEqual(
            coordinator._pending_mutations.for_database(descriptor.database_id), ()
        )
        self.assertEqual(coordinator.metrics(descriptor.database_id).reconnect_count, 1)


class SqlCollaborationControlledRecoveryRequestTests(_SecondPassBase):
    def test_simultaneous_projection_failures_request_recovery_once_and_recover_each_once(
        self,
    ):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        recovery_started = []
        coordinator._event_bus.subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            lambda database_id="", **_payload: recovery_started.append(
                coordinator.resume_controlled_recovery(database_id)
            ),
        )
        writes = []
        callbacks = {"first": [], "second": []}
        for name, created in (("first", "501"), ("second", "502")):
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "8", 8),),
                lambda: writes.append("write") or _committed_execution("0"),
                callbacks[name].append,
                operation_id=f"projection-failure-{name}",
            )
        requests = [
            pending.request
            for pending in coordinator._pending_mutations.for_database(
                runtime.database_id
            )
        ]
        self.assertEqual(len(requests), 2)
        # Both writes were already dequeued and committed by the worker.
        while not runtime.mutation_requests.empty():
            runtime.mutation_requests.get_nowait()
        for request, created in zip(requests, ("501", "502")):
            store.durable_results[request.operation_id] = _durable_result(
                request, created
            )
            callback = (
                callbacks["first"]
                if request.payload["test_operation"].endswith("first")
                else callbacks["second"]
            )
            coordinator._complete_mutation_request(
                (
                    callback.append,
                    QueuedMutationResult(
                        database_id=runtime.database_id,
                        runtime_generation=runtime.generation,
                        operation_id=request.operation_id,
                        outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                        message="projection failed",
                        commit_attempted=True,
                    ),
                )
            )
        # Two failed projections, one controlled-recovery request.
        self.assertEqual(recovery_started, [True])
        self.assertEqual(
            [
                payload["state"]
                for payload in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
            ],
            ["reconciliation_required", "connecting"],
        )
        self.assertEqual(
            [
                payload["reason"]
                for payload in self.published(
                    coordinator, AppEvents.FULL_RECONCILIATION_REQUIRED
                )
            ],
            ["A committed SQL mutation could not be projected locally."],
        )
        self.assertEqual(
            {
                pending.request.operation_id: pending.state
                for pending in coordinator._pending_mutations.for_database(
                    runtime.database_id
                )
            },
            {
                request.operation_id: PendingMutationState.RECOVERING
                for request in requests
            },
        )
        self.assertEqual(
            set(coordinator._uncertain_callbacks),
            {request.operation_id for request in requests},
        )
        self.assertEqual(
            {
                name: [r.outcome_status for r in values]
                for name, values in callbacks.items()
            },
            {
                "first": [MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED],
                "second": [MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED],
            },
        )
        # The worker-owned recovery resolves both from their durable markers.
        coordinator._reset_session(runtime)
        with runtime.lock:
            runtime.recovery_requested = False
            runtime.recovery_ready = False
            runtime.pending_delivery = False
        session_generation = coordinator._install_session(
            runtime, DatabaseSession(runtime.database_id, str(uuid.uuid4()))
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                runtime.database_id,
                runtime.generation,
                session_generation,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
                None,
            )
        )
        self.assertEqual(writes, [])
        self.assertEqual(
            {
                name: [(r.outcome_status, r.created_resource_ids) for r in values]
                for name, values in callbacks.items()
            },
            {
                "first": [
                    (MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED, ()),
                    (MutationOutcomeStatus.COMMITTED, ("501",)),
                ],
                "second": [
                    (MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED, ()),
                    (MutationOutcomeStatus.COMMITTED, ("502",)),
                ],
            },
        )
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})
        self.assertEqual(coordinator._uncertain_callbacks, {})


def _placement_request(database_id, label, **overrides):
    values = dict(
        database_id=database_id,
        operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"ostv-second-pass:{label}")),
        mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
        owning_surface="main-plan",
        resources=(ResourceRef("takeoffs_collection", "8", 8),),
        payload={"label": label},
    )
    values.update(overrides)
    return QueuedMutationRequest(**values)


class SqlCollaborationQueueIsolationTests(_SecondPassBase):
    def test_each_database_has_its_own_bounded_fifo_queue(self):
        coordinator, runtime_a = self.ready_coordinator()
        runtime_b = self.add_ready_runtime(coordinator, "OTHER", 9)
        for runtime in (runtime_a, runtime_b):
            runtime.healthy = False
            runtime.pending_delivery = True
        calls = []
        results = {"a": [], "b": []}
        requests = {"a": [], "b": []}

        def submit(name, runtime, index):
            request = _placement_request(runtime.database_id, f"{name}-{index}")
            requests[name].append(request)

            def operation():
                calls.append((name, index))
                return _committed_execution(f"{name}{index}")

            return coordinator.queue_request(request, operation, results[name].append)

        for index in range(64):
            self.assertEqual(submit("a", runtime_a, index), runtime_a.generation)
        # A full queue on one database never blocks another database.
        for index in range(64):
            self.assertEqual(submit("b", runtime_b, index), runtime_b.generation)
        self.assertEqual(submit("a", runtime_a, 64), -1)
        self.assertEqual(submit("b", runtime_b, 64), -1)
        self.assertEqual(
            (runtime_a.mutation_requests.qsize(), runtime_b.mutation_requests.qsize()),
            (64, 64),
        )
        for name in ("a", "b"):
            self.assertEqual(
                [(r.operation_id, r.outcome_status) for r in results[name]],
                [(requests[name][64].operation_id, MutationOutcomeStatus.REJECTED)],
            )
        # Cancelling needs the owning database: another database's id is refused.
        self.assertFalse(
            coordinator.cancel_queued_mutation(
                runtime_a.database_id, requests["b"][0].operation_id
            )
        )
        self.assertTrue(
            coordinator.cancel_queued_mutation(
                runtime_b.database_id, requests["b"][0].operation_id
            )
        )
        # Unblocking one database processes only its own queue, in submission order.
        runtime_a.healthy = True
        runtime_a.pending_delivery = False
        for _ in range(3):
            coordinator._process_mutation_requests(runtime_a)
        self.assertEqual(calls, [("a", 0), ("a", 1), ("a", 2)])
        self.assertEqual(runtime_a.mutation_requests.qsize(), 61)
        self.assertEqual(runtime_b.mutation_requests.qsize(), 64)
        runtime_b.healthy = True
        runtime_b.pending_delivery = False
        for _ in range(2):
            coordinator._process_mutation_requests(runtime_b)
        # b-0 was cancelled before it started; b-1 is the next write in FIFO order.
        self.assertEqual(calls[3:], [("b", 1)])
        self.assertEqual(
            [(r.operation_id, r.outcome_status) for r in results["b"][1:]],
            [
                (
                    requests["b"][0].operation_id,
                    MutationOutcomeStatus.CANCELLED_BEFORE_START,
                ),
                (requests["b"][1].operation_id, MutationOutcomeStatus.COMMITTED),
            ],
        )
        self.assertEqual(
            [r.operation_id for r in results["a"][1:]],
            [request.operation_id for request in requests["a"][:3]],
        )

    def test_cancellation_is_only_possible_before_the_worker_starts_executing(self):
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        database_id = runtime.database_id
        attempts = []
        results = []
        request = _placement_request(database_id, "cancel-too-late")

        def operation():
            attempts.append(
                (
                    "executing",
                    coordinator._pending_mutations.get(request.operation_id).state,
                    coordinator.cancel_queued_mutation(
                        database_id, request.operation_id
                    ),
                )
            )
            return _committed_execution("501")

        coordinator.queue_request(request, operation, results.append)
        self.assertIs(
            coordinator.cancel_queued_mutation("not-open", request.operation_id), False
        )
        self.assertIs(
            coordinator.cancel_queued_mutation(database_id, str(uuid.uuid4())), False
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(
            attempts, [("executing", PendingMutationState.EXECUTING, False)]
        )
        self.assertEqual(runtime.cancelled_mutation_ids, set())
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED],
        )
        self.assertEqual(len(reconciliation.batches), 1)
        # A finished (and unknown) operation can no longer be cancelled either.
        self.assertFalse(
            coordinator.cancel_queued_mutation(database_id, request.operation_id)
        )
        self.assertEqual(runtime.cancelled_mutation_ids, set())

    def test_cancellation_is_refused_while_the_committed_write_is_projecting(self):
        reconciliation = _DeferredProjectionReconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        results = []
        request = _placement_request(runtime.database_id, "cancel-while-projecting")
        coordinator.queue_request(
            request, lambda: _committed_execution("501"), results.append
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(
            coordinator._pending_mutations.get(request.operation_id).state,
            PendingMutationState.PROJECTING,
        )
        self.assertFalse(
            coordinator.cancel_queued_mutation(
                runtime.database_id, request.operation_id
            )
        )
        self.assertEqual(runtime.cancelled_mutation_ids, set())
        self.assertEqual(results, [])
        reconciliation.token.complete(True)
        self.assertEqual(
            [result.outcome_status for result in results],
            [MutationOutcomeStatus.COMMITTED],
        )

    def test_duplicate_operation_ids_and_runtime_gaps_reject_the_submission(self):
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(journal=journal)
        database_id = runtime.database_id
        results = []
        writes = []
        request = _placement_request(database_id, "duplicate")
        self.assertEqual(
            coordinator.queue_request(
                request,
                lambda: writes.append("first") or _committed_execution("1"),
                results.append,
            ),
            runtime.generation,
        )
        duplicate = []
        self.assertEqual(
            coordinator.queue_request(
                request,
                lambda: writes.append("second") or _committed_execution("2"),
                duplicate.append,
            ),
            -1,
        )
        self.assertEqual(
            [(r.outcome_status, r.message, r.runtime_generation) for r in duplicate],
            [
                (
                    MutationOutcomeStatus.REJECTED,
                    "A pending mutation already uses this operation ID",
                    runtime.generation,
                )
            ],
        )
        # The first submission keeps its queue slot, journal record and pending entry.
        self.assertEqual(runtime.mutation_requests.qsize(), 1)
        self.assertEqual(set(journal.records), {request.operation_id})
        self.assertEqual(
            coordinator._pending_mutations.get(request.operation_id).state,
            PendingMutationState.QUEUED,
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(writes, ["first"])
        # Without any runtime the submission is rejected with generation 0 and
        # leaves no pending or journal trace.
        coordinator._runtimes.clear()
        orphan = []
        orphan_request = _placement_request(database_id, "no-runtime")
        self.assertEqual(
            coordinator.queue_request(
                orphan_request, lambda: _committed_execution("3"), orphan.append
            ),
            -1,
        )
        self.assertEqual(
            [(r.outcome_status, r.message, r.runtime_generation) for r in orphan],
            [
                (
                    MutationOutcomeStatus.REJECTED,
                    "SQL collaboration is not ready for editing.",
                    0,
                )
            ],
        )
        self.assertEqual(coordinator._pending_mutations.for_database(database_id), ())
        self.assertEqual(journal.records, {})

    def test_submission_is_rejected_when_the_runtime_cannot_accept_work(self):
        # (label, runtime change, expected message)
        not_ready = "SQL collaboration is not ready for editing."
        stopped = "SQL collaboration stopped before the mutation was queued."
        cases = (
            (
                "not editable",
                lambda c, r: c._capabilities.set_collaboration_state(
                    r.database_id, SynchronizationState.CATCHING_UP
                ),
                not_ready,
            ),
            ("no session", lambda c, r: setattr(r, "session", None), stopped),
            ("not established", lambda c, r: setattr(r, "established", False), stopped),
            (
                "recovery requested",
                lambda c, r: setattr(r, "recovery_requested", True),
                stopped,
            ),
            ("stopping", lambda c, r: r.stop_event.set(), stopped),
            ("shutting down", lambda c, r: setattr(c, "_shutting_down", True), stopped),
            (
                "lifecycle drain pending",
                lambda c, r: c._mutation_drain_callbacks.setdefault(r.database_id, []),
                stopped,
            ),
        )
        for label, change, message in cases:
            with self.subTest(label):
                journal = _PendingOperationJournal()
                coordinator, runtime = self.ready_coordinator(journal=journal)
                change(coordinator, runtime)
                results = []
                request = _placement_request(runtime.database_id, f"rejected-{label}")
                self.assertEqual(
                    coordinator.queue_request(
                        request, lambda: _committed_execution("1"), results.append
                    ),
                    -1,
                )
                self.assertEqual(
                    [
                        (r.outcome_status, r.message, r.runtime_generation)
                        for r in results
                    ],
                    [(MutationOutcomeStatus.REJECTED, message, runtime.generation)],
                )
                self.assertTrue(runtime.mutation_requests.empty())
                self.assertEqual(
                    coordinator._pending_mutations.for_database(runtime.database_id), ()
                )
                self.assertEqual(journal.records, {})
        # Positive control: the unchanged runtime accepts the same request.
        coordinator, runtime = self.ready_coordinator()
        self.assertEqual(
            coordinator.queue_request(
                _placement_request(runtime.database_id, "accepted"),
                lambda: _committed_execution("1"),
                lambda _result: None,
            ),
            runtime.generation,
        )

    def test_replaced_runtime_never_receives_a_submission_for_its_predecessor(self):
        coordinator, runtime = self.ready_coordinator()
        replacement = _DatabaseRuntime(runtime.database_id, runtime.generation + 1)
        replacement.session = runtime.session
        replacement.established = True
        replacement.healthy = True
        results = []
        queued = coordinator._pending_mutations
        request = _placement_request(runtime.database_id, "replaced")
        queued.begin(request, runtime_generation=runtime.generation)
        coordinator._runtimes[runtime.database_id] = replacement
        self.assertEqual(
            coordinator._enqueue_mutation(
                runtime,
                _QueuedMutation(
                    database_id=runtime.database_id,
                    runtime_generation=runtime.generation,
                    operation_id=request.operation_id,
                    owning_surface=request.owning_surface,
                    resources=request.resources,
                    dependency_resources=(),
                    operation=lambda: _committed_execution("1"),
                    callback=results.append,
                    typed_request=request,
                ),
            ),
            -1,
        )
        self.assertEqual(
            [(r.message, r.runtime_generation) for r in results],
            [
                (
                    "SQL collaboration stopped before the mutation was queued.",
                    runtime.generation,
                )
            ],
        )
        self.assertTrue(runtime.mutation_requests.empty())
        self.assertTrue(replacement.mutation_requests.empty())
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )


class SqlCollaborationMutationDrainTests(_SecondPassBase):
    def two_database_coordinator(self, **kwargs):
        coordinator, runtime_a = self.ready_coordinator(**kwargs)
        runtime_b = self.add_ready_runtime(coordinator, "SECOND", 9)
        return coordinator, runtime_a, runtime_b

    def test_drain_all_without_runtimes_completes_immediately(self):
        coordinator, runtime = self.ready_coordinator()
        coordinator._runtimes.clear()
        results = []
        coordinator.drain_all_mutations_async(lambda *result: results.append(result))
        self.assertEqual(results, [(True, "")])

    def test_drain_all_waits_for_every_database_and_aggregates_their_failures(self):
        coordinator, runtime_a, runtime_b = self.two_database_coordinator()
        results = []
        for runtime, label, outcome in (
            (runtime_a, "a", MutationOutcomeStatus.REJECTED),
            (runtime_b, "b", MutationOutcomeStatus.CONFLICT),
        ):
            coordinator.queue_request(
                _placement_request(runtime.database_id, f"drain-{label}"),
                lambda outcome=outcome, label=label: MutationExecutionResult(
                    outcome_status=outcome, message=f"{label} refused"
                ),
                lambda _result: None,
            )
        drained = []
        coordinator.drain_all_mutations_async(lambda *result: drained.append(result))
        self.assertEqual(drained, [])
        coordinator._process_mutation_requests(runtime_a)
        self.assertEqual(drained, [])
        coordinator._process_mutation_requests(runtime_b)
        self.assertEqual(drained, [(False, "a refused; b refused")])
        self.assertEqual(coordinator._mutation_drain_callbacks, {})
        self.assertEqual(coordinator._mutation_drain_failures, {})
        # Without failures the aggregate is a clean success.
        clean = []
        for runtime, label in ((runtime_a, "a"), (runtime_b, "b")):
            coordinator.queue_request(
                _placement_request(runtime.database_id, f"clean-{label}"),
                lambda label=label: _committed_execution(label),
                lambda _result: None,
            )
        coordinator.drain_all_mutations_async(lambda *result: clean.append(result))
        coordinator._process_mutation_requests(runtime_b)
        self.assertEqual(clean, [])
        coordinator._process_mutation_requests(runtime_a)
        self.assertEqual(clean, [(True, "")])

    def test_drain_failure_without_any_message_names_the_database(self):
        coordinator, runtime = self.ready_coordinator()
        results = []

        def failing_drain(database_id, callback):
            callback(False, "")
            callback(False, "reported twice")  # a repeated completion is ignored

        with patch.object(coordinator, "drain_database_mutations_async", failing_drain):
            coordinator.drain_all_mutations_async(
                lambda *result: results.append(result)
            )
        self.assertEqual(
            results, [(False, f"{runtime.database_id}: mutation drain failed")]
        )

    def test_a_pending_drain_blocks_new_submissions_until_the_critical_work_finishes(
        self,
    ):
        coordinator, runtime = self.ready_coordinator(
            reconciliation=_DeferredProjectionReconciliation()
        )
        reconciliation = coordinator._reconciliation
        writes = []
        coordinator.queue_request(
            _placement_request(runtime.database_id, "blocking"),
            lambda: writes.append("blocking") or _committed_execution("501"),
            lambda _result: None,
        )
        drained = []
        coordinator.drain_database_mutations_async(
            runtime.database_id, lambda *result: drained.append(result)
        )
        self.assertEqual(drained, [])
        late = []
        self.assertEqual(
            coordinator.queue_request(
                _placement_request(runtime.database_id, "late"),
                lambda: writes.append("late") or _committed_execution("502"),
                late.append,
            ),
            -1,
        )
        self.assertEqual(
            [(r.outcome_status, r.message) for r in late],
            [
                (
                    MutationOutcomeStatus.REJECTED,
                    "SQL collaboration stopped before the mutation was queued.",
                )
            ],
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(drained, [])
        reconciliation.token.complete(True)
        self.assertEqual(drained, [(True, "")])
        self.assertEqual(writes, ["blocking"])
        # Once drained, the database accepts work again.
        self.assertEqual(
            coordinator.queue_request(
                _placement_request(runtime.database_id, "after-drain"),
                lambda: _committed_execution("503"),
                lambda _result: None,
            ),
            runtime.generation,
        )

    def test_drain_waits_for_executing_and_projecting_but_records_failed_outcomes(self):
        outcomes = (
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.CONFLICT,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        )
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                coordinator, runtime = self.ready_coordinator()
                drained = []
                coordinator.queue_request(
                    _placement_request(runtime.database_id, f"failed-{outcome.value}"),
                    lambda outcome=outcome: MutationExecutionResult(
                        outcome_status=outcome, message=""
                    ),
                    lambda _result: None,
                )
                coordinator.drain_database_mutations_async(
                    runtime.database_id, lambda *result: drained.append(result)
                )
                coordinator._process_mutation_requests(runtime)
                self.assertEqual(
                    drained,
                    [(False, "A lifecycle-critical SQL mutation did not complete.")],
                )
        # Committed work completes the drain successfully.
        coordinator, runtime = self.ready_coordinator()
        drained = []
        states = []
        request = _placement_request(runtime.database_id, "executing")

        def operation():
            states.append(
                coordinator._pending_mutations.get(request.operation_id).state
            )
            coordinator.drain_database_mutations_async(
                runtime.database_id, lambda *result: drained.append(result)
            )
            states.append(len(drained))
            return _committed_execution("501")

        coordinator.queue_request(request, operation, lambda _result: None)
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(states, [PendingMutationState.EXECUTING, 0])
        self.assertEqual(drained, [(True, "")])

    def test_drain_failures_are_deduplicated_across_operations(self):
        coordinator, runtime = self.ready_coordinator()
        drained = []
        for index in range(2):
            coordinator.queue_request(
                _placement_request(runtime.database_id, f"same-failure-{index}"),
                lambda: MutationExecutionResult(
                    outcome_status=MutationOutcomeStatus.REJECTED, message="busy"
                ),
                lambda _result: None,
            )
        coordinator.drain_database_mutations_async(
            runtime.database_id, lambda *result: drained.append(result)
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(drained, [])
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(drained, [(False, "busy")])


class SqlCollaborationRetainedMetadataDrainTests(_SecondPassBase):
    def test_a_database_without_a_new_runtime_keeps_its_drain_pending_on_retained_cancellations(
        self,
    ):
        """Pins AGENTS.md "Retain undelivered operations' recovery metadata".
        A cancellation the UI bridge could not deliver keeps its lifecycle-critical
        pending entry and journal record, so a drain of that database stays
        pending - also when the database never gets another runtime - until a
        later runtime resolves the durable outcome. drain_all_mutations_async only
        waits for databases that still have a runtime.
        """
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        database_id = runtime.database_id
        writes = []
        request = _placement_request(database_id, "retained-for-drain")
        coordinator.queue_request(
            request,
            lambda: writes.append("write") or _committed_execution("1"),
            lambda _result: None,
        )
        runtime.stop_event.set()
        with patch.object(
            coordinator._dispatcher,
            "dispatch",
            side_effect=RuntimeError("UI bridge unavailable"),
        ):
            coordinator._worker(runtime)
        # The stopped database has no runtime any more.
        coordinator._runtimes.pop(database_id)
        self.assertEqual(
            [
                p.request.operation_id
                for p in coordinator._pending_mutations.for_database(database_id)
            ],
            [request.operation_id],
        )
        drained = []
        coordinator.drain_database_mutations_async(
            database_id, lambda *result: drained.append(result)
        )
        coordinator._complete_mutation_drain_if_ready(database_id)
        self.assertEqual(drained, [])
        self.assertEqual(set(journal.records), {request.operation_id})
        everything = []
        coordinator.drain_all_mutations_async(lambda *result: everything.append(result))
        self.assertEqual(everything, [(True, "")])
        # A later runtime for the database resolves the durable outcome (without
        # replaying the write) and releases the drain.
        new_runtime = _DatabaseRuntime(database_id, runtime.generation + 1)
        coordinator._runtimes[database_id] = new_runtime
        session_generation = coordinator._install_session(
            new_runtime, DatabaseSession(database_id, str(uuid.uuid4()))
        )
        coordinator._recover_journaled_operations(new_runtime)
        coordinator._on_session_started(
            (
                database_id,
                new_runtime.generation,
                session_generation,
                HydratedDatabaseChangeBatch(_batch(database_id, "epoch", 0, 0)),
                None,
            )
        )
        self.assertEqual(drained, [(True, "")])
        self.assertEqual(writes, [])
        self.assertEqual(journal.records, {})


class SqlCollaborationSubmissionBookkeepingTests(_SecondPassBase):
    def test_rejected_submissions_leave_no_pending_entry_before_the_ui_delivers_them(
        self,
    ):
        # The rejection reaches the caller through the (asynchronous) UI bridge;
        # the registry and journal must already be clean when it is queued.
        cases = (
            (
                "journal write fails",
                lambda c, r: setattr(
                    c, "_operation_journal", _FailingPendingOperationJournal(1)
                ),
            ),
            (
                "runtime cannot accept work",
                lambda c, r: setattr(r, "recovery_requested", True),
            ),
            (
                "capability not editable",
                lambda c, r: c._capabilities.set_collaboration_state(
                    r.database_id, SynchronizationState.CATCHING_UP
                ),
            ),
        )
        for label, change in cases:
            with self.subTest(label):
                dispatcher = _DelayedMutationDispatcher()
                coordinator, runtime = self.ready_coordinator(dispatcher=dispatcher)
                change(coordinator, runtime)
                results = []
                request = _placement_request(runtime.database_id, f"async-{label}")
                self.assertEqual(
                    coordinator.queue_request(
                        request, lambda: _committed_execution("1"), results.append
                    ),
                    -1,
                )
                self.assertEqual(results, [])
                self.assertEqual(
                    coordinator._pending_mutations.for_database(runtime.database_id), ()
                )
                self.assertEqual(coordinator._operation_journal.records, {})
                dispatcher.deliver_pending()
                self.assertEqual(
                    [r.outcome_status for r in results],
                    [MutationOutcomeStatus.REJECTED],
                )

    def test_submission_without_a_runtime_registers_its_pending_entry_with_generation_zero(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        coordinator._runtimes.clear()
        request = _placement_request(runtime.database_id, "no-runtime-generation")
        with patch.object(
            coordinator._pending_mutations,
            "begin",
            wraps=coordinator._pending_mutations.begin,
        ) as begin:
            coordinator.queue_request(
                request, lambda: _committed_execution("1"), lambda _r: None
            )
        begin.assert_called_once_with(request, runtime_generation=0)

    def test_boolean_commands_return_real_booleans(self):
        coordinator, runtime = self.ready_coordinator()
        database_id = runtime.database_id
        request = _placement_request(database_id, "boolean-results")
        coordinator.queue_request(
            request, lambda: _committed_execution("1"), lambda _r: None
        )
        self.assertIs(
            coordinator.cancel_queued_mutation("not-open", request.operation_id), False
        )
        self.assertIs(coordinator.cancel_queued_mutation(database_id, "unknown"), False)
        self.assertIs(
            coordinator.cancel_queued_mutation(database_id, request.operation_id), True
        )
        self.assertIs(coordinator.start_database("not-registered"), False)
        self.assertIs(coordinator.start_database(database_id), False)  # running
        self.assertIs(coordinator.resume_controlled_recovery("not-open"), False)
        self.assertIs(coordinator.resume_controlled_recovery(database_id), False)
        runtime.recovery_requested = True
        self.assertIs(coordinator.resume_controlled_recovery(database_id), True)
        self.assertIs(coordinator.resume_controlled_recovery(database_id), False)
        self.assertIs(coordinator.uses_sql_collaboration(database_id), True)
        self.assertIs(coordinator.uses_sql_collaboration("not-registered"), False)
        self.assertIs(
            coordinator.is_runtime_current(database_id, runtime.generation), True
        )
        self.assertIs(
            coordinator.is_runtime_current(database_id, runtime.generation + 1), False
        )

    def test_a_local_detach_never_finalizes_a_runtime_that_started_in_the_meantime(
        self,
    ):
        for generation in (0, 1, 2, 4):
            with self.subTest(runtime_generation=generation):
                coordinator, runtime = self.ready_coordinator()
                runtime.generation = generation
                with (
                    patch.object(coordinator, "_detach_runtime", return_value=None),
                    patch.object(
                        coordinator._concurrency_tokens,
                        "clear_database",
                        wraps=coordinator._concurrency_tokens.clear_database,
                    ) as clear,
                ):
                    coordinator.stop_database_async(runtime.database_id, "closed")
                clear.assert_not_called()
                self.assertEqual(
                    self.published(coordinator, AppEvents.COLLABORATION_STATE_CHANGED),
                    [],
                )
                self.assertIs(coordinator._runtime(runtime.database_id), runtime)

    def test_recovering_and_uncertain_work_does_not_block_a_lifecycle_drain(self):
        coordinator, runtime = self.ready_coordinator()
        for state in (PendingMutationState.RECOVERING, PendingMutationState.UNCERTAIN):
            with self.subTest(state=state):
                request = _placement_request(
                    runtime.database_id, f"awaiting-{state.value}"
                )
                coordinator._pending_mutations.begin(
                    request, runtime_generation=runtime.generation
                )
                if state == PendingMutationState.UNCERTAIN:
                    coordinator._pending_mutations.transition(
                        request.operation_id, PendingMutationState.EXECUTING
                    )
                coordinator._pending_mutations.transition(request.operation_id, state)
                drained = []
                coordinator.drain_database_mutations_async(
                    runtime.database_id, lambda *result: drained.append(result)
                )
                self.assertEqual(drained, [(True, "")])
                coordinator._pending_mutations.finish(request.operation_id)


class SqlCollaborationSubmissionWakeTests(_SecondPassBase):
    def test_an_accepted_submission_wakes_the_worker(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.command_event.clear()
        coordinator.queue_request(
            _placement_request(runtime.database_id, "wake"),
            lambda: _committed_execution("1"),
            lambda _result: None,
        )
        self.assertTrue(runtime.command_event.is_set())

    def test_a_duplicate_without_a_runtime_is_rejected_with_generation_zero(self):
        coordinator, runtime = self.ready_coordinator()
        request = _placement_request(runtime.database_id, "duplicate-no-runtime")
        coordinator._pending_mutations.begin(
            request, runtime_generation=runtime.generation
        )
        coordinator._runtimes.clear()
        results = []
        self.assertEqual(
            coordinator.queue_request(
                request, lambda: _committed_execution("1"), results.append
            ),
            -1,
        )
        self.assertEqual(
            [(r.outcome_status, r.runtime_generation) for r in results],
            [(MutationOutcomeStatus.REJECTED, 0)],
        )
        # The original owner of the operation id is untouched.
        self.assertIsNotNone(coordinator._pending_mutations.get(request.operation_id))

    def test_a_failing_rejection_callback_is_contained_and_logged(self):
        coordinator, runtime = self.ready_coordinator()
        request = _placement_request(runtime.database_id, "duplicate-failing-callback")
        coordinator._pending_mutations.begin(
            request, runtime_generation=runtime.generation
        )

        def broken(result):
            raise RuntimeError("closed dialog")

        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logged:
            self.assertEqual(
                coordinator.queue_request(
                    request, lambda: _committed_execution("1"), broken
                ),
                -1,
            )
        self.assertEqual(
            [r.getMessage() for r in logged.records],
            ["SQL rejected-submission completion callback failed"],
        )

    def test_a_journal_failure_still_lets_a_concurrent_lifecycle_drain_finish(self):
        # Another thread may request a lifecycle drain while the submission is
        # being recorded; the rejection must re-evaluate that drain.
        drained = []
        coordinator, runtime = self.ready_coordinator()
        database_id = runtime.database_id

        class _DrainRequestingJournal(_PendingOperationJournal):
            def save(self, record):
                coordinator.drain_database_mutations_async(
                    database_id, lambda *result: drained.append(result)
                )
                raise OSError("journal unavailable")

        coordinator._operation_journal = _DrainRequestingJournal()
        results = []
        coordinator.queue_request(
            _placement_request(database_id, "journal-with-drain"),
            lambda: _committed_execution("1"),
            results.append,
        )
        self.assertEqual(
            [r.outcome_status for r in results], [MutationOutcomeStatus.REJECTED]
        )
        self.assertEqual(drained, [(True, "")])


class SqlCollaborationDraftContextTests(_SecondPassBase):
    def test_a_page_draft_with_a_non_numeric_id_has_no_page_uid(self):
        coordinator, runtime = self.ready_coordinator()
        results = []
        coordinator.request_local_edit(
            runtime.database_id,
            (ResourceRef("page", "front-sheet", 8),),
            results.append,
        )
        ((request, _callback),) = tuple(runtime.edit_requests.queue)
        draft = coordinator._local_drafts.get(request.draft_id)
        self.assertEqual(
            (draft.draft_type, draft.page_uid, draft.bid_uid), ("pages_editor", None, 8)
        )


class SqlCollaborationWorkerSpinTests(_SecondPassBase):
    def worker_clock_reads(self, runtime, window):
        reads = []
        real = time.monotonic

        def counting():
            if threading.current_thread() is runtime.thread:
                reads.append(1)
            return real()

        with patch.object(time, "monotonic", counting):
            time.sleep(window)
        return len(reads)

    def test_a_worker_waiting_for_the_recovery_resume_does_not_spin(self):
        store = _ScriptedStore()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(3))
        runtime = coordinator._runtime(descriptor.database_id)
        coordinator._on_reconciliation_required(
            (descriptor.database_id, runtime.generation, "waiting")
        )
        deadline = time.monotonic() + 3
        while runtime.session is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        # An unrelated command wake-up must not turn the wait into a busy loop.
        runtime.command_event.set()
        reads = self.worker_clock_reads(runtime, 0.4)
        self.assertLess(reads, 40)
        self.assertEqual(store.calls["start_session"], 1)
        coordinator.resume_controlled_recovery(descriptor.database_id)
        _stop_database(coordinator, descriptor.database_id)

    def test_a_command_wake_up_does_not_turn_the_idle_worker_into_a_busy_loop(self):
        store = _ScriptedStore()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(3))
        runtime = coordinator._runtime(descriptor.database_id)
        runtime.command_event.set()
        polls = store.calls["poll_changes"]
        time.sleep(0.4)
        self.assertLess(store.calls["poll_changes"] - polls, 30)
        _stop_database(coordinator, descriptor.database_id)


class SqlCollaborationCatchUpHealthTests(_SecondPassBase):
    def test_a_session_that_catches_up_through_remote_batches_becomes_healthy_and_editable(
        self,
    ):
        """Production defect proof (fixed).
        The UI-thread batch completion marks the runtime healthy as soon as the
        checkpoint reaches the feed, which made the worker believe the restored
        state had already been announced: the database stayed CATCHING_UP (not
        editable, no writer session registered) forever. Failed before the fix
        with the state still catching_up after 2 s although runtime.healthy was
        True and acknowledged_version == 3.
        """

        class _PartialBatchStore(_ScriptedStore):
            """The feed releases one change per poll: 1, 2, 3."""

            def poll_changes(
                self, database_id, after_version, limit, excluding_session_id
            ):
                self._step("poll_changes")
                pending = [v for v in (1, 2, 3) if v > after_version]
                changes = tuple(
                    _change(
                        database_id, ResourceRef("condition", str(v), 8), sequence=v
                    )
                    for v in pending[:1]
                )
                delivered = changes[-1].commit_version if changes else 3
                observed = _batch(
                    database_id, "epoch", 0, 3, changes, delivered_through=delivered
                )
                return DatabaseChangePollResult(
                    observed_batch=observed,
                    remote_batch=HydratedDatabaseChangeBatch(observed),
                )

        class _CountingProbe(_PermissionProbe):
            calls = 0

            def can_edit(self, _database_id):
                type(self).calls += 1
                return True

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _CountingProbe())
        capabilities.mark_connected(descriptor.database_id)
        _CountingProbe.calls = 0
        store = _PartialBatchStore()
        dispatcher = _UiThreadDispatcher()
        coordinator, _descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store,
            dispatcher=dispatcher,
            capabilities=capabilities,
            descriptor=descriptor,
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        acknowledged_at_announcement = []
        events.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED,
            lambda database_id="", state="", **_payload: (
                acknowledged_at_announcement.append(
                    coordinator._runtime(database_id).acknowledged_version
                )
                if state == "healthy"
                else None
            ),
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(dispatcher.pump_until(healthy.is_set, 5))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertEqual(acknowledged_at_announcement, [3])
        self.assertTrue(capabilities.is_editable(descriptor.database_id))
        self.assertEqual(
            coordinator._sessions.get(descriptor.database_id),
            runtime.session.session_id,
        )
        # Announced exactly once per session: one permission probe, one state.
        dispatcher.pump_until(lambda: False, 0.3)
        self.assertEqual(_CountingProbe.calls, 1)
        self.assertEqual(
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
            ].count("healthy"),
            1,
        )
        done = threading.Event()
        coordinator.stop_database_async(
            descriptor.database_id, callback=lambda *_result: done.set()
        )
        self.assertTrue(dispatcher.pump_until(done.is_set, 5))


class SqlCollaborationPartialBatchHealthTests(_SecondPassBase):
    def test_health_is_not_announced_between_partial_batches(self):
        class _PartialBatchStore(_ScriptedStore):
            """The feed releases one change per poll: 1, 2, 3."""

            def poll_changes(
                self, database_id, after_version, limit, excluding_session_id
            ):
                self._step("poll_changes")
                pending = [v for v in (1, 2, 3) if v > after_version]
                changes = tuple(
                    _change(
                        database_id, ResourceRef("condition", str(v), 8), sequence=v
                    )
                    for v in pending[:1]
                )
                delivered = changes[-1].commit_version if changes else 3
                observed = _batch(
                    database_id, "epoch", 0, 3, changes, delivered_through=delivered
                )
                return DatabaseChangePollResult(
                    observed_batch=observed,
                    remote_batch=HydratedDatabaseChangeBatch(observed),
                )

        class _HoldBatches(_Dispatcher):
            def __init__(self):
                self.held = []

            def dispatch(self, callback, payload=()):
                if callback.__name__ == "_on_remote_batch":
                    self.held.append((callback, payload))
                else:
                    callback(payload)

            def deliver(self):
                for callback, payload in tuple(self.held):
                    callback(payload)
                self.held.clear()

        store = _PartialBatchStore()
        dispatcher = _HoldBatches()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store, dispatcher=dispatcher
        )
        announced = []
        done = threading.Event()
        events.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED,
            lambda database_id="", state="", **_payload: (
                (
                    announced.append(
                        coordinator._runtime(database_id).acknowledged_version
                    ),
                    done.set(),
                )
                if state == "healthy"
                else None
            ),
        )
        original_poll = coordinator._poll

        def poll_then_finish_projection(runtime):
            original_poll(runtime)
            # The UI finishes projecting the batch right after the worker polled.
            dispatcher.deliver()

        coordinator._poll = poll_then_finish_projection
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(done.wait(5))
        self.assertEqual(announced, [3])
        _stop_database(coordinator, descriptor.database_id)


class SqlCollaborationMutationFailureClassificationTests(_SecondPassBase):
    def test_mutation_failures_end_the_worker_only_for_session_level_errors(self):
        for label, error, fatal in (
            ("plain refusal", DatabaseCatalogError("refused"), False),
            ("retryable", DatabaseCatalogError("lost", retryable=True), True),
            (
                "session expired",
                DatabaseCatalogError("expired", session_expired=True),
                True,
            ),
            (
                "credentials",
                DatabaseCatalogError("sign in", credential_required=True),
                True,
            ),
            (
                "read only",
                DatabaseCatalogError("denied", read_only_required=True),
                True,
            ),
            ("os error", OSError("socket closed"), True),
        ):
            with self.subTest(label):
                coordinator, runtime = self.ready_coordinator()
                results = []

                def failing(error=error):
                    raise error

                request = _placement_request(runtime.database_id, f"failure-{label}")
                coordinator.queue_request(request, failing, results.append)
                if fatal:
                    with self.assertRaises(type(error)) as raised:
                        coordinator._process_mutation_requests(runtime)
                    self.assertIs(raised.exception, error)
                else:
                    coordinator._process_mutation_requests(runtime)
                self.assertEqual(
                    [
                        (r.outcome_status, r.message, r.commit_attempted)
                        for r in results
                    ],
                    [(MutationOutcomeStatus.FAILED_BEFORE_COMMIT, str(error), False)],
                )
                self.assertEqual(
                    coordinator._pending_mutations.for_database(runtime.database_id), ()
                )
                self.assertEqual(coordinator._local_drafts._drafts, {})

    def test_consuming_a_lease_tolerates_partial_ownership(self):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        first = ResourceRef("takeoff", "42", 8)
        second = ResourceRef("takeoff", "43", 8)
        lock = ResourceLock(runtime.database_id, first, "lock-first")
        # The runtime no longer owns the lock named by the handle.
        handle = EditLeaseHandle(
            database_id=runtime.database_id,
            draft_id="draft",
            runtime_generation=runtime.generation,
            operation_id="op",
            owning_surface="main-plan",
            resources=(first,),
            locks=(lock,),
        )
        runtime.edit_depth = 1
        failure = coordinator._consume_mutation_edit_lease(
            runtime, runtime.session, handle, ()
        )
        self.assertIsNone(failure)
        # The handle names a resource without a lock entry while the runtime owns one.
        runtime.owned_locks[second.lease_identity] = ResourceLock(
            runtime.database_id, second, "lock-second"
        )
        no_lock_handle = replace(handle, resources=(second,), locks=())
        failure = coordinator._consume_mutation_edit_lease(
            runtime, runtime.session, no_lock_handle, ()
        )
        self.assertIsNone(failure)
        self.assertIn(second.lease_identity, runtime.owned_locks)


class SqlCollaborationFeedHealthTests(_SecondPassBase):
    def test_a_conflicted_state_alone_blocks_the_checkpoint(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.pending_delivery = True
        runtime.acknowledged_version = 7
        runtime.observed_high_water_version = 12
        coordinator._capabilities.set_collaboration_state(
            runtime.database_id, SynchronizationState.CONFLICTED
        )
        coordinator._finish_remote_batch(
            runtime.database_id,
            runtime.generation,
            runtime.session_generation,
            12,
            time.perf_counter(),
            None,
            True,
        )
        self.assertEqual(runtime.acknowledged_version, 7)
        self.assertTrue(runtime.pending_delivery)
        self.assertFalse(runtime.healthy)
        self.assertFalse(runtime.recovery_requested)

    def test_poll_duration_is_the_measured_time_of_each_poll(self):
        coordinator, runtime = self.ready_coordinator()
        with patch.object(
            time, "perf_counter", side_effect=[100.0, 100.25, 200.0, 200.5]
        ):
            coordinator._poll(runtime)
            coordinator._poll(runtime)
        self.assertEqual(runtime.poll_count, 2)
        self.assertAlmostEqual(runtime.poll_duration_seconds, 0.75)

    def test_a_batch_with_changes_is_delivered_even_if_its_checkpoint_does_not_move(
        self,
    ):
        store = _CollaborationStore()
        change = _change("db", ResourceRef("condition", "42", 8), sequence=10)
        store.batch = _batch("db", "epoch", 1, 25, (change,), delivered_through=10)
        dispatcher = _RecordingDispatcher()
        coordinator, runtime = self.ready_coordinator(
            store=store, dispatcher=dispatcher
        )
        runtime.acknowledged_version = 10
        runtime.feed_epoch = "epoch"
        coordinator._poll_once(runtime)
        self.assertEqual([name for name, _ in dispatcher.calls], ["_on_remote_batch"])


class SqlCollaborationUncertainDeliveryTests(_SecondPassBase):
    def test_an_uncertain_commit_whose_ui_delivery_fails_still_reaches_the_recovered_callback(
        self,
    ):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        writes = []
        results = []
        request = _placement_request(runtime.database_id, "uncertain-delivery-fails")
        coordinator.queue_request(
            request,
            lambda: writes.append("write") or _unknown_commit(),
            results.append,
        )
        original_dispatch = coordinator._dispatcher.dispatch

        def failing_dispatch(callback, payload=()):
            if callback.__name__ == "_complete_mutation_request":
                raise RuntimeError("UI bridge unavailable")
            return original_dispatch(callback, payload)

        with patch.object(
            coordinator._dispatcher, "dispatch", side_effect=failing_dispatch
        ):
            with self.assertRaises(RuntimeError):
                coordinator._process_mutation_requests(runtime)
        # The caller was never told, but the callback is retained for recovery.
        self.assertEqual(results, [])
        self.assertEqual(set(coordinator._uncertain_callbacks), {request.operation_id})
        store.durable_results[request.operation_id] = _durable_result(request, "501")
        coordinator._reset_session(runtime)
        session_generation = coordinator._install_session(
            runtime, DatabaseSession(runtime.database_id, str(uuid.uuid4()))
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                runtime.database_id,
                runtime.generation,
                session_generation,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
                None,
            )
        )
        self.assertEqual(
            [(r.outcome_status, r.created_resource_ids) for r in results],
            [(MutationOutcomeStatus.COMMITTED, ("501",))],
        )
        self.assertEqual(writes, ["write"])
        self.assertEqual(coordinator._uncertain_callbacks, {})
        self.assertEqual(journal.records, {})


class SqlCollaborationEditRequestTests(_SecondPassBase):
    def test_edit_request_without_resources_is_denied_before_any_lookup(self):
        coordinator, runtime = self.ready_coordinator()
        results = []
        coordinator.request_local_edit(runtime.database_id, (), results.append)
        self.assertEqual(
            results,
            [EditLeaseResult(False, "An edit lease requires at least one resource.")],
        )
        self.assertTrue(runtime.edit_requests.empty())
        self.assertEqual(coordinator._local_drafts._drafts, {})

    def test_access_databases_receive_an_immediate_local_grant_without_a_session(self):
        store = _CollaborationStore()  # any store call is an error
        coordinator, runtime = self.ready_coordinator(store=store)
        access = DatabaseDescriptor.for_access("C:/second-pass.mdb")
        coordinator._registry.register(access)
        first = ResourceRef("condition", "43", 8)
        second = ResourceRef("condition", "42", 8)
        page = ResourceRef("page", "20", 8)
        results = []
        coordinator.request_local_edit(
            access.database_id,
            (first, second, first),
            results.append,
            dependency_resources=(page, page),
            owning_surface="detached-plan",
        )
        coordinator.request_local_edit(
            access.database_id,
            (first,),
            results.append,
            operation_id="named-operation",
        )
        self.assertEqual([result.granted for result in results], [True, True])
        handle, named = results[0].handle, results[1].handle
        self.assertEqual(handle.database_id, access.database_id)
        self.assertEqual(handle.runtime_generation, 0)
        self.assertEqual(handle.operation_id, "access-local-edit")
        self.assertEqual(handle.owning_surface, "detached-plan")
        self.assertEqual(handle.resources, (second, first))
        self.assertEqual(handle.dependency_resources, (page,))
        self.assertEqual(handle.locks, ())
        self.assertEqual(str(uuid.UUID(handle.draft_id)), handle.draft_id)
        self.assertNotEqual(handle.draft_id, named.draft_id)
        self.assertEqual(named.operation_id, "named-operation")
        self.assertEqual(named.owning_surface, "desktop")
        # No SQL runtime, draft or session is involved.
        self.assertEqual(coordinator._local_drafts._drafts, {})
        self.assertTrue(runtime.edit_requests.empty())

    def test_edit_request_without_a_runtime_is_denied(self):
        coordinator, runtime = self.ready_coordinator()
        coordinator._runtimes.clear()
        unregistered = []
        known = []
        coordinator.request_local_edit(
            "not-registered", (ResourceRef("condition", "42", 8),), unregistered.append
        )
        coordinator.request_local_edit(
            runtime.database_id, (ResourceRef("condition", "42", 8),), known.append
        )
        denial = EditLeaseResult(
            False, "SQL collaboration is not available for this database."
        )
        self.assertEqual((unregistered, known), ([denial], [denial]))
        self.assertEqual(coordinator._local_drafts._drafts, {})

    def test_overlapping_local_draft_denies_the_edit_with_its_own_message(self):
        coordinator, runtime = self.ready_coordinator()
        resource = ResourceRef("condition", "42", 8)
        owner = coordinator._local_drafts.begin(
            draft_type="conditions_editor",
            database_id=runtime.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="condition-sidebar",
            affected_resources=(resource,),
        )
        results = []
        coordinator.request_local_edit(runtime.database_id, (resource,), results.append)
        self.assertEqual(
            results,
            [
                EditLeaseResult(
                    False, "A local edit already owns one of the requested resources."
                )
            ],
        )
        self.assertTrue(runtime.edit_requests.empty())
        # Only the pre-existing draft remains.
        self.assertEqual(set(coordinator._local_drafts._drafts), {owner.draft_id})

    def test_queued_edit_draft_records_family_bid_page_and_base_tokens(self):
        coordinator, runtime = self.ready_coordinator()
        database_id = runtime.database_id
        page = ResourceRef("page", "20", 8)
        condition = ResourceRef("condition", "5")
        dependency = ResourceRef("takeoffs_collection", "8", 8)
        token = ConcurrencyToken((7).to_bytes(8, "big"))
        coordinator._concurrency_tokens._reader.resources = {page: token}
        coordinator._concurrency_tokens.load_bid(database_id, "8")
        coordinator.request_local_edit(
            database_id,
            (condition, page),
            lambda _result: None,
            dependency_resources=(dependency,),
            operation_id="edit-page",
            owning_surface="page-settings",
        )
        ((request, _callback),) = tuple(runtime.edit_requests.queue)
        draft = coordinator._local_drafts.get(request.draft_id)
        # Resources are normalized (sorted, unique); the draft family comes from
        # the FIRST sorted resource, the Bid from the first resource that has one
        # and the Page UID only when that first resource is a Page.
        self.assertEqual(request.resources, (condition, page))
        self.assertEqual(draft.draft_type, "conditions_editor")
        self.assertEqual(draft.database_id, database_id)
        self.assertEqual(draft.bid_uid, 8)
        self.assertIsNone(draft.page_uid)
        self.assertEqual(draft.owning_surface, "page-settings")
        self.assertEqual(draft.affected_resources, (condition, page))
        self.assertEqual(draft.dependency_resources, (dependency,))
        self.assertEqual(draft.base_tokens, ((page, token),))
        self.assertEqual(draft.operation_id, "edit-page")
        self.assertEqual(request.operation_id, "edit-page")
        self.assertEqual(request.owning_surface, "page-settings")
        self.assertEqual(request.dependency_resources, (dependency,))
        # A Page edit records the Page UID.
        coordinator._local_drafts.finish(request.draft_id)
        runtime.edit_requests.get_nowait()
        coordinator.request_local_edit(
            database_id, (page,), lambda _result: None, owning_surface="page-settings"
        )
        ((page_request, _callback),) = tuple(runtime.edit_requests.queue)
        page_draft = coordinator._local_drafts.get(page_request.draft_id)
        self.assertEqual(page_draft.draft_type, "pages_editor")
        self.assertEqual(page_draft.page_uid, 20)
        self.assertEqual(page_draft.bid_uid, 8)

    def test_edit_requests_are_not_queued_when_the_runtime_cannot_take_them(self):
        cases = (
            ("no session", lambda c, r: setattr(r, "session", None)),
            ("recovery requested", lambda c, r: setattr(r, "recovery_requested", True)),
            ("stopping", lambda c, r: r.stop_event.set()),
            ("shutting down", lambda c, r: setattr(c, "_shutting_down", True)),
        )
        for label, change in cases:
            with self.subTest(label):
                coordinator, runtime = self.ready_coordinator()
                change(coordinator, runtime)
                results = []
                coordinator.request_local_edit(
                    runtime.database_id,
                    (ResourceRef("condition", "42", 8),),
                    results.append,
                )
                self.assertEqual(
                    results,
                    [
                        EditLeaseResult(
                            False,
                            "SQL collaboration stopped before the edit could be queued.",
                        )
                    ],
                )
                self.assertTrue(runtime.edit_requests.empty())
                self.assertEqual(coordinator._local_drafts._drafts, {})
        # A runtime replaced after the lookup is equally refused.
        coordinator, runtime = self.ready_coordinator()
        replaced = []
        original_begin = coordinator._local_drafts.begin

        def begin_then_replace(**kwargs):
            draft = original_begin(**kwargs)
            coordinator._runtimes[runtime.database_id] = _DatabaseRuntime(
                runtime.database_id, runtime.generation + 1
            )
            return draft

        with patch.object(coordinator._local_drafts, "begin", begin_then_replace):
            coordinator.request_local_edit(
                runtime.database_id,
                (ResourceRef("condition", "42", 8),),
                replaced.append,
            )
        self.assertEqual(
            replaced,
            [
                EditLeaseResult(
                    False, "SQL collaboration stopped before the edit could be queued."
                )
            ],
        )
        self.assertTrue(runtime.edit_requests.empty())
        self.assertEqual(coordinator._local_drafts._drafts, {})

    def test_worker_denies_edit_requests_it_cannot_serve_with_the_matching_reason(self):
        resource = ResourceRef("condition", "42", 8)
        owned_lock = ResourceLock("db", resource, "held")
        cases = (
            (
                "already owned",
                lambda c, r: r.owned_locks.update(
                    {resource.lease_identity: owned_lock}
                ),
                "One of the requested resources is already being edited.",
            ),
            (
                "not editable",
                lambda c, r: c._capabilities.set_collaboration_state(
                    r.database_id, SynchronizationState.CATCHING_UP
                ),
                "SQL collaboration is not ready for editing.",
            ),
            (
                "no session",
                lambda c, r: setattr(r, "session", None),
                "The SQL collaboration session is not available.",
            ),
        )
        for label, change, message in cases:
            with self.subTest(label):
                store = _CollaborationStore()  # acquiring a lock would raise
                coordinator, runtime = self.ready_coordinator(store=store)
                results = []
                coordinator.request_local_edit(
                    runtime.database_id, (resource,), results.append
                )
                # The state changes after the request was accepted and queued.
                change(coordinator, runtime)
                coordinator._process_edit_requests(runtime)
                self.assertEqual(results, [EditLeaseResult(False, message)])
                self.assertEqual(coordinator._local_drafts._drafts, {})
                self.assertTrue(runtime.edit_requests.empty())


class SqlCollaborationEventHandlerTests(_SecondPassBase):
    def test_file_opened_event_starts_the_runtime_for_that_database(self):
        store = _CollaborationStore()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        events.publish(AppEvents.FILE_OPENED, file_path=descriptor.database_id)
        self.assertTrue(healthy.wait(2))
        self.assertIsNotNone(coordinator._runtime(descriptor.database_id))
        self.assertEqual(store.start_count, 1)

    def test_file_unloaded_event_stops_the_runtime_resolved_from_the_descriptor(self):
        store = _CollaborationStore()
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(store=store)
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        stopped = _state_signal(
            events, descriptor.database_id, SynchronizationState.STOPPED
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(2))
        runtime = coordinator._runtime(descriptor.database_id)
        events.publish(AppEvents.FILE_UNLOADED, file_path=descriptor.database_id)
        self.assertIsNone(coordinator._runtime(descriptor.database_id))
        self.assertTrue(stopped.wait(2))
        self.assertTrue(store.closed.is_set())
        self.assertEqual(runtime.close_reason, "closed")
        self.assertEqual(
            capabilities.collaboration_status(descriptor.database_id).state,
            SynchronizationState.STOPPED,
        )

    def test_file_unloaded_event_for_an_unregistered_path_uses_the_path_as_database_id(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        orphan = _DatabaseRuntime("C:/unregistered.mdb", 3)
        coordinator._runtimes[orphan.database_id] = orphan
        stopped = threading.Event()
        coordinator._event_bus.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED,
            lambda database_id="", state="", **_payload: (
                stopped.set()
                if database_id == orphan.database_id and state == "stopped"
                else None
            ),
        )
        coordinator._event_bus.publish(
            AppEvents.FILE_UNLOADED, file_path=orphan.database_id
        )
        self.assertTrue(stopped.wait(2))
        self.assertNotIn(orphan.database_id, coordinator._runtimes)
        self.assertTrue(orphan.stop_event.is_set())
        # The other database's runtime is untouched.
        self.assertIs(coordinator._runtime(runtime.database_id), runtime)

    def test_database_refreshed_clears_conflicts_and_resumes_a_pending_recovery(self):
        coordinator, runtime = self.ready_coordinator()
        resource = ResourceRef("condition", "42", 8)
        coordinator.enter_resource_conflict(runtime.database_id, resource)
        self.assertEqual(
            coordinator.status(runtime.database_id).conflicted_resources,
            frozenset({resource}),
        )
        coordinator._event_bus.published.clear()
        runtime.command_event.clear()
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=runtime.database_id
        )
        status = coordinator.status(runtime.database_id)
        self.assertEqual(status.conflicted_resources, frozenset())
        self.assertEqual(status.state, SynchronizationState.CONNECTING)
        self.assertEqual(status.message, "Recovering the authoritative SQL state.")
        self.assertTrue(runtime.recovery_ready)
        self.assertTrue(runtime.recovery_attempted)
        self.assertTrue(runtime.command_event.is_set())
        # Resuming the recovery is the only notification: no extra capability
        # event for the cleared conflicts.
        self.assertEqual(
            [event for event, _payload in coordinator._event_bus.published],
            [
                AppEvents.DATABASE_REFRESHED,
                AppEvents.COLLABORATION_STATE_CHANGED,
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
            ],
        )

    def test_database_refreshed_without_recovery_republishes_only_for_cleared_conflicts(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        resource = ResourceRef("condition", "42", 8)
        coordinator._capabilities.add_collaboration_conflict(
            runtime.database_id, resource
        )
        coordinator._event_bus.published.clear()
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=runtime.database_id
        )
        self.assertEqual(
            coordinator.status(runtime.database_id).conflicted_resources, frozenset()
        )
        self.assertEqual(
            coordinator._event_bus.published,
            [
                (AppEvents.DATABASE_REFRESHED, {"file_path": runtime.database_id}),
                (
                    AppEvents.DATABASE_CAPABILITIES_CHANGED,
                    {"file_path": runtime.database_id},
                ),
            ],
        )
        self.assertFalse(runtime.recovery_attempted)
        # Without conflicts (and without a recovery request) nothing is published.
        coordinator._event_bus.published.clear()
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=runtime.database_id
        )
        self.assertEqual(
            coordinator._event_bus.published,
            [(AppEvents.DATABASE_REFRESHED, {"file_path": runtime.database_id})],
        )
        # A database without a runtime ignores the refresh entirely.
        coordinator._capabilities.add_collaboration_conflict(
            "not-open", ResourceRef("condition", "1", 8)
        )
        before = list(coordinator._event_bus.published)
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path="not-open"
        )
        self.assertEqual(
            coordinator.status("not-open").conflicted_resources,
            frozenset({ResourceRef("condition", "1", 8)}),
        )
        self.assertEqual(
            coordinator._event_bus.published[len(before) :],
            [(AppEvents.DATABASE_REFRESHED, {"file_path": "not-open"})],
        )

    def test_resume_controlled_recovery_requires_a_requested_unattempted_recovery(self):
        coordinator, runtime = self.ready_coordinator()
        database_id = runtime.database_id
        self.assertIs(coordinator.resume_controlled_recovery("not-open"), False)
        # Nothing requested yet.
        self.assertIs(coordinator.resume_controlled_recovery(database_id), False)
        self.assertFalse(runtime.recovery_ready)
        self.assertFalse(runtime.recovery_attempted)
        runtime.recovery_requested = True
        runtime.command_event.clear()
        self.assertIs(coordinator.resume_controlled_recovery(database_id), True)
        self.assertTrue(runtime.recovery_ready)
        self.assertTrue(runtime.recovery_attempted)
        self.assertTrue(runtime.command_event.is_set())
        # A second resume while the first one is still in flight does nothing.
        runtime.command_event.clear()
        self.assertIs(coordinator.resume_controlled_recovery(database_id), False)
        self.assertFalse(runtime.command_event.is_set())
        runtime.recovery_requested = False
        runtime.recovery_attempted = False
        self.assertIs(coordinator.resume_controlled_recovery(database_id), False)


class SqlCollaborationPublicQueryTests(_SecondPassBase):
    def test_presence_updates_convert_identifiers_and_clear_missing_context(self):
        coordinator, runtime = self.ready_coordinator()
        database_id = runtime.database_id
        coordinator.update_presence(database_id, "8", "20", PresenceMode.EDITING)
        self.assertEqual(
            (runtime.bid_uid, runtime.page_uid, runtime.mode),
            (8, 20, PresenceMode.EDITING),
        )
        coordinator.update_presence(database_id, None, "", PresenceMode.VIEWING)
        self.assertEqual(
            (runtime.bid_uid, runtime.page_uid, runtime.mode),
            (None, None, PresenceMode.VIEWING),
        )
        coordinator.update_presence(database_id, "9", None)
        self.assertEqual(
            (runtime.bid_uid, runtime.page_uid, runtime.mode),
            (9, None, PresenceMode.VIEWING),
        )
        # Updating a database without a runtime is a no-op.
        coordinator.update_presence("not-open", "1", "2", PresenceMode.EDITING)
        self.assertEqual(runtime.bid_uid, 9)

    def test_metrics_report_the_runtime_counters_or_zeroes(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.poll_count = 3
        runtime.poll_duration_seconds = 0.5
        runtime.transaction_count = 4
        runtime.change_row_count = 5
        runtime.reconciliation_count = 6
        runtime.reconciliation_duration_seconds = 0.25
        runtime.retention_gap_count = 7
        runtime.reconnect_count = 8
        metrics = coordinator.metrics(runtime.database_id)
        self.assertEqual(
            (
                metrics.database_id,
                metrics.poll_count,
                metrics.poll_duration_seconds,
                metrics.transaction_count,
                metrics.change_row_count,
                metrics.reconciliation_count,
                metrics.reconciliation_duration_seconds,
                metrics.retention_gap_count,
                metrics.reconnect_count,
            ),
            (runtime.database_id, 3, 0.5, 4, 5, 6, 0.25, 7, 8),
        )
        empty = coordinator.metrics("not-open")
        self.assertEqual(
            (
                empty.database_id,
                empty.poll_count,
                empty.poll_duration_seconds,
                empty.transaction_count,
                empty.change_row_count,
                empty.reconciliation_count,
                empty.reconciliation_duration_seconds,
                empty.retention_gap_count,
                empty.reconnect_count,
            ),
            ("not-open", 0, 0.0, 0, 0, 0, 0.0, 0, 0),
        )

    def test_enter_conflict_blocks_delivery_and_requests_a_worker_owned_recovery(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.recovery_ready = True
        runtime.pending_delivery = False
        runtime.command_event.clear()
        coordinator.enter_conflict(runtime.database_id, "remote conflict")
        self.assertFalse(runtime.healthy)
        self.assertTrue(runtime.pending_delivery)
        self.assertTrue(runtime.recovery_requested)
        self.assertFalse(runtime.recovery_ready)
        self.assertTrue(runtime.command_event.is_set())
        status = coordinator.status(runtime.database_id)
        self.assertEqual(status.state, SynchronizationState.CONFLICTED)
        self.assertEqual(status.message, "remote conflict")
        # A database without a runtime is ignored.
        published = len(coordinator._event_bus.published)
        coordinator.enter_conflict("not-open", "ignored")
        coordinator.enter_resource_conflict(
            "not-open", ResourceRef("condition", "1", 8), "ignored"
        )
        self.assertEqual(len(coordinator._event_bus.published), published)
        self.assertEqual(
            coordinator.status("not-open").conflicted_resources, frozenset()
        )

    def test_resource_conflicts_use_the_default_message_and_mark_the_resource(self):
        coordinator, runtime = self.ready_coordinator()
        resource = ResourceRef("condition", "42", 8)
        coordinator.enter_resource_conflict(runtime.database_id, resource)
        status = coordinator.status(runtime.database_id)
        self.assertEqual(
            status.message,
            "A pending remote transaction overlaps an active local draft.",
        )
        self.assertEqual(status.conflicted_resources, frozenset({resource}))
        self.assertEqual(status.state, SynchronizationState.CONFLICTED)

    def test_only_registered_sql_databases_use_sql_collaboration(self):
        coordinator, runtime = self.ready_coordinator()
        access = DatabaseDescriptor.for_access("C:/second-pass-query.mdb")
        coordinator._registry.register(access)
        self.assertIs(coordinator.uses_sql_collaboration(runtime.database_id), True)
        self.assertIs(coordinator.uses_sql_collaboration(access.database_id), False)
        self.assertIs(coordinator.uses_sql_collaboration("not-registered"), False)


class _RecordingDispatcher:
    """Capture the feed deliveries a poll hands to the UI; run everything else."""

    _CAPTURED = frozenset({"_on_remote_batch", "_on_session_reconciliation_required"})

    def __init__(self):
        self.calls = []

    def dispatch(self, callback, payload=()):
        if callback.__name__ in self._CAPTURED:
            self.calls.append((callback.__name__, payload))
        else:
            callback(payload)


class SqlCollaborationPollBoundaryTests(_SecondPassBase):
    def poll(self, *, acknowledged, feed_epoch, batch, maximum_batch_size=500):
        store = _CollaborationStore()
        store.batch = batch
        dispatcher = _RecordingDispatcher()
        coordinator, runtime = self.ready_coordinator(
            store=store,
            dispatcher=dispatcher,
            polling_policy=CollaborationPollingPolicy(
                maximum_batch_size=maximum_batch_size
            ),
        )
        runtime.acknowledged_version = acknowledged
        runtime.feed_epoch = feed_epoch
        with patch.object(store, "poll_changes", wraps=store.poll_changes) as polled:
            coordinator._poll_once(runtime)
        return coordinator, runtime, dispatcher, polled

    def test_checkpoint_validity_is_checked_at_the_exact_range_boundaries(self):
        invalid = "The SQL Change Tracking checkpoint is no longer valid."
        # (label, acknowledged, minimum valid, high water, expected invalid)
        for label, acknowledged, minimum, high_water, expected_gap in (
            ("equal to the minimum valid version", 10, 10, 25, False),
            ("one below the minimum valid version", 9, 10, 25, True),
            ("equal to the high-water version", 25, 10, 25, False),
            ("one above the high-water version", 26, 10, 25, True),
            # Decision D3: 0 is a real checkpoint (a session that started before
            # any tracked change), not an "unset" one, so it is validated too.
            ("zero with history retained from zero", 0, 0, 25, False),
            ("zero below the retained range", 0, 5, 25, True),
            ("zero one below the retained range", 0, 1, 25, True),
        ):
            with self.subTest(label):
                batch = DatabaseChangeBatch(
                    database_id="db",
                    feed_epoch="epoch",
                    minimum_valid_version=minimum,
                    high_water_version=high_water,
                    delivered_through_version=acknowledged,
                )
                coordinator, runtime, dispatcher, _polled = self.poll(
                    acknowledged=acknowledged, feed_epoch="epoch", batch=batch
                )
                database_id = runtime.database_id
                self.assertEqual(runtime.observed_high_water_version, high_water)
                if expected_gap:
                    self.assertEqual(
                        dispatcher.calls,
                        [
                            (
                                "_on_session_reconciliation_required",
                                (
                                    database_id,
                                    runtime.generation,
                                    runtime.session_generation,
                                    invalid,
                                ),
                            )
                        ],
                    )
                    self.assertEqual(runtime.retention_gap_count, 1)
                    self.assertTrue(runtime.pending_delivery)
                else:
                    self.assertEqual(dispatcher.calls, [])
                    self.assertEqual(runtime.retention_gap_count, 0)
                    self.assertFalse(runtime.pending_delivery)

    def test_feed_epoch_is_adopted_once_and_a_different_epoch_forces_reconciliation(
        self,
    ):
        database_id = "db"
        change = _change(database_id, ResourceRef("condition", "42", 8), sequence=12)
        batch = _batch(database_id, "epoch-2", 1, 25, (change,), delivered_through=12)
        coordinator, runtime, dispatcher, _polled = self.poll(
            acknowledged=10, feed_epoch="epoch-1", batch=batch
        )
        self.assertEqual(
            dispatcher.calls,
            [
                (
                    "_on_session_reconciliation_required",
                    (
                        runtime.database_id,
                        runtime.generation,
                        runtime.session_generation,
                        "The SQL change feed was reset.",
                    ),
                )
            ],
        )
        self.assertTrue(runtime.pending_delivery)
        # The feed reset is not a retention gap and the old epoch is kept until
        # the controlled recovery installs a new session.
        self.assertEqual(runtime.retention_gap_count, 0)
        self.assertEqual(runtime.feed_epoch, "epoch-1")
        self.assertEqual(runtime.observed_high_water_version, 25)
        self.assertEqual(runtime.acknowledged_version, 10)
        # Matching epochs deliver the batch; the first poll of a session adopts
        # the epoch the feed reports.
        for previous in ("epoch-2", ""):
            with self.subTest(previous_epoch=previous):
                coordinator, runtime, dispatcher, _polled = self.poll(
                    acknowledged=10, feed_epoch=previous, batch=batch
                )
                self.assertEqual(runtime.feed_epoch, "epoch-2")
                self.assertEqual(
                    [name for name, _ in dispatcher.calls], ["_on_remote_batch"]
                )

    def test_remote_batch_delivery_carries_exact_context_and_counts_transactions(self):
        database_id = "db"
        first = _change(database_id, ResourceRef("condition", "42", 8), sequence=11)
        second = replace(
            _change(database_id, ResourceRef("condition", "43", 8), sequence=12),
            transaction_id=first.transaction_id,
        )
        third = replace(
            _change(database_id, ResourceRef("takeoff", "9", 8), sequence=13),
            transaction_id="transaction-2",
        )
        batch = _batch(
            database_id, "epoch", 1, 25, (first, second, third), delivered_through=13
        )
        coordinator, runtime, dispatcher, polled = self.poll(
            acknowledged=10, feed_epoch="epoch", batch=batch, maximum_batch_size=7
        )
        polled.assert_called_once_with(
            runtime.database_id, 10, 7, runtime.session.session_id
        )
        ((name, payload),) = dispatcher.calls
        self.assertEqual(name, "_on_remote_batch")
        (delivered_database, generation, session_generation, hydrated, owner) = payload
        self.assertEqual(
            (delivered_database, generation, session_generation, owner),
            (runtime.database_id, runtime.generation, runtime.session_generation, None),
        )
        self.assertEqual(hydrated.batch.changes, (first, second, third))
        self.assertEqual(hydrated.batch.delivered_through_version, 13)
        self.assertTrue(runtime.pending_delivery)
        # The checkpoint only moves after the main-thread reconciliation.
        self.assertEqual(runtime.acknowledged_version, 10)
        self.assertEqual(runtime.transaction_count, 2)
        self.assertEqual(runtime.change_row_count, 3)

    def test_empty_batch_delivers_only_when_the_checkpoint_can_advance(self):
        database_id = "db"
        quiet = _batch(database_id, "epoch", 1, 25, delivered_through=10)
        coordinator, runtime, dispatcher, polled = self.poll(
            acknowledged=10, feed_epoch="epoch", batch=quiet
        )
        self.assertEqual(dispatcher.calls, [])
        self.assertFalse(runtime.pending_delivery)
        self.assertEqual(runtime.transaction_count, 0)
        self.assertEqual(runtime.change_row_count, 0)
        advance = _batch(database_id, "epoch", 1, 25, delivered_through=11)
        coordinator, runtime, dispatcher, _polled = self.poll(
            acknowledged=10, feed_epoch="epoch", batch=advance
        )
        self.assertEqual([name for name, _ in dispatcher.calls], ["_on_remote_batch"])
        self.assertTrue(runtime.pending_delivery)

    def test_poll_does_not_reach_the_store_while_a_delivery_or_session_is_missing(self):
        store = _CollaborationStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        runtime.pending_delivery = True
        coordinator._poll_once(runtime)
        self.assertFalse(store.polled.is_set())
        runtime.pending_delivery = False
        session, runtime.session = runtime.session, None
        coordinator._poll_once(runtime)
        self.assertFalse(store.polled.is_set())
        runtime.session = session
        coordinator._poll_once(runtime)
        self.assertTrue(store.polled.is_set())

    def test_poll_metrics_count_every_attempt_even_when_the_store_fails(self):
        class _FailingStore(_CollaborationStore):
            def poll_changes(self, *args):
                raise OSError("poll failed")

        coordinator, runtime = self.ready_coordinator(store=_FailingStore())
        for expected in (1, 2):
            with self.assertRaises(OSError):
                coordinator._poll(runtime)
            self.assertEqual(runtime.poll_count, expected)
        self.assertGreater(runtime.poll_duration_seconds, 0.0)
        working, healthy = self.ready_coordinator()
        working._poll(healthy)
        self.assertEqual(healthy.poll_count, 1)


class SqlCollaborationRuntimeStateTests(unittest.TestCase):
    def test_a_new_runtime_starts_idle_untrusted_and_unestablished(self):
        runtime = _DatabaseRuntime("database", 3)
        self.assertEqual((runtime.database_id, runtime.generation), ("database", 3))
        self.assertEqual(
            (
                runtime.session_generation,
                runtime.restored_session_generation,
                runtime.retry_initial_failure,
                runtime.initial_open_callback,
                runtime.session,
                runtime.acknowledged_version,
                runtime.observed_high_water_version,
                runtime.feed_epoch,
                runtime.healthy,
                runtime.established,
                runtime.edit_depth,
                runtime.pending_delivery,
                runtime.recovery_requested,
                runtime.recovery_ready,
                runtime.recovery_attempted,
                runtime.bid_uid,
                runtime.page_uid,
                runtime.mode,
                runtime.close_reason,
                runtime.thread,
            ),
            (
                0,
                -1,
                True,
                None,
                None,
                0,
                0,
                "",
                False,
                False,
                0,
                False,
                False,
                False,
                False,
                None,
                None,
                PresenceMode.VIEWING,
                "closed",
                None,
            ),
        )
        self.assertEqual(
            (
                runtime.poll_count,
                runtime.poll_duration_seconds,
                runtime.transaction_count,
                runtime.change_row_count,
                runtime.reconciliation_count,
                runtime.reconciliation_duration_seconds,
                runtime.retention_gap_count,
                runtime.reconnect_count,
            ),
            (0, 0.0, 0, 0, 0, 0.0, 0, 0),
        )
        self.assertEqual(
            (
                runtime.owned_locks,
                runtime.draft_ids,
                runtime.cancelled_mutation_ids,
                runtime.recovered_operation_ids,
                runtime.recovered_operation_results,
                runtime.cleanup_errors,
            ),
            ({}, {}, set(), set(), {}, []),
        )
        self.assertFalse(
            runtime.stop_event.is_set()
            or runtime.ready_event.is_set()
            or runtime.command_event.is_set()
        )
        # Mutable collections are per runtime, never shared.
        other = _DatabaseRuntime("database", 4)
        runtime.owned_locks["x"] = None
        runtime.cleanup_errors.append("x")
        self.assertEqual((other.owned_locks, other.cleanup_errors), ({}, []))

    def test_a_queued_mutation_is_an_immutable_snapshot(self):
        request = _placement_request("database", "frozen")
        queued = _QueuedMutation(
            database_id="database",
            runtime_generation=1,
            operation_id=request.operation_id,
            owning_surface=request.owning_surface,
            resources=request.resources,
            dependency_resources=(),
            operation=lambda: _committed_execution(),
            callback=lambda _result: None,
            typed_request=request,
        )
        self.assertIsNone(queued.result_validator)
        self.assertIsNone(queued.edit_lease_handle)
        with self.assertRaises(FrozenInstanceError):
            queued.operation_id = "changed"

    def test_the_mutation_queue_bound_and_drain_grace_are_the_documented_constants(
        self,
    ):
        runtime = _DatabaseRuntime("database", 1)
        self.assertEqual(runtime.mutation_requests.maxsize, 64)
        self.assertEqual(runtime.edit_requests.maxsize, 0)


class SqlCollaborationStartGuardTests(_SecondPassBase):
    def test_start_is_refused_for_every_blocked_database_state(self):
        store = _CollaborationStore()
        coordinator, descriptor, _store, _events, _caps = self.threaded_coordinator(
            store=store
        )
        database_id = descriptor.database_id
        access_with_sql_version = DatabaseDescriptor.for_access(
            "C:/versioned.mdb", schema_version=SQL_SCHEMA_V1.version
        )
        coordinator._registry.register(access_with_sql_version)
        self.assertIs(
            coordinator.start_database(access_with_sql_version.database_id), False
        )
        coordinator._shutting_down = True
        self.assertIs(coordinator.start_database(database_id), False)
        coordinator._shutting_down = False
        coordinator._database_drains[(database_id, 7)] = []
        self.assertIs(coordinator.start_database(database_id), False)
        del coordinator._database_drains[(database_id, 7)]
        coordinator._database_cleanup_failures[database_id] = "remote session left open"
        self.assertIs(coordinator.start_database(database_id), False)
        del coordinator._database_cleanup_failures[database_id]
        self.assertEqual(store.start_count, 0)
        self.assertEqual(coordinator._runtimes, {})
        # Another draining database does not block this one (positive control).
        coordinator._database_drains[("another-database", 7)] = []
        self.assertTrue(coordinator.start_database(database_id))
        self.assertTrue(store.started.wait(2))
        self.assertIs(coordinator.start_database(database_id), False)
        coordinator._database_drains.clear()

    def test_started_runtime_is_numbered_named_and_announced_as_connecting(self):
        created = []

        class _RecordingThread(threading.Thread):
            def __init__(self, *args, **kwargs):
                created.append(kwargs)
                super().__init__(*args, **kwargs)

        store = _CollaborationStore()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store
        )
        database_id = descriptor.database_id
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        callback = []
        with patch.object(threading, "Thread", _RecordingThread):
            self.assertTrue(
                coordinator.start_database(
                    database_id, on_initial_open=lambda *result: callback.append(result)
                )
            )
            self.assertTrue(healthy.wait(2))
            first = coordinator._runtime(database_id)
            _stop_database(coordinator, database_id)
            self.assertTrue(coordinator.start_database(database_id))
            second = coordinator._runtime(database_id)
        self.assertEqual((first.generation, second.generation), (1, 2))
        self.assertTrue(first.retry_initial_failure)
        self.assertEqual(callback, [(True, "")])
        worker_kwargs = [
            kw for kw in created if kw["name"].startswith("SqlCollaboration-")
        ]
        drain_kwargs = [
            kw for kw in created if kw["name"].startswith("SqlCollaborationDrain-")
        ]
        self.assertEqual(
            [(kw["name"], kw["daemon"]) for kw in worker_kwargs],
            [(f"SqlCollaboration-{database_id[:8]}", True)] * 2,
        )
        # The drain must finish remote cleanup before the process may exit.
        self.assertEqual(
            [(kw["name"], kw["daemon"]) for kw in drain_kwargs],
            [(f"SqlCollaborationDrain-{database_id[:8]}", False)],
        )
        self.assertEqual(
            self.published(coordinator, AppEvents.COLLABORATION_STATE_CHANGED)[0][
                "state"
            ],
            "connecting",
        )

    def test_initial_connection_failure_is_retried_by_default(self):
        store = _AlwaysUnavailableStoreForRetry()
        coordinator, descriptor, _store, _events, _caps = self.threaded_coordinator(
            store=store
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(store.repeated_failure.wait(3))
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertTrue(runtime.thread.is_alive())
        self.assertGreaterEqual(
            coordinator.metrics(descriptor.database_id).reconnect_count, 1
        )


class _AlwaysUnavailableStoreForRetry(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.repeated_failure = threading.Event()

    def start_session(self, *args, **kwargs):
        self.start_count += 1
        if self.start_count > 1:
            self.repeated_failure.set()
        raise DatabaseCatalogError("server unavailable", retryable=True)


class SqlCollaborationStopAndDrainBookkeepingTests(_SecondPassBase):
    def idle_coordinator(self):
        coordinator, descriptor, store, events, capabilities = (
            self.threaded_coordinator(register_cleanup=False)
        )
        return coordinator, descriptor.database_id, events, capabilities

    def stopped_signal(self, events, database_id):
        return _state_signal(events, database_id, SynchronizationState.STOPPED)

    def test_stopping_an_unknown_database_reports_success_without_finalizing_it(self):
        coordinator, database_id, events, _caps = self.idle_coordinator()
        results = []
        with patch.object(
            coordinator._concurrency_tokens,
            "clear_database",
            wraps=coordinator._concurrency_tokens.clear_database,
        ) as clear:
            coordinator.stop_database_async(
                database_id, "reconfigured", lambda *result: results.append(result)
            )
        self.assertEqual(results, [(True, "")])
        clear.assert_not_called()
        self.assertEqual(events.published, [])
        # No callback is also fine.
        coordinator.stop_database_async(database_id, "reconfigured")

    def test_a_retained_cleanup_failure_is_reported_unless_the_stop_is_a_local_detach(
        self,
    ):
        coordinator, database_id, events, capabilities = self.idle_coordinator()
        coordinator._database_cleanup_failures[database_id] = "session left open"
        results = []
        coordinator.stop_database_async(
            database_id, "reconfigured", lambda *result: results.append(result)
        )
        self.assertEqual(results, [(False, "session left open")])
        self.assertEqual(
            coordinator._database_cleanup_failures, {database_id: "session left open"}
        )
        for reason in ("closed", "unchecked", "connection-removed"):
            with self.subTest(reason=reason):
                coordinator._database_cleanup_failures[database_id] = (
                    "session left open"
                )
                results.clear()
                with patch.object(
                    coordinator._concurrency_tokens,
                    "clear_database",
                    wraps=coordinator._concurrency_tokens.clear_database,
                ) as clear:
                    coordinator.stop_database_async(
                        database_id, reason, lambda *result: results.append(result)
                    )
                self.assertEqual(results, [(True, "")])
                self.assertEqual(coordinator._database_cleanup_failures, {})
                clear.assert_called_once_with(database_id)
                self.assertEqual(
                    capabilities.collaboration_status(database_id).state,
                    SynchronizationState.STOPPED,
                )
        # A local detach without a callback still finalizes the database.
        events.published.clear()
        coordinator.stop_database_async(database_id, "closed")
        self.assertEqual(
            [
                payload["state"]
                for event, payload in events.published
                if event is AppEvents.COLLABORATION_STATE_CHANGED
            ],
            ["stopped"],
        )

    def test_stop_requests_during_a_drain_join_it_and_local_detach_wins(self):
        coordinator, database_id, events, _caps = self.idle_coordinator()
        key = (database_id, 5)
        coordinator._database_drains[key] = []
        results = []
        coordinator.stop_database_async(
            database_id,
            "reconfigured",
            lambda *result: results.append(("first", *result)),
        )
        self.assertEqual(results, [])
        self.assertEqual(coordinator._local_detach_drains, set())
        coordinator.stop_database_async(database_id, "closed")
        self.assertEqual(coordinator._local_detach_drains, {key})
        coordinator.stop_database_async(
            database_id, "closed", lambda *result: results.append(("second", *result))
        )
        self.assertEqual(len(coordinator._database_drains[key]), 2)
        # The drain failed remotely, but a local detach abandons the cleanup.
        coordinator._complete_database_drain((database_id, 5, False, "close failed"))
        self.assertEqual(results, [("first", True, ""), ("second", True, "")])
        self.assertEqual(coordinator._database_cleanup_failures, {})
        self.assertEqual(coordinator._local_detach_drains, set())
        self.assertEqual(coordinator._database_drains, {})

    def test_failed_drain_is_recorded_with_a_default_message_and_blocks_a_restart(self):
        coordinator, database_id, events, _caps = self.idle_coordinator()
        results = []
        coordinator._database_drains[(database_id, 5)] = [
            lambda *result: results.append(result)
        ]
        coordinator._complete_database_drain((database_id, 5, False, ""))
        failure = f"SQL collaboration cleanup failed for {database_id}."
        self.assertEqual(results, [(False, failure)])
        self.assertEqual(coordinator._database_cleanup_failures, {database_id: failure})
        self.assertIs(coordinator.start_database(database_id), False)
        # No STOPPED projection for a failed drain.
        self.assertEqual(
            self.published(coordinator, AppEvents.COLLABORATION_STATE_CHANGED), []
        )
        # A later successful drain of the same database clears the record.
        coordinator._database_drains[(database_id, 6)] = []
        coordinator._complete_database_drain((database_id, 6, True, ""))
        self.assertEqual(coordinator._database_cleanup_failures, {})
        self.assertEqual(
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
            ],
            ["stopped"],
        )

    def test_drain_failures_during_shutdown_are_added_to_the_shutdown_report(self):
        coordinator, database_id, events, _caps = self.idle_coordinator()
        coordinator._shutting_down = True
        coordinator._shutdown_state = CollaborationShutdownState.DRAINING
        coordinator._database_drains[(database_id, 5)] = []
        coordinator._complete_database_drain((database_id, 5, False, "close failed"))
        self.assertEqual(coordinator._shutdown_cleanup_errors, ["close failed"])
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.CLEANUP_FAILED
        )
        # Not shutting down: the failure stays per database only.
        other, other_id, _events, _caps = self.idle_coordinator()
        other._database_drains[(other_id, 5)] = []
        other._complete_database_drain((other_id, 5, False, "close failed"))
        self.assertEqual(other._shutdown_cleanup_errors, [])

    def test_detaching_a_runtime_cancels_the_pending_open_and_wakes_its_worker(self):
        coordinator, runtime = self.ready_coordinator()
        opened = []
        runtime.initial_open_callback = lambda *result: opened.append(result)
        runtime.ready_event.clear()
        runtime.command_event.clear()
        _stop_database(coordinator, runtime.database_id)
        self.assertEqual(opened, [(False, "SQL database opening was stopped.")])
        self.assertEqual(runtime.close_reason, "closed")
        self.assertTrue(runtime.stop_event.is_set())
        self.assertTrue(runtime.ready_event.is_set())
        self.assertTrue(runtime.command_event.is_set())
        states = [
            (payload["state"], payload["message"])
            for payload in self.published(
                coordinator, AppEvents.COLLABORATION_STATE_CHANGED
            )
        ]
        self.assertEqual(
            states,
            [("read_only", "SQL collaboration is closing."), ("stopped", "")],
        )
        self.assertNotIn(runtime.database_id, coordinator._runtimes)

    def test_configured_database_drain_timeout_is_connection_plus_command_plus_grace(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        self.assertEqual(coordinator._database_drain_timeout(runtime.database_id), 45.0)
        self.assertEqual(coordinator._database_drain_timeout("unregistered"), 5.0)
        access = DatabaseDescriptor.for_access("C:/drain-timeout.mdb")
        coordinator._registry.register(access)
        self.assertEqual(coordinator._database_drain_timeout(access.database_id), 5.0)


class SqlCollaborationShutdownReportingTests(_SecondPassBase):
    def build(self, event_bus=None):
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            events=event_bus, register_cleanup=False
        )
        return coordinator, descriptor, events

    def test_known_cleanup_failures_are_reported_once_and_keep_subscriptions(self):
        coordinator, descriptor, events = self.build()
        coordinator._database_cleanup_failures = {"a": "boom", "b": "boom", "c": "bang"}
        results = []
        coordinator.request_shutdown(lambda *result: results.append(result))
        self.assertEqual(results, [(False, "boom; bang")])
        self.assertEqual(
            coordinator.shutdown_state, CollaborationShutdownState.CLEANUP_FAILED
        )
        # A failed cleanup keeps the event bindings so a later cleanup can retry.
        self.assertEqual(
            {event for event, callbacks in events.subscribers.items() if callbacks},
            {
                AppEvents.FILE_OPENED,
                AppEvents.FILE_UNLOADED,
                AppEvents.DATABASE_REFRESHED,
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
            },
        )
        again = []
        coordinator.request_shutdown(lambda *result: again.append(result))
        self.assertEqual(again, [(False, "boom; bang")])

    def test_clean_shutdown_unsubscribes_every_event_and_refuses_new_work(self):
        coordinator, descriptor, events = self.build()
        results = []
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.RUNNING)
        coordinator.request_shutdown(lambda *result: results.append(result))
        self.assertEqual(results, [(True, "")])
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)
        self.assertEqual(
            {event for event, callbacks in events.subscribers.items() if callbacks},
            set(),
        )
        self.assertIs(coordinator.start_database(descriptor.database_id), False)
        # Terminal state answers later requests, with or without a callback.
        coordinator.request_shutdown()
        later = []
        coordinator.request_shutdown(lambda *result: later.append(result))
        self.assertEqual(later, [(True, "")])

    def test_unsubscribe_failure_message_names_the_event_and_the_error(self):
        coordinator, descriptor, events = self.build(_FailingUnsubscribeEventBus())
        results = []
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logs:
            coordinator.request_shutdown(lambda *result: results.append(result))
        expected = (
            f"SQL collaboration event unsubscription failed for "
            f"{AppEvents.FILE_OPENED}: listener registry unavailable"
        )
        self.assertEqual(results, [(False, expected)])
        self.assertEqual(
            [record.getMessage() for record in logs.records[:1]], [expected]
        )

    def test_shutdown_stops_every_runtime_with_the_shutdown_reason(self):
        coordinator, runtime = self.ready_coordinator()
        other = _DatabaseRuntime("second-database", 9)
        coordinator._runtimes[other.database_id] = other
        results = []
        coordinator.request_shutdown(lambda *result: results.append(result))
        self.assertEqual(results, [(True, "")])
        self.assertEqual(
            (runtime.close_reason, other.close_reason), ("shutdown", "shutdown")
        )
        self.assertTrue(runtime.stop_event.is_set() and other.stop_event.is_set())
        self.assertEqual(coordinator._runtimes, {})
        self.assertEqual(coordinator._database_drains, {})


class SqlCollaborationWorkerStopGateTests(_SecondPassBase):
    """A stop request must prevent every later phase of the session bootstrap."""

    def start_gated(self, gate_name):
        store = _ScriptedStore()
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(store=store)
        )
        spies = {
            "load_database": patch.object(
                coordinator._concurrency_tokens,
                "load_database",
                wraps=coordinator._concurrency_tokens.load_database,
            ),
            "initial_reconciliation": patch.object(
                coordinator._remote_reader,
                "initial_reconciliation",
                wraps=coordinator._remote_reader.initial_reconciliation,
            ),
            "journal": patch.object(
                coordinator._operation_journal,
                "list_all",
                wraps=coordinator._operation_journal.list_all,
            ),
            "session_started": patch.object(
                coordinator,
                "_on_session_started",
                wraps=coordinator._on_session_started,
            ),
        }
        mocks = {name: spy.start() for name, spy in spies.items()}
        for spy in spies.values():
            self.addCleanup(spy.stop)
        gate = _Gate()
        self.addCleanup(gate.release.set)
        gated = {
            "load_database": (coordinator._concurrency_tokens, "load_database"),
            "initial_reconciliation": (
                coordinator._remote_reader,
                "initial_reconciliation",
            ),
            "journal": (coordinator._operation_journal, "list_all"),
        }
        if gate_name in gated:
            owner, attribute = gated[gate_name]
            original = getattr(owner, attribute)
            setattr(owner, attribute, gate.wrap(original))
            self.addCleanup(setattr, owner, attribute, original)
        return coordinator, descriptor, store, mocks, gate, events

    def shutdown_while_gated(self, coordinator, gate):
        self.assertTrue(gate.entered.wait(3))
        done = threading.Event()
        results = []
        coordinator.request_shutdown(
            lambda *result: (results.append(result), done.set())
        )
        gate.release.set()
        self.assertTrue(done.wait(3))
        self.assertEqual(results, [(True, "")])

    def test_stop_during_bootstrap_skips_every_later_phase(self):
        # (gate, phases that must NOT run afterwards)
        for gate_name, skipped in (
            ("load_database", ("initial_reconciliation", "journal", "session_started")),
            ("initial_reconciliation", ("journal", "session_started")),
            ("journal", ("session_started",)),
        ):
            with self.subTest(gate=gate_name):
                coordinator, descriptor, store, mocks, gate, _events = self.start_gated(
                    gate_name
                )
                self.assertTrue(coordinator.start_database(descriptor.database_id))
                self.shutdown_while_gated(coordinator, gate)
                for name in skipped:
                    mocks[name].assert_not_called()
                self.assertEqual(store.calls.get("heartbeat", 0), 0)
                self.assertEqual(store.calls.get("poll_changes", 0), 0)
                self.assertTrue(store.closed.is_set())

    def test_stop_while_waiting_for_the_session_start_projection_ends_the_worker(self):
        class _HoldSessionStart(_Dispatcher):
            def dispatch(self, callback, payload=()):
                if callback.__name__ == "_on_session_started":
                    return  # the UI never gets to project the session start
                callback(payload)

        store = _ScriptedStore()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store, dispatcher=_HoldSessionStart()
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        deadline = time.monotonic() + 3
        while store.calls.get("start_session", 0) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        runtime = coordinator._runtime(descriptor.database_id)
        time.sleep(0.15)
        # The worker is still waiting for the projection: no heartbeat or poll yet.
        self.assertEqual(store.calls.get("heartbeat", 0), 0)
        self.assertEqual(store.calls.get("poll_changes", 0), 0)
        self.assertTrue(runtime.thread.is_alive())
        _stop_database(coordinator, descriptor.database_id)
        self.assertFalse(runtime.thread.is_alive())
        self.assertEqual(store.calls.get("heartbeat", 0), 0)
        self.assertEqual(store.calls.get("poll_changes", 0), 0)
        self.assertTrue(store.closed.is_set())

    def test_each_session_start_loads_the_concurrency_tokens_for_that_database(self):
        store = _ScriptedStore()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        with patch.object(
            coordinator._concurrency_tokens,
            "load_database",
            wraps=coordinator._concurrency_tokens.load_database,
        ) as load:
            self.assertTrue(coordinator.start_database(descriptor.database_id))
            self.assertTrue(healthy.wait(3))
            load.assert_called_once_with(descriptor.database_id)
            _stop_database(coordinator, descriptor.database_id)

    def test_stop_during_the_first_poll_does_not_probe_permissions_or_announce_health(
        self,
    ):
        class _CountingProbe(_PermissionProbe):
            calls = 0

            def can_edit(self, _database_id):
                type(self).calls += 1
                return True

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _CountingProbe())
        capabilities.mark_connected(descriptor.database_id)
        _CountingProbe.calls = 0
        store = _ScriptedStore()
        entered = threading.Event()
        release = threading.Event()

        def hold():
            entered.set()
            release.wait(5)

        store.script[("poll_changes", 1)] = hold
        coordinator, _descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store, capabilities=capabilities, descriptor=descriptor
        )
        self.addCleanup(release.set)
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(entered.wait(3))
        done = threading.Event()
        coordinator.request_shutdown(lambda *_result: done.set())
        release.set()
        self.assertTrue(done.wait(3))
        self.assertEqual(_CountingProbe.calls, 0)
        self.assertNotIn(
            "healthy",
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
            ],
        )

    def test_stop_while_the_queue_is_serviced_prevents_the_heartbeat(self):
        store = _ScriptedStore()
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store,
            polling_policy=CollaborationPollingPolicy(
                heartbeat_seconds=0.0, inactive_database_seconds=0.05, jitter_ratio=0.0
            ),
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        gate = _Gate()
        self.addCleanup(gate.release.set)
        original = coordinator._process_mutation_requests
        calls = []

        def gated(runtime):
            calls.append(runtime)
            if len(calls) == 2:
                gate.entered.set()
                gate.release.wait(5)
            return original(runtime)

        coordinator._process_mutation_requests = gated
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(3))
        self.assertTrue(gate.entered.wait(3))
        heartbeats = store.calls["heartbeat"]
        done = threading.Event()
        coordinator.request_shutdown(lambda *_result: done.set())
        gate.release.set()
        self.assertTrue(done.wait(3))
        self.assertEqual(store.calls["heartbeat"], heartbeats)


class SqlCollaborationWorkerRecoveryLoopTests(_SecondPassBase):
    def test_a_requested_recovery_waits_for_resume_then_installs_one_fresh_session(
        self,
    ):
        store = _ScriptedStore()
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(store=store)
        )
        database_id = descriptor.database_id
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.assertTrue(coordinator.start_database(database_id))
        self.assertTrue(healthy.wait(3))
        runtime = coordinator._runtime(database_id)
        self.assertEqual(runtime.feed_epoch, "epoch")
        first_session = runtime.session.session_id
        # A feed reset: the replacement session sees a different epoch.
        store.batch = _batch(database_id, "epoch-2", 0, 0)
        coordinator._on_reconciliation_required(
            (database_id, runtime.generation, "retention gap")
        )
        deadline = time.monotonic() + 3
        while runtime.session is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(runtime.session)
        self.assertTrue(store.closed.is_set())
        # Without a resume the worker keeps waiting; no replacement session.
        time.sleep(0.4)
        self.assertEqual(store.calls["start_session"], 1)
        self.assertEqual(
            capabilities.collaboration_status(database_id).state,
            SynchronizationState.RECONCILIATION_REQUIRED,
        )
        recovered = threading.Event()
        events.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED,
            lambda database_id="", state="", **_payload: (
                recovered.set()
                if state == "healthy" and store.calls["start_session"] == 2
                else None
            ),
        )
        self.assertTrue(coordinator.resume_controlled_recovery(database_id))
        self.assertTrue(recovered.wait(3))
        self.assertNotEqual(runtime.session.session_id, first_session)
        time.sleep(0.3)
        # One replacement only; its flags are clean and its epoch is the new one.
        self.assertEqual(store.calls["start_session"], 2)
        self.assertFalse(runtime.recovery_requested)
        self.assertFalse(runtime.recovery_ready)
        self.assertFalse(runtime.pending_delivery)
        self.assertEqual(runtime.feed_epoch, "epoch-2")
        self.assertEqual(
            [
                p["reason"]
                for p in self.published(
                    coordinator, AppEvents.FULL_RECONCILIATION_REQUIRED
                )
            ],
            ["retention gap"],
        )
        # A later recovery can be resumed again (the attempt flag was re-armed).
        coordinator._on_reconciliation_required(
            (database_id, runtime.generation, "again")
        )
        self.assertTrue(coordinator.resume_controlled_recovery(database_id))
        deadline = time.monotonic() + 3
        while store.calls["start_session"] < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(store.calls["start_session"], 3)
        _stop_database(coordinator, database_id)

    def test_a_feed_error_closes_the_session_before_requesting_recovery(self):
        store = _ScriptedStore()
        store.fail_once["poll_changes"] = ValueError("invalid transaction marker")
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store
        )
        requested = _state_signal(
            events, descriptor.database_id, SynchronizationState.RECONCILIATION_REQUIRED
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(requested.wait(3))
        states = [
            (p["state"], p["message"])
            for p in self.published(coordinator, AppEvents.COLLABORATION_STATE_CHANGED)
        ]
        self.assertEqual(
            states[-2:],
            [
                ("disconnected", "invalid transaction marker"),
                ("reconciliation_required", "invalid transaction marker"),
            ],
        )
        self.assertTrue(store.closed.is_set())
        self.assertEqual(store.calls["start_session"], 1)

    def test_a_retention_gap_never_reports_health_while_recovery_is_pending(self):
        store = _ScriptedStore()
        store.initial_version = 30
        store.batch = DatabaseChangeBatch(
            database_id="db",
            feed_epoch="epoch",
            minimum_valid_version=1,
            high_water_version=25,
            delivered_through_version=30,
        )
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store
        )
        requested = _state_signal(
            events, descriptor.database_id, SynchronizationState.RECONCILIATION_REQUIRED
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(requested.wait(3))
        time.sleep(0.4)
        self.assertNotIn(
            "healthy",
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
            ],
        )
        self.assertEqual(store.calls["start_session"], 1)
        runtime = coordinator._runtime(descriptor.database_id)
        self.assertTrue(runtime.pending_delivery)
        self.assertFalse(runtime.healthy)


class SqlCollaborationMutationCompletionTests(_SecondPassBase):
    def pending_request(self, coordinator, runtime, label, **overrides):
        request = _placement_request(runtime.database_id, label, **overrides)
        coordinator._pending_mutations.begin(
            request, runtime_generation=runtime.generation
        )
        return request

    def result_for(self, runtime, request, status, **fields):
        return QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=request.operation_id,
            outcome_status=status,
            **fields,
        )

    def test_a_committed_result_is_untrusted_while_the_runtime_stops_or_recovers(self):
        for label, change in (
            ("stopping", lambda r: r.stop_event.set()),
            ("recovery requested", lambda r: setattr(r, "recovery_requested", True)),
        ):
            with self.subTest(label):
                coordinator, runtime = self.ready_coordinator()
                request = self.pending_request(
                    coordinator, runtime, f"untrusted-{label}"
                )
                change(runtime)
                results = []
                coordinator._complete_mutation_request(
                    (
                        results.append,
                        self.result_for(
                            runtime,
                            request,
                            MutationOutcomeStatus.COMMITTED,
                            created_resource_ids=("1",),
                        ),
                    )
                )
                self.assertEqual(
                    [
                        (r.outcome_status, r.message, r.created_resource_ids)
                        for r in results
                    ],
                    [
                        (
                            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                            "The SQL runtime changed before the mutation completed.",
                            (),
                        )
                    ],
                )
        # A conflict is only published for a trusted runtime.
        coordinator, runtime = self.ready_coordinator()
        runtime.stop_event.set()
        request = self.pending_request(coordinator, runtime, "untrusted-conflict")
        conflict = SynchronizationConflict(
            runtime.database_id, ResourceRef("takeoffs_collection", "8", 8), "stale"
        )
        coordinator._complete_mutation_request(
            (
                lambda _result: None,
                self.result_for(
                    runtime,
                    request,
                    MutationOutcomeStatus.CONFLICT,
                    message="stale",
                    conflict=conflict,
                ),
            )
        )
        self.assertEqual(
            self.published(coordinator, AppEvents.SYNCHRONIZATION_CONFLICT), []
        )

    def test_a_failing_callback_turns_a_committed_result_into_recovery_only(self):
        for status, expects_recovery in (
            (MutationOutcomeStatus.COMMITTED, True),
            (MutationOutcomeStatus.REJECTED, False),
        ):
            with self.subTest(status=status):
                coordinator, runtime = self.ready_coordinator()
                request = self.pending_request(
                    coordinator, runtime, f"callback-{status.value}"
                )

                def broken(result):
                    raise RuntimeError("closed dialog")

                with self.assertLogs(
                    "ost_visualizer.application.services.sql_collaboration_coordinator",
                    level="ERROR",
                ) as logged:
                    coordinator._complete_mutation_request(
                        (
                            broken,
                            self.result_for(
                                runtime,
                                request,
                                status,
                                authoritative_result=(
                                    AuthoritativeMutationResult(created_resource_ids=())
                                    if status == MutationOutcomeStatus.COMMITTED
                                    else None
                                ),
                            ),
                        )
                    )
                self.assertEqual(
                    [r.getMessage() for r in logged.records],
                    ["SQL queued-mutation completion callback failed"],
                )
                pending = coordinator._pending_mutations.get(request.operation_id)
                if expects_recovery:
                    self.assertEqual(pending.state, PendingMutationState.RECOVERING)
                    self.assertIn(
                        request.operation_id, coordinator._uncertain_callbacks
                    )
                    self.assertTrue(runtime.recovery_requested)
                else:
                    self.assertIsNone(pending)
                    self.assertEqual(coordinator._uncertain_callbacks, {})
                    self.assertFalse(runtime.recovery_requested)

    def test_a_healthy_callback_finishes_a_committed_result_without_recovery(self):
        coordinator, runtime = self.ready_coordinator()
        request = self.pending_request(coordinator, runtime, "healthy-callback")
        results = []
        coordinator._complete_mutation_request(
            (
                results.append,
                self.result_for(runtime, request, MutationOutcomeStatus.COMMITTED),
            )
        )
        self.assertEqual(len(results), 1)
        self.assertIsNone(coordinator._pending_mutations.get(request.operation_id))
        self.assertEqual(coordinator._uncertain_callbacks, {})
        self.assertFalse(runtime.recovery_requested)

    def test_a_result_without_a_pending_entry_still_reaches_its_callback(self):
        coordinator, runtime = self.ready_coordinator()
        results = []
        orphan = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.REJECTED,
            message="orphan",
        )
        coordinator._complete_mutation_request((results.append, orphan))
        self.assertEqual(results, [orphan])
        self.assertEqual(coordinator._event_bus.published, [])

    def test_unknown_commit_status_is_recorded_with_its_message_or_a_default(self):
        for message, expected in (
            ("connection dropped", "connection dropped"),
            ("", "The SQL mutation's commit status is not yet known."),
        ):
            with self.subTest(message=message):
                journal = _PendingOperationJournal()
                coordinator, runtime = self.ready_coordinator(journal=journal)
                request = self.pending_request(
                    coordinator, runtime, f"unknown-{len(message)}"
                )
                coordinator._pending_mutations.transition(
                    request.operation_id, PendingMutationState.EXECUTING
                )
                results = []
                coordinator._complete_mutation_request(
                    (
                        results.append,
                        self.result_for(
                            runtime,
                            request,
                            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                            message=message,
                            commit_attempted=True,
                        ),
                    )
                )
                pending = coordinator._pending_mutations.get(request.operation_id)
                self.assertEqual(
                    (pending.state, pending.message),
                    (PendingMutationState.UNCERTAIN, expected),
                )
                self.assertEqual(
                    journal.records[request.operation_id].state,
                    PendingMutationState.UNCERTAIN,
                )
                self.assertEqual(
                    self.published(
                        coordinator, AppEvents.COLLABORATION_MUTATION_STATE_CHANGED
                    )[-1]["message"],
                    message,
                )

    def test_only_critical_failures_are_reported_to_a_pending_lifecycle_drain(self):
        coordinator, runtime = self.ready_coordinator()
        drained = []
        blocking = self.pending_request(coordinator, runtime, "blocking-critical")
        coordinator.drain_database_mutations_async(
            runtime.database_id, lambda *result: drained.append(result)
        )
        quiet = self.pending_request(
            coordinator, runtime, "noncritical-failure", lifecycle_critical=False
        )
        coordinator._complete_mutation_request(
            (
                lambda _result: None,
                self.result_for(
                    runtime,
                    quiet,
                    MutationOutcomeStatus.REJECTED,
                    message="view state refused",
                ),
            )
        )
        self.assertEqual(drained, [])
        coordinator._complete_mutation_request(
            (
                lambda _result: None,
                self.result_for(runtime, blocking, MutationOutcomeStatus.COMMITTED),
            )
        )
        self.assertEqual(drained, [(True, "")])
        # A critical failure is reported with its own message.
        critical = self.pending_request(coordinator, runtime, "critical-failure")
        again = []
        coordinator.drain_database_mutations_async(
            runtime.database_id, lambda *result: again.append(result)
        )
        coordinator._complete_mutation_request(
            (
                lambda _result: None,
                self.result_for(
                    runtime, critical, MutationOutcomeStatus.CONFLICT, message="stale"
                ),
            )
        )
        self.assertEqual(again, [(False, "stale")])


class SqlCollaborationShutdownStateObservationTests(_SecondPassBase):
    def test_shutdown_state_is_stop_requested_while_runtimes_are_stopped_and_during_unsubscription(
        self,
    ):
        class _ObservingBus(_EventBus):
            coordinator = None
            during_publish = []
            during_unsubscribe = []

            def publish(self, event, **payload):
                if event is AppEvents.COLLABORATION_STATE_CHANGED and self.coordinator:
                    self.during_publish.append(
                        (payload["state"], self.coordinator.shutdown_state)
                    )
                super().publish(event, **payload)

            def unsubscribe(self, event, callback):
                self.during_unsubscribe.append(self.coordinator.shutdown_state)
                super().unsubscribe(event, callback)

        bus = _ObservingBus()
        bus.during_publish = []
        bus.during_unsubscribe = []
        coordinator, runtime = self.ready_coordinator(event_bus=bus)
        bus.coordinator = coordinator
        results = []
        coordinator.request_shutdown(lambda *result: results.append(result))
        self.assertEqual(results, [(True, "")])
        self.assertEqual(
            bus.during_publish[0],
            ("read_only", CollaborationShutdownState.STOP_REQUESTED),
        )
        self.assertEqual(
            bus.during_unsubscribe,
            [CollaborationShutdownState.STOP_REQUESTED] * 4,
        )
        self.assertEqual(coordinator.shutdown_state, CollaborationShutdownState.CLOSED)


class _ScriptedStore(_CollaborationStore):
    """_CollaborationStore whose Nth call of a method can run or raise a script."""

    def __init__(self):
        super().__init__()
        self.script = {}
        self.fail_once = {}
        self.calls = {}
        self.thread_ids = {}

    def _step(self, name):
        count = self.calls[name] = self.calls.get(name, 0) + 1
        self.thread_ids.setdefault(name, set()).add(threading.get_ident())
        error = self.fail_once.pop(name, None)
        if error is not None:
            raise error
        action = self.script.get((name, count))
        if action is not None:
            action()

    def start_session(self, *args, **kwargs):
        self._step("start_session")
        return super().start_session(*args, **kwargs)

    def heartbeat(self, *args):
        self._step("heartbeat")
        return super().heartbeat(*args)

    def list_locks(self, *args, **kwargs):
        self._step("list_locks")
        return super().list_locks(*args, **kwargs)

    def poll_changes(self, *args):
        self._step("poll_changes")
        return super().poll_changes(*args)


def _raise(error):
    def action():
        raise error

    return action


class _Gate:
    """Block a collaborator call until released, reporting that it was entered."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def wrap(self, original):
        def gated(*args, **kwargs):
            self.entered.set()
            if not self.release.wait(5):
                raise AssertionError("gate was not released")
            return original(*args, **kwargs)

        return gated


class SqlCollaborationWorkerRetryTests(_SecondPassBase):
    def run_failures(self, error_factory, failures, *, retry_initial_failure=True):
        store = _ScriptedStore()
        for attempt in range(1, failures + 1):
            store.script[("start_session", attempt)] = _raise(error_factory(attempt))
        polling = CollaborationPollingPolicy(
            heartbeat_seconds=0.0,
            inactive_database_seconds=0.05,
            jitter_ratio=0.0,
            reconnect_backoff_seconds=(0.01, 0.02, 0.03),
        )
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store, polling_policy=polling
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        delays = []
        original = coordinator._reconnect_delay

        def recording_delay(attempt):
            delays.append(attempt)
            return original(attempt)

        coordinator._reconnect_delay = recording_delay
        started = time.monotonic()
        self.assertTrue(
            coordinator.start_database(
                descriptor.database_id, retry_initial_failure=retry_initial_failure
            )
        )
        return coordinator, descriptor, store, events, healthy, delays, started

    def test_backoff_steps_up_to_the_last_delay_and_every_attempt_is_counted(self):
        for label, factory in (
            (
                "catalog error",
                lambda n: DatabaseCatalogError(f"down {n}", retryable=True),
            ),
            ("os error", lambda n: OSError(f"socket {n}")),
        ):
            with self.subTest(label):
                coordinator, descriptor, store, events, healthy, delays, started = (
                    self.run_failures(factory, 6)
                )
                self.assertTrue(healthy.wait(5))
                elapsed = time.monotonic() - started
                self.assertEqual(delays, [0, 1, 2, 2, 2, 2])
                self.assertEqual(store.calls["start_session"], 7)
                self.assertEqual(
                    coordinator.metrics(descriptor.database_id).reconnect_count, 6
                )
                # Every retry really waited (the minimum delay is 50 ms).
                self.assertGreaterEqual(elapsed, 0.25)
                # The attempt counter restarts after a successful session.
                store.fail_once["heartbeat"] = factory(0)
                recovered = _state_signal(
                    events, descriptor.database_id, SynchronizationState.DISCONNECTED
                )
                self.assertTrue(recovered.wait(3))
                deadline = time.monotonic() + 3
                while len(delays) < 7 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(delays[6], 0)
                self.addCleanup(
                    lambda c=coordinator, d=descriptor: _stop_database(c, d.database_id)
                )

    def test_retryable_failures_continue_after_establishment_even_without_initial_retry(
        self,
    ):
        for label, factory in (
            ("catalog error", lambda: DatabaseCatalogError("lost", retryable=True)),
            ("os error", lambda: OSError("socket closed")),
        ):
            with self.subTest(label):
                store = _ScriptedStore()
                coordinator, descriptor, _store, events, _caps = (
                    self.threaded_coordinator(
                        store=store,
                        polling_policy=CollaborationPollingPolicy(
                            heartbeat_seconds=0.0,
                            inactive_database_seconds=0.05,
                            jitter_ratio=0.0,
                            reconnect_backoff_seconds=(0.05,),
                        ),
                    )
                )
                healthy = _state_signal(
                    events, descriptor.database_id, SynchronizationState.HEALTHY
                )
                self.assertTrue(
                    coordinator.start_database(
                        descriptor.database_id, retry_initial_failure=False
                    )
                )
                self.assertTrue(healthy.wait(3))
                store.fail_once["heartbeat"] = factory()
                deadline = time.monotonic() + 3
                while (
                    store.calls.get("start_session", 0) < 2
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                self.assertEqual(store.calls["start_session"], 2)
                self.assertEqual(
                    coordinator.metrics(descriptor.database_id).reconnect_count, 1
                )
                _stop_database(coordinator, descriptor.database_id)

    def test_initial_failures_without_retry_end_the_worker_without_counting_a_reconnect(
        self,
    ):
        for label, factory in (
            ("catalog error", lambda n: DatabaseCatalogError("down", retryable=True)),
            ("os error", lambda n: OSError("socket")),
        ):
            with self.subTest(label):
                coordinator, descriptor, store, events, healthy, delays, started = (
                    self.run_failures(factory, 1, retry_initial_failure=False)
                )
                runtime = coordinator._runtime(descriptor.database_id)
                runtime.thread.join(3)
                self.assertFalse(runtime.thread.is_alive())
                self.assertEqual(store.calls["start_session"], 1)
                self.assertEqual(delays, [])
                self.assertEqual(runtime.reconnect_count, 0)
                self.assertEqual(
                    coordinator.status(descriptor.database_id).state,
                    SynchronizationState.DISCONNECTED,
                )

    def test_non_retryable_failures_end_the_worker_in_the_state_their_flags_select(
        self,
    ):
        for label, error, state in (
            (
                "plain",
                DatabaseCatalogError("The database is missing."),
                SynchronizationState.DISCONNECTED,
            ),
            (
                "read only",
                DatabaseCatalogError("denied", read_only_required=True),
                SynchronizationState.READ_ONLY,
            ),
            (
                "credentials",
                DatabaseCatalogError("sign in", credential_required=True),
                SynchronizationState.CREDENTIAL_REQUIRED,
            ),
        ):
            with self.subTest(label):
                coordinator, descriptor, store, events, healthy, delays, started = (
                    self.run_failures(lambda n, error=error: error, 1)
                )
                runtime = coordinator._runtime(descriptor.database_id)
                runtime.thread.join(3)
                self.assertFalse(runtime.thread.is_alive())
                status = coordinator.status(descriptor.database_id)
                self.assertEqual((status.state, status.message), (state, str(error)))
                self.assertEqual(delays, [])
                self.assertEqual(runtime.reconnect_count, 0)
                self.assertEqual(store.calls["start_session"], 1)

    def test_failures_after_a_stop_request_are_not_treated_as_connection_loss(self):
        for label, error in (
            ("catalog error", DatabaseCatalogError("down", retryable=True)),
            ("os error", OSError("socket closed")),
        ):
            with self.subTest(label):
                store = _ScriptedStore()
                entered = threading.Event()
                release = threading.Event()

                def hold(error=error):
                    entered.set()
                    release.wait(5)
                    raise error

                store.script[("start_session", 1)] = hold
                coordinator, descriptor, _store, events, _caps = (
                    self.threaded_coordinator(store=store, register_cleanup=False)
                )
                self.assertTrue(coordinator.start_database(descriptor.database_id))
                self.assertTrue(entered.wait(2))
                runtime = coordinator._runtime(descriptor.database_id)
                results = []
                coordinator.stop_database_async(
                    descriptor.database_id,
                    callback=lambda *result: results.append(result),
                )
                release.set()
                runtime.thread.join(3)
                self.assertFalse(runtime.thread.is_alive())
                self.assertEqual(runtime.reconnect_count, 0)
                self.assertEqual(runtime.cleanup_errors, [])
                self.assertEqual(store.calls["start_session"], 1)
                deadline = time.monotonic() + 3
                while not results and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(results, [(True, "")])
                self.assertEqual(
                    [
                        payload["state"]
                        for payload in self.published(
                            coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                        )
                    ],
                    ["connecting", "read_only", "stopped"],
                )

    def test_worker_cleanup_failures_are_recorded_for_the_drain(self):
        coordinator, runtime = self.ready_coordinator(cleanup_success=False)
        runtime.stop_event.set()
        with patch.object(
            coordinator, "_reset_session", side_effect=RuntimeError("reset failed")
        ):
            coordinator._worker(runtime)
        self.assertEqual(
            runtime.cleanup_errors,
            ["The SQL collaboration worker could not complete session cleanup."],
        )
        coordinator2, runtime2 = self.ready_coordinator(cleanup_success=False)
        with (
            patch.object(
                coordinator2, "_run_worker", side_effect=RuntimeError("worker bug")
            ),
            patch.object(
                coordinator2,
                "_handle_worker_failure",
                side_effect=RuntimeError("handler bug"),
            ),
            self.assertLogs(
                "ost_visualizer.application.services.sql_collaboration_coordinator",
                level="ERROR",
            ),
        ):
            coordinator2._worker(runtime2)
        self.assertEqual(
            runtime2.cleanup_errors,
            ["The failed SQL collaboration worker could not reset its session."],
        )


class SqlCollaborationWorkerClockTests(_SecondPassBase):
    def run_with_fake_clock(self, store, *, dispatcher=None):
        clock = [1000.0]
        patcher = patch.object(time, "monotonic", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        polling = CollaborationPollingPolicy(
            heartbeat_seconds=0.0,
            inactive_database_seconds=0.05,
            jitter_ratio=0.0,
            reconnect_backoff_seconds=(0.05,),
        )
        coordinator, descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store, polling_policy=polling, dispatcher=dispatcher
        )
        return clock, coordinator, descriptor, events

    def wait_for_calls(self, store, name, count, timeout=3):
        # time.monotonic is replaced by the fake clock here: use the real timer.
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if store.calls.get(name, 0) >= count:
                return True
            time.sleep(0.01)
        return False

    def test_a_loop_gap_of_exactly_the_session_lifetime_is_not_a_suspension(self):
        store = _ScriptedStore()
        clock, coordinator, descriptor, events = self.run_with_fake_clock(store)
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(3))
        polls = store.calls["poll_changes"]
        clock[0] += COLLABORATION_STALE_SECONDS
        self.assertTrue(self.wait_for_calls(store, "poll_changes", polls + 3))
        self.assertEqual(store.calls["start_session"], 1)
        self.assertEqual(
            [
                payload["state"]
                for payload in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
                if payload["state"] == "disconnected"
            ],
            [],
        )
        # One tick beyond the lifetime is a suspension.
        polls = store.calls["poll_changes"]
        clock[0] += COLLABORATION_STALE_SECONDS + 0.5
        self.assertTrue(self.wait_for_calls(store, "start_session", 2))
        self.assertTrue(self.wait_for_calls(store, "poll_changes", polls + 2))
        self.assertEqual(
            [
                payload["message"]
                for payload in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
                if payload["state"] == "disconnected"
            ],
            ["The collaboration session expired while the computer was suspended."],
        )
        _stop_database(coordinator, descriptor.database_id)

    def test_a_long_wait_without_a_session_is_not_reported_as_a_suspension(self):
        store = _ScriptedStore()

        def failing_start():
            clock[0] += 5 * COLLABORATION_STALE_SECONDS
            raise DatabaseCatalogError("server unavailable", retryable=True)

        store.script[("start_session", 1)] = failing_start
        clock, coordinator, descriptor, events = self.run_with_fake_clock(store)
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(3))
        self.assertEqual(
            [
                payload["message"]
                for payload in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
                if payload["state"] == "disconnected"
            ],
            ["server unavailable"],
        )
        self.assertEqual(store.calls["start_session"], 2)
        _stop_database(coordinator, descriptor.database_id)

    def test_a_stop_requested_while_reporting_a_suspension_prevents_the_reconnect(self):
        store = _ScriptedStore()

        class _StoppingDispatcher(_Dispatcher):
            runtime = None

            def dispatch(self, callback, payload=()):
                callback(payload)
                if (
                    callback.__name__ == "_on_disconnected"
                    and "suspended" in payload[4]
                    and self.runtime is not None
                ):
                    self.runtime.stop_event.set()

        dispatcher = _StoppingDispatcher()
        clock, coordinator, descriptor, events = self.run_with_fake_clock(
            store, dispatcher=dispatcher
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(3))
        runtime = coordinator._runtime(descriptor.database_id)
        dispatcher.runtime = runtime
        clock[0] += COLLABORATION_STALE_SECONDS + 1
        runtime.thread.join(3)
        self.assertFalse(runtime.thread.is_alive())
        self.assertEqual(store.calls["start_session"], 1)
        _stop_database(coordinator, descriptor.database_id)


class SqlCollaborationWorkerPollingCadenceTests(_SecondPassBase):
    def test_poll_interval_follows_edit_selection_and_idle_state_with_jitter(self):
        import ost_visualizer.application.services.sql_collaboration_coordinator as module

        policy = CollaborationPollingPolicy(
            selected_database_seconds=2.0,
            active_edit_seconds=0.4,
            inactive_database_seconds=8.0,
            jitter_ratio=0.25,
        )
        coordinator, runtime = self.ready_coordinator(polling_policy=policy)
        for label, edit_depth, bid_uid, base in (
            ("editing", 1, 8, 0.4),
            ("selected database", 0, 8, 2.0),
            ("inactive database", 0, None, 8.0),
        ):
            with self.subTest(label):
                runtime.edit_depth = edit_depth
                runtime.bid_uid = bid_uid
                with patch.object(
                    module.random, "uniform", return_value=0.0
                ) as uniform:
                    self.assertEqual(coordinator._next_poll_interval(runtime), base)
                uniform.assert_called_once_with(-base * 0.25, base * 0.25)
                with patch.object(module.random, "uniform", return_value=base * 0.25):
                    self.assertAlmostEqual(
                        coordinator._next_poll_interval(runtime), base * 1.25
                    )
                with patch.object(module.random, "uniform", return_value=-base * 0.25):
                    self.assertAlmostEqual(
                        coordinator._next_poll_interval(runtime), base * 0.75
                    )
        # Very short intervals never go below 50 ms.
        quick = CollaborationPollingPolicy(
            inactive_database_seconds=0.01, jitter_ratio=0.0
        )
        coordinator, runtime = self.ready_coordinator(polling_policy=quick)
        runtime.bid_uid = None
        self.assertEqual(coordinator._next_poll_interval(runtime), 0.05)

    def test_reconnect_delay_uses_the_attempt_step_with_jitter_and_a_floor(self):
        import ost_visualizer.application.services.sql_collaboration_coordinator as module

        policy = CollaborationPollingPolicy(
            jitter_ratio=0.5, reconnect_backoff_seconds=(0.01, 2.0, 6.0)
        )
        coordinator, runtime = self.ready_coordinator(polling_policy=policy)
        for attempt, base in ((1, 2.0), (2, 6.0)):
            with patch.object(module.random, "uniform", return_value=0.0) as uniform:
                self.assertEqual(coordinator._reconnect_delay(attempt), base)
            uniform.assert_called_once_with(-base * 0.5, base * 0.5)
            with patch.object(module.random, "uniform", return_value=base * 0.5):
                self.assertAlmostEqual(
                    coordinator._reconnect_delay(attempt), base * 1.5
                )
            with patch.object(module.random, "uniform", return_value=-base * 0.5):
                self.assertAlmostEqual(
                    coordinator._reconnect_delay(attempt), base * 0.5
                )
        with patch.object(module.random, "uniform", return_value=0.0):
            self.assertEqual(coordinator._reconnect_delay(0), 0.05)

    def test_an_idle_healthy_worker_polls_at_the_configured_pace_and_announces_health_once(
        self,
    ):
        class _CountingProbe(_PermissionProbe):
            calls = 0

            def can_edit(self, _database_id):
                type(self).calls += 1
                return True

        store = _ScriptedStore()
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        probe = _CountingProbe()
        capabilities = DatabaseCapabilityService(descriptors, probe)
        capabilities.mark_connected(descriptor.database_id)
        _CountingProbe.calls = 0
        coordinator, _descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store, capabilities=capabilities, descriptor=descriptor
        )
        healthy = _state_signal(
            events, descriptor.database_id, SynchronizationState.HEALTHY
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        self.assertTrue(healthy.wait(3))
        time.sleep(0.4)
        # About eight 50 ms cycles ran; a busy loop would run thousands.
        self.assertGreaterEqual(store.calls["poll_changes"], 2)
        self.assertLess(store.calls["poll_changes"], 30)
        self.assertEqual(
            [
                payload["state"]
                for payload in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
            ].count("healthy"),
            1,
        )
        # Permissions are re-probed once per (re)connection, never per heartbeat.
        self.assertEqual(_CountingProbe.calls, 1)
        self.assertEqual(store.calls["start_session"], 1)
        _stop_database(coordinator, descriptor.database_id)

    def test_revoked_edit_permission_after_connecting_ends_the_worker_read_only(self):
        class _RevokedProbe(_PermissionProbe):
            allowed = True

            def can_edit(self, _database_id):
                return type(self).allowed

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        capabilities = DatabaseCapabilityService(descriptors, _RevokedProbe())
        capabilities.mark_connected(descriptor.database_id)
        _RevokedProbe.allowed = False
        store = _ScriptedStore()
        coordinator, _descriptor, _store, events, _caps = self.threaded_coordinator(
            store=store, capabilities=capabilities, descriptor=descriptor
        )
        self.assertTrue(coordinator.start_database(descriptor.database_id))
        runtime = coordinator._runtime(descriptor.database_id)
        runtime.thread.join(3)
        self.assertFalse(runtime.thread.is_alive())
        status = coordinator.status(descriptor.database_id)
        self.assertEqual(
            (status.state, status.message),
            (
                SynchronizationState.READ_ONLY,
                "SQL edit permissions or schema trust changed.",
            ),
        )
        self.assertTrue(store.closed.is_set())
        self.assertFalse(capabilities.is_editable(descriptor.database_id))
        self.assertNotIn(
            "healthy",
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                )
            ],
        )


class SqlCollaborationMutationProcessingTests(_SecondPassBase):
    def queued(self, coordinator, runtime, label, operation=None, **overrides):
        results = []
        request = _placement_request(runtime.database_id, label, **overrides)
        coordinator.queue_request(
            request,
            operation or (lambda: _committed_execution("501")),
            results.append,
        )
        return request, results

    def test_the_worker_leaves_queued_work_alone_until_the_runtime_is_ready(self):
        cases = (
            ("not healthy", lambda r: setattr(r, "healthy", False)),
            ("delivery pending", lambda r: setattr(r, "pending_delivery", True)),
            ("recovery requested", lambda r: setattr(r, "recovery_requested", True)),
            ("stopping", lambda r: r.stop_event.set()),
        )
        for label, change in cases:
            with self.subTest(label):
                coordinator, runtime = self.ready_coordinator()
                writes = []
                request, results = self.queued(
                    coordinator,
                    runtime,
                    "waiting",
                    lambda: writes.append("write") or _committed_execution("1"),
                )
                change(runtime)
                coordinator._process_mutation_requests(runtime)
                self.assertEqual((writes, results), ([], []))
                self.assertEqual(runtime.mutation_requests.qsize(), 1)
                self.assertEqual(
                    coordinator._pending_mutations.get(request.operation_id).state,
                    PendingMutationState.QUEUED,
                )

    def test_a_request_dequeued_while_the_runtime_stops_being_ready_is_cancelled(self):
        message = "SQL collaboration is not ready for editing."
        cases = (
            ("no session", lambda c, r: setattr(r, "session", None)),
            (
                "newer runtime generation",
                lambda c, r: setattr(r, "generation", r.generation + 1),
            ),
            ("not healthy", lambda c, r: setattr(r, "healthy", False)),
            ("delivery pending", lambda c, r: setattr(r, "pending_delivery", True)),
            ("recovery requested", lambda c, r: setattr(r, "recovery_requested", True)),
            ("stopping", lambda c, r: r.stop_event.set()),
            (
                "not editable",
                lambda c, r: c._capabilities.set_collaboration_state(
                    r.database_id, SynchronizationState.CATCHING_UP
                ),
            ),
        )
        for label, change in cases:
            with self.subTest(label):
                coordinator, runtime = self.ready_coordinator()
                writes = []
                states = []
                results = []
                request = _placement_request(runtime.database_id, "dequeued")

                def callback(result):
                    states.append(
                        coordinator._pending_mutations.get(request.operation_id).state
                    )
                    results.append(result)

                coordinator.queue_request(
                    request,
                    lambda: writes.append("write") or _committed_execution("1"),
                    callback,
                )
                original_get = runtime.mutation_requests.get_nowait

                def get_then_change(original_get=original_get, change=change):
                    queued = original_get()
                    change(coordinator, runtime)
                    return queued

                with patch.object(
                    runtime.mutation_requests, "get_nowait", side_effect=get_then_change
                ):
                    # The first guard must pass so the request is dequeued.
                    coordinator._process_mutation_requests(runtime)
                self.assertEqual(writes, [])
                # Never promoted to EXECUTING: the pending entry is still QUEUED
                # when the cancellation is delivered.
                self.assertEqual(states, [PendingMutationState.QUEUED])
                self.assertEqual(
                    [(r.outcome_status, r.message) for r in results],
                    [(MutationOutcomeStatus.CANCELLED_BEFORE_START, message)],
                )
                self.assertEqual(
                    coordinator._pending_mutations.for_database(runtime.database_id), ()
                )

    def test_a_cancelled_request_never_starts_executing(self):
        coordinator, runtime = self.ready_coordinator()
        states = []
        request = _placement_request(runtime.database_id, "cancelled-state")
        results = []

        def callback(result):
            states.append(
                coordinator._pending_mutations.get(request.operation_id).state
            )
            results.append(result)

        coordinator.queue_request(request, lambda: _committed_execution("1"), callback)
        runtime.command_event.clear()
        self.assertTrue(
            coordinator.cancel_queued_mutation(
                runtime.database_id, request.operation_id
            )
        )
        self.assertTrue(runtime.command_event.is_set())
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(states, [PendingMutationState.QUEUED])
        self.assertEqual(
            [r.message for r in results],
            ["The queued SQL mutation was cancelled before execution."],
        )
        self.assertEqual(
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_MUTATION_STATE_CHANGED
                )
            ],
            ["queued", "queued"],
        )

    def test_a_failed_journal_write_before_execution_fails_the_mutation_and_goes_read_only(
        self,
    ):
        journal = _FailingPendingOperationJournal(2)
        coordinator, runtime = self.ready_coordinator(journal=journal)
        writes = []
        request, results = self.queued(
            coordinator,
            runtime,
            "journal-before-execution",
            lambda: writes.append("write") or _committed_execution("1"),
        )
        with (
            self.assertRaises(DatabaseCatalogError) as failure,
            self.assertLogs(
                "ost_visualizer.application.services.sql_collaboration_coordinator",
                level="ERROR",
            ) as logged,
        ):
            coordinator._process_mutation_requests(runtime)
        self.assertTrue(failure.exception.read_only_required)
        self.assertEqual(
            str(failure.exception), "The SQL operation journal is unavailable."
        )
        self.assertEqual(
            [r.getMessage() for r in logged.records],
            [f"Could not persist SQL operation {request.operation_id} state executing"],
        )
        self.assertEqual(writes, [])
        self.assertEqual(
            [(r.outcome_status, r.message, r.commit_attempted) for r in results],
            [
                (
                    MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                    "The SQL operation journal could not record the mutation before execution.",
                    False,
                )
            ],
        )
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )

    def test_failed_journal_cleanup_is_logged_and_reported(self):
        class _FailingRemoveJournal(_PendingOperationJournal):
            def remove(self, operation_id):
                raise OSError("disk full")

        journal = _FailingRemoveJournal()
        coordinator, runtime = self.ready_coordinator(journal=journal)
        request, results = self.queued(coordinator, runtime, "remove-fails")
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logged:
            self.assertIs(
                coordinator._remove_operation_record(request.operation_id), False
            )
        self.assertEqual(
            [r.getMessage() for r in logged.records],
            [f"Could not remove SQL operation record {request.operation_id}"],
        )
        self.assertIs(
            coordinator._transition_operation_record(
                request, PendingMutationState.EXECUTING
            ),
            True,
        )
        self.assertEqual(
            journal.records[request.operation_id].state, PendingMutationState.EXECUTING
        )
        coordinator._operation_journal = _FailingPendingOperationJournal(1)
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ):
            self.assertIs(
                coordinator._transition_operation_record(
                    request, PendingMutationState.PROJECTING
                ),
                False,
            )
        coordinator._operation_journal = journal
        working = _PendingOperationJournal()
        coordinator._operation_journal = working
        working.save(PendingSqlOperationRecord.from_request(request))
        self.assertTrue(coordinator._remove_operation_record(request.operation_id))
        self.assertEqual(working.records, {})

    def test_an_invalid_edit_lease_conflicts_without_touching_the_lease_or_the_write(
        self,
    ):
        coordinator, runtime = self.ready_coordinator(store=_CollaborationStore())
        resource = ResourceRef("takeoff", "42", 8)
        lock = ResourceLock(runtime.database_id, resource, "lock-token")
        draft = coordinator._local_drafts.begin(
            draft_type="takeoffs_gesture",
            database_id=runtime.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="main-plan",
            affected_resources=(resource,),
            operation_id="gesture",
        )
        coordinator._local_drafts.activate(
            draft.draft_id, (lock,), runtime_generation=runtime.generation
        )
        handle = EditLeaseHandle(
            database_id=runtime.database_id,
            draft_id=draft.draft_id,
            runtime_generation=runtime.generation,
            operation_id="gesture",
            owning_surface="main-plan",
            resources=(resource,),
            locks=(lock,),
        )
        # The runtime never registered this lease as owned.
        writes = []
        results = []
        request = _placement_request(
            runtime.database_id,
            "bad-lease",
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            resources=(resource,),
            edit_lease_handle=handle,
        )
        coordinator.queue_request(
            request,
            lambda: writes.append("write") or _committed_execution(),
            results.append,
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(writes, [])
        self.assertEqual(
            [(r.outcome_status, r.message) for r in results],
            [
                (
                    MutationOutcomeStatus.CONFLICT,
                    "The geometry edit lease expired before the mutation started.",
                )
            ],
        )
        self.assertIsNotNone(coordinator._local_drafts.get(draft.draft_id))
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )

    def test_lease_validation_checks_every_ownership_property(self):
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
            operation_id="edit",
        )
        drafts.activate(
            draft.draft_id, (edited_lock, navigable_lock), runtime_generation=4
        )
        handle = EditLeaseHandle(
            database_id="database",
            draft_id=draft.draft_id,
            runtime_generation=4,
            operation_id="edit",
            owning_surface="condition-sidebar",
            resources=(edited, navigable),
            locks=(edited_lock, navigable_lock),
        )

        def runtime_for(draft_ids=True):
            runtime = _DatabaseRuntime("database", 4)
            runtime.owned_locks = {
                edited.lease_identity: edited_lock,
                navigable.lease_identity: navigable_lock,
            }
            if draft_ids:
                runtime.draft_ids[
                    frozenset((edited.lease_identity, navigable.lease_identity))
                ] = draft.draft_id
            return runtime

        request = QueuedMutationRequest(
            database_id="database",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE,
            owning_surface="condition-sidebar",
            resources=(navigable,),
            payload={},
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
            coordinator._validated_mutation_edit_lease(runtime_for(), queued, handle),
            drafts.get(draft.draft_id),
        )
        # The runtime's own draft index must agree with the handle.
        self.assertIsNone(
            coordinator._validated_mutation_edit_lease(
                runtime_for(False), queued, handle
            )
        )
        other_bid = ResourceRef("condition", "42", 9)
        for label, changed in {
            "resource Bid context": replace(handle, resources=(other_bid, navigable)),
            "lock order": replace(handle, locks=(navigable_lock, edited_lock)),
        }.items():
            with self.subTest(label):
                self.assertIsNone(
                    coordinator._validated_mutation_edit_lease(
                        runtime_for(), queued, changed
                    )
                )
        # A draft that is not (yet) ACTIVE cannot authorize a mutation.
        pending_draft = drafts.begin(
            draft_type="conditions_editor",
            database_id="database",
            bid_uid=9,
            page_uid=None,
            owning_surface="condition-sidebar",
            affected_resources=(ResourceRef("condition", "70", 9),),
            operation_id="pending",
        )
        pending_handle = EditLeaseHandle(
            database_id="database",
            draft_id=pending_draft.draft_id,
            runtime_generation=0,
            operation_id="pending",
            owning_surface="condition-sidebar",
            resources=(ResourceRef("condition", "70", 9),),
        )
        pending_runtime = _DatabaseRuntime("database", 0)
        pending_runtime.draft_ids[
            frozenset({ResourceRef("condition", "70", 9).lease_identity})
        ] = pending_draft.draft_id
        pending_queued = replace(
            queued,
            runtime_generation=0,
            resources=pending_handle.resources,
            typed_request=replace(
                request,
                resources=pending_handle.resources,
                edit_lease_handle=pending_handle,
            ),
            edit_lease_handle=pending_handle,
        )
        self.assertIsNone(
            coordinator._validated_mutation_edit_lease(
                pending_runtime, pending_queued, pending_handle
            )
        )

    def test_consuming_a_lease_leaves_unrelated_ownership_and_keeps_other_edits_active(
        self,
    ):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        first = ResourceRef("takeoff", "42", 8)
        second = ResourceRef("takeoff", "43", 8)
        grants = []
        coordinator.request_local_edit(runtime.database_id, (first,), grants.append)
        coordinator.request_local_edit(runtime.database_id, (second,), grants.append)
        coordinator._process_edit_requests(runtime)
        handle = grants[0].handle
        self.assertEqual(runtime.edit_depth, 2)
        session = runtime.session
        # A replaced lock token on the runtime must not be dropped by a stale handle.
        replaced = ResourceLock(runtime.database_id, first, "replacement-token")
        runtime.owned_locks[first.lease_identity] = replaced
        failure = coordinator._consume_mutation_edit_lease(runtime, session, handle, ())
        self.assertIsNone(failure)
        self.assertEqual(runtime.owned_locks[first.lease_identity], replaced)
        self.assertIn(second.lease_identity, runtime.owned_locks)
        self.assertEqual((runtime.edit_depth, runtime.mode), (1, PresenceMode.EDITING))
        # The lock of a consumed handle is not released a second time by the server.
        failure = coordinator._consume_mutation_edit_lease(
            runtime,
            session,
            grants[1].handle,
            (grants[1].handle.locks[0].lock_token.upper(),),
        )
        self.assertIsNone(failure)
        self.assertEqual((runtime.edit_depth, runtime.mode), (0, PresenceMode.VIEWING))
        self.assertEqual(
            store.released,
            [(runtime.database_id, session.session_id, "lock-token")],
        )
        # The depth never goes negative.
        coordinator._consume_mutation_edit_lease(runtime, session, handle, ())
        self.assertEqual(runtime.edit_depth, 0)

    def test_draft_and_lock_state_while_a_non_lease_mutation_runs(self):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        resource = ResourceRef("takeoffs_collection", "8", 8)
        dependency = ResourceRef("page", "20", 8)
        token = ConcurrencyToken((9).to_bytes(8, "big"))
        coordinator._concurrency_tokens._reader.resources = {resource: token}
        seen = []

        def operation():
            (draft,) = coordinator._local_drafts._drafts.values()
            seen.append(
                (
                    draft.draft_type,
                    draft.bid_uid,
                    draft.page_uid,
                    draft.owning_surface,
                    draft.affected_resources,
                    draft.dependency_resources,
                    draft.operation_id,
                    draft.state,
                    draft.leases,
                    draft.runtime_generation,
                    draft.base_tokens,
                    coordinator._sessions.lock_tokens(runtime.database_id, (resource,)),
                )
            )
            return _committed_execution("501")

        request, results = self.queued(
            coordinator,
            runtime,
            "draft-state",
            operation,
            resources=(resource,),
            dependency_resources=(dependency,),
            owning_surface="detached-plan",
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(
            seen,
            [
                (
                    "takeoffs_mutation",
                    8,
                    None,
                    "detached-plan",
                    (resource,),
                    (dependency,),
                    request.operation_id,
                    LocalDraftState.ACTIVE,
                    (ResourceLock(runtime.database_id, resource, "lock-token"),),
                    runtime.generation,
                    ((resource, token),),
                    ("lock-token",),
                )
            ],
        )
        self.assertEqual(
            [r.outcome_status for r in results], [MutationOutcomeStatus.COMMITTED]
        )

    def test_overlapping_local_draft_rejects_the_mutation(self):
        coordinator, runtime = self.ready_coordinator()
        resource = ResourceRef("takeoffs_collection", "8", 8)
        owner = coordinator._local_drafts.begin(
            draft_type="takeoffs_editor",
            database_id=runtime.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="other",
            affected_resources=(resource,),
        )
        writes = []
        request, results = self.queued(
            coordinator,
            runtime,
            "overlap",
            lambda: writes.append("write") or _committed_execution("1"),
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(writes, [])
        self.assertEqual(
            [(r.outcome_status, r.message) for r in results],
            [
                (
                    MutationOutcomeStatus.REJECTED,
                    "A local edit already owns one of the requested resources.",
                )
            ],
        )
        self.assertEqual(set(coordinator._local_drafts._drafts), {owner.draft_id})
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )

    def test_committed_result_without_an_authoritative_projection_goes_read_only(self):
        coordinator, runtime = self.ready_coordinator()
        request, results = self.queued(
            coordinator,
            runtime,
            "no-authoritative-result",
            lambda: MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            ),
        )
        with self.assertRaises(DatabaseCatalogError) as failure:
            coordinator._process_mutation_requests(runtime)
        self.assertTrue(failure.exception.read_only_required)
        self.assertEqual(
            str(failure.exception),
            "The SQL mutation committed without an authoritative projection result.",
        )
        self.assertEqual(
            [
                (r.outcome_status, r.created_resource_ids, r.commit_attempted)
                for r in results
            ],
            [(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED, ("501",), True)],
        )
        self.assertEqual(
            coordinator._pending_mutations.get(request.operation_id).state,
            PendingMutationState.RECOVERING,
        )

    def test_committed_result_rejected_by_its_validator_keeps_the_authoritative_result(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        results = []
        request = _placement_request(runtime.database_id, "validator")
        authoritative = AuthoritativeMutationResult(created_resource_ids=("501",))
        coordinator.queue_request(
            request,
            lambda: _committed_execution("501"),
            results.append,
            result_validator=lambda result: "The validator rejected the result.",
        )
        with self.assertRaises(DatabaseCatalogError) as failure:
            coordinator._process_mutation_requests(runtime)
        self.assertTrue(failure.exception.read_only_required)
        self.assertEqual(str(failure.exception), "The validator rejected the result.")
        self.assertEqual(
            [
                (
                    r.outcome_status,
                    r.message,
                    r.authoritative_result,
                    r.commit_attempted,
                )
                for r in results
            ],
            [
                (
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                    "The validator rejected the result.",
                    authoritative,
                    True,
                )
            ],
        )

    def test_committed_work_moves_through_projecting_and_wakes_the_worker_for_more(
        self,
    ):
        reconciliation = _DeferredProjectionReconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        observed = []
        request = _placement_request(runtime.database_id, "projecting")

        def callback(result):
            observed.append(
                (
                    result.outcome_status,
                    coordinator._pending_mutations.get(request.operation_id).state,
                )
            )

        coordinator.queue_request(
            request, lambda: _committed_execution("501"), callback
        )
        second, _ = self.queued(coordinator, runtime, "second-in-queue")
        runtime.command_event.clear()
        coordinator._process_mutation_requests(runtime)
        # The worker is woken because another request is still queued.
        self.assertTrue(runtime.command_event.is_set())
        self.assertEqual(
            coordinator._pending_mutations.get(request.operation_id).state,
            PendingMutationState.PROJECTING,
        )
        self.assertEqual(
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_MUTATION_STATE_CHANGED
                )
            ],
            ["queued", "queued", "executing", "projecting"],
        )
        reconciliation.token.complete(True)
        self.assertEqual(
            observed,
            [(MutationOutcomeStatus.COMMITTED, PendingMutationState.PROJECTING)],
        )
        runtime.mutation_requests.get_nowait()
        runtime.command_event.clear()
        # Nothing is queued any more: no wake-up request.
        self.assertTrue(runtime.mutation_requests.empty())
        coordinator._process_mutation_requests(runtime)
        self.assertFalse(runtime.command_event.is_set())

    def test_local_result_for_a_navigated_away_owner_is_a_projection_failure(self):
        class _NavigatedAway(_Reconciliation):
            def capture_navigation_owner(self, _database_id):
                return "owner"

            def navigation_owner_is_current(self, _database_id, owner):
                return False

        coordinator, runtime = self.ready_coordinator(reconciliation=_NavigatedAway())
        results = []
        authoritative = AuthoritativeMutationResult(created_resource_ids=("501",))
        result = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=str(uuid.uuid4()),
            created_resource_ids=("501",),
            authoritative_result=authoritative,
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(runtime.database_id, "epoch", 0, 1)
        )
        coordinator._apply_local_mutation_result(
            (results.append, result, hydrated, runtime.session_generation, "owner")
        )
        self.assertEqual(coordinator._reconciliation.batches, [])
        self.assertEqual(
            [(r.outcome_status, r.message, r.commit_attempted) for r in results],
            [
                (
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                    "The SQL mutation committed, but its local projection failed.",
                    True,
                )
            ],
        )
        self.assertIs(results[0].authoritative_result, authoritative)

    def test_takeoff_placement_projects_provisional_aliases_only_for_its_own_operation(
        self,
    ):
        reconciliation = _Reconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        for mutation_type, created, expected in (
            (CollaborationMutationType.TAKEOFF_PLACEMENT, ("501", "502"), 2),
            (CollaborationMutationType.PLAN_ITEMS_PASTE, ("501", "502"), None),
        ):
            with self.subTest(mutation_type=mutation_type):
                request = _placement_request(
                    runtime.database_id,
                    f"alias-{mutation_type.value}",
                    mutation_type=mutation_type,
                )
                coordinator._pending_mutations.begin(
                    request, runtime_generation=runtime.generation
                )
                result = QueuedMutationResult(
                    database_id=runtime.database_id,
                    runtime_generation=runtime.generation,
                    operation_id=request.operation_id,
                    created_resource_ids=created,
                    authoritative_result=AuthoritativeMutationResult(
                        created_resource_ids=created
                    ),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
                coordinator._apply_local_mutation_result(
                    (
                        lambda _result: None,
                        result,
                        HydratedDatabaseChangeBatch(
                            _batch(runtime.database_id, "e", 0, 1)
                        ),
                        runtime.session_generation,
                        None,
                    )
                )
                aliases = reconciliation.projection_barriers[
                    -1
                ].resource_uid_aliases_by_family
                if expected is None:
                    self.assertEqual(aliases, {})
                else:
                    self.assertEqual(
                        aliases,
                        {
                            "takeoffs": tuple(
                                queued_takeoff_preview_uid(request.operation_id, index)
                                for index in range(expected)
                            )
                        },
                    )
        # Without a pending entry (already finished) no alias is projected.
        orphan = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=str(uuid.uuid4()),
            created_resource_ids=("1",),
            authoritative_result=AuthoritativeMutationResult(
                created_resource_ids=("1",)
            ),
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        coordinator._apply_local_mutation_result(
            (
                lambda _result: None,
                orphan,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "e", 0, 1)),
                runtime.session_generation,
                None,
            )
        )
        self.assertEqual(
            reconciliation.projection_barriers[-1].resource_uid_aliases_by_family, {}
        )

    def test_a_stale_session_cannot_project_a_local_result(self):
        coordinator, runtime = self.ready_coordinator()
        results = []
        result = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=str(uuid.uuid4()),
            created_resource_ids=("501",),
            authoritative_result=AuthoritativeMutationResult(
                created_resource_ids=("501",)
            ),
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        coordinator._apply_local_mutation_result(
            (
                results.append,
                result,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "e", 0, 1)),
                runtime.session_generation + 1,
                None,
            )
        )
        self.assertEqual(coordinator._reconciliation.batches, [])
        self.assertEqual(
            [(r.outcome_status, r.message, r.created_resource_ids) for r in results],
            [
                (
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                    "The SQL mutation committed after its UI runtime changed.",
                    (),
                )
            ],
        )


class _NavigatedAwayReconciliation(_Reconciliation):
    """The Bid the batch was captured for is no longer the loaded one."""

    def capture_navigation_owner(self, _database_id):
        return "captured-owner"

    def navigation_owner_is_current(self, _database_id, _owner):
        return False


class SqlCollaborationSessionStartProjectionTests(_SecondPassBase):
    def started_payload(self, runtime, *, session_generation=None, owner=None):
        return (
            runtime.database_id,
            runtime.generation,
            (
                runtime.session_generation
                if session_generation is None
                else session_generation
            ),
            HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
            owner,
        )

    def test_a_stale_session_start_is_ignored_but_still_rechecks_the_mutation_drain(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        drained = []
        coordinator._mutation_drain_callbacks[runtime.database_id] = [
            lambda *result: drained.append(result)
        ]
        runtime.ready_event.clear()
        coordinator._on_session_started(
            self.started_payload(
                runtime, session_generation=runtime.session_generation + 1
            )
        )
        self.assertEqual(coordinator._reconciliation.batches, [])
        self.assertFalse(runtime.ready_event.is_set())
        self.assertEqual(coordinator._event_bus.published, [])
        self.assertEqual(drained, [(True, "")])

    def test_navigation_replaced_during_session_start_requests_recovery_and_releases_the_worker(
        self,
    ):
        reconciliation = _NavigatedAwayReconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        runtime.ready_event.clear()
        runtime.recovery_attempted = True
        coordinator._on_session_started(
            self.started_payload(runtime, owner="captured-owner")
        )
        reason = "Navigation replaced the loaded Bid while SQL session-start hydration was pending."
        self.assertEqual(reconciliation.batches, [])
        self.assertTrue(runtime.ready_event.is_set())
        self.assertTrue(runtime.recovery_requested)
        # The navigation replacement allows the controlled recovery to run again.
        self.assertFalse(runtime.recovery_attempted)
        self.assertEqual(
            [
                p["reason"]
                for p in self.published(
                    coordinator, AppEvents.FULL_RECONCILIATION_REQUIRED
                )
            ],
            [reason],
        )

    def test_recovered_operations_are_resolved_once_and_the_runtime_catches_up(self):
        coordinator, runtime = self.ready_coordinator()
        orphan_id = str(uuid.uuid4())
        runtime.recovered_operation_ids.add(orphan_id)
        runtime.recovered_operation_results[orphan_id] = DurableOperationResult(
            database_id=runtime.database_id, operation_id=orphan_id, found=False
        )
        runtime.healthy = True
        runtime.ready_event.clear()
        coordinator._on_session_started(self.started_payload(runtime))
        self.assertEqual(runtime.recovered_operation_ids, set())
        self.assertEqual(runtime.recovered_operation_results, {})
        self.assertTrue(runtime.ready_event.is_set())
        self.assertFalse(runtime.healthy)
        self.assertEqual(
            coordinator.status(runtime.database_id).state,
            SynchronizationState.CATCHING_UP,
        )
        self.assertEqual(len(coordinator._reconciliation.batches), 1)

    def test_a_malformed_recovered_result_is_reported_and_does_not_block_later_operations(
        self,
    ):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        dispatcher = _DelayedMutationDispatcher()
        coordinator, runtime = self.ready_coordinator(
            store=store, journal=journal, dispatcher=dispatcher
        )
        callbacks = {"bad": [], "good": []}
        requests = {}
        for name in ("bad", "good"):
            request = _placement_request(runtime.database_id, f"recovered-{name}")
            requests[name] = request
            coordinator._pending_mutations.begin(
                request, runtime_generation=runtime.generation
            )
            coordinator._pending_mutations.transition(
                request.operation_id, PendingMutationState.RECOVERING
            )
            journal.save(
                PendingSqlOperationRecord.from_request(
                    request, PendingMutationState.RECOVERING
                )
            )
            coordinator._uncertain_callbacks[request.operation_id] = (
                request,
                callbacks[name].append,
            )
        store.durable_results[requests["bad"].operation_id] = replace(
            _durable_result(requests["bad"], "1"),
            result_payload='{"value": 5, "value_available": true}',
        )
        store.durable_results[requests["good"].operation_id] = _durable_result(
            requests["good"], "502"
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(self.started_payload(runtime))
        # The malformed result is reported as such before anything is delivered.
        self.assertEqual(callbacks, {"bad": [], "good": []})
        self.assertEqual(
            [
                p["reason"]
                for p in self.published(
                    coordinator, AppEvents.FULL_RECONCILIATION_REQUIRED
                )
            ],
            ["A recovered SQL operation result was malformed."],
        )
        dispatcher.deliver_pending()
        self.assertEqual(
            [
                (r.outcome_status, r.message, r.commit_attempted, r.runtime_generation)
                for r in callbacks["bad"]
            ],
            [
                (
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                    "The committed SQL operation has no valid authoritative result.",
                    True,
                    runtime.generation,
                )
            ],
        )
        # The later operation was still processed (not skipped by the malformed
        # one). Its completion is downgraded because a controlled recovery is
        # already requested; it stays retained for the next recovery pass.
        self.assertEqual(
            [
                (r.outcome_status, r.message, r.created_resource_ids)
                for r in callbacks["good"]
            ],
            [
                (
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                    "The SQL runtime changed before the mutation completed.",
                    (),
                )
            ],
        )
        self.assertEqual(
            [
                p["state"]
                for p in self.published(
                    coordinator, AppEvents.COLLABORATION_MUTATION_STATE_CHANGED
                )
                if p["operation_id"] == requests["good"].operation_id
            ],
            ["projecting", "recovering"],
        )
        self.assertEqual(
            set(coordinator._uncertain_callbacks),
            {requests["bad"].operation_id, requests["good"].operation_id},
        )

    def test_recovery_trusts_neither_a_foreign_marker_type_nor_a_foreign_request_hash(
        self,
    ):
        for label, change in (
            (
                "mutation type",
                {"mutation_type": CollaborationMutationType.PLAN_GEOMETRY.value},
            ),
            ("request hash", {"request_hash": "e" * 64}),
        ):
            with self.subTest(label):
                store = _RecoverableProjectionStore()
                journal = _PendingOperationJournal()
                coordinator, runtime = self.ready_coordinator(
                    store=store, journal=journal
                )
                request = _placement_request(runtime.database_id, f"foreign-{label}")
                journal.save(PendingSqlOperationRecord.from_request(request))
                store.durable_results[request.operation_id] = replace(
                    _durable_result(request, "1"), **change
                )
                with self.assertRaises(DatabaseCatalogError) as failure:
                    coordinator._recover_journaled_operations(runtime)
                self.assertTrue(failure.exception.read_only_required)
        # Positive control: matching type and hash is accepted.
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        request = _placement_request(runtime.database_id, "matching")
        journal.save(PendingSqlOperationRecord.from_request(request))
        store.durable_results[request.operation_id] = _durable_result(request, "1")
        coordinator._recover_journaled_operations(runtime)
        self.assertEqual(runtime.recovered_operation_ids, {request.operation_id})

    def test_recovered_completion_requires_the_exact_request_and_session(self):
        coordinator, runtime = self.ready_coordinator()
        request = _placement_request(runtime.database_id, "recovered-exact")
        other = _placement_request(
            runtime.database_id, "recovered-exact", payload={"label": "other"}
        )
        results = []
        coordinator._uncertain_callbacks[request.operation_id] = (
            request,
            results.append,
        )
        result = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            message="did not commit",
        )
        # Same operation id, different request: not ours.
        coordinator._complete_recovered_mutation_request(
            (other, result, runtime.session_generation)
        )
        self.assertEqual(results, [])
        self.assertIn(request.operation_id, coordinator._uncertain_callbacks)
        # No retained callback at all.
        coordinator._complete_recovered_mutation_request(
            (
                other,
                replace(result, operation_id=str(uuid.uuid4())),
                runtime.session_generation,
            )
        )
        self.assertEqual(results, [])
        coordinator._complete_recovered_mutation_request(
            (request, result, runtime.session_generation)
        )
        self.assertEqual([r.message for r in results], ["did not commit"])
        self.assertNotIn(request.operation_id, coordinator._uncertain_callbacks)

    def test_recovered_result_parser_rejects_partial_nulls_and_empties(self):
        request = _placement_request("database", "parser")

        def parse(value):
            return SqlCollaborationCoordinator._recovered_authoritative_result(
                request,
                DurableOperationResult(
                    database_id="database",
                    operation_id=request.operation_id,
                    found=True,
                    mutation_type=request.mutation_type.value,
                    request_hash=request.request_hash,
                    result_format_version=1,
                    result_payload=json.dumps(
                        {"value": value, "value_available": True}
                    ),
                ),
            )

        for value in (
            ["501", None],
            ["501", ""],
            {
                "takeoff_uids": {"a": "1", "b": None},
                "annotation_uids": {},
                "condition_uids": {},
            },
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse(value))
        self.assertEqual(parse(["501", "502"]).created_resource_ids, ("501", "502"))
        self.assertEqual(
            parse(
                {
                    "takeoff_uids": {"a": "1", "b": "2"},
                    "annotation_uids": {},
                    "condition_uids": {},
                }
            ).created_resource_ids,
            ("1", "2"),
        )


class SqlCollaborationRemoteBatchProjectionTests(_SecondPassBase):
    def payload(self, runtime, *, session_generation=None, owner=None, version=12):
        return (
            runtime.database_id,
            runtime.generation,
            (
                runtime.session_generation
                if session_generation is None
                else session_generation
            ),
            HydratedDatabaseChangeBatch(
                _batch(runtime.database_id, "epoch", 1, version)
            ),
            owner,
        )

    def test_a_remote_batch_for_an_older_session_is_dropped(self):
        coordinator, runtime = self.ready_coordinator()
        coordinator._on_remote_batch(
            self.payload(runtime, session_generation=runtime.session_generation + 1)
        )
        self.assertEqual(coordinator._reconciliation.batches, [])
        self.assertEqual(coordinator._event_bus.published, [])

    def test_navigation_replaced_while_a_batch_is_pending_requests_recovery_without_applying(
        self,
    ):
        reconciliation = _NavigatedAwayReconciliation()
        coordinator, runtime = self.ready_coordinator(reconciliation=reconciliation)
        runtime.recovery_attempted = True
        coordinator._on_remote_batch(self.payload(runtime, owner="captured-owner"))
        self.assertEqual(reconciliation.batches, [])
        self.assertFalse(runtime.recovery_attempted)
        self.assertTrue(runtime.recovery_requested)
        self.assertEqual(
            [
                p["reason"]
                for p in self.published(
                    coordinator, AppEvents.FULL_RECONCILIATION_REQUIRED
                )
            ],
            ["Navigation replaced the loaded Bid while a SQL snapshot was pending."],
        )
        self.assertEqual(runtime.reconciliation_count, 0)

    def test_finishing_a_batch_measures_the_reconciliation_and_checks_trust(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.pending_delivery = True
        runtime.acknowledged_version = 7
        runtime.observed_high_water_version = 12
        started = time.perf_counter() - 2.0
        coordinator._finish_remote_batch(
            runtime.database_id,
            runtime.generation,
            runtime.session_generation,
            12,
            started,
            None,
            True,
        )
        self.assertEqual(runtime.reconciliation_count, 1)
        self.assertGreaterEqual(runtime.reconciliation_duration_seconds, 2.0)
        self.assertLess(runtime.reconciliation_duration_seconds, 30.0)
        self.assertEqual(runtime.acknowledged_version, 12)
        # A second batch accumulates instead of replacing the duration.
        coordinator._finish_remote_batch(
            runtime.database_id,
            runtime.generation,
            runtime.session_generation,
            12,
            time.perf_counter() - 3.0,
            None,
            True,
        )
        self.assertEqual(runtime.reconciliation_count, 2)
        self.assertGreaterEqual(runtime.reconciliation_duration_seconds, 5.0)

    def test_an_untrusted_batch_never_advances_the_checkpoint_or_wakes_the_worker(self):
        for label, change, expects_request in (
            (
                "conflicted",
                lambda c, r: c.enter_conflict(r.database_id, "conflict"),
                False,
            ),
            (
                "recovery already requested",
                lambda c, r: setattr(r, "recovery_requested", True),
                False,
            ),
        ):
            with self.subTest(label):
                coordinator, runtime = self.ready_coordinator()
                runtime.pending_delivery = True
                runtime.acknowledged_version = 7
                runtime.observed_high_water_version = 12
                change(coordinator, runtime)
                runtime.command_event.clear()
                runtime.mutation_requests.put_nowait(object())
                published = len(coordinator._event_bus.published)
                coordinator._finish_remote_batch(
                    runtime.database_id,
                    runtime.generation,
                    runtime.session_generation,
                    12,
                    time.perf_counter(),
                    None,
                    True,
                )
                self.assertEqual(runtime.acknowledged_version, 7)
                self.assertTrue(runtime.pending_delivery)
                self.assertFalse(runtime.healthy)
                self.assertFalse(runtime.command_event.is_set())
                self.assertEqual(len(coordinator._event_bus.published), published)
        # A conflicted runtime is already in controlled recovery: a failed
        # projection does not request a second one.
        coordinator, runtime = self.ready_coordinator()
        coordinator.enter_conflict(runtime.database_id, "conflict")
        published = len(coordinator._event_bus.published)
        coordinator._finish_remote_batch(
            runtime.database_id,
            runtime.generation,
            runtime.session_generation,
            12,
            time.perf_counter(),
            None,
            False,
        )
        self.assertEqual(
            self.published(coordinator, AppEvents.FULL_RECONCILIATION_REQUIRED), []
        )
        self.assertEqual(len(coordinator._event_bus.published), published)

    def test_a_late_batch_completion_from_an_older_session_changes_nothing(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.pending_delivery = True
        runtime.acknowledged_version = 7
        coordinator._finish_remote_batch(
            runtime.database_id,
            runtime.generation,
            runtime.session_generation + 1,
            12,
            time.perf_counter(),
            None,
            True,
        )
        self.assertEqual(
            (runtime.acknowledged_version, runtime.reconciliation_count), (7, 0)
        )
        self.assertTrue(runtime.pending_delivery)

    def test_recovery_requests_wake_the_worker_and_are_idempotent_per_session(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.command_event.clear()
        coordinator._on_reconciliation_required(
            (runtime.database_id, runtime.generation, "first")
        )
        self.assertTrue(runtime.command_event.is_set())
        self.assertTrue(runtime.recovery_requested and not runtime.recovery_ready)
        runtime.command_event.clear()
        coordinator._on_reconciliation_required(
            (runtime.database_id, runtime.generation, "second")
        )
        self.assertFalse(runtime.command_event.is_set())
        self.assertEqual(
            [
                p["reason"]
                for p in self.published(
                    coordinator, AppEvents.FULL_RECONCILIATION_REQUIRED
                )
            ],
            ["first"],
        )
        # An older runtime generation is ignored.
        other, other_runtime = self.ready_coordinator()
        other._on_reconciliation_required(
            (other_runtime.database_id, other_runtime.generation + 1, "stale")
        )
        self.assertFalse(other_runtime.recovery_requested)

    def test_session_scoped_recovery_requests_validate_the_session_and_navigation_flag(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        base = (
            runtime.database_id,
            runtime.generation,
            runtime.session_generation,
            "reason",
        )
        coordinator._on_session_reconciliation_required(
            (
                runtime.database_id,
                runtime.generation,
                runtime.session_generation + 1,
                "stale",
            )
        )
        self.assertFalse(runtime.recovery_requested)
        # An ordinary request keeps the attempt flag.
        runtime.recovery_attempted = True
        coordinator._on_session_reconciliation_required(base)
        self.assertTrue(runtime.recovery_attempted)
        self.assertTrue(runtime.recovery_requested)
        # A navigation replacement resets it only when no recovery is pending.
        other, other_runtime = self.ready_coordinator()
        other_runtime.recovery_attempted = True
        other._on_session_reconciliation_required(
            (
                other_runtime.database_id,
                other_runtime.generation,
                other_runtime.session_generation,
                "nav",
            ),
            navigation_replaced=True,
        )
        self.assertFalse(other_runtime.recovery_attempted)
        third, third_runtime = self.ready_coordinator()
        third_runtime.recovery_requested = True
        third_runtime.recovery_attempted = True
        third._on_session_reconciliation_required(
            (
                third_runtime.database_id,
                third_runtime.generation,
                third_runtime.session_generation,
                "nav",
            ),
            navigation_replaced=True,
        )
        self.assertTrue(third_runtime.recovery_attempted)


class SqlCollaborationSessionResetTests(_SecondPassBase):
    def test_reset_advances_the_session_generation_exactly_once_per_live_session(self):
        coordinator, runtime = self.ready_coordinator()
        before = runtime.session_generation
        runtime.ready_event.set()
        coordinator._reset_session(runtime)
        self.assertEqual(runtime.session_generation, before + 1)
        self.assertFalse(runtime.ready_event.is_set())
        coordinator._reset_session(runtime)
        self.assertEqual(runtime.session_generation, before + 1)

    def test_cleanup_failures_name_lock_and_session_problems_in_order(self):
        class _AllFailStore(_LockingStore):
            def release_lock(self, database_id, session_id, lock_token):
                raise DatabaseCatalogError("release failed")

            def close_session(self, database_id, session_id, reason):
                raise DatabaseCatalogError("close failed")

        coordinator, runtime = self.ready_coordinator(
            store=_AllFailStore(), cleanup_success=False
        )
        resources = (
            ResourceRef("condition", "42", 8),
            ResourceRef("condition", "43", 8),
        )
        for resource in resources:
            runtime.owned_locks[resource.lease_identity] = ResourceLock(
                runtime.database_id, resource, f"token-{resource.resource_id}"
            )
        coordinator._reset_session(runtime)
        self.assertEqual(
            runtime.cleanup_errors,
            [
                "A SQL collaboration edit lock could not be released.",
                "The SQL collaboration session could not be closed.",
            ],
        )

    def test_reset_clears_runtime_ownership_even_when_the_registry_names_another_session(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        resource = ResourceRef("condition", "42", 8)
        runtime.owned_locks[resource.lease_identity] = ResourceLock(
            runtime.database_id, resource, "token"
        )
        runtime.healthy = True
        coordinator._sessions.register_lock(runtime.database_id, resource, "token")
        coordinator._sessions.register(runtime.database_id, "another-session")
        coordinator._reset_session(runtime)
        self.assertFalse(runtime.healthy)
        self.assertEqual(
            coordinator._sessions.lock_tokens(runtime.database_id, (resource,)), ()
        )
        self.assertEqual(
            coordinator._sessions.get(runtime.database_id), "another-session"
        )

    def test_worker_failure_projects_the_state_for_the_failed_session_generation(self):
        coordinator, runtime = self.ready_coordinator()
        before = runtime.session_generation
        runtime.ready_event.set()
        coordinator._handle_worker_failure(
            runtime, "lost", SynchronizationState.READ_ONLY
        )
        status = coordinator.status(runtime.database_id)
        self.assertEqual(
            (status.state, status.message), (SynchronizationState.READ_ONLY, "lost")
        )
        self.assertFalse(runtime.ready_event.is_set())
        self.assertEqual(runtime.session_generation, before + 1)


class _RaisingAcquireStore(_LockingStore):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def acquire_locks(self, database_id, session_id, resources, operation_description):
        raise self.error


class SqlCollaborationEditProcessingTests(_SecondPassBase):
    def request(self, coordinator, runtime, *resources, results=None, **kwargs):
        results = results if results is not None else []
        coordinator.request_local_edit(
            runtime.database_id, tuple(resources), results.append, **kwargs
        )
        return results

    def test_any_owned_resource_denies_the_whole_request_and_later_requests_still_run(
        self,
    ):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        owned = ResourceRef("condition", "43", 8)
        free = ResourceRef("condition", "42", 8)
        other = ResourceRef("condition", "50", 8)
        runtime.owned_locks[owned.lease_identity] = ResourceLock(
            runtime.database_id, owned, "held"
        )
        first = self.request(coordinator, runtime, free, owned)
        second = self.request(coordinator, runtime, other)
        coordinator._process_edit_requests(runtime)
        self.assertEqual(
            first,
            [
                EditLeaseResult(
                    False, "One of the requested resources is already being edited."
                )
            ],
        )
        self.assertTrue(second[0].granted)
        self.assertEqual(
            set(runtime.owned_locks), {owned.lease_identity, other.lease_identity}
        )
        self.assertEqual(store.released, [])

    def test_granted_edit_registers_its_locks_and_enters_editing_mode(self):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        first = ResourceRef("condition", "42", 8)
        second = ResourceRef("condition", "43", 8)
        grants = self.request(coordinator, runtime, first)
        more = self.request(coordinator, runtime, second)
        coordinator._process_edit_requests(runtime)
        handles = [grants[0].handle, more[0].handle]
        self.assertEqual(runtime.edit_depth, 2)
        self.assertEqual(runtime.mode, PresenceMode.EDITING)
        for handle, resource in zip(handles, (first, second)):
            self.assertEqual(
                coordinator._sessions.lock_tokens(runtime.database_id, (resource,)),
                ("lock-token",),
            )
            self.assertEqual(handle.runtime_generation, runtime.generation)
            self.assertEqual(
                handle.locks,
                (ResourceLock(runtime.database_id, resource, "lock-token"),),
            )
            draft = coordinator._local_drafts.get(handle.draft_id)
            self.assertEqual(
                (draft.state, draft.leases, draft.runtime_generation),
                (LocalDraftState.ACTIVE, handle.locks, runtime.generation),
            )
        self.assertEqual(
            runtime.draft_ids,
            {
                frozenset({first.lease_identity}): handles[0].draft_id,
                frozenset({second.lease_identity}): handles[1].draft_id,
            },
        )
        # Releasing one edit keeps the session in editing mode until the last ends.
        coordinator.end_edit_lease(handles[0])
        coordinator._process_release_requests(runtime)
        self.assertEqual((runtime.edit_depth, runtime.mode), (1, PresenceMode.EDITING))
        coordinator.end_edit_lease(handles[1])
        coordinator._process_release_requests(runtime)
        self.assertEqual((runtime.edit_depth, runtime.mode), (0, PresenceMode.VIEWING))

    def test_base_tokens_cover_the_requested_resources_and_dependencies_are_loaded(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        page = ResourceRef("page", "20", 8)
        dependency = ResourceRef("takeoffs_collection", "9", 9)
        page_token = ConcurrencyToken((3).to_bytes(8, "big"))
        dependency_token = ConcurrencyToken((4).to_bytes(8, "big"))
        coordinator._concurrency_tokens._reader.resources = {
            page: page_token,
            dependency: dependency_token,
        }
        grants = self.request(
            coordinator, runtime, page, dependency_resources=(dependency,)
        )
        coordinator._process_edit_requests(runtime)
        draft = coordinator._local_drafts.get(grants[0].handle.draft_id)
        # Both Bids were loaded; only the edited resource is pinned as a base token.
        self.assertEqual(draft.base_tokens, ((page, page_token),))
        self.assertEqual(
            coordinator._concurrency_tokens.tokens_for_resources(
                runtime.database_id, (page, dependency)
            ),
            ((page, page_token), (dependency, dependency_token)),
        )

    def test_denials_end_the_worker_only_for_session_level_errors(self):
        resource = ResourceRef("condition", "42", 8)
        plain = DatabaseCatalogError("another editor holds it")
        for label, error, fatal in (
            ("plain refusal", plain, False),
            ("retryable", DatabaseCatalogError("lost", retryable=True), True),
            (
                "session expired",
                DatabaseCatalogError("expired", session_expired=True),
                True,
            ),
            (
                "credentials",
                DatabaseCatalogError("sign in", credential_required=True),
                True,
            ),
            (
                "read only",
                DatabaseCatalogError("denied", read_only_required=True),
                True,
            ),
            ("os error", OSError("socket closed"), True),
            ("value error", ValueError("bad lock request"), False),
        ):
            with self.subTest(label):
                coordinator, runtime = self.ready_coordinator(
                    store=_RaisingAcquireStore(error)
                )
                first = self.request(coordinator, runtime, resource)
                second = self.request(
                    coordinator, runtime, ResourceRef("condition", "43", 8)
                )
                if fatal:
                    with self.assertRaises(type(error)) as raised:
                        coordinator._process_edit_requests(runtime)
                    self.assertIs(raised.exception, error)
                    # Only the failing request was consumed; the next one waits.
                    self.assertEqual(runtime.edit_requests.qsize(), 1)
                    self.assertEqual(second, [])
                else:
                    coordinator._process_edit_requests(runtime)
                    self.assertEqual(second, [EditLeaseResult(False, str(error))])
                    self.assertTrue(runtime.edit_requests.empty())
                self.assertEqual(first, [EditLeaseResult(False, str(error))])
                self.assertEqual(
                    [
                        d.affected_resources
                        for d in coordinator._local_drafts._drafts.values()
                    ],
                    [(ResourceRef("condition", "43", 8),)] if fatal else [],
                )

    def test_a_draft_cancelled_during_acquisition_releases_the_acquired_locks(self):
        for label, finish_before_activation in (
            ("before activation", True),
            ("after activation", False),
        ):
            with self.subTest(label):
                store = _LockingStore()
                coordinator, runtime = self.ready_coordinator(store=store)
                first = self.request(
                    coordinator, runtime, ResourceRef("condition", "42", 8)
                )
                second = self.request(
                    coordinator, runtime, ResourceRef("condition", "43", 8)
                )
                draft_id = tuple(runtime.edit_requests.queue)[0][0].draft_id
                if finish_before_activation:
                    original = store.acquire_locks

                    def acquire(*args, original=original):
                        locks = original(*args)
                        coordinator._local_drafts.finish(draft_id)
                        return locks

                    store.acquire_locks = acquire
                    expected = "The local draft is no longer active"
                else:
                    original_activate = coordinator._local_drafts.activate

                    def activate(*args, **kwargs):
                        original_activate(*args, **kwargs)
                        coordinator._local_drafts.finish(draft_id)

                    coordinator._local_drafts.activate = activate
                    expected = (
                        "The local edit was cancelled before its lease became active."
                    )
                coordinator._process_edit_requests(runtime)
                self.assertEqual(first, [EditLeaseResult(False, expected)])
                self.assertEqual(
                    store.released[:1],
                    [(runtime.database_id, runtime.session.session_id, "lock-token")],
                )
                self.assertNotIn(
                    ResourceRef("condition", "42", 8).lease_identity,
                    runtime.owned_locks,
                )
                # The loop moved on to, and granted, the next queued request.
                self.assertTrue(second[0].granted)
                self.assertEqual(runtime.edit_depth, 1)

    def test_denied_edit_attempts_every_release_and_reports_the_first_failure(self):
        class _FailingReleaseStore(_LockingStore):
            def release_lock(self, database_id, session_id, lock_token):
                super().release_lock(database_id, session_id, lock_token)
                raise DatabaseCatalogError(f"release failed for {lock_token}")

        store = _FailingReleaseStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        resources = (
            ResourceRef("condition", "42", 8),
            ResourceRef("condition", "43", 8),
        )
        locks = [
            ResourceLock(runtime.database_id, r, f"token-{r.resource_id}")
            for r in resources
        ]
        results = []
        draft = coordinator._local_drafts.begin(
            draft_type="conditions_editor",
            database_id=runtime.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="desktop",
            affected_resources=resources,
        )
        request = replace_edit_request(runtime, draft, resources)
        with self.assertRaises(DatabaseCatalogError) as failure:
            coordinator._deny_edit_request(
                request,
                draft.draft_id,
                results.append,
                runtime.session,
                locks,
                "denied",
            )
        self.assertEqual(str(failure.exception), "release failed for token-42")
        self.assertEqual(
            store.released,
            [
                (runtime.database_id, runtime.session.session_id, "token-42"),
                (runtime.database_id, runtime.session.session_id, "token-43"),
            ],
        )
        self.assertEqual(results, [EditLeaseResult(False, "denied")])
        self.assertIsNone(coordinator._local_drafts.get(draft.draft_id))
        # Without a failing release nothing is raised.
        coordinator._store = _LockingStore()
        draft = coordinator._local_drafts.begin(
            draft_type="conditions_editor",
            database_id=runtime.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="desktop",
            affected_resources=resources,
        )
        coordinator._deny_edit_request(
            replace_edit_request(runtime, draft, resources),
            draft.draft_id,
            results.append,
            runtime.session,
            locks,
            "denied again",
        )
        self.assertEqual(results[-1], EditLeaseResult(False, "denied again"))


def replace_edit_request(runtime, draft, resources):
    return EditLeaseRequest(
        database_id=runtime.database_id,
        draft_id=draft.draft_id,
        operation_id=draft.operation_id,
        owning_surface=draft.owning_surface,
        resources=resources,
    )


class SqlCollaborationReleaseProcessingTests(_SecondPassBase):
    def active_lease(self, store=None):
        coordinator, runtime = self.ready_coordinator(store=store)
        resource = ResourceRef("condition", "42", 8)
        grants = []
        coordinator.request_local_edit(
            runtime.database_id,
            (resource,),
            grants.append,
            operation_id="edit-42",
            owning_surface="condition-sidebar",
        )
        coordinator._process_edit_requests(runtime)
        return coordinator, runtime, resource, grants[0].handle

    def test_only_the_exact_handle_releases_and_later_valid_handles_still_run(self):
        variants = {
            "handle runtime generation": lambda h, c, r: replace(
                h, runtime_generation=h.runtime_generation + 1
            ),
            "database": lambda h, c, r: replace(h, database_id="another-database"),
            "operation": lambda h, c, r: replace(h, operation_id="another-operation"),
            "surface": lambda h, c, r: replace(h, owning_surface="detached-plan"),
            "resource Bid context": lambda h, c, r: replace(
                h, resources=(ResourceRef("condition", "42", 9),)
            ),
            "dependencies": lambda h, c, r: replace(
                h, dependency_resources=(ResourceRef("page", "20", 8),)
            ),
            "lock token": lambda h, c, r: replace(
                h, locks=(replace(h.locks[0], lock_token="other-token"),)
            ),
            "lock database": lambda h, c, r: replace(
                h, locks=(replace(h.locks[0], database_id="another-database"),)
            ),
            "unknown draft": lambda h, c, r: replace(h, draft_id="missing-draft"),
            "draft activated for another generation": lambda h, c, r: (
                c._local_drafts.activate(
                    h.draft_id, h.locks, runtime_generation=r.generation - 1
                )
                or h
            ),
        }
        for label, forge in variants.items():
            with self.subTest(label):
                store = _LockingStore()
                coordinator, runtime, resource, handle = self.active_lease(store)
                forged = forge(handle, coordinator, runtime)
                runtime.release_requests.put(forged)
                coordinator._process_release_requests(runtime)
                # The forged handle alone releases nothing and changes nothing.
                self.assertEqual(store.released, [])
                self.assertEqual(set(runtime.owned_locks), {resource.lease_identity})
                self.assertEqual(runtime.edit_depth, 1)
                self.assertTrue(runtime.release_requests.empty())
        # A valid handle queued behind forged ones is still served.
        store = _LockingStore()
        coordinator, runtime, resource, handle = self.active_lease(store)
        runtime.release_requests.put(replace(handle, database_id="another-database"))
        runtime.release_requests.put(handle)
        coordinator._process_release_requests(runtime)
        self.assertEqual(
            store.released,
            [(runtime.database_id, runtime.session.session_id, "lock-token")],
        )
        self.assertEqual(runtime.owned_locks, {})

    def test_a_handle_from_another_runtime_generation_is_ignored_even_when_its_draft_matches(
        self,
    ):
        store = _LockingStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        resource = ResourceRef("condition", "42", 8)
        lock = ResourceLock(runtime.database_id, resource, "held")
        draft = coordinator._local_drafts.begin(
            draft_type="conditions_editor",
            database_id=runtime.database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="desktop",
            affected_resources=(resource,),
            operation_id="edit",
        )
        old_generation = runtime.generation - 1
        coordinator._local_drafts.activate(
            draft.draft_id, (lock,), runtime_generation=old_generation
        )
        runtime.owned_locks[resource.lease_identity] = lock
        runtime.draft_ids[frozenset({resource.lease_identity})] = draft.draft_id
        handle = EditLeaseHandle(
            database_id=runtime.database_id,
            draft_id=draft.draft_id,
            runtime_generation=old_generation,
            operation_id="edit",
            owning_surface="desktop",
            resources=(resource,),
            locks=(lock,),
        )
        runtime.release_requests.put(handle)
        coordinator._process_release_requests(runtime)
        self.assertEqual(store.released, [])
        self.assertIsNotNone(coordinator._local_drafts.get(draft.draft_id))
        self.assertEqual(runtime.owned_locks, {resource.lease_identity: lock})

    def test_a_handle_for_a_superseded_draft_does_not_release_the_newer_owner(self):
        store = _LockingStore()
        coordinator, runtime, resource, handle = self.active_lease(store)
        runtime.draft_ids[frozenset({resource.lease_identity})] = "newer-draft"
        runtime.release_requests.put(handle)
        coordinator._process_release_requests(runtime)
        self.assertEqual(store.released, [])
        self.assertEqual(
            runtime.draft_ids, {frozenset({resource.lease_identity}): "newer-draft"}
        )
        self.assertIsNotNone(coordinator._local_drafts.get(handle.draft_id))

    def test_release_without_a_session_finishes_the_draft_without_store_calls(self):
        store = _LockingStore()
        coordinator, runtime, resource, handle = self.active_lease(store)
        runtime.session = None
        runtime.release_requests.put(handle)
        coordinator._process_release_requests(runtime)
        self.assertEqual(store.released, [])
        self.assertIsNone(coordinator._local_drafts.get(handle.draft_id))
        self.assertEqual(runtime.owned_locks, {})
        self.assertEqual(runtime.draft_ids, {})

    def test_release_requests_stop_being_served_once_the_runtime_is_stopping(self):
        store = _LockingStore()
        coordinator, runtime, resource, handle = self.active_lease(store)
        runtime.release_requests.put(handle)
        runtime.stop_event.set()
        coordinator._process_release_requests(runtime)
        self.assertEqual(store.released, [])
        self.assertEqual(runtime.release_requests.qsize(), 1)

    def test_end_edit_lease_queues_for_the_exact_runtime_only_and_wakes_the_worker(
        self,
    ):
        coordinator, runtime, resource, handle = self.active_lease()
        runtime.command_event.clear()
        coordinator.end_edit_lease(handle)
        self.assertEqual(runtime.release_requests.qsize(), 1)
        self.assertTrue(runtime.command_event.is_set())
        # A handle from another generation, or for another database, has no owner.
        runtime.command_event.clear()
        coordinator.end_edit_lease(
            replace(handle, runtime_generation=handle.runtime_generation + 1)
        )
        coordinator.end_edit_lease(replace(handle, database_id="not-open"))
        self.assertEqual(runtime.release_requests.qsize(), 1)
        self.assertFalse(runtime.command_event.is_set())

    def test_discard_local_draft_releases_the_lease_of_exactly_that_database(self):
        store = _LockingStore()
        coordinator, runtime, resource, handle = self.active_lease(store)
        coordinator.discard_local_draft("another-database", handle.draft_id)
        coordinator.discard_local_draft(runtime.database_id, "unknown-draft")
        self.assertTrue(runtime.release_requests.empty())
        runtime.command_event.clear()
        coordinator.discard_local_draft(runtime.database_id, handle.draft_id)
        self.assertEqual(runtime.release_requests.qsize(), 1)
        queued = runtime.release_requests.queue[0]
        self.assertEqual(queued, handle)
        self.assertTrue(runtime.command_event.is_set())
        coordinator._process_release_requests(runtime)
        self.assertEqual(
            store.released,
            [(runtime.database_id, runtime.session.session_id, "lock-token")],
        )
        self.assertIsNone(coordinator._local_drafts.get(handle.draft_id))

    def test_runtime_lease_delivery_requires_a_live_draft_and_a_running_coordinator(
        self,
    ):
        coordinator, runtime, resource, handle = self.active_lease()
        delivered = []
        grant = EditLeaseResult(True, handle=handle)

        def deliver(result, draft_id=handle.draft_id, generation=runtime.generation):
            coordinator._complete_runtime_lease_request(
                (runtime.database_id, generation, draft_id, delivered.append, result)
            )

        deliver(grant)
        self.assertEqual(delivered, [grant])
        # Shutting down: the grant is replaced by a denial.
        coordinator._shutting_down = True
        deliver(grant)
        coordinator._shutting_down = False
        self.assertEqual(
            delivered[1],
            EditLeaseResult(
                False, "SQL collaboration stopped before the edit lease became active."
            ),
        )
        # A draft that is no longer the runtime's active draft is denied as well.
        deliver(grant, draft_id="unknown-draft")
        self.assertFalse(delivered[2].granted)
        # Another runtime generation: denied.
        deliver(grant, generation=runtime.generation + 1)
        self.assertFalse(delivered[3].granted)
        # Denials pass through unchanged, whether or not the draft is active.
        denial = EditLeaseResult(False, "someone else is editing")
        deliver(denial, draft_id="unknown-draft")
        deliver(denial)
        self.assertEqual(delivered[4:], [denial, denial])


class SqlCollaborationHeartbeatTests(_SecondPassBase):
    def test_heartbeat_without_a_session_does_nothing(self):
        store = _CollaborationStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        runtime.session = None
        with patch.object(store, "heartbeat") as heartbeat:
            coordinator._heartbeat(runtime)
        heartbeat.assert_not_called()
        self.assertEqual(coordinator._event_bus.published, [])

    def test_heartbeat_republishes_renewed_leases_and_replaces_the_session(self):
        state = _FakeSqlServerState()
        store = _ServerBackedStore(state)
        coordinator, runtime = self.ready_coordinator(store=store)
        resource = ResourceRef("takeoff", "7", 8)
        grants = []
        coordinator.request_local_edit(runtime.database_id, (resource,), grants.append)
        coordinator._process_edit_requests(runtime)
        lock = grants[0].handle.locks[0]
        coordinator._sessions.remove_lock(runtime.database_id, resource)
        runtime.owned_locks.clear()
        runtime.owned_locks[("stale", "entry")] = lock
        previous_session = runtime.session
        coordinator._heartbeat(runtime)
        self.assertIsNot(runtime.session, previous_session)
        # Renewal restores the registry token and keys the lease by its resource.
        self.assertEqual(
            coordinator._sessions.lock_tokens(runtime.database_id, (resource,)),
            (lock.lock_token,),
        )
        self.assertEqual(runtime.owned_locks[resource.lease_identity], lock)
        # Without any owned lock nothing is re-registered.
        other, other_runtime = self.ready_coordinator(store=_ServerBackedStore(state))
        other._heartbeat(other_runtime)
        self.assertEqual(other_runtime.owned_locks, {})
        self.assertEqual(other._store.renewals, [])

    def test_presence_is_published_only_for_the_current_session(self):
        coordinator, runtime = self.ready_coordinator()
        runtime.bid_uid = 8
        coordinator._heartbeat(runtime)
        (payload,) = self.published(coordinator, AppEvents.PRESENCE_CHANGED)
        self.assertEqual(
            payload, {"database_id": runtime.database_id, "bid_uid": "8", "users": []}
        )
        for stale in (
            (
                runtime.database_id,
                runtime.generation,
                runtime.session_generation + 1,
                "8",
                (),
            ),
            (
                runtime.database_id,
                runtime.generation + 1,
                runtime.session_generation,
                "8",
                (),
            ),
            (
                "another-database",
                runtime.generation,
                runtime.session_generation,
                "8",
                (),
            ),
        ):
            coordinator._publish_presence(stale)
        self.assertEqual(
            len(self.published(coordinator, AppEvents.PRESENCE_CHANGED)), 1
        )
        # Without a Bid no presence is requested at all.
        runtime.bid_uid = None
        coordinator._heartbeat(runtime)
        self.assertEqual(
            len(self.published(coordinator, AppEvents.PRESENCE_CHANGED)), 1
        )


class SqlCollaborationLockPollingTests(_SecondPassBase):
    def test_foreign_locks_are_published_once_and_conflicts_are_kept(self):
        state = _FakeSqlServerState()
        store = _ServerBackedStore(state)
        coordinator, runtime = self.ready_coordinator(store=store)
        database_id = runtime.database_id
        state.start("other-client")
        in_bid = ResourceRef("condition", "42", 8)
        elsewhere = ResourceRef("condition", "50", 9)
        state.acquire("other-client", (in_bid, elsewhere))
        conflict = ResourceRef("condition", "7", 8)
        coordinator._capabilities.add_collaboration_conflict(database_id, conflict)
        runtime.bid_uid = 8
        coordinator._event_bus.published.clear()
        coordinator._poll_locks(runtime)
        status = coordinator.status(database_id)
        self.assertEqual(status.locked_resources, frozenset({in_bid}))
        self.assertEqual(status.conflicted_resources, frozenset({conflict}))
        self.assertEqual(
            coordinator._event_bus.published,
            [(AppEvents.DATABASE_CAPABILITIES_CHANGED, {"file_path": database_id})],
        )
        # Unchanged locks publish nothing more.
        coordinator._poll_locks(runtime)
        self.assertEqual(len(coordinator._event_bus.published), 1)
        # Without a Bid context every foreign lock is reported.
        runtime.bid_uid = None
        coordinator._poll_locks(runtime)
        self.assertEqual(
            coordinator.status(database_id).locked_resources,
            frozenset({in_bid, elsewhere}),
        )
        self.assertEqual(len(coordinator._event_bus.published), 2)
        # The session's own locks are never reported as foreign.
        own = ResourceRef("condition", "60", 8)
        state.acquire(runtime.session.session_id, (own,))
        coordinator._poll_locks(runtime)
        self.assertEqual(
            coordinator.status(database_id).locked_resources,
            frozenset({in_bid, elsewhere}),
        )

    def test_lock_polling_ignores_a_missing_session_and_stale_deliveries(self):
        store = _CollaborationStore()
        coordinator, runtime = self.ready_coordinator(store=store)
        session, runtime.session = runtime.session, None
        with patch.object(store, "list_locks") as list_locks:
            coordinator._poll_locks(runtime)
        list_locks.assert_not_called()
        runtime.session = session
        resource = frozenset({ResourceRef("condition", "42", 8)})
        for stale in (
            (
                runtime.database_id,
                runtime.generation,
                runtime.session_generation + 1,
                resource,
            ),
            (
                runtime.database_id,
                runtime.generation + 1,
                runtime.session_generation,
                resource,
            ),
            (
                "another-database",
                runtime.generation,
                runtime.session_generation,
                resource,
            ),
        ):
            coordinator._publish_capability_change(stale)
        self.assertEqual(
            coordinator.status(runtime.database_id).locked_resources, frozenset()
        )
        self.assertEqual(coordinator._event_bus.published, [])

    def test_disconnect_and_restore_notifications_require_the_current_session(self):
        coordinator, runtime = self.ready_coordinator()
        database_id = runtime.database_id
        coordinator._on_disconnected(
            (
                database_id,
                runtime.generation,
                runtime.session_generation + 1,
                SynchronizationState.DISCONNECTED,
                "old session",
            )
        )
        coordinator._on_connection_restored(
            (database_id, runtime.generation + 1, runtime.session_generation)
        )
        self.assertEqual(coordinator._event_bus.published, [])
        self.assertEqual(
            coordinator.status(database_id).state, SynchronizationState.HEALTHY
        )
        coordinator._on_disconnected(
            (
                database_id,
                runtime.generation,
                runtime.session_generation,
                SynchronizationState.DISCONNECTED,
                "current session",
            )
        )
        status = coordinator.status(database_id)
        self.assertEqual(
            (status.state, status.message),
            (SynchronizationState.DISCONNECTED, "current session"),
        )
        coordinator._on_connection_restored(
            (database_id, runtime.generation, runtime.session_generation)
        )
        self.assertEqual(
            coordinator.status(database_id).state, SynchronizationState.HEALTHY
        )

    def test_runtime_currency_follows_the_registered_generation(self):
        coordinator, runtime = self.ready_coordinator()
        self.assertIs(
            coordinator.is_runtime_current(runtime.database_id, runtime.generation),
            True,
        )
        self.assertIs(
            coordinator.is_runtime_current(runtime.database_id, runtime.generation + 1),
            False,
        )
        self.assertIs(
            coordinator.is_runtime_current("another-database", runtime.generation),
            False,
        )


# --- D12 pin: deadlock victim / lock timeout / snapshot conflict -----------------
from ost_visualizer.domain.entities.database_descriptor import (  # noqa: E402
    SqlServerDatabaseLocation as _ConflictPinLocation,
)
from ost_visualizer.infrastructure.sql.collaboration_store import (  # noqa: E402
    SqlCollaborationStore as _ConflictPinSqlStore,
)
from ost_visualizer.infrastructure.sql.connection_manager import (  # noqa: E402
    SqlConnectionRequest as _ConflictPinConnectionRequest,
)
from ost_visualizer.infrastructure.sql.errors import (  # noqa: E402
    SqlInfrastructureError as _ConflictPinInfrastructureError,
    classify_pyodbc_error as _conflict_pin_classify,
)
from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    Reply as _ConflictPinReply,
    StrictSqlServer as _ConflictPinServer,
    applock_rules as _conflict_pin_applock_rules,
    sql_server_error as _conflict_pin_error,
)

_CONFLICT_PIN_ERRORS = (
    (
        "deadlock victim 1205",
        _conflict_pin_error(
            "40001",
            "Transaction (Process ID 55) was deadlocked on lock resources with "
            "another process and has been chosen as the deadlock victim. Rerun "
            "the transaction.",
            1205,
        ),
    ),
    (
        "lock timeout 1222",
        _conflict_pin_error("42000", "Lock request time out period exceeded.", 1222),
    ),
    (
        "snapshot update conflict 3960",
        _conflict_pin_error(
            "42000",
            "Snapshot isolation transaction aborted due to update conflict. You "
            "cannot use snapshot isolation to access table 'dbo.BidLayers' "
            "directly or indirectly in database 'TEST' to update, delete, or "
            "insert the row that has been modified or deleted by another "
            "transaction. Retry the transaction or change the isolation level "
            "for the update/delete statement.",
            3960,
        ),
    ),
)


class _ConflictPinRequests:
    def __init__(self, request):
        self._request = request

    def request(self, _database_id, *, read_only):
        return self._request


class _ConflictPinMarkerStore(_RecoverableProjectionStore, _ScriptedStore):
    """Coordinator store whose ``query_operation`` is the REAL
    ``SqlCollaborationStore.query_operation`` running against the strict SQL
    Server model (application lock, marker SELECT by operation id, rollback), so
    the marker lookup the coordinator performs is visible as statements.
    Everything else stays on the coordinator fakes; no write statement exists in
    the model, any DML the coordinator sent would be an unscripted-SQL violation.
    """

    def __init__(self):
        super().__init__()
        self.server = _ConflictPinServer()
        _conflict_pin_applock_rules(self.server)
        self.server.on(
            "FROM [ostv].[ChangeTransactions] WHERE [TransactionId]=?",
            self._marker_rows,
        )
        self.marker = {}
        self.query_log = []
        store = _ConflictPinSqlStore.__new__(_ConflictPinSqlStore)
        location = _ConflictPinLocation(server="localhost", database="TEST")
        store._requests = _ConflictPinRequests(_ConflictPinConnectionRequest(location))
        store._connections = self.server.manager()
        self.real_store = store

    def _marker_rows(self, call):
        row = self.marker.get(call.params[0])
        return _ConflictPinReply.rows(*([row] if row is not None else []))

    def commit_marker(self, durable):
        self.marker[durable.operation_id] = (
            durable.mutation_type,
            durable.request_hash,
            durable.result_format_version,
            durable.result_payload,
        )

    def query_operation(self, database_id, operation_id):
        self.query_log.append((database_id, operation_id))
        with self.server.patched():
            return self.real_store.query_operation(database_id, operation_id)


class SqlCollaborationCoordinatorTransactionConflictPinTests(_SecondPassBase):
    """Decision D12 (pin): after a deadlock victim (1205), lock timeout (1222) or
    snapshot update conflict (3960) the coordinator never replays the DML. A
    statement-time failure is reported FAILED_BEFORE_COMMIT and reconnects; an
    uncertain commit reconnects with a NEW session and asks the SQL operation
    marker (under the operation's application lock, by operation id, always
    rolled back) for the outcome, delivering COMMITTED from the marker or
    FAILED_BEFORE_COMMIT when it is absent.
    Real: coordinator, pending-mutation registry, journal fake, the worker thread
    in the threaded test and ``SqlCollaborationStore.query_operation`` over the
    strict SQL model. Fake: the mutation executor (it returns what the writer
    returns, pinned separately in WriterTransactionConflictPinTests), the rest of
    the store, and server behaviour (the model injects nothing for the marker).
    """

    DML_WRITE = "dml"

    def _error(self, source):
        return _ConflictPinInfrastructureError(_conflict_pin_classify(source))

    def _queue(self, coordinator, runtime, log, operation, results):
        _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            operation,
            results.append,
            operation_id="conflict-pin",
        )
        return coordinator._pending_mutations.for_database(runtime.database_id)[
            0
        ].request

    def _reconnect(self, coordinator, runtime):
        """What the worker does after the retryable failure."""
        previous = runtime.session
        coordinator._reset_session(runtime)
        session_generation = coordinator._install_session(
            runtime, DatabaseSession(runtime.database_id, str(uuid.uuid4()))
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                runtime.database_id,
                runtime.generation,
                session_generation,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
                None,
            )
        )
        return previous

    def _assert_marker_lookup_only(self, store, operation_id, expected_lookups=1):
        server = store.server
        self.assertEqual(len(server.connect_calls), expected_lookups)
        for number in range(1, expected_lookups + 1):
            statements = server.statements(number)
            # the application lock of the operation first, then the marker SELECT
            # by operation id, then the transaction is abandoned (rolled back)
            self.assertEqual(len(statements), 2)
            self.assertIn("sp_getapplock", statements[0])
            self.assertIn("@LockMode=N'Exclusive'", statements[0])
            self.assertIn("@LockOwner=N'Transaction'", statements[0])
            self.assertIn(
                "FROM [ostv].[ChangeTransactions] WHERE [TransactionId]=?",
                statements[1],
            )
            self.assertEqual(
                [
                    call
                    for call in server.events
                    if call[0] == number and call[1] == "execute"
                ][0][2],
                statements[0],
            )
            raw = server.connections[number - 1]
            self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
            self.assertEqual(
                server.event_kinds(number),
                [
                    "cursor_open",
                    "execute",
                    "execute",
                    "cursor_close",
                    "rollback",
                    "close",
                ],
            )
        # never a write: no DML/DDL statement of any kind reached the server
        everything = " ".join(server.statements()).upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "ALTER ", "CREATE "):
            self.assertNotIn(verb, everything)
        self.assertEqual(server.applocks.holders(f"OSTV:operation:{operation_id}"), [])
        server.assert_everything_closed()

    def test_uncertain_commit_reconnects_and_reads_the_marker_instead_of_replaying(
        self,
    ):
        for label, source in _CONFLICT_PIN_ERRORS:
            for marker_committed in (True, False):
                with self.subTest(error=label, marker_committed=marker_committed):
                    store = _ConflictPinMarkerStore()
                    journal = _PendingOperationJournal()
                    coordinator, runtime = self.ready_coordinator(
                        store=store, journal=journal
                    )
                    log = []
                    results = []

                    def operation(log=log):
                        log.append(self.DML_WRITE)
                        # what SqlProjectWriter.execute returns when the commit
                        # raised this error (WriterTransactionConflictPinTests)
                        return _unknown_commit(
                            "The SQL commit failed and its outcome is unknown."
                        )

                    request = self._queue(coordinator, runtime, log, operation, results)
                    first_session = runtime.session
                    with self.assertRaises(DatabaseCatalogError) as failure:
                        coordinator._process_mutation_requests(runtime)
                    # worker reconnects (retryable), it is not read-only/credential
                    self.assertTrue(failure.exception.retryable)
                    self.assertFalse(failure.exception.read_only_required)
                    self.assertFalse(failure.exception.credential_required)
                    self.assertEqual(log, [self.DML_WRITE])
                    self.assertEqual(
                        [r.outcome_status for r in results],
                        [MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN],
                    )
                    # the marker is NOT consulted before the reconnect
                    self.assertEqual(store.query_log, [])
                    self.assertEqual(store.server.connect_calls, [])
                    self.assertEqual(
                        coordinator._pending_mutations.get(request.operation_id).state,
                        PendingMutationState.UNCERTAIN,
                    )
                    if marker_committed:
                        store.commit_marker(_durable_result(request, "501"))
                    previous = self._reconnect(coordinator, runtime)
                    self.assertIs(previous, first_session)
                    self.assertNotEqual(
                        runtime.session.session_id, first_session.session_id
                    )
                    # exactly one marker query, for this operation id only
                    self.assertEqual(
                        store.query_log,
                        [(runtime.database_id, request.operation_id)],
                    )
                    self._assert_marker_lookup_only(store, request.operation_id)
                    # and the DML was not executed a second time
                    self.assertEqual(log, [self.DML_WRITE])
                    if marker_committed:
                        self.assertEqual(
                            [
                                (r.outcome_status, r.created_resource_ids)
                                for r in results
                            ],
                            [
                                (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, ()),
                                (MutationOutcomeStatus.COMMITTED, ("501",)),
                            ],
                        )
                    else:
                        self.assertEqual(
                            [(r.outcome_status, r.commit_attempted) for r in results],
                            [
                                (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, True),
                                (MutationOutcomeStatus.FAILED_BEFORE_COMMIT, False),
                            ],
                        )
                    self.assertEqual(
                        coordinator._pending_mutations.for_database(
                            runtime.database_id
                        ),
                        (),
                    )
                    self.assertEqual(journal.records, {})
                    self.assertEqual(coordinator._uncertain_callbacks, {})

    def test_statement_time_failure_is_reported_not_committed_and_never_replayed(self):
        for label, source in _CONFLICT_PIN_ERRORS:
            with self.subTest(error=label):
                store = _ConflictPinMarkerStore()
                journal = _PendingOperationJournal()
                coordinator, runtime = self.ready_coordinator(
                    store=store, journal=journal
                )
                log = []
                results = []
                raised = self._error(source)

                def operation(log=log, raised=raised):
                    log.append(self.DML_WRITE)
                    raise raised

                request = self._queue(coordinator, runtime, log, operation, results)
                with self.assertRaises(DatabaseCatalogError) as failure:
                    coordinator._process_mutation_requests(runtime)
                # the classified error itself drives the reconnect
                self.assertIs(failure.exception, raised)
                self.assertTrue(failure.exception.retryable)
                self.assertEqual(log, [self.DML_WRITE])
                self.assertEqual(
                    [(r.outcome_status, r.commit_attempted) for r in results],
                    [(MutationOutcomeStatus.FAILED_BEFORE_COMMIT, False)],
                )
                self.assertEqual(
                    results[0].message, "SQL Server returned an unexpected error."
                )
                self.assertEqual(coordinator._uncertain_callbacks, {})
                # reconnect: nothing is replayed, the queue and journal are empty
                # and the operation is not re-submitted under any session
                self._reconnect(coordinator, runtime)
                coordinator._process_mutation_requests(runtime)
                self.assertEqual(log, [self.DML_WRITE])
                self.assertEqual(len(results), 1)
                self.assertEqual(
                    coordinator._pending_mutations.for_database(runtime.database_id),
                    (),
                )
                self.assertEqual(journal.records, {})
                self.assertEqual(
                    [r.operation_id for r in results], [request.operation_id]
                )
                self.assertEqual(store.server.statements(), [])
                self.assertEqual(
                    store.query_log,
                    [],
                    "a statement-time failure has no uncertain outcome to look up",
                )

    def test_the_worker_reconnects_with_a_new_session_and_resolves_the_marker_once(
        self,
    ):
        polling = CollaborationPollingPolicy(
            heartbeat_seconds=0.0,
            inactive_database_seconds=0.05,
            jitter_ratio=0.0,
            reconnect_backoff_seconds=(0.05,),
        )
        for label, source in _CONFLICT_PIN_ERRORS:
            with self.subTest(error=label):
                store = _ConflictPinMarkerStore()
                dispatcher = _UiThreadDispatcher()
                coordinator, descriptor, _s, _events, capabilities = (
                    self.threaded_coordinator(
                        store=store, dispatcher=dispatcher, polling_policy=polling
                    )
                )
                database_id = descriptor.database_id

                def state():
                    return capabilities.collaboration_status(database_id).state

                self.assertTrue(coordinator.start_database(database_id))
                self.assertTrue(
                    dispatcher.pump_until(
                        lambda: state() == SynchronizationState.HEALTHY, 5
                    )
                )
                first_session = coordinator._sessions.get(database_id)
                log = []
                statuses = []

                def operation(log=log):
                    log.append(self.DML_WRITE)
                    return _unknown_commit()

                _queue_test_mutation(
                    coordinator,
                    database_id,
                    (ResourceRef("takeoffs_collection", "8", 8),),
                    operation,
                    lambda result: statuses.append(result.outcome_status),
                    operation_id="conflict-pin-thread",
                )
                request = coordinator._pending_mutations.for_database(database_id)[
                    0
                ].request
                store.commit_marker(_durable_result(request, "501"))
                self.assertTrue(dispatcher.pump_until(lambda: len(statuses) >= 2, 5))
                self.assertTrue(
                    dispatcher.pump_until(
                        lambda: state() == SynchronizationState.HEALTHY
                        and coordinator._sessions.get(database_id) != first_session,
                        5,
                    )
                )
                self.assertEqual(
                    statuses,
                    [
                        MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                        MutationOutcomeStatus.COMMITTED,
                    ],
                )
                self.assertEqual(log, [self.DML_WRITE])
                self.assertEqual(store.calls["start_session"], 2)
                self.assertEqual(store.query_log, [(database_id, request.operation_id)])
                self._assert_marker_lookup_only(store, request.operation_id)
                self.assertEqual(
                    coordinator._pending_mutations.for_database(database_id), ()
                )
                done = threading.Event()
                coordinator.stop_database_async(
                    database_id, callback=lambda *_r: done.set()
                )
                self.assertTrue(dispatcher.pump_until(done.is_set, 5))


class _StartFailureStore(_CollaborationStore):
    """start_session raises `always` (when set) or the next scripted error, else
    succeeds; heartbeat raises the next scripted heartbeat error. `attempts`
    counts every start_session call."""

    def __init__(self):
        super().__init__()
        self.always = None
        self.errors = []
        self.heartbeat_errors = []
        self.attempts = 0

    def start_session(self, *args, **kwargs):
        self.attempts += 1
        if self.always is not None:
            raise self.always
        if self.errors:
            raise self.errors.pop(0)
        return super().start_session(*args, **kwargs)

    def heartbeat(self, *args):
        if self.heartbeat_errors:
            raise self.heartbeat_errors.pop(0)
        return super().heartbeat(*args)


class _ManualClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class SqlCollaborationRestartRuleTests(_SecondPassBase):
    """D13: an ended worker stays stopped until an explicit re-probe, and every
    re-probe restart is bounded by the reconnect backoff. The UI-thread
    dispatcher delivers the coordinator's own state changes after the worker
    thread has exited, exactly as the Qt bridge does; the synchronous test
    dispatcher hides that order."""

    polling = CollaborationPollingPolicy(
        heartbeat_seconds=0.0,
        inactive_database_seconds=0.05,
        jitter_ratio=0.0,
        reconnect_backoff_seconds=(1.0, 2.0, 5.0),
    )
    # Callbacks one scenario may run before the runaway guard stops it: a restart
    # loop is driven by pumped callbacks, so the guard ends it without spinning.
    runaway = 200
    sign_in = DatabaseCatalogError("Sign in again.", credential_required=True)

    def started(self, store, *, clock=None, retry_initial_failure=True):
        dispatcher = _UiThreadDispatcher()
        extra = {} if clock is None else {"clock": clock}
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(
                store=store,
                dispatcher=dispatcher,
                polling_policy=self.polling,
                register_cleanup=False,
                **extra,
            )
        )
        self.addCleanup(self._shutdown_pumped, coordinator, dispatcher)
        database_id = descriptor.database_id
        self.assertTrue(
            coordinator.start_database(
                database_id, retry_initial_failure=retry_initial_failure
            )
        )
        return coordinator, dispatcher, database_id, events, capabilities

    @staticmethod
    def collaboration_threads_alive():
        return any(
            thread.name.startswith("SqlCollaboration") and thread.is_alive()
            for thread in threading.enumerate()
        )

    def settle(self, dispatcher):
        """Deliver callbacks until every collaboration thread has ended (these
        scenarios end their workers) and the queue is empty."""
        executed = dispatcher.pump_idle(
            is_busy=self.collaboration_threads_alive, max_callbacks=self.runaway
        )
        self.assertLess(executed, self.runaway, "runaway restart loop")

    def states(self, coordinator):
        return [
            (payload["state"], payload["message"])
            for payload in self.published(
                coordinator, AppEvents.COLLABORATION_STATE_CHANGED
            )
        ]

    def reprobe(self, events, dispatcher, database_id):
        events.publish(AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id)
        self.settle(dispatcher)

    def assert_worker_ended_and_stays_stopped(
        self, coordinator, store, database_id, states
    ):
        runtime = coordinator._runtime(database_id)
        self.assertIsNotNone(runtime)
        self.assertEqual(runtime.generation, 1)
        self.assertFalse(runtime.thread.is_alive())
        self.assertEqual(store.attempts, 1)
        self.assertEqual(self.states(coordinator), states)

    def test_ended_workers_stay_stopped_until_a_reprobe_under_the_ui_dispatcher(self):
        cases = (
            (
                "credential_required",
                DatabaseCatalogError("Sign in again.", credential_required=True),
                True,
                [("connecting", ""), ("credential_required", "Sign in again.")],
            ),
            (
                "read_only_required",
                DatabaseCatalogError("No write access.", read_only_required=True),
                True,
                [("connecting", ""), ("read_only", "No write access.")],
            ),
            (
                "session_expired",
                DatabaseCatalogError("Session expired.", session_expired=True),
                True,
                [("connecting", ""), ("disconnected", "Session expired.")],
            ),
            (
                "non_retryable",
                DatabaseCatalogError("Schema is not supported."),
                True,
                [("connecting", ""), ("disconnected", "Schema is not supported.")],
            ),
            (
                "failed_first_open_without_retry",
                DatabaseCatalogError("Server unavailable.", retryable=True),
                False,
                [("connecting", ""), ("disconnected", "Server unavailable.")],
            ),
            (
                "unexpected_internal_error",
                RuntimeError("boom"),
                True,
                [
                    ("connecting", ""),
                    (
                        "disconnected",
                        "SQL collaboration stopped after an unexpected internal "
                        "error.",
                    ),
                ],
            ),
        )
        for name, error, retry_initial_failure, states in cases:
            with self.subTest(failure=name):
                store = _StartFailureStore()
                store.always = error
                coordinator, dispatcher, database_id, _events, _caps = self.started(
                    store, retry_initial_failure=retry_initial_failure
                )
                self.settle(dispatcher)
                self.assert_worker_ended_and_stays_stopped(
                    coordinator, store, database_id, states
                )

    def test_a_trust_change_found_after_connecting_ends_the_worker_for_good(self):
        store = _StartFailureStore()
        dispatcher = _UiThreadDispatcher()
        coordinator, descriptor, _store, _events, capabilities = (
            self.threaded_coordinator(
                store=store,
                dispatcher=dispatcher,
                polling_policy=self.polling,
                register_cleanup=False,
            )
        )
        self.addCleanup(self._shutdown_pumped, coordinator, dispatcher)
        database_id = descriptor.database_id
        # The permission probe now denies writing: the restored-session check
        # fails after the session connected (a trust change, not a connection
        # failure) and ends the worker.
        with patch.object(capabilities, "_permission_probe", _DeniedPermissionProbe()):
            self.assertTrue(coordinator.start_database(database_id))
            self.settle(dispatcher)
        runtime = coordinator._runtime(database_id)
        self.assertFalse(runtime.thread.is_alive())
        self.assertEqual(store.attempts, 1)
        self.assertEqual(
            self.states(coordinator),
            [
                ("connecting", ""),
                ("catching_up", ""),
                ("read_only", "SQL edit permissions or schema trust changed."),
            ],
        )

    def test_credential_failure_then_explicit_reprobe_restarts_exactly_once(self):
        store = _StartFailureStore()
        store.always = self.sign_in
        coordinator, dispatcher, database_id, events, _caps = self.started(store)
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.settle(dispatcher)
        first = coordinator._runtime(database_id)
        self.assert_worker_ended_and_stays_stopped(
            coordinator,
            store,
            database_id,
            [("connecting", ""), ("credential_required", "Sign in again.")],
        )
        # The user signs in again: the explicit re-probe replaces the worker.
        store.always = None
        events.publish(AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id)
        self.assertTrue(dispatcher.pump_until(healthy.is_set, 5))
        dispatcher.pump_until(lambda: False, 0.2)
        replacement = coordinator._runtime(database_id)
        self.assertIsNot(replacement, first)
        self.assertEqual((replacement.generation, store.attempts), (2, 2))
        self.assertTrue(replacement.thread.is_alive())
        self.assertEqual(
            self.states(coordinator)[2:],
            [
                ("read_only", "SQL collaboration is closing."),
                ("stopped", ""),
                ("connecting", ""),
                ("catching_up", ""),
                ("healthy", ""),
            ],
        )

    def test_reprobe_restarts_follow_the_reconnect_backoff_with_an_injected_clock(
        self,
    ):
        clock = _ManualClock(100.0)
        store = _StartFailureStore()
        store.always = self.sign_in
        coordinator, dispatcher, database_id, events, _caps = self.started(
            store, clock=clock
        )
        self.settle(dispatcher)
        self.assertEqual(store.attempts, 1)
        # (clock reading, restarts that re-probe causes). Backoff steps 1, 2, 5
        # then capped at 5: a restart is refused until the previous restart's
        # step has elapsed, and the first one is immediate.
        schedule = (
            (100.0, 1),
            (100.5, 0),
            (100.999, 0),
            (101.0, 1),
            (102.999, 0),
            (103.0, 1),
            (107.999, 0),
            (108.0, 1),
            (112.999, 0),
            (113.0, 1),
            (117.999, 0),
            (118.0, 1),
        )
        observed = []
        for now, _expected in schedule:
            clock.now = now
            before = store.attempts
            self.reprobe(events, dispatcher, database_id)
            observed.append((now, store.attempts - before))
        self.assertEqual(observed, list(schedule))
        # One initial attempt plus six restarts; every restart is a new runtime
        # generation and every refused re-probe left the ended runtime alone.
        self.assertEqual(store.attempts, 7)
        self.assertEqual(coordinator._runtime(database_id).generation, 7)

    def test_a_healthy_session_restarts_the_backoff_sequence(self):
        clock = _ManualClock(100.0)
        store = _StartFailureStore()
        store.always = self.sign_in
        coordinator, dispatcher, database_id, events, _caps = self.started(
            store, clock=clock
        )
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.settle(dispatcher)
        for now in (100.0, 101.0):  # steps 1 and 2 are used up
            clock.now = now
            self.reprobe(events, dispatcher, database_id)
        self.assertEqual(store.attempts, 3)
        # The next re-probe (step 5) connects; a HEALTHY session resets the steps.
        store.always = None
        clock.now = 103.0
        events.publish(AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id)
        self.assertTrue(dispatcher.pump_until(healthy.is_set, 5))
        self.assertEqual(store.attempts, 4)
        # The session then expires and sign-in is needed again.
        store.heartbeat_errors.append(
            DatabaseCatalogError("Session expired.", session_expired=True)
        )
        store.always = self.sign_in
        self.settle(dispatcher)
        # Before the reset this re-probe (103.5 < 108.0) would be refused.
        clock.now = 103.5
        self.reprobe(events, dispatcher, database_id)
        self.assertEqual(store.attempts, 5)
        clock.now = 104.4
        self.reprobe(events, dispatcher, database_id)
        self.assertEqual(store.attempts, 5)
        # The delay is step one (1 s), not the capped 5 s of the old sequence.
        clock.now = 104.5
        self.reprobe(events, dispatcher, database_id)
        self.assertEqual(store.attempts, 6)

    def test_closing_the_database_restarts_the_backoff_sequence(self):
        clock = _ManualClock(100.0)
        store = _StartFailureStore()
        store.always = self.sign_in
        coordinator, dispatcher, database_id, events, _caps = self.started(
            store, clock=clock
        )
        self.settle(dispatcher)
        self.reprobe(events, dispatcher, database_id)
        self.assertEqual(store.attempts, 2)
        clock.now = 100.2
        self.reprobe(events, dispatcher, database_id)
        self.assertEqual(store.attempts, 2)  # refused: control for the close below
        stopped = threading.Event()
        coordinator.stop_database_async(
            database_id, callback=lambda *_result: stopped.set()
        )
        self.assertTrue(dispatcher.pump_until(stopped.is_set, 5))
        self.assertTrue(coordinator.start_database(database_id))
        self.settle(dispatcher)
        self.assertEqual(store.attempts, 3)
        self.reprobe(events, dispatcher, database_id)
        self.assertEqual(store.attempts, 4)

    def ended_runtime(self):
        class StoppedThread:
            ident = 1

            def is_alive(self):
                return False

        coordinator, runtime = self.ready_coordinator()
        patcher = patch.object(runtime, "thread", StoppedThread())
        patcher.start()
        self.addCleanup(patcher.stop)
        stop = patch.object(coordinator, "stop_database_async")
        self.addCleanup(stop.stop)
        return coordinator, runtime, stop.start()

    def test_the_coordinators_own_events_do_not_restart_an_ended_worker(self):
        coordinator, runtime, stop = self.ended_runtime()
        database_id = runtime.database_id
        for state in (
            SynchronizationState.DISCONNECTED,
            SynchronizationState.CREDENTIAL_REQUIRED,
            SynchronizationState.READ_ONLY,
            SynchronizationState.STOPPED,
        ):
            coordinator._set_state(database_id, state, "own change")
        coordinator._publish_capability_change(
            (
                database_id,
                runtime.generation,
                runtime.session_generation,
                frozenset({ResourceRef("condition", "42", 8)}),
            )
        )
        # Positive controls: the coordinator did publish the event the handler
        # subscribes to, once per state change and once for the lock change.
        self.assertEqual(
            len(self.published(coordinator, AppEvents.DATABASE_CAPABILITIES_CHANGED)),
            5,
        )
        stop.assert_not_called()
        # An explicit re-probe published by anyone else still restarts it.
        coordinator._event_bus.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id
        )
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(stop.call_args.args[:2], (database_id, "reconfigured"))

    def test_a_failing_subscriber_does_not_leave_the_own_event_guard_set(self):
        coordinator, runtime, stop = self.ended_runtime()
        database_id = runtime.database_id

        def failing_subscriber(**_payload):
            raise RuntimeError("subscriber failed")

        coordinator._event_bus.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED, failing_subscriber
        )
        self.addCleanup(
            coordinator._event_bus.unsubscribe,
            AppEvents.COLLABORATION_STATE_CHANGED,
            failing_subscriber,
        )
        with self.assertRaises(RuntimeError):
            coordinator._set_state(database_id, SynchronizationState.DISCONNECTED)
        coordinator._event_bus.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id
        )
        self.assertEqual(stop.call_count, 1)

    def test_the_own_event_guard_is_per_thread(self):
        coordinator, runtime, stop = self.ended_runtime()
        database_id = runtime.database_id
        explicit = []

        def publish_explicitly(**_payload):
            # Runs inside the coordinator's own publication on this thread; an
            # explicit re-probe from ANOTHER thread meanwhile must still count.
            if explicit:
                return
            thread = threading.Thread(
                target=lambda: coordinator._event_bus.publish(
                    AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id
                )
            )
            explicit.append(thread)
            thread.start()
            thread.join(2)

        coordinator._event_bus.subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED, publish_explicitly
        )
        coordinator._set_state(database_id, SynchronizationState.DISCONNECTED)
        self.assertEqual(len(explicit), 1)
        self.assertEqual(stop.call_count, 1)

    def test_an_explicit_refresh_that_clears_conflicts_restarts_an_ended_worker(self):
        # Contract changed by F3: Refresh is the explicit re-probe whether or not
        # it had a conflict to clear (the old control "a refresh with nothing to
        # republish does not restart it" no longer holds; it is covered by
        # SqlCollaborationRefreshReprobeTests). What stays pinned here is the
        # conflict-clearing route: it republishes the capabilities so the UI sees
        # the conflict cleared, and still causes exactly one restart.
        coordinator, runtime, stop = self.ended_runtime()
        # G1: only a recoverable end restarts on Refresh (the unrecoverable
        # conflict-clearing route is pinned in SqlCollaborationRefreshReprobeTests).
        runtime.end_reason = _WorkerEndReason.MARKER_LOOKUP_BLOCKED
        coordinator._clock = _ManualClock(100.0)
        database_id = runtime.database_id
        capabilities = coordinator._capabilities
        capabilities.add_collaboration_conflict(
            database_id, ResourceRef("condition", "42", 8)
        )
        republished = len(
            self.published(coordinator, AppEvents.DATABASE_CAPABILITIES_CHANGED)
        )
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=database_id
        )
        self.assertEqual(
            capabilities.collaboration_status(database_id).conflicted_resources,
            frozenset(),
        )
        self.assertEqual(
            len(self.published(coordinator, AppEvents.DATABASE_CAPABILITIES_CHANGED)),
            republished + 1,
        )
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(stop.call_args.args[:2], (database_id, "reconfigured"))
        # A conflict-clearing refresh inside the backoff window still clears the
        # conflict and republishes, but is dropped as a restart.
        capabilities.add_collaboration_conflict(
            database_id, ResourceRef("condition", "43", 8)
        )
        coordinator._clock.now = 100.5
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=database_id
        )
        self.assertEqual(
            capabilities.collaboration_status(database_id).conflicted_resources,
            frozenset(),
        )
        self.assertEqual(
            len(self.published(coordinator, AppEvents.DATABASE_CAPABILITIES_CHANGED)),
            republished + 2,
        )
        self.assertEqual(stop.call_count, 1)


class SqlCollaborationRefreshReprobeTests(_SecondPassBase):
    """F3: the user's Refresh (DATABASE_REFRESHED) is the explicit re-probe of an
    ended worker. It goes through the same bounded backoff as every other
    re-probe restart (a refresh inside the window is dropped, not queued, and
    shows no error) and never touches a live worker. Every scenario runs with
    NO resource conflict to clear, the case the D13 conflict-clearing route
    missed; the UI-thread dispatcher models the Qt bridge, the synchronous
    dispatcher the in-process one."""

    polling = SqlCollaborationRestartRuleTests.polling
    sign_in = DatabaseCatalogError("Sign in again.", credential_required=True)
    runaway = 200

    def started(self, store, *, clock, ui=True, retry_initial_failure=True):
        dispatcher = _UiThreadDispatcher() if ui else None
        coordinator, descriptor, _store, events, _capabilities = (
            self.threaded_coordinator(
                store=store,
                dispatcher=dispatcher,
                polling_policy=self.polling,
                register_cleanup=dispatcher is None,
                clock=clock,
            )
        )
        if dispatcher is not None:
            self.addCleanup(self._shutdown_pumped, coordinator, dispatcher)
        database_id = descriptor.database_id
        self.assertTrue(
            coordinator.start_database(
                database_id, retry_initial_failure=retry_initial_failure
            )
        )
        return coordinator, dispatcher, database_id, events

    @staticmethod
    def collaboration_threads_alive():
        return any(
            thread.name.startswith("SqlCollaboration") and thread.is_alive()
            for thread in threading.enumerate()
        )

    def settle(self, dispatcher):
        """Run until every collaboration thread (worker and drain) has ended and
        no callback is queued."""
        if dispatcher is not None:
            executed = dispatcher.pump_idle(
                is_busy=self.collaboration_threads_alive, max_callbacks=self.runaway
            )
            self.assertLess(executed, self.runaway, "runaway restart loop")
            return
        deadline = time.monotonic() + 10
        quiet = 0
        while quiet < 3:
            quiet = 0 if self.collaboration_threads_alive() else quiet + 1
            self.assertLess(time.monotonic(), deadline, "collaboration never idled")
            time.sleep(0.02)

    def refresh(self, events, dispatcher, database_id):
        events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
        self.settle(dispatcher)

    def states(self, coordinator):
        return [
            (payload["state"], payload["message"])
            for payload in self.published(
                coordinator, AppEvents.COLLABORATION_STATE_CHANGED
            )
        ]

    def blocked_marker_worker(self, *, clock, ui, marker_committed=False):
        """A worker that ended because the uncertain-commit recovery found the
        operation marker blocked by the old writer's application lock (F6): the
        recoverable end (LOCKED-uncertain). Returns the coordinator, dispatcher,
        database id, event bus, store, the old writer's connection, the queued
        request and the delivered results."""
        store = _ConflictPinMarkerStore()
        dispatcher = _UiThreadDispatcher() if ui else None
        coordinator, descriptor, _store, events, _capabilities = (
            self.threaded_coordinator(
                store=store,
                dispatcher=dispatcher,
                polling_policy=self.polling,
                register_cleanup=dispatcher is None,
                clock=clock,
            )
        )
        if dispatcher is not None:
            self.addCleanup(self._shutdown_pumped, coordinator, dispatcher)
        database_id = descriptor.database_id
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.assertTrue(coordinator.start_database(database_id))
        self.assertTrue(self._await(dispatcher, healthy, 5))
        name = "refresh-blocked-marker"
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ostv-test:{name}"))
        holder = store.server.connect("old-writer", autocommit=False)
        store.server.applocks.acquire(
            holder, f"OSTV:operation:{operation_id}", "Exclusive"
        )
        log, results = [], []

        def operation():
            log.append("dml")
            return _unknown_commit()

        _queue_test_mutation(
            coordinator,
            database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            operation,
            results.append,
            operation_id=name,
        )
        request = coordinator._pending_mutations.for_database(database_id)[0].request
        self.assertEqual(request.operation_id, operation_id)
        if marker_committed:
            store.commit_marker(_durable_result(request, "501"))
        self.settle(dispatcher)
        ended = coordinator._runtime(database_id)
        self.assertEqual(ended.generation, 1)
        self.assertFalse(ended.thread.is_alive())
        self.assertEqual(store.calls["start_session"], 2)
        self.assertEqual(log, ["dml"])
        self.assertIs(ended.end_reason, _WorkerEndReason.MARKER_LOOKUP_BLOCKED)
        return (
            coordinator,
            dispatcher,
            database_id,
            events,
            store,
            holder,
            request,
            (
                log,
                results,
            ),
        )

    def assert_refreshes_follow_the_backoff(self, ui):
        clock = _ManualClock(100.0)
        (
            coordinator,
            dispatcher,
            database_id,
            events,
            store,
            _holder,
            request,
            (
                log,
                results,
            ),
        ) = self.blocked_marker_worker(clock=clock, ui=ui)
        # (clock reading, restarts the user's Refresh causes): the first restart
        # is immediate, then 1 s, 2 s, 5 s steps measured from the previous one.
        # Every restart ends again (the old writer still holds the lock), so each
        # step is one more start_session and one more blocked marker lookup.
        schedule = (
            (100.0, 1),
            (100.5, 0),
            (101.0, 1),
            (102.999, 0),
            (103.0, 1),
            (107.999, 0),
            (108.0, 1),
        )
        observed = []
        for now, expected in schedule:
            clock.now = now
            before_attempts = store.calls["start_session"]
            before_states = self.states(coordinator)
            self.refresh(events, dispatcher, database_id)
            observed.append((now, store.calls["start_session"] - before_attempts))
            if not expected:
                # Dropped, not queued: no state change, no error, ended runtime kept.
                self.assertEqual(self.states(coordinator), before_states)
        self.assertEqual(observed, list(schedule))
        runtime = coordinator._runtime(database_id)
        self.assertEqual((store.calls["start_session"], runtime.generation), (6, 5))
        # the first session had nothing to recover; sessions 2..6 each asked
        self.assertEqual(len(store.query_log), 5)
        self.assertFalse(runtime.thread.is_alive())
        # Nothing was replayed and the operation is still waiting to be resolved.
        self.assertEqual(log, ["dml"])
        self.assertEqual(
            [
                entry.state
                for entry in coordinator._pending_mutations.for_database(database_id)
            ],
            [PendingMutationState.UNCERTAIN],
        )
        # A refused refresh queued nothing: a quiet period restarts nothing.
        self.settle(dispatcher)
        self.assertEqual(store.calls["start_session"], 6)

    def test_user_refresh_restarts_an_ended_worker_once_per_backoff_window(self):
        self.assert_refreshes_follow_the_backoff(ui=True)

    def test_user_refresh_follows_the_backoff_with_the_synchronous_dispatcher(self):
        self.assert_refreshes_follow_the_backoff(ui=False)

    def test_user_refresh_leaves_each_unrecoverable_ended_worker_stopped(self):
        # G1 (user decision), replaces the F3 per-kind test that expected every one
        # of these to restart on Refresh: DATABASE_REFRESHED is also published
        # after routine post-write reloads, compaction and the Access monitor, so
        # only a recoverable end restarts. These stay stopped until an explicit
        # Reconnect / credential re-entry (stop 'reconfigured' + start_database).
        cases = (
            (
                "credential_required",
                DatabaseCatalogError("Sign in again.", credential_required=True),
                True,
            ),
            (
                "read_only_required",
                DatabaseCatalogError("No write access.", read_only_required=True),
                True,
            ),
            (
                "session_expired",
                DatabaseCatalogError("Session expired.", session_expired=True),
                True,
            ),
            ("non_retryable", DatabaseCatalogError("Schema is not supported."), True),
            ("unexpected_internal_error", RuntimeError("boom"), True),
        )
        for name, error, retry_initial_failure in cases:
            for ui in (True, False):
                with self.subTest(failure=name, ui_dispatcher=ui):
                    clock = _ManualClock(100.0)
                    store = _StartFailureStore()
                    store.always = error
                    coordinator, dispatcher, database_id, events = self.started(
                        store,
                        clock=clock,
                        ui=ui,
                        retry_initial_failure=retry_initial_failure,
                    )
                    self.settle(dispatcher)
                    ended = coordinator._runtime(database_id)
                    self.assertEqual((store.attempts, ended.generation), (1, 1))
                    self.assertFalse(ended.thread.is_alive())
                    states = self.states(coordinator)
                    self.assertEqual(len(states), 2)
                    # Even with the cause gone and long after any backoff window,
                    # Refresh restarts nothing and spends no backoff.
                    store.always = None
                    for now in (100.0, 100.5, 101.0, 1000.0):
                        clock.now = now
                        self.refresh(events, dispatcher, database_id)
                    self.assertIs(coordinator._runtime(database_id), ended)
                    self.assertEqual((store.attempts, ended.generation), (1, 1))
                    self.assertFalse(ended.thread.is_alive())
                    self.assertEqual(self.states(coordinator), states)
                    self.assertEqual(coordinator._restart_not_before, {})
                    self.assertEqual(coordinator._restart_steps, {})

    def test_user_refresh_of_a_failed_first_open_restarts_it_as_a_retrying_worker(
        self,
    ):
        clock = _ManualClock(100.0)
        store = _StartFailureStore()
        store.always = DatabaseCatalogError("Server unavailable.", retryable=True)
        coordinator, dispatcher, database_id, events = self.started(
            store, clock=clock, retry_initial_failure=False
        )
        self.settle(dispatcher)
        self.assertEqual(store.attempts, 1)
        self.assertFalse(coordinator._runtime(database_id).thread.is_alive())
        events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
        self.assertTrue(dispatcher.pump_until(lambda: store.attempts >= 2, 5))
        # The restart is a normal start (retry_initial_failure defaults to True):
        # the replacement worker stays alive and retries at the reconnect backoff.
        replacement = coordinator._runtime(database_id)
        self.assertEqual(replacement.generation, 2)
        self.assertTrue(replacement.thread.is_alive())
        # It is a live worker now: a further Refresh leaves it alone.
        events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
        dispatcher.pump_until(lambda: False, 0.1)
        self.assertIs(coordinator._runtime(database_id), replacement)
        self.assertTrue(replacement.thread.is_alive())

    def end_subtest(self, coordinator, dispatcher):
        """Shut a subtest's coordinator down: its restarted worker is alive and
        the next subtest's settle() waits for every collaboration thread."""
        if dispatcher is not None:
            self._shutdown_pumped(coordinator, dispatcher)
        else:
            _shutdown_coordinator(coordinator)

    @staticmethod
    def wait_until(dispatcher, predicate, timeout=5):
        """Wait for `predicate` (a UI-thread dispatcher is pumped meanwhile)."""
        if dispatcher is not None:
            return dispatcher.pump_until(predicate, timeout)
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def test_user_refresh_restarts_a_failed_first_open_under_the_backoff(self):
        # G1: a transient failed first open (retryable, retry_initial_failure
        # False) is a recoverable end, so Refresh restarts it with either
        # dispatcher and spends the first backoff step (1 s).
        for ui in (True, False):
            with self.subTest(ui_dispatcher=ui):
                clock = _ManualClock(100.0)
                store = _StartFailureStore()
                store.always = DatabaseCatalogError(
                    "Server unavailable.", retryable=True
                )
                coordinator, dispatcher, database_id, events = self.started(
                    store, clock=clock, ui=ui, retry_initial_failure=False
                )
                self.settle(dispatcher)
                ended = coordinator._runtime(database_id)
                self.assertEqual((store.attempts, ended.generation), (1, 1))
                self.assertFalse(ended.thread.is_alive())
                self.assertEqual(coordinator._restart_not_before, {})
                events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
                self.assertTrue(
                    self.wait_until(dispatcher, lambda: store.attempts >= 2)
                )
                replacement = coordinator._runtime(database_id)
                self.assertEqual(replacement.generation, 2)
                self.assertTrue(replacement.thread.is_alive())
                self.assertEqual(coordinator._restart_not_before, {database_id: 101.0})
                self.assertEqual(coordinator._restart_steps, {database_id: 1})
                self.end_subtest(coordinator, dispatcher)

    def test_user_refresh_resolves_a_blocked_marker_query_once_the_old_writer_is_gone(
        self,
    ):
        # G1: LOCKED-uncertain (F6) is a recoverable end. While the old writer
        # still holds the operation lock a Refresh restarts the worker, the
        # recovery is blocked again and the worker ends again (bounded by the
        # backoff, nothing replayed); once the old writer's connection is gone
        # the next Refresh resolves the operation from the marker.
        for ui in (True, False):
            for marker_committed in (False, True):
                with self.subTest(ui_dispatcher=ui, marker_committed=marker_committed):
                    clock = _ManualClock(100.0)
                    (
                        coordinator,
                        dispatcher,
                        database_id,
                        events,
                        store,
                        holder,
                        request,
                        (log, results),
                    ) = self.blocked_marker_worker(
                        clock=clock, ui=ui, marker_committed=marker_committed
                    )
                    self.assertEqual(
                        [r.outcome_status for r in results],
                        [MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN],
                    )
                    self.refresh(events, dispatcher, database_id)
                    self.assertEqual(coordinator._runtime(database_id).generation, 2)
                    self.assertEqual(store.calls["start_session"], 3)
                    self.assertEqual(len(store.query_log), 2)
                    self.assertEqual(len(results), 1)
                    holder.close()
                    clock.now = 101.0
                    events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
                    self.assertTrue(
                        self.wait_until(dispatcher, lambda: len(results) >= 2)
                    )
                    self.assertEqual(log, ["dml"])
                    expected = (
                        (MutationOutcomeStatus.COMMITTED, ("501",))
                        if marker_committed
                        else (MutationOutcomeStatus.FAILED_BEFORE_COMMIT, ())
                    )
                    self.assertEqual(
                        (results[1].outcome_status, results[1].created_resource_ids),
                        expected,
                    )
                    self.assertEqual(coordinator._runtime(database_id).generation, 3)
                    self.assertEqual(store.calls["start_session"], 4)
                    self.assertEqual(len(store.query_log), 3)
                    self.assertTrue(
                        self.wait_until(
                            dispatcher,
                            lambda: not coordinator._pending_mutations.for_database(
                                database_id
                            ),
                        )
                    )
                    self.assertEqual(coordinator._operation_journal.records, {})
                    self.assertEqual(coordinator._uncertain_callbacks, {})
                    # the next subtest must not see this coordinator's worker
                    self.end_subtest(coordinator, dispatcher)

    def test_user_refresh_leaves_a_worker_ended_by_a_trust_change_stopped(self):
        clock = _ManualClock(100.0)
        store = _StartFailureStore()
        dispatcher = _UiThreadDispatcher()
        coordinator, descriptor, _store, events, capabilities = (
            self.threaded_coordinator(
                store=store,
                dispatcher=dispatcher,
                polling_policy=self.polling,
                register_cleanup=False,
                clock=clock,
            )
        )
        self.addCleanup(self._shutdown_pumped, coordinator, dispatcher)
        database_id = descriptor.database_id
        # The permission probe denies writing after the session connected: the
        # restored-session check fails (a trust change) and ends the worker.
        with patch.object(capabilities, "_permission_probe", _DeniedPermissionProbe()):
            self.assertTrue(coordinator.start_database(database_id))
            self.settle(dispatcher)
        ended = coordinator._runtime(database_id)
        self.assertFalse(ended.thread.is_alive())
        self.assertIs(ended.end_reason, _WorkerEndReason.READ_ONLY_REQUIRED)
        states = self.states(coordinator)
        self.assertEqual(
            states[-1], ("read_only", "SQL edit permissions or schema trust changed.")
        )
        # The probe permits writing again, yet Refresh does not restart it.
        for now in (100.0, 101.0, 1000.0):
            clock.now = now
            self.refresh(events, dispatcher, database_id)
        self.assertIs(coordinator._runtime(database_id), ended)
        self.assertEqual((store.attempts, ended.generation), (1, 1))
        self.assertEqual(self.states(coordinator), states)
        self.assertEqual(coordinator._restart_not_before, {})

    def test_credential_re_entry_reconnects_the_stopped_worker_but_refresh_does_not(
        self,
    ):
        # G1 (user decision), replaces the F3 test that expected Refresh to
        # reconnect a credential_required worker once the user had signed in.
        clock = _ManualClock(100.0)
        store = _StartFailureStore()
        store.always = self.sign_in
        coordinator, dispatcher, database_id, events = self.started(store, clock=clock)
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.settle(dispatcher)
        # The user signs in again, but a Refresh is not the credential re-entry.
        store.always = None
        for _ in range(2):
            events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
            dispatcher.pump_until(lambda: False, 0.1)
        self.assertEqual(
            (coordinator._runtime(database_id).generation, store.attempts), (1, 1)
        )
        self.assertFalse(healthy.is_set())
        # The credential re-entry / Reconnect path restarts it directly.
        coordinator.stop_database_async(
            database_id,
            "reconfigured",
            lambda success, _message: (
                coordinator.start_database(database_id) if success else None
            ),
        )
        self.assertTrue(dispatcher.pump_until(healthy.is_set, 5))
        replacement = coordinator._runtime(database_id)
        self.assertEqual((replacement.generation, store.attempts), (2, 2))
        self.assertTrue(replacement.thread.is_alive())
        self.assertEqual(
            self.states(coordinator),
            [
                ("connecting", ""),
                ("credential_required", "Sign in again."),
                ("read_only", "SQL collaboration is closing."),
                ("stopped", ""),
                ("connecting", ""),
                ("catching_up", ""),
                ("healthy", ""),
            ],
        )

    def test_user_refresh_does_not_touch_a_live_worker_or_spend_the_backoff(self):
        clock = _ManualClock(100.0)
        store = _StartFailureStore()
        coordinator, dispatcher, database_id, events = self.started(store, clock=clock)
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.assertTrue(dispatcher.pump_until(healthy.is_set, 5))
        live = coordinator._runtime(database_id)
        states = self.states(coordinator)
        for _ in range(3):
            events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
            dispatcher.pump_until(lambda: False, 0.1)
        self.assertIs(coordinator._runtime(database_id), live)
        self.assertTrue(live.thread.is_alive())
        self.assertEqual((live.generation, store.attempts), (1, 1))
        self.assertEqual(self.states(coordinator), states)
        # The refreshes spent no backoff of a live worker.
        self.assertEqual(coordinator._restart_not_before, {})
        self.assertEqual(coordinator._restart_steps, {})
        # G1 (user decision): when the session later expires the worker ends for
        # good; a Refresh no longer restarts it (it spends no backoff either).
        store.heartbeat_errors.append(
            DatabaseCatalogError("Session expired.", session_expired=True)
        )
        self.settle(dispatcher)
        self.assertFalse(live.thread.is_alive())
        states = self.states(coordinator)
        self.assertEqual(states[-1], ("disconnected", "Session expired."))
        events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
        dispatcher.pump_until(lambda: False, 0.3)
        self.assertIs(coordinator._runtime(database_id), live)
        self.assertEqual((store.attempts, live.generation), (1, 1))
        self.assertEqual(self.states(coordinator), states)
        self.assertEqual(coordinator._restart_not_before, {})

    def ended_runtime(self, reason=_WorkerEndReason.TRANSIENT_OPEN_FAILURE):
        class StoppedThread:
            ident = 1

            def is_alive(self):
                return False

        coordinator, runtime = self.ready_coordinator()
        coordinator._clock = _ManualClock(100.0)
        runtime.end_reason = reason
        patcher = patch.object(runtime, "thread", StoppedThread())
        patcher.start()
        self.addCleanup(patcher.stop)
        stop = patch.object(coordinator, "stop_database_async")
        self.addCleanup(stop.stop)
        return coordinator, runtime, stop.start()

    # Every way a worker can end and whether a DATABASE_REFRESHED may restart it
    # (G1, user decision). Written out here, not read from the production set.
    REASON_RECOVERABLE = {
        "SESSION_EXPIRED": False,
        "CREDENTIAL_REQUIRED": False,
        "READ_ONLY_REQUIRED": False,
        "NON_RETRYABLE_ERROR": False,
        "INTERNAL_ERROR": False,
        "MARKER_LOOKUP_BLOCKED": True,
        "TRANSIENT_OPEN_FAILURE": True,
    }

    def test_user_refresh_restarts_an_ended_worker_only_for_a_recoverable_end_reason(
        self,
    ):
        # A new end reason must be classified here on purpose.
        self.assertEqual(
            {reason.name for reason in _WorkerEndReason}, set(self.REASON_RECOVERABLE)
        )
        cases = [
            (name, recoverable) for name, recoverable in self.REASON_RECOVERABLE.items()
        ]
        # An ended thread with no recorded reason (a stop request) is not recoverable.
        cases.append((None, False))
        for name, recoverable in cases:
            with self.subTest(end_reason=name):
                coordinator, runtime, stop = self.ended_runtime(
                    reason=None if name is None else _WorkerEndReason[name]
                )
                coordinator._event_bus.publish(
                    AppEvents.DATABASE_REFRESHED, file_path=runtime.database_id
                )
                self.assertEqual(stop.call_count, 1 if recoverable else 0)
                # a refused restart spends no backoff either
                self.assertEqual(
                    list(coordinator._restart_not_before),
                    [runtime.database_id] if recoverable else [],
                )

    def test_the_capability_event_restarts_an_ended_worker_whatever_its_end_reason(
        self,
    ):
        # G1 left the D13 rule alone: an explicit re-probe published by someone
        # else (the credential re-entry flow) still restarts every ended worker.
        for name in [*self.REASON_RECOVERABLE, None]:
            with self.subTest(end_reason=name):
                coordinator, runtime, stop = self.ended_runtime(
                    reason=None if name is None else _WorkerEndReason[name]
                )
                coordinator._event_bus.publish(
                    AppEvents.DATABASE_CAPABILITIES_CHANGED,
                    file_path=runtime.database_id,
                )
                self.assertEqual(stop.call_count, 1)
                self.assertEqual(
                    stop.call_args.args[:2], (runtime.database_id, "reconfigured")
                )

    def test_a_conflict_clearing_refresh_of_an_unrecoverable_worker_restarts_nothing(
        self,
    ):
        coordinator, runtime, stop = self.ended_runtime(
            reason=_WorkerEndReason.CREDENTIAL_REQUIRED
        )
        database_id = runtime.database_id
        capabilities = coordinator._capabilities
        capabilities.add_collaboration_conflict(
            database_id, ResourceRef("condition", "42", 8)
        )
        republished = len(
            self.published(coordinator, AppEvents.DATABASE_CAPABILITIES_CHANGED)
        )
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=database_id
        )
        # The UI still sees the conflict cleared (the capabilities are
        # republished once) but the republication is the coordinator's own, so
        # the capability handler restarts nothing.
        self.assertEqual(
            capabilities.collaboration_status(database_id).conflicted_resources,
            frozenset(),
        )
        self.assertEqual(
            len(self.published(coordinator, AppEvents.DATABASE_CAPABILITIES_CHANGED)),
            republished + 1,
        )
        stop.assert_not_called()
        self.assertEqual(coordinator._restart_not_before, {})
        self.assertEqual(coordinator._own_publication.depth, 0)
        # The explicit re-probe by someone else (credential re-entry) still works.
        coordinator._event_bus.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id
        )
        self.assertEqual(stop.call_count, 1)

    def test_a_refused_marker_lookup_is_blocked_only_without_another_cause(self):
        coordinator, runtime = self.ready_coordinator()
        record = SimpleNamespace(database_id=runtime.database_id, operation_id="op-1")
        cases = (
            ("no cause (LOCKED)", DatabaseCatalogError("Locked."), True),
            ("retryable", DatabaseCatalogError("Down.", retryable=True), False),
            ("session", DatabaseCatalogError("Gone.", session_expired=True), False),
            (
                "credential",
                DatabaseCatalogError("In.", credential_required=True),
                False,
            ),
            ("read only", DatabaseCatalogError("No.", read_only_required=True), False),
        )
        for name, error, blocked in cases:
            with self.subTest(error=name):
                runtime.marker_lookup_blocked = not blocked  # must be overwritten
                with (
                    patch.object(
                        coordinator._operation_journal,
                        "list_all",
                        return_value=(record,),
                    ),
                    patch.object(
                        coordinator._store,
                        "query_operation",
                        side_effect=error,
                        create=True,
                    ),
                ):
                    with self.assertRaises(DatabaseCatalogError) as raised:
                        coordinator._recover_journaled_operations(runtime)
                self.assertIs(raised.exception, error)
                self.assertIs(runtime.marker_lookup_blocked, blocked)

    def test_the_end_reason_of_each_worker_exit_is_recorded(self):
        cases = (
            (
                "credential_required",
                DatabaseCatalogError("Sign in again.", credential_required=True),
                True,
                _WorkerEndReason.CREDENTIAL_REQUIRED,
            ),
            (
                "read_only_required",
                DatabaseCatalogError("No write access.", read_only_required=True),
                True,
                _WorkerEndReason.READ_ONLY_REQUIRED,
            ),
            (
                "session_expired",
                DatabaseCatalogError("Session expired.", session_expired=True),
                True,
                _WorkerEndReason.SESSION_EXPIRED,
            ),
            (
                "non_retryable",
                DatabaseCatalogError("Schema is not supported."),
                True,
                _WorkerEndReason.NON_RETRYABLE_ERROR,
            ),
            (
                "internal_error",
                RuntimeError("boom"),
                True,
                _WorkerEndReason.INTERNAL_ERROR,
            ),
            (
                "failed_first_open",
                DatabaseCatalogError("Server unavailable.", retryable=True),
                False,
                _WorkerEndReason.TRANSIENT_OPEN_FAILURE,
            ),
            (
                "failed_first_open_os_error",
                OSError("network down"),
                False,
                _WorkerEndReason.TRANSIENT_OPEN_FAILURE,
            ),
        )
        for name, error, retry_initial_failure, expected in cases:
            with self.subTest(failure=name):
                store = _StartFailureStore()
                store.always = error
                coordinator, dispatcher, database_id, _events = self.started(
                    store,
                    clock=_ManualClock(100.0),
                    retry_initial_failure=retry_initial_failure,
                )
                self.settle(dispatcher)
                self.assertIs(coordinator._runtime(database_id).end_reason, expected)
                self.end_subtest(coordinator, dispatcher)
        # A healthy worker records no reason; an expired session found by the
        # heartbeat ends it as SESSION_EXPIRED.
        store = _StartFailureStore()
        coordinator, dispatcher, database_id, events = self.started(
            store, clock=_ManualClock(100.0)
        )
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.assertTrue(dispatcher.pump_until(healthy.is_set, 5))
        live = coordinator._runtime(database_id)
        self.assertIsNone(live.end_reason)
        store.heartbeat_errors.append(
            DatabaseCatalogError("Session expired.", session_expired=True)
        )
        self.settle(dispatcher)
        self.assertIs(live.end_reason, _WorkerEndReason.SESSION_EXPIRED)

    def test_user_refresh_of_an_ended_worker_asks_for_one_reconfigured_restart(self):
        coordinator, runtime, stop = self.ended_runtime()
        database_id = runtime.database_id
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=database_id
        )
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(stop.call_args.args[:2], (database_id, "reconfigured"))
        # The restart callback starts the replacement only after a clean stop.
        with patch.object(coordinator, "start_database") as start:
            callback = stop.call_args.args[2]
            callback(False, "cleanup failed")
            start.assert_not_called()
            callback(True, "")
            start.assert_called_once_with(database_id)
        # A second Refresh inside the window is dropped.
        coordinator._clock.now = 100.9
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=database_id
        )
        self.assertEqual(stop.call_count, 1)

    def test_user_refresh_of_an_ended_worker_ignores_a_pending_controlled_recovery(
        self,
    ):
        coordinator, runtime, stop = self.ended_runtime()
        database_id = runtime.database_id
        with runtime.lock:
            runtime.recovery_requested = True
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path=database_id
        )
        # The dead worker cannot run the recovery: Refresh restarts it instead of
        # consuming the recovery request on a runtime that is about to be replaced.
        self.assertEqual(stop.call_count, 1)
        self.assertFalse(runtime.recovery_attempted)
        self.assertFalse(runtime.recovery_ready)

    def test_user_refresh_of_an_unknown_database_does_nothing(self):
        coordinator, runtime, stop = self.ended_runtime()
        coordinator._event_bus.publish(
            AppEvents.DATABASE_REFRESHED, file_path="not-a-database"
        )
        stop.assert_not_called()
        self.assertEqual(coordinator._restart_not_before, {})

    def test_a_worker_thread_that_has_not_started_yet_is_not_an_ended_worker(self):
        coordinator, runtime, stop = self.ended_runtime()
        database_id = runtime.database_id
        # start_database registers the runtime before it starts the thread.
        unstarted = threading.Thread(target=lambda: None)
        self.assertIsNone(unstarted.ident)
        with patch.object(runtime, "thread", unstarted):
            coordinator._event_bus.publish(
                AppEvents.DATABASE_REFRESHED, file_path=database_id
            )
            coordinator._event_bus.publish(
                AppEvents.DATABASE_CAPABILITIES_CHANGED, file_path=database_id
            )
        stop.assert_not_called()
        self.assertEqual(coordinator._restart_not_before, {})


class SqlCollaborationMarkerQueryBlockedPinTests(_SecondPassBase):
    """F6 (pin, no production change): the old writer's connection still holds
    the operation's application lock (the server has not noticed the dead client
    yet) when the uncertain-commit recovery asks for the SQL operation marker.
    ``SqlCollaborationStore.query_operation`` takes the Exclusive transaction
    applock first, gets -1 and raises a non-retryable LOCKED error. Pinned: the
    worker ends, the operation stays UNCERTAIN and journaled, NOTHING is
    replayed, and the user sees the LOCKED message, which tells them to
    reconnect (G2). Once the lock is gone a Refresh restarts this recoverable end
    (G1) and the recovery resolves the operation from the marker.
    Real: coordinator, pending-mutation registry, worker thread (threaded tests),
    ``SqlCollaborationStore.query_operation`` and the classification of its error
    over the strict SQL model. Fake: the mutation executor (it returns an
    unknown-commit result), the rest of the store, the journal, and the server's
    lock timeout (the model answers -1 at once instead of waiting
    @LockTimeout=10000)."""

    LOCK_MESSAGE = (
        "Another session is resolving the same SQL operation. "
        "Reconnect to the database to finish resolving it."
    )
    DML = "dml"

    def lock_held_by_old_writer(self, store, operation_id):
        holder = store.server.connect("old-writer", autocommit=False)
        store.server.applocks.acquire(
            holder, f"OSTV:operation:{operation_id}", "Exclusive"
        )
        return holder

    @staticmethod
    def operation_id_of(name):
        # _queue_test_mutation derives the operation id from the name
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ostv-test:{name}"))

    def queue_uncertain_write(self, coordinator, database_id, log, results, name):
        def operation():
            log.append(self.DML)
            return _unknown_commit()

        _queue_test_mutation(
            coordinator,
            database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            operation,
            results.append,
            operation_id=name,
        )
        return coordinator._pending_mutations.for_database(database_id)[0].request

    def assert_blocked_marker_query(self, store, operation_id):
        server = store.server
        resource = f"OSTV:operation:{operation_id}"
        # connection 1 is the old writer, connection 2 the marker query
        self.assertEqual(
            server.applocks.log,
            [(1, resource, "Exclusive", 0), (2, resource, "Exclusive", -1)],
        )
        self.assertEqual(len(server.connect_calls), 2)
        statements = server.statements(2)
        self.assertEqual(len(statements), 1)
        self.assertIn("sp_getapplock", statements[0])
        self.assertIn("@LockMode=N'Exclusive'", statements[0])
        # the marker SELECT never ran, and the failed lookup was rolled back
        self.assertNotIn("ChangeTransactions", " ".join(server.statements()))
        raw = server.connections[1]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertEqual(
            server.event_kinds(2),
            ["cursor_open", "execute", "cursor_close", "rollback", "close"],
        )
        everything = " ".join(server.statements()).upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "ALTER ", "CREATE "):
            self.assertNotIn(verb, everything)
        self.assertEqual(server.applocks.holders(resource), [1])

    def test_a_held_operation_lock_fails_the_marker_query_and_nothing_is_replayed(
        self,
    ):
        for marker_committed in (False, True):
            with self.subTest(marker_committed=marker_committed):
                store = _ConflictPinMarkerStore()
                journal = _PendingOperationJournal()
                coordinator, runtime = self.ready_coordinator(
                    store=store, journal=journal
                )
                database_id = runtime.database_id
                log, results = [], []
                request = self.queue_uncertain_write(
                    coordinator, database_id, log, results, "marker-blocked-unit"
                )
                self.assertEqual(
                    request.operation_id, self.operation_id_of("marker-blocked-unit")
                )
                with self.assertRaises(DatabaseCatalogError) as commit_failure:
                    coordinator._process_mutation_requests(runtime)
                self.assertTrue(commit_failure.exception.retryable)
                if marker_committed:
                    # even a committed marker cannot be read while the lock is held
                    store.commit_marker(_durable_result(request, "501"))
                holder = self.lock_held_by_old_writer(store, request.operation_id)
                with self.assertRaises(_ConflictPinInfrastructureError) as blocked:
                    self.reconnect(coordinator, runtime)
                error = blocked.exception
                self.assertEqual(error.details.code, SqlErrorCode.LOCKED)
                self.assertEqual(str(error), self.LOCK_MESSAGE)
                # non-retryable and not a credential/permission/session problem:
                # the worker ends instead of reconnecting again
                self.assertEqual(
                    (
                        error.retryable,
                        error.credential_required,
                        error.read_only_required,
                        error.session_expired,
                    ),
                    (False, False, False, False),
                )
                self.assertEqual(store.query_log, [(database_id, request.operation_id)])
                self.assert_blocked_marker_query(store, request.operation_id)
                # nothing replayed, nothing resolved: the operation stays UNCERTAIN
                self.assertEqual(log, [self.DML])
                self.assertEqual(
                    [r.outcome_status for r in results],
                    [MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN],
                )
                pending = coordinator._pending_mutations.for_database(database_id)
                self.assertEqual(
                    [(entry.request.operation_id, entry.state) for entry in pending],
                    [(request.operation_id, PendingMutationState.UNCERTAIN)],
                )
                self.assertEqual(list(journal.records), [request.operation_id])
                self.assertEqual(
                    list(coordinator._uncertain_callbacks), [request.operation_id]
                )
                self.assertEqual(runtime.recovered_operation_ids, set())
                self.assertEqual(runtime.recovered_operation_results, {})
                # the operation stays recoverable: once the old writer is gone the
                # same recovery resolves it from the marker, still without a replay
                holder.close()
                self.reconnect(coordinator, runtime)
                self.assertEqual(log, [self.DML])
                if marker_committed:
                    self.assertEqual(
                        [(r.outcome_status, r.created_resource_ids) for r in results],
                        [
                            (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, ()),
                            (MutationOutcomeStatus.COMMITTED, ("501",)),
                        ],
                    )
                else:
                    self.assertEqual(
                        [r.outcome_status for r in results],
                        [
                            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                        ],
                    )
                self.assertEqual(
                    coordinator._pending_mutations.for_database(database_id), ()
                )
                self.assertEqual(journal.records, {})
                self.assertEqual(coordinator._uncertain_callbacks, {})

    def reconnect(self, coordinator, runtime):
        """What the worker does after the retryable commit failure."""
        coordinator._reset_session(runtime)
        session_generation = coordinator._install_session(
            runtime, DatabaseSession(runtime.database_id, str(uuid.uuid4()))
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                runtime.database_id,
                runtime.generation,
                session_generation,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
                None,
            )
        )

    def test_the_worker_ends_and_the_user_sees_the_lock_message_with_a_reconnect_hint(
        self,
    ):
        polling = SqlCollaborationRestartRuleTests.polling
        for marker_committed in (False, True):
            with self.subTest(marker_committed=marker_committed):
                store = _ConflictPinMarkerStore()
                dispatcher = _UiThreadDispatcher()
                coordinator, descriptor, _s, events, capabilities = (
                    self.threaded_coordinator(
                        store=store,
                        dispatcher=dispatcher,
                        polling_policy=polling,
                        register_cleanup=False,
                    )
                )
                self.addCleanup(self._shutdown_pumped, coordinator, dispatcher)
                database_id = descriptor.database_id
                healthy = _state_signal(
                    events, database_id, SynchronizationState.HEALTHY
                )
                self.assertTrue(coordinator.start_database(database_id))
                self.assertTrue(dispatcher.pump_until(healthy.is_set, 5))
                name = "marker-blocked-worker"
                operation_id = self.operation_id_of(name)
                holder = self.lock_held_by_old_writer(store, operation_id)
                log, results = [], []
                request = self.queue_uncertain_write(
                    coordinator, database_id, log, results, name
                )
                if marker_committed:
                    store.commit_marker(_durable_result(request, "501"))
                executed = dispatcher.pump_idle(
                    is_busy=SqlCollaborationRestartRuleTests.collaboration_threads_alive,
                    max_callbacks=200,
                )
                self.assertLess(executed, 200, "runaway restart loop")
                states = [
                    (payload["state"], payload["message"])
                    for payload in self.published(
                        coordinator, AppEvents.COLLABORATION_STATE_CHANGED
                    )
                ]
                # The last thing the user sees is the LOCKED message in the
                # disconnected state; it tells them to reconnect (G2).
                self.assertEqual(
                    states,
                    [
                        ("connecting", ""),
                        ("catching_up", ""),
                        ("healthy", ""),
                        (
                            "disconnected",
                            "The SQL mutation's commit status must be resolved "
                            "after reconnecting.",
                        ),
                        ("disconnected", self.LOCK_MESSAGE),
                    ],
                )
                self.assertIn("reconnect", states[-1][1].lower())
                status = capabilities.collaboration_status(database_id)
                self.assertEqual(
                    (status.state, status.message),
                    (SynchronizationState.DISCONNECTED, self.LOCK_MESSAGE),
                )
                ended = coordinator._runtime(database_id)
                self.assertEqual(ended.generation, 1)
                self.assertFalse(ended.thread.is_alive())
                # one session, one reconnect session, one marker query; no replay
                self.assertEqual(store.calls["start_session"], 2)
                self.assertEqual(store.query_log, [(database_id, request.operation_id)])
                self.assertEqual(log, [self.DML])
                self.assert_blocked_marker_query(store, request.operation_id)
                self.assertEqual(
                    [r.outcome_status for r in results],
                    [MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN],
                )
                pending = coordinator._pending_mutations.for_database(database_id)
                self.assertEqual(
                    [(entry.request.operation_id, entry.state) for entry in pending],
                    [(request.operation_id, PendingMutationState.UNCERTAIN)],
                )
                self.assertEqual(
                    list(coordinator._operation_journal.records),
                    [request.operation_id],
                )
                self.assertEqual(
                    list(coordinator._uncertain_callbacks), [request.operation_id]
                )
                # Nothing restarts the ended worker by itself, and a second
                # Refresh-less quiet period replays nothing either.
                dispatcher.pump_until(lambda: False, 0.3)
                self.assertEqual(store.calls["start_session"], 2)
                self.assertEqual(log, [self.DML])
                # The old writer's connection is gone: the user's Refresh (F3, the
                # explicit re-probe) restarts the worker and the recovery now
                # resolves the operation from the marker, without a replay.
                holder.close()
                events.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
                self.assertTrue(dispatcher.pump_until(lambda: len(results) >= 2, 5))
                self.assertEqual(log, [self.DML])
                expected = (
                    (MutationOutcomeStatus.COMMITTED, ("501",))
                    if marker_committed
                    else (MutationOutcomeStatus.FAILED_BEFORE_COMMIT, ())
                )
                self.assertEqual(
                    (results[1].outcome_status, results[1].created_resource_ids),
                    expected,
                )
                self.assertEqual(coordinator._runtime(database_id).generation, 2)
                self.assertEqual(
                    store.query_log,
                    [(database_id, request.operation_id)] * 2,
                )
                self.assertTrue(
                    dispatcher.pump_until(
                        lambda: not coordinator._pending_mutations.for_database(
                            database_id
                        ),
                        5,
                    )
                )
                self.assertEqual(coordinator._operation_journal.records, {})
                # The next subtest must not see this coordinator's worker.
                self._shutdown_pumped(coordinator, dispatcher)


class SqlCollaborationCoordinatorBidLockedRejectionTests(
    _SqlCollaborationCoordinatorCollaborationFixture
):
    """Decision B2: a REJECTED / bid_locked work result reaches the queued callback
    with its reason, exactly once, as a plain refusal: the queue continues in FIFO
    order, the runtime is not recovered or reconnected and no synchronization
    conflict is published. Fakes: the work callables return the MutationExecutionResult
    the SQL writer path would (the writer itself is covered in test_writer)."""

    @staticmethod
    def _bid_locked_execution(message="The database rejected the project update."):
        return MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.REJECTED,
            message=message,
            rejection_reason=MutationRejectionReason.BID_LOCKED,
        )

    def _queue(self, coordinator, runtime, work, results, name):
        return _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            work,
            results.append,
            operation_id=name,
        )

    def test_a_bid_locked_rejection_is_delivered_once_with_its_reason_and_the_queue_goes_on(
        self,
    ):
        store = _LockingStore()
        events = _EventBus()
        coordinator, runtime = self.ready_coordinator(store=store, event_bus=events)
        results = []
        calls = []

        def locked():
            calls.append("locked")
            return self._bid_locked_execution()

        def plain_rejection():
            calls.append("plain")
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.REJECTED, message="busy"
            )

        def committed():
            calls.append("committed")
            return _committed_execution("501")

        for name, work in (
            ("locked", locked),
            ("committed", committed),
            ("plain", plain_rejection),
        ):
            self.assertEqual(
                self._queue(coordinator, runtime, work, results, name),
                runtime.generation,
            )
        requests = tuple(runtime.mutation_requests.queue)
        generation = runtime.generation
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["locked"])
        self.assertEqual(len(results), 1)
        refused = results[0]
        self.assertEqual(refused.operation_id, requests[0].operation_id)
        self.assertEqual(refused.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertIs(refused.rejection_reason, MutationRejectionReason.BID_LOCKED)
        self.assertEqual(refused.rejection_reason, "bid_locked")
        # the canonical refusal text replaces the generic "database rejected" one
        self.assertEqual(refused.message, "The active bid is locked")
        self.assertFalse(refused.commit_attempted)
        self.assertIsNone(refused.conflict)
        self.assertIsNone(refused.authoritative_result)
        self.assertEqual(refused.created_resource_ids, ())
        # FIFO: the rest of the queue is still waiting, then runs in order
        self.assertEqual(runtime.mutation_requests.qsize(), 2)
        coordinator._process_mutation_requests(runtime)
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(calls, ["locked", "committed", "plain"])
        self.assertEqual(
            [result.operation_id for result in results],
            [request.operation_id for request in requests],
        )
        self.assertEqual(
            [(r.outcome_status, r.rejection_reason) for r in results],
            [
                (MutationOutcomeStatus.REJECTED, MutationRejectionReason.BID_LOCKED),
                (MutationOutcomeStatus.COMMITTED, None),
                (MutationOutcomeStatus.REJECTED, None),
            ],
        )
        self.assertEqual(results[2].message, "busy")
        # a refusal is not a runtime failure: no recovery, no reconnect, no conflict
        self.assertTrue(runtime.healthy)
        self.assertFalse(runtime.recovery_requested)
        self.assertEqual(runtime.generation, generation)
        self.assertEqual(coordinator._runtime(runtime.database_id), runtime)
        published = {event for event, _payload in events.published}
        self.assertNotIn(AppEvents.SYNCHRONIZATION_CONFLICT, published)
        self.assertEqual(
            {event.__name__ for event in published if isinstance(event, type)},
            {"CollaborationMutationStateChangedEvent", "BidLockedRejectionEvent"},
            "only the pending-mutation state events and (decision B4) the bid-locked "
            "rejection notice are published, never a conflict, a collaboration "
            "state change or a reconnect",
        )
        self.assertEqual(
            [
                payload
                for event, payload in events.published
                if event is AppEvents.BID_LOCKED_REJECTION
            ],
            [
                {
                    "database_id": runtime.database_id,
                    "operation_id": requests[0].operation_id,
                }
            ],
        )
        # the edit locks the queue took for the request were released again
        self.assertEqual(
            store.released,
            [(runtime.database_id, runtime.session.session_id, "lock-token")] * 3,
        )
        self.assertEqual(coordinator._local_drafts._drafts, {})
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(coordinator._operation_journal.records, {})

    def test_the_callback_receives_the_refusal_exactly_once(self):
        coordinator, runtime = self.ready_coordinator(store=_LockingStore())
        results = []
        self._queue(coordinator, runtime, self._bid_locked_execution, results, "once")
        coordinator._process_mutation_requests(runtime)
        # nothing is left to run or re-deliver
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(len(results), 1)
        self.assertTrue(runtime.mutation_requests.empty())

    def test_a_lifecycle_critical_bid_locked_refusal_is_a_drain_failure_with_its_message(
        self,
    ):
        coordinator, runtime = self.ready_coordinator(store=_LockingStore())
        results = []
        coordinator._mutation_drain_failures[runtime.database_id] = []
        self._queue(coordinator, runtime, self._bid_locked_execution, results, "drain")
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(
            coordinator._mutation_drain_failures[runtime.database_id],
            ["The active bid is locked"],
        )
        self.assertEqual(results[0].rejection_reason, "bid_locked")

    def test_other_non_committed_results_never_gain_a_reason(self):
        for status in (
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        ):
            with self.subTest(status=status):
                coordinator, runtime = self.ready_coordinator(store=_LockingStore())
                results = []
                self._queue(
                    coordinator,
                    runtime,
                    lambda status=status: MutationExecutionResult(
                        outcome_status=status, message="no reason"
                    ),
                    results,
                    "plain",
                )
                coordinator._process_mutation_requests(runtime)
                self.assertEqual(results[0].outcome_status, status)
                self.assertIsNone(results[0].rejection_reason)
                self.assertEqual(results[0].message, "no reason")

    def test_the_real_service_result_builder_hands_the_reason_to_the_real_coordinator(
        self,
    ):
        # Chain: executor DatabaseMutationResult(REJECTED, bid_locked) -> the real
        # ProjectWriteService result builder -> the real coordinator work loop ->
        # the QueuedMutationResult the caller's callback receives.
        from dataclasses import replace as dataclass_replace
        from tests.application.services.test_project_write_service import _Harness

        harness = _Harness()
        harness.executor.status = MutationOutcomeStatus.REJECTED
        harness.executor.rejection_reason = MutationRejectionReason.BID_LOCKED
        harness.service.queue_bid_job_status_update(
            _Harness.DATABASE, "7", "2", lambda _result: None
        )
        queued, execute, _callback = harness.provider.requests[-1]
        coordinator, runtime = self.ready_coordinator(store=_LockingStore())
        results = []
        request = dataclass_replace(queued, database_id=runtime.database_id)
        coordinator.queue_request(request, execute, results.append)
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].operation_id, queued.operation_id)
        self.assertEqual(results[0].outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertIs(results[0].rejection_reason, MutationRejectionReason.BID_LOCKED)
        self.assertEqual(results[0].message, "The active bid is locked")
        self.assertIsNone(results[0].conflict)
        self.assertFalse(results[0].commit_attempted)
        self.assertEqual(
            harness.executor.requests[-1].resources[0].resource_type, "bid"
        )

    # Decision B4: the coordinator tells the UI about a bid_locked refusal.
    def test_a_bid_locked_rejection_publishes_one_event_after_its_callback(self):
        events = _EventBus()
        coordinator, runtime = self.ready_coordinator(
            store=_LockingStore(), event_bus=events
        )
        order = []
        results = []

        def callback(result):
            order.append("callback")
            results.append(result)

        original_publish = events.publish

        def recording_publish(event, **payload):
            if event is AppEvents.BID_LOCKED_REJECTION:
                order.append("event")
            original_publish(event, **payload)

        events.publish = recording_publish
        _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            self._bid_locked_execution,
            callback,
            operation_id="locked-event",
        )
        coordinator._process_mutation_requests(runtime)
        coordinator._process_mutation_requests(runtime)
        locked_events = [
            payload
            for event, payload in events.published
            if event is AppEvents.BID_LOCKED_REJECTION
        ]
        self.assertEqual(
            locked_events,
            [
                {
                    "database_id": runtime.database_id,
                    "operation_id": results[0].operation_id,
                }
            ],
        )
        # the callback reverts its optimistic state first, the UI hook runs after it
        self.assertEqual(order, ["callback", "event"])
        self.assertEqual(len(results), 1)
        # still no conflict, no recovery
        self.assertNotIn(
            AppEvents.SYNCHRONIZATION_CONFLICT, {event for event, _ in events.published}
        )
        self.assertFalse(runtime.recovery_requested)

    def test_only_a_bid_locked_rejection_publishes_the_event(self):
        events = _EventBus()
        coordinator, runtime = self.ready_coordinator(
            store=_LockingStore(), event_bus=events
        )
        results = []
        for name, work in (
            (
                "plain",
                lambda: MutationExecutionResult(
                    outcome_status=MutationOutcomeStatus.REJECTED, message="busy"
                ),
            ),
            (
                "failed",
                lambda: MutationExecutionResult(
                    outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                    message="down",
                ),
            ),
            ("committed", lambda: _committed_execution("501")),
        ):
            self._queue(coordinator, runtime, work, results, name)
        for _ in range(3):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(len(results), 3)
        self.assertNotIn(
            AppEvents.BID_LOCKED_REJECTION, {event for event, _ in events.published}
        )


_TERMINAL_STATUSES = frozenset(
    {
        MutationOutcomeStatus.COMMITTED,
        MutationOutcomeStatus.REJECTED,
        MutationOutcomeStatus.CONFLICT,
        MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        MutationOutcomeStatus.CANCELLED_BEFORE_START,
    }
)
_INTERIM_STATUSES = frozenset(
    {
        MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
        MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
    }
)


class _DeliveryLog:
    """Every callback delivery, per submission, in the order the callback saw it.
    A delivery that raised is kept: the coordinator re-delivers a COMMITTED whose
    callback failed, so only a delivery that did not raise closes an id."""

    def __init__(self):
        self.entries = []

    def callback(self, submission, *, raise_mode="none"):
        seen = []

        def deliver(result):
            raised = (
                raise_mode == "first"
                and not seen
                or raise_mode == "first_committed"
                and result.outcome_status == MutationOutcomeStatus.COMMITTED
                and not any(
                    earlier.outcome_status == MutationOutcomeStatus.COMMITTED
                    for earlier in seen
                )
            )
            seen.append(result)
            self.entries.append(
                (submission, result.operation_id, result.outcome_status, raised)
            )
            if raised:
                raise RuntimeError("the completion callback failed")

        return deliver

    def sequences(self):
        grouped = {}
        for submission, operation_id, status, raised in self.entries:
            grouped.setdefault((submission, operation_id), []).append((status, raised))
        return grouped


def _violations_of_the_terminal_status_contract(sequences):
    problems = []
    for key, deliveries in sequences.items():
        statuses = [status for status, _raised in deliveries]
        terminals = [status for status in statuses if status in _TERMINAL_STATUSES]
        if len(set(terminals)) > 1:
            problems.append((key, "two different terminal statuses", statuses))
        closing = [
            index
            for index, (status, raised) in enumerate(deliveries)
            if status in _TERMINAL_STATUSES
            and not (status == MutationOutcomeStatus.COMMITTED and raised)
        ]
        if len(closing) != 1:
            problems.append((key, "not exactly one closing terminal", statuses))
        elif closing[0] != len(deliveries) - 1:
            problems.append((key, "delivery after the terminal status", statuses))
        else:
            for status, raised in deliveries[: closing[0]]:
                if status not in _INTERIM_STATUSES and not (
                    status == MutationOutcomeStatus.COMMITTED and raised
                ):
                    problems.append(
                        (key, "non-interim status before terminal", statuses)
                    )
    return problems


class SqlCollaborationOperationTerminalStatusContractTests(_SecondPassBase):
    """Decision R3: one operation id never reports two different terminal statuses.
    Terminal: COMMITTED, REJECTED, CONFLICT, FAILED_BEFORE_COMMIT and
    CANCELLED_BEFORE_START (the coordinator finishes the pending entry and the
    journal record). Interim: COMMIT_STATUS_UNKNOWN and COMMITTED_PROJECTION_FAILED
    (the entry stays UNCERTAIN / RECOVERING with its callback until the recovery
    delivers the ONE terminal). The contract is per submission: a duplicate
    submission of a live id is a second, rejected submission with its own callback.
    This is what makes window._sql_completion_was_applied's status test redundant
    for ids that production generates with uuid4. Scenarios run the real coordinator
    synchronously (no worker thread; _process_mutation_requests and the worker's
    reset/recovery sequence are driven by the test); the SQL store, writer and
    reconciliation are fakes, so the server-side half of the contract (the marker
    decides committed vs not committed) is only as strong as those fakes."""

    WORKS = (
        "commit",
        "unknown_committed",
        "unknown_lost",
        "failed_before_commit",
        "rejected",
        "bid_locked",
        "conflict",
    )
    PRE_EVENTS = ("none", "cancel", "cancel_twice", "stop", "trust_loss", "duplicate")
    POST_EVENTS = ("none", "trust_loss", "late_cancel", "duplicate")
    PROJECTIONS = ("immediate", "deferred_ok", "deferred_failed")
    RAISE_MODES = ("none", "first", "first_committed")

    @staticmethod
    def execution_for(work, database_id):
        if work == "commit":
            return _committed_execution("501")
        if work.startswith("unknown"):
            return _unknown_commit()
        if work == "conflict":
            conflict = SynchronizationConflict(
                database_id,
                ResourceRef("takeoffs_collection", "8", 8),
                "changed by another session",
            )
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.CONFLICT,
                message=conflict.reason,
                conflict=conflict,
            )
        return MutationExecutionResult(
            outcome_status=(
                MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                if work == "failed_before_commit"
                else MutationOutcomeStatus.REJECTED
            ),
            message="refused",
            rejection_reason=(
                MutationRejectionReason.BID_LOCKED if work == "bid_locked" else None
            ),
        )

    def recover(self, coordinator, runtime):
        coordinator._reset_session(runtime)
        with runtime.lock:
            runtime.recovery_requested = False
            runtime.recovery_ready = False
            runtime.pending_delivery = False
        session_generation = coordinator._install_session(
            runtime, DatabaseSession(runtime.database_id, str(uuid.uuid4()))
        )
        coordinator._recover_journaled_operations(runtime)
        coordinator._on_session_started(
            (
                runtime.database_id,
                runtime.generation,
                session_generation,
                HydratedDatabaseChangeBatch(_batch(runtime.database_id, "epoch", 0, 0)),
                None,
            )
        )

    def run_scenario(self, work, pre, projection, post, raise_mode, delayed, log):
        dispatcher = _DelayedMutationDispatcher() if delayed else _Dispatcher()
        reconciliation = (
            _Reconciliation()
            if projection == "immediate"
            else _FailFirstLocalProjectionReconciliation()
        )
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(
            store=store,
            journal=journal,
            dispatcher=dispatcher,
            reconciliation=reconciliation,
        )
        database_id = runtime.database_id
        writes = []

        def operation():
            writes.append("write")
            return self.execution_for(work, database_id)

        _queue_test_mutation(
            coordinator,
            database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            operation,
            log.callback("original", raise_mode=raise_mode),
            operation_id="terminal-contract",
        )
        request = coordinator._pending_mutations.for_database(database_id)[0].request
        if work in ("commit", "unknown_committed"):
            store.durable_results[request.operation_id] = _durable_result(
                request, "501"
            )
        duplicates = []

        def duplicate():
            if coordinator._pending_mutations.get(request.operation_id) is None:
                return
            duplicates.append(None)
            coordinator.queue_request(
                request,
                operation,
                log.callback(f"duplicate-{len(duplicates)}"),
            )

        def event(name):
            if name == "cancel":
                coordinator.cancel_queued_mutation(database_id, request.operation_id)
            elif name == "cancel_twice":
                for _ in range(2):
                    coordinator.cancel_queued_mutation(
                        database_id, request.operation_id
                    )
            elif name == "stop":
                coordinator._reset_session(runtime)
            elif name == "trust_loss":
                coordinator._on_reconciliation_required(
                    (database_id, runtime.generation, "trust lost")
                )
            elif name == "late_cancel":
                coordinator.cancel_queued_mutation(database_id, request.operation_id)
            elif name == "duplicate":
                duplicate()

        event(pre)
        try:
            coordinator._process_mutation_requests(runtime)
        except DatabaseCatalogError:
            pass
        event(post)
        token = getattr(reconciliation, "token", None)
        if token is not None:
            token.complete(projection == "deferred_ok")
        if delayed:
            dispatcher.deliver_pending()
        for _ in range(3):
            if not coordinator._pending_mutations.for_database(database_id):
                break
            self.recover(coordinator, runtime)
            if delayed:
                dispatcher.deliver_pending()
        return coordinator, journal, writes, request

    def scenarios(self):
        for work in self.WORKS:
            for pre in self.PRE_EVENTS:
                for projection in self.PROJECTIONS:
                    if projection != "immediate" and work != "commit":
                        continue
                    for post in self.POST_EVENTS:
                        for raise_mode in self.RAISE_MODES:
                            for delayed in (False, True):
                                yield work, pre, projection, post, raise_mode, delayed

    def test_the_status_classification_matches_what_the_coordinator_finishes(self):
        self.assertEqual(
            _TERMINAL_STATUSES | _INTERIM_STATUSES, set(MutationOutcomeStatus)
        )
        self.assertEqual(_TERMINAL_STATUSES & _INTERIM_STATUSES, set())
        for status in MutationOutcomeStatus:
            with self.subTest(status=status):
                coordinator, runtime = self.ready_coordinator()
                journal = coordinator._operation_journal
                _queue_test_mutation(
                    coordinator,
                    runtime.database_id,
                    (ResourceRef("takeoffs_collection", "8", 8),),
                    lambda: None,
                    lambda _result: None,
                    operation_id="classification",
                )
                request = coordinator._pending_mutations.for_database(
                    runtime.database_id
                )[0].request
                coordinator._pending_mutations.transition(
                    request.operation_id,
                    PendingMutationState.EXECUTING,
                )
                coordinator._complete_mutation_request(
                    (
                        lambda _result: None,
                        QueuedMutationResult(
                            database_id=runtime.database_id,
                            runtime_generation=runtime.generation,
                            operation_id=request.operation_id,
                            outcome_status=status,
                            commit_attempted=True,
                        ),
                    )
                )
                remains = (
                    coordinator._pending_mutations.get(request.operation_id) is not None
                )
                self.assertEqual(remains, status in _INTERIM_STATUSES)
                self.assertEqual(request.operation_id in journal.records, remains)
                self.assertEqual(
                    request.operation_id in coordinator._uncertain_callbacks, remains
                )

    def test_every_bounded_event_order_ends_with_exactly_one_terminal_status(self):
        observed = set()
        problems = []
        count = 0
        quiet = patch(
            "ost_visualizer.application.services.sql_collaboration_coordinator.logger"
        )
        quiet.start()
        self.addCleanup(quiet.stop)
        for scenario in self.scenarios():
            count += 1
            log = _DeliveryLog()
            coordinator, journal, writes, request = self.run_scenario(*scenario, log)
            sequences = log.sequences()
            problems.extend(
                (scenario, *problem)
                for problem in _violations_of_the_terminal_status_contract(sequences)
            )
            if len(writes) > 1:
                problems.append((scenario, "the write was replayed", writes))
            if coordinator._pending_mutations.for_database(request.database_id):
                problems.append((scenario, "the operation never settled", ()))
            if journal.records or coordinator._uncertain_callbacks:
                problems.append((scenario, "recovery metadata was leaked", ()))
            self.assertIn(("original", request.operation_id), sequences, scenario)
            observed.add(
                tuple(
                    (status.value, raised)
                    for status, raised in sequences[("original", request.operation_id)]
                )
            )
        self.assertEqual(problems, [])
        self.assertEqual(count, (3 + 6 * 1) * 6 * 4 * 3 * 2)
        self.assertEqual(observed, self.EXPECTED_SEQUENCES)

    EXPECTED_SEQUENCES = {
        (("cancelled_before_start", False),),
        (("cancelled_before_start", True),),
        (("commit_status_unknown", False), ("committed", False)),
        (("commit_status_unknown", False), ("committed", True), ("committed", False)),
        (("commit_status_unknown", False), ("failed_before_commit", False)),
        (("commit_status_unknown", True), ("committed", False)),
        (("commit_status_unknown", True), ("failed_before_commit", False)),
        (("committed", False),),
        (("committed", True), ("committed", False)),
        (("committed_projection_failed", False), ("committed", False)),
        (
            ("committed_projection_failed", False),
            ("committed", True),
            ("committed", False),
        ),
        (("committed_projection_failed", True), ("committed", False)),
        (("conflict", False),),
        (("conflict", True),),
        (("failed_before_commit", False),),
        (("failed_before_commit", True),),
        (("rejected", False),),
        (("rejected", True),),
    }

    def queue_one(self, coordinator, runtime, operation, log, name):
        _queue_test_mutation(
            coordinator,
            runtime.database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            operation,
            log.callback("original"),
            operation_id=name,
        )
        return [
            pending.request
            for pending in coordinator._pending_mutations.for_database(
                runtime.database_id
            )
            if pending.request.payload["test_operation"] == name
        ][0]

    def test_a_duplicate_submission_of_a_live_id_is_rejected_without_touching_the_original(
        self,
    ):
        store = _RecoverableProjectionStore()
        journal = _PendingOperationJournal()
        coordinator, runtime = self.ready_coordinator(store=store, journal=journal)
        log = _DeliveryLog()
        writes = []
        request = self.queue_one(
            coordinator,
            runtime,
            lambda: writes.append("original") or _unknown_commit(),
            log,
            "duplicated",
        )
        store.durable_results[request.operation_id] = _durable_result(request, "501")
        original_entry = coordinator._pending_mutations.get(request.operation_id)
        original_record = journal.records[request.operation_id]
        attempts = []

        def duplicate():
            attempts.append(None)
            return coordinator.queue_request(
                request,
                lambda: writes.append("duplicate") or _committed_execution("999"),
                log.callback(f"duplicate-{len(attempts)}"),
            )

        self.assertEqual(duplicate(), -1)
        self.assertIs(
            coordinator._pending_mutations.get(request.operation_id), original_entry
        )
        self.assertIs(journal.records[request.operation_id], original_record)
        self.assertEqual(runtime.mutation_requests.qsize(), 1)
        with self.assertRaises(DatabaseCatalogError):
            coordinator._process_mutation_requests(runtime)
        self.assertEqual(duplicate(), -1)
        self.assertEqual(
            coordinator._pending_mutations.get(request.operation_id).state,
            PendingMutationState.UNCERTAIN,
        )
        self.assertEqual(set(coordinator._uncertain_callbacks), {request.operation_id})
        self.recover(coordinator, runtime)
        self.assertEqual(writes, ["original"])
        sequences = log.sequences()
        self.assertEqual(
            sequences,
            {
                ("original", request.operation_id): [
                    (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, False),
                    (MutationOutcomeStatus.COMMITTED, False),
                ],
                ("duplicate-1", request.operation_id): [
                    (MutationOutcomeStatus.REJECTED, False)
                ],
                ("duplicate-2", request.operation_id): [
                    (MutationOutcomeStatus.REJECTED, False)
                ],
            },
        )
        self.assertEqual(_violations_of_the_terminal_status_contract(sequences), [])
        self.assertEqual(
            coordinator._pending_mutations.for_database(runtime.database_id), ()
        )
        self.assertEqual(journal.records, {})

    def test_cancel_is_refused_once_execution_started_and_after_any_terminal_status(
        self,
    ):
        coordinator, runtime = self.ready_coordinator()
        log = _DeliveryLog()
        database_id = runtime.database_id
        during_execution = []
        started = []

        def operation():
            during_execution.append(
                coordinator.cancel_queued_mutation(database_id, started[0].operation_id)
            )
            return _committed_execution("501")

        started.append(self.queue_one(coordinator, runtime, operation, log, "started"))
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(during_execution, [False])
        self.assertFalse(
            coordinator.cancel_queued_mutation(database_id, started[0].operation_id)
        )
        self.assertEqual(
            log.sequences(),
            {
                ("original", started[0].operation_id): [
                    (MutationOutcomeStatus.COMMITTED, False)
                ]
            },
        )
        waiting = self.queue_one(
            coordinator, runtime, lambda: _committed_execution("502"), log, "waiting"
        )
        for _ in range(2):
            self.assertTrue(
                coordinator.cancel_queued_mutation(database_id, waiting.operation_id)
            )
        coordinator._process_mutation_requests(runtime)
        self.assertFalse(
            coordinator.cancel_queued_mutation(database_id, waiting.operation_id)
        )
        self.assertFalse(
            coordinator.cancel_queued_mutation(database_id, "never-queued")
        )
        coordinator._process_mutation_requests(runtime)
        self.assertEqual(
            log.sequences()[("original", waiting.operation_id)],
            [(MutationOutcomeStatus.CANCELLED_BEFORE_START, False)],
        )
        self.assertEqual(
            _violations_of_the_terminal_status_contract(log.sequences()), []
        )

    def test_a_recovered_result_dispatched_twice_reaches_the_callback_once(self):
        store = _RecoverableProjectionStore()
        dispatcher = _DelayedMutationDispatcher()
        coordinator, runtime = self.ready_coordinator(
            store=store, dispatcher=dispatcher
        )
        log = _DeliveryLog()
        request = self.queue_one(
            coordinator, runtime, _unknown_commit, log, "dispatched-twice"
        )
        store.durable_results[request.operation_id] = _durable_result(request, "501")
        with self.assertRaises(DatabaseCatalogError):
            coordinator._process_mutation_requests(runtime)
        dispatcher.deliver_pending()
        self.recover(coordinator, runtime)
        recovered = [
            (callback, payload)
            for callback, payload in dispatcher.pending
            if callback.__name__ == "_complete_recovered_mutation_request"
        ]
        self.assertEqual(len(recovered), 1)
        dispatcher.deliver_pending()
        for callback, payload in recovered:
            callback(payload)
        self.assertEqual(
            log.sequences(),
            {
                ("original", request.operation_id): [
                    (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, False),
                    (MutationOutcomeStatus.COMMITTED, False),
                ]
            },
        )

    def test_an_uncertain_operation_survives_a_stop_and_a_restart_and_resolves_once(
        self,
    ):
        class _HeldMarkerStore(_RecoverableProjectionStore):
            def __init__(self):
                super().__init__()
                self.hold = True
                self.held_lookups = 0

            def query_operation(self, database_id, operation_id):
                if self.hold:
                    self.held_lookups += 1
                    raise DatabaseCatalogError(
                        "The commit marker is not readable yet.", retryable=True
                    )
                return super().query_operation(database_id, operation_id)

        store = _HeldMarkerStore()
        coordinator, descriptor, _store, events, _capabilities = (
            self.threaded_coordinator(store=store)
        )
        database_id = descriptor.database_id
        healthy = _state_signal(events, database_id, SynchronizationState.HEALTHY)
        self.assertTrue(coordinator.start_database(database_id))
        self.assertTrue(healthy.wait(2))
        log = _DeliveryLog()
        writes = []
        unknown_seen = threading.Event()
        record = log.callback("original")

        def callback(result):
            record(result)
            unknown_seen.set()

        _queue_test_mutation(
            coordinator,
            database_id,
            (ResourceRef("takeoffs_collection", "8", 8),),
            lambda: writes.append("write") or _unknown_commit(),
            callback,
            operation_id="uncertain-across-restart",
        )
        request = coordinator._pending_mutations.for_database(database_id)[0].request
        self.assertTrue(unknown_seen.wait(3))
        deadline = time.monotonic() + 3
        while store.held_lookups < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(store.held_lookups, 2)
        _stop_database(coordinator, database_id)
        self.assertEqual(
            log.sequences(),
            {
                ("original", request.operation_id): [
                    (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, False)
                ]
            },
        )
        self.assertEqual(
            coordinator._pending_mutations.get(request.operation_id).state,
            PendingMutationState.UNCERTAIN,
        )
        self.assertEqual(set(coordinator._uncertain_callbacks), {request.operation_id})
        store.durable_results[request.operation_id] = _durable_result(request, "501")
        store.hold = False
        resolved = threading.Event()
        events.subscribe(
            AppEvents.COLLABORATION_MUTATION_STATE_CHANGED,
            lambda **payload: (
                resolved.set()
                if payload["operation_id"] == request.operation_id
                and payload["state"] == PendingMutationState.QUEUED.value
                else None
            ),
        )
        self.assertTrue(coordinator.start_database(database_id))
        self.assertTrue(resolved.wait(3))
        self.assertEqual(writes, ["write"])
        self.assertEqual(
            log.sequences(),
            {
                ("original", request.operation_id): [
                    (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, False),
                    (MutationOutcomeStatus.COMMITTED, False),
                ]
            },
        )
        self.assertEqual(coordinator._uncertain_callbacks, {})
        self.assertEqual(coordinator._pending_mutations.for_database(database_id), ())

    def test_submissions_that_cannot_be_queued_report_one_rejection_and_leave_no_entry(
        self,
    ):
        for label in ("read_only", "journal_failure", "no_runtime", "stopped"):
            with self.subTest(label):
                journal = (
                    _FailingPendingOperationJournal(1)
                    if label == "journal_failure"
                    else _PendingOperationJournal()
                )
                coordinator, runtime = self.ready_coordinator(journal=journal)
                database_id = runtime.database_id
                if label == "read_only":
                    coordinator._capabilities.set_collaboration_state(
                        database_id, SynchronizationState.READ_ONLY
                    )
                elif label == "no_runtime":
                    coordinator._runtimes.pop(database_id)
                elif label == "stopped":
                    runtime.stop_event.set()
                log = _DeliveryLog()
                _queue_test_mutation(
                    coordinator,
                    database_id,
                    (ResourceRef("takeoffs_collection", "8", 8),),
                    lambda: _committed_execution("501"),
                    log.callback("original"),
                    operation_id=label,
                )
                ((_key, deliveries),) = log.sequences().items()
                self.assertEqual(deliveries, [(MutationOutcomeStatus.REJECTED, False)])
                self.assertEqual(
                    coordinator._pending_mutations.for_database(database_id), ()
                )
                self.assertEqual(journal.records, {})
                self.assertTrue(runtime.mutation_requests.empty())
                self.assertEqual(
                    _violations_of_the_terminal_status_contract(log.sequences()), []
                )
