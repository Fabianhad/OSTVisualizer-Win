from __future__ import annotations
import getpass
import logging
import platform
import queue
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional
from ...domain.entities.database_descriptor import DatabaseBackend
from ..dtos.collaboration_resource_catalog import resource_definition
from ..dtos.application_info import APPLICATION_VERSION
from ..dtos.collaboration_dtos import (
    CollaborationStatus,
    CollaborationMetrics,
    CollaborationPollingPolicy,
    COLLABORATION_STALE_SECONDS,
    DatabaseSession,
    EditLeaseResult,
    PresenceMode,
    ResourceLock,
    ResourceRef,
    SynchronizationState,
)
from ..events.app_events import AppEvents
from ..interfaces.i_collaboration_store import ICollaborationStore
from ..interfaces.i_database_catalog import DatabaseCatalogError
from ..interfaces.i_database_descriptor_registry import IDatabaseDescriptorRegistry
from ..interfaces.i_database_session_registry import IDatabaseSessionRegistry
from ..interfaces.i_remote_change_reader import IRemoteChangeReader
from ..interfaces.i_shutdown_aware import IShutdownAware
from ..interfaces.i_thread_callback_bridge import IThreadCallbackBridge
from .database_capability_service import DatabaseCapabilityService
from .local_draft_registry import LocalDraftRegistry
from .remote_change_reconciliation_service import RemoteChangeReconciliationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EditLeaseRequest:
    database_id: str
    resources: tuple[ResourceRef, ...]
    operation_description: str


@dataclass
class _DatabaseRuntime:
    database_id: str
    generation: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    ready_event: threading.Event = field(default_factory=threading.Event)
    command_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    session: Optional[DatabaseSession] = None
    acknowledged_version: int = 0
    observed_high_water_version: int = 0
    feed_epoch: str = ""
    healthy: bool = False
    edit_depth: int = 0
    owned_locks: dict[ResourceRef, ResourceLock] = field(default_factory=dict)
    draft_ids: dict[frozenset[ResourceRef], str] = field(default_factory=dict)
    edit_requests: queue.Queue = field(default_factory=queue.Queue)
    release_requests: queue.Queue = field(default_factory=queue.Queue)
    pending_delivery: bool = False
    recovery_requested: bool = False
    recovery_ready: bool = False
    bid_uid: Optional[int] = None
    page_uid: Optional[int] = None
    mode: PresenceMode = PresenceMode.VIEWING
    close_reason: str = "closed"
    thread: Optional[threading.Thread] = None
    poll_count: int = 0
    poll_duration_seconds: float = 0.0
    transaction_count: int = 0
    change_row_count: int = 0
    reconciliation_count: int = 0
    reconciliation_duration_seconds: float = 0.0
    retention_gap_count: int = 0
    reconnect_count: int = 0


