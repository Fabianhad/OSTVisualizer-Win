from __future__ import annotations
import getpass
import platform
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from ...domain.entities.database_descriptor import DatabaseBackend
from ..dtos.application_info import APPLICATION_VERSION
from ..dtos.collaboration_dtos import (
    CollaborationStatus,
    DatabaseSession,
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
from .remote_change_reconciliation_service import RemoteChangeReconciliationService

_POLL_INTERVAL_SECONDS = 2.0
_HEARTBEAT_INTERVAL_SECONDS = 10.0
_RECONNECT_BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)


@dataclass
class _DatabaseRuntime:
    database_id: str
    generation: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    ready_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    session: Optional[DatabaseSession] = None
    acknowledged_sequence: int = 0
    observed_high_water: int = 0
    reconciliation_high_water: int = 0
    feed_epoch: str = ""
    pending_feed_epoch: str = ""
    healthy: bool = False
    edit_depth: int = 0
    owned_locks: dict[ResourceRef, ResourceLock] = field(default_factory=dict)
    pending_delivery: bool = False
    bid_uid: Optional[int] = None
    page_uid: Optional[int] = None
    mode: PresenceMode = PresenceMode.VIEWING
    close_reason: str = "closed"
    thread: Optional[threading.Thread] = None


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
        event_bus,
        supported_schema_version: int,
    ) -> None:
        self._registry = descriptor_registry
        self._store = store
        self._remote_reader = remote_reader
        self._dispatcher = dispatcher
        self._reconciliation = reconciliation
        self._capabilities = capability_service
        self._sessions = session_registry
        self._concurrency_tokens = concurrency_tokens
        self._event_bus = event_bus
        self._supported_schema_version = supported_schema_version
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
        state = self._capabilities.collaboration_status(file_path).state
        if state not in {
            SynchronizationState.CONFLICTED,
            SynchronizationState.RECONCILIATION_REQUIRED,
        }:
            if had_resource_conflicts:
                self._event_bus.publish(
                    AppEvents.DATABASE_CAPABILITIES_CHANGED,
                    file_path=file_path,
                )
            return
        with runtime.lock:
            session = runtime.session
            if runtime.reconciliation_high_water:
                runtime.acknowledged_sequence = max(
                    runtime.acknowledged_sequence,
                    runtime.reconciliation_high_water,
                )
                runtime.reconciliation_high_water = 0
            if runtime.pending_feed_epoch:
                runtime.feed_epoch = runtime.pending_feed_epoch
                runtime.pending_feed_epoch = ""
            runtime.pending_delivery = False
            runtime.healthy = session is not None
        if session is None:
            return
        self._sessions.register(file_path, session.session_id)
        self._capabilities.set_collaboration_state(
            file_path, SynchronizationState.HEALTHY
        )
        self._publish_state(file_path, SynchronizationState.HEALTHY)

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
        if runtime.thread is not None:
            runtime.thread.join()
        session = runtime.session
        if session is not None:
            self._sessions.remove(database_id, session.session_id)
        self._concurrency_tokens.clear_database(database_id)
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

    def enter_conflict(self, database_id: str, message: str) -> None:
        runtime = self._runtime(database_id)
        if runtime is None:
            return
        with runtime.lock:
            runtime.healthy = False
            runtime.pending_delivery = True
            session = runtime.session
        self._release_runtime_edits(runtime)
        if session is not None:
            self._sessions.remove(database_id, session.session_id)
        self._capabilities.set_collaboration_state(
            database_id,
            SynchronizationState.CONFLICTED,
            message,
        )
        self._publish_state(database_id, SynchronizationState.CONFLICTED, message)

    def enter_resource_conflict(self, database_id: str, resource: ResourceRef) -> None:
        if self._runtime(database_id) is None:
            return
        self._capabilities.add_collaboration_conflict(database_id, resource)
        self._event_bus.publish(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            file_path=database_id,
        )

    def begin_local_edit(self, database_id: str, resources: tuple) -> bool:
        runtime = self._runtime(database_id)
        if runtime is None:
            descriptor = self._registry.resolve(database_id)
            return bool(
                descriptor is not None and descriptor.backend == DatabaseBackend.ACCESS
            )
        with runtime.lock:
            session = runtime.session
            already_owned = any(
                resource in runtime.owned_locks for resource in resources
            )
        if already_owned:
            return False
        if session is None:
            return False
        self._concurrency_tokens.begin_edit(database_id, resources)
        acquired = []
        try:
            for resource in sorted(resources):
                lock = self._store.acquire_lock(
                    database_id,
                    session.session_id,
                    resource,
                    "editing",
                )
                acquired.append(lock)
        except (DatabaseCatalogError, OSError, ValueError) as exc:
            for lock in acquired:
                try:
                    self._store.release_lock(
                        database_id, session.session_id, lock.lock_token
                    )
                except (DatabaseCatalogError, OSError, ValueError):
                    pass
            self._concurrency_tokens.end_edit(database_id, resources)
            blocked_resource = resources[0] if resources else None
            self._event_bus.publish(
                AppEvents.SYNCHRONIZATION_CONFLICT,
                database_id=database_id,
                resource_type=(
                    blocked_resource.resource_type if blocked_resource else "database"
                ),
                resource_id=(
                    blocked_resource.resource_id if blocked_resource else database_id
                ),
                bid_uid=str(blocked_resource.bid_uid or "") if blocked_resource else "",
                message=str(exc),
                blocks_database=False,
            )
            return False
        with runtime.lock:
            for lock in acquired:
                runtime.owned_locks[lock.resource] = lock
                self._sessions.register_lock(
                    database_id, lock.resource, lock.lock_token
                )
            runtime.edit_depth += 1
            runtime.mode = PresenceMode.EDITING
        return True

    def end_local_edit(self, database_id: str, resources: tuple) -> None:
        self._concurrency_tokens.end_edit(database_id, resources)
        runtime = self._runtime(database_id)
        if runtime is not None:
            with runtime.lock:
                session = runtime.session
                locks = [
                    runtime.owned_locks.pop(resource)
                    for resource in resources
                    if resource in runtime.owned_locks
                ]
                for resource in resources:
                    self._sessions.remove_lock(database_id, resource)
                runtime.edit_depth = max(0, runtime.edit_depth - 1)
                if runtime.edit_depth == 0:
                    runtime.mode = PresenceMode.VIEWING
            if session is not None:
                for lock in locks:
                    try:
                        self._store.release_lock(
                            database_id,
                            session.session_id,
                            lock.lock_token,
                        )
                    except (DatabaseCatalogError, OSError, ValueError):
                        self.enter_conflict(
                            database_id,
                            "An SQL edit lock could not be released cleanly.",
                        )
                        break

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
        while not runtime.stop_event.is_set():
            try:
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
                        runtime.acknowledged_sequence = (
                            session.last_acknowledged_sequence
                        )
                    self._concurrency_tokens.load_database(runtime.database_id)
                    hydrated = self._remote_reader.initial_reconciliation(
                        runtime.database_id,
                        runtime.bid_uid,
                        session.last_acknowledged_sequence,
                    )
                    self._dispatcher.dispatch(
                        self._on_session_started,
                        (
                            runtime.database_id,
                            runtime.generation,
                            session,
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
                now = time.monotonic()
                if now >= next_heartbeat:
                    self._heartbeat(runtime)
                    next_heartbeat = now + _HEARTBEAT_INTERVAL_SECONDS
                self._poll_locks(runtime)
                self._poll(runtime)
                with runtime.lock:
                    caught_up = (
                        not runtime.pending_delivery
                        and runtime.acknowledged_sequence >= runtime.observed_high_water
                    )
                    needs_restored_event = caught_up and not runtime.healthy
                    runtime.healthy = caught_up
                    active_session = runtime.session
                if needs_restored_event and active_session is not None:
                    self._sessions.register(
                        runtime.database_id, active_session.session_id
                    )
                    self._dispatcher.dispatch(
                        self._on_connection_restored,
                        (
                            runtime.database_id,
                            runtime.generation,
                            active_session.session_id,
                        ),
                    )
                runtime.stop_event.wait(_POLL_INTERVAL_SECONDS)
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
                if exc.session_expired:
                    expired_session, abandoned_resources = self._abandon_session(
                        runtime
                    )
                    if expired_session is not None:
                        self._sessions.remove(
                            runtime.database_id,
                            expired_session.session_id,
                        )
                    self._concurrency_tokens.end_edit(
                        runtime.database_id, abandoned_resources
                    )
                    runtime.ready_event.clear()
                elif not exc.retryable:
                    break
                delay = _RECONNECT_BACKOFF_SECONDS[reconnect_attempt]
                reconnect_attempt = min(
                    reconnect_attempt + 1, len(_RECONNECT_BACKOFF_SECONDS) - 1
                )
                runtime.stop_event.wait(delay)
            except OSError as exc:
                self._handle_worker_failure(runtime, str(exc))
                delay = _RECONNECT_BACKOFF_SECONDS[reconnect_attempt]
                reconnect_attempt = min(
                    reconnect_attempt + 1, len(_RECONNECT_BACKOFF_SECONDS) - 1
                )
                runtime.stop_event.wait(delay)
            except ValueError as exc:
                self._handle_worker_failure(runtime, str(exc))
                self._dispatcher.dispatch(
                    self._on_feed_invalid,
                    (runtime.database_id, runtime.generation, str(exc)),
                )
                break
        session = runtime.session
        if session is not None:
            try:
                self._store.close_session(
                    runtime.database_id,
                    session.session_id,
                    runtime.close_reason,
                )
            except (DatabaseCatalogError, OSError, ValueError):
                pass
            self._sessions.remove(runtime.database_id, session.session_id)
            with runtime.lock:
                runtime.session = None

    def _heartbeat(self, runtime: _DatabaseRuntime) -> None:
        with runtime.lock:
            session = runtime.session
            acknowledged = runtime.acknowledged_sequence
            bid_uid = runtime.bid_uid
            page_uid = runtime.page_uid
            mode = runtime.mode
            owned_locks = tuple(runtime.owned_locks.values())
        if session is None:
            return
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

    @staticmethod
    def _abandon_session(
        runtime: _DatabaseRuntime,
    ) -> tuple[Optional[DatabaseSession], tuple[ResourceRef, ...]]:
        with runtime.lock:
            session = runtime.session
            resources = tuple(runtime.owned_locks)
            runtime.session = None
            runtime.owned_locks.clear()
            runtime.edit_depth = 0
            runtime.mode = PresenceMode.VIEWING
            runtime.healthy = False
        return session, resources

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
        with runtime.lock:
            if runtime.pending_delivery or runtime.session is None:
                return
            acknowledged = runtime.acknowledged_sequence
            session_id = runtime.session.session_id
        batch = self._store.poll_changes(runtime.database_id, acknowledged, 500)
        with runtime.lock:
            runtime.observed_high_water = batch.high_water_sequence
            previous_epoch = runtime.feed_epoch
            if not previous_epoch:
                runtime.feed_epoch = batch.feed_epoch
        if previous_epoch and previous_epoch != batch.feed_epoch:
            with runtime.lock:
                runtime.pending_delivery = True
                runtime.pending_feed_epoch = batch.feed_epoch
            self._dispatcher.dispatch(
                self._on_reconciliation_required,
                (
                    runtime.database_id,
                    runtime.generation,
                    batch.high_water_sequence,
                    "The SQL change feed was reset.",
                ),
            )
            return
        if (
            batch.oldest_available_sequence
            and acknowledged < batch.oldest_available_sequence - 1
        ):
            with runtime.lock:
                runtime.pending_delivery = True
            self._dispatcher.dispatch(
                self._on_reconciliation_required,
                (
                    runtime.database_id,
                    runtime.generation,
                    batch.high_water_sequence,
                    "The SQL change history no longer contains this checkpoint.",
                ),
            )
            return
        remote_changes = tuple(
            change for change in batch.changes if change.source_session_id != session_id
        )
        if not batch.changes:
            return
        if not remote_changes:
            with runtime.lock:
                runtime.acknowledged_sequence = batch.changes[-1].sequence
            return
        remote_batch = type(batch)(
            database_id=batch.database_id,
            feed_epoch=batch.feed_epoch,
            oldest_available_sequence=batch.oldest_available_sequence,
            high_water_sequence=batch.high_water_sequence,
            changes=remote_changes,
        )
        hydrated = self._remote_reader.hydrate(remote_batch)
        with runtime.lock:
            runtime.pending_delivery = True
        self._dispatcher.dispatch(
            self._on_remote_batch,
            (runtime.database_id, runtime.generation, hydrated),
        )

    def _on_session_started(self, payload) -> None:
        database_id, generation, session, hydrated = payload
        runtime = self._runtime(database_id, generation)
        if runtime is None:
            return
        if not self._reconciliation.apply(hydrated):
            self._on_reconciliation_required(
                (
                    database_id,
                    generation,
                    session.last_acknowledged_sequence,
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
        database_id, generation, session_id = payload
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
        applied = self._reconciliation.apply(hydrated)
        with runtime.lock:
            conflicted = (
                self._capabilities.collaboration_status(database_id).state
                == SynchronizationState.CONFLICTED
            )
            if applied and not conflicted and hydrated.batch.changes:
                runtime.acknowledged_sequence = hydrated.batch.changes[-1].sequence
            runtime.pending_delivery = conflicted
        if conflicted:
            return
        if not applied:
            self._on_reconciliation_required(
                (
                    database_id,
                    generation,
                    hydrated.batch.high_water_sequence,
                    "A remote SQL change requires a controlled database refresh.",
                )
            )

    def _on_reconciliation_required(self, payload) -> None:
        database_id, generation, high_water, reason = payload
        runtime = self._runtime(database_id, generation)
        if runtime is None:
            return
        self._capabilities.set_collaboration_state(
            database_id, SynchronizationState.RECONCILIATION_REQUIRED
        )
        with runtime.lock:
            runtime.healthy = False
            runtime.reconciliation_high_water = max(
                runtime.reconciliation_high_water, high_water
            )
            runtime.pending_delivery = True
            session = runtime.session
        self._release_runtime_edits(runtime)
        if session is not None:
            self._sessions.remove(database_id, session.session_id)
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
        with runtime.lock:
            runtime.healthy = False
            session = runtime.session
        self._clear_runtime_edits(runtime)
        if session is not None:
            self._sessions.remove(runtime.database_id, session.session_id)
        self._dispatcher.dispatch(
            self._on_disconnected,
            (runtime.database_id, runtime.generation, state, message),
        )

    def _release_runtime_edits(self, runtime: _DatabaseRuntime) -> None:
        session, locks = self._clear_runtime_edits(runtime)
        if session is None:
            return
        for lock in locks:
            try:
                self._store.release_lock(
                    runtime.database_id,
                    session.session_id,
                    lock.lock_token,
                )
            except (DatabaseCatalogError, OSError, ValueError):
                continue

    def _clear_runtime_edits(
        self, runtime: _DatabaseRuntime
    ) -> tuple[Optional[DatabaseSession], tuple[ResourceLock, ...]]:
        with runtime.lock:
            session = runtime.session
            locks = tuple(runtime.owned_locks.values())
            resources = tuple(runtime.owned_locks)
            runtime.owned_locks.clear()
            runtime.edit_depth = 0
            runtime.mode = PresenceMode.VIEWING
        self._concurrency_tokens.end_edit(runtime.database_id, resources)
        for resource in resources:
            self._sessions.remove_lock(runtime.database_id, resource)
        return session, locks

    def _on_feed_invalid(self, payload) -> None:
        database_id, generation, message = payload
        if self._runtime(database_id, generation) is None:
            return
        self._capabilities.set_collaboration_state(
            database_id,
            SynchronizationState.RECONCILIATION_REQUIRED,
            message=message,
        )
        self._publish_state(
            database_id,
            SynchronizationState.RECONCILIATION_REQUIRED,
            message,
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
