import logging
import math
import weakref
from typing import Any, Optional
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem
from shiboken6 import isValid
from .....application.dtos.render_result_dto import RenderResult
from .....domain.entities.page import Page
from .graphics_items import ImageBackgroundItem, TileGraphicsItem

logger = logging.getLogger(__name__)
_RENDER_PRIORITY_REQUIRED_PAGE = 0
_RENDER_PRIORITY_VISIBLE_FRAME = 1
_RENDER_PRIORITY_OPTIONAL_BASE = 3
_SHOW_MODE_OVERLAY_ONLY = 1
_PDF_FRAME_CURRENT_Z = 0.35
_OVERLAY_FRAME_CURRENT_Z = 0.65
_FRAME_SCALE_LOG_STEP = 0.125
_VISIBLE_FRAME_OVERSCAN_RATIO = 0.25
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
        self._sync_overlay_move_hidden_normal_visuals()

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
        self._sync_overlay_move_hidden_normal_visuals()

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
            self._sync_overlay_move_hidden_normal_visuals()

    def _sync_overlay_move_hidden_normal_visuals(self) -> None:
        if self._overlay_move_normal_visuals_hidden:
            self._hide_overlay_move_normal_visuals()
            self._set_overlay_move_preview_items_visible(True)

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

    def _compute_frame_scale(self, view_m11: float) -> float:
        display_scale = self._scene_scale * view_m11 * self._device_pixel_ratio()
        max_scale = self._scene_scale * self.MAX_ZOOM * self._device_pixel_ratio()
        return max(0.1, min(max_scale, display_scale))

    def _quantize_frame_scale(self, scale: float) -> float:
        if scale <= 1.0:
            return 1.0
        log_scale = math.log2(scale)
        quantized_log = (
            math.ceil((log_scale - 1e-9) / _FRAME_SCALE_LOG_STEP)
            * _FRAME_SCALE_LOG_STEP
        )
        return round(max(1.0, 2**quantized_log), 3)

    def _clear_tiles(self) -> None:
        self._clear_visible_frame()
        self._set_low_res_base_item_visible(True)
        self._set_low_res_overlay_items_visible(True)

    def _clear_tile_grid(self) -> None:
        self._clear_visible_frame()

    def _set_low_res_base_item_visible(self, visible: bool) -> None:
        if self._background_item is not None and isValid(self._background_item):
            self._background_item.setVisible(visible)

    def _sync_low_res_base_visibility_for_tiles(self) -> None:
        self._set_low_res_base_item_visible(True)

    def _set_low_res_overlay_items_visible(self, visible: bool) -> None:
        for item in self._overlay_items:
            if isValid(item):
                item.setVisible(visible)

    def _sync_low_res_overlay_visibility_for_tiles(self) -> None:
        if self._uses_overlay_pdf_tiles():
            self._set_low_res_overlay_items_visible(True)

    def _tiles_active(self) -> bool:
        return bool(
            self._visible_frame_item
            or self._visible_frame_request_id
            or self._visible_frame_scale > 0
        )

    def _cancel_high_res_frame_requests(self) -> None:
        self._cancel_visible_frame_request()

    def _cancel_visible_frame_request(self) -> None:
        if self._visible_frame_request_id:
            self._rendering_service.cancel_request(self._visible_frame_request_id)
        self._visible_frame_request_id = None
        self._pending_visible_frame_metadata = None
        self._restore_visible_frame_state_from_current_metadata()

    def _clear_visible_frame(self) -> None:
        self._cancel_visible_frame_request()
        if self._visible_frame_item is not None:
            self._remove_tile_item(self._visible_frame_item)
        self._visible_frame_item = None
        self._visible_frame_key = None
        self._visible_frame_metadata = None
        self._visible_frame_kind = None
        self._visible_frame_scale = 0.0

    def _visible_frame_overlay_state_key(self, page: Page, kind: str):
        if kind not in ("composite", "overlay"):
            return None
        overlay_rect = self._overlay_rect_tuple(page)
        if overlay_rect is None:
            return None
        return (
            page.overlay_image_path or "",
            tuple(round(value, 6) for value in overlay_rect),
            round(float(page.overlay_rotation or 0.0), 6),
            round(float(page.deskew_rotation_overlay or 0.0), 6),
        )

    def _visible_frame_render_identity_key(self):
        return tuple(
            sorted(
                (str(key), repr(value))
                for key, value in (self._current_render_identity or {}).items()
            )
        )

    @staticmethod
    def _visible_frame_rect_tuple(context: dict, prefix: str = "frame"):
        return (
            float(context[f"{prefix}_x_pts"]),
            float(context[f"{prefix}_y_pts"]),
            float(context[f"{prefix}_w_pts"]),
            float(context[f"{prefix}_h_pts"]),
        )

    @staticmethod
    def _visible_frame_rect_contains(outer, inner) -> bool:
        epsilon = 1e-3
        outer_x, outer_y, outer_w, outer_h = outer
        inner_x, inner_y, inner_w, inner_h = inner
        return (
            outer_x <= inner_x + epsilon
            and outer_y <= inner_y + epsilon
            and outer_x + outer_w + epsilon >= inner_x + inner_w
            and outer_y + outer_h + epsilon >= inner_y + inner_h
        )

    def _visible_frame_metadata_from_context(self, context: dict) -> dict:
        return {
            "identity": context["identity"],
            "key": context["key"],
            "kind": context["kind"],
            "page_uid": context["page_uid"],
            "file_path": context["file_path"],
            "page_index": context["page_index"],
            "scale": context["scale"],
            "render_scale": context["scale"],
            "rotation": context["rotation"],
            "render_identity": context["render_identity"],
            "overlay_state_key": context["overlay_state_key"],
            "source_dimensions": (
                context["source_w_pts"],
                context["source_h_pts"],
            ),
            "frame_rect": self._visible_frame_rect_tuple(context, "frame"),
            "visible_rect": self._visible_frame_rect_tuple(context, "visible"),
        }

    def _visible_frame_metadata_covers(self, metadata: Optional[dict], context: dict):
        if not metadata:
            return False
        if metadata.get("identity") != context["identity"]:
            return False
        return self._visible_frame_rect_contains(
            metadata.get("frame_rect", (0.0, 0.0, 0.0, 0.0)),
            self._visible_frame_rect_tuple(context, "visible"),
        )

    def _restore_visible_frame_state_from_current_metadata(self) -> None:
        if self._visible_frame_metadata is None:
            self._visible_frame_key = None
            self._visible_frame_kind = None
            self._visible_frame_scale = 0.0
            return
        self._visible_frame_key = self._visible_frame_metadata.get("key")
        self._visible_frame_kind = self._visible_frame_metadata.get("kind")
        self._visible_frame_scale = self._visible_frame_metadata.get("scale", 0.0)

    def _visible_frame_item_transform(self, context: dict) -> QTransform:
        if context["kind"] == "overlay":
            return self._overlay_pdf_tile_transform()
        return self._get_page_transform(
            context["source_w_pts"] * self._scene_scale,
            context["source_h_pts"] * self._scene_scale,
        )

    def _visible_frame_local_rect(self, context: dict, image) -> QRectF:
        scale = context["scale"]
        frame_scene_x = round(context["frame_x_pts"] * self._scene_scale)
        frame_scene_y = round(context["frame_y_pts"] * self._scene_scale)
        frame_scene_w = round(float(image.width()) * self._scene_scale / scale)
        frame_scene_h = round(float(image.height()) * self._scene_scale / scale)
        return QRectF(
            float(frame_scene_x),
            float(frame_scene_y),
            float(max(1, frame_scene_w)),
            float(max(1, frame_scene_h)),
        )

    def _build_visible_frame_context(self, frame_scale: float) -> Optional[dict]:
        page = self._current_page
        viewport = self.viewport()
        if (
            page is None
            or viewport is None
            or not viewport.rect().isValid()
            or frame_scale <= 0.0
        ):
            return None
        if self._is_composite_mode:
            kind = "composite"
            file_path = page.image_path
            page_index = page.page_index
            rotation = _PLAN_VIEW_RASTER_ROTATION
            source_w_pts, source_h_pts = self._rendered_pdf_page_dimensions()
            transform = self._get_page_transform(
                source_w_pts * self._scene_scale,
                source_h_pts * self._scene_scale,
            )
        elif (
            self._primary_tiles_use_overlay_pdf() or self._uses_both_overlay_pdf_tiles()
        ):
            kind = "overlay"
            file_path = page.overlay_image_path
            page_index = 0
            rotation = self._active_page_raster_rotation()
            source_w_pts, source_h_pts = self._overlay_tile_raster_dimensions()
            transform = self._overlay_pdf_tile_transform()
        elif self._can_zoom_rerender:
            kind = "base"
            file_path = page.image_path
            page_index = page.page_index
            rotation = _PLAN_VIEW_RASTER_ROTATION
            source_w_pts, source_h_pts = self._rendered_pdf_page_dimensions()
            transform = self._get_page_transform(
                source_w_pts * self._scene_scale,
                source_h_pts * self._scene_scale,
            )
        else:
            return None
        if (
            not file_path
            or source_w_pts <= 0.0
            or source_h_pts <= 0.0
            or self._scene_scale <= 0.0
        ):
            return None
        transform_inv, invertible = transform.inverted()
        viewport_polygon = self.mapToScene(viewport.rect())
        if invertible:
            viewport_local_rect = transform_inv.map(viewport_polygon).boundingRect()
        else:
            viewport_local_rect = viewport_polygon.boundingRect()
        source_local_rect = QRectF(
            0.0,
            0.0,
            source_w_pts * self._scene_scale,
            source_h_pts * self._scene_scale,
        )
        visible_local_rect = viewport_local_rect.intersected(source_local_rect)
        if visible_local_rect.isNull() or visible_local_rect.isEmpty():
            return None
        visible_x_pts = visible_local_rect.left() / self._scene_scale
        visible_y_pts = visible_local_rect.top() / self._scene_scale
        visible_w_pts = visible_local_rect.width() / self._scene_scale
        visible_h_pts = visible_local_rect.height() / self._scene_scale
        if visible_w_pts <= 0.0 or visible_h_pts <= 0.0:
            return None
        buffer_w_pts = visible_w_pts * _VISIBLE_FRAME_OVERSCAN_RATIO
        buffer_h_pts = visible_h_pts * _VISIBLE_FRAME_OVERSCAN_RATIO
        frame_x_pts = max(0.0, visible_x_pts - buffer_w_pts)
        frame_y_pts = max(0.0, visible_y_pts - buffer_h_pts)
        frame_right_pts = min(
            source_w_pts, visible_x_pts + visible_w_pts + buffer_w_pts
        )
        frame_bottom_pts = min(
            source_h_pts, visible_y_pts + visible_h_pts + buffer_h_pts
        )
        frame_w_pts = frame_right_pts - frame_x_pts
        frame_h_pts = frame_bottom_pts - frame_y_pts
        if frame_w_pts <= 0.0 or frame_h_pts <= 0.0:
            return None
        overlay_state_key = self._visible_frame_overlay_state_key(page, kind)
        render_identity = self._visible_frame_render_identity_key()
        identity = (
            kind,
            page.uid,
            file_path,
            page_index,
            round(frame_scale, 3),
            rotation,
            render_identity,
            overlay_state_key,
            round(source_w_pts, 3),
            round(source_h_pts, 3),
        )
        key = (
            kind,
            file_path,
            page_index,
            round(frame_scale, 3),
            rotation,
            page.uid,
            round(frame_x_pts, 3),
            round(frame_y_pts, 3),
            round(frame_w_pts, 3),
            round(frame_h_pts, 3),
            overlay_state_key,
        )
        return {
            "kind": kind,
            "page_uid": page.uid,
            "file_path": file_path,
            "page_index": page_index,
            "scale": frame_scale,
            "rotation": rotation,
            "render_identity": render_identity,
            "overlay_state_key": overlay_state_key,
            "frame_x_pts": frame_x_pts,
            "frame_y_pts": frame_y_pts,
            "frame_w_pts": frame_w_pts,
            "frame_h_pts": frame_h_pts,
            "visible_x_pts": visible_x_pts,
            "visible_y_pts": visible_y_pts,
            "visible_w_pts": visible_w_pts,
            "visible_h_pts": visible_h_pts,
            "source_w_pts": source_w_pts,
            "source_h_pts": source_h_pts,
            "identity": identity,
            "key": key,
        }

    def _request_visible_frame(self, context: dict) -> None:
        if (
            self._visible_frame_item is not None
            and self._visible_frame_metadata_covers(
                self._visible_frame_metadata, context
            )
        ):
            if (
                self._visible_frame_request_id is not None
                and not self._visible_frame_metadata_covers(
                    self._pending_visible_frame_metadata, context
                )
            ):
                self._cancel_visible_frame_request()
            self._sync_low_res_base_visibility_for_tiles()
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        if (
            self._visible_frame_request_id is not None
            and self._visible_frame_metadata_covers(
                self._pending_visible_frame_metadata, context
            )
        ):
            self._sync_low_res_base_visibility_for_tiles()
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        page = self._current_page
        if page is None:
            return
        self._cancel_visible_frame_request()
        generation_id = self._advance_render_generation()
        metadata = self._visible_frame_metadata_from_context(context)
        key = context["key"]
        self._visible_frame_key = key
        self._visible_frame_kind = context["kind"]
        self._visible_frame_scale = context["scale"]
        self._pending_visible_frame_metadata = metadata
        self._sync_low_res_base_visibility_for_tiles()
        self._sync_low_res_overlay_visibility_for_tiles()
        load_token = self._current_load_token
        render_identity = dict(self._current_render_identity or {})
        weak_self = weakref.ref(self)

        def on_frame_loaded(result: RenderResult) -> None:
            view = weak_self()
            if view is not None:
                view._on_visible_frame_loaded(
                    result,
                    dict(context),
                    load_token,
                    render_identity,
                    generation_id,
                )

        if context["kind"] == "composite":
            request_id = self._rendering_service.render_composite_frame_async(
                page=page,
                bid_ref=self._current_bid_ref,
                scale=context["scale"],
                rotation=context["rotation"],
                frame_x_pts=context["frame_x_pts"],
                frame_y_pts=context["frame_y_pts"],
                frame_w_pts=context["frame_w_pts"],
                frame_h_pts=context["frame_h_pts"],
                callback=on_frame_loaded,
                priority=_RENDER_PRIORITY_VISIBLE_FRAME,
            )
        else:
            tint_rgb = None
            if (
                context["kind"] == "base"
                and page.image_show_mode == 2
                and page.has_overlay
            ):
                tint_rgb = (255, 80, 80)
            elif context["kind"] == "overlay" and page.image_show_mode == 2:
                tint_rgb = (80, 80, 255)
            request_id = self._rendering_service.render_frame_async(
                file_path=context["file_path"],
                page_index=context["page_index"],
                scale=context["scale"],
                rotation=context["rotation"],
                frame_x_pts=context["frame_x_pts"],
                frame_y_pts=context["frame_y_pts"],
                frame_w_pts=context["frame_w_pts"],
                frame_h_pts=context["frame_h_pts"],
                callback=on_frame_loaded,
                priority=_RENDER_PRIORITY_VISIBLE_FRAME,
                invert=page.invert,
                bitonal=page.bitonal,
                tint_rgb=tint_rgb,
            )
        self._visible_frame_request_id = request_id

    def _on_visible_frame_loaded(
        self,
        result: RenderResult,
        context: dict,
        load_token: str,
        render_identity,
        generation_id: int,
    ) -> None:
        if self._visible_frame_request_id != result.request_id:
            return
        if not self._is_current_async_result(load_token, render_identity):
            return
        self._visible_frame_request_id = None
        if (
            self._is_stale_generation(generation_id)
            or self._overlay_move_suppresses_normal_tiles()
            or self._visible_frame_key != context["key"]
            or not result.success
            or not result.image
        ):
            self._pending_visible_frame_metadata = None
            self._restore_visible_frame_state_from_current_metadata()
            self._sync_low_res_base_visibility_for_tiles()
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        old_item = self._visible_frame_item
        image = result.image
        scale = context["scale"]
        item_transform = self._visible_frame_item_transform(context)
        local_rect = self._visible_frame_local_rect(context, image)
        item = TileGraphicsItem(
            image,
            local_rect,
            QRectF(0.0, 0.0, float(image.width()), float(image.height())),
        )
        if context["kind"] == "overlay":
            item.setZValue(_OVERLAY_FRAME_CURRENT_Z)
        else:
            item.setZValue(_PDF_FRAME_CURRENT_Z)
        item.setTransform(item_transform)
        self._scene.addItem(item)
        self._visible_frame_item = item
        self._visible_frame_metadata = self._visible_frame_metadata_from_context(
            context
        )
        self._pending_visible_frame_metadata = None
        self._visible_frame_kind = context["kind"]
        self._visible_frame_scale = scale
        if old_item is not None:
            self._remove_tile_item(old_item)
        self._sync_low_res_base_visibility_for_tiles()
        self._sync_low_res_overlay_visibility_for_tiles()

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

    def _update_tile_coverage(self, view_m11: float) -> None:
        if not self._current_page:
            return
        if self._overlay_move_suppresses_normal_tiles():
            self._clear_tiles()
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
        raw_scale = self._compute_frame_scale(view_m11)
        frame_scale = self._quantize_frame_scale(raw_scale)
        base_scale = self._base_raster_scale or self._scene_scale
        if frame_scale <= base_scale * self._FRAME_ACTIVATE_RATIO:
            self._clear_tiles()
            generation_id = self._advance_render_generation()
            if self._primary_tiles_use_overlay_pdf():
                self._update_optional_overlay_base_coverage(view_m11, generation_id)
            else:
                self._update_optional_base_coverage(view_m11, generation_id)
            return
        self._cancel_optional_base_correction()
        context = self._build_visible_frame_context(frame_scale)
        if context is None:
            self._clear_visible_frame()
            self._sync_low_res_base_visibility_for_tiles()
            self._sync_low_res_overlay_visibility_for_tiles()
            return
        self._request_visible_frame(context)

    def _cancel_pending_renders(self):
        for request_id in self._current_render_requests:
            self._rendering_service.cancel_request(request_id)
        self._current_render_requests.clear()
        self._cancel_pdf_text_extraction()
        self._pending_page_data = None
        self._deferred_page_visual_result = None
        self._cancel_high_res_frame_requests()
        self._cancel_optional_base_correction()
        if self._visible_frame_item is not None:
            self._remove_tile_item(self._visible_frame_item)
        self._visible_frame_item = None
        self._visible_frame_key = None
        self._visible_frame_metadata = None
        self._pending_visible_frame_metadata = None
        self._visible_frame_kind = None
        self._visible_frame_scale = 0.0
        self._set_low_res_base_item_visible(True)
        self._set_low_res_overlay_items_visible(True)
        self._zoom_debouncer.cancel()
