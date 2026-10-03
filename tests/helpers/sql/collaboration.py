import json
import queue
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    COLLABORATION_LOCK_SECONDS,
    COLLABORATION_STALE_SECONDS,
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
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG,
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
    CollaborationResourceFamily,
    coalesced_resource_type,
)
from ost_visualizer.application.dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.local_draft_dtos import (
    LocalDraftConflict,
    LocalDraftState,
)
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.conflict_resolution_service import (
    ConflictResolutionService,
)
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
from ost_visualizer.application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
    _QueuedMutation,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.page_info import BidPageInfo

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


from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.entity_version_reader import (
    DatabaseEntityVersionReader,
)
from ost_visualizer.infrastructure.sql.collaboration_store import (
    SqlCollaborationStore,
    _change_from_row,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.remote_change_reader import (
    _MAX_HYDRATION_BATCH_PARAMETERS,
    _MAX_HYDRATION_BATCH_QUERIES,
    SqlRemoteChangeReader,
    _execute_recorded_queries,
    _recorded_query_batches,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.schema_validator import SqlSchemaValidator
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation


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
    def capture_navigation_owner(self, _database_id):
        return None

    def navigation_owner_is_current(self, _database_id, owner):
        return owner is None

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


class _RaisingReconciliation(_Reconciliation):
    def apply(self, _batch, projection_barrier=None, *, local_completion=False):
        raise RuntimeError("reconciliation callback failed")


class _DeferredProjectionReconciliation(_Reconciliation):
    def __init__(self):
        super().__init__()
        self.token = None

    def apply(self, _batch, projection_barrier=None, *, local_completion=False):
        self.batches.append(_batch)
        self.projection_barriers.append(projection_barrier)
        self.token = projection_barrier.register("test-plan")
        return ReconciliationResult(applied=True)


class _FailFirstLocalProjectionReconciliation(_Reconciliation):
    def __init__(self):
        super().__init__()
        self.token = None
        self.local_projection_started = threading.Event()

    def apply(self, _batch, projection_barrier=None, *, local_completion=False):
        self.batches.append(_batch)
        self.projection_barriers.append(projection_barrier)
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
        *,
        stop_requested=None,
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

    def start_session(self, *args, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            self.failed.set()
            raise DatabaseCatalogError("Sign in again.", credential_required=True)
        self.restarted.set()
        return super().start_session(*args, **kwargs)


class _TransientRecoveryStore(_CollaborationStore):
    def __init__(self):
        super().__init__()
        self.failed_once = False

    def start_session(self, *args, **kwargs):
        session = super().start_session(*args, **kwargs)
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
        *,
        stop_requested=None,
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
        self.takeoffs = []
        self.layers = []

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
        if CollaborationResourceFamily.LAYERS.value in families:
            self.layers = list(bid_data.bid_layers)
        if CollaborationResourceFamily.ANNOTATIONS.value in families:
            self.annotations = list(bid_data.bid_annotations)
        if CollaborationResourceFamily.TAKEOFFS.value in families:
            self.takeoffs = list(bid_data.bid_takeoffs)
        return True

    def get_bid_layer_snapshot(self):
        return list(self.layers)

    def get_all_takeoffs(self):
        return list(self.takeoffs)

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


class _FakeSqlServerState:
    """In-memory model of one database's ostv.Sessions/ostv.Locks tables.
    It models what SqlCollaborationStore relies on the SERVER for: every
    timestamp is the server UTC clock (`now`, advanced only by tests and never
    supplied by a client); a session is active only while it is not disconnected
    and its last heartbeat is within COLLABORATION_STALE_SECONDS; a lock row is
    live only until its server-side expiry and is exclusive per
    (resource type, resource id) across sessions whatever the Bid context is;
    acquisition is all-or-nothing in sorted order and re-acquiring an owned row
    returns its existing token. It is only a fake: no T-SQL, isolation levels,
    sp_getapplock waits or deadlocks are involved, so it proves coordinator
    behaviour against the store contract, never SQL Server behaviour.
    """

    def __init__(self):
        self.guard = threading.RLock()
        self.now = 1_000_000.0
        self.sessions = {}
        self.locks = {}
        self.acquire_orders = []
        self.closed_reasons = []

    def advance(self, seconds):
        with self.guard:
            self.now += seconds

    def _session_is_active(self, session_id):
        session = self.sessions.get(session_id)
        return (
            session is not None
            and not session["disconnected"]
            and session["heartbeat"] >= self.now - COLLABORATION_STALE_SECONDS
        )

    @staticmethod
    def _expired_error(message):
        return SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.SESSION_EXPIRED, message)
        )

    def start(self, session_id):
        with self.guard:
            self.sessions[session_id] = {
                "heartbeat": self.now,
                "disconnected": False,
            }

    def heartbeat(self, session_id):
        with self.guard:
            if not self._session_is_active(session_id):
                raise self._expired_error(
                    "The SQL collaboration session expired. Reconnecting is "
                    "required before editing."
                )
            self.sessions[session_id]["heartbeat"] = self.now

    def disconnect(self, session_id, reason):
        with self.guard:
            self.closed_reasons.append((session_id, reason))
            if session_id in self.sessions:
                self.sessions[session_id]["disconnected"] = True
            for key in [
                key for key, lock in self.locks.items() if lock["owner"] == session_id
            ]:
                del self.locks[key]

    def _live_locks(self):
        return {
            key: lock for key, lock in self.locks.items() if lock["expires"] > self.now
        }

    def live_lock_tokens(self):
        with self.guard:
            return {key: lock["token"] for key, lock in self._live_locks().items()}

    def list_locks(self, excluding_session_id, bid_uid):
        with self.guard:
            return tuple(
                lock["resource"]
                for _key, lock in sorted(self._live_locks().items())
                if lock["owner"] != excluding_session_id
                and (bid_uid is None or lock["resource"].bid_uid == bid_uid)
            )

    def acquire(self, session_id, resources):
        ordered = tuple(sorted(set(resources)))
        with self.guard:
            self.acquire_orders.append(
                tuple(resource.lease_identity for resource in ordered)
            )
            if not self._session_is_active(session_id):
                raise self._expired_error(
                    "The SQL collaboration session expired. Reconnect before editing."
                )
            live = self._live_locks()
            for resource in ordered:
                held = live.get(resource.lease_identity)
                if held is not None and held["owner"] != session_id:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.LOCKED,
                            f"{resource.resource_type} {resource.resource_id} "
                            "is being edited by another session.",
                        )
                    )
            granted = []
            for resource in ordered:
                key = resource.lease_identity
                held = live.get(key)
                if held is None:
                    held = {
                        "resource": resource,
                        "owner": session_id,
                        "token": str(uuid.uuid4()),
                    }
                    self.locks[key] = held
                held["expires"] = self.now + COLLABORATION_LOCK_SECONDS
                granted.append((resource, held["token"]))
            return tuple(granted)

    def renew(self, session_id, lock_token):
        with self.guard:
            if not self._session_is_active(session_id):
                raise self._expired_error(
                    "The SQL collaboration session expired. Reconnect before editing."
                )
            for lock in self._live_locks().values():
                if lock["token"] == lock_token and lock["owner"] == session_id:
                    lock["expires"] = self.now + COLLABORATION_LOCK_SECONDS
                    return lock["resource"]
            raise self._expired_error(
                "The edit lock expired and can no longer be renewed."
            )

    def release(self, session_id, lock_token):
        with self.guard:
            for key, lock in list(self.locks.items()):
                if lock["token"] == lock_token and lock["owner"] == session_id:
                    del self.locks[key]
                    return True
            return False


