from PySide6.QtGui import QColor, QImage, QPainter
from ..utils import ost_image


def tint_image(image: QImage, r: int, g: int, b: int) -> QImage:
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    w = gray.width()
    h = gray.height()
    gray_data = bytes(gray.constBits())
    result = ost_image.tint_grayscale(gray_data, w, h, r, g, b, 235)
    return QImage(result.to_bytes(), w, h, QImage.Format.Format_ARGB32).copy()


def invert_image(image: QImage) -> QImage:
    inverted = image.copy()
    inverted.invertPixels(QImage.InvertMode.InvertRgb)
    return inverted


def bitonal_image(image: QImage) -> QImage:
    result = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Darken)
    painter.fillRect(result.rect(), QColor(220, 220, 220))
    painter.end()
    return result


def page_effect_paper_color(*, invert: bool = False, bitonal: bool = False) -> QColor:
    r, g, b = (220, 220, 220) if bitonal else (255, 255, 255)
    if invert:
        r, g, b = 255 - r, 255 - g, 255 - b
    return QColor(r, g, b)


def apply_page_image_effects(
    image: QImage, *, invert: bool = False, bitonal: bool = False
) -> QImage:
    if not invert and not bitonal:
        return image
    result = image
    if bitonal:
        result = bitonal_image(result)
    if invert:
        result = invert_image(result)
    return result
