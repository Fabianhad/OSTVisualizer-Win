from typing import Optional, Tuple
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsView
from shiboken6 import isValid

_DISPLAY_ZOOM_RATIO = 0.333


class ZoomHandlerMixin:
    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if dx or dy:
            self._request_crosshair_repaint()
        if (dx or dy) and self._selected_uids:
            self.viewport().update()
        if (
            (dx or dy)
            and self._cursor_mode in ("place", "annotation_place")
            and self._place_preview_items
        ):
            self.refresh_place_preview_after_view_change()
        if self._paste_backout_active:
            self.refresh_paste_backout_preview_after_view_change()
        if self._uses_dynamic_tile_coverage():
            self._zoom_debouncer.handle_scale_changed(self.transform().m11())

    def fit_to_page(self):
        target_rect = self._page_reset_scene_rect()
        if target_rect.isNull() or not target_rect.isValid():
            target_rect = self._scene.sceneRect()
        if target_rect.isValid():
            self._fit_in_view_with_stable_scrollbars(target_rect)
            self._zoom_debouncer.handle_scale_changed(self.transform().m11())
            self.zoom_changed.emit(
                self.transform().m11() * self._scene_scale * _DISPLAY_ZOOM_RATIO
            )

    def _fit_in_view_with_stable_scrollbars(self, target_rect: QRectF) -> None:
        h_scroll = self.horizontalScrollBar()
        v_scroll = self.verticalScrollBar()
        h_policy = self.horizontalScrollBarPolicy()
        v_policy = self.verticalScrollBarPolicy()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self.fitInView(target_rect, Qt.AspectRatioMode.KeepAspectRatio)
        finally:
            self.setHorizontalScrollBarPolicy(h_policy)
            self.setVerticalScrollBarPolicy(v_policy)
        if h_scroll is not None and h_scroll.maximum() <= 0:
            h_scroll.setValue(0)
        if v_scroll is not None and v_scroll.maximum() <= 0:
            v_scroll.setValue(0)

    def _apply_zoom(self, factor: float) -> None:
        current_scale = self.transform().m11()
        tentative = current_scale * factor
        if tentative < self.MIN_ZOOM:
            factor = self.MIN_ZOOM / current_scale
        elif tentative > self.MAX_ZOOM:
            factor = self.MAX_ZOOM / current_scale
        self.scale(factor, factor)
        new_scale = self.transform().m11()
        self._zoom_debouncer.handle_scale_changed(new_scale)
        self.zoom_changed.emit(new_scale * self._scene_scale * _DISPLAY_ZOOM_RATIO)

    def _apply_zoom_centered(self, factor: float) -> None:
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        try:
            self._apply_zoom(factor)
        finally:
            self.setTransformationAnchor(anchor)

    def set_zoom_percent(self, percent: float) -> None:
        if self._scene_scale <= 0:
            return
        target_m11 = (percent / 100.0) / (self._scene_scale * _DISPLAY_ZOOM_RATIO)
        current = self.transform().m11()
        if current == 0:
            return
        self._apply_zoom_centered(target_m11 / current)

    def zoom_in(self) -> None:
        self._apply_zoom_centered(self.ZOOM_FACTOR)

    def zoom_out(self) -> None:
        self._apply_zoom_centered(1.0 / self.ZOOM_FACTOR)

    def _current_page_scene_context(self):
        page = getattr(self, "_current_page", None)
        scene_scale = getattr(self, "_scene_scale", 0.0)
        if page is None or scene_scale <= 0.0:
            return None
        width = page.effective_width_pts * scene_scale
        height = page.effective_height_pts * scene_scale
        if width <= 0.0 or height <= 0.0:
            return None
        return page, width, height

    def _scene_center_to_persisted_coords(
        self, center_scene: QPointF
    ) -> Tuple[float, float]:
        context = self._current_page_scene_context()
        if context is not None:
            page, scene_width, scene_height = context
            converted = page.canvas_point_to_ost_page_pixels(
                center_scene.x(),
                center_scene.y(),
                scene_width,
                scene_height,
            )
            if converted is not None:
                return converted
        return center_scene.x(), center_scene.y()

    def _persisted_coords_to_scene_center(
        self, center_x: float, center_y: float
    ) -> QPointF:
        context = self._current_page_scene_context()
        if context is not None:
            page, scene_width, scene_height = context
            converted = page.ost_page_pixels_to_canvas_point(
                center_x,
                center_y,
                scene_width,
                scene_height,
            )
            if converted is not None:
                return QPointF(converted[0], converted[1])
        return QPointF(center_x, center_y)

    def get_view_state(self) -> Tuple[float, float, float]:
        m11 = self.transform().m11()
        zoom_fac = m11 * self._scene_scale * _DISPLAY_ZOOM_RATIO
        center = self.mapToScene(self.viewport().rect().center())
        persisted_x, persisted_y = self._scene_center_to_persisted_coords(center)
        return zoom_fac, persisted_x, persisted_y

    def restore_view_state(
        self, zoom_fac: float, center_x: float, center_y: float
    ) -> bool:
        if zoom_fac <= 0 or self._scene_scale <= 0:
            return False
        target_m11 = zoom_fac / (self._scene_scale * _DISPLAY_ZOOM_RATIO)
        current = self.transform().m11()
        if current <= 0:
            return False
        factor = target_m11 / current
        self.scale(factor, factor)
        self.centerOn(self._persisted_coords_to_scene_center(center_x, center_y))
        new_scale = self.transform().m11()
        self._zoom_debouncer.handle_scale_changed(new_scale)
        self.zoom_changed.emit(zoom_fac)
        return True

    def zoom_to_rect(
        self,
        min_x: float,
        min_y: float,
        max_x: float,
        max_y: float,
        margin: float = 0.1,
    ) -> None:
        width = max_x - min_x
        height = max_y - min_y
        if width <= 0 or height <= 0:
            return
        cs = self._scene_builder.get_coordinate_system()
        tl_screen = cs.transform_to_2d(min_x, min_y)
        br_screen = cs.transform_to_2d(max_x, max_y)
        screen_width = abs(br_screen[0] - tl_screen[0])
        screen_height = abs(br_screen[1] - tl_screen[1])
        margin_x = screen_width * margin
        margin_y = screen_height * margin
        page_local_rect = QRectF(
            min(tl_screen[0], br_screen[0]) - margin_x,
            min(tl_screen[1], br_screen[1]) - margin_y,
            screen_width + margin_x * 2,
            screen_height + margin_y * 2,
        )
        page_transform = self._current_page_transform()
        if page_transform is not None:
            page_local_rect = page_transform.mapRect(page_local_rect)
        self.fitInView(page_local_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_debouncer.handle_scale_changed(self.transform().m11())

    def _get_page_transform(self, width: float, height: float) -> QTransform:
        transform = QTransform()
        transform.translate(width / 2, height / 2)
        if self._current_rotation != 0:
            transform.rotate(-self._current_rotation)
        scale_x = -1.0 if self._current_flip_x else 1.0
        scale_y = -1.0 if self._current_flip_y else 1.0
        transform.scale(scale_x, scale_y)
        transform.translate(-width / 2, -height / 2)
        return transform

    def _get_page_rect_dimensions(self) -> Optional[Tuple[float, float]]:
        if self._background_item is not None and isValid(self._background_item):
            rect = self._background_item.boundingRect()
        elif self._white_canvas_item is not None and isValid(self._white_canvas_item):
            rect = self._white_canvas_item.rect()
        else:
            return None
        w, h = rect.width(), rect.height()
        if w == 0 or h == 0:
            return None
        return w, h

    def _apply_page_transform_to_items(self):
        dims = self._get_page_rect_dimensions()
        if dims is None:
            return
        width, height = dims
        transform = self._get_page_transform(width, height)
        for ref_item in (self._background_item, self._white_canvas_item):
            if ref_item is not None and isValid(ref_item):
                ref_item.setTransform(transform)
        for item in self._takeoff_items:
            if isValid(item):
                item.setTransform(transform)
        for item in self._selection_items:
            if isValid(item):
                item.setTransform(transform)
        for item in self._pdf_text_highlight_items:
            if isValid(item):
                item.setTransform(transform)

    def _current_page_transform(self):
        dims = self._get_page_rect_dimensions()
        if dims is None:
            return None
        return self._get_page_transform(*dims)
