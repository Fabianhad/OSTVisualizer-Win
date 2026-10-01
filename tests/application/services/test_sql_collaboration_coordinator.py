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
        self, *, store=None, reconciliation=None, journal=None, cleanup_success=True
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
            _Dispatcher(),
            reconciliation if reconciliation is not None else _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            tokens,
            drafts,
            _EventBus(),
            SQL_SCHEMA_V1.version,
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
        for success in (False, True):
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
        self.assertIn("event unsubscription failed", results[0][1])
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
            self.assertRaisesRegex(DatabaseCatalogError, "recovery record"),
            self.assertLogs(
                "ost_visualizer.application.services.sql_collaboration_coordinator",
                level="ERROR",
            ),
        ):
            coordinator._process_mutation_requests(runtime)
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
        self.assertFalse(coordinator.start_database("not-registered"))
        self.assertFalse(coordinator.start_database(access_descriptor.database_id))
        self.assertFalse(coordinator.start_database(unversioned_descriptor.database_id))
        self.assertFalse(coordinator.start_database(future_descriptor.database_id))
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
            self.assertFalse(coordinator.start_database(sql_descriptor.database_id))
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
        self.assertFalse(coordinator.start_database(descriptor.database_id))
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
        self.assertFalse(coordinator.start_database(descriptor.database_id))
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
        self.assertFalse(coordinator.start_database(descriptor.database_id))
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
            "null source uid": json.dumps(
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
