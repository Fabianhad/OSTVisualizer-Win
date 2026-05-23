import logging
from typing import Optional
from ...domain.entities.license import LicenseStatus
from ..events.app_events import AppEvents
from ..interfaces.i_event_bus import IEventBus


class LicenseEventPublisher:
    def __init__(self, event_bus: IEventBus, logger: logging.Logger) -> None:
        self._event_bus = event_bus
        self._logger = logger
        self._failure_notified: bool = False

    def publish_activated(self) -> None:
        self._event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self._failure_notified = False

    def publish_license_lost(self) -> None:
        self._event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)

    def publish_invalidated(
        self,
        message: str,
        status: Optional[LicenseStatus] = None,
    ) -> bool:
        if self._failure_notified:
            return False
        self._failure_notified = True
        if status == LicenseStatus.EXPIRED:
            self._logger.warning("License expired: %s", message)
            self._event_bus.publish(AppEvents.LICENSE_EXPIRED)
        else:
            self._logger.warning("License invalid: %s", message)
        self._event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)
        return True

    def reset_failure_state(self) -> None:
        self._failure_notified = False