class _ServerBackedStore(_CollaborationStore):
    """_CollaborationStore whose sessions and locks live in _FakeSqlServerState.
    Unlike _LockingStore it enforces cross-session exclusivity, unique tokens,
    sorted all-or-nothing acquisition, server-side lease expiry and stale-session
    rejection with the same SqlInfrastructureError codes as the real store.
    """

    def __init__(self, state=None):
        super().__init__()
        self.state = state if state is not None else _FakeSqlServerState()
        self.acquire_requests = []
        self.heartbeats = []
        self.renewals = []

    def start_session(self, database_id, session_id, *args, **kwargs):
        self.state.start(session_id)
        return super().start_session(database_id, session_id, *args, **kwargs)

    def heartbeat(
        self, database_id, session_id, acknowledged_version, bid_uid, page_uid, mode
    ):
        self.state.heartbeat(session_id)
        self.heartbeats.append((session_id, acknowledged_version, bid_uid, page_uid))
        return super().heartbeat(
            database_id, session_id, acknowledged_version, bid_uid, page_uid, mode
        )

    def close_session(self, database_id, session_id, reason):
        self.state.disconnect(session_id, reason)
        super().close_session(database_id, session_id, reason)

    def list_locks(self, database_id, excluding_session_id, bid_uid=None):
        return tuple(
            ResourceLock(database_id, resource, "foreign-token")
            for resource in self.state.list_locks(excluding_session_id, bid_uid)
        )

    def acquire_locks(self, database_id, session_id, resources, operation_description):
        self.acquire_requests.append(tuple(resources))
        return tuple(
            ResourceLock(database_id, resource, token)
            for resource, token in self.state.acquire(session_id, resources)
        )

    def renew_lock(self, database_id, session_id, lock_token):
        resource = self.state.renew(session_id, lock_token)
        self.renewals.append((session_id, lock_token))
        return ResourceLock(database_id, resource, lock_token)

    def release_lock(self, database_id, session_id, lock_token):
        return self.state.release(session_id, lock_token)


