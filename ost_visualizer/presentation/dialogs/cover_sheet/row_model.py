from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
from ...utils.image_show_mode import SHOW_ORIGINAL, SHOW_OVERLAY

PdfPageSize = Tuple[float, float, str]


@dataclass
class CoverSheetPageRow:
    width: float
    height: float
    scale_factor1: float
    scale_factor2: float
    show_mode: int
    image_path: str
    overlay_path: str
    page_index: int
    multi_page_count: int
    revision: int = 0
    pdf_page_sizes: Optional[Tuple[PdfPageSize, ...]] = None
    metadata_signature: Optional[Tuple[int, int]] = None
    pending_metadata_request: Optional[Tuple[int, Tuple[int, int]]] = None

    def replace_image_path(self, path: str) -> None:
        if path == self.image_path:
            return
        self.image_path = path
        if not path:
            self.show_mode = SHOW_OVERLAY if self.overlay_path else SHOW_ORIGINAL
        elif not self.overlay_path:
            self.show_mode = SHOW_ORIGINAL
        self.revision += 1
        self.pdf_page_sizes = None
        self.metadata_signature = None
        self.pending_metadata_request = None

    def replace_overlay_path(self, path: str) -> None:
        self.overlay_path = path
        if not path:
            self.show_mode = SHOW_ORIGINAL
        elif not self.image_path:
            self.show_mode = SHOW_OVERLAY

    def apply_pdf_metadata(
        self,
        signature: Optional[Tuple[int, int]],
        page_sizes: Tuple[PdfPageSize, ...],
    ) -> None:
        self.pdf_page_sizes = page_sizes
        self.multi_page_count = len(page_sizes)
        self.metadata_signature = signature
        self.pending_metadata_request = None
