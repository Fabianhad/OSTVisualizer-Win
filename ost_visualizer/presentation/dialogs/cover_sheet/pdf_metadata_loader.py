from __future__ import annotations
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Tuple
from PySide6 import QtCore
from .row_model import PdfPageSize


class IRunnablePool(Protocol):
    def start(self, _runnable: QtCore.QRunnable) -> None: ...


PdfFileSignature = Tuple[int, int]
PdfMetadataKey = Tuple[str, PdfFileSignature]


@dataclass(frozen=True)
class PdfMetadataRequest:
    request_id: int
    dialog_generation: int
    page_uid: str
    row_revision: int
    path: str
    path_identity: str
    file_signature: PdfFileSignature


@dataclass(frozen=True)
class PdfMetadataResult:
    request: PdfMetadataRequest
    signature: Optional[PdfFileSignature]
    page_sizes: Tuple[PdfPageSize, ...]
    error: Optional[Exception]


@dataclass(frozen=True)
class PdfMetadataSnapshot:
    signature: PdfFileSignature
    page_sizes: Tuple[PdfPageSize, ...]


@dataclass(frozen=True)
class _CacheEntry:
    signature: PdfFileSignature
    page_sizes: Tuple[PdfPageSize, ...]


@dataclass(frozen=True)
class _LoadResult:
    request_key: PdfMetadataKey
    signature: Optional[PdfFileSignature]
    page_sizes: Tuple[PdfPageSize, ...]
    error: Optional[Exception]


class _MetadataRunnable(QtCore.QRunnable):
    def __init__(
        self,
        loader: "PdfMetadataLoader",
        path: str,
        request_key: PdfMetadataKey,
    ) -> None:
        super().__init__()
        self._loader = loader
        self._path = path
        self._request_key = request_key

    def run(self) -> None:
        result = self._loader._load_result(self._path, self._request_key)
        self._loader._worker_completed.emit(result)


class PdfMetadataLoader(QtCore.QObject):
    result_ready = QtCore.Signal(object)
    _worker_completed = QtCore.Signal(object)

    def __init__(
        self,
        provider: Optional[Callable[[str], List[PdfPageSize]]],
        *,
        thread_pool: Optional[IRunnablePool] = None,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._thread_pool = (
            thread_pool
            if thread_pool is not None
            else QtCore.QThreadPool.globalInstance()
        )
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._in_flight: Dict[PdfMetadataKey, List[PdfMetadataRequest]] = {}
        self._closed = False
        self._worker_completed.connect(
            self._on_worker_completed,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

    @staticmethod
    def file_signature(path: str) -> PdfFileSignature:
        stat = Path(path).stat()
        return stat.st_mtime_ns, stat.st_size

    def cached(
        self, path_identity: str, signature: PdfFileSignature
    ) -> Optional[Tuple[PdfPageSize, ...]]:
        with self._cache_lock:
            entry = self._cache.get(path_identity)
            if entry is None or entry.signature != signature:
                return None
            return entry.page_sizes

    def load(self, path: str, path_identity: str) -> PdfMetadataSnapshot:
        if self._closed:
            raise RuntimeError("PDF metadata loader is closed")
        if self._provider is None:
            return ()
        signature = self.file_signature(path)
        result = self._load_result(path, (path_identity, signature))
        if result.error is not None:
            raise result.error
        if result.signature != signature:
            raise OSError(f"PDF changed while reading page metadata: {path}")
        return PdfMetadataSnapshot(signature, result.page_sizes)

    def request(self, request: PdfMetadataRequest) -> bool:
        if self._closed or self._provider is None:
            return False
        request_key = request.path_identity, request.file_signature
        waiters = self._in_flight.get(request_key)
        if waiters is not None:
            waiters.append(request)
            return True
        self._in_flight[request_key] = [request]
        try:
            self._thread_pool.start(_MetadataRunnable(self, request.path, request_key))
        except RuntimeError:
            self._in_flight.pop(request_key, None)
            return False
        return True

    def close(self) -> None:
        self._in_flight.clear()
        with self._cache_lock:
            self._closed = True
            self._cache.clear()

    def _load_result(self, path: str, request_key: PdfMetadataKey) -> _LoadResult:
        path_identity, requested_signature = request_key
        provider = self._provider
        assert provider is not None
        try:
            signature = self.file_signature(path)
            if signature != requested_signature:
                return _LoadResult(request_key, signature, (), None)
            cached = self.cached(path_identity, signature)
            if cached is not None:
                return _LoadResult(request_key, signature, cached, None)
            page_sizes = tuple(provider(path))
            final_signature = self.file_signature(path)
            if final_signature != signature:
                return _LoadResult(request_key, final_signature, (), None)
            with self._cache_lock:
                if not self._closed:
                    self._cache[path_identity] = _CacheEntry(signature, page_sizes)
            return _LoadResult(request_key, signature, page_sizes, None)
        except Exception as exc:
            return _LoadResult(request_key, None, (), exc)

    @QtCore.Slot(object)
    def _on_worker_completed(self, loaded: _LoadResult) -> None:
        requests = self._in_flight.pop(loaded.request_key, [])
        if self._closed:
            return
        for request in requests:
            self.result_ready.emit(
                PdfMetadataResult(
                    request=request,
                    signature=loaded.signature,
                    page_sizes=loaded.page_sizes,
                    error=loaded.error,
                )
            )
