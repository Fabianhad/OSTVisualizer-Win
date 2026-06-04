import logging
import math
import weakref
from typing import Any, Optional, Set
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem
from shiboken6 import isValid
from .....application.dtos.render_result_dto import RenderResult
from .....domain.entities.page import Page
from .graphics_items import ImageBackgroundItem, TileGraphicsItem, TileKey

logger = logging.getLogger(__name__)
_RENDER_PRIORITY_REQUIRED_PAGE = 0
_RENDER_PRIORITY_VISIBLE_TILE = 1
_RENDER_PRIORITY_BUFFERED_TILE = 2
_RENDER_PRIORITY_OPTIONAL_BASE = 3
_SHOW_MODE_OVERLAY_ONLY = 1
_PDF_TILE_TRANSITION_Z = 0.3
_PDF_TILE_CURRENT_Z = 0.35
_OVERLAY_TILE_TRANSITION_Z = 0.6
_OVERLAY_TILE_CURRENT_Z = 0.65
_TILE_BLEED_PX = 1
_TILE_SCALE_LOG_STEP = 0.125
_BASE_RASTER_SCALE_STEP = 0.25
_BASE_RASTER_MIN_SCALE = 1.0
_BASE_RASTER_MAX_SCALE = 3.0
_BASE_RASTER_MAX_PIXELS = 20_000_000
_PLAN_VIEW_RASTER_ROTATION = 0


