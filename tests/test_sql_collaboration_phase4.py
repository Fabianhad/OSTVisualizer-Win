import json
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
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
from ost_visualizer.application.dtos.local_draft_dtos import LocalDraftState
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    AuthoritativeMutationResult,
    CollaborationMutationType,
    CollaborationStatus,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
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
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    MutationOutcomeStatus,
    MutationExecutionResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    PendingMutationState,
    PendingSqlOperationRecord,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
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
from ost_visualizer.application.services.pending_mutation_registry import (
    PendingMutationRegistry,
)
from ost_visualizer.application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
    _QueuedMutation,
)
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)

_COORDINATOR_TYPE = SqlCollaborationCoordinator


class _PendingOperationJournal:
    def __init__(self):
        self.records = {}

    def list_all(self):
        return tuple(self.records.values())

    def save(self, record):
        self.records[record.operation_id] = record

    def remove(self, operation_id):
        self.records.pop(operation_id, None)


class _FailingPendingOperationJournal(_PendingOperationJournal):
    def __init__(self, *failed_save_numbers):
        super().__init__()
        self.failed_save_numbers = set(failed_save_numbers)
        self.save_count = 0

    def save(self, record):
        self.save_count += 1
        if self.save_count in self.failed_save_numbers:
            raise OSError("test operation journal failure")
        super().save(record)


def _coordinator(*args, **kwargs):
    kwargs.setdefault("pending_mutations", PendingMutationRegistry())
    kwargs.setdefault("operation_journal", _PendingOperationJournal())
    return _COORDINATOR_TYPE(*args, **kwargs)


from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.entity_version_reader import (
    DatabaseEntityVersionReader,
)
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.schema_validator import SqlSchemaValidator
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.remote_change_reader import (
    _MAX_HYDRATION_BATCH_PARAMETERS,
    _MAX_HYDRATION_BATCH_QUERIES,
    _execute_recorded_queries,
    _recorded_query_batches,
    SqlRemoteChangeReader,
)
from ost_visualizer.infrastructure.sql.collaboration_store import (
    SqlCollaborationStore,
    _change_from_row,
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


class _FailingUnsubscribeEventBus(_EventBus):
    def __init__(self):
        super().__init__()
        self.unsubscribe_attempts = []

    def unsubscribe(self, event, callback):
        self.unsubscribe_attempts.append(event)
        if event == AppEvents.FILE_OPENED:
            raise RuntimeError("listener registry unavailable")
        super().unsubscribe(event, callback)


class _PermissionProbe:
    def can_edit(self, _database_id):
        return True


class _DeniedPermissionProbe:
    def can_edit(self, _database_id):
        return False


class _ReadRequestFactory:
    @staticmethod
    def request(_database_id, *, read_only):
        if not read_only:
            raise AssertionError("Remote hydration must use a read request.")
        return object()


class _ConflictingMutationExecutor:
    def __init__(self, conflict):
        self._conflict = conflict

    def execute(self, request, _operation):
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.CONFLICT,
            conflict=self._conflict,
        )


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


def _shutdown_coordinator(coordinator):
    completed = threading.Event()
    results = []
    coordinator.request_shutdown(
        lambda success, message: (results.append((success, message)), completed.set())
    )
    if not completed.wait(2):
        raise AssertionError("SQL collaboration shutdown did not complete")
    if results != [(True, "")]:
        raise AssertionError(f"SQL collaboration shutdown failed: {results!r}")


def _stop_database(coordinator, database_id):
    completed = threading.Event()
    results = []
    coordinator.stop_database_async(
        database_id,
        callback=lambda success, message: (
            results.append((success, message)),
            completed.set(),
        ),
    )
    if not completed.wait(2):
        raise AssertionError("SQL collaboration database drain did not complete")
    if results != [(True, "")]:
        raise AssertionError(f"SQL collaboration database drain failed: {results!r}")


def _queue_test_mutation(
    coordinator,
    database_id,
    resources,
    operation,
    callback,
    *,
    dependency_resources=(),
    expected_id_count=1,
    operation_id="",
    owning_surface="main-plan",
    lifecycle_critical=True,
    mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
):
    canonical_operation_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"ostv-test:{operation_id or uuid.uuid4()}")
    )
    request = QueuedMutationRequest(
        database_id=database_id,
        operation_id=canonical_operation_id,
        mutation_type=mutation_type,
        owning_surface=owning_surface,
        resources=tuple(resources),
        dependency_resources=tuple(dependency_resources),
        payload={"test_operation": operation_id or canonical_operation_id},
        lifecycle_critical=lifecycle_critical,
    )

    def validate(result):
        if (
            result.outcome_status == MutationOutcomeStatus.COMMITTED
            and len(result.created_resource_ids) != expected_id_count
        ):
            return "The test mutation returned an incomplete authoritative result."
        return ""

    return coordinator.queue_request(
        request,
        operation,
        callback,
        result_validator=validate,
    )


def _committed_execution(*created_resource_ids: str) -> MutationExecutionResult:
    created = tuple(created_resource_ids)
    return MutationExecutionResult(
        outcome_status=MutationOutcomeStatus.COMMITTED,
        created_resource_ids=created,
        authoritative_result=AuthoritativeMutationResult(
            created_resource_ids=created,
        ),
    )


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


class _DelayedReconciliationDispatcher:
    def __init__(self):
        self.pending = []

    def dispatch(self, callback, payload=()):
        if callback.__name__ == "_on_remote_batch":
            self.pending.append((callback, payload))
            return
        callback(payload)

    def deliver_pending(self):
        for callback, payload in tuple(self.pending):
            callback(payload)
        self.pending.clear()


class _DelayedMutationDispatcher:
    def __init__(self):
        self.pending = []

    def dispatch(self, callback, payload=()):
        if callback.__name__ in {
            "_complete_mutation_request",
            "_complete_recovered_mutation_request",
        }:
            self.pending.append((callback, payload))
            return
        callback(payload)

    def deliver_pending(self):
        for callback, payload in tuple(self.pending):
            callback(payload)
        self.pending.clear()


class _Reconciliation:
    def __init__(self):
        self.batches = []
        self.projection_barriers = []
        self.result = True
        self.failure_kind = None

    def apply(
        self,
        hydrated,
        projection_barrier=None,
        *,
        local_completion=False,
    ):
        self.batches.append(hydrated)
        self.projection_barriers.append(projection_barrier)
        return ReconciliationResult(
            applied=self.result,
            failure_kind=self.failure_kind,
        )


class _RaisingReconciliation:
    def apply(self, _batch, projection_barrier=None, *, local_completion=False):
        raise RuntimeError("reconciliation callback failed")


class _DeferredProjectionReconciliation:
    def __init__(self):
        self.token = None

    def apply(self, _batch, projection_barrier=None, *, local_completion=False):
        self.token = projection_barrier.register("test-plan")
        return ReconciliationResult(applied=True)


class _FailFirstLocalProjectionReconciliation:
    def __init__(self):
        self.token = None
        self.local_projection_started = threading.Event()

    def apply(self, _batch, projection_barrier=None, *, local_completion=False):
        if local_completion and self.token is None:
            self.token = projection_barrier.register("test-plan")
            self.local_projection_started.set()
        return ReconciliationResult(applied=True)


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
        bid_uid,
        page_uid,
        mode,
    ):
        return DatabaseSession(
            database_id=database_id,
            session_id=session_id,
            last_acknowledged_version=acknowledged_version,
        )

    def close_session(self, database_id, session_id, reason):
        self.closed.set()

    def list_presence(self, database_id, bid_uid, excluding_session_id):
        return ()

    def list_locks(self, database_id, excluding_session_id, bid_uid=None):
        return ()

    def acquire_lock(self, database_id, session_id, resource, operation_description):
        raise AssertionError("No edit lock was requested")

    def acquire_locks(self, database_id, session_id, resources, operation_description):
        return tuple(
            self.acquire_lock(
                database_id,
                session_id,
                resource,
                operation_description,
            )
            for resource in resources
        )

    def renew_lock(self, database_id, session_id, lock_token):
        raise AssertionError("No edit lock was requested")

    def release_lock(self, database_id, session_id, lock_token):
        raise AssertionError("No edit lock was requested")

    def poll_changes(self, database_id, after_version, limit, excluding_session_id):
        self.polled.set()
        if self.batch is not None:
            observed = self.batch
            changes = observed.changes
        else:
            changes = (self.change,) if self.change is not None else ()
            high_water = changes[-1].commit_version if changes else 0
            observed = _batch(database_id, "epoch", 0, high_water, changes)
        if changes:
            self.change_seen.set()
        remote = _batch(
            observed.database_id,
            observed.feed_epoch,
            observed.minimum_valid_version,
            observed.high_water_version,
            tuple(
                change
                for change in changes
                if not session_identities_equal(
                    change.source_session_id, excluding_session_id
                )
            ),
            delivered_through=observed.delivered_through_version,
        )
        return DatabaseChangePollResult(
            observed_batch=observed,
            remote_batch=HydratedDatabaseChangeBatch(remote),
        )

    def hydrate_operation(self, database_id, operation_id):
        return HydratedDatabaseChangeBatch(_batch(database_id, "epoch", 0, 0))


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


