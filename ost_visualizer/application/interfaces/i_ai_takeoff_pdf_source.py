from typing import Protocol
from ..dtos.pdf_metadata_dtos import PdfVectorSegmentsDto
from .i_pdf_metadata_provider import IPdfMetadataProvider


class IAiTakeoffPdfSource(IPdfMetadataProvider, Protocol):
    def get_path_segments(
        self, file_path: str, page_index: int
    ) -> PdfVectorSegmentsDto: ...
