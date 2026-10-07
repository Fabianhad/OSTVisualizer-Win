import logging
from typing import Callable, Tuple
from ..exporters import ost_pdf_writer

logger = logging.getLogger(__name__)


def read_visible_box_origin(
    file_path: str,
    page_index: int,
    reader_factory: Callable = ost_pdf_writer.PDFWriter,
) -> Tuple[float, float]:
    try:
        geometries = reader_factory().get_page_geometries(file_path)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("PDF page geometry read failed: %s", type(exc).__name__)
        return 0.0, 0.0
    index = int(page_index or 0)
    if not 0 <= index < len(geometries):
        return 0.0, 0.0
    min_x, min_y = geometries[index].visible_box[:2]
    return float(min_x), float(min_y)