class _AlwaysUnavailableStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.first_failure = threading.Event()
        self.repeated_failure = threading.Event()
        self.start_threads = []

    def start_session(
        self,
        database_id,
        session_id,
        client_instance_id,
        display_name,
        machine_name,
        application_version,
    ):
        self.start_threads.append(threading.get_ident())
        self.start_count += 1
        if self.start_count == 1:
            self.first_failure.set()
        else:
            self.repeated_failure.set()
        raise DatabaseCatalogError("server unavailable", retryable=True)


class _InvalidFeedStore(_CollaborationStore):
    def poll_changes(
        self,
        _database_id,
        _after_version,
        _limit,
        _excluding_session_id,
    ):
        raise ValueError("invalid transaction marker")


class _UnexpectedPollFailureStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.failed = threading.Event()

    def poll_changes(
        self,
        _database_id,
        _after_version,
        _limit,
        _excluding_session_id,
    ):
        self.failed.set()
        raise RuntimeError("unexpected poll implementation failure")


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


class _InvalidCommittedHydrationStore(_LockingStore):
    def hydrate_operation(self, _database_id, _operation_id):
        raise ValueError("A committed SQL transaction marker has no ChangeLog records.")


class _RecoverableProjectionStore(_LockingStore):
    def __init__(self):
        super().__init__()
        self.durable_results = {}
        self.recovery_queried = threading.Event()

    def query_operation(self, database_id, operation_id):
        self.recovery_queried.set()
        return self.durable_results.get(
            operation_id,
            DurableOperationResult(
                database_id=database_id,
                operation_id=operation_id,
                found=False,
            ),
        )


class _BlockedPollStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.poll_entered = threading.Event()
        self.release_poll = threading.Event()

    def poll_changes(self, database_id, _after_version, _limit, _excluding_session_id):
        self.poll_entered.set()
        if not self.release_poll.wait(2):
            raise OSError("test poll did not receive its release signal")
        batch = _batch(database_id, "epoch", 0, 0)
        return DatabaseChangePollResult(
            observed_batch=batch,
            remote_batch=HydratedDatabaseChangeBatch(batch),
        )


class _FailedCloseStore(_CollaborationStore):
    def close_session(self, _database_id, _session_id, _reason):
        raise DatabaseCatalogError("test close failure")


class _ReleaseFailsCloseSucceedsStore(_LockingStore):
    def release_lock(self, database_id, session_id, lock_token):
        raise DatabaseCatalogError("test individual release failure")


class _BatchAcquireFailureStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.acquire_failed = threading.Event()

    def acquire_locks(self, database_id, session_id, resources, operation_description):
        self.acquire_failed.set()
        raise ValueError("second lock was denied")


class _BlockingDraftRegistry(LocalDraftRegistry):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.proceed = threading.Event()

    def begin(self, **kwargs):
        self.entered.set()
        if not self.proceed.wait(2):
            raise RuntimeError("test draft creation was not released")
        return super().begin(**kwargs)


class _ProjectData:
    def __init__(self, database_id):
        self.bid_ref = BidRef(database_id, "8")
        self.conditions = {}
        self.areas = ()
        self.database_settings = {}
        self.cover_sheets = {}
        self.page_delete_content = {}
        self.removed_transient_takeoff_uids = []
        self.annotations = []

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_bid_conditions(self):
        return self.conditions

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

    def replace_database_hierarchy(self, _file_entry, _cdn_types):
        raise AssertionError("No hierarchy change was requested")

    def replace_remote_bid_families(self, bid_ref, bid_data, families):
        if bid_ref != self.bid_ref:
            return False
        if CollaborationResourceFamily.ANNOTATIONS.value in families:
            self.annotations = list(bid_data.bid_annotations)
        return True

    def get_all_annotations(self):
        return list(self.annotations)

    def remove_transient_takeoffs(self, takeoff_uids):
        self.removed_transient_takeoff_uids.extend(takeoff_uids)

    def replace_database_settings(
        self,
        database_id,
        *,
        default_layers=None,
        job_statuses=None,
        employees=None,
        pay_classes=None,
        used_job_status_uids=None,
        used_employee_uids=None,
    ):
        values = {
            "default_layers": default_layers,
            "job_statuses": job_statuses,
            "employees": employees,
            "pay_classes": pay_classes,
            "used_job_status_uids": used_job_status_uids,
            "used_employee_uids": used_employee_uids,
        }
        self.database_settings[database_id] = values

    def replace_cover_sheet_data(self, database_id, bid_uid, cover_sheet):
        self.cover_sheets[(database_id, str(bid_uid))] = cover_sheet

    def replace_page_delete_content_uids(self, database_id, bid_uid, page_uids):
        self.page_delete_content[(database_id, str(bid_uid))] = frozenset(page_uids)

    def replace_settings_defaults(self, database_id, defaults):
        self.database_settings.setdefault(database_id, {})["defaults"] = defaults


def _change(
    database_id,
    resource,
    sequence=1,
    source="other-session",
    changed_fields=(),
    operation=ChangeOperation.UPDATE,
):
    return DatabaseChange(
        sequence=sequence,
        commit_version=sequence,
        transaction_id="transaction-1",
        source_session_id=source,
        resource=resource,
        operation=operation,
        resulting_version=ConcurrencyToken(sequence.to_bytes(8, "big")),
        changed_fields=tuple(changed_fields),
    )


def _batch(
    database_id,
    feed_epoch,
    minimum_version,
    high_water_version,
    changes=(),
    delivered_through=None,
):
    return DatabaseChangeBatch(
        database_id=database_id,
        feed_epoch=feed_epoch,
        minimum_valid_version=minimum_version,
        high_water_version=high_water_version,
        delivered_through_version=(
            high_water_version if delivered_through is None else delivered_through
        ),
        changes=changes,
    )


