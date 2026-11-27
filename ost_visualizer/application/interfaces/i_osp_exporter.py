from typing import Optional, Protocol
from ...domain.dtos.raw_bid_data_dto import RawBidData
from ..dtos.export_dto import ExportProgressCallback, ExportResultDto
from ...shared.texts import EXPORT_SERVICE_LABEL_BID


class IOspExporter(Protocol):
    def export(
        self,
        raw_data: RawBidData,
        output_file: str,
        bid_name: str = EXPORT_SERVICE_LABEL_BID,
        on_progress: Optional[ExportProgressCallback] = None,
    ) -> ExportResultDto: ...
