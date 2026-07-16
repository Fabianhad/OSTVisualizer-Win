from pathlib import Path
from typing import List, Optional, Protocol, Tuple
from ..dtos.plan_view_renderers_dto import PlanViewRenderers
from .i_color_service import IColorService
from .i_annotation_caption_resolver import IAnnotationCaptionResolver
from .i_coordinate_transformer import ICoordinateTransformer
from .i_coordinate_transformer_factory import ICoordinateTransformerFactory
from .i_database_creator import IDatabaseCreator
from .i_license_validation_scheduler import ILicenseValidationScheduler
from .i_mdb_connection_manager import IMdbConnectionManager
from .i_mdb_reader import IMdbReader
from .i_mdb_writer import IMdbWriter
from .i_osp_exporter import IOspExporter
from .i_osp_importer import IOspImporter
from .i_ost_exporter import IOstExporter
from .i_ost_importer import IOstImporter
from .i_pdf_exporter import IPDFExporter
from .i_takeoff_domain_service import ITakeoffDomainService
from .i_thread_callback_bridge import IThreadCallbackBridge
from .i_transaction_monitor import ITransactionMonitor
from .i_uom_service import IUOMService
from .i_visualization_provider import IVisualizationProvider
from .i_window_icon_provider import IWindowIconProvider


class IInfrastructureServiceProvider(Protocol):
    def create_license_validation_scheduler(
        self, interval_seconds: int
    ) -> ILicenseValidationScheduler: ...
    def get_transaction_monitor(self) -> ITransactionMonitor: ...
    def get_thread_callback_bridge(self) -> IThreadCallbackBridge: ...
    def get_icon_provider(self) -> Optional[IWindowIconProvider]: ...
    def get_visualization_provider(
        self, takeoff_service: ITakeoffDomainService
    ) -> IVisualizationProvider: ...
    def get_coordinate_transformer_factory(self) -> ICoordinateTransformerFactory: ...
    def get_color_service(self) -> IColorService: ...
    def get_takeoff_domain_service(self) -> ITakeoffDomainService: ...
    def get_uom_service(self) -> IUOMService: ...
    def get_pdf_exporter(
        self,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
        uom_service: IUOMService,
        annotation_caption_resolver: IAnnotationCaptionResolver,
    ) -> IPDFExporter: ...
    def get_ost_exporter(self, uom_service: IUOMService) -> IOstExporter: ...
    def get_ost_importer(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IOstImporter: ...
    def get_osp_importer(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IOspImporter: ...
    def get_mdb_reader(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IMdbReader: ...
    def get_mdb_writer(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IMdbWriter: ...
    def create_connection_manager(self) -> IMdbConnectionManager: ...
    def create_plan_view_renderers(
        self,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
    ) -> PlanViewRenderers: ...
    def get_pdf_page_sizes(self, path: str) -> List[Tuple[float, float, str]]: ...
    def get_osp_exporter(
        self, uom_service: IUOMService, version: str
    ) -> IOspExporter: ...
    def get_database_creator(self) -> IDatabaseCreator: ...
    def get_default_working_dir(self) -> Path: ...
