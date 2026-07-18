import logging
from pathlib import Path
from typing import Callable, Optional
from ..application.dtos.plan_view_renderers_dto import PlanViewRenderers
from ..application.interfaces.i_api_client_provider import IApiClientProvider
from ..application.interfaces.i_annotation_caption_resolver import (
    IAnnotationCaptionResolver,
)
from ..application.interfaces.i_color_service import IColorService
from ..application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ..application.interfaces.i_coordinate_transformer_factory import (
    ICoordinateTransformerFactory,
)
from ..application.interfaces.i_database_creator import IDatabaseCreator
from ..application.interfaces.i_credential_store import ICredentialStore
from ..application.interfaces.i_database_catalog import IDatabaseCatalog
from ..application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ..application.interfaces.i_database_permission_probe import (
    IDatabasePermissionProbe,
)
from ..application.interfaces.i_database_session_registry import (
    IDatabaseSessionRegistry,
)
from ..application.interfaces.i_sql_database_creator import ISqlDatabaseCreator
from ..application.interfaces.i_infrastructure_service_provider import (
    IInfrastructureServiceProvider,
)
from ..application.interfaces.i_license_validation_scheduler import (
    ILicenseValidationScheduler,
)
from ..application.interfaces.i_mdb_connection_manager import IMdbConnectionManager
from ..application.interfaces.i_mdb_reader import IMdbReader
from ..application.interfaces.i_mdb_writer import IMdbWriter
from ..application.interfaces.i_message_notifier import IMessageNotifier
from ..application.interfaces.i_osp_exporter import IOspExporter
from ..application.interfaces.i_osp_importer import IOspImporter
from ..application.interfaces.i_ost_exporter import IOstExporter
from ..application.interfaces.i_ost_importer import IOstImporter
from ..application.interfaces.i_pdf_exporter import IPDFExporter
from ..application.interfaces.i_repository_provider import IRepositoryProvider
from ..application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from ..application.interfaces.i_thread_callback_bridge import IThreadCallbackBridge
from ..application.interfaces.i_transaction_monitor import ITransactionMonitor
from ..application.interfaces.i_uom_service import IUOMService
from ..application.interfaces.i_visualization_provider import IVisualizationProvider
from ..application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..application.services.page_load_strategy_service import PageLoadStrategyService
from ..domain.repositories.i_config_repository import IConfigRepository
from ..domain.repositories.i_file_state_repository import IFileStateRepository
from ..domain.repositories.i_license_api_client import ILicenseApiClient
from ..domain.repositories.i_license_repository import ILicenseRepository
from ..domain.repositories.i_license_signature_verifier import (
    ILicenseSignatureVerifier,
)
from ..domain.repositories.i_project_repository import IProjectRepository
from ..domain.repositories.i_workspace_state_repository import IWorkspaceStateRepository
from ..domain.services.takeoff_service_impl import TakeoffDomainService
from ..domain.services.uom_service_impl import UOMDomainService
from ..presentation.visualization.core.geometry.linear_geometry import LinearGeometry
from ..presentation.visualization.exporters.osp_exporter import OspExporter
from ..presentation.visualization.exporters.pdf_exporter import PDFExporter
from ..presentation.visualization.factories.coordinate_transformer_factory import (
    CoordinateTransformerFactory,
)
from ..presentation.visualization.pdf import ost_pdf as _ost_pdf
from ..presentation.visualization.pdf.page_cache import PageCache
from ..presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ..presentation.visualization.pdf.renderers.takeoff_renderer import TakeoffRenderer
from ..presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
)
from ..presentation.visualization.pdf.services.pdf_rendering_service import (
    PDFRenderingService,
)
from ..presentation.visualization.services.color_service import ColorService
from .app_paths import get_default_working_dir
from .database.descriptor_registry import DatabaseDescriptorRegistry
from .database.reader_router import DatabaseProjectReader
from .database.writer_router import DatabaseProjectWriter
from .external.license_api_client import LicenseApiClient
from .hardware.hwid_generator import HWIDGenerator
from .mdb.connection_manager import MdbConnectionManager
from .mdb.database_creator import DatabaseCreator
from .mdb.exporters.ost_exporter import OstExporter
from .mdb.importers.osp_importer import OspImporter
from .mdb.importers.ost_importer import OstImporter
from .mdb.mdb_reader import MdbReader
from .monitoring.transaction_monitor import TransactionMonitor
from .persistence.repositories.file_project_repository import (
    FileProjectRepository,
    MdbFileParser,
)
from .persistence.repositories.json_config_repository import JsonConfigRepository
from .persistence.repositories.json_file_state_repository import JsonFileStateRepository
from .persistence.repositories.json_license_repository import JsonLicenseRepository
from .persistence.repositories.json_workspace_state_repository import (
    JsonWorkspaceStateRepository,
)
from .security.license_signature_verifier import LicenseSignatureVerifier
from .services.license_validation_scheduler import LicenseValidationScheduler
from .sql.catalog import SqlDatabaseCatalog
from .sql.credential_store import WindowsCredentialStore
from .sql.database_creator import SqlDatabaseCreator
from .sql.permissions import SqlDatabasePermissionProbe
from .visualization_provider import VisualizationProvider


