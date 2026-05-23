from typing import Dict, List, Optional, Protocol
from ...domain.entities.annotation import BidAnnotation
from ..dtos.page_export_data_dto import PageExportData


class IPDFExporter(Protocol):
    def export(
        self,
        pages_data: List[PageExportData],
        output_path: str,
        color_mode: str,
        grayscale_enabled: bool,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        bid_annotations: Optional[List[BidAnnotation]] = None,
    ) -> bool: ...
