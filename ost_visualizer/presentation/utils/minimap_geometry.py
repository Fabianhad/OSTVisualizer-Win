from PySide6.QtCore import QPointF, QRectF, QSizeF


def _is_degenerate(rect: QRectF) -> bool:
    return rect.width() <= 0.0 or rect.height() <= 0.0


def fit_rect(source: QRectF, target: QRectF) -> QRectF:
    if _is_degenerate(source) or _is_degenerate(target):
        return QRectF()
    scale = min(target.width() / source.width(), target.height() / source.height())
    width = source.width() * scale
    height = source.height() * scale
    return QRectF(
        target.x() + (target.width() - width) / 2.0,
        target.y() + (target.height() - height) / 2.0,
        width,
        height,
    )


def scene_to_map_rect(scene_rect: QRectF, source: QRectF, map_rect: QRectF) -> QRectF:
    if _is_degenerate(source) or _is_degenerate(map_rect):
        return QRectF()
    clipped = scene_rect.intersected(source)
    if _is_degenerate(clipped):
        return QRectF()
    scale_x = map_rect.width() / source.width()
    scale_y = map_rect.height() / source.height()
    return QRectF(
        map_rect.x() + (clipped.x() - source.x()) * scale_x,
        map_rect.y() + (clipped.y() - source.y()) * scale_y,
        clipped.width() * scale_x,
        clipped.height() * scale_y,
    )


def map_to_scene_point(point: QPointF, source: QRectF, map_rect: QRectF) -> QPointF:
    if _is_degenerate(source) or _is_degenerate(map_rect):
        return source.center()
    x = min(max(point.x(), map_rect.left()), map_rect.right())
    y = min(max(point.y(), map_rect.top()), map_rect.bottom())
    return QPointF(
        source.x() + (x - map_rect.x()) * source.width() / map_rect.width(),
        source.y() + (y - map_rect.y()) * source.height() / map_rect.height(),
    )


def _clamp_axis(value: float, low: float, high: float, extent: float) -> float:
    half = extent / 2.0
    if extent >= high - low:
        return (low + high) / 2.0
    return min(max(value, low + half), high - half)


def clamp_center(center: QPointF, source: QRectF, visible_size: QSizeF) -> QPointF:
    return QPointF(
        _clamp_axis(center.x(), source.left(), source.right(), visible_size.width()),
        _clamp_axis(center.y(), source.top(), source.bottom(), visible_size.height()),
    )


def center_for_click(
    point: QPointF, source: QRectF, map_rect: QRectF, visible_size: QSizeF
) -> QPointF:
    scene_point = map_to_scene_point(point, source, map_rect)
    return clamp_center(scene_point, source, visible_size)


def grab_offset(
    point: QPointF, source: QRectF, map_rect: QRectF, view_center: QPointF
) -> QPointF:
    return map_to_scene_point(point, source, map_rect) - view_center


def drag_center(
    point: QPointF,
    offset: QPointF,
    source: QRectF,
    map_rect: QRectF,
    visible_size: QSizeF,
) -> QPointF:
    return clamp_center(
        map_to_scene_point(point, source, map_rect) - offset, source, visible_size
    )
