import logging
from dataclasses import dataclass
from ...config.license_config import LICENSE_VALIDATION_INTERVAL_SECONDS
from ..interfaces.i_event_bus import IEventBus
from ..interfaces.i_infrastructure_service_provider import (
    IInfrastructureServiceProvider,
)
from ..interfaces.i_license_validation_scheduler import ILicenseValidationScheduler
from ..orchestrators.license_event_publisher import LicenseEventPublisher
from ..orchestrators.license_orchestrator import LicenseOrchestrator
from ..orchestrators.license_thread_manager import LicenseThreadManager
from ..orchestrators.lifecycle_orchestrator import LifecycleOrchestrator
from ..orchestrators.visualization_orchestrator import VisualizationOrchestrator
from ..service_container import ServiceContainer


@dataclass
class AppOrchestrators:
    visualization: VisualizationOrchestrator
    lifecycle: LifecycleOrchestrator
    license: LicenseOrchestrator


class OrchestratorBuilder:
    def __init__(
        self,
        container: ServiceContainer,
        event_bus: IEventBus,
        logger: logging.Logger,
        infrastructure_provider: IInfrastructureServiceProvider,
    ) -> None:
        self.container = container
        self.event_bus = event_bus
        self.logger = logger
        self.infrastructure_provider = infrastructure_provider

    def build(
        self,
        license_model,
        validate_use_case,
        activate_use_case,
        deactivate_use_case,
    ) -> AppOrchestrators:
        orchestrator_logger = self.logger.getChild("Orchestrators")
        visualization = VisualizationOrchestrator()
        self.container.register_instance("visualization_orchestrator", visualization)
        lifecycle_logger = orchestrator_logger.getChild("Lifecycle")
        lifecycle = LifecycleOrchestrator(
            container=self.container,
            visualization_orchestrator=visualization,
            event_bus=self.event_bus,
            logger=lifecycle_logger,
        )
        self.container.register_instance("lifecycle_orchestrator", lifecycle)
        license_orchestrator = self._build_license_orchestrator(
            orchestrator_logger,
            license_model,
            validate_use_case,
            activate_use_case,
            deactivate_use_case,
        )
        self.container.register_instance("license_orchestrator", license_orchestrator)
        return AppOrchestrators(
            visualization=visualization,
            lifecycle=lifecycle,
            license=license_orchestrator,
        )

    def _build_license_orchestrator(
        self,
        orchestrator_logger: logging.Logger,
        license_model,
        validate_use_case,
        activate_use_case,
        deactivate_use_case,
    ) -> LicenseOrchestrator:
        license_logger = orchestrator_logger.getChild("License")
        thread_manager = LicenseThreadManager(license_logger.getChild("ThreadManager"))
        self.container.register_instance("license_thread_manager", thread_manager)
        event_publisher = LicenseEventPublisher(
            self.event_bus, license_logger.getChild("EventPublisher")
        )
        self.container.register_instance("license_event_publisher", event_publisher)
        scheduler = self._create_scheduler()
        callback_bridge = self.infrastructure_provider.get_thread_callback_bridge()
        return LicenseOrchestrator(
            license_model=license_model,
            validate_use_case=validate_use_case,
            activate_use_case=activate_use_case,
            deactivate_use_case=deactivate_use_case,
            scheduler=scheduler,
            event_publisher=event_publisher,
            thread_manager=thread_manager,
            callback_bridge=callback_bridge,
            logger=license_logger.getChild("Orchestrator"),
        )

    def _create_scheduler(self) -> ILicenseValidationScheduler:
        scheduler = self.infrastructure_provider.create_license_validation_scheduler(
            interval_seconds=LICENSE_VALIDATION_INTERVAL_SECONDS
        )
        self.container.register_instance("license_validation_scheduler", scheduler)
        return scheduler
