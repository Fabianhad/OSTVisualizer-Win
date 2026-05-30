from typing import List, Protocol
from ..dtos.pdf_metadata_dtos import PdfPageInfoDto, PdfTextRunDto, PdfVectorSegmentDto


class IPdfMetadataProvider(Protocol):
    def get_page_info(self, file_path: str, page_index: int) -> PdfPageInfoDto: ...
    def get_text_runs(self, file_path: str, page_index: int) -> List[PdfTextRunDto]: ...
    def get_vector_segments(
        self, file_path: str, page_index: int
    ) -> List[PdfVectorSegmentDto]: ...
