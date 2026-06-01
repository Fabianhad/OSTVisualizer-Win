import logging
from typing import Callable, Optional
from ..events.app_events import AppEvents


class BaseWriteService:
    def __init__(
        self,
        reload_database: Callable[[str], bool],
        event_bus,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._reload_database = reload_database
        self._event_bus = event_bus
        self.logger = logger or logging.getLogger(__name__)

    def reload_and_notify(self, file_path: str) -> bool:
        if not self.reload_database(file_path):
            return False
        self.notify_database_refreshed(file_path)
        return True

    def reload_database(self, file_path: str) -> bool:
        try:
            return self._reload_database(file_path)
        except Exception:
            self.logger.warning("Failed to reload database", exc_info=True)
            return False

    def notify_database_refreshed(self, file_path: str) -> None:
        self._event_bus.publish(AppEvents.DATABASE_REFRESHED, file_path=file_path)
