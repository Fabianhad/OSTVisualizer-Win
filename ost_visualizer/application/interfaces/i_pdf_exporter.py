from typing import Dict, List, Optional, Protocol
from ..dtos.annotation_caption_dto import AnnotationCaptionSettingsDto
from ..dtos.export_dto import ExportProgressCallback, ExportResultDto
from ...domain.entities.annotation import BidAnnotation
from ...domain.entities.config import Config
from ...domain.entities.elevation_callout import (
    DEFAULT_ELEVATION_CALLOUT_SETTINGS,
    ElevationCalloutSettings,
)
from ..dtos.page_export_data_dto import PageExportData


class IPDFExporter(Protocol):
    def export(
        self,
        pages_data: List[PageExportData],
        output_path: str,
        display_mode: str,
        grayscale_enabled: bool,
        caption_settings: AnnotationCaptionSettingsDto,
        elevation_callouts_enabled: bool,
        elevation_callout_settings: ElevationCalloutSettings = (
            DEFAULT_ELEVATION_CALLOUT_SETTINGS
        ),
        elevation_callout_color: str = Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        bid_annotations: Optional[List[BidAnnotation]] = None,
        on_progress: Optional[ExportProgressCallback] = None,
    ) -> ExportResultDto: ...
