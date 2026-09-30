from ost_visualizer.application.services.base_write_service import (
    DatabaseMutationWriteService,
)
from ost_visualizer.application.interfaces.i_mdb_connection_manager import (
    DatabaseConnectionUnavailableError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    ResourceRef,
)
from contextlib import contextmanager
import uuid
import unittest
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
from ost_visualizer.application.services.database_concurrency_token_service import (
    DatabaseConcurrencyTokenService,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from tests.helpers.sql.collaboration import (
    _ConflictingMutationExecutor,
    _EventBus,
    _TokenReader,
    _token_service,
)
from contextlib import nullcontext
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
    ResourceRef,
)
from tests.application.services.write_access_support import (
    _CapabilityService as _write_access_support__CapabilityService,
    _ConcurrencyTokens as _write_access_support__ConcurrencyTokens,
    _EventBus as _write_access_support__EventBus,
    _MutationExecutor as _write_access_support__MutationExecutor,
    _SessionRegistry as _write_access_support__SessionRegistry,
)


class _UnavailableMutationExecutor:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    def execute(self, _request, _operation):
        self.calls += 1
        raise DatabaseConnectionUnavailableError(self.message)


class _MutationScope:
    def __init__(self) -> None:
        self.applied = []

    @contextmanager
    def mutation_scope(self, _database_id):
        yield

    def ensure_resources_loaded(self, _database_id, _resources):
        pass

    def expected_versions(self, _database_id, _resources):
        return {}

    def apply_result(self, database_id, versions):
        self.applied.append((database_id, versions))


class DatabaseMutationConnectionFailureTests(unittest.TestCase):
    def test_mutation_service_returns_failed_result_for_connection_exhaustion(self):
        message = "Restart OST Visualizer and try again."
        executor = _UnavailableMutationExecutor(message)
        concurrency = _MutationScope()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=type(
                "EventBus", (), {"publish": lambda *_args, **_kwargs: None}
            )(),
            mutation_executor=executor,
            session_registry=type(
                "SessionRegistry",
                (),
                {
                    "get": lambda _self, _database_id: None,
                    "lock_tokens": lambda _self, _database_id, _resources: (),
                },
            )(),
            concurrency_tokens=concurrency,
            database_capability_service=type(
                "Capability",
                (),
                {"is_editable": lambda _self, _database_id, _resource=None: True},
            )(),
        )
        result = service._execute_database_mutation(
            "exhausted.mdb",
            (ResourceRef("takeoffs_collection", "7", 7),),
            lambda _recorder: ["99"],
            operation_id=str(uuid.uuid4()),
        )
        self.assertEqual(
            result.outcome_status,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        )
        self.assertEqual(result.failure_reason, message)
        self.assertFalse(result.commit_attempted)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(concurrency.applied, [])


class BaseWriteServiceCollaborationTests(unittest.TestCase):
    def test_project_write_conflict_publishes_typed_event(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        events = _EventBus()
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda *_args: True
        )
        service._event_bus = events
        service._mutation_executor = _ConflictingMutationExecutor(
            SynchronizationConflict(database_id, resource, "stale update")
        )
        service._session_registry = DatabaseSessionRegistry()
        service._concurrency_tokens, _drafts = _token_service()
        result = service._execute_database_mutation(
            database_id, (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        event, payload = events.published[-1]
        self.assertIs(event, AppEvents.SYNCHRONIZATION_CONFLICT)
        self.assertEqual(payload["resource_id"], "42")
        self.assertFalse(payload["blocks_database"])

    def test_project_write_session_conflict_blocks_the_database(self):
        database_id = "database"
        resource = ResourceRef("database", database_id)
        events = _EventBus()
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda *_args: True
        )
        service._event_bus = events
        service._mutation_executor = _ConflictingMutationExecutor(
            SynchronizationConflict(
                database_id,
                resource,
                "session expired",
                kind=SynchronizationConflictKind.SESSION,
            )
        )
        service._session_registry = DatabaseSessionRegistry()
        service._concurrency_tokens, _drafts = _token_service()
        result = service._execute_database_mutation(
            database_id, (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        _event, payload = events.published[-1]
        self.assertTrue(payload["blocks_database"])


class UIAccessPlanEditingTests(unittest.TestCase):
    def test_application_mutation_boundary_rejects_revoked_database_access(self):
        capability = _write_access_support__CapabilityService(editable=False)
        executor = _write_access_support__MutationExecutor()
        tokens = _write_access_support__ConcurrencyTokens()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=_write_access_support__EventBus(),
            mutation_executor=executor,
            session_registry=_write_access_support__SessionRegistry(),
            concurrency_tokens=tokens,
            database_capability_service=capability,
        )
        resource = ResourceRef("takeoff", "41", 7)
        result = service._execute_database_mutation(
            "sql-db", (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(tokens.load_calls, 0)
        self.assertEqual(
            capability.requests,
            [("sql-db", None)],
        )

    def test_application_mutation_boundary_preserves_editable_access_path(self):
        capability = _write_access_support__CapabilityService(editable=True)
        executor = _write_access_support__MutationExecutor()
        tokens = _write_access_support__ConcurrencyTokens()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=_write_access_support__EventBus(),
            mutation_executor=executor,
            session_registry=_write_access_support__SessionRegistry(),
            concurrency_tokens=tokens,
            database_capability_service=capability,
        )
        resource = ResourceRef("takeoff", "41", 7)
        result = service._execute_database_mutation(
            "access-db", (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(tokens.load_calls, 1)

    def test_application_mutation_boundary_rejects_locked_resource(self):
        resource = ResourceRef("takeoff", "41", 7)
        capability = _write_access_support__CapabilityService(
            editable=True, denied_resource=resource
        )
        executor = _write_access_support__MutationExecutor()
        tokens = _write_access_support__ConcurrencyTokens()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=_write_access_support__EventBus(),
            mutation_executor=executor,
            session_registry=_write_access_support__SessionRegistry(),
            concurrency_tokens=tokens,
            database_capability_service=capability,
        )
        result = service._execute_database_mutation(
            "sql-db", (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(tokens.load_calls, 0)
        self.assertEqual(
            capability.requests,
            [("sql-db", None), ("sql-db", resource)],
        )
