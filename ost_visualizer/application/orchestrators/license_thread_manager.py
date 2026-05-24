import logging
import threading
from typing import Any, Callable, List


class LicenseThreadManager:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._active_threads: List[threading.Thread] = []

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
                    on_main_thread(s, m, extra_data)

                try:
                    callback_bridge.request_callback(wrapped_callback, success, message)
                except Exception as exc:
                    self._logger.exception("Error dispatching thread callback: %s", exc)
                finally:
                    self._remove_thread(thread)

        thread = threading.Thread(target=run_operation, daemon=True)
        self._active_threads.append(thread)
        thread.start()
        return thread

    def cleanup(self, timeout: float = 2.0) -> None:
        for thread in self._active_threads[:]:
            if thread.is_alive():
                thread.join(timeout=timeout)
                if thread.is_alive():
                    self._logger.warning(
                        "Thread %s did not stop within %ss",
                        thread.name,
                        timeout,
                    )
        self._active_threads.clear()

    def _remove_thread(self, thread: threading.Thread) -> None:
        try:
            self._active_threads.remove(thread)
        except ValueError:
            pass
