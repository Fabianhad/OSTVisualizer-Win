from typing import Dict, List, Optional, Protocol
from ..dtos.annotation_caption_dto import AnnotationCaptionSettingsDto
from ..dtos.export_dto import ExportProgressCallback, ExportResultDto
from ...domain.entities.annotation import BidAnnotation
from ..dtos.page_export_data_dto import PageExportData


class IPDFExporter(Protocol):
    def export(
        self,
        pages_data: List[PageExportData],
        output_path: str,
        display_mode: str,
        grayscale_enabled: bool,
        caption_settings: AnnotationCaptionSettingsDto,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        bid_annotations: Optional[List[BidAnnotation]] = None,
        on_progress: Optional[ExportProgressCallback] = None,
    ) -> ExportResultDto: ...
