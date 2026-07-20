from __future__ import annotations
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Generic, Optional, Protocol, TypeVar
from PySide6 import QtCore
from ...application.interfaces.i_thread_callback_bridge import IThreadCallbackBridge

logger = logging.getLogger(__name__)
RequestT = TypeVar("RequestT")
PreparedT = TypeVar("PreparedT")


class IRunnablePool(Protocol):
    def start(self, _runnable: QtCore.QRunnable) -> None: ...
@dataclass
class _Submission(Generic[RequestT]):
    request: RequestT
    completions: list[Callable[[bool], None]]


@dataclass(frozen=True)
class _PreparationResult(Generic[RequestT, PreparedT]):
    request: RequestT
    prepared: Optional[PreparedT]
    error: Optional[Exception]


class _PreparationRunnable(QtCore.QRunnable, Generic[RequestT, PreparedT]):
    def __init__(
        self,
        request: RequestT,
        prepare: Callable[[RequestT], PreparedT],
        callback_bridge: IThreadCallbackBridge,
        callback: Callable[[_PreparationResult[RequestT, PreparedT]], None],
    ) -> None:
        super().__init__()
        self._request = request
        self._prepare = prepare
        self._callback_bridge = callback_bridge
        self._callback = callback

    def run(self) -> None:
        try:
            result = _PreparationResult(
                request=self._request,
                prepared=self._prepare(self._request),
                error=None,
            )
        except Exception as exc:
            result = _PreparationResult(
                request=self._request,
                prepared=None,
                error=exc,
            )
        self._callback_bridge.dispatch(self._callback, result)


class RemotePlanUpdatePipeline(Generic[RequestT, PreparedT]):
    """Runs bounded plan preparation off-thread and serializes Qt projections."""

    def __init__(
        self,
        *,
        callback_bridge: IThreadCallbackBridge,
        prepare: Callable[[RequestT], PreparedT],
        apply: Callable[[PreparedT], bool],
        is_current: Callable[[RequestT], bool],
        coalesce: Callable[[RequestT, RequestT], RequestT],
        thread_pool: Optional[IRunnablePool] = None,
    ) -> None:
        self._callback_bridge = callback_bridge
        self._prepare = prepare
        self._apply = apply
        self._is_current = is_current
        self._coalesce = coalesce
        self._thread_pool = thread_pool or QtCore.QThreadPool.globalInstance()
        self._lock = threading.Lock()
        self._in_flight: Optional[_Submission[RequestT]] = None
        self._pending: Optional[_Submission[RequestT]] = None
        self._closed = False

    def submit(self, request: RequestT, completion: Callable[[bool], None]) -> None:
        start: Optional[_Submission[RequestT]] = None
        reject = False
        with self._lock:
            if self._closed:
                reject = True
            elif self._in_flight is None:
                start = _Submission(request, [completion])
                self._in_flight = start
            elif self._pending is None:
                self._pending = _Submission(request, [completion])
            else:
                self._pending.request = self._coalesce(self._pending.request, request)
                self._pending.completions.append(completion)
        if reject:
            self._invoke_completions((completion,), False)
        elif start is not None:
            self._start_submission(start)

    def _start_submission(self, submission: _Submission[RequestT]) -> None:
        try:
            self._thread_pool.start(
                _PreparationRunnable(
                    submission.request,
                    self._prepare,
                    self._callback_bridge,
                    self._on_prepared,
                )
            )
            return
        except Exception:
            logger.exception("Remote plan update worker could not be started")
        next_submission: Optional[_Submission[RequestT]] = None
        with self._lock:
            if self._in_flight is not submission:
                return
            self._in_flight = None
            if not self._closed and self._pending is not None:
                next_submission = self._pending
                self._pending = None
                self._in_flight = next_submission
        self._invoke_completions(submission.completions, False)
        if next_submission is not None:
            with self._lock:
                should_start = not self._closed and self._in_flight is next_submission
            if should_start:
                self._start_submission(next_submission)

    def _on_prepared(self, result: _PreparationResult[RequestT, PreparedT]) -> None:
        with self._lock:
            submission = self._in_flight
            closed = self._closed
        if submission is None or submission.request is not result.request:
            return
        success = False
        if not closed and result.error is None and self._is_current(result.request):
            try:
                if result.prepared is not None:
                    success = bool(self._apply(result.prepared))
            except Exception:
                logger.exception("Remote plan projection failed")
        elif result.error is not None:
            logger.error(
                "Remote plan update preparation failed: %s",
                result.error,
                exc_info=(
                    type(result.error),
                    result.error,
                    result.error.__traceback__,
                ),
            )
        next_submission: Optional[_Submission[RequestT]] = None
        with self._lock:
            if self._in_flight is not submission:
                return
            self._in_flight = None
            if not self._closed and self._pending is not None:
                next_submission = self._pending
                self._pending = None
                self._in_flight = next_submission
        self._invoke_completions(submission.completions, success)
        if next_submission is not None:
            with self._lock:
                should_start = not self._closed and self._in_flight is next_submission
            if should_start:
                self._start_submission(next_submission)

    @staticmethod
    def _invoke_completions(
        completions: list[Callable[[bool], None]] | tuple[Callable[[bool], None], ...],
        success: bool,
    ) -> None:
        for completion in completions:
            try:
                completion(success)
            except Exception:
                logger.exception("Remote plan update completion callback failed")

    def cleanup(self) -> None:
        completions: list[Callable[[bool], None]] = []
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._in_flight is not None:
                completions.extend(self._in_flight.completions)
                self._in_flight = None
            if self._pending is not None:
                completions.extend(self._pending.completions)
                self._pending = None
        self._invoke_completions(completions, False)
