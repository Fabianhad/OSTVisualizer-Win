import importlib
import logging
import threading
from pathlib import Path
from typing import Callable, Dict, List, Tuple
from ..application.dtos.pdf_metadata_dtos import (
    PdfPageInfoDto,
    PdfTextRunDto,
    PdfVectorSegmentDto,
)


class NativePdfMetadataProvider:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        renderer_factory: Callable | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._renderer_factory = renderer_factory or self._load_renderer_factory()
        self._lock = threading.Lock()
        self._page_info_cache: Dict[Tuple[str, int], PdfPageInfoDto] = {}
        self._text_runs_cache: Dict[Tuple[str, int], List[PdfTextRunDto]] = {}
        self._segments_cache: Dict[Tuple[str, int], List[PdfVectorSegmentDto]] = {}

    @staticmethod
    def _load_renderer_factory() -> Callable:
        module = importlib.import_module(
            "ost_visualizer.presentation.visualization.pdf.ost_pdf"
        )
        return module.PDFRenderer

    def get_page_info(self, file_path: str, page_index: int) -> PdfPageInfoDto:
        key = (str(file_path or ""), int(page_index or 0))
        with self._lock:
            cached = self._page_info_cache.get(key)
            if cached is not None:
                return cached
        info = self._read_page_info(key[0], key[1])
        with self._lock:
            self._page_info_cache[key] = info
        return info

    def get_text_runs(self, file_path: str, page_index: int) -> List[PdfTextRunDto]:
        key = (str(file_path or ""), int(page_index or 0))
        with self._lock:
            cached = self._text_runs_cache.get(key)
            if cached is not None:
                return list(cached)
        runs = self._read_text_runs(key[0], key[1])
        with self._lock:
            self._text_runs_cache[key] = list(runs)
        return list(runs)

    def get_vector_segments(
        self, file_path: str, page_index: int
    ) -> List[PdfVectorSegmentDto]:
        key = (str(file_path or ""), int(page_index or 0))
        with self._lock:
            cached = self._segments_cache.get(key)
            if cached is not None:
                return list(cached)
        segments = self._read_vector_segments(key[0], key[1])
        with self._lock:
            self._segments_cache[key] = list(segments)
        return list(segments)

    def _read_page_info(self, file_path: str, page_index: int) -> PdfPageInfoDto:
        path = Path(file_path)
        if not file_path:
            return PdfPageInfoDto(status="not_configured")
        if path.suffix.lower() != ".pdf":
            return PdfPageInfoDto(status="not_pdf")
        if not path.exists() or not path.is_file():
            return PdfPageInfoDto(status="missing")
        renderer = self._renderer_factory()
        opened = False
        try:
            opened = bool(renderer.open(file_path))
            if not opened:
                return PdfPageInfoDto(status="unavailable")
            page_count = int(renderer.page_count())
            clean_index = self._clean_page_index(page_index, page_count)
            native_info = renderer.page_info(clean_index)
            if native_info is None:
                return PdfPageInfoDto(status="unavailable", page_count=page_count)
            return PdfPageInfoDto(
                status="ok",
                page_count=page_count,
                effective_width_pts=float(native_info.effective_width_pts),
                effective_height_pts=float(native_info.effective_height_pts),
                media_width_pts=float(native_info.media_width_pts),
                media_height_pts=float(native_info.media_height_pts),
                crop_width_pts=float(native_info.crop_width_pts),
                crop_height_pts=float(native_info.crop_height_pts),
                intrinsic_rotation=int(native_info.intrinsic_rotation),
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._logger.warning("Failed to read PDF page info: %s", type(exc).__name__)
            return PdfPageInfoDto(status="unavailable")
        finally:
            if opened:
                renderer.close()

    def _read_text_runs(self, file_path: str, page_index: int) -> List[PdfTextRunDto]:
        path = Path(file_path)
        if not file_path or path.suffix.lower() != ".pdf":
            return []
        if not path.exists() or not path.is_file():
            return []
        renderer = self._renderer_factory()
        opened = False
        try:
            opened = bool(renderer.open(file_path))
            if not opened:
                return []
            clean_index = self._clean_page_index(page_index, int(renderer.page_count()))
            runs: List[PdfTextRunDto] = []
            for native_run in renderer.extract_text_runs(clean_index):
                try:
                    runs.append(
                        PdfTextRunDto(
                            text=str(native_run.text or ""),
                            left=float(native_run.left),
                            top=float(native_run.top),
                            right=float(native_run.right),
                            bottom=float(native_run.bottom),
                        )
                    )
                except (AttributeError, TypeError, ValueError):
                    continue
            return runs
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._logger.warning("Failed to read PDF text runs: %s", type(exc).__name__)
            return []
        finally:
            if opened:
                renderer.close()

    def _read_vector_segments(
        self, file_path: str, page_index: int
    ) -> List[PdfVectorSegmentDto]:
        path = Path(file_path)
        if not file_path or path.suffix.lower() != ".pdf":
            return []
        if not path.exists() or not path.is_file():
            return []
        renderer = self._renderer_factory()
        opened = False
        try:
            opened = bool(renderer.open(file_path))
            if not opened:
                return []
            clean_index = self._clean_page_index(page_index, int(renderer.page_count()))
            segments: List[PdfVectorSegmentDto] = []
            for x1, y1, x2, y2 in renderer.extract_path_segments(clean_index):
                segments.append(
                    PdfVectorSegmentDto(
                        x1=float(x1),
                        y1=float(y1),
                        x2=float(x2),
                        y2=float(y2),
                    )
                )
            return segments
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._logger.warning(
                "Failed to read PDF vector segments: %s", type(exc).__name__
            )
            return []
        finally:
            if opened:
                renderer.close()

    @staticmethod
    def _clean_page_index(page_index: int, page_count: int) -> int:
        if page_count <= 0:
            return 0
        return max(0, min(int(page_index or 0), page_count - 1))