class SqlCollaborationCoordinator(IShutdownAware):
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        store: ICollaborationStore,
        remote_reader: IRemoteChangeReader,
        dispatcher: IThreadCallbackBridge,
        reconciliation: RemoteChangeReconciliationService,
        capability_service: DatabaseCapabilityService,
        session_registry: IDatabaseSessionRegistry,
        concurrency_tokens,
        local_drafts: LocalDraftRegistry,
        event_bus,
        supported_schema_version: int,
        polling_policy: CollaborationPollingPolicy = CollaborationPollingPolicy(),
    ) -> None:
        self._registry = descriptor_registry
        self._store = store
        self._remote_reader = remote_reader
        self._dispatcher = dispatcher
        self._reconciliation = reconciliation
        self._capabilities = capability_service
        self._sessions = session_registry
        self._concurrency_tokens = concurrency_tokens
        self._local_drafts = local_drafts
        self._event_bus = event_bus
        self._supported_schema_version = supported_schema_version
        self._polling_policy = polling_policy
        self._client_instance_id = str(uuid.uuid4())
        self._runtimes: dict[str, _DatabaseRuntime] = {}
        self._lock = threading.Lock()
        self._next_generation = 0
        self._shutting_down = False
        self._event_bus.subscribe(AppEvents.FILE_OPENED, self._on_file_opened)
        self._event_bus.subscribe(AppEvents.FILE_UNLOADED, self._on_file_unloaded)
        self._event_bus.subscribe(
            AppEvents.DATABASE_REFRESHED, self._on_database_refreshed
        )
        self._event_bus.subscribe(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            self._on_database_capabilities_changed,
        )

    def _on_file_opened(self, file_path: str, **_event_data) -> None:
        self.start_database(file_path)

    def _on_file_unloaded(self, file_path: str, **_event_data) -> None:
        descriptor = self._registry.resolve(file_path)
        database_id = descriptor.database_id if descriptor is not None else file_path
        self.stop_database(database_id)

    def _on_database_refreshed(self, file_path: str, **_event_data) -> None:
        runtime = self._runtime(file_path)
        if runtime is None:
            return
        had_resource_conflicts = bool(
            self._capabilities.collaboration_status(file_path).conflicted_resources
        )
        self._capabilities.clear_collaboration_conflicts(file_path)
        with runtime.lock:
            if runtime.recovery_requested:
                runtime.recovery_ready = True
                runtime.pending_delivery = False
                runtime.command_event.set()
                return
        if had_resource_conflicts:
            self._event_bus.publish(
                AppEvents.DATABASE_CAPABILITIES_CHANGED,
                file_path=file_path,
            )

    def _on_database_capabilities_changed(self, file_path: str, **_event_data) -> None:
        runtime = self._runtime(file_path)
        if runtime is None:
            return
        thread = runtime.thread
        if thread is None or thread.is_alive() or thread.ident is None:
            return
        self.stop_database(file_path, "reconfigured")
        self.start_database(file_path)

    def start_database(self, database_id: str) -> bool:
        descriptor = self._registry.resolve(database_id)
        if (
            descriptor is None
            or descriptor.backend != DatabaseBackend.SQL_SERVER
            or descriptor.schema_version != self._supported_schema_version
        ):
            return False
        with self._lock:
            if self._shutting_down or database_id in self._runtimes:
                return False
            self._next_generation += 1
            runtime = _DatabaseRuntime(database_id, self._next_generation)
            runtime.thread = threading.Thread(
                target=self._worker,
                args=(runtime,),
                daemon=True,
                name=f"SqlCollaboration-{database_id[:8]}",
            )
            self._runtimes[database_id] = runtime
        self._set_state(database_id, SynchronizationState.CONNECTING)
        runtime.thread.start()
        return True

    def stop_database(self, database_id: str, reason: str = "closed") -> None:
        with self._lock:
            runtime = self._runtimes.pop(database_id, None)
        if runtime is None:
            return
        runtime.close_reason = reason
        runtime.stop_event.set()
        runtime.ready_event.set()
        runtime.command_event.set()
        if runtime.thread is not None:
            runtime.thread.join()
        self._concurrency_tokens.clear_database(database_id)
        self._local_drafts.clear_database(database_id)
        self._capabilities.set_collaboration_state(
            database_id, SynchronizationState.STOPPED
        )
        self._publish_state(database_id, SynchronizationState.STOPPED)

    def update_presence(
        self,
        database_id: str,
        bid_uid: Optional[str],
        page_uid: Optional[str],
        mode: PresenceMode = PresenceMode.VIEWING,
    ) -> None:
        runtime = self._runtime(database_id)
        if runtime is None:
            return
        with runtime.lock:
            runtime.bid_uid = int(bid_uid) if bid_uid else None
            runtime.page_uid = int(page_uid) if page_uid else None
            runtime.mode = mode

    def status(self, database_id: str) -> CollaborationStatus:
        return self._capabilities.collaboration_status(database_id)

    def metrics(self, database_id: str) -> CollaborationMetrics:
        runtime = self._runtime(database_id)
        if runtime is None:
            return CollaborationMetrics(database_id)
        with runtime.lock:
            return CollaborationMetrics(
                database_id=database_id,
                poll_count=runtime.poll_count,
                poll_duration_seconds=runtime.poll_duration_seconds,
                transaction_count=runtime.transaction_count,
                change_row_count=runtime.change_row_count,
                reconciliation_count=runtime.reconciliation_count,
                reconciliation_duration_seconds=(
                    runtime.reconciliation_duration_seconds
                ),
                retention_gap_count=runtime.retention_gap_count,
                reconnect_count=runtime.reconnect_count,
            )

    def enter_conflict(self, database_id: str, message: str) -> None:
        runtime = self._runtime(database_id)
        if runtime is None:
            return
        with runtime.lock:
            runtime.healthy = False
            runtime.pending_delivery = True
            runtime.recovery_requested = True
            runtime.recovery_ready = False
            runtime.command_event.set()
        self._capabilities.set_collaboration_state(
            database_id,
            SynchronizationState.CONFLICTED,
            message,
        )
        self._publish_state(database_id, SynchronizationState.CONFLICTED, message)

    def enter_resource_conflict(
        self, database_id: str, resource: ResourceRef, message: str = ""
    ) -> None:
        if self._runtime(database_id) is None:
            return
        self._capabilities.add_collaboration_conflict(database_id, resource)
        self.enter_conflict(
            database_id,
            message or "A pending remote transaction overlaps an active local draft.",
        )

    def request_local_edit(
        self,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        callback: Callable[[EditLeaseResult], None],
    ) -> None:
        normalized_resources = tuple(sorted(set(resources)))
        descriptor = self._registry.resolve(database_id)
        if not normalized_resources:
            self._dispatch_lease_result(
                callback,
                EditLeaseResult(
                    False,
                    "An edit lease requires at least one resource.",
                ),
            )
            return
        if descriptor is not None and descriptor.backend == DatabaseBackend.ACCESS:
            self._dispatch_lease_result(
                callback,
                EditLeaseResult(
                    True,
                ),
            )
            return
        runtime = self._runtime(database_id)
        if runtime is None:
            self._dispatch_lease_result(
                callback,
                EditLeaseResult(
                    False,
                    "SQL collaboration is not available for this database.",
                ),
            )
            return
        if not self._capabilities.is_editable(database_id):
            self._dispatch_lease_result(
                callback,
                EditLeaseResult(
                    False,
                    "SQL collaboration is not ready for editing.",
                ),
            )
            return
        first_resource = normalized_resources[0]
        try:
            draft = self._local_drafts.begin(
                draft_type=(
                    resource_definition(first_resource.resource_type).family.value
                    + "_editor"
                ),
                database_id=database_id,
                bid_uid=next(
                    (
                        resource.bid_uid
                        for resource in normalized_resources
                        if resource.bid_uid is not None
                    ),
                    None,
                ),
                page_uid=(
                    int(first_resource.resource_id)
                    if first_resource.resource_type == "page"
                    and first_resource.resource_id.isdecimal()
                    else None
                ),
                owning_surface="desktop",
                affected_resources=normalized_resources,
                base_tokens=self._concurrency_tokens.tokens_for_resources(
                    database_id, normalized_resources
                ),
            )
        except ValueError as exc:
            self._dispatch_lease_result(
                callback,
                EditLeaseResult(
                    False,
                    str(exc),
                ),
            )
            return
        request = _EditLeaseRequest(
            database_id=database_id,
            resources=normalized_resources,
            operation_description=draft.draft_type,
        )
        runtime.edit_requests.put((request, draft.draft_id, callback))
        runtime.command_event.set()

    def end_local_edit(self, database_id: str, resources: tuple) -> None:
        runtime = self._runtime(database_id)
        if runtime is None:
            return
        runtime.release_requests.put(tuple(sorted(set(resources))))
        runtime.command_event.set()

    def discard_local_draft(self, database_id: str, draft_id: str) -> None:
        draft = self._local_drafts.get(draft_id)
        if draft is None or draft.database_id != database_id:
            return
        self.end_local_edit(database_id, draft.affected_resources)

    def shutdown(self) -> None:
        with self._lock:
            self._shutting_down = True
            database_ids = tuple(self._runtimes)
        for database_id in database_ids:
            self.stop_database(database_id, "shutdown")
        self._event_bus.unsubscribe(AppEvents.FILE_OPENED, self._on_file_opened)
        self._event_bus.unsubscribe(AppEvents.FILE_UNLOADED, self._on_file_unloaded)
        self._event_bus.unsubscribe(
            AppEvents.DATABASE_REFRESHED, self._on_database_refreshed
        )
        self._event_bus.unsubscribe(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            self._on_database_capabilities_changed,
        )

    def _worker(self, runtime: _DatabaseRuntime) -> None:
        reconnect_attempt = 0
        next_heartbeat = 0.0
        previous_loop = time.monotonic()
        while not runtime.stop_event.is_set():
            try:
                loop_started = time.monotonic()
                with runtime.lock:
                    session_before_gap = runtime.session
                if (
                    session_before_gap is not None
                    and loop_started - previous_loop > COLLABORATION_STALE_SECONDS
                ):
                    self._handle_worker_failure(
                        runtime,
                        "The collaboration session expired while the computer was suspended.",
                    )
                    previous_loop = loop_started
                    continue
                previous_loop = loop_started
                with runtime.lock:
                    recovery_requested = runtime.recovery_requested
                    recovery_ready = runtime.recovery_ready
                if recovery_requested:
                    if runtime.session is not None:
                        self._reset_session(runtime)
                    if not recovery_ready:
                        runtime.command_event.wait(0.25)
                        runtime.command_event.clear()
                        continue
                    with runtime.lock:
                        runtime.recovery_requested = False
                        runtime.recovery_ready = False
                        runtime.pending_delivery = False
                        runtime.feed_epoch = ""
                if runtime.session is None:
                    session = self._store.start_session(
                        runtime.database_id,
                        str(uuid.uuid4()),
                        self._client_instance_id,
                        getpass.getuser(),
                        platform.node(),
                        APPLICATION_VERSION,
                    )
                    with runtime.lock:
                        runtime.session = session
                        runtime.acknowledged_version = session.last_acknowledged_version
                    self._concurrency_tokens.load_database(runtime.database_id)
                    hydrated = self._remote_reader.initial_reconciliation(
                        runtime.database_id,
                        runtime.bid_uid,
                        session.last_acknowledged_version,
                    )
                    self._dispatcher.dispatch(
                        self._on_session_started,
                        (
                            runtime.database_id,
                            runtime.generation,
                            hydrated,
                        ),
                    )
                    while not runtime.stop_event.is_set():
                        if runtime.ready_event.wait(timeout=0.25):
                            break
                    if runtime.stop_event.is_set():
                        break
                    next_heartbeat = time.monotonic()
                    reconnect_attempt = 0
                self._process_edit_requests(runtime)
                self._process_release_requests(runtime)
                now = time.monotonic()
                if now >= next_heartbeat:
                    self._heartbeat(runtime)
                    next_heartbeat = now + self._polling_policy.heartbeat_seconds
                self._poll_locks(runtime)
                self._poll(runtime)
                with runtime.lock:
                    caught_up = (
                        not runtime.pending_delivery
                        and runtime.acknowledged_version
                        >= runtime.observed_high_water_version
                    )
                    needs_restored_event = caught_up and not runtime.healthy
                    runtime.healthy = caught_up
                    active_session = runtime.session
                if needs_restored_event and active_session is not None:
                    if not self._capabilities.mark_connected(runtime.database_id):
                        with runtime.lock:
                            runtime.healthy = False
                        self._dispatcher.dispatch(
                            self._on_disconnected,
                            (
                                runtime.database_id,
                                runtime.generation,
                                SynchronizationState.READ_ONLY,
                                "SQL edit permissions or schema trust changed.",
                            ),
                        )
                        break
                    self._sessions.register(
                        runtime.database_id, active_session.session_id
                    )
                    self._dispatcher.dispatch(
                        self._on_connection_restored,
                        (
                            runtime.database_id,
                            runtime.generation,
                        ),
                    )
                runtime.command_event.wait(self._next_poll_interval(runtime))
                runtime.command_event.clear()
            except DatabaseCatalogError as exc:
                failure_state = (
                    SynchronizationState.CREDENTIAL_REQUIRED
                    if exc.credential_required
                    else (
                        SynchronizationState.READ_ONLY
                        if exc.read_only_required
                        else SynchronizationState.DISCONNECTED
                    )
                )
                self._handle_worker_failure(runtime, str(exc), failure_state)
                if not exc.retryable:
                    break
                delay = self._reconnect_delay(reconnect_attempt)
                with runtime.lock:
                    runtime.reconnect_count += 1
                reconnect_attempt = min(
                    reconnect_attempt + 1,
                    len(self._polling_policy.reconnect_backoff_seconds) - 1,
                )
                runtime.stop_event.wait(delay)
            except OSError as exc:
                self._handle_worker_failure(runtime, str(exc))
                delay = self._reconnect_delay(reconnect_attempt)
                with runtime.lock:
                    runtime.reconnect_count += 1
                reconnect_attempt = min(
                    reconnect_attempt + 1,
                    len(self._polling_policy.reconnect_backoff_seconds) - 1,
                )
                runtime.stop_event.wait(delay)
            except ValueError as exc:
                self._handle_worker_failure(runtime, str(exc))
                with runtime.lock:
                    runtime.recovery_requested = True
                    runtime.recovery_ready = False
                    runtime.pending_delivery = True
                self._dispatcher.dispatch(
                    self._on_reconciliation_required,
                    (runtime.database_id, runtime.generation, str(exc)),
                )
        self._reject_pending_edits(
            runtime, "SQL collaboration stopped before the edit lease was acquired."
        )
        self._reset_session(runtime, close_reason=runtime.close_reason)

    def _process_edit_requests(self, runtime: _DatabaseRuntime) -> None:
        while not runtime.stop_event.is_set():
            try:
                request, draft_id, callback = runtime.edit_requests.get_nowait()
            except queue.Empty:
                return
            with runtime.lock:
                session = runtime.session
                already_owned = any(
                    resource in runtime.owned_locks for resource in request.resources
                )
            editable = self._capabilities.is_editable(request.database_id)
            if session is None or already_owned or not editable:
                self._local_drafts.finish(draft_id)
                self._dispatch_lease_result(
                    callback,
                    EditLeaseResult(
                        False,
                        (
                            "One of the requested resources is already being edited."
                            if already_owned
                            else (
                                "The SQL collaboration session is not available."
                                if session is None
                                else "SQL collaboration is not ready for editing."
                            )
                        ),
                    ),
                )
                continue
            acquired = []
            try:
                self._concurrency_tokens.ensure_resources_loaded(
                    request.database_id, request.resources
                )
                self._local_drafts.set_base_tokens(
                    draft_id,
                    self._concurrency_tokens.tokens_for_resources(
                        request.database_id, request.resources
                    ),
                )
                for resource in request.resources:
                    acquired.append(
                        self._store.acquire_lock(
                            request.database_id,
                            session.session_id,
                            resource,
                            request.operation_description,
                        )
                    )
            except DatabaseCatalogError as exc:
                self._deny_edit_request(
                    request, draft_id, callback, session, acquired, str(exc)
                )
                if (
                    exc.retryable
                    or exc.session_expired
                    or exc.credential_required
                    or exc.read_only_required
                ):
                    raise
                continue
            except OSError as exc:
                self._deny_edit_request(
                    request, draft_id, callback, session, acquired, str(exc)
                )
                raise
            except ValueError as exc:
                self._deny_edit_request(
                    request, draft_id, callback, session, acquired, str(exc)
                )
                continue
            with runtime.lock:
                for lock in acquired:
                    runtime.owned_locks[lock.resource] = lock
                    self._sessions.register_lock(
                        request.database_id, lock.resource, lock.lock_token
                    )
                runtime.edit_depth += 1
                runtime.mode = PresenceMode.EDITING
                runtime.draft_ids[frozenset(request.resources)] = draft_id
            self._local_drafts.activate(
                draft_id, acquired[0] if len(acquired) == 1 else None
            )
            self._dispatch_runtime_lease_result(
                runtime,
                draft_id,
                callback,
                EditLeaseResult(
                    True,
                ),
            )

    def _deny_edit_request(
        self,
        request: _EditLeaseRequest,
        draft_id: str,
        callback: Callable[[EditLeaseResult], None],
        session: DatabaseSession,
        acquired: list[ResourceLock],
        message: str,
    ) -> None:
        for lock in acquired:
            try:
                self._store.release_lock(
                    request.database_id,
                    session.session_id,
                    lock.lock_token,
                )
            except (DatabaseCatalogError, OSError, ValueError):
                continue
        self._local_drafts.finish(draft_id)
        self._dispatch_lease_result(
            callback,
            EditLeaseResult(
                False,
                message,
            ),
        )

    def _reject_pending_edits(self, runtime: _DatabaseRuntime, message: str) -> None:
        while True:
            try:
                request, draft_id, callback = runtime.edit_requests.get_nowait()
            except queue.Empty:
                return
            self._local_drafts.finish(draft_id)
            self._dispatch_lease_result(
                callback,
                EditLeaseResult(
                    False,
                    message,
                ),
            )

    def _process_release_requests(self, runtime: _DatabaseRuntime) -> None:
        while not runtime.stop_event.is_set():
            try:
                resources = runtime.release_requests.get_nowait()
            except queue.Empty:
                return
            with runtime.lock:
                resource_key = frozenset(resources)
                draft_id = runtime.draft_ids.pop(resource_key, None)
                if draft_id is None:
                    continue
                session = runtime.session
                locks = tuple(
                    runtime.owned_locks.pop(resource)
                    for resource in resources
                    if resource in runtime.owned_locks
                )
                for resource in resources:
                    self._sessions.remove_lock(runtime.database_id, resource)
                runtime.edit_depth = max(0, runtime.edit_depth - 1)
                if runtime.edit_depth == 0:
                    runtime.mode = PresenceMode.VIEWING
            self._local_drafts.finish(draft_id)
            if session is None:
                continue
            for lock in locks:
                self._store.release_lock(
                    runtime.database_id,
                    session.session_id,
                    lock.lock_token,
                )

    def _dispatch_lease_result(
        self,
        callback: Callable[[EditLeaseResult], None],
        result: EditLeaseResult,
    ) -> None:
        self._dispatcher.dispatch(self._complete_lease_request, (callback, result))

    def _dispatch_runtime_lease_result(
        self,
        runtime: _DatabaseRuntime,
        draft_id: str,
        callback: Callable[[EditLeaseResult], None],
        result: EditLeaseResult,
    ) -> None:
        self._dispatcher.dispatch(
            self._complete_runtime_lease_request,
            (
                runtime.database_id,
                runtime.generation,
                draft_id,
                callback,
                result,
            ),
        )

    @staticmethod
    def _complete_lease_request(payload) -> None:
        callback, result = payload
        callback(result)

    def _complete_runtime_lease_request(self, payload) -> None:
        database_id, generation, draft_id, callback, result = payload
        runtime = self._runtime(database_id, generation)
        active = False
        if runtime is not None:
            with runtime.lock:
                active = draft_id in runtime.draft_ids.values()
        if result.granted and not active:
            result = EditLeaseResult(
                False,
                "SQL collaboration stopped before the edit lease became active.",
            )
        callback(result)

    def _heartbeat(self, runtime: _DatabaseRuntime) -> None:
        with runtime.lock:
            session = runtime.session
            acknowledged = runtime.acknowledged_version
            bid_uid = runtime.bid_uid
            page_uid = runtime.page_uid
            mode = runtime.mode
            owned_locks = tuple(runtime.owned_locks.values())
            healthy = runtime.healthy
        if session is None:
            return
        if healthy and not self._capabilities.mark_connected(runtime.database_id):
            raise DatabaseCatalogError(
                "SQL edit permissions changed. Reconnect before editing.",
                read_only_required=True,
            )
        updated = self._store.heartbeat(
            runtime.database_id,
            session.session_id,
            acknowledged,
            bid_uid,
            page_uid,
            mode,
        )
        with runtime.lock:
            runtime.session = updated
        renewed_locks = []
        for owned_lock in owned_locks:
            renewed_locks.append(
                self._store.renew_lock(
                    runtime.database_id,
                    updated.session_id,
                    owned_lock.lock_token,
                )
            )
        if renewed_locks:
            with runtime.lock:
                for renewed in renewed_locks:
                    runtime.owned_locks[renewed.resource] = renewed
                    self._sessions.register_lock(
                        runtime.database_id,
                        renewed.resource,
                        renewed.lock_token,
                    )
        if bid_uid is not None:
            users = self._store.list_presence(
                runtime.database_id, bid_uid, updated.session_id
            )
            self._dispatcher.dispatch(
                self._publish_presence,
                (runtime.database_id, runtime.generation, str(bid_uid), users),
            )

    def _poll_locks(self, runtime: _DatabaseRuntime) -> None:
        with runtime.lock:
            session = runtime.session
            bid_uid = runtime.bid_uid
        if session is None:
            return
        external_locks = self._store.list_locks(
            runtime.database_id,
            session.session_id,
            bid_uid,
        )
        self._dispatcher.dispatch(
            self._publish_capability_change,
            (
                runtime.database_id,
                runtime.generation,
                frozenset(lock.resource for lock in external_locks),
            ),
        )

    def _poll(self, runtime: _DatabaseRuntime) -> None:
        started = time.perf_counter()
        try:
            self._poll_once(runtime)
        finally:
            with runtime.lock:
                runtime.poll_count += 1
                runtime.poll_duration_seconds += time.perf_counter() - started

    def _poll_once(self, runtime: _DatabaseRuntime) -> None:
        with runtime.lock:
            if runtime.pending_delivery or runtime.session is None:
                return
            acknowledged = runtime.acknowledged_version
            session_id = runtime.session.session_id
        batch = self._store.poll_changes(
            runtime.database_id,
            acknowledged,
            self._polling_policy.maximum_batch_size,
        )
        with runtime.lock:
            runtime.transaction_count += len(
                {change.transaction_id for change in batch.changes}
            )
            runtime.change_row_count += len(batch.changes)
        with runtime.lock:
            runtime.observed_high_water_version = batch.high_water_version
            previous_epoch = runtime.feed_epoch
            if not previous_epoch:
                runtime.feed_epoch = batch.feed_epoch
        if previous_epoch and previous_epoch != batch.feed_epoch:
            with runtime.lock:
                runtime.pending_delivery = True
            self._dispatcher.dispatch(
                self._on_reconciliation_required,
                (
                    runtime.database_id,
                    runtime.generation,
                    "The SQL change feed was reset.",
                ),
            )
            return
        if acknowledged and (
            acknowledged < batch.minimum_valid_version
            or acknowledged > batch.high_water_version
        ):
            with runtime.lock:
                runtime.pending_delivery = True
                runtime.retention_gap_count += 1
            self._dispatcher.dispatch(
                self._on_reconciliation_required,
                (
                    runtime.database_id,
                    runtime.generation,
                    "The SQL Change Tracking checkpoint is no longer valid.",
                ),
            )
            return
        remote_changes = tuple(
            change for change in batch.changes if change.source_session_id != session_id
        )
        if not batch.changes:
            with runtime.lock:
                runtime.acknowledged_version = batch.delivered_through_version
            return
        if not remote_changes:
            with runtime.lock:
                runtime.acknowledged_version = batch.delivered_through_version
            return
        remote_batch = type(batch)(
            database_id=batch.database_id,
            feed_epoch=batch.feed_epoch,
            minimum_valid_version=batch.minimum_valid_version,
            high_water_version=batch.high_water_version,
            delivered_through_version=batch.delivered_through_version,
            changes=remote_changes,
        )
        hydrated = self._remote_reader.hydrate(remote_batch)
        with runtime.lock:
            runtime.pending_delivery = True
        self._dispatcher.dispatch(
            self._on_remote_batch,
            (runtime.database_id, runtime.generation, hydrated),
        )

    def _next_poll_interval(self, runtime: _DatabaseRuntime) -> float:
        with runtime.lock:
            if runtime.edit_depth:
                base = self._polling_policy.active_edit_seconds
            elif runtime.bid_uid is not None:
                base = self._polling_policy.selected_database_seconds
            else:
                base = self._polling_policy.inactive_database_seconds
        jitter = base * self._polling_policy.jitter_ratio
        return max(0.05, base + random.uniform(-jitter, jitter))

    def _reconnect_delay(self, attempt: int) -> float:
        base = self._polling_policy.reconnect_backoff_seconds[attempt]
        jitter = base * self._polling_policy.jitter_ratio
        return max(0.05, base + random.uniform(-jitter, jitter))

    def _on_session_started(self, payload) -> None:
        database_id, generation, hydrated = payload
        runtime = self._runtime(database_id, generation)
        if runtime is None:
            return
        if not self._apply_reconciliation(hydrated):
            self._on_reconciliation_required(
                (
                    database_id,
                    generation,
                    "The SQL database could not be reconciled at session start.",
                )
            )
            runtime.ready_event.set()
            return
        with runtime.lock:
            runtime.healthy = False
        self._capabilities.set_collaboration_state(
            database_id,
            SynchronizationState.CATCHING_UP,
        )
        self._publish_state(database_id, SynchronizationState.CATCHING_UP)
        runtime.ready_event.set()

    def _on_connection_restored(self, payload) -> None:
        database_id, generation = payload
        if self._runtime(database_id, generation) is None:
            return
        self._capabilities.set_collaboration_state(
            database_id,
            SynchronizationState.HEALTHY,
        )
        self._publish_state(database_id, SynchronizationState.HEALTHY)

    def _on_remote_batch(self, payload) -> None:
        database_id, generation, hydrated = payload
        runtime = self._runtime(database_id, generation)
        if runtime is None:
            return
        started = time.perf_counter()
        applied = self._apply_reconciliation(hydrated)
        elapsed = time.perf_counter() - started
        with runtime.lock:
            runtime.reconciliation_count += 1
            runtime.reconciliation_duration_seconds += elapsed
            conflicted = (
                self._capabilities.collaboration_status(database_id).state
                == SynchronizationState.CONFLICTED
            )
            if applied and not conflicted:
                runtime.acknowledged_version = hydrated.batch.delivered_through_version
            runtime.pending_delivery = conflicted
        if conflicted:
            return
        if not applied:
            self._on_reconciliation_required(
                (
                    database_id,
                    generation,
                    "A remote SQL change requires a controlled database refresh.",
                )
            )

    def _apply_reconciliation(self, hydrated) -> bool:
        try:
            return self._reconciliation.apply(hydrated)
        except Exception:
            logger.exception("SQL main-thread reconciliation failed")
            return False

    def _on_reconciliation_required(self, payload) -> None:
        database_id, generation, reason = payload
        runtime = self._runtime(database_id, generation)
        if runtime is None:
            return
        self._set_state(
            database_id,
            SynchronizationState.RECONCILIATION_REQUIRED,
            reason,
        )
        with runtime.lock:
            runtime.healthy = False
            runtime.pending_delivery = True
            runtime.recovery_requested = True
            runtime.recovery_ready = False
            runtime.command_event.set()
        self._event_bus.publish(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            database_id=database_id,
            reason=reason,
        )

    def _handle_worker_failure(
        self,
        runtime: _DatabaseRuntime,
        message: str,
        state: SynchronizationState = SynchronizationState.DISCONNECTED,
    ) -> None:
        self._reset_session(runtime)
        runtime.ready_event.clear()
        self._dispatcher.dispatch(
            self._on_disconnected,
            (runtime.database_id, runtime.generation, state, message),
        )

    def _reset_session(
        self,
        runtime: _DatabaseRuntime,
        *,
        close_reason: str = "trust-lost",
    ) -> None:
        session, locks = self._clear_runtime_edits(runtime)
        if session is not None:
            for lock in locks:
                try:
                    self._store.release_lock(
                        runtime.database_id,
                        session.session_id,
                        lock.lock_token,
                    )
                except (DatabaseCatalogError, OSError, ValueError):
                    continue
            self._sessions.remove(runtime.database_id, session.session_id)
            try:
                self._store.close_session(
                    runtime.database_id,
                    session.session_id,
                    close_reason,
                )
            except (DatabaseCatalogError, OSError, ValueError):
                pass
        runtime.ready_event.clear()

    def _clear_runtime_edits(
        self, runtime: _DatabaseRuntime
    ) -> tuple[Optional[DatabaseSession], tuple[ResourceLock, ...]]:
        with runtime.lock:
            session = runtime.session
            locks = tuple(runtime.owned_locks.values())
            resources = tuple(runtime.owned_locks)
            had_drafts = bool(runtime.draft_ids)
            runtime.session = None
            runtime.owned_locks.clear()
            runtime.draft_ids.clear()
            runtime.edit_depth = 0
            runtime.mode = PresenceMode.VIEWING
            runtime.healthy = False
        self._local_drafts.clear_database(runtime.database_id)
        if had_drafts:
            self._dispatcher.dispatch(
                self._publish_lease_loss,
                runtime.database_id,
            )
        for resource in resources:
            self._sessions.remove_lock(runtime.database_id, resource)
        return session, locks

    def _publish_lease_loss(self, database_id) -> None:
        self._event_bus.publish(
            AppEvents.EDIT_LEASE_LOST,
            database_id=database_id,
        )

    def _on_disconnected(self, payload) -> None:
        database_id, generation, state, message = payload
        if self._runtime(database_id, generation) is None:
            return
        self._capabilities.set_collaboration_state(database_id, state)
        self._publish_state(database_id, state, message)

    def _publish_presence(self, payload) -> None:
        database_id, generation, bid_uid, users = payload
        if self._runtime(database_id, generation) is None:
            return
        self._event_bus.publish(
            AppEvents.PRESENCE_CHANGED,
            database_id=database_id,
            bid_uid=bid_uid,
            users=list(users),
        )

    def _publish_capability_change(self, payload) -> None:
        database_id, generation, locked_resources = payload
        if self._runtime(database_id, generation) is None:
            return
        current_status = self._capabilities.collaboration_status(database_id)
        if current_status.locked_resources == locked_resources:
            return
        self._capabilities.update_collaboration_resources(
            database_id,
            locked_resources,
            current_status.conflicted_resources,
        )
        self._event_bus.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            file_path=database_id,
        )

    def _set_state(
        self, database_id: str, state: SynchronizationState, message: str = ""
    ) -> None:
        self._capabilities.set_collaboration_state(database_id, state)
        self._publish_state(database_id, state, message)

    def _publish_state(
        self, database_id: str, state: SynchronizationState, message: str = ""
    ) -> None:
        self._event_bus.publish(
            AppEvents.COLLABORATION_STATE_CHANGED,
            database_id=database_id,
            state=state.value,
            message=message,
        )
        self._event_bus.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            file_path=database_id,
        )

    def _runtime(
        self, database_id: str, generation: Optional[int] = None
    ) -> Optional[_DatabaseRuntime]:
        with self._lock:
            runtime = self._runtimes.get(database_id)
        if runtime is None or (
            generation is not None and runtime.generation != generation
        ):
            return None
        return runtime
