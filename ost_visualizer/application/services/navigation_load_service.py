from __future__ import annotations
import logging
import queue
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, Optional, TypeVar
from ...domain.entities.database_descriptor import DatabaseBackend
from ..interfaces.i_database_descriptor_registry import IDatabaseDescriptorRegistry
from ..interfaces.i_thread_callback_bridge import IThreadCallbackBridge

T = TypeVar("T")


class NavigationLoadState(str, Enum):
    EMPTY = "empty"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class NavigationLoadResult(Generic[T]):
    request_id: str
    generation: int
    database_id: str
    bid_uid: str
    state: NavigationLoadState
    value: Optional[T] = None
    message: str = ""


@dataclass(frozen=True)
class _NavigationReadRequest(Generic[T]):
    request_id: str
    generation: int
    database_id: str
    bid_uid: str
    work: Callable[[], T]
    completion: Callable[[NavigationLoadResult[T]], None]


class NavigationLoadService:
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        dispatcher: IThreadCallbackBridge,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._registry = descriptor_registry
        self._dispatcher = dispatcher
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._requests: queue.Queue[Optional[_NavigationReadRequest]] = queue.Queue(
            maxsize=1
        )
        self._generation = 0
        self._active_request_id = ""
        self._active_database_id = ""
        self._active_bid_uid = ""
        self._state = NavigationLoadState.EMPTY
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="NavigationRead",
        )
        self._thread.start()

    def uses_background_reads(self, database_id: str) -> bool:
        descriptor = self._registry.resolve(database_id)
        return bool(
            descriptor is not None and descriptor.backend == DatabaseBackend.SQL_SERVER
        )

    def submit(
        self,
        database_id: str,
        bid_uid: str,
        work: Callable[[], T],
        completion: Callable[[NavigationLoadResult[T]], None],
    ) -> NavigationLoadResult[None]:
        if not database_id:
            raise ValueError("A navigation read requires a database ID.")
        with self._lock:
            if self._closed:
                raise RuntimeError("Navigation loading has stopped.")
            self._generation += 1
            request = _NavigationReadRequest(
                request_id=str(uuid.uuid4()),
                generation=self._generation,
                database_id=database_id,
                bid_uid=str(bid_uid or ""),
                work=work,
                completion=completion,
            )
            self._active_request_id = request.request_id
            self._active_database_id = database_id
            self._active_bid_uid = request.bid_uid
            self._state = NavigationLoadState.LOADING
            self._discard_queued_request()
            self._requests.put_nowait(request)
            return NavigationLoadResult(
                request_id=request.request_id,
                generation=request.generation,
                database_id=database_id,
                bid_uid=request.bid_uid,
                state=NavigationLoadState.LOADING,
            )

    def cancel(self, database_id: str = "") -> None:
        with self._lock:
            if database_id and database_id != self._active_database_id:
                return
            self._generation += 1
            self._active_request_id = ""
            self._active_database_id = ""
            self._active_bid_uid = ""
            self._state = NavigationLoadState.CANCELLED
            self._discard_queued_request()

    def state(self) -> NavigationLoadResult[None]:
        with self._lock:
            return NavigationLoadResult(
                request_id=self._active_request_id,
                generation=self._generation,
                database_id=self._active_database_id,
                bid_uid=self._active_bid_uid,
                state=self._state,
            )

    def cleanup(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            self._active_request_id = ""
            self._active_database_id = ""
            self._active_bid_uid = ""
            self._state = NavigationLoadState.CANCELLED
            self._discard_queued_request()
            try:
                self._requests.put_nowait(None)
            except queue.Full:
                pass

    def _discard_queued_request(self) -> None:
        try:
            self._requests.get_nowait()
        except queue.Empty:
            return

    def _run(self) -> None:
        while True:
            request = self._requests.get()
            if request is None:
                return
            try:
                value = request.work()
                result = NavigationLoadResult(
                    request_id=request.request_id,
                    generation=request.generation,
                    database_id=request.database_id,
                    bid_uid=request.bid_uid,
                    state=NavigationLoadState.READY,
                    value=value,
                )
            except Exception as exc:
                self._logger.warning(
                    "Navigation read failed for database %s",
                    request.database_id,
                    exc_info=True,
                )
                result = NavigationLoadResult(
                    request_id=request.request_id,
                    generation=request.generation,
                    database_id=request.database_id,
                    bid_uid=request.bid_uid,
                    state=NavigationLoadState.FAILED,
                    message=str(exc) or exc.__class__.__name__,
                )
            with self._lock:
                if (
                    self._closed
                    or request.request_id != self._active_request_id
                    or request.generation != self._generation
                ):
                    continue
                self._dispatcher.dispatch(
                    self._complete,
                    (request, result),
                )

    def _complete(self, payload) -> None:
        request, result = payload
        with self._lock:
            if (
                self._closed
                or result.request_id != self._active_request_id
                or result.generation != self._generation
            ):
                return
            self._state = result.state
        request.completion(result)
