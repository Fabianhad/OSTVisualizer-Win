import logging
import threading
from typing import Any, Callable, Optional


class LicenseValidationScheduler:
    def __init__(
        self,
        interval_seconds: int,
        task: Optional[Callable[[], Optional[Any]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.interval_seconds = interval_seconds
        self._task = task
        self.logger = logger or logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def set_task(self, task: Callable[[], Optional[Any]]) -> None:
        self._task = task

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=2)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._stop_event.wait(self.interval_seconds):
                break
            if not self._task:
                continue
            try:
                self._task()
            except Exception as exc:
                self.logger.exception("Scheduled license validation failed: %s", exc)
