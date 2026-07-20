from __future__ import annotations
import threading
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class RemoteProjectionToken:
    surface_id: str
    _barrier: "RemoteProjectionBarrier"

    def complete(self, success: bool) -> None:
        self._barrier.complete(self, success)


class RemoteProjectionBarrier:
    def __init__(
        self,
        *,
        database_id: str,
        runtime_generation: int,
        is_runtime_current: Callable[[str, int], bool],
        on_complete: Callable[[bool], None],
    ) -> None:
        self.database_id = database_id
        self.runtime_generation = runtime_generation
        self._is_runtime_current = is_runtime_current
        self._on_complete = on_complete
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._sealed = False
        self._failed = False
        self._completed = False

    def is_current(self) -> bool:
        return self._is_runtime_current(self.database_id, self.runtime_generation)

    def register(self, surface_id: str) -> RemoteProjectionToken:
        if not surface_id:
            raise ValueError("A remote projection surface ID is required")
        with self._lock:
            if self._sealed:
                raise RuntimeError("Remote projection registration is already sealed")
            if surface_id in self._pending:
                raise ValueError(
                    f"Remote projection surface is already registered: {surface_id}"
                )
            self._pending.add(surface_id)
        return RemoteProjectionToken(surface_id, self)

    def seal(self) -> None:
        callback: Optional[Callable[[bool], None]] = None
        success = False
        with self._lock:
            if self._sealed:
                return
            self._sealed = True
            callback, success = self._completion_locked()
        if callback is not None:
            callback(success and self.is_current())

    def fail(self) -> None:
        with self._lock:
            if not self._completed:
                self._failed = True

    def complete(self, token: RemoteProjectionToken, success: bool) -> None:
        if token._barrier is not self:
            raise ValueError("The projection token belongs to another barrier")
        callback: Optional[Callable[[bool], None]] = None
        completed_successfully = False
        with self._lock:
            if self._completed or token.surface_id not in self._pending:
                return
            self._pending.remove(token.surface_id)
            self._failed = self._failed or not success
            callback, completed_successfully = self._completion_locked()
        if callback is not None:
            callback(completed_successfully and self.is_current())

    def _completion_locked(self) -> tuple[Optional[Callable[[bool], None]], bool]:
        if self._completed or not self._sealed or self._pending:
            return None, False
        self._completed = True
        callback = self._on_complete
        self._on_complete = lambda _success: None
        success = not self._failed
        return callback, success
