import math
from dataclasses import dataclass
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QGraphicsItem

_SMOOTHING_SCALE_TOLERANCE = 0.01


class _ImageGraphicsItem(QGraphicsItem):
    def __init__(
        self,
        image: QImage,
        rect: QRectF,
        source_rect: QRectF,
        smooth_when_not_upscaled: bool = True,
    ):
        super().__init__()
        self._image = image
        self._rect = rect
        self._source_rect = source_rect
        self._smooth_when_not_upscaled = smooth_when_not_upscaled

    def boundingRect(self) -> QRectF:
        return self._rect

    def clear_image(self) -> None:
        self._image = QImage()

    def _should_smooth_transform(self, painter: QPainter) -> bool:
        if self._smooth_when_not_upscaled:
            return True
        if self._image.width() <= 0 or self._image.height() <= 0:
            return False
        transform = painter.worldTransform()
        origin = transform.map(QPointF(0.0, 0.0))
        x_axis = transform.map(QPointF(1.0, 0.0))
        y_axis = transform.map(QPointF(0.0, 1.0))
        dpr = painter.device().devicePixelRatioF()
        x_scale = math.hypot(x_axis.x() - origin.x(), x_axis.y() - origin.y()) * dpr
        y_scale = math.hypot(y_axis.x() - origin.x(), y_axis.y() - origin.y()) * dpr
        x_device_pixels_per_image_pixel = (
            x_scale * self._rect.width() / self._image.width()
        )
        y_device_pixels_per_image_pixel = (
            y_scale * self._rect.height() / self._image.height()
        )
        min_crisp_ratio = 1.0 - _SMOOTHING_SCALE_TOLERANCE
        max_crisp_ratio = 1.0 + _SMOOTHING_SCALE_TOLERANCE
        return not (
            min_crisp_ratio <= x_device_pixels_per_image_pixel <= max_crisp_ratio
            and min_crisp_ratio <= y_device_pixels_per_image_pixel <= max_crisp_ratio
        )

    def paint(self, painter, _option, _widget=None):
        if not self._image.isNull():
            painter.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform,
                self._should_smooth_transform(painter),
            )
            painter.drawImage(
                self._rect,
                self._image,
                self._source_rect,
            )


class ImageBackgroundItem(_ImageGraphicsItem):
    def __init__(self, image: QImage, scene_width: float, scene_height: float):
        super().__init__(
            image,
            QRectF(0.0, 0.0, scene_width, scene_height),
            QRectF(0.0, 0.0, float(image.width()), float(image.height())),
        )


@dataclass(frozen=True)
class TileKey:
    col: int
    row: int
    scale: float


class TileGraphicsItem(_ImageGraphicsItem):
    def __init__(self, image: QImage, scene_rect: QRectF, source_rect: QRectF):
        super().__init__(
            image,
            scene_rect,
            source_rect=source_rect,
            smooth_when_not_upscaled=False,
        )