class PageLoaderMixin:
    def set_page_visual_reveal_deferred(self, deferred: bool) -> None:
        self._defer_page_visual_reveal = deferred
        if not deferred:
            return
        self._deferred_page_visual_result = None

    def reveal_deferred_page_visual(self) -> None:
        self._defer_page_visual_reveal = False
        deferred = self._deferred_page_visual_result
        self._deferred_page_visual_result = None
        if deferred is None:
            self._set_page_overlay_items_visible(True)
            return
        render_type, data, result = deferred
        if render_type == "composite":
            self._apply_composite_result(data, result)
        elif render_type == "page":
            self._apply_page_result(data, result)
        elif render_type == "overlay":
            self._apply_overlay_result(data, result)
        self._set_page_overlay_items_visible(True)

    def _defer_page_visual_result(
        self, render_type: str, data: dict, result: RenderResult
    ) -> bool:
        if not self._defer_page_visual_reveal:
            return False
        self._deferred_page_visual_result = (render_type, data, result)
        if not self._load_geometry_ready:
            self._mark_load_geometry_ready()
        return True

    def _advance_render_generation(self) -> int:
        self._page_render_generation_id += 1
        return self._page_render_generation_id

    def _is_current_async_result(self, load_token: str, render_identity) -> bool:
        return (
            load_token == self._current_load_token
            and render_identity == self._current_render_identity
        )

    def _is_stale_generation(self, generation_id: int) -> bool:
        return generation_id != self._page_render_generation_id

    def load_composite_async(
        self, page: Page, bid_ref, render_scale: float, rotation: int
    ):
        request_id = self._rendering_service.render_composite_async(
            page=page,
            bid_ref=bid_ref,
            render_scale=render_scale,
            rotation=_PLAN_VIEW_RASTER_ROTATION,
            callback=self._on_composite_loaded,
            priority=_RENDER_PRIORITY_REQUIRED_PAGE,
        )
        self._current_render_requests.append(request_id)

    def load_page_async(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        rotation: int,
        invert: bool,
        bitonal: bool,
        tint_rgb: Optional[tuple[int, int, int]] = None,
    ):
        request_id = self._rendering_service.render_page_async(
            file_path=file_path,
            page_index=page_index,
            scale=scale,
            rotation=_PLAN_VIEW_RASTER_ROTATION,
            callback=self._on_page_loaded,
            priority=_RENDER_PRIORITY_REQUIRED_PAGE,
            invert=invert,
            bitonal=bitonal,
            tint_rgb=tint_rgb,
        )
        self._current_render_requests.append(request_id)

    def load_overlay_async(
        self,
        page: Page,
        bid_ref,
        view_scale: float,
        show_mode: int,
        rotation: int,
        render_scale: Optional[float] = None,
    ):
        if not page.overlay_image_path:
            return
        request_id = self._rendering_service.render_overlay_async(
            page=page,
            bid_ref=bid_ref,
            view_scale=view_scale,
            show_mode=show_mode,
            rotation=rotation,
            callback=self._on_overlay_loaded,
            priority=_RENDER_PRIORITY_REQUIRED_PAGE,
            render_scale=render_scale,
        )
        self._current_render_requests.append(request_id)

    def _resolve_pending_render(
        self, result: RenderResult, render_type: str
    ) -> Optional[dict]:
        if result.request_id in self._current_render_requests:
            self._current_render_requests.remove(result.request_id)
        else:
            return None
        if not result.success or not result.image:
            logger.warning("%s render failed: %s", render_type, result.error)
            return None
        data = self._pending_page_data
        if not data:
            return None
        if not self._is_current_async_result(
            data.get("load_token"), data.get("render_identity")
        ):
            return None
        return data

    def _replace_background_item(self, item: ImageBackgroundItem) -> None:
        self._remove_background_item()
        self._background_item = item
        self._background_item.setZValue(0)
        self._scene.addItem(self._background_item)

    def _remove_background_item(self) -> None:
        if self._background_item is None:
            return
        if not isValid(self._background_item):
            self._background_item = None
            return
        self._background_item.clear_image()
        if self._background_item.scene() is self._scene:
            self._scene.removeItem(self._background_item)
        self._background_item = None

    def _remove_tile_item(self, item: TileGraphicsItem) -> None:
        if not isValid(item):
            return
        item.clear_image()
        if item.scene() is self._scene:
            self._scene.removeItem(item)

    def _remove_overlay_item(self, item: QGraphicsPixmapItem) -> None:
        if not isValid(item):
            return
        item.setPixmap(QPixmap())
        if item.scene() is self._scene:
            self._scene.removeItem(item)

    def _device_pixel_ratio(self) -> float:
        viewport = self.viewport()
        if viewport is not None:
            return max(1.0, float(viewport.devicePixelRatioF()))
        return max(1.0, float(self.devicePixelRatioF()))

    def _max_base_raster_scale(self) -> float:
        raster_width_pts, raster_height_pts = self._active_tile_raster_dimensions()
        if raster_width_pts <= 0 or raster_height_pts <= 0:
            return _BASE_RASTER_MAX_SCALE
        budget_scale = math.sqrt(
            _BASE_RASTER_MAX_PIXELS / (raster_width_pts * raster_height_pts)
        )
        return max(0.25, min(_BASE_RASTER_MAX_SCALE, budget_scale))

    def _quantize_base_raster_scale(self, scale: float) -> float:
        max_scale = self._max_base_raster_scale()
        min_scale = min(_BASE_RASTER_MIN_SCALE, max_scale)
        clamped = max(min_scale, min(max_scale, scale))
        quantized = (
            math.ceil((clamped - 1e-9) / _BASE_RASTER_SCALE_STEP)
            * _BASE_RASTER_SCALE_STEP
        )
        return round(min(max_scale, quantized), 3)

    def _target_base_raster_scale(
        self, default_scale: float, view_m11: Optional[float] = None
    ) -> float:
        if not self._can_zoom_rerender or self._disable_high_resolution_images:
            return default_scale
        view_transform_scale = (
            view_m11 if view_m11 and view_m11 > 0 else self.transform().m11()
        )
        if view_transform_scale <= 0:
            return default_scale
        target_scale = (
            self._scene_scale * view_transform_scale * self._device_pixel_ratio()
        )
        return self._quantize_base_raster_scale(target_scale)

    def _uses_pdf_base_raster(self, data: dict) -> bool:
        page = data.get("page", self._current_page)
        return bool(
            page and page.image_path and page.image_path.lower().endswith(".pdf")
        )

    def _rendered_pdf_page_dimensions(
        self,
        rotation: Optional[int] = None,
        pdf_width_pts: Optional[float] = None,
        pdf_height_pts: Optional[float] = None,
    ) -> tuple[float, float]:
        width = float(self._pdf_width_pts if pdf_width_pts is None else pdf_width_pts)
        height = float(
            self._pdf_height_pts if pdf_height_pts is None else pdf_height_pts
        )
        return width, height

    def _uses_overlay_pdf_tiles(self) -> bool:
        return (
            self._primary_tiles_use_overlay_pdf() or self._uses_both_overlay_pdf_tiles()
        )

    def _primary_tiles_use_overlay_pdf(self) -> bool:
        page = self._current_page
        return bool(
            page
            and self._loaded_visual_kind == "overlay"
            and page.image_show_mode == _SHOW_MODE_OVERLAY_ONLY
            and page.overlay_image_path
            and page.overlay_image_path.lower().endswith(".pdf")
        )

    def _uses_both_overlay_pdf_tiles(self) -> bool:
        page = self._current_page
        return bool(
            page
            and self._loaded_visual_kind == "overlay"
            and page.image_show_mode == 2
            and page.overlay_image_path
            and page.overlay_image_path.lower().endswith(".pdf")
        )

    def _uses_dynamic_tile_coverage(self) -> bool:
        return self._can_zoom_rerender or self._uses_overlay_pdf_tiles()

    def _active_page_raster_rotation(self) -> int:
        rotation = self._current_rotation
        if not rotation and self._current_page is not None:
            rotation = self._current_page.rotation
        return int(rotation or _PLAN_VIEW_RASTER_ROTATION)

    def _active_tile_raster_dimensions(self) -> tuple[float, float]:
        if self._primary_tiles_use_overlay_pdf():
            return self._overlay_tile_raster_dimensions()
        return self._rendered_pdf_page_dimensions()

    def _overlay_tile_raster_dimensions(self) -> tuple[float, float]:
        width = self._overlay_pdf_width_pts
        height = self._overlay_pdf_height_pts
        if width > 0.0 and height > 0.0:
            return width, height
        return self._rendered_pdf_page_dimensions()

    def _tile_raster_dimensions(self, overlay: bool = False) -> tuple[float, float]:
        if overlay or self._primary_tiles_use_overlay_pdf():
            width = self._overlay_pdf_width_pts
            height = self._overlay_pdf_height_pts
            if width > 0.0 and height > 0.0:
                return width, height
        return self._rendered_pdf_page_dimensions()

    def _overlay_pdf_tile_transform(self) -> QTransform:
        page = self._current_page
        transform = QTransform()
        if page is None:
            return transform
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_page_points()
        source_w = self._overlay_pdf_width_pts
        source_h = self._overlay_pdf_height_pts
        if rect_w <= 0.0 or rect_h <= 0.0 or source_w <= 0.0 or source_h <= 0.0:
            return transform
        transform.translate(
            rect_x * self._scene_scale,
            rect_y * self._scene_scale,
        )
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        if total_rotation != 0:
            transform.rotate(math.degrees(total_rotation))
        transform.scale(rect_w / source_w, rect_h / source_h)
        return transform

    def _logical_page_scene_dimensions(
        self, data: dict, result: Optional[RenderResult] = None
    ) -> tuple[float, float]:
        if not self._uses_pdf_base_raster(data) and result is not None:
            return float(result.image.width()), float(result.image.height())
        width, height = self._rendered_pdf_page_dimensions(
            data.get("rotation", self._current_rotation),
            data["pdf_width_pts"],
            data["pdf_height_pts"],
        )
        return width * self._scene_scale, height * self._scene_scale

    def _clear_overlay_items(self) -> None:
        for item in self._overlay_items:
            self._remove_overlay_item(item)
        self._overlay_items.clear()

    def _remove_white_canvas_item(self) -> None:
        if self._white_canvas_item is not None and isValid(self._white_canvas_item):
            if self._white_canvas_item.scene() is self._scene:
                self._scene.removeItem(self._white_canvas_item)
        self._white_canvas_item = None

    def _on_composite_loaded(self, result: RenderResult):
        data = self._resolve_pending_render(result, "Composite")
        if data is None:
            return
        if self._defer_page_visual_result("composite", data, result):
            return
        self._apply_composite_result(data, result)

    def _apply_composite_result(self, data: dict, result: RenderResult) -> None:
        self._remove_white_canvas_item()
        self._clear_overlay_items()
        scene_width, scene_height = self._logical_page_scene_dimensions(data, result)
        background_item = ImageBackgroundItem(
            result.image,
            scene_width,
            scene_height,
        )
        self._replace_background_item(background_item)
        self._loaded_visual_kind = "composite"
        self._base_raster_scale = data["base_raster_scale"]
        self._apply_page_transform_to_items()
        self._mark_load_geometry_ready()

    def _on_page_loaded(self, result: RenderResult):
        data = self._resolve_pending_render(result, "Page")
        if data is None:
            return
        if self._defer_page_visual_result("page", data, result):
            return
        self._apply_page_result(data, result)

    def _apply_page_result(self, data: dict, result: RenderResult) -> None:
        view_scale = data.get("view_scale", 1.0)
        self._clear_overlay_items()
        scene_width, scene_height = self._logical_page_scene_dimensions(data, result)
        background_item = ImageBackgroundItem(
            result.image,
            scene_width,
            scene_height,
        )
        self._replace_background_item(background_item)
        self._loaded_visual_kind = "page"
        self._base_raster_scale = data["base_raster_scale"]
        self._apply_page_transform_to_items()
        self._update_scene_rect()
        if self._load_view_applied:
            self._update_tile_coverage(self.transform().m11())
        page = data["page"]
        show_mode = data["show_mode"]
        show_overlay = data["show_overlay"]
        rotation = data["rotation"]
        if show_overlay and show_mode != _SHOW_MODE_OVERLAY_ONLY and page.has_overlay:
            self.load_overlay_async(
                page, data.get("bid_ref"), view_scale, show_mode, rotation
            )
        else:
            self._mark_load_geometry_ready()

    def _on_overlay_loaded(self, result: RenderResult):
        data = self._resolve_pending_render(result, "Overlay")
        if data is None:
            return
        if self._defer_page_visual_result("overlay", data, result):
            return
        self._apply_overlay_result(data, result)

    def _apply_overlay_result(self, data: dict, result: RenderResult) -> None:
        page = data["page"]
        view_scale = data["view_scale"]
        show_mode = data["show_mode"]
        render_scale = data.get("overlay_render_scale", view_scale)
        if (
            page.overlay_image_path
            and page.overlay_image_path.lower().endswith(".pdf")
            and render_scale > 0
        ):
            self._overlay_pdf_width_pts = float(result.image.width()) / render_scale
            self._overlay_pdf_height_pts = float(result.image.height()) / render_scale
        overlay_pixmap = QPixmap.fromImage(result.image)
        item = self._create_overlay_graphics_item(
            overlay_pixmap, page, view_scale, show_mode
        )
        if item:
            self._clear_overlay_items()
            self._scene.addItem(item)
            self._overlay_items.append(item)
            self._loaded_visual_kind = "overlay"
            self._base_raster_scale = render_scale
            self._mark_load_geometry_ready()

    def _create_overlay_graphics_item(
        self,
        overlay_pixmap: Any,
        page: Page,
        view_scale: float,
        show_mode: int,
    ):
        item = QGraphicsPixmapItem(overlay_pixmap)
        item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        z_value = 0.5 if show_mode in (_SHOW_MODE_OVERLAY_ONLY, 2) else 0
        item.setZValue(z_value)
        overlay_width = overlay_pixmap.width()
        overlay_height = overlay_pixmap.height()
        is_pdf = page.overlay_image_path.lower().endswith(".pdf")
        if is_pdf:
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        transform = self._overlay_graphics_transform(
            page, overlay_width, overlay_height, view_scale
        )
        if transform is None:
            return None
        item.setTransform(transform)
        return item

    def _overlay_graphics_transform(
        self,
        page: Page,
        overlay_width: float,
        overlay_height: float,
        view_scale: float,
    ) -> Optional[QTransform]:
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_canvas(
            page.effective_width_pts * view_scale,
            page.effective_height_pts * view_scale,
        )
        if overlay_width <= 0 or overlay_height <= 0 or rect_w <= 0.0 or rect_h <= 0.0:
            return None
        transform = QTransform()
        transform.translate(rect_x, rect_y)
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        if total_rotation != 0:
            transform.rotate(math.degrees(total_rotation))
        transform.scale(rect_w / overlay_width, rect_h / overlay_height)
        return transform

    def _compute_tile_scale(self, view_m11: float) -> float:
        display_scale = self._scene_scale * view_m11 * self._device_pixel_ratio()
        max_scale = self._scene_scale * self.MAX_ZOOM * self._device_pixel_ratio()
        return max(0.1, min(max_scale, display_scale))

    def _quantize_tile_scale(self, scale: float) -> float:
        if scale <= 1.0:
            return 1.0
        log_scale = math.log2(scale)
        quantized_log = (
            math.ceil((log_scale - 1e-9) / _TILE_SCALE_LOG_STEP) * _TILE_SCALE_LOG_STEP
        )
        return max(1.0, 2**quantized_log)

    def _compute_visible_tile_keys(
        self,
        viewport_scene_rect: QRectF,
        tile_scale: float,
        buffer: int = 1,
        overlay: bool = False,
    ) -> Set[TileKey]:
        view_scale = self._scene_scale
        raster_width_pts, raster_height_pts = self._tile_raster_dimensions(overlay)
        if raster_width_pts <= 0 or raster_height_pts <= 0:
            return set()
        page_px_w = raster_width_pts * tile_scale
        page_px_h = raster_height_pts * tile_scale
        num_cols = math.ceil(page_px_w / self.TILE_SIZE_PX)
        num_rows = math.ceil(page_px_h / self.TILE_SIZE_PX)
        tile_scene_dim = self.TILE_SIZE_PX * view_scale / tile_scale
        vp = viewport_scene_rect
        col_min = max(0, int((vp.left() - buffer * tile_scene_dim) / tile_scene_dim))
        row_min = max(0, int((vp.top() - buffer * tile_scene_dim) / tile_scene_dim))
        col_max = min(
            num_cols, int((vp.right() + buffer * tile_scene_dim) / tile_scene_dim) + 1
        )
        row_max = min(
            num_rows,
            int((vp.bottom() + buffer * tile_scene_dim) / tile_scene_dim) + 1,
        )
        q_scale = self._quantize_tile_scale(tile_scale)
        return {
            TileKey(col, row, q_scale)
            for col in range(col_min, col_max)
            for row in range(row_min, row_max)
        }

    def _get_tile_render_local_rect(
        self, key: TileKey, overlay: bool = False
    ) -> QRectF:
        view_scale = self._scene_scale
        tile_x, tile_y, tile_w, tile_h = self._get_tile_px_rect(key, overlay)
        bleed_left, bleed_top, bleed_right, bleed_bottom = self._get_tile_bleed_offsets(
            tile_x, tile_y, tile_w, tile_h, key, overlay
        )
        render_x = tile_x - bleed_left
        render_y = tile_y - bleed_top
        render_w = tile_w + bleed_left + bleed_right
        render_h = tile_h + bleed_top + bleed_bottom
        return QRectF(
            render_x * view_scale / key.scale,
            render_y * view_scale / key.scale,
            render_w * view_scale / key.scale,
            render_h * view_scale / key.scale,
        )

    def _get_tile_local_rect(self, key: TileKey, overlay: bool = False) -> QRectF:
        view_scale = self._scene_scale
        raster_width_pts, raster_height_pts = self._tile_raster_dimensions(overlay)
        page_px_w = raster_width_pts * key.scale
        page_px_h = raster_height_pts * key.scale
        tile_x_px = key.col * self.TILE_SIZE_PX
        tile_y_px = key.row * self.TILE_SIZE_PX
        tile_w_px = min(self.TILE_SIZE_PX, page_px_w - tile_x_px)
        tile_h_px = min(self.TILE_SIZE_PX, page_px_h - tile_y_px)
        scene_x = tile_x_px * view_scale / key.scale
        scene_y = tile_y_px * view_scale / key.scale
        scene_w = tile_w_px * view_scale / key.scale
        scene_h = tile_h_px * view_scale / key.scale
        return QRectF(scene_x, scene_y, scene_w, scene_h)

    def _get_tile_px_rect(self, key: TileKey, overlay: bool = False) -> tuple:
        raster_width_pts, raster_height_pts = self._tile_raster_dimensions(overlay)
        page_px_w = int(raster_width_pts * key.scale)
        page_px_h = int(raster_height_pts * key.scale)
        tile_x = key.col * self.TILE_SIZE_PX
        tile_y = key.row * self.TILE_SIZE_PX
        tile_w = min(self.TILE_SIZE_PX, page_px_w - tile_x)
        tile_h = min(self.TILE_SIZE_PX, page_px_h - tile_y)
        return (tile_x, tile_y, tile_w, tile_h)

    def _get_tile_bleed_offsets(
        self,
        tile_x: int,
        tile_y: int,
        tile_w: int,
        tile_h: int,
        key: TileKey,
        overlay: bool = False,
    ) -> tuple:
        raster_width_pts, raster_height_pts = self._tile_raster_dimensions(overlay)
        page_px_w = int(raster_width_pts * key.scale)
        page_px_h = int(raster_height_pts * key.scale)
        return (
            min(_TILE_BLEED_PX, tile_x),
            min(_TILE_BLEED_PX, tile_y),
            min(_TILE_BLEED_PX, max(0, page_px_w - (tile_x + tile_w))),
            min(_TILE_BLEED_PX, max(0, page_px_h - (tile_y + tile_h))),
        )

    def _get_tile_render_px_rect(self, key: TileKey, overlay: bool = False) -> tuple:
        tile_x, tile_y, tile_w, tile_h = self._get_tile_px_rect(key, overlay)
        bleed_left, bleed_top, bleed_right, bleed_bottom = self._get_tile_bleed_offsets(
            tile_x, tile_y, tile_w, tile_h, key, overlay
        )
        return (
            tile_x - bleed_left,
            tile_y - bleed_top,
            tile_w + bleed_left + bleed_right,
            tile_h + bleed_top + bleed_bottom,
        )

    def _evict_tiles(self, keep_keys: Set[TileKey]) -> None:
        evict_keys = (self._tile_items.keys() | self._tile_requests.keys()) - keep_keys
        self._evict_tile_keys(list(evict_keys))

    def _evict_tiles_at_scale(self, scale: float, keep_keys: Set[TileKey]) -> None:
        candidates = {
            k for k in (*self._tile_items, *self._tile_requests) if k.scale == scale
        }
        self._evict_tile_keys(candidates - keep_keys)

    def _evict_overlay_tile_keys(self, keys) -> None:
        keys = list(keys)
        if not keys:
            return
        for key in keys:
            item = self._overlay_tile_items.pop(key, None)
            if item:
                self._remove_tile_item(item)
            req_id = self._overlay_tile_requests.pop(key, None)
            if req_id:
                self._rendering_service.cancel_request(req_id)
        self._sync_low_res_overlay_visibility_for_tiles()

    def _evict_overlay_tiles_at_scale(
        self, scale: float, keep_keys: Set[TileKey]
    ) -> None:
        candidates = {
            k
            for k in (*self._overlay_tile_items, *self._overlay_tile_requests)
            if k.scale == scale
        }
        self._evict_overlay_tile_keys(candidates - keep_keys)

    def _evict_old_scale_tiles(self) -> None:
        old_keys = [
            k for k in list(self._tile_items.keys()) if k.scale != self._tile_scale
        ]
        for key in old_keys:
            item = self._tile_items.pop(key, None)
            if item:
                self._remove_tile_item(item)
        old_overlay_keys = [
            k
            for k in list(self._overlay_tile_items.keys())
            if k.scale != self._overlay_tile_scale
        ]
        for key in old_overlay_keys:
            item = self._overlay_tile_items.pop(key, None)
            if item:
                self._remove_tile_item(item)
        self._sync_low_res_base_visibility_for_tiles()
        self._sync_low_res_overlay_visibility_for_tiles()

    def _demote_old_scale_tiles(self) -> None:
        transition_z = (
            _OVERLAY_TILE_TRANSITION_Z
            if self._primary_tiles_use_overlay_pdf()
            else _PDF_TILE_TRANSITION_Z
        )
        for key, item in self._tile_items.items():
            if key.scale != self._tile_scale:
                item.setZValue(transition_z)
        for key, item in self._overlay_tile_items.items():
            if key.scale != self._overlay_tile_scale:
                item.setZValue(_OVERLAY_TILE_TRANSITION_Z)

    def _tile_keys_local_rect(
        self, keys: Set[TileKey], overlay: bool = False
    ) -> QRectF:
        rect = QRectF()
        for key in keys:
            tile_rect = self._tile_scene_local_rect(key, overlay=overlay)
            rect = tile_rect if rect.isNull() else rect.united(tile_rect)
        return rect

    def _tile_request_px_rect(self, key: TileKey, overlay: bool = False) -> tuple:
        if self._is_composite_mode:
            return self._get_tile_px_rect(key, overlay)
        return self._get_tile_render_px_rect(key, overlay)

    def _tile_scene_local_rect(self, key: TileKey, overlay: bool = False) -> QRectF:
        if self._is_composite_mode:
            return self._get_tile_local_rect(key, overlay)
        return self._get_tile_render_local_rect(key, overlay)

    def _tile_item_rects(
        self, key: TileKey, overlay: bool = False
    ) -> tuple[QRectF, QRectF]:
        if self._is_composite_mode:
            return (
                self._get_tile_local_rect(key, overlay),
                QRectF(
                    0.0,
                    0.0,
                    float(self._get_tile_px_rect(key, overlay)[2]),
                    float(self._get_tile_px_rect(key, overlay)[3]),
                ),
            )
        tile_x, tile_y, tile_w, tile_h = self._get_tile_px_rect(key, overlay)
        bleed_left, bleed_top, _bleed_right, _bleed_bottom = (
            self._get_tile_bleed_offsets(tile_x, tile_y, tile_w, tile_h, key, overlay)
        )
        return (
            self._get_tile_local_rect(key, overlay),
            QRectF(
                float(bleed_left),
                float(bleed_top),
                float(tile_w),
                float(tile_h),
            ),
        )

    def _evict_old_scale_tiles_outside(self, keep_rect: QRectF) -> None:
        if keep_rect.isNull():
            self._evict_old_scale_tiles()
            return
        old_keys = [
            key
            for key in list(self._tile_items.keys())
            if key.scale != self._tile_scale
            and not self._tile_scene_local_rect(key).intersects(keep_rect)
        ]
        self._evict_tile_keys(old_keys)

    def _evict_old_overlay_scale_tiles_outside(self, keep_rect: QRectF) -> None:
        if keep_rect.isNull():
            old_keys = [
                k
                for k in list(self._overlay_tile_items.keys())
                if k.scale != self._overlay_tile_scale
            ]
            self._evict_overlay_tile_keys(old_keys)
            return
        old_keys = [
            key
            for key in list(self._overlay_tile_items.keys())
            if key.scale != self._overlay_tile_scale
            and not self._tile_scene_local_rect(key, overlay=True).intersects(keep_rect)
        ]
        self._evict_overlay_tile_keys(old_keys)

    def _clear_tiles(self) -> None:
        self._evict_tiles(set())
        self._evict_overlay_tile_keys(
            set(self._overlay_tile_items.keys())
            | set(self._overlay_tile_requests.keys())
        )
        self._tile_scale = 0.0
        self._overlay_tile_scale = 0.0
        self._set_low_res_base_item_visible(True)
        self._set_low_res_overlay_items_visible(True)

    def _set_low_res_base_item_visible(self, visible: bool) -> None:
        if self._background_item is not None and isValid(self._background_item):
            self._background_item.setVisible(visible)

    def _sync_low_res_base_visibility_for_tiles(self) -> None:
        page = self._current_page
        if not (
            page
            and page.image_show_mode == 2
            and page.has_overlay
            and self._can_zoom_rerender
            and not self._is_composite_mode
            and not self._primary_tiles_use_overlay_pdf()
        ):
            return
        self._set_low_res_base_item_visible(
            not bool(self._tile_items) or bool(self._tile_requests)
        )

    def _set_low_res_overlay_items_visible(self, visible: bool) -> None:
        for item in self._overlay_items:
            if isValid(item):
                item.setVisible(visible)

    def _sync_low_res_overlay_visibility_for_tiles(self) -> None:
        if self._uses_overlay_pdf_tiles():
            self._set_low_res_overlay_items_visible(
                not bool(self._overlay_tile_items) or bool(self._overlay_tile_requests)
            )

    def _tiles_active(self) -> bool:
        return bool(
            self._tile_items
            or self._tile_requests
            or self._tile_scale > 0
            or self._overlay_tile_items
            or self._overlay_tile_requests
            or self._overlay_tile_scale > 0
        )

    def _cancel_tile_requests(self) -> None:
        for req_id in self._tile_requests.values():
            self._rendering_service.cancel_request(req_id)
        self._tile_requests.clear()
        for req_id in self._overlay_tile_requests.values():
            self._rendering_service.cancel_request(req_id)
        self._overlay_tile_requests.clear()

    def _request_tile(self, key: TileKey, generation_id: int, priority: int) -> None:
        if key in self._tile_items or key in self._tile_requests:
            return
        page = self._current_page
        if not page:
            return
        tile_x, tile_y, tile_w, tile_h = self._tile_request_px_rect(key)
        if tile_w <= 0 or tile_h <= 0:
            return
        load_token = self._current_load_token
        render_identity = dict(self._current_render_identity or {})
        weak_self = weakref.ref(self)

        def on_tile_loaded(result: RenderResult, _key: TileKey = key) -> None:
            view = weak_self()
            if view is not None:
                view._on_tile_loaded(
                    result,
                    _key,
                    load_token,
                    render_identity,
                    generation_id,
                )

        if self._is_composite_mode:
            req_id = self._rendering_service.render_composite_region_async(
                page=page,
                bid_ref=self._current_bid_ref,
                scale=key.scale,
                rotation=_PLAN_VIEW_RASTER_ROTATION,
                tile_x=tile_x,
                tile_y=tile_y,
                tile_w=tile_w,
                tile_h=tile_h,
                callback=on_tile_loaded,
                priority=priority,
            )
        elif self._primary_tiles_use_overlay_pdf():
            req_id = self._rendering_service.render_region_async(
                file_path=page.overlay_image_path,
                page_index=0,
                scale=key.scale,
                rotation=self._active_page_raster_rotation(),
                tile_x=tile_x,
                tile_y=tile_y,
                tile_w=tile_w,
                tile_h=tile_h,
                callback=on_tile_loaded,
                priority=priority,
                invert=page.invert,
                bitonal=page.bitonal,
                tint_rgb=(80, 80, 255) if page.image_show_mode == 2 else None,
            )
        else:
            req_id = self._rendering_service.render_region_async(
                file_path=page.image_path,
                page_index=page.page_index,
                scale=key.scale,
                rotation=_PLAN_VIEW_RASTER_ROTATION,
                tile_x=tile_x,
                tile_y=tile_y,
                tile_w=tile_w,
                tile_h=tile_h,
                callback=on_tile_loaded,
                priority=priority,
                invert=page.invert,
                bitonal=page.bitonal,
                tint_rgb=(
                    (255, 80, 80)
                    if page.image_show_mode == 2 and page.has_overlay
                    else None
                ),
            )
        self._tile_requests[key] = req_id

    def _on_tile_loaded(
        self,
        result: RenderResult,
        key: TileKey,
        load_token: str,
        render_identity,
        generation_id: int,
    ) -> None:
        request_id = self._tile_requests.get(key)
        if request_id != result.request_id or not self._is_current_async_result(
            load_token, render_identity
        ):
            return
        self._tile_requests.pop(key, None)
        if self._overlay_move_suppresses_normal_tiles():
            self._sync_low_res_base_visibility_for_tiles()
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        if (
            self._is_stale_generation(generation_id)
            or not result.success
            or not result.image
            or key in self._tile_items
            or key.scale != self._tile_scale
        ):
            self._sync_low_res_base_visibility_for_tiles()
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        local_rect, source_rect = self._tile_item_rects(key)
        item = TileGraphicsItem(
            result.image,
            local_rect,
            source_rect,
        )
        if self._primary_tiles_use_overlay_pdf():
            item.setZValue(_OVERLAY_TILE_CURRENT_Z)
            item.setTransform(self._overlay_pdf_tile_transform())
        else:
            item.setZValue(_PDF_TILE_CURRENT_Z)
            raster_width_pts, raster_height_pts = self._rendered_pdf_page_dimensions()
            W = raster_width_pts * self._scene_scale
            H = raster_height_pts * self._scene_scale
            item.setTransform(self._get_page_transform(W, H))
        self._scene.addItem(item)
        self._tile_items[key] = item
        self._sync_low_res_base_visibility_for_tiles()
        self._sync_low_res_overlay_visibility_for_tiles()
        if not self._tile_requests:
            self._evict_old_scale_tiles()

    def _request_overlay_tile(
        self, key: TileKey, generation_id: int, priority: int
    ) -> None:
        if key in self._overlay_tile_items or key in self._overlay_tile_requests:
            return
        page = self._current_page
        if not page or not page.overlay_image_path:
            return
        tile_x, tile_y, tile_w, tile_h = self._tile_request_px_rect(key, overlay=True)
        if tile_w <= 0 or tile_h <= 0:
            return
        load_token = self._current_load_token
        render_identity = dict(self._current_render_identity or {})
        weak_self = weakref.ref(self)

        def on_tile_loaded(result: RenderResult, _key: TileKey = key) -> None:
            view = weak_self()
            if view is not None:
                view._on_overlay_tile_loaded(
                    result,
                    _key,
                    load_token,
                    render_identity,
                    generation_id,
                )

        req_id = self._rendering_service.render_region_async(
            file_path=page.overlay_image_path,
            page_index=0,
            scale=key.scale,
            rotation=self._active_page_raster_rotation(),
            tile_x=tile_x,
            tile_y=tile_y,
            tile_w=tile_w,
            tile_h=tile_h,
            callback=on_tile_loaded,
            priority=priority,
            invert=page.invert,
            bitonal=page.bitonal,
            tint_rgb=(80, 80, 255),
        )
        self._overlay_tile_requests[key] = req_id

    def _on_overlay_tile_loaded(
        self,
        result: RenderResult,
        key: TileKey,
        load_token: str,
        render_identity,
        generation_id: int,
    ) -> None:
        request_id = self._overlay_tile_requests.get(key)
        if request_id != result.request_id or not self._is_current_async_result(
            load_token, render_identity
        ):
            return
        self._overlay_tile_requests.pop(key, None)
        if self._overlay_move_suppresses_normal_tiles():
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        if (
            self._is_stale_generation(generation_id)
            or not result.success
            or not result.image
            or key in self._overlay_tile_items
            or key.scale != self._overlay_tile_scale
        ):
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        local_rect, source_rect = self._tile_item_rects(key, overlay=True)
        item = TileGraphicsItem(
            result.image,
            local_rect,
            source_rect,
        )
        item.setZValue(_OVERLAY_TILE_CURRENT_Z)
        item.setTransform(self._overlay_pdf_tile_transform())
        self._scene.addItem(item)
        self._overlay_tile_items[key] = item
        self._sync_low_res_overlay_visibility_for_tiles()
        if not self._overlay_tile_requests:
            self._evict_old_scale_tiles()

    def _request_optional_base_correction(
        self, base_raster_scale: float, generation_id: int
    ) -> None:
        page = self._current_page
        if not page or not self._current_render_identity:
            return
        if self._tiles_active():
            return
        self._cancel_optional_base_correction()
        load_token = self._current_load_token
        render_identity = dict(self._current_render_identity)
        weak_self = weakref.ref(self)

        def on_base_loaded(
            result: RenderResult, _scale: float = base_raster_scale
        ) -> None:
            view = weak_self()
            if view is not None:
                view._on_optional_base_correction_loaded(
                    result, _scale, load_token, render_identity, generation_id
                )

        request_id = self._rendering_service.render_page_async(
            file_path=page.image_path,
            page_index=page.page_index,
            scale=base_raster_scale,
            rotation=_PLAN_VIEW_RASTER_ROTATION,
            callback=on_base_loaded,
            priority=_RENDER_PRIORITY_OPTIONAL_BASE,
            invert=page.invert,
            bitonal=page.bitonal,
            tint_rgb=(
                (255, 80, 80)
                if page.image_show_mode == 2 and page.has_overlay
                else None
            ),
        )
        self._base_raster_request_id = request_id
        self._base_raster_request_scale = base_raster_scale
        self._base_correction_request_generation_id = generation_id

    def _request_optional_overlay_base_correction(
        self, base_raster_scale: float, generation_id: int
    ) -> None:
        page = self._current_page
        if not page or not page.overlay_image_path or not self._current_render_identity:
            return
        if self._tiles_active():
            return
        self._cancel_optional_base_correction()
        load_token = self._current_load_token
        render_identity = dict(self._current_render_identity)
        weak_self = weakref.ref(self)

        def on_base_loaded(
            result: RenderResult, _scale: float = base_raster_scale
        ) -> None:
            view = weak_self()
            if view is not None:
                view._on_optional_overlay_base_correction_loaded(
                    result, _scale, load_token, render_identity, generation_id
                )

        request_id = self._rendering_service.render_overlay_async(
            page=page,
            bid_ref=self._current_bid_ref,
            view_scale=self._scene_scale,
            show_mode=page.image_show_mode,
            rotation=self._active_page_raster_rotation(),
            callback=on_base_loaded,
            priority=_RENDER_PRIORITY_OPTIONAL_BASE,
            render_scale=base_raster_scale,
        )
        self._base_raster_request_id = request_id
        self._base_raster_request_scale = base_raster_scale
        self._base_correction_request_generation_id = generation_id

    def _cancel_optional_base_correction(self) -> None:
        if not self._base_raster_request_id:
            return
        self._rendering_service.cancel_request(self._base_raster_request_id)
        self._base_raster_request_id = None
        self._base_raster_request_scale = 0.0
        self._base_correction_request_generation_id = 0

    def _on_optional_base_correction_loaded(
        self,
        result: RenderResult,
        base_raster_scale: float,
        load_token: str,
        render_identity: dict,
        generation_id: int,
    ) -> None:
        if result.request_id != self._base_raster_request_id:
            return
        self._base_raster_request_id = None
        self._base_raster_request_scale = 0.0
        self._base_correction_request_generation_id = 0
        if (
            not result.success
            or not result.image
            or not self._is_current_async_result(load_token, render_identity)
            or self._current_page is None
        ):
            return
        if self._is_stale_generation(generation_id):
            return
        data = {
            "pdf_width_pts": self._pdf_width_pts,
            "pdf_height_pts": self._pdf_height_pts,
            "rotation": self._current_rotation,
        }
        scene_width, scene_height = self._logical_page_scene_dimensions(data)
        background_item = ImageBackgroundItem(result.image, scene_width, scene_height)
        self._replace_background_item(background_item)
        self._base_raster_scale = base_raster_scale
        self._apply_page_transform_to_items()
        self._update_scene_rect()

    def _on_optional_overlay_base_correction_loaded(
        self,
        result: RenderResult,
        base_raster_scale: float,
        load_token: str,
        render_identity: dict,
        generation_id: int,
    ) -> None:
        if result.request_id != self._base_raster_request_id:
            return
        self._base_raster_request_id = None
        self._base_raster_request_scale = 0.0
        self._base_correction_request_generation_id = 0
        if (
            not result.success
            or not result.image
            or not self._is_current_async_result(load_token, render_identity)
            or self._current_page is None
            or self._is_stale_generation(generation_id)
        ):
            return
        data = {
            "page": self._current_page,
            "view_scale": self._scene_scale,
            "show_mode": self._current_page.image_show_mode,
            "overlay_render_scale": base_raster_scale,
        }
        self._apply_overlay_result(data, result)

    def _update_optional_base_coverage(
        self, view_m11: float, generation_id: int
    ) -> None:
        if (
            not self._can_zoom_rerender
            or self._disable_high_resolution_images
            or self._is_composite_mode
            or not self._current_page
            or not self._background_item
            or self._pending_page_data is not None
        ):
            return
        target_scale = self._target_base_raster_scale(
            self._scene_scale, view_m11=view_m11
        )
        active_request_scale = self._base_raster_request_scale
        if (
            active_request_scale
            and abs(active_request_scale - target_scale) < 1e-6
            and self._base_correction_request_generation_id == generation_id
        ):
            return
        if (
            self._base_raster_scale
            and abs(self._base_raster_scale - target_scale) < 1e-6
        ):
            return
        self._request_optional_base_correction(target_scale, generation_id)

    def _update_optional_overlay_base_coverage(
        self, view_m11: float, generation_id: int
    ) -> None:
        if (
            not self._primary_tiles_use_overlay_pdf()
            or self._pending_page_data is not None
        ):
            return
        if self._disable_high_resolution_images:
            target_scale = self._scene_scale
        else:
            view_transform_scale = view_m11 if view_m11 and view_m11 > 0 else 1.0
            target_scale = self._quantize_base_raster_scale(
                self._scene_scale * view_transform_scale * self._device_pixel_ratio()
            )
        active_request_scale = self._base_raster_request_scale
        if (
            active_request_scale
            and abs(active_request_scale - target_scale) < 1e-6
            and self._base_correction_request_generation_id == generation_id
        ):
            return
        if (
            self._base_raster_scale
            and abs(self._base_raster_scale - target_scale) < 1e-6
        ):
            return
        self._request_optional_overlay_base_correction(target_scale, generation_id)

    def _evict_tile_keys(self, keys) -> None:
        keys = list(keys)
        if not keys:
            return
        for key in keys:
            item = self._tile_items.pop(key, None)
            if item:
                self._remove_tile_item(item)
            req_id = self._tile_requests.pop(key, None)
            if req_id:
                self._rendering_service.cancel_request(req_id)
        self._sync_low_res_base_visibility_for_tiles()
        self._sync_low_res_overlay_visibility_for_tiles()

    def _update_tile_coverage(self, view_m11: float) -> None:
        if not self._current_page:
            return
        if self._overlay_move_suppresses_normal_tiles():
            self._cancel_tile_requests()
            return
        overlay_pdf_tiles = self._uses_overlay_pdf_tiles()
        if not (self._can_zoom_rerender or overlay_pdf_tiles):
            return
        if self._disable_high_resolution_images:
            self._clear_tiles()
            self._cancel_optional_base_correction()
            if (
                self._primary_tiles_use_overlay_pdf()
                and abs((self._base_raster_scale or 0.0) - self._scene_scale) > 1e-6
            ):
                self._request_optional_overlay_base_correction(
                    self._scene_scale,
                    self._advance_render_generation(),
                )
            elif (
                self._can_zoom_rerender
                and self._background_item is not None
                and not self._is_composite_mode
                and abs((self._base_raster_scale or 0.0) - self._scene_scale) > 1e-6
            ):
                self._request_optional_base_correction(
                    self._scene_scale,
                    self._advance_render_generation(),
                )
            return
        generation_id = self._advance_render_generation()
        raw_scale = self._compute_tile_scale(view_m11)
        tile_scale = self._quantize_tile_scale(raw_scale)
        base_scale = self._base_raster_scale or self._scene_scale
        if tile_scale <= base_scale * self._TILE_ACTIVATE_RATIO:
            self._clear_tiles()
            if self._primary_tiles_use_overlay_pdf():
                self._update_optional_overlay_base_coverage(view_m11, generation_id)
            else:
                self._update_optional_base_coverage(view_m11, generation_id)
            return
        if tile_scale != self._tile_scale:
            self._tile_scale = tile_scale
            self._demote_old_scale_tiles()
        if (
            self._uses_both_overlay_pdf_tiles()
            and tile_scale != self._overlay_tile_scale
        ):
            self._overlay_tile_scale = tile_scale
            self._demote_old_scale_tiles()
        self._cancel_tile_requests()
        self._cancel_optional_base_correction()
        if self._primary_tiles_use_overlay_pdf():
            T = self._overlay_pdf_tile_transform()
        else:
            raster_width_pts, raster_height_pts = self._rendered_pdf_page_dimensions()
            W = raster_width_pts * self._scene_scale
            H = raster_height_pts * self._scene_scale
            T = self._get_page_transform(W, H)
        T_inv, invertible = T.inverted()
        viewport_polygon = self.mapToScene(self.viewport().rect())
        if invertible:
            viewport_local_rect = T_inv.map(viewport_polygon).boundingRect()
        else:
            viewport_local_rect = viewport_polygon.boundingRect()
        visible_keys, buffered_keys = self._partition_visible_and_buffered_tiles(
            viewport_local_rect,
            tile_scale,
        )
        needed_keys = visible_keys | buffered_keys
        self._evict_old_scale_tiles_outside(self._tile_keys_local_rect(needed_keys))
        self._evict_tiles_at_scale(tile_scale, needed_keys)
        for key in sorted(visible_keys, key=lambda k: (k.row, k.col)):
            self._request_tile(key, generation_id, _RENDER_PRIORITY_VISIBLE_TILE)
        for key in sorted(buffered_keys, key=lambda k: (k.row, k.col)):
            self._request_tile(key, generation_id, _RENDER_PRIORITY_BUFFERED_TILE)
        self._sync_low_res_base_visibility_for_tiles()
        if self._uses_both_overlay_pdf_tiles():
            overlay_transform = self._overlay_pdf_tile_transform()
            overlay_inv, overlay_invertible = overlay_transform.inverted()
            if overlay_invertible:
                overlay_viewport_local_rect = overlay_inv.map(
                    viewport_polygon
                ).boundingRect()
            else:
                overlay_viewport_local_rect = viewport_polygon.boundingRect()
            overlay_visible, overlay_buffered = (
                self._partition_visible_and_buffered_tiles(
                    overlay_viewport_local_rect,
                    tile_scale,
                    overlay=True,
                )
            )
            overlay_needed = overlay_visible | overlay_buffered
            self._evict_old_overlay_scale_tiles_outside(
                self._tile_keys_local_rect(overlay_needed, overlay=True)
            )
            self._evict_overlay_tiles_at_scale(tile_scale, overlay_needed)
            for key in sorted(overlay_visible, key=lambda k: (k.row, k.col)):
                self._request_overlay_tile(
                    key, generation_id, _RENDER_PRIORITY_VISIBLE_TILE
                )
            for key in sorted(overlay_buffered, key=lambda k: (k.row, k.col)):
                self._request_overlay_tile(
                    key, generation_id, _RENDER_PRIORITY_BUFFERED_TILE
                )
        if not self._tile_requests:
            self._evict_old_scale_tiles()

    def _partition_visible_and_buffered_tiles(
        self, viewport_local_rect: QRectF, tile_scale: float, overlay: bool = False
    ) -> tuple[Set[TileKey], Set[TileKey]]:
        visible_keys = self._compute_visible_tile_keys(
            viewport_local_rect, tile_scale, buffer=0, overlay=overlay
        )
        buffered_keys = (
            self._compute_visible_tile_keys(
                viewport_local_rect, tile_scale, buffer=1, overlay=overlay
            )
            - visible_keys
        )
        return visible_keys, buffered_keys

    def _cancel_pending_renders(self):
        for request_id in self._current_render_requests:
            self._rendering_service.cancel_request(request_id)
        self._current_render_requests.clear()
        self._cancel_pdf_text_extraction()
        self._pending_page_data = None
        self._deferred_page_visual_result = None
        self._cancel_tile_requests()
        self._cancel_optional_base_correction()
        for item in self._tile_items.values():
            self._remove_tile_item(item)
        self._tile_items.clear()
        for item in self._overlay_tile_items.values():
            self._remove_tile_item(item)
        self._overlay_tile_items.clear()
        self._tile_scale = 0.0
        self._overlay_tile_scale = 0.0
        self._set_low_res_base_item_visible(True)
        self._set_low_res_overlay_items_visible(True)
        self._zoom_debouncer.cancel()
