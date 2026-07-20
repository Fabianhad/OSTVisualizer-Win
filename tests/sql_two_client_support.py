from __future__ import annotations
import multiprocessing
import os
import queue
import uuid
from dataclasses import dataclass
from enum import Enum
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue
from typing import Optional

_MAX_TEXT_LENGTH = 512


class ClientScenario(str, Enum):
    FOUNDATION_PROBE = "foundation_probe"
    FAIL = "fail"
    FAIL_BEFORE_BARRIER = "fail_before_barrier"


@dataclass(frozen=True)
class ClientProcessConfiguration:
    client_id: str
    scenario: ClientScenario

    def validate(self) -> None:
        _bounded_text(self.client_id, "client_id")


@dataclass(frozen=True)
class ClientProcessResult:
    client_id: str
    process_id: int
    stack_identity: str
    cleanup_errors: tuple[str, ...] = ()
    remaining_resources: tuple[str, ...] = ()
    error: str = ""

    def validate(self) -> None:
        _bounded_text(self.client_id, "client_id")
        _bounded_text(self.stack_identity, "stack_identity")
        _bounded_text(self.error, "error")
        if self.process_id < 0:
            raise ValueError("process_id cannot be negative")
        self._validate_values(self.cleanup_errors, "cleanup_errors")
        self._validate_values(self.remaining_resources, "remaining_resources")

    @staticmethod
    def _validate_values(values: tuple[str, ...], name: str) -> None:
        if len(values) > 64:
            raise ValueError(f"{name} exceeds its bounded result size")
        for value in values:
            _bounded_text(value, name)

    def to_payload(self) -> dict[str, object]:
        self.validate()
        return {
            "client_id": self.client_id,
            "process_id": self.process_id,
            "stack_identity": self.stack_identity,
            "cleanup_errors": self.cleanup_errors,
            "remaining_resources": self.remaining_resources,
            "error": self.error,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "ClientProcessResult":
        known_fields = {
            "client_id",
            "process_id",
            "stack_identity",
            "cleanup_errors",
            "remaining_resources",
            "error",
        }
        if set(payload) != known_fields:
            raise ValueError("Client result payload has unexpected fields")
        result = cls(**payload)
        result.validate()
        return result


@dataclass(frozen=True)
class TwoClientRunResult:
    clients: tuple[ClientProcessResult, ClientProcessResult]

    def assert_clean(self) -> None:
        for client in self.clients:
            if client.error:
                raise RuntimeError(
                    f"SQL client {client.client_id} failed: {client.error}"
                )
            if client.cleanup_errors or client.remaining_resources:
                raise RuntimeError(
                    f"SQL client {client.client_id} did not clean up completely"
                )


class TwoClientProcessHarness:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("timeout_seconds must be between 0 and 120")
        self._timeout_seconds = timeout_seconds
        self._context = multiprocessing.get_context("spawn")

    @property
    def start_method(self) -> str:
        return self._context.get_start_method()

    def run(
        self,
        first: ClientProcessConfiguration,
        second: ClientProcessConfiguration,
    ) -> TwoClientRunResult:
        first.validate()
        second.validate()
        if first.client_id == second.client_id:
            raise ValueError("Two-client runs require distinct client identities")
        barrier = self._context.Barrier(2, timeout=self._timeout_seconds)
        result_queue = self._context.Queue(maxsize=2)
        processes = (
            self._process(first, barrier, result_queue),
            self._process(second, barrier, result_queue),
        )
        started_processes: list[BaseProcess] = []
        results: list[ClientProcessResult] = []
        try:
            for process in processes:
                process.start()
                started_processes.append(process)
            for _ in processes:
                payload = result_queue.get(timeout=self._timeout_seconds)
                results.append(ClientProcessResult.from_payload(payload))
        except queue.Empty as exc:
            raise RuntimeError("Timed out waiting for a spawned SQL client") from exc
        finally:
            try:
                if len(started_processes) == len(processes):
                    self._join(processes)
                else:
                    self._terminate(tuple(started_processes))
            finally:
                result_queue.close()
                result_queue.join_thread()
        by_client = {result.client_id: result for result in results}
        if set(by_client) != {first.client_id, second.client_id}:
            raise RuntimeError("Spawned SQL clients returned invalid identities")
        ordered = (by_client[first.client_id], by_client[second.client_id])
        return TwoClientRunResult(ordered)

    def _process(
        self,
        configuration: ClientProcessConfiguration,
        barrier,
        result_queue: Queue,
    ) -> BaseProcess:
        return self._context.Process(
            target=_client_process_entry,
            args=(configuration, barrier, result_queue),
            name=f"OSTV-SQL-{configuration.client_id}",
        )

    def _join(self, processes: tuple[BaseProcess, ...]) -> None:
        for process in processes:
            process.join(self._timeout_seconds)
        alive = tuple(process for process in processes if process.is_alive())
        if alive:
            self._terminate(alive)
            raise RuntimeError("A spawned SQL client did not exit within the timeout")

    def _terminate(self, processes: tuple[BaseProcess, ...]) -> None:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(self._timeout_seconds)


def _client_process_entry(
    configuration: ClientProcessConfiguration,
    barrier,
    result_queue: Queue,
) -> None:
    stack_identity = str(uuid.uuid4())
    try:
        if configuration.scenario == ClientScenario.FAIL_BEFORE_BARRIER:
            barrier.abort()
            raise RuntimeError("deliberate pre-barrier failure")
        barrier.wait()
        if configuration.scenario == ClientScenario.FAIL:
            raise RuntimeError("deliberate child failure")
        if configuration.scenario == ClientScenario.FOUNDATION_PROBE:
            _construct_independent_application_stack()
        result = ClientProcessResult(
            client_id=configuration.client_id,
            process_id=os.getpid(),
            stack_identity=stack_identity,
        )
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        result = ClientProcessResult(
            client_id=configuration.client_id,
            process_id=os.getpid(),
            stack_identity=stack_identity,
            error=message[:_MAX_TEXT_LENGTH],
        )
    result_queue.put(result.to_payload())


class _InMemoryCredentialAdapter:
    def __init__(self) -> None:
        self._passwords: dict[str, str] = {}

    def read_password(self, target: str) -> Optional[str]:
        return self._passwords.get(target)

    def write_password(self, target: str, _username: str, password: str) -> None:
        self._passwords[target] = password

    def delete_password(self, target: str) -> None:
        self._passwords.pop(target, None)


class _FoundationRepository:
    active_file_path = None


def _construct_independent_application_stack() -> None:
    from PySide6.QtCore import QCoreApplication
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
    from ost_visualizer.application.services.local_draft_registry import (
        LocalDraftRegistry,
    )
    from ost_visualizer.application.services.remote_change_reconciliation_service import (
        RemoteChangeReconciliationService,
    )
    from ost_visualizer.application.services.sql_collaboration_coordinator import (
        SqlCollaborationCoordinator,
    )
    from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
    from ost_visualizer.domain.entities.database_descriptor import (
        DatabaseDescriptor,
        SqlServerDatabaseLocation,
    )
    from ost_visualizer.domain.services.file_manager_service import FileManager
    from ost_visualizer.domain.services.project_data_service import ProjectDataService
    from ost_visualizer.infrastructure.database.descriptor_registry import (
        DatabaseDescriptorRegistry,
    )
    from ost_visualizer.infrastructure.database.entity_version_reader import (
        DatabaseEntityVersionReader,
    )
    from ost_visualizer.infrastructure.events.event_bus import EventBus
    from ost_visualizer.infrastructure.sql.collaboration_store import (
        SqlCollaborationStore,
    )
    from ost_visualizer.infrastructure.sql.connection_manager import (
        SqlConnectionManager,
    )
    from ost_visualizer.infrastructure.sql.permissions import (
        SqlDatabasePermissionProbe,
    )
    from ost_visualizer.infrastructure.sql.remote_change_reader import (
        SqlRemoteChangeReader,
    )
    from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
    from ost_visualizer.presentation.utils.qt_callback_bridge import QtCallbackBridge

    application = QCoreApplication.instance() or QCoreApplication([])
    credentials = _InMemoryCredentialAdapter()
    connections = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
    descriptors = DatabaseDescriptorRegistry()
    descriptor = DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(
            server="localhost,65535",
            database="OSTV_IT_FOUNDATION",
            database_guid=str(uuid.uuid4()),
        ),
        schema_version=SQL_SCHEMA_V1.version,
    )
    descriptors.register(descriptor)
    sessions = DatabaseSessionRegistry()
    drafts = LocalDraftRegistry()
    token_reader = DatabaseEntityVersionReader(descriptors, credentials, connections)
    tokens = DatabaseConcurrencyTokenService(token_reader, drafts)
    event_bus = EventBus()
    project_data = ProjectDataService(
        OstAggregate(FileManager(_FoundationRepository()))
    )
    reconciliation = RemoteChangeReconciliationService(
        project_data,
        event_bus,
        tokens,
        drafts,
        ConflictResolutionService(),
    )
    remote_reader = SqlRemoteChangeReader(descriptors, credentials, connections)
    store = SqlCollaborationStore(descriptors, credentials, connections)
    capabilities = DatabaseCapabilityService(
        descriptors,
        SqlDatabasePermissionProbe(descriptors, credentials, connections),
    )
    bridge = QtCallbackBridge()
    coordinator = SqlCollaborationCoordinator(
        descriptors,
        store,
        remote_reader,
        bridge,
        reconciliation,
        capabilities,
        sessions,
        tokens,
        drafts,
        event_bus,
        SQL_SCHEMA_V1.version,
    )
    shutdown_results = []
    coordinator.request_shutdown(
        lambda success, message: shutdown_results.append((success, message))
    )
    application.processEvents()
    if shutdown_results != [(True, "")]:
        raise RuntimeError("The spawned client stack did not shut down cleanly")


def _bounded_text(value: str, name: str) -> None:
    if len(value) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{name} exceeds its bounded result size")
