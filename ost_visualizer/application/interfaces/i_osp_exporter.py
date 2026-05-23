from typing import Protocol
from ...domain.dtos.raw_bid_data_dto import RawBidData
from ..dtos.export_dto import ExportResultDto


class IOspExporter(Protocol):
    def export(
        self,
        raw_data: RawBidData,
        output_file: str,
        bid_name: str = "Bid",
    ) -> ExportResultDto: ...
