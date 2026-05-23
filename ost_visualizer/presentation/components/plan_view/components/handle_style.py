from typing import Optional, Tuple
from PySide6.QtGui import QBrush, QColor, QPen

TAKEOFF_HANDLE_LIGHT_FILL = QColor(255, 255, 255, 224)
TAKEOFF_HANDLE_LIGHT_OUTLINE = QColor(0, 0, 0)
TAKEOFF_HANDLE_DARK_FILL = QColor(0, 0, 0, 224)
TAKEOFF_HANDLE_DARK_OUTLINE = QColor(255, 255, 255)
_DARK_BACKGROUND_LUMINANCE_THRESHOLD = 128.0


def _relative_luminance(color: QColor) -> float:
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def handle_colors_for_background(background: QColor) -> Tuple[QColor, QColor]:
    if _relative_luminance(background) < _DARK_BACKGROUND_LUMINANCE_THRESHOLD:
        return QColor(TAKEOFF_HANDLE_LIGHT_FILL), QColor(TAKEOFF_HANDLE_LIGHT_OUTLINE)
    return QColor(TAKEOFF_HANDLE_DARK_FILL), QColor(TAKEOFF_HANDLE_DARK_OUTLINE)


def apply_takeoff_handle_style(
    item,
    background_color: Optional[QColor] = None,
    pen_width: float = 1.0,
) -> None:
    fill, outline = handle_colors_for_background(
        background_color if background_color is not None else QColor(255, 255, 255)
    )
    pen = QPen(outline)
    pen.setWidthF(pen_width)
    item.setPen(pen)
    item.setBrush(QBrush(fill))
