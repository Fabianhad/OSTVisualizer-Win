from typing import Optional, Protocol
from ...domain.dtos.raw_bid_data_dto import RawBidData
from ..dtos.export_dto import ExportProgressCallback, ExportResultDto


class IOstExporter(Protocol):
    def export(
        self,
        raw_data: RawBidData,
        output_path: str,
        on_progress: Optional[ExportProgressCallback] = None,
    ) -> ExportResultDto: ...
