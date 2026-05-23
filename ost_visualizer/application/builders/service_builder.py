import logging
from ..events.app_events import AppEvents
from ..interfaces.i_color_service import IColorService
from ..interfaces.i_infrastructure_service_provider import (
    IInfrastructureServiceProvider,
)
from ..interfaces.i_parser_provider import IParserProvider
from ..interfaces.i_thread_scene_notifier import IThreadSceneNotifier
from ..service_container import ServiceContainer
from ..services.export_service import ExportService
from ..services.file_loading_service import FileLoadingService
from ..services.import_service import ImportService
from ..services.preferences_service import PreferencesService
from ..services.update_check_service import UpdateCheckService
from ..services.visualization_service import VisualizationService
from ..services.working_directory_service import WorkingDirectoryService


class ServiceBuilder:
    def __init__(
        self,
        container: ServiceContainer,
        logger: logging.Logger,
        infrastructure_provider: IInfrastructureServiceProvider,
        parser_provider: IParserProvider,
        scene_notifier: IThreadSceneNotifier,
        ost_signaler=None,
    ) -> None:
        self.container = container
        self.logger = logger
        self.infrastructure_provider = infrastructure_provider
        self.parser_provider = parser_provider
        self.scene_notifier = scene_notifier
        self.ost_signaler = ost_signaler

    def build(
        self,
        config_model,
        project_data_service,
        project_operations_service,
        event_bus,
        connection_manager,
        license_api_client,
    ) -> None:
        self._register_icon_provider()
        self._register_core_services(
            config_model,
            project_data_service,
            project_operations_service,
            event_bus,
            connection_manager,
            license_api_client,
        )

    def _register_icon_provider(self) -> None:
        icon_provider = self.infrastructure_provider.get_icon_provider()
        if icon_provider:
            self.container.register_instance("icon_provider", icon_provider)

    def _register_core_services(
        self,
        config_model,
        project_data_service,
        project_operations_service,
        event_bus,
        connection_manager,
        license_api_client,
    ) -> None:
        parsers = self.parser_provider.get_parsers()
        mdb_parser = parsers.get("mdb")
        if mdb_parser:
            self.container.register_instance("mdb_file_parser", mdb_parser)
        self.container.register_singleton(
            "file_loading_service",
            lambda: FileLoadingService(
                project_operations_service,
                project_data_service,
                mdb_parser,
            ),
        )
        self.container.register_singleton(
            "preferences_service",
            lambda: PreferencesService(config_model, event_bus),
        )
        transaction_monitor = self.infrastructure_provider.get_transaction_monitor()
        conn_manager = connection_manager
        if self.ost_signaler is not None:

            def _on_ost_signaler_main_thread(active: bool) -> None:
                if conn_manager:
                    conn_manager.set_write_blocked(active)
                event_bus.publish(AppEvents.OST_STATUS_CHANGED, active=active)

            self.ost_signaler.ost_changed.connect(_on_ost_signaler_main_thread)
            transaction_monitor.set_ost_status_callback(self.ost_signaler.emit_status)
        self.container.register_instance("transaction_monitor", transaction_monitor)
        takeoff_service = self.infrastructure_provider.get_takeoff_domain_service()
        self.container.register_instance("takeoff_domain_service", takeoff_service)
        uom_service = self.infrastructure_provider.get_uom_service()
        self.container.register_instance("uom_service", uom_service)
        visualization_provider = (
            self.infrastructure_provider.get_visualization_provider(takeoff_service)
        )
        self.container.register_instance(
            "visualization_provider", visualization_provider
        )
        coord_factory = (
            self.infrastructure_provider.get_coordinate_transformer_factory()
        )
        self.container.register_instance(
            "coordinate_transformer_factory", coord_factory
        )
        self.container.register_singleton(
            "visualization_service",
            lambda: VisualizationService(
                config_model,
                project_data_service,
                project_operations_service,
                event_bus,
                transaction_monitor,
                visualization_provider,
                self.scene_notifier,
            ),
        )
        self.container.register_singleton(
            "export_service",
            lambda: ExportService(
                visualization_provider,
                project_data_service,
            ),
        )
        api_client = license_api_client
        update_logger = self.logger.getChild("UpdateCheck")
        self.container.register_singleton(
            "update_check_service",
            lambda: UpdateCheckService(
                api_client=api_client,
                logger=update_logger,
            ),
        )
        color_service: IColorService = self.infrastructure_provider.get_color_service()
        self.container.register_instance("color_service", color_service)
        pdf_exporter = self.infrastructure_provider.get_pdf_exporter(
            coord_factory.create(),
            color_service,
            takeoff_service,
            uom_service,
        )
        self.container.register_instance("pdf_exporter", pdf_exporter)
        ost_exporter = self.infrastructure_provider.get_ost_exporter(uom_service)
        self.container.register_instance("ost_exporter", ost_exporter)
        osp_exporter = self.infrastructure_provider.get_osp_exporter(
            uom_service, UpdateCheckService.CURRENT_VERSION
        )
        self.container.register_instance("osp_exporter", osp_exporter)
        ost_importer = self.infrastructure_provider.get_ost_importer(
            conn_manager=conn_manager
        )
        self.container.register_instance("ost_importer", ost_importer)
        osp_importer = self.infrastructure_provider.get_osp_importer(
            conn_manager=conn_manager
        )
        self.container.register_instance("osp_importer", osp_importer)
        reload_database_uc = self.container.get("reload_database_use_case")
        self.container.register_instance(
            "import_service",
            ImportService(
                ost_importer=ost_importer,
                osp_importer=osp_importer,
                reload_database=reload_database_uc.execute,
                event_bus=event_bus,
                logger=self.logger.getChild("ImportService"),
            ),
        )
        wd_logger = self.logger.getChild("WorkingDirectory")
        working_directory_service = WorkingDirectoryService(
            database_creator=self.infrastructure_provider.get_database_creator(),
            working_dir=self.infrastructure_provider.get_default_working_dir(),
            logger=wd_logger,
        )
        self.container.register_instance(
            "working_directory_service", working_directory_service
        )
