from typing import Callable
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

BAND_PIXELS = 262144


def _band_rows(width: int) -> int:
    return max(1, BAND_PIXELS // max(1, width))


def _carry_metadata(source: QImage, result: QImage) -> QImage:
    result.setDotsPerMeterX(source.dotsPerMeterX())
    result.setDotsPerMeterY(source.dotsPerMeterY())
    result.setDevicePixelRatio(source.devicePixelRatio())
    result.setOffset(source.offset())
    result.setColorSpace(source.colorSpace())
    return result


def _apply_in_bands(
    image: QImage,
    target_format: QImage.Format,
    whole_image_operation: Callable[[QImage], QImage],
    band_operation: Callable[[QImage], QImage],
    region: QRect | None = None,
) -> QImage:
    if image.isNull():
        return QImage()
    left, first_row, width, height = (
        (0, 0, image.width(), image.height())
        if region is None
        else (region.x(), region.y(), region.width(), region.height())
    )
    if width * height <= BAND_PIXELS or image.colorCount() > 0:
        return whole_image_operation(image)
    result = QImage(width, height, target_format)
    destination = result.bits()
    stride = result.bytesPerLine()
    rows = _band_rows(width)
    for top in range(0, height, rows):
        count = min(rows, height - top)
        band = band_operation(image.copy(left, first_row + top, width, count))
        size = count * stride
        destination[top * stride : top * stride + size] = band.constBits()[:size]
    return _carry_metadata(image, result)


def convert_to_format(image: QImage, target_format: QImage.Format) -> QImage:
    return _apply_in_bands(
        image,
        target_format,
        lambda whole: whole.convertToFormat(target_format),
        lambda band: band.convertToFormat(target_format),
    )


def copy_image(image: QImage) -> QImage:
    return _apply_in_bands(
        image, image.format(), lambda whole: whole.copy(), lambda band: band
    )


def copy_region(image: QImage, x: int, y: int, width: int, height: int) -> QImage:
    return _apply_in_bands(
        image,
        image.format(),
        lambda whole: whole.copy(x, y, width, height),
        lambda band: band,
        QRect(x, y, width, height),
    )


def _invert_rgb(image: QImage) -> QImage:
    inverted = image.copy()
    inverted.invertPixels(QImage.InvertMode.InvertRgb)
    return inverted


def inverted_rgb(image: QImage) -> QImage:
    return _apply_in_bands(image, image.format(), _invert_rgb, _invert_rgb)


def _darken(image: QImage, color: QColor) -> QImage:
    result = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if result.isNull():
        return result
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Darken)
    painter.fillRect(result.rect(), color)
    painter.end()
    return result


def darkened_premultiplied(image: QImage, color: QColor) -> QImage:
    return _apply_in_bands(
        image,
        QImage.Format.Format_ARGB32_Premultiplied,
        lambda whole: _darken(whole, color),
        lambda band: _darken(band, color),
    )
