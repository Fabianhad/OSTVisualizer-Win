from __future__ import annotations
from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from shiboken6 import isValid
from ..utils.minimap_geometry import (
    center_for_click,
    clamp_center,
    drag_center,
    fit_rect,
    grab_offset,
    scene_to_map_rect,
)

PAN_SIDEBAR_EMPTY_TEXT = "No page open"


class PanSidebar(QtWidgets.QWidget):
    THUMBNAIL_MAX_SIDE = 1024
    SCENE_REFRESH_DELAY_MS = 500
    LOAD_REFRESH_DELAY_MS = 0
    MARGIN = 6

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._plan_view = None
        self._thumbnail: Optional[QtGui.QImage] = None
        self._inverted: Optional[QtGui.QImage] = None
        self._render_count = 0
        self._stale = False
        self._dragging = False
        self._grab_offset = QPointF()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_if_stale)
        self.setMouseTracking(True)
        self.setMinimumHeight(80)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

    @property
    def thumbnail_render_count(self) -> int:
        return self._render_count

    def thumbnail(self) -> Optional[QtGui.QImage]:
        return self._thumbnail

    def bind_plan_view(self, plan_view) -> None:
        self.unbind_plan_view()
        self._plan_view = plan_view
        plan_view.horizontalScrollBar().valueChanged.connect(self._on_view_changed)
        plan_view.horizontalScrollBar().rangeChanged.connect(self._on_view_changed)
        plan_view.verticalScrollBar().valueChanged.connect(self._on_view_changed)
        plan_view.verticalScrollBar().rangeChanged.connect(self._on_view_changed)
        plan_view.zoom_changed.connect(self._on_view_changed)
        plan_view.page_geometry_ready.connect(self._on_page_loaded)
        plan_view.page_fully_loaded.connect(self._on_page_loaded)
        plan_view.page_cleared.connect(self._on_page_cleared)
        plan_view.scene().changed.connect(self._on_scene_changed)
        plan_view.destroyed.connect(self._on_plan_view_destroyed)
        plan_view.viewport().installEventFilter(self)
        self._schedule_refresh(self.LOAD_REFRESH_DELAY_MS)
        self.update()

    def unbind_plan_view(self) -> None:
        view = self._live_view()
        self._plan_view = None
        self._dragging = False
        self._refresh_timer.stop()
        self._discard_thumbnail()
        if view is not None:
            view.horizontalScrollBar().valueChanged.disconnect(self._on_view_changed)
            view.horizontalScrollBar().rangeChanged.disconnect(self._on_view_changed)
            view.verticalScrollBar().valueChanged.disconnect(self._on_view_changed)
            view.verticalScrollBar().rangeChanged.disconnect(self._on_view_changed)
            view.zoom_changed.disconnect(self._on_view_changed)
            view.page_geometry_ready.disconnect(self._on_page_loaded)
            view.page_fully_loaded.disconnect(self._on_page_loaded)
            view.page_cleared.disconnect(self._on_page_cleared)
            view.scene().changed.disconnect(self._on_scene_changed)
            view.destroyed.disconnect(self._on_plan_view_destroyed)
            view.viewport().removeEventFilter(self)
        self.unsetCursor()
        self.update()

    def _live_view(self):
        view = self._plan_view
        if view is None or not isValid(view):
            return None
        return view

    @property
    def has_page(self) -> bool:
        view = self._live_view()
        return (
            view is not None
            and bool(view.current_page_uid)
            and view.sceneRect().isValid()
            and not view.sceneRect().isEmpty()
        )

    @property
    def is_interactive(self) -> bool:
        view = self._live_view()
        return self.has_page and view.is_view_state_stable

    def _source_rect(self) -> QRectF:
        view = self._live_view()
        return view.sceneRect() if view is not None else QRectF()

    def map_rect(self) -> QRectF:
        if not self.has_page:
            return QRectF()
        area = QRectF(self.rect()).adjusted(
            self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN
        )
        return fit_rect(self._source_rect(), area)

    def _view_visible_rect(self) -> QRectF:
        view = self._live_view()
        if view is None:
            return QRectF()
        return view.mapToScene(view.viewport().rect()).boundingRect()

    def _displayed_view_rect(self) -> QRectF:
        view = self._live_view()
        if view is None or not self.has_page:
            return QRectF()
        if self.is_interactive:
            return self._view_visible_rect()
        predicted = view.predicted_visible_scene_rect()
        if predicted.isEmpty():
            return QRectF()
        center = clamp_center(predicted.center(), self._source_rect(), predicted.size())
        return QRectF(
            center.x() - predicted.width() / 2.0,
            center.y() - predicted.height() / 2.0,
            predicted.width(),
            predicted.height(),
        )

    def visible_map_rect(self) -> QRectF:
        return scene_to_map_rect(
            self._displayed_view_rect(), self._source_rect(), self.map_rect()
        )

    def _on_view_changed(self, *_args) -> None:
        self.update()

    def _on_page_loaded(self) -> None:
        self._schedule_refresh(self.LOAD_REFRESH_DELAY_MS)
        self.update()

    def _on_page_cleared(self) -> None:
        self._dragging = False
        self._refresh_timer.stop()
        self._discard_thumbnail()
        self.unsetCursor()
        self.update()

    def _on_scene_changed(self, *_args) -> None:
        if self._dragging:
            return
        self._schedule_refresh(self.SCENE_REFRESH_DELAY_MS)

    def _on_plan_view_destroyed(self, *_args) -> None:
        self._plan_view = None
        self._dragging = False
        self._refresh_timer.stop()
        self._discard_thumbnail()
        self.unsetCursor()
        self.update()

    def _discard_thumbnail(self) -> None:
        self._thumbnail = None
        self._inverted = None
        self._stale = False

    def _schedule_refresh(self, delay_ms: int) -> None:
        self._stale = True
        timer = self._refresh_timer
        if timer.isActive() and timer.remainingTime() <= delay_ms:
            return
        self._refresh_timer.start(delay_ms)

    def flush_scheduled_refresh(self) -> None:
        self._refresh_timer.stop()
        self._refresh_if_stale()

    def _refresh_if_stale(self) -> None:
        if self._stale:
            self.refresh_thumbnail()

    def _thumbnail_size(self, map_rect: QRectF) -> QtCore.QSize:
        ratio = self.devicePixelRatioF()
        width = max(1, round(map_rect.width() * ratio))
        height = max(1, round(map_rect.height() * ratio))
        largest = max(width, height)
        if largest > self.THUMBNAIL_MAX_SIDE:
            factor = self.THUMBNAIL_MAX_SIDE / largest
            width = max(1, round(width * factor))
            height = max(1, round(height * factor))
        return QtCore.QSize(width, height)

    def refresh_thumbnail(self) -> None:
        self._refresh_timer.stop()
        view = self._live_view()
        if view is None or not self.has_page:
            return
        if not self.isVisible():
            self._stale = True
            return
        map_rect = self.map_rect()
        if map_rect.isEmpty():
            return
        size = self._thumbnail_size(map_rect)
        image = QtGui.QImage(size, QtGui.QImage.Format.Format_RGB32)
        brush = view.backgroundBrush()
        if brush.style() == Qt.BrushStyle.NoBrush:
            brush = self.palette().base()
        image.fill(Qt.GlobalColor.white)
        painter = QtGui.QPainter(image)
        painter.fillRect(image.rect(), brush)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        view.scene().render(
            painter,
            QRectF(0.0, 0.0, size.width(), size.height()),
            self._source_rect(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
        )
        painter.end()
        inverted = QtGui.QImage(image)
        inverted.invertPixels()
        self._thumbnail = image
        self._inverted = inverted
        self._stale = False
        self._render_count += 1
        self.update()

    def eventFilter(self, watched, event) -> bool:
        view = self._live_view()
        if (
            view is not None
            and watched is view.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self.update()
        return False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.has_page:
            self._schedule_refresh(self.LOAD_REFRESH_DELAY_MS)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale or (self.has_page and self._thumbnail is None):
            self.refresh_thumbnail()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._dragging = False
        self.unsetCursor()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if not self._dragging:
            self.unsetCursor()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if not self.has_page:
            painter.setPen(self.palette().text().color())
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, PAN_SIDEBAR_EMPTY_TEXT
            )
            return
        map_rect = self.map_rect()
        if self._thumbnail is not None:
            painter.drawImage(map_rect, self._thumbnail)
        else:
            painter.fillRect(map_rect, self.palette().base())
        visible = self.visible_map_rect()
        if visible.isEmpty():
            return
        if self._inverted is not None:
            painter.save()
            painter.setClipRect(visible)
            painter.drawImage(map_rect, self._inverted)
            painter.restore()
        pen = QtGui.QPen(self.palette().highlight().color())
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(visible.adjusted(0.5, 0.5, -0.5, -0.5))

    def _apply_hover_cursor(self, position: QPointF) -> None:
        if self.is_interactive and self.visible_map_rect().contains(position):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def _pan_to(self, center: QPointF) -> None:
        view = self._live_view()
        if view is not None:
            view.centerOn(center)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.is_interactive:
            super().mousePressEvent(event)
            return
        position = event.position()
        visible = self.visible_map_rect()
        if visible.contains(position):
            self._dragging = True
            self._grab_offset = grab_offset(
                position,
                self._source_rect(),
                self.map_rect(),
                self._view_visible_rect().center(),
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._pan_to(
                center_for_click(
                    position,
                    self._source_rect(),
                    self.map_rect(),
                    self._view_visible_rect().size(),
                )
            )
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        position = event.position()
        if self._dragging and not event.buttons() & Qt.MouseButton.LeftButton:
            self._dragging = False
        if not self._dragging:
            self._apply_hover_cursor(position)
            super().mouseMoveEvent(event)
            return
        if not self.is_interactive:
            self._dragging = False
            self.unsetCursor()
            return
        self._pan_to(
            drag_center(
                position,
                self._grab_offset,
                self._source_rect(),
                self.map_rect(),
                self._view_visible_rect().size(),
            )
        )
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            super().mouseReleaseEvent(event)
            return
        self._dragging = False
        self._apply_hover_cursor(event.position())
        event.accept()
