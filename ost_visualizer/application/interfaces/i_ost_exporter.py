from typing import Protocol
from ...domain.dtos.raw_bid_data_dto import RawBidData


class IOstExporter(Protocol):
    def export(self, raw_data: RawBidData, output_path: str) -> bool: ...