class SqlCollaborationPhase4Tests(unittest.TestCase):
    def test_session_rejects_multiple_database_metadata_rows(self):
        expected_guid = "00000000-0000-0000-0000-000000000123"
        inserted_sessions = []

        class _Requests:
            @staticmethod
            def request(_database_id, *, read_only):
                self.assertFalse(read_only)
                return SimpleNamespace(
                    location=SqlServerDatabaseLocation(
                        server="localhost",
                        database="TEST",
                        database_guid=expected_guid,
                    )
                )

        class _Cursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, *parameters):
                self.last_sql = sql
                if "INSERT INTO [ostv].[Sessions]" in sql:
                    inserted_sessions.append(parameters)
                return self

            def fetchone(self):
                if "DatabaseMetadata" in self.last_sql:
                    if "COUNT_BIG(*)" in self.last_sql:
                        return None
                    return (expected_guid,)
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.last_sql:
                    return (8,)
                raise AssertionError(self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return _Cursor()

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.assertFalse(autocommit)
                yield lease

            def assertFalse(self, value):
                self_test.assertFalse(value)

        self_test = self
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _Requests()
        store._connections = _Connections()
        with self.assertRaisesRegex(
            SqlInfrastructureError,
            "metadata is missing",
        ) as raised:
            store.start_session(
                "saved-database-id",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "test-user",
                "test-machine",
                "test-version",
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(inserted_sessions, [])
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)

    def test_session_rejects_database_recreated_with_saved_connection_identity(self):
        expected_guid = "00000000-0000-0000-0000-000000000123"
        replacement_guid = "00000000-0000-0000-0000-000000000456"
        inserted_sessions = []
        statements = []

        class _Requests:
            @staticmethod
            def request(_database_id, *, read_only):
                self.assertFalse(read_only)
                return SimpleNamespace(
                    location=SqlServerDatabaseLocation(
                        server="localhost",
                        database="TEST",
                        database_guid=expected_guid,
                    )
                )

        class _Cursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, *parameters):
                self.last_sql = sql
                statements.append(sql)
                if "INSERT INTO [ostv].[Sessions]" in sql:
                    inserted_sessions.append(parameters)
                return self

            def fetchone(self):
                if "DatabaseMetadata" in self.last_sql:
                    return (replacement_guid,)
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.last_sql:
                    return (8,)
                raise AssertionError(self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return _Cursor()

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.assertFalse(autocommit)
                yield lease

            def assertFalse(self, value):
                self_test.assertFalse(value)

        self_test = self
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _Requests()
        store._connections = _Connections()
        with self.assertRaisesRegex(
            SqlInfrastructureError,
            "replaced since this connection was saved",
        ) as raised:
            store.start_session(
                "saved-database-id",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "test-user",
                "test-machine",
                "test-version",
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(inserted_sessions, [])
        self.assertEqual(len(statements), 1)
        self.assertIn("COUNT_BIG(*)", statements[0])
        self.assertIn("sys.database_recovery_status", statements[0])
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)

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
                (results.append, result, object(), runtime.session_generation)
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

    def test_same_sql_principal_still_creates_distinct_client_sessions(self):
        class _RecordingStore(_CollaborationStore):
            def __init__(self):
                super().__init__()
                self.starts = []

            def start_session(self, *args):
                self.starts.append((args[1], args[2], args[3]))
                return super().start_session(*args)

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

    def test_takeoff_hydration_includes_authoritative_condition_dependency(self):
        calls = []
        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = SimpleNamespace(
            _schema=lambda _connection: object(),
            _parse_cdn_types=lambda _connection: {},
            _parse_bid_layers_for_bid=lambda _connection, bid_uid: calls.append(
                ("condition-layers", bid_uid)
            )
            or {},
            _parse_bid_conditions_for_bid=lambda _connection, bid_uid, *_args: {
                "10": Condition(uid="10")
            },
            _parse_bid_condition_folders_for_bid=lambda *_args: {},
            _parse_bid_takeoffs_for_bid=lambda *_args: (
                [Takeoff(uid="30", condition_uid="10", page_uid="20")],
                {},
            ),
            _parse_bid_pages_for_bid=lambda *_args: {
                "20": SimpleNamespace(
                    name="Sheet",
                    sheet_no="",
                    sequence=0,
                    image_path="",
                    width_pts=0.0,
                    height_pts=0.0,
                    scale_factor1=1.0,
                    scale_factor2=1.0,
                    rotation=0.0,
                    flip_x=False,
                    flip_y=False,
                    page_index=0,
                    layer_visible=True,
                    overlay_image_path="",
                    overlay_offset_x=0.0,
                    overlay_offset_y=0.0,
                    overlay_rotation=0.0,
                    overlay_resized=False,
                    deskew_rotation_overlay=0.0,
                    overlay_rect=(),
                    image_show_mode=0,
                    zoom_fac=1.0,
                    current_x=0.0,
                    current_y=0.0,
                    invert=False,
                    bitonal=False,
                )
            },
        )
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("takeoff", "30", 8),
                    sequence=2,
                ),
            ),
        )
        hydrated = reader.hydrate_connection(batch, object())
        self.assertEqual(set(hydrated.conditions_by_bid[8]), {"10"})
        self.assertEqual(calls, [("condition-layers", "8")])

    def test_takeoff_hydration_batches_bound_parameters_and_query_count(self):
        parameter_queries = tuple(
            (f"SELECT {index}", tuple(range(10))) for index in range(201)
        )
        parameter_batches = tuple(_recorded_query_batches(parameter_queries))
        self.assertEqual(
            tuple(item for batch in parameter_batches for item in batch),
            parameter_queries,
        )
        self.assertGreater(len(parameter_batches), 1)
        self.assertTrue(
            all(
                sum(len(parameters) for _query, parameters in batch)
                <= _MAX_HYDRATION_BATCH_PARAMETERS
                for batch in parameter_batches
            )
        )
        query_count_queries = tuple(
            (f"SELECT {index}", ()) for index in range(_MAX_HYDRATION_BATCH_QUERIES + 1)
        )
        query_count_batches = tuple(_recorded_query_batches(query_count_queries))
        self.assertEqual(
            tuple(item for batch in query_count_batches for item in batch),
            query_count_queries,
        )
        self.assertEqual(
            tuple(len(batch) for batch in query_count_batches),
            (_MAX_HYDRATION_BATCH_QUERIES, 1),
        )

    def test_takeoff_hydration_replay_preserves_order_across_bounded_batches(self):
        class _BatchCursor:
            def __init__(self, owner):
                self._owner = owner
                self._result_index = 0
                self._results = ()
                self.description = (("Value",),)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *parameters):
                query_count = str(sql).count(";") + 1
                start = self._owner.next_result
                self._owner.next_result += query_count
                self._owner.executions.append((query_count, len(parameters)))
                self._results = tuple(
                    ((start + index,),) for index in range(query_count)
                )
                self._result_index = 0
                return self

            def fetchall(self):
                return self._results[self._result_index]

            def nextset(self):
                self._result_index += 1
                return self._result_index < len(self._results)

        class _BatchConnection:
            def __init__(self):
                self.executions = []
                self.next_result = 0

            def cursor(self):
                return _BatchCursor(self)

        queries = tuple(
            ("SELECT ?", (index,)) for index in range(_MAX_HYDRATION_BATCH_QUERIES + 1)
        )
        connection = _BatchConnection()
        replay = _execute_recorded_queries(connection, queries)
        replayed = []
        for query, parameters in queries:
            with replay.cursor() as cursor:
                cursor.execute(query, *parameters)
                replayed.extend(row[0] for row in cursor.fetchall())
        replay.assert_consumed()
        self.assertEqual(replayed, list(range(len(queries))))
        self.assertEqual(
            connection.executions,
            [
                (_MAX_HYDRATION_BATCH_QUERIES, _MAX_HYDRATION_BATCH_QUERIES),
                (1, 1),
            ],
        )

    def test_initial_reconciliation_uses_one_snapshot_without_advancing_checkpoint(
        self,
    ):
        class _Cursor:
            def __init__(self):
                self.statements = []

            def execute(self, sql, *_parameters):
                self.statements.append(sql)
                return self

            def fetchone(self):
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.statements[-1]:
                    return (19,)
                raise AssertionError(self.statements[-1])

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()
                self.autocommit = None

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        connections = _Connections()
        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._requests = _ReadRequestFactory()
        remote_reader._connections = connections
        hydration_connections = []

        def hydrate(batch, connection):
            hydration_connections.append(connection)
            self.assertEqual(connections.lease.commits, 1)
            return HydratedDatabaseChangeBatch(batch)

        remote_reader.hydrate_connection = hydrate
        hydrated = remote_reader.initial_reconciliation("database", 8, 11)
        self.assertFalse(connections.autocommit)
        self.assertEqual(
            connections.lease.cursor_value.statements[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(hydrated.batch.high_water_version, 19)
        self.assertEqual(hydrated.batch.delivered_through_version, 11)
        self.assertEqual(hydration_connections, [connections.lease])
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)

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

    def test_edit_lease_result_rejects_incomplete_ownership_state(self):
        resource = ResourceRef("condition", "42", 8)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(resource,),
        )
        with self.assertRaisesRegex(ValueError, "handle"):
            EditLeaseResult(True)
        with self.assertRaisesRegex(ValueError, "handle"):
            EditLeaseResult(False, handle=handle)

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
                if "MIN_VALID_VERSION" in self.last_sql:
                    return (1,)
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.last_sql:
                    return (12,)
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
                self.commits = 0
                self.rollbacks = 0

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                if autocommit:
                    raise AssertionError("Feed reads require one transaction.")
                owner = self

                class _Lease:
                    def cursor(self):
                        return owner.cursor

                    def commit(self):
                        owner.commits += 1

                    def rollback(self):
                        owner.rollbacks += 1

                yield _Lease()

        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _ReadRequestFactory()
        store._connections = _Connections()
        hydration_connections = []

        class _RemoteReader:
            def hydrate_connection(self, batch, connection):
                self_batch = batch
                hydration_connections.append(connection)
                test_case.assertEqual(store._connections.commits, 1)
                return HydratedDatabaseChangeBatch(self_batch)

        test_case = self
        remote_reader = _RemoteReader()
        store._remote_reader = remote_reader
        result = store.poll_changes("database", 11, 10, "local-session")
        batch = result.observed_batch
        statements = " ".join(store._connections.cursor.statements)
        self.assertEqual(
            store._connections.cursor.statements[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(store._connections.commits, 2)
        self.assertEqual(store._connections.rollbacks, 0)
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
        self.assertEqual(result.remote_batch.batch.changes, batch.changes)
        self.assertEqual(len(hydration_connections), 1)

    def test_snapshot_feed_rolls_back_the_whole_poll_when_payload_is_missing(self):
        transaction_id = "00000000-0000-0000-0000-000000000099"

        class _Cursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                return self

            def fetchone(self):
                if "ChangeFeedState" in self.last_sql:
                    return ("epoch",)
                if "MIN_VALID_VERSION" in self.last_sql:
                    return (1,)
                if "CURRENT_VERSION" in self.last_sql:
                    return (12,)
                raise AssertionError(self.last_sql)

            def fetchall(self):
                if "CHANGETABLE" in self.last_sql:
                    return [(12, "I", transaction_id)]
                return [
                    (
                        None,
                        12,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                ]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        cursor = _Cursor()

        class _Lease:
            commits = 0
            rollbacks = 0

            def cursor(self):
                return cursor

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield lease

        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _ReadRequestFactory()
        store._connections = _Connections()
        with self.assertRaisesRegex(ValueError, "no ChangeLog records"):
            store.poll_changes("database", 11, 10, "local-session")
        self.assertFalse(store._connections.autocommit)
        self.assertEqual(lease.commits, 1)
        self.assertEqual(lease.rollbacks, 1)

    def test_production_collaboration_store_acquires_resource_locks_in_one_batch(self):
        class _WriteRequestFactory:
            @staticmethod
            def request(_database_id, *, read_only):
                self.assertFalse(read_only)
                return object()

        class _Cursor:
            def __init__(self):
                self.last_sql = ""
                self.parameters = ()

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                self.parameters = _parameters
                return self

            def fetchall(self):
                self.assert_canonical_lock_batch()
                requested = json.loads(self.parameters[0])
                return [
                    (0, item["ordinal"], None, item["lock_token"]) for item in requested
                ]

            def assert_canonical_lock_batch(self):
                test_case.assertIn("OPENJSON", self.last_sql)
                test_case.assertIn("sp_getapplock", self.last_sql)
                test_case.assertIn("INSERT INTO [ostv].[Locks]", self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                test_case.assertFalse(autocommit)
                yield self.lease

        test_case = self
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _WriteRequestFactory()
        store._connections = _Connections()
        resources = (
            ResourceRef("takeoffs_collection", "8", 8),
            ResourceRef("takeoff", "19", 19),
        )
        locks = store.acquire_locks(
            "database", "session", resources, "takeoff-placement:test"
        )
        self.assertEqual(len(locks), 2)
        for lock, resource in zip(locks, sorted(resources), strict=True):
            self.assertEqual(lock.database_id, "database")
            self.assertEqual(lock.resource, resource)
            self.assertRegex(
                lock.lock_token,
                r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            )
        self.assertEqual(store._connections.lease.commits, 1)
        self.assertEqual(store._connections.lease.rollbacks, 0)
        store._connections.lease.cursor_value.assert_canonical_lock_batch()

    def test_snapshot_feed_rolls_back_a_retention_gap(self):
        class _Cursor:
            last_sql = ""

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                return self

            def fetchone(self):
                if "ChangeFeedState" in self.last_sql:
                    return ("epoch",)
                if "MIN_VALID_VERSION" in self.last_sql:
                    return (20,)
                if "CURRENT_VERSION" in self.last_sql:
                    return (25,)
                raise AssertionError(self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        cursor = _Cursor()

        class _Lease:
            commits = 0
            rollbacks = 0

            def cursor(self):
                return cursor

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield lease

        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _ReadRequestFactory()
        store._connections = _Connections()
        batch = store.poll_changes("database", 10, 10, "local-session").observed_batch
        self.assertEqual(batch.minimum_valid_version, 20)
        self.assertEqual(batch.delivered_through_version, 10)
        self.assertEqual(lease.commits, 1)
        self.assertEqual(lease.rollbacks, 1)

    def test_snapshot_feed_rejects_duplicate_resource_payloads(self):
        transaction_id = "00000000-0000-0000-0000-000000000099"

        class _Cursor:
            def execute(self, _sql, *_parameters):
                return self

            def fetchall(self):
                row = (
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
                return (row, (2, *row[1:]))

        with self.assertRaisesRegex(ValueError, "duplicate resource payloads"):
            SqlCollaborationStore._load_transaction_changes(
                _Cursor(), ((transaction_id, 12),)
            )

    def test_transaction_log_uuid_text_is_canonicalized_before_marker_validation(self):
        transaction_id = "859945fa-fbf8-4b90-bafe-735976033238"
        session_id = "8b2ce0c5-90f8-4580-a5ee-b2f4fdc7581a"

        class _Cursor:
            def execute(self, _sql, *_parameters):
                return self

            @staticmethod
            def fetchall():
                return (
                    (
                        1,
                        12,
                        transaction_id.upper(),
                        session_id.upper(),
                        8,
                        "takeoff",
                        "501",
                        "create",
                        None,
                        None,
                        None,
                        "ost_visualizer",
                    ),
                )

        rows = SqlCollaborationStore._load_transaction_changes(
            _Cursor(), ((transaction_id, 12),)
        )
        change = _change_from_row(rows[0])
        self.assertEqual(change.transaction_id, transaction_id)
        self.assertEqual(change.source_session_id, session_id.upper())

    def test_remote_condition_and_area_hydration_uses_current_reader_contract(self):
        condition = object()
        folder = object()
        area = object()
        layer = object()
        reader_connections = []

        class _Connections:
            def __init__(self):
                self.calls = 0

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                if not autocommit:
                    raise AssertionError("Remote hydration must use autocommit reads.")
                self.calls += 1
                yield object()

        class _Reader:
            logger = None

            @staticmethod
            def _schema(connection):
                reader_connections.append(connection)
                return object()

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

            def _parse_bid_layers_for_sidebar(self, connection, bid_uid):
                reader_connections.append(connection)
                return [layer]

        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._connections = _Connections()
        remote_reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            3,
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
                _change(
                    "database",
                    ResourceRef("layers_collection", "8", 8),
                    3,
                ),
            ),
        )
        connection = object()
        hydrated = remote_reader.hydrate_connection(batch, connection)
        self.assertEqual(hydrated.conditions_by_bid, {8: {"42": condition}})
        self.assertEqual(hydrated.condition_folders_by_bid, {8: {"5": folder}})
        self.assertEqual(hydrated.areas_by_bid, {8: (area,)})
        self.assertEqual(hydrated.bid_data_by_bid[8].bid_layers, [layer])
        self.assertTrue(reader_connections)
        self.assertTrue(all(value is connection for value in reader_connections))
        self.assertEqual(remote_reader._connections.calls, 0)

    def test_remote_cover_sheet_hydration_carries_delete_confirmation_snapshot(self):
        cover_sheet = object()

        class _Reader:
            @staticmethod
            def _parse_cover_sheet_data(_connection, bid_uid):
                self.assertEqual(bid_uid, "8")
                return cover_sheet

            @staticmethod
            def _parse_pages_with_delete_content(_connection, bid_uid):
                self.assertEqual(bid_uid, "8")
                return {"page-1"}

        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("cover_sheet", "8", 8),
                    2,
                ),
            ),
        )
        hydrated = remote_reader.hydrate_connection(batch, object())
        self.assertIs(hydrated.cover_sheet_by_bid[8], cover_sheet)
        self.assertEqual(
            hydrated.page_delete_content_uids_by_bid[8], frozenset({"page-1"})
        )
        project_data = _ProjectData("database")
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertIs(project_data.cover_sheets[("database", "8")], cover_sheet)
        self.assertEqual(
            project_data.page_delete_content[("database", "8")],
            frozenset({"page-1"}),
        )

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

    def test_resource_reference_order_handles_optional_bid_context(self):
        context_free = ResourceRef("condition", "42")
        bid_scoped = ResourceRef("condition", "42", 8)
        self.assertEqual(
            sorted((bid_scoped, context_free)),
            [context_free, bid_scoped],
        )
        self.assertLess(context_free, bid_scoped)

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
            SqlErrorDetails(SqlErrorCode.SCHEMA_MISMATCH, "Schema mismatch.")
        )
        permission = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.PERMISSION_DENIED, "Permission revoked.")
        )
        self.assertTrue(credential.credential_required)
        self.assertFalse(credential.read_only_required)
        self.assertTrue(schema.read_only_required)
        self.assertTrue(permission.read_only_required)
        self.assertFalse(schema.credential_required)

    def test_schema_v1_has_canonical_collaboration_objects(self):
        self.assertEqual(SQL_SCHEMA_V1.version, 1)
        self.assertIn(
            "ALLOW_SNAPSHOT_ISOLATION=ON",
            SQL_SCHEMA_V1.canonical_database_requirements,
        )
        tables = {table.name: table for table in SQL_SCHEMA_V1.tables}
        self.assertEqual(
            set(tables),
            {
                "DatabaseMetadata",
                "SchemaMigrations",
                "Sessions",
                "Presence",
                "UserBidWorkspaceState",
                "UserPageWorkspaceState",
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
            SQL_SCHEMA_V1.change_tracking_tables,
            (("ostv", "ChangeTransactions"),),
        )
        transaction_columns = {
            column.name for column in tables["ChangeTransactions"].columns
        }
        self.assertTrue(
            {
                "OperationType",
                "RequestHash",
                "ResultFormatVersion",
                "ResultPayload",
            }.issubset(transaction_columns)
        )
        feed_columns = {column.name for column in tables["ChangeFeedState"].columns}
        self.assertEqual(feed_columns, {"SingletonId", "FeedEpoch"})
        self.assertEqual(len(SQL_SCHEMA_V1.checksum), 64)

    def test_schema_v1_requires_snapshot_isolation_and_tracking_configuration(self):
        inventory = type(
            "Inventory",
            (),
            {
                "snapshot_isolation_enabled": False,
                "change_tracking_retention_days": 6,
                "change_tracking_auto_cleanup": False,
            },
        )()
        self.assertEqual(
            SqlSchemaValidator._validate_database_requirements(
                inventory, SQL_SCHEMA_V1
            ),
            [
                "database.snapshot_isolation",
                "database.change_tracking_retention",
                "database.change_tracking_auto_cleanup",
            ],
        )

    def test_entity_seed_includes_empty_bid_collections_and_annotations(self):
        sql = "\n".join(SQL_SCHEMA_V1.collaboration_initialization_statements)
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

    def test_session_registry_uses_sql_lock_identity_without_bid_context(self):
        registry = DatabaseSessionRegistry()
        registered = ResourceRef("condition", "42")
        requested = ResourceRef("condition", "42", 8)
        registry.register("database", "session")
        registry.register_lock("database", registered, "lock-token")
        self.assertEqual(
            registry.lock_tokens("database", (requested,)),
            ("lock-token",),
        )
        registry.remove_lock("database", requested)
        self.assertEqual(registry.lock_tokens("database", (registered,)), ())

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
        draft = drafts.begin(
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

    def test_local_draft_overlap_ignores_optional_bid_context(self):
        drafts = LocalDraftRegistry()
        stored = ResourceRef("takeoff", "41")
        requested = ResourceRef("takeoff", "41", 7)
        drafts.begin(
            draft_type="takeoff-mutation",
            database_id="database",
            bid_uid=None,
            page_uid=None,
            owning_surface="plan-view",
            affected_resources=(stored,),
        )
        with self.assertRaisesRegex(ValueError, "already owns"):
            drafts.begin(
                draft_type="takeoff-mutation",
                database_id="database",
                bid_uid=7,
                page_uid=None,
                owning_surface="detached-plan",
                affected_resources=(requested,),
            )

    def test_local_draft_remote_conflict_ignores_optional_bid_context(self):
        drafts = LocalDraftRegistry()
        stored = ResourceRef("takeoff", "41")
        changed = ResourceRef("takeoff", "41", 7)
        draft = drafts.begin(
            draft_type="takeoff-mutation",
            database_id="database",
            bid_uid=None,
            page_uid=None,
            owning_surface="plan-view",
            affected_resources=(stored,),
        )
        conflicts = drafts.conflicts_for_changes(
            "database", (_change("database", changed, 2),)
        )
        self.assertEqual(
            tuple(conflict.draft_id for conflict in conflicts), (draft.draft_id,)
        )

    def test_local_draft_version_state_ignores_optional_bid_context(self):
        drafts = LocalDraftRegistry()
        stored = ResourceRef("takeoff", "41")
        contextual = ResourceRef("takeoff", "41", 7)
        original = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        updated = ConcurrencyToken(b"\x00" * 7 + b"\x02")
        draft = drafts.begin(
            draft_type="takeoff-mutation",
            database_id="database",
            bid_uid=None,
            page_uid=None,
            owning_surface="plan-view",
            affected_resources=(stored,),
            base_tokens=((stored, original),),
        )
        self.assertEqual(drafts.base_token("database", contextual), original)
        drafts.apply_local_versions("database", {contextual: updated})
        self.assertEqual(drafts.base_token("database", contextual), updated)
        self.assertEqual(drafts.get(draft.draft_id).base_tokens, ((stored, updated),))

    def test_local_draft_tracks_active_editor_and_all_leases(self):
        first = ResourceRef("takeoff", "1", 8)
        second = ResourceRef("takeoff", "2", 8)
        drafts = LocalDraftRegistry()
        draft = drafts.begin(
            draft_type="takeoff-geometry",
            database_id="database",
            bid_uid=8,
            page_uid=3,
            owning_surface="detached-2d",
            affected_resources=(first, second),
            operation_id="move-takeoffs",
        )
        locks = (
            ResourceLock("database", first, "first-token"),
            ResourceLock("database", second, "second-token"),
        )
        drafts.activate(draft.draft_id, locks, runtime_generation=7)
        active = drafts.get(draft.draft_id)
        self.assertEqual(active.state, LocalDraftState.ACTIVE)
        self.assertEqual(active.leases, locks)
        self.assertEqual(active.runtime_generation, 7)
        drafts.finish(draft.draft_id)
        self.assertIsNone(drafts.get(draft.draft_id))

    def test_authoritative_reload_uses_current_token_after_drafts_are_cancelled(self):
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        current = ConcurrencyToken(b"\x00" * 7 + b"\x02")
        reader = _TokenReader({resource: initial})
        tokens, drafts = _token_service(reader)
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
        reader.resources[resource] = current
        drafts.finish(draft.draft_id)
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
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
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

    def test_capability_check_uses_one_collaboration_status_snapshot(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        locked = ResourceRef("condition", "42", 8)

        class SnapshotChangingCapabilities(DatabaseCapabilityService):
            def __init__(self):
                super().__init__(descriptors, _PermissionProbe())
                self.status_reads = 0

            def collaboration_status(self, database_id):
                self.status_reads += 1
                if self.status_reads == 1:
                    return CollaborationStatus(
                        database_id=database_id,
                        state=SynchronizationState.HEALTHY,
                        locked_resources=frozenset({locked}),
                    )
                return CollaborationStatus(
                    database_id=database_id,
                    state=SynchronizationState.STOPPED,
                )

        capabilities = SnapshotChangingCapabilities()
        capabilities.mark_connected(descriptor.database_id)
        self.assertFalse(capabilities.is_editable(descriptor.database_id, locked))
        self.assertEqual(capabilities.status_reads, 1)

    def test_resource_conflict_is_targeted_and_cleared_by_reconciliation(self):
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
                _change(
                    database_id,
                    condition_resource,
                    1,
                    changed_fields=("name", "z_value"),
                ),
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
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual(set(project_data.conditions), {"42"})
        self.assertEqual([area.uid for area in project_data.areas], ["6"])
        names = [event for event, _payload in events.published]
        self.assertEqual(names.count(AppEvents.CONDITIONS_CHANGED), 1)
        self.assertEqual(names.count(AppEvents.REMOTE_AREAS_CHANGED), 1)
        condition_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.CONDITIONS_CHANGED
        )
        self.assertEqual(condition_event["changed_fields"], ["name", "z_value"])
        self.assertEqual(condition_event["change_operations"], ["update"])
        self.assertTrue(condition_event["invalidates_undo"])

    def test_remote_transaction_publishes_one_deferred_plan_projection(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("condition", "42", 8),
                        1,
                        changed_fields=("name",),
                    ),
                    _change(database_id, ResourceRef("area", "6", 8), 2),
                ),
            ),
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
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        projected = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        ]
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["runtime_generation"], 5)
        self.assertEqual(projected[0]["condition_uids"], ("42",))
        self.assertEqual(projected[0]["condition_changed_fields"], ("name",))
        self.assertTrue(projected[0]["areas_changed"])
        granular = [
            payload
            for event, payload in events.published
            if event
            in {
                AppEvents.CONDITIONS_CHANGED,
                AppEvents.REMOTE_AREAS_CHANGED,
            }
        ]
        self.assertEqual(
            [payload["defer_plan_projection"] for payload in granular],
            [True, True],
        )

    def test_local_area_completion_is_identified_on_granular_event(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("area", "6", 8), 2),),
            ),
            areas_by_bid={
                8: (
                    BidArea(
                        uid="6",
                        bid_uid="8",
                        parent_uid="0",
                        name="Local Area",
                        sequence=1,
                    ),
                )
            },
        )
        self.assertTrue(service.apply(hydrated, local_completion=True).applied)
        area_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.REMOTE_AREAS_CHANGED
        )
        self.assertTrue(area_event["local_completion"])

    def test_condition_folder_only_change_is_not_projected_as_condition_geometry(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("condition_folder", "5", 8),
                        1,
                        changed_fields=("name",),
                    ),
                    _change(
                        database_id,
                        ResourceRef("conditions_collection", "8", 8),
                        2,
                    ),
                ),
            ),
            conditions_by_bid={8: {"42": Condition(uid="42", name="Walls")}},
            condition_folders_by_bid={8: {"5": object()}},
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        condition_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.CONDITIONS_CHANGED
        )
        self.assertEqual(condition_event["condition_uids"], [])
        self.assertEqual(condition_event["changed_fields"], ["condition_folder"])
        self.assertEqual(condition_event["change_operations"], [])
        self.assertFalse(
            any(
                event is AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
                for event, _payload in events.published
            )
        )

    def test_valid_remote_takeoff_reconciles_and_requests_one_active_plan_update(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        takeoff = Takeoff(uid="30", condition_uid="10", page_uid="20")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("takeoff", "30", 8), 2),),
            ),
            conditions_by_bid={8: {"10": Condition(uid="10")}},
            condition_folders_by_bid={8: {}},
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[takeoff],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[takeoff])},
                )
            },
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        content_events = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        ]
        projection_events = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        ]
        self.assertEqual(len(content_events), 1)
        self.assertEqual(content_events[0]["families"], ["takeoffs"])
        self.assertEqual(len(projection_events), 1)

    def test_remote_annotation_projection_carries_old_and_new_page_ownership(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.annotations = [
            BidAnnotation(
                uid="annotation-1",
                annotation_type=ANNOTATION_TYPE_TEXT,
                page_uid="page-1",
            )
        ]
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        moved_annotation = BidAnnotation(
            uid="annotation-1",
            annotation_type=ANNOTATION_TYPE_TEXT,
            page_uid="page-2",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("annotation", "text/annotation-1", 8),
                        2,
                    ),
                ),
            ),
            bid_data_by_bid={8: BidLoadResult(bid_annotations=[moved_annotation])},
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        content = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        )
        projection = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        )
        self.assertEqual(
            content["affected_page_uids_by_family"],
            {"annotations": ("page-1", "page-2")},
        )
        self.assertEqual(
            projection["affected_page_uids_by_family"],
            {"annotations": ("page-1", "page-2")},
        )

    def test_local_takeoff_projection_replaces_transient_identity_as_one_change(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        operation_id = "54a05683-1032-431d-b57b-3552317fc74b"
        preview_uid = queued_takeoff_preview_uid(operation_id, 0)
        takeoff = Takeoff(uid="30", condition_uid="10", page_uid="20")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("takeoff", "30", 8), 2),),
            ),
            conditions_by_bid={8: {"10": Condition(uid="10")}},
            condition_folders_by_bid={8: {}},
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[takeoff],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[takeoff])},
                )
            },
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
            resource_uid_aliases_by_family={"takeoffs": (preview_uid,)},
        )
        self.assertTrue(service.apply(hydrated, barrier, local_completion=True).applied)
        self.assertEqual(project_data.removed_transient_takeoff_uids, [preview_uid])
        content = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        )
        projection = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        )
        self.assertEqual(
            content["resource_uids_by_family"]["takeoffs"],
            sorted((preview_uid, "30")),
        )
        self.assertEqual(
            projection["resource_uids_by_family"]["takeoffs"],
            tuple(sorted((preview_uid, "30"))),
        )

    def test_unrelated_remote_takeoff_refresh_preserves_pending_preview(self):
        database_id = "database"
        aggregate = OstAggregate(None)
        aggregate.current_bid_ref = BidRef(database_id, "8")
        aggregate.set_pages({"20": Page(uid="20", name="Sheet")})
        project_data = ProjectDataService(aggregate)
        preview = Takeoff(
            uid="pending:takeoff-placement:operation-1:0",
            condition_uid="10",
            page_uid="20",
        )
        project_data.add_transient_takeoffs([preview])
        remote = Takeoff(uid="30", condition_uid="10", page_uid="20")
        self.assertTrue(
            project_data.replace_remote_bid_families(
                BidRef(database_id, "8"),
                BidLoadResult(
                    bid_takeoffs=[remote],
                    pages={
                        "20": Page(
                            uid="20",
                            name="Sheet",
                            takeoffs=[remote],
                        )
                    },
                ),
                {"takeoffs"},
            )
        )
        self.assertEqual(
            {takeoff.uid for takeoff in aggregate.bid_takeoffs},
            {preview.uid, remote.uid},
        )
        self.assertEqual(
            {takeoff.uid for takeoff in aggregate.get_page("20").takeoffs},
            {preview.uid, remote.uid},
        )

    def test_self_only_checkpoint_does_not_schedule_plan_projection(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            _ProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(
            service.apply(
                HydratedDatabaseChangeBatch(_batch(database_id, "epoch", 1, 2, ())),
                barrier,
            ).applied
        )
        self.assertNotIn(
            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
            [event for event, _payload in events.published],
        )

    def test_hierarchy_only_change_does_not_schedule_plan_projection(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()

        class _HierarchyProjectData(_ProjectData):
            def replace_database_hierarchy(self, _file_entry, _cdn_types):
                pass

        service = RemoteChangeReconciliationService(
            _HierarchyProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        hierarchy_file = HierarchyFileEntry(
            file_path=database_id,
            display_name="SQL",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("database", database_id), 2),),
            ),
            hierarchy_file=hierarchy_file,
            settings_defaults={"next_bid_no": 1},
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        published = [event for event, _payload in events.published]
        self.assertIn(AppEvents.REMOTE_HIERARCHY_CHANGED, published)
        self.assertNotIn(AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED, published)

    def test_condition_type_only_change_refreshes_conditions_without_view_rebuild(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()

        class _ConditionTypeProjectData(_ProjectData):
            def replace_database_hierarchy(self, _file_entry, _cdn_types):
                pass

        service = RemoteChangeReconciliationService(
            _ConditionTypeProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        hierarchy_file = HierarchyFileEntry(
            file_path=database_id,
            display_name="SQL",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("condition_type", "5"),
                        1,
                        changed_fields=("name",),
                    ),
                    _change(
                        database_id,
                        ResourceRef("condition_types_collection", "database"),
                        2,
                    ),
                ),
            ),
            hierarchy_file=hierarchy_file,
            cdn_types={"5": CdnType(uid="5", name="Concrete")},
            settings_defaults={"next_bid_no": 1},
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        condition_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.CONDITIONS_CHANGED
        )
        self.assertEqual(condition_event["changed_fields"], ["condition_type_catalog"])
        published = [event for event, _payload in events.published]
        self.assertNotIn(AppEvents.REMOTE_HIERARCHY_CHANGED, published)
        self.assertNotIn(AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED, published)

    def test_initial_sql_hierarchy_registration_includes_cdn_types(self):
        database_id = "sql-database"
        registered = []

        class _InactiveProjectData(_ProjectData):
            def __init__(self):
                super().__init__("access-database")

            def replace_database_hierarchy(self, file_entry, cdn_types):
                registered.append((file_entry, cdn_types))

        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            _InactiveProjectData(),
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        hierarchy_file = HierarchyFileEntry(
            file_path=database_id,
            display_name="SQL",
        )
        cdn_types = {"1": CdnType(uid="1", name="Linear")}
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                1,
                (
                    _change(
                        database_id,
                        ResourceRef("database", database_id),
                    ),
                ),
            ),
            hierarchy_file=hierarchy_file,
            cdn_types=cdn_types,
            settings_defaults={"next_bid_no": 1},
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual(registered, [(hierarchy_file, cdn_types)])

    def test_remote_events_publish_only_after_all_model_merges(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)

        def switch_active_bid(**_payload):
            project_data.bid_ref = BidRef(database_id, "9")

        events.subscribe(AppEvents.CONDITIONS_CHANGED, switch_active_bid)
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
        self.assertTrue(service.apply(hydrated).applied)
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
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)).applied)
        self.assertEqual(set(project_data.conditions), {"old"})
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
            initial,
        )

    def test_incomplete_cover_sheet_batch_does_not_cache_partial_snapshots(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
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
            (
                _change(
                    database_id,
                    ResourceRef("cover_sheet", "8", 8),
                    2,
                ),
            ),
        )
        result = service.apply(
            HydratedDatabaseChangeBatch(
                batch,
                cover_sheet_by_bid={8: object()},
            )
        )
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind,
            ReconciliationFailureKind.MALFORMED_PAYLOAD,
        )
        self.assertEqual(project_data.cover_sheets, {})
        self.assertEqual(project_data.page_delete_content, {})

    def test_malformed_remote_takeoff_graph_is_rejected_before_projection(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        change = _change(database_id, ResourceRef("takeoffs_collection", "8", 8), 2)
        orphan = Takeoff(
            uid="4485",
            condition_uid="10",
            page_uid="20",
            parent_uid="4393",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(database_id, "epoch", 1, 2, (change,)),
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[orphan],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[orphan])},
                )
            },
        )
        result = service.apply(hydrated)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind, ReconciliationFailureKind.MALFORMED_PAYLOAD
        )
        self.assertEqual(events.published, [])

    def test_reconciliation_returns_typed_result_without_mutable_failure_state(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        malformed = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("condition", "42", 8), 2),),
            )
        )
        result = service.apply(malformed)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind,
            ReconciliationFailureKind.MALFORMED_PAYLOAD,
        )
        self.assertFalse(hasattr(service, "last_failure_kind"))

    def test_remote_takeoff_cycle_is_rejected_before_projection(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, _EventBus(), tokens, drafts, ConflictResolutionService()
        )
        first = Takeoff(uid="30", condition_uid="10", page_uid="20", parent_uid="31")
        second = Takeoff(uid="31", condition_uid="10", page_uid="20", parent_uid="30")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("takeoffs_collection", "8", 8),
                        2,
                    ),
                ),
            ),
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[first, second],
                    pages={
                        "20": Page(uid="20", name="Sheet", takeoffs=[first, second])
                    },
                )
            },
        )
        result = service.apply(hydrated)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind, ReconciliationFailureKind.MALFORMED_PAYLOAD
        )

    def test_remote_takeoff_with_missing_condition_is_rejected(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, _EventBus(), tokens, drafts, ConflictResolutionService()
        )
        takeoff = Takeoff(uid="30", condition_uid="999", page_uid="20")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("takeoffs_collection", "8", 8),
                        2,
                    ),
                ),
            ),
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[takeoff],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[takeoff])},
                )
            },
        )
        result = service.apply(hydrated)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind, ReconciliationFailureKind.MALFORMED_PAYLOAD
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
        self.assertTrue(service.apply(HydratedDatabaseChangeBatch(batch)).applied)
        self.assertEqual(events.published, [])

    def test_default_layer_change_uses_authoritative_reconciliation(self):
        self.assertIn("default_layers_collection", SUPPORTED_REMOTE_RESOURCE_TYPES)
        database_id = "database"
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
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
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            default_layers=(
                BidLayer(
                    uid="5",
                    bid_uid="",
                    name="Default",
                    show=True,
                    sequence=1,
                    is_template=True,
                ),
            ),
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual(
            project_data.database_settings[database_id]["default_layers"][0].uid,
            "5",
        )
        self.assertEqual(len(tokens.expected_versions(database_id, (resource,))), 1)

    def test_master_data_change_replaces_all_authoritative_lists_and_publishes(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        events = _EventBus()
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        resources = (
            ResourceRef("job_statuses_collection", database_id),
            ResourceRef("employees_collection", database_id),
            ResourceRef("pay_classes_collection", database_id),
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            3,
            tuple(
                _change(database_id, resource, sequence)
                for sequence, resource in enumerate(resources, start=1)
            ),
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            job_statuses=(JobStatus("job-1", "Open"),),
            employees=(Employee("employee-1", first_name="Ava"),),
            pay_classes=(PayClass("pay-1", "Regular"),),
            used_job_status_uids=frozenset({"job-1"}),
            used_employee_uids=frozenset({"employee-1"}),
        )
        self.assertTrue(service.apply(hydrated).applied)
        settings = project_data.database_settings[database_id]
        self.assertEqual(settings["job_statuses"][0].uid, "job-1")
        self.assertEqual(settings["employees"][0].uid, "employee-1")
        self.assertEqual(settings["pay_classes"][0].uid, "pay-1")
        master_events = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_MASTER_DATA_CHANGED
        ]
        self.assertEqual(
            master_events,
            [
                {
                    "database_id": database_id,
                    "families": ["job_statuses", "employees", "pay_classes"],
                }
            ],
        )

    def test_job_status_and_employee_hydration_refreshes_hierarchy_displays(self):
        hierarchy = HierarchyFileEntry(file_path="database")
        parse_calls = []

        class _Reader:
            @staticmethod
            def parse_file_connection(database_id, _connection):
                parse_calls.append(database_id)
                return hierarchy, {}

            @staticmethod
            def _parse_settings_defaults(_connection):
                return {}

            @staticmethod
            def _parse_job_statuses(_connection):
                return (JobStatus("status-1", "Renamed"),)

            @staticmethod
            def _parse_used_job_status_uids(_connection):
                return {"status-1"}

            @staticmethod
            def _parse_employees_and_pay_classes(_connection):
                return ([Employee("employee-1", first_name="Renamed")], [])

            @staticmethod
            def _parse_used_employee_uids(_connection):
                return {"employee-1"}

        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("job_statuses_collection", "database"),
                    1,
                ),
                _change(
                    "database",
                    ResourceRef("employees_collection", "database"),
                    2,
                ),
            ),
        )
        hydrated = reader.hydrate_connection(batch, object())
        self.assertIs(hydrated.hierarchy_file, hierarchy)
        self.assertEqual(parse_calls, ["database"])

    def test_inactive_database_rejects_incomplete_cover_sheet_hydration(self):
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
                    ResourceRef("cover_sheet", "8", 8),
                    2,
                ),
            ),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)).applied)

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
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)).applied)
        event, payload = events.published[-1]
        self.assertIs(event, AppEvents.SYNCHRONIZATION_CONFLICT)
        self.assertFalse(payload["blocks_database"])
        self.assertEqual(payload["bid_uid"], "8")

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

    def test_sql_writer_classifies_session_and_lease_conflicts(self):
        sessions = DatabaseSessionRegistry()
        sessions.register("database", "current-session")
        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            SimpleNamespace(),
            session_registry=sessions,
        )
        session_result = writer.execute(
            DatabaseMutationRequest(
                database_id="database",
                session_id="stale-session",
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                request_hash="a" * 64,
            ),
            lambda _recorder: True,
        )
        self.assertEqual(
            session_result.conflict.kind, SynchronizationConflictKind.SESSION
        )
        for error_code, expected_kind in (
            (SqlErrorCode.LOCKED, SynchronizationConflictKind.LEASE),
            (SqlErrorCode.SESSION_EXPIRED, SynchronizationConflictKind.SESSION),
        ):
            classified_writer = SqlProjectWriter.__new__(SqlProjectWriter)

            def fail(_request, _operation, code=error_code):
                raise SqlInfrastructureError(SqlErrorDetails(code, code.value))

            classified_writer._execute_mutation_transaction = fail
            result = classified_writer.execute(
                DatabaseMutationRequest(
                    database_id="database",
                    session_id=None,
                    operation_id=str(uuid.uuid4()),
                    mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                    request_hash="a" * 64,
                ),
                lambda _recorder: True,
            )
            self.assertEqual(result.conflict.kind, expected_kind)

    def test_session_identity_comparison_normalizes_uuid_text(self):
        self.assertTrue(
            session_identities_equal(
                "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            )
        )
        self.assertFalse(session_identities_equal("session-a", "session-b"))
        self.assertFalse(session_identities_equal("session-a", "SESSION-A"))

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
        self.assertTrue(coordinator.start_database(sql_descriptor.database_id))
        runtime = coordinator._runtime(sql_descriptor.database_id)
        try:
            self.assertTrue(store.started.wait(5))
            self.assertTrue(store.polled.wait(5))
            self.assertTrue(healthy.wait(5))
            _stop_database(coordinator, sql_descriptor.database_id)
            self.assertTrue(store.closed.wait(5))
            self.assertEqual(sessions.get(sql_descriptor.database_id), "")
            self.assertIsNotNone(runtime)
            self.assertFalse(runtime.thread.is_alive())
        finally:
            _shutdown_coordinator(coordinator)

    def test_unversioned_sql_does_not_read_collaboration_versions(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="EXTERNAL"),
            schema_version=0,
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
            )
        )
        failure_payload = next(
            payload
            for event, payload in events.published
            if event is AppEvents.FULL_RECONCILIATION_REQUIRED
        )
        self.assertIn("session-start", failure_payload["reason"])
        _shutdown_coordinator(coordinator)

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

    def test_queued_mutation_result_requires_current_keyword_shape(self):
        with self.assertRaises(TypeError):
            QueuedMutationResult("database", 1, "operation", True)

    def test_project_write_queues_takeoff_insert_with_page_and_condition_dependencies(
        self,
    ):
        queued = []

        class _MutationQueue:
            def queue_request(self, *args, **kwargs):
                queued.append((args, kwargs))
                return 7

        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: _MutationQueue()
        insert_calls = []
        service._insert_takeoffs_mutation = lambda *_args, **kwargs: (
            insert_calls.append(kwargs)
            or DatabaseMutationResult(
                operation_id=kwargs["operation_id"],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=["501"],
            )
        )
        callback = lambda _result: None
        specs = [
            InsertTakeoffSpec(
                condition_uid="10",
                page_uid="20",
                area_uid=None,
                position=[1.0, 2.0],
            ),
            InsertTakeoffSpec(
                condition_uid="11",
                page_uid="20",
                area_uid=None,
                position=[3.0, 4.0],
            ),
        ]
        generation = service.queue_takeoff_placement(
            "database",
            "8",
            specs,
            "7b3c5ac1-e623-44aa-8203-26a0125873b9",
            callback,
        )
        args, kwargs = queued[0]
        request = args[0]
        self.assertIsInstance(request, QueuedMutationRequest)
        self.assertEqual(request.database_id, "database")
        self.assertEqual(
            request.mutation_type, CollaborationMutationType.TAKEOFF_PLACEMENT
        )
        self.assertEqual(
            request.resources, (ResourceRef("takeoffs_collection", "8", 8),)
        )
        work_result = args[1]()
        self.assertEqual(
            work_result.outcome_status,
            MutationOutcomeStatus.COMMITTED,
        )
        self.assertEqual(work_result.created_resource_ids, ("501",))
        self.assertIs(args[2], callback)
        self.assertEqual(
            request.dependency_resources,
            (
                ResourceRef("condition", "10", 8),
                ResourceRef("condition", "11", 8),
                ResourceRef("page", "20", 8),
            ),
        )
        self.assertTrue(kwargs["result_validator"](work_result))
        self.assertNotIn("allow_resource_overlap", kwargs)
        self.assertEqual(generation, 7)
        self.assertEqual(
            insert_calls[0]["consistency_resources"],
            request.dependency_resources,
        )
        self.assertFalse(insert_calls[0]["publish_conflict_event"])

    def test_queued_takeoff_reassign_rejects_missing_member_before_bulk_update(self):
        queued = []

        class MutationQueue:
            def queue_request(self, *args, **kwargs):
                queued.append((args, kwargs))
                return 9

        class MutationExecutor:
            def __init__(self):
                self.verifications = []

            def verify_plan_items_exist(self, database_id, takeoff_uids, annotations):
                self.verifications.append(
                    (database_id, tuple(takeoff_uids), tuple(annotations))
                )
                raise RuntimeError("selected takeoff was deleted")

        executor = MutationExecutor()
        save_calls = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: MutationQueue()
        service._mutation_executor = executor
        service._save_takeoffs_condition = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )

        def execute_mutation(
            _database_id,
            _resources,
            operation,
            **_kwargs,
        ):
            value = operation(SimpleNamespace(record=lambda *_args, **_kwargs: None))
            return DatabaseMutationResult(
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

        service._execute_database_mutation = execute_mutation
        service.queue_plan_properties(
            "database",
            "8",
            "takeoff_condition",
            [("101", "20"), ("102", "20")],
            lambda _result: None,
            page_uids=("30",),
            dependency_resources=(ResourceRef("condition", "20", 8),),
        )
        with self.assertRaisesRegex(RuntimeError, "selected takeoff was deleted"):
            queued[0][0][1]()
        self.assertEqual(
            executor.verifications,
            [("database", ("101", "102"), ())],
        )
        self.assertEqual(save_calls, [])

    def test_queued_bulk_move_rejects_missing_member_before_geometry_update(self):
        queued = []

        class MutationQueue:
            def queue_request(self, *args, **kwargs):
                queued.append((args, kwargs))
                return 10

        class MutationExecutor:
            def __init__(self):
                self.verifications = []

            def verify_plan_items_exist(self, database_id, takeoff_uids, annotations):
                self.verifications.append(
                    (database_id, tuple(takeoff_uids), tuple(annotations))
                )
                raise RuntimeError("selected plan item was deleted")

        executor = MutationExecutor()
        save_calls = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: MutationQueue()
        service._mutation_executor = executor
        service._save_takeoff_positions = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )
        service._save_takeoff_rotations = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )
        service._save_annotation_positions = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )

        def execute_mutation(
            _database_id,
            _resources,
            operation,
            **_kwargs,
        ):
            value = operation(SimpleNamespace(record=lambda *_args, **_kwargs: None))
            return DatabaseMutationResult(
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

        service._execute_database_mutation = execute_mutation
        service.queue_plan_geometry(
            "database",
            "8",
            lambda _result: None,
            takeoff_positions=[
                ("101", [1.0, 2.0]),
                ("102", [3.0, 4.0]),
            ],
            annotation_positions=[("201", "line", [5.0, 6.0, 7.0, 8.0])],
            page_uids=("30",),
        )
        with self.assertRaisesRegex(RuntimeError, "selected plan item was deleted"):
            queued[0][0][1]()
        self.assertEqual(
            executor.verifications,
            [("database", ("101", "102"), (("201", "line"),))],
        )
        self.assertEqual(save_calls, [])

    def test_takeoff_insert_rejects_incomplete_identities_before_commit(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda _database_id, _bid_uid: False
        )
        service._insert_takeoffs = SimpleNamespace(
            execute=lambda _database_id, _bid_uid, _specs: ["501"]
        )
        specs = [
            InsertTakeoffSpec(
                condition_uid="10",
                page_uid="20",
                area_uid=None,
                position=[1.0, 2.0],
            ),
            InsertTakeoffSpec(
                condition_uid="10",
                page_uid="20",
                area_uid=None,
                position=[3.0, 4.0],
            ),
        ]

        class RejectingRecorder:
            def record(
                self,
                _resource,
                _operation,
                *,
                changed_fields=(),
                payload="",
            ):
                del changed_fields, payload
                self.fail("an incomplete identity batch must not be recorded")

            def fail(self, message):
                raise AssertionError(message)

        def execute_mutation(
            _database_id,
            _resources,
            operation,
            *,
            operation_id="",
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="",
            result_format_version=1,
            block_bid_child_locks=False,
            block_bid_active_editors=False,
            publish_conflict_event=True,
        ):
            del (
                operation_id,
                mutation_type,
                request_hash,
                result_format_version,
                block_bid_child_locks,
                block_bid_active_editors,
                publish_conflict_event,
            )
            return operation(RejectingRecorder())

        service._execute_database_mutation = execute_mutation
        with self.assertRaisesRegex(RuntimeError, "authoritative identity set"):
            service._insert_takeoffs_mutation("database", "8", specs)

    def test_empty_takeoff_inserts_do_not_create_mutation_requests(self):
        service = ProjectWriteService.__new__(ProjectWriteService)

        def reject_local_mutation(
            _database_id,
            _bid_uid,
            _specs,
            *,
            consistency_resources=(),
            publish_conflict_event=True,
            operation_id="",
            request_hash="",
        ):
            del (
                consistency_resources,
                publish_conflict_event,
                operation_id,
                request_hash,
            )
            self.fail("an empty insert must not enter the mutation boundary")

        service._insert_takeoffs_mutation = reject_local_mutation
        self.assertEqual(service.insert_takeoffs("database", "8", []), [])
        with self.assertRaisesRegex(ValueError, "requires at least one takeoff"):
            service.queue_takeoff_placement(
                "database",
                "8",
                [],
                "7b3c5ac1-e623-44aa-8203-26a0125873b9",
                lambda _result: None,
            )

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
        _shutdown_coordinator(coordinator)

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

    def test_lease_loss_event_requires_the_typed_loss_payload(self):
        with self.assertRaises(TypeError):
            AppEvents.EDIT_LEASE_LOST()
        loss = EditLeaseLoss(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(ResourceRef("condition", "42", 8),),
            reason="trust-lost",
        )
        self.assertIs(AppEvents.EDIT_LEASE_LOST(loss).loss, loss)

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
        caller_thread = threading.get_ident()
        self.assertTrue(
            coordinator.start_database(
                descriptor.database_id,
                retry_initial_failure=False,
            )
        )
        self.assertTrue(store.first_failure.wait(2))
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


if __name__ == "__main__":
    unittest.main()