class RepositoryProvider(IRepositoryProvider):
    def __init__(
        self,
        logger: logging.Logger,
        descriptor_registry: Optional[IDatabaseDescriptorRegistry] = None,
        project_reader_factory: Optional[
            Callable[[Optional[IMdbConnectionManager]], IMdbReader]
        ] = None,
    ):
        self.logger = logger
        self._hwid_generator = HWIDGenerator()
        self._descriptor_registry = descriptor_registry
        self._project_reader_factory = project_reader_factory

    def get_config_repository(self) -> IConfigRepository:
        return JsonConfigRepository(logger=self.logger.getChild("ConfigRepository"))

    def get_file_state_repository(self) -> IFileStateRepository:
        return JsonFileStateRepository(
            logger=self.logger.getChild("FileStateRepository")
        )

    def get_workspace_state_repository(self) -> IWorkspaceStateRepository:
        return JsonWorkspaceStateRepository(
            logger=self.logger.getChild("WorkspaceStateRepository")
        )

    def get_license_repository(self) -> ILicenseRepository:
        return JsonLicenseRepository(logger=self.logger.getChild("LicenseRepository"))

    def get_license_signature_verifier(self) -> ILicenseSignatureVerifier:
        return LicenseSignatureVerifier(
            logger=self.logger.getChild("LicenseSignatureVerifier")
        )

    def get_project_repository(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IProjectRepository:
        file_manager_logger = self.logger.getChild("FileManager")
        parser_logger = file_manager_logger.getChild("MdbFileParser")
        if self._project_reader_factory is not None:
            reader = self._project_reader_factory(conn_manager)
        else:
            reader = MdbReader(conn_manager=conn_manager, logger=parser_logger)
        parser = MdbFileParser(logger=parser_logger, parser=reader)
        return FileProjectRepository(
            parser=parser,
            logger=file_manager_logger.getChild("Repository"),
            descriptor_registry=self._descriptor_registry,
        )

    def get_hwid_provider(self) -> Callable[[], str]:
        return self._hwid_generator.get_hwid


class InfrastructureServiceProvider(IInfrastructureServiceProvider):
    def __init__(
        self,
        logger: logging.Logger,
        callback_bridge_factory: Callable[[], IThreadCallbackBridge],
        database_session_registry: IDatabaseSessionRegistry,
        icon_provider: Optional[IWindowIconProvider] = None,
        message_notifier: Optional[IMessageNotifier] = None,
        descriptor_registry: Optional[IDatabaseDescriptorRegistry] = None,
        credential_store: Optional[ICredentialStore] = None,
    ):
        self.logger = logger
        self._callback_bridge_factory = callback_bridge_factory
        self._icon_provider = icon_provider
        self._message_notifier = message_notifier
        self._descriptor_registry = (
            DatabaseDescriptorRegistry()
            if descriptor_registry is None
            else descriptor_registry
        )
        self._credential_store = (
            WindowsCredentialStore() if credential_store is None else credential_store
        )
        self._database_session_registry = database_session_registry
        self._database_readers: dict[int, IMdbReader] = {}
        self._database_writers: dict[int, IMdbWriter] = {}

    def create_license_validation_scheduler(
        self, interval_seconds: int
    ) -> ILicenseValidationScheduler:
        return LicenseValidationScheduler(
            interval_seconds=interval_seconds,
            logger=self.logger.getChild("LicenseValidationScheduler"),
        )

    def get_transaction_monitor(self) -> ITransactionMonitor:
        return TransactionMonitor(message_notifier=self._message_notifier)

    def get_icon_provider(self) -> Optional[IWindowIconProvider]:
        return self._icon_provider

    def get_thread_callback_bridge(self) -> IThreadCallbackBridge:
        return self._callback_bridge_factory()

    def get_takeoff_domain_service(self) -> ITakeoffDomainService:
        return TakeoffDomainService()

    def get_uom_service(self) -> IUOMService:
        return UOMDomainService()

    def get_visualization_provider(
        self, takeoff_service: ITakeoffDomainService
    ) -> IVisualizationProvider:
        return VisualizationProvider(takeoff_service)

    def get_coordinate_transformer_factory(self) -> ICoordinateTransformerFactory:
        return CoordinateTransformerFactory()

    def get_color_service(self) -> IColorService:
        return ColorService()

    def get_pdf_exporter(
        self,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
        uom_service: IUOMService,
        annotation_caption_resolver: IAnnotationCaptionResolver,
    ) -> IPDFExporter:
        return PDFExporter(
            coord_system,
            color_service,
            takeoff_service,
            uom_service,
            annotation_caption_resolver,
        )

    def get_ost_exporter(self, uom_service: IUOMService) -> IOstExporter:
        return OstExporter(uom_service)

    def get_ost_importer(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IOstImporter:
        writer = self.get_mdb_writer(conn_manager=conn_manager)
        return OstImporter(
            writer,
            mutation_executor=writer,
            session_registry=self._database_session_registry,
        )

    def get_osp_importer(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IOspImporter:
        return OspImporter(self.get_ost_importer(conn_manager=conn_manager))

    def create_connection_manager(self) -> MdbConnectionManager:
        return MdbConnectionManager()

    def get_pdf_page_sizes(self, path: str) -> list[tuple[float, float, str]]:
        sizes = []
        renderer = None
        opened = False
        try:
            renderer = _ost_pdf.PDFRenderer()
            opened = renderer.open(path)
            if opened:
                for pi in range(max(1, renderer.page_count())):
                    pts_w, pts_h = renderer.page_size(pi)
                    label = renderer.page_label(pi)
                    sizes.append((pts_w / 72.0, pts_h / 72.0, label))
        except Exception:
            self.logger.exception("Failed to read PDF page sizes for %s", path)
        finally:
            if opened and renderer is not None:
                renderer.close()
        return sizes

    def create_plan_view_renderers(
        self,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
    ) -> PlanViewRenderers:
        page_cache = PageCache()
        rendering_service = PDFRenderingService(page_cache, num_workers=1)
        load_coordinator = PageLoadStrategyService(page_cache)
        return PlanViewRenderers(
            page_cache=page_cache,
            rendering_service=rendering_service,
            load_coordinator=load_coordinator,
            prefetch_coordinator=PageRenderPrefetchCoordinator(
                rendering_service,
                load_coordinator,
                page_cache,
            ),
            takeoff_renderer=TakeoffRenderer(coord_system, color_service),
            annotation_renderer=AnnotationItemRenderer(coord_system),
            linear_geometry=LinearGeometry(),
        )

    def get_mdb_reader(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IMdbReader:
        resolved_manager = conn_manager or MdbConnectionManager()
        key = id(resolved_manager)
        reader = self._database_readers.get(key)
        if reader is None:
            reader = DatabaseProjectReader(
                resolved_manager,
                self._descriptor_registry,
                self._credential_store,
                logger=self.logger.getChild("DatabaseProjectReader"),
            )
            self._database_readers[key] = reader
        return reader

    def get_mdb_writer(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IMdbWriter:
        resolved_manager = conn_manager or MdbConnectionManager()
        key = id(resolved_manager)
        writer = self._database_writers.get(key)
        if writer is None:
            writer = DatabaseProjectWriter(
                resolved_manager,
                self._descriptor_registry,
                self._credential_store,
                self._database_session_registry,
                logger=self.logger.getChild("DatabaseProjectWriter"),
            )
            self._database_writers[key] = writer
        return writer

    def get_osp_exporter(self, uom_service: IUOMService, version: str) -> IOspExporter:
        return OspExporter(uom_service, version, self.get_ost_exporter)

    def get_database_creator(self) -> IDatabaseCreator:
        return DatabaseCreator()

    def get_database_catalog(self) -> IDatabaseCatalog:
        return SqlDatabaseCatalog()

    def get_credential_store(self) -> ICredentialStore:
        return self._credential_store

    def get_database_descriptor_registry(self) -> IDatabaseDescriptorRegistry:
        return self._descriptor_registry

    def get_sql_database_creator(self) -> ISqlDatabaseCreator:
        return SqlDatabaseCreator()

    def get_database_permission_probe(self) -> IDatabasePermissionProbe:
        return SqlDatabasePermissionProbe(
            self._descriptor_registry, self._credential_store
        )

    def get_default_working_dir(self) -> Path:
        return get_default_working_dir()


class ApiClientProvider(IApiClientProvider):
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def get_license_api_client(self) -> ILicenseApiClient:
        return LicenseApiClient(logger=self.logger.getChild("LicenseApiClient"))
