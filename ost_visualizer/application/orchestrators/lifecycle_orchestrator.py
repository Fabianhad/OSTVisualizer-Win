import logging
from typing import Any
from ..interfaces.i_event_bus import IEventBus
from ..interfaces.i_shutdown_aware import IShutdownAware
from ..service_container import ServiceContainer


class LifecycleOrchestrator:
    def __init__(
        self,
        container: ServiceContainer,
        visualization_orchestrator,
        event_bus: IEventBus,
        logger: logging.Logger,
    ):
        self._container = container
        self._viz_orchestrator = visualization_orchestrator
        self.event_bus = event_bus
        self.logger = logger
        self._shutdown_performed = False
        self._app_controller = None

    def set_app_controller(self, app_controller) -> None:
        self._app_controller = app_controller

    def handle_license_expired(self, **kwargs: Any) -> None:
        self._viz_orchestrator.close_realtime_visualization()

    def shutdown(self) -> None:
        if self._shutdown_performed:
            return
        self._perform_shutdown()

    def _perform_shutdown(self) -> None:
        self._shutdown_performed = True
        try:
            participants = self._container.get_by_interface(IShutdownAware)
            for participant in participants:
                try:
                    participant.shutdown()
                except Exception as exc:
                    self.logger.exception(
                        "Error shutting down %s: %s", participant, exc
                    )
            if self._app_controller:
                self._app_controller.cleanup()
        except Exception as exc:
            self.logger.exception("Error during shutdown: %s", exc)