class _UiThreadDispatcher:
    """IThreadCallbackBridge model: dispatch() only queues the callback.
    Callbacks run exclusively when the thread that created the dispatcher (the
    test thread, standing in for the Qt UI thread) calls pump_until(), so a
    callback that production runs directly on a worker thread instead of
    crossing the bridge is observable through `executed_on`.
    """

    def __init__(self):
        self.ui_thread = threading.get_ident()
        self._queue = queue.Queue()
        self.dispatched_from = []
        self.executed_on = []

    def dispatch(self, callback, payload=()):
        self.dispatched_from.append(threading.get_ident())
        self._queue.put((callback, payload))

    def pump_until(self, predicate, timeout=5.0):
        if threading.get_ident() != self.ui_thread:
            raise AssertionError("The UI dispatcher must be pumped on its own thread")
        deadline = time.monotonic() + timeout
        while not predicate():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                callback, payload = self._queue.get(timeout=min(remaining, 0.02))
            except queue.Empty:
                continue
            self.executed_on.append((callback.__name__, threading.get_ident()))
            callback(payload)
        return True

    def pump_idle(self, is_busy=None, max_callbacks=200, timeout=10.0):
        """Run queued callbacks until the queue is empty and no collaboration
        drain thread (or other `is_busy()` work) is still running, then return the
        number of callbacks run. `max_callbacks` is the runaway guard: a feedback
        loop that keeps scheduling work stops there instead of spinning, and the
        caller asserts the returned count stayed below it. Work that never goes
        idle (a busy thread that schedules no callbacks) fails after `timeout`."""
        if threading.get_ident() != self.ui_thread:
            raise AssertionError("The UI dispatcher must be pumped on its own thread")
        if is_busy is None:

            def is_busy():
                return any(
                    thread.name.startswith("SqlCollaborationDrain-")
                    and thread.is_alive()
                    for thread in threading.enumerate()
                )

        executed = 0
        deadline = time.monotonic() + timeout
        while executed < max_callbacks:
            try:
                callback, payload = self._queue.get(timeout=0.02)
            except queue.Empty:
                if is_busy():
                    if time.monotonic() > deadline:
                        raise AssertionError(
                            f"The UI dispatcher was still busy after {timeout} s"
                        )
                    continue
                try:
                    callback, payload = self._queue.get_nowait()
                except queue.Empty:
                    return executed
            self.executed_on.append((callback.__name__, threading.get_ident()))
            callback(payload)
            executed += 1
        return executed


class _ThreadRecordingEventBus(_EventBus):
    """_EventBus that records the thread each event was published on."""

    def __init__(self):
        super().__init__()
        self.publish_threads = []

    def publish(self, event, **payload):
        self.publish_threads.append((event, threading.get_ident()))
        super().publish(event, **payload)
