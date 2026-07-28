from typing import Optional, Tuple
from PySide6.QtGui import QBrush, QColor, QPen

STANDARD_HANDLE_FILL_HEX = "#ffffff"
STANDARD_HANDLE_FILL_RGB = (255, 255, 255)
STANDARD_HANDLE_OUTLINE_RGB = (0, 0, 0)
TAKEOFF_HANDLE_FILL = QColor(*STANDARD_HANDLE_FILL_RGB, 224)
TAKEOFF_HANDLE_OUTLINE = QColor(*STANDARD_HANDLE_OUTLINE_RGB)


def handle_colors_for_background(_background: QColor) -> Tuple[QColor, QColor]:
    return QColor(TAKEOFF_HANDLE_FILL), QColor(TAKEOFF_HANDLE_OUTLINE)


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
