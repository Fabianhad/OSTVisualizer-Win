import threading
import unittest
import uuid
from types import SimpleNamespace
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
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
    _QueuedMutation,
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
    _COORDINATOR_TYPE,
    _CollaborationStore,
    _ConflictingMutationExecutor,
    _DelayedMutationDispatcher,
    _EventBus,
    _PendingOperationJournal,
    _PermissionProbe,
    _Reconciliation,
    _RemoteReader,
    _TokenReader,
    _batch,
    _coordinator,
    _shutdown_coordinator,
    _token_service,
)


class WriteTokenOrderingCollaborationTests(unittest.TestCase):
    def test_queued_mutation_conflict_is_published_only_after_qt_dispatch(self):
        database_id = "database"
        resource = ResourceRef("takeoffs_collection", "8", 8)
        conflict = SynchronizationConflict(
            database_id,
            resource,
            "stale takeoff collection",
        )
        events = _EventBus()
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda *_args: True
        )
        service._event_bus = events
        service._mutation_executor = _ConflictingMutationExecutor(conflict)
        service._session_registry = DatabaseSessionRegistry()
        service._concurrency_tokens, _drafts = _token_service()
        mutation = service._execute_database_mutation(
            database_id,
            (resource,),
            lambda _recorder: True,
            publish_conflict_event=False,
        )
        self.assertEqual(mutation.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(events.published, [])
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
        coordinator = _coordinator(
            descriptors,
            _CollaborationStore(),
            _RemoteReader(),
            dispatcher,
            _Reconciliation(),
            capabilities,
            DatabaseSessionRegistry(),
            service._concurrency_tokens,
            _drafts,
            events,
            SQL_SCHEMA_V1.version,
        )
        runtime = _DatabaseRuntime(descriptor.database_id, 1)
        runtime.healthy = True
        coordinator._runtimes[descriptor.database_id] = runtime
        callback_results = []
        callback_threads = []
        event_threads = []
        delivery_order = []
        events.subscribe(
            AppEvents.SYNCHRONIZATION_CONFLICT,
            lambda **_payload: (
                event_threads.append(threading.get_ident()),
                delivery_order.append("conflict"),
            ),
        )
        coordinator._dispatch_mutation_result(
            lambda result: (
                callback_results.append(result),
                callback_threads.append(threading.get_ident()),
                delivery_order.append("completion"),
            ),
            QueuedMutationResult(
                database_id=descriptor.database_id,
                runtime_generation=runtime.generation,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
                message=conflict.reason,
                conflict=conflict,
            ),
        )
        self.assertEqual(events.published, [])
        dispatch_thread = threading.get_ident()
        dispatcher.deliver_pending()
        self.assertEqual(callback_threads, [dispatch_thread])
        self.assertEqual(event_threads, [dispatch_thread])
        self.assertEqual(delivery_order, ["completion", "conflict"])
        self.assertEqual(callback_results[0].conflict, conflict)
        _shutdown_coordinator(coordinator)

    def test_many_rapid_local_mutations_advance_expected_token_each_commit(self):
        database_id = "database"
        resource = ResourceRef("takeoffs_collection", "8", 8)
        initial = ConcurrencyToken((1).to_bytes(8, "big"))
        tokens, _drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")

        class _AdvancingExecutor:
            def __init__(self):
                self.current = initial
                self.expected = []

            def execute(self, request, _operation):
                presented = request.expected_versions[0].expected
                self.expected.append(presented)
                if presented != self.current:
                    return DatabaseMutationResult(
                        operation_id=request.operation_id,
                        outcome_status=MutationOutcomeStatus.CONFLICT,
                        conflict=SynchronizationConflict(
                            database_id,
                            resource,
                            "stale takeoff collection",
                            expected=presented,
                            actual=self.current,
                            kind=SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY,
                        ),
                    )
                self.current = ConcurrencyToken(
                    (int.from_bytes(self.current.value, "big") + 1).to_bytes(8, "big")
                )
                return DatabaseMutationResult(
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    value=True,
                    resulting_versions={resource: self.current},
                )

        executor = _AdvancingExecutor()
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda *_args: True
        )
        service._event_bus = _EventBus()
        service._mutation_executor = executor
        service._session_registry = DatabaseSessionRegistry()
        service._session_registry.register(database_id, "session")
        service._concurrency_tokens = tokens
        for _index in range(100):
            result = service._execute_database_mutation(
                database_id, (resource,), lambda _recorder: True
            )
            self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executor.expected[0], initial)
        self.assertEqual(
            executor.expected[-1], ConcurrencyToken((100).to_bytes(8, "big"))
        )

    def test_write_services_share_one_database_token_mutation_scope(self):
        database_id = "database"
        resource = ResourceRef("takeoffs_collection", "8", 8)
        initial = ConcurrencyToken((1).to_bytes(8, "big"))
        tokens, _drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")

        class _OverlapDetectingExecutor:
            def __init__(self):
                self.current = initial
                self.active = False
                self.overlap = False
                self.first_entered = threading.Event()
                self.release_first = threading.Event()
                self.lock = threading.Lock()

            def execute(self, request, _operation):
                with self.lock:
                    if self.active:
                        self.overlap = True
                        self.release_first.set()
                    self.active = True
                    first = not self.first_entered.is_set()
                    self.first_entered.set()
                if first:
                    self.release_first.wait(0.2)
                presented = request.expected_versions[0].expected
                success = presented == self.current
                if success:
                    self.current = ConcurrencyToken(
                        (int.from_bytes(self.current.value, "big") + 1).to_bytes(
                            8, "big"
                        )
                    )
                with self.lock:
                    self.active = False
                return DatabaseMutationResult(
                    operation_id=request.operation_id,
                    outcome_status=(
                        MutationOutcomeStatus.COMMITTED
                        if success
                        else MutationOutcomeStatus.CONFLICT
                    ),
                    value=success,
                    resulting_versions={resource: self.current} if success else {},
                )

        executor = _OverlapDetectingExecutor()
        sessions = DatabaseSessionRegistry()
        sessions.register(database_id, "session")

        def service():
            instance = ProjectWriteService.__new__(ProjectWriteService)
            instance._database_capability_service = SimpleNamespace(
                is_editable=lambda *_args: True
            )
            instance._event_bus = _EventBus()
            instance._mutation_executor = executor
            instance._session_registry = sessions
            instance._concurrency_tokens = tokens
            return instance

        services = (service(), service())
        start = threading.Barrier(3)
        results = []

        def mutate(instance):
            start.wait()
            results.append(
                instance._execute_database_mutation(
                    database_id, (resource,), lambda _recorder: True
                )
            )

        workers = [
            threading.Thread(target=mutate, args=(instance,)) for instance in services
        ]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join(2)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertFalse(executor.overlap)
        self.assertEqual(len(results), 2)
        self.assertTrue(
            all(
                result.outcome_status == MutationOutcomeStatus.COMMITTED
                for result in results
            )
        )
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
            ConcurrencyToken((3).to_bytes(8, "big")),
        )

    def test_database_token_clear_waits_for_inflight_mutation(self):
        database_id = "database"
        resource = ResourceRef("takeoffs_collection", "8", 8)
        initial = ConcurrencyToken((1).to_bytes(8, "big"))
        tokens, _drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        entered = threading.Event()
        release = threading.Event()

        class _BlockingExecutor:
            def execute(self, request, _operation):
                entered.set()
                if not release.wait(2):
                    raise AssertionError("blocked mutation was not released")
                return DatabaseMutationResult(
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    value=True,
                    resulting_versions={
                        resource: ConcurrencyToken((2).to_bytes(8, "big"))
                    },
                )

        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda *_args: True
        )
        service._event_bus = _EventBus()
        service._mutation_executor = _BlockingExecutor()
        service._session_registry = DatabaseSessionRegistry()
        service._session_registry.register(database_id, "session")
        service._concurrency_tokens = tokens
        mutation = threading.Thread(
            target=lambda: service._execute_database_mutation(
                database_id, (resource,), lambda _recorder: True
            )
        )
        cleared = threading.Event()
        mutation.start()
        self.assertTrue(entered.wait(1))
        clearing = threading.Thread(
            target=lambda: (tokens.clear_database(database_id), cleared.set())
        )
        clearing.start()
        self.assertFalse(cleared.wait(0.05))
        release.set()
        mutation.join(2)
        clearing.join(2)
        self.assertTrue(cleared.is_set())
        self.assertEqual(tokens.tokens_for_resources(database_id, (resource,)), ())

    def test_authoritative_token_reload_waits_for_inflight_mutation(self):
        database_id = "database"
        resource = ResourceRef("takeoffs_collection", "8", 8)
        initial = ConcurrencyToken((1).to_bytes(8, "big"))
        committed = ConcurrencyToken((2).to_bytes(8, "big"))

        class _ObservedReader(_TokenReader):
            def __init__(self):
                super().__init__({resource: initial})
                self.entered = threading.Event()

            def read_bid_versions(self, database_id, bid_uid):
                self.entered.set()
                return super().read_bid_versions(database_id, bid_uid)

        reader = _ObservedReader()
        tokens, _drafts = _token_service(reader)
        tokens.load_bid(database_id, "8")
        reader.entered.clear()
        mutation_entered = threading.Event()
        release_mutation = threading.Event()

        class _BlockingExecutor:
            def execute(self, request, _operation):
                mutation_entered.set()
                if not release_mutation.wait(2):
                    raise AssertionError("blocked mutation was not released")
                reader.resources[resource] = committed
                return DatabaseMutationResult(
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    value=True,
                    resulting_versions={resource: committed},
                )

        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda *_args: True
        )
        service._event_bus = _EventBus()
        service._mutation_executor = _BlockingExecutor()
        service._session_registry = DatabaseSessionRegistry()
        service._session_registry.register(database_id, "session")
        service._concurrency_tokens = tokens
        mutation = threading.Thread(
            target=lambda: service._execute_database_mutation(
                database_id, (resource,), lambda _recorder: True
            )
        )
        reload_complete = threading.Event()
        mutation.start()
        self.assertTrue(mutation_entered.wait(1))
        reload = threading.Thread(
            target=lambda: (
                tokens.load_bid(database_id, "8"),
                reload_complete.set(),
            )
        )
        reload.start()
        self.assertFalse(reader.entered.wait(0.05))
        self.assertFalse(reload_complete.is_set())
        release_mutation.set()
        mutation.join(2)
        reload.join(2)
        self.assertTrue(reload_complete.is_set())
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
            committed,
        )
