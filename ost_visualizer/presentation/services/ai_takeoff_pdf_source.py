import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from PySide6.QtGui import QImage
from ...application.dtos.pdf_metadata_dtos import (
    PdfPageInfoDto,
    PdfPathStyleDto,
    PdfTextRunDto,
    PdfVectorSegmentDto,
    PdfVectorSegmentsDto,
)
from ...domain.entities.file_extensions import is_pdf_suffix
from ..visualization.exporters import ost_pdf_writer
from ..visualization.pdf import ost_pdf
from ..visualization.pdf.page_cache import PageCache
from ..visualization.pdf.pdf_visible_origin import read_visible_box_origin
from ..visualization.pdf.pdfium_lock import pdfium_lock

logger = logging.getLogger(__name__)
MAX_PAGE_PATH_ITEMS = 250000
PATH_CACHE_PAGES = 2


class PageCachePdfSource:
    def __init__(
        self,
        page_cache: PageCache,
        renderer_factory: Callable = ost_pdf.PDFRenderer,
        geometry_reader_factory: Callable = ost_pdf_writer.PDFWriter,
    ):
        self._page_cache = page_cache
        self._renderer_factory = renderer_factory
        self._geometry_reader_factory = geometry_reader_factory
        self._paths: "OrderedDict[tuple, PdfVectorSegmentsDto]" = OrderedDict()
        self._paths_lock = threading.Lock()

    def release(self) -> None:
        with self._paths_lock:
            self._paths.clear()
        self._page_cache.clear()

    def get_page_info(self, file_path: str, page_index: int) -> PdfPageInfoDto:
        status = _file_status(file_path)
        if status is not None:
            return PdfPageInfoDto(status=status)
        info = self._page_cache.get_page_info(file_path, page_index)
        width = float(info.get("pdf_width") or 0.0)
        height = float(info.get("pdf_height") or 0.0)
        if width <= 0.0 or height <= 0.0:
            return PdfPageInfoDto(status="unavailable")
        return PdfPageInfoDto(
            status="ok",
            effective_width_pts=width,
            effective_height_pts=height,
            media_width_pts=float(info.get("media_width_pts") or 0.0),
            media_height_pts=float(info.get("media_height_pts") or 0.0),
            crop_width_pts=float(info.get("crop_width_pts") or 0.0),
            crop_height_pts=float(info.get("crop_height_pts") or 0.0),
            intrinsic_rotation=int(info.get("intrinsic_rotation") or 0),
        )

    def get_text_runs(self, file_path: str, page_index: int) -> List[PdfTextRunDto]:
        if _file_status(file_path) is not None:
            return []
        origin_x, origin_y = self._visible_origin(file_path, page_index)
        return [
            PdfTextRunDto(
                text=str(run.text),
                left=float(run.left) - origin_x,
                top=float(run.top) - origin_y,
                right=float(run.right) - origin_x,
                bottom=float(run.bottom) - origin_y,
            )
            for run in self._page_cache.get_text_runs(file_path, page_index)
        ]

    def get_vector_segments(
        self, file_path: str, page_index: int
    ) -> List[PdfVectorSegmentDto]:
        return list(self.get_path_segments(file_path, page_index).segments)

    def get_path_segments(
        self, file_path: str, page_index: int
    ) -> PdfVectorSegmentsDto:
        if _file_status(file_path) is not None:
            return PdfVectorSegmentsDto()
        key = _cache_key(file_path, page_index)
        with self._paths_lock:
            cached = self._paths.get(key)
            if cached is not None:
                self._paths.move_to_end(key)
                return cached
        extraction = self._extract(file_path, page_index)
        if extraction is None:
            return PdfVectorSegmentsDto()
        origin_x, origin_y = self._visible_origin(file_path, page_index)
        styles: Dict[tuple, PdfPathStyleDto] = {}
        segments = tuple(
            PdfVectorSegmentDto(
                float(item.x1) - origin_x,
                float(item.y1) - origin_y,
                float(item.x2) - origin_x,
                float(item.y2) - origin_y,
                segment_id=f"o{item.object_id}s{item.segment_index}",
                group=f"{item.object_id}:{item.subpath_index}",
                curve=bool(item.curve),
                closed=bool(item.closed),
                style=_style(item, styles),
            )
            for item in extraction.items
        )
        result = PdfVectorSegmentsDto(segments, bool(extraction.truncated))
        with self._paths_lock:
            self._paths[key] = result
            while len(self._paths) > PATH_CACHE_PAGES:
                self._paths.popitem(last=False)
        return result

    def _extract(self, file_path: str, page_index: int):
        renderer = self._renderer_factory()
        opened = False
        try:
            with pdfium_lock:
                opened = bool(renderer.open(file_path))
                if not opened:
                    return None
                return renderer.extract_path_items(page_index, MAX_PAGE_PATH_ITEMS)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("PDF vector extraction failed: %s", type(exc).__name__)
            return None
        finally:
            if opened:
                with pdfium_lock:
                    renderer.close()

    def _visible_origin(self, file_path: str, page_index: int) -> tuple:
        return read_visible_box_origin(
            file_path, page_index, self._geometry_reader_factory
        )

    def render_frame(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        frame_pts: tuple,
    ) -> Optional[QImage]:
        if _file_status(file_path) is not None:
            return None
        left, top, width, height = frame_pts
        return self._page_cache.get_frame(
            file_path, page_index, scale, left, top, width, height, 0
        )


def _cache_key(file_path: str, page_index: int) -> Tuple:
    stat = Path(file_path).stat()
    return (str(file_path), int(page_index), stat.st_mtime_ns, stat.st_size)


def _style(item, styles: Dict[tuple, PdfPathStyleDto]) -> PdfPathStyleDto:
    key = (
        float(item.stroke_width),
        tuple(float(value) for value in item.dash),
        int(item.stroke_rgba),
        int(item.fill_rgba),
        bool(item.stroked),
        bool(item.filled),
    )
    style = styles.get(key)
    if style is None:
        style = PdfPathStyleDto(*key)
        styles[key] = style
    return style


def _file_status(file_path: str) -> Optional[str]:
    if not file_path:
        return "not_configured"
    path = Path(file_path)
    if not is_pdf_suffix(path.suffix):
        return "not_pdf"
    if not path.is_file():
        return "missing"
    return None
