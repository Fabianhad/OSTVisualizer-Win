import logging
import os
from pathlib import Path
from typing import Dict, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader
from .....domain.entities.file_extensions import (
    TIFF_EXTENSIONS,
    is_pdf_suffix,
)
from .. import ost_pdf
from ..pdfium_lock import pdfium_lock

logger = logging.getLogger(__name__)


class PageRenderer:
    IMAGE_EXTENSIONS = TIFF_EXTENSIONS
    _pdfium_lock = pdfium_lock

    def __init__(self):
        self._pdf_renderer = None
        self._current_pdf_path: Optional[str] = None
        self._current_pdf_signature: Optional[tuple[int, int]] = None

    @staticmethod
    def _file_signature(file_path: str) -> Optional[tuple[int, int]]:
        try:
            stat = os.stat(file_path)
        except OSError:
            return None
        return int(stat.st_mtime_ns), int(stat.st_size)

    def _ensure_pdf_open_locked(self, file_path: str):
        renderer = self._get_pdf_renderer()
        if not renderer:
            logger.error("PDF rendering not available")
            return None
        file_signature = self._file_signature(file_path)
        if (
            self._current_pdf_path == file_path
            and self._current_pdf_signature == file_signature
        ):
            return renderer
        renderer.close()
        self._current_pdf_path = None
        self._current_pdf_signature = None
        if not renderer.open(file_path):
            path_obj = Path(file_path)
            pdfium_error = renderer.get_last_error()
            if not path_obj.exists():
                logger.error(f"Failed to open PDF (file not found): {file_path}")
            elif not path_obj.is_file():
                logger.error(f"Failed to open PDF (not a file): {file_path}")
            else:
                file_size = path_obj.stat().st_size
                logger.error(
                    f"Failed to open PDF ({pdfium_error}, size={file_size}): {file_path}"
                )
            return None
        self._current_pdf_path = file_path
        self._current_pdf_signature = file_signature
        return renderer

    def _get_pdf_renderer(self):
        if self._pdf_renderer is None:
            self._pdf_renderer = ost_pdf.PDFRenderer()
        return self._pdf_renderer

    def render(
        self,
        file_path: str,
        page_index: int = 0,
        scale: float = 1.0,
        rotation: int = 0,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return None
        ext = path.suffix.lower()
        if is_pdf_suffix(ext):
            return self._render_pdf(file_path, page_index, scale, rotation)
        elif ext in self.IMAGE_EXTENSIONS:
            return self._render_image(file_path, scale)
        else:
            logger.warning(f"Unsupported file type: {ext}")
            return None

    def _render_pdf(
        self, file_path: str, page_index: int, scale: float, rotation: int
    ) -> Optional[QImage]:
        with self._pdfium_lock:
            renderer = self._ensure_pdf_open_locked(file_path)
            if not renderer:
                return None
            page_count = renderer.page_count()
            if page_index < 0 or page_index >= page_count:
                page_index = max(0, min(page_index, page_count - 1))
            result = renderer.render_page(page_index, scale, rotation)
        if not result:
            logger.error(f"Failed to render PDF page {page_index}")
            return None
        data = result.to_bytes()
        qimage = QImage(
            data,
            result.width,
            result.height,
            result.stride,
            QImage.Format.Format_ARGB32,
        )
        return qimage.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    def _render_image(
        self,
        file_path: str,
        scale: float,
    ) -> Optional[QImage]:
        QImageReader.setAllocationLimit(0)
        reader = QImageReader(file_path)
        image = reader.read()
        if image.isNull():
            logger.error(f"Failed to load image: {file_path} - {reader.errorString()}")
            return None
        if scale != 1.0:
            new_width = int(image.width() * scale)
            new_height = int(image.height() * scale)
            image = image.scaled(
                new_width,
                new_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return image

    def render_frame(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        rotation: int = 0,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        path = Path(file_path)
        if not path.exists() or not is_pdf_suffix(path.suffix):
            return None
        with self._pdfium_lock:
            renderer = self._ensure_pdf_open_locked(file_path)
            if not renderer:
                return None
            result = renderer.render_page_frame(
                page_index,
                scale,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
                rotation,
            )
        if not result:
            return None
        data = result.to_bytes()
        qimage = QImage(
            data,
            result.width,
            result.height,
            result.stride,
            QImage.Format.Format_ARGB32,
        )
        return qimage.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    def get_page_count(self, file_path: str) -> int:
        path = Path(file_path)
        if not path.exists() or not is_pdf_suffix(path.suffix):
            return 1
        with self._pdfium_lock:
            renderer = self._ensure_pdf_open_locked(file_path)
            if not renderer:
                return 1
            return renderer.page_count()

    def get_page_size(self, file_path: str, page_index: int = 0) -> tuple:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"get_page_size: File not found: {file_path}")
            return (0.0, 0.0)
        if is_pdf_suffix(path.suffix):
            with self._pdfium_lock:
                renderer = self._ensure_pdf_open_locked(file_path)
                if not renderer:
                    return (0.0, 0.0)
                return renderer.page_size(page_index)
        else:
            reader = QImageReader(file_path)
            size = reader.size()
            if size.isValid():
                return (float(size.width()), float(size.height()))
            return (0.0, 0.0)

    def get_page_info(self, file_path: str, page_index: int = 0) -> Dict:
        info = {
            "pdf_width": 0.0,
            "pdf_height": 0.0,
            "media_width_pts": 0.0,
            "media_height_pts": 0.0,
            "crop_width_pts": 0.0,
            "crop_height_pts": 0.0,
            "intrinsic_rotation": 0,
        }
        path = Path(file_path)
        if not path.exists():
            return info
        if is_pdf_suffix(path.suffix):
            with self._pdfium_lock:
                renderer = self._ensure_pdf_open_locked(file_path)
                if not renderer:
                    return info
                page_info = renderer.page_info(page_index)
            if not page_info:
                return info
            info["pdf_width"] = page_info.effective_width_pts
            info["pdf_height"] = page_info.effective_height_pts
            info["media_width_pts"] = page_info.media_width_pts
            info["media_height_pts"] = page_info.media_height_pts
            info["crop_width_pts"] = page_info.crop_width_pts
            info["crop_height_pts"] = page_info.crop_height_pts
            info["intrinsic_rotation"] = page_info.intrinsic_rotation
        else:
            width, height = self.get_page_size(file_path, page_index)
            info["pdf_width"] = width
            info["pdf_height"] = height
        return info

    def extract_text_runs(self, file_path: str, page_index: int = 0) -> list:
        path = Path(file_path)
        if not path.exists() or not is_pdf_suffix(path.suffix):
            return []
        with self._pdfium_lock:
            renderer = self._ensure_pdf_open_locked(file_path)
            if not renderer:
                return []
            return list(renderer.extract_text_runs(page_index))

    def close(self):
        with self._pdfium_lock:
            if self._pdf_renderer:
                self._pdf_renderer.close()
                self._pdf_renderer = None
            self._current_pdf_path = None
            self._current_pdf_signature = None
