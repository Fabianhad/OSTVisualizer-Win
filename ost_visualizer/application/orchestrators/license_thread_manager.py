import logging
import threading
from typing import Any, Callable, List


class LicenseThreadManager:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._lock = threading.RLock()
        self._active_threads: List[threading.Thread] = []
        self._closed = False

    def spawn_with_bridge(
        self,
        operation: Callable[[], tuple[bool, str, Any]],
        callback_bridge: Any,
        on_main_thread: Callable[..., None],
        error_prefix: str = "Operation",
    ) -> threading.Thread:
        def run_operation() -> None:
            success, message, extra_data = False, "", None
            try:
                success, message, extra_data = operation()
            except Exception as exc:
                self._logger.exception("Error in %s thread: %s", error_prefix, exc)
                success, message = False, f"Operation failed: {str(exc)}"
            finally:

                def wrapped_callback(s: bool, m: str) -> None:
                    with self._lock:
                        if self._closed:
                            return
                        on_main_thread(s, m, extra_data)

                try:
                    with self._lock:
                        if not self._closed:
                            callback_bridge.request_callback(
                                wrapped_callback, success, message
                            )
                except Exception as exc:
                    self._logger.exception("Error dispatching thread callback: %s", exc)
                finally:
                    self._remove_thread(thread)

        thread = threading.Thread(target=run_operation, daemon=True)
        with self._lock:
            if self._closed:
                raise RuntimeError("License operations have stopped")
            self._active_threads.append(thread)
            try:
                thread.start()
            except Exception:
                self._active_threads.remove(thread)
                raise
        return thread

    def cleanup(self, timeout: float = 2.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active_threads = list(self._active_threads)
        errors = []
        for thread in active_threads:
            if thread.is_alive():
                try:
                    thread.join(timeout=timeout)
                except Exception as exc:
                    errors.append(exc)
                    continue
                if thread.is_alive():
                    self._logger.warning(
                        "Thread %s did not stop within %ss",
                        thread.name,
                        timeout,
                    )
        with self._lock:
            self._active_threads.clear()
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("License worker cleanup failed", errors)

    def _remove_thread(self, thread: threading.Thread) -> None:
        with self._lock:
            if thread in self._active_threads:
                self._active_threads.remove(thread)
