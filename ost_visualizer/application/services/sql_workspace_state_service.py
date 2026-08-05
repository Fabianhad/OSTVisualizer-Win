from __future__ import annotations
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional
from ...domain.entities.database_descriptor import DatabaseBackend
from ..dtos.user_workspace_state_dtos import (
    UserBidWorkspaceState,
    UserPageViewState,
)
from ..interfaces.i_database_descriptor_registry import IDatabaseDescriptorRegistry
from ..interfaces.i_sql_workspace_state_repository import (
    ISqlWorkspaceStateRepository,
)


@dataclass(frozen=True)
class _WorkspaceWriteRequest:
    key: tuple[str, ...]
    generation: int
    work: Callable[[], None]


class SqlWorkspaceStateService:
    """Own per-user SQL workspace reads and serialized background writes.
    Navigation calls the read path from its worker. UI callers enqueue writes
    here so SQL connections remain off the Qt thread.
    """

    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        repository: ISqlWorkspaceStateRepository,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._registry = descriptor_registry
        self._repository = repository
        self._logger = logger or logging.getLogger(__name__)
        self._condition = threading.Condition()
        self._pending: dict[tuple[str, ...], _WorkspaceWriteRequest] = {}
        self._keys: deque[tuple[str, ...]] = deque()
        self._enqueued: set[tuple[str, ...]] = set()
        self._generations: dict[tuple[str, ...], int] = {}
        self._active_writes = 0
        self._accepting = True
        self._stopping = False
        self._thread: Optional[threading.Thread] = None

    def uses_sql_workspace(self, database_id: str) -> bool:
        descriptor = self._registry.resolve(database_id)
        return bool(
            descriptor is not None and descriptor.backend == DatabaseBackend.SQL_SERVER
        )

    def load_bid_state(self, database_id: str, bid_uid: str) -> UserBidWorkspaceState:
        if not self.uses_sql_workspace(database_id):
            raise ValueError("SQL workspace state requires a SQL Server database")
        try:
            return self._repository.load_bid_state(database_id, bid_uid)
        except Exception:
            self._logger.warning(
                "Failed to load per-user SQL workspace state for database %s bid %s",
                database_id,
                bid_uid,
                exc_info=True,
            )
            return UserBidWorkspaceState()

    def save_active_page(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
    ) -> None:
        key = ("active_page", database_id, str(bid_uid))
        self._submit(
            key,
            database_id,
            lambda: self._repository.save_active_page(
                database_id, str(bid_uid), str(page_uid)
            ),
        )

    def save_page_view(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> None:
        state = UserPageViewState(
            zoom_fac=float(zoom_fac),
            current_x=float(current_x),
            current_y=float(current_y),
        )
        key = ("page_view", database_id, str(bid_uid), str(page_uid))
        self._submit(
            key,
            database_id,
            lambda: self._repository.save_page_view(
                database_id, str(bid_uid), str(page_uid), state
            ),
        )

    def wait_for_idle(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._condition:
            while self._pending or self._keys or self._active_writes:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._condition.wait(remaining)
            return True

    def cleanup(self, timeout_seconds: float = 1.0) -> bool:
        with self._condition:
            if self._stopping:
                return not bool(self._pending or self._active_writes)
            self._accepting = False
        drained = self.wait_for_idle(timeout_seconds)
        with self._condition:
            if not drained:
                abandoned = len(self._pending)
                active = self._active_writes
                self._pending.clear()
                self._keys.clear()
                self._enqueued.clear()
                self._logger.warning(
                    "SQL workspace shutdown timed out with %d queued write(s) "
                    "abandoned and %d active write(s) still finishing",
                    abandoned,
                    active,
                )
            self._stopping = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=0.05)
        return drained

    def _submit(
        self,
        key: tuple[str, ...],
        database_id: str,
        work: Callable[[], None],
    ) -> None:
        if not self.uses_sql_workspace(database_id):
            raise ValueError("SQL workspace state requires a SQL Server database")
        with self._condition:
            if not self._accepting:
                raise RuntimeError("SQL workspace persistence has stopped")
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    daemon=True,
                    name="SqlWorkspaceState",
                )
                self._thread.start()
            generation = self._generations.get(key, 0) + 1
            self._generations[key] = generation
            self._pending[key] = _WorkspaceWriteRequest(
                key=key,
                generation=generation,
                work=work,
            )
            if key not in self._enqueued:
                self._enqueued.add(key)
                self._keys.append(key)
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._keys and not self._stopping:
                    self._condition.wait()
                if self._stopping and not self._keys:
                    return
                key = self._keys.popleft()
                self._enqueued.discard(key)
                request = self._pending.pop(key, None)
                if request is None:
                    self._condition.notify_all()
                    continue
                self._active_writes += 1
            self._execute(request)
            with self._condition:
                self._active_writes -= 1
                self._condition.notify_all()

    def _execute(self, request: _WorkspaceWriteRequest) -> None:
        try:
            request.work()
        except Exception:
            self._logger.warning(
                "Per-user SQL workspace write failed for %s generation %d",
                request.key,
                request.generation,
                exc_info=True,
            )
