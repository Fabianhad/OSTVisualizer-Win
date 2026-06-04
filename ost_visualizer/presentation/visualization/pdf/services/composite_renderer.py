import math
from collections import OrderedDict
from typing import Optional
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from .....domain.entities.identity_refs import BidRef
from .....domain.entities.page import Page
from ...utils.image_effects import tint_image
from ..page_cache import PageCache

_COMPOSITE_CACHE_MAX_BYTES = 96 * 1024 * 1024
_COMPOSITE_CACHE_MAX_SINGLE_IMAGE_BYTES = 48 * 1024 * 1024
_NEAR_NATIVE_OVERLAY_SCALE_TOLERANCE = 0.0015


def _quantize_render_scale(scale: float) -> float:
    return max(0.1, round(scale, 3))


def _native_pdf_pixel_extent(points: float, scale: float) -> int:
    return int(points * scale + 0.5)


class CompositeRenderer:
    MAX_CACHE_SIZE = 10

    def __init__(self, page_cache: PageCache):
        self._page_cache = page_cache
        self._composite_cache: OrderedDict[str, QImage] = OrderedDict()

    def render_composite(
        self,
        page: Page,
        bid_ref: Optional[BidRef],
        render_scale: float,
        raster_rotation: int,
        cancelled_check=None,
    ) -> Optional[QImage]:
        cache_key = self._build_cache_key(page, bid_ref, render_scale, raster_rotation)
        if cache_key in self._composite_cache:
            self._composite_cache.move_to_end(cache_key)
            return self._composite_cache[cache_key]
        if cancelled_check and cancelled_check():
            return None
        red_tinted = self._page_cache.get_tinted_page(
            page.image_path,
            page.page_index,
            render_scale,
            raster_rotation,
            tint_rgb=(255, 80, 80),
        )
        if not red_tinted:
            return None
        if cancelled_check and cancelled_check():
            return None
        is_overlay_pdf = page.overlay_image_path.lower().endswith(".pdf")
        overlay_scale = 2.0 if is_overlay_pdf else 1.0
        blue_tinted = self._page_cache.get_tinted_page(
            page.overlay_image_path,
            0,
            overlay_scale,
            raster_rotation,
            tint_rgb=(80, 80, 255),
        )
        if not blue_tinted:
            return red_tinted
        if cancelled_check and cancelled_check():
            return None
        composited = self._composite_images(red_tinted, blue_tinted, page)
        self._store_composite(cache_key, composited)
        return composited

    @staticmethod
    def _build_cache_key(
        page: Page,
        bid_ref: Optional[BidRef],
        render_scale: float,
        raster_rotation: int,
    ) -> str:
        bid_file_path = bid_ref.file_path if bid_ref else ""
        bid_uid = bid_ref.bid_uid if bid_ref else ""
        return "|".join(
            [
                bid_file_path,
                bid_uid,
                page.uid,
                str(page.page_index),
                page.image_path or "",
                page.overlay_image_path or "",
                str(render_scale),
                str(raster_rotation),
                str(page.image_show_mode),
                str(page.layer_visible),
                str(page.overlay_rotation),
                str(page.deskew_rotation_overlay),
                str(page.overlay_rect),
            ]
        )

    def _composite_images(self, red: QImage, blue: QImage, page: Page) -> QImage:
        canvas_w = red.width()
        canvas_h = red.height()
        result = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32)
        result.fill(QColor(255, 255, 255))
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(0, 0, red)
        self._draw_overlay_image(painter, blue, page, canvas_w, canvas_h)
        painter.end()
        return result

    def _draw_overlay_image(
        self,
        painter: QPainter,
        overlay: QImage,
        page: Page,
        canvas_w: int,
        canvas_h: int,
    ) -> None:
        if overlay.width() <= 0 or overlay.height() <= 0:
            return
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_canvas(canvas_w, canvas_h)
        if rect_w <= 0.0 or rect_h <= 0.0:
            return
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        transform = self._build_transform(
            rect_x,
            rect_y,
            total_rotation,
            rect_w / overlay.width(),
            rect_h / overlay.height(),
        )
        painter.save()
        painter.setTransform(transform)
        painter.drawImage(0, 0, overlay)
        painter.restore()

    def _build_transform(
        self,
        translate_x: float,
        translate_y: float,
        rotation_radians: float,
        scale_x: float,
        scale_y: float,
    ) -> QTransform:
        transform = QTransform()
        transform.translate(translate_x, translate_y)
        if rotation_radians != 0:
            rotation_degrees = math.degrees(rotation_radians)
            transform.rotate(rotation_degrees)
        transform.scale(scale_x, scale_y)
        return transform

    def _evict_if_needed(self):
        while (
            len(self._composite_cache) > self.MAX_CACHE_SIZE
            or self._cache_size_bytes() > _COMPOSITE_CACHE_MAX_BYTES
        ):
            self._composite_cache.popitem(last=False)

    def _store_composite(self, cache_key: str, image: QImage) -> None:
        if self._image_size_bytes(image) > _COMPOSITE_CACHE_MAX_SINGLE_IMAGE_BYTES:
            return
        self._composite_cache[cache_key] = image
        self._composite_cache.move_to_end(cache_key)
        self._evict_if_needed()

    def _cache_size_bytes(self) -> int:
        return sum(
            self._image_size_bytes(image) for image in self._composite_cache.values()
        )

    @staticmethod
    def _image_size_bytes(image: QImage) -> int:
        if image.isNull():
            return 0
        return int(image.sizeInBytes())

    def render_composite_region(
        self,
        page: Page,
        scale: float,
        tile_x: int,
        tile_y: int,
        tile_w: int,
        tile_h: int,
        rotation: int,
        cancelled_check=None,
    ) -> Optional[QImage]:
        if tile_w <= 0 or tile_h <= 0:
            return None
        render_scale = _quantize_render_scale(scale)
        red_tile = self._page_cache.render_region_uncached(
            page.image_path,
            page.page_index,
            render_scale,
            tile_x,
            tile_y,
            tile_w,
            tile_h,
            rotation,
        )
        if not red_tile:
            return None
        red_tinted = tint_image(red_tile, 255, 80, 80)
        if cancelled_check and cancelled_check():
            return None
        if not page.overlay_image_path:
            return red_tinted
        source_w, source_h = self._page_cache.get_page_size(page.overlay_image_path, 0)
        canvas_w = _native_pdf_pixel_extent(page.effective_width_pts, render_scale)
        canvas_h = _native_pdf_pixel_extent(page.effective_height_pts, render_scale)
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_canvas(
            canvas_w,
            canvas_h,
        )
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        is_overlay_pdf = page.overlay_image_path.lower().endswith(".pdf")
        if is_overlay_pdf:
            overlay_scale = self._overlay_pdf_region_scale(
                source_w,
                source_h,
                rect_w,
                rect_h,
                total_rotation,
                render_scale,
            )
            source_width_px = _native_pdf_pixel_extent(source_w, overlay_scale)
            source_height_px = _native_pdf_pixel_extent(source_h, overlay_scale)
        else:
            native_w, _ = self._page_cache.get_page_size(page.overlay_image_path, 0)
            pdf_width_pts = page.width_pts
            overlay_scale = (
                native_w / pdf_width_pts
                if pdf_width_pts > 0 and native_w > 0
                else render_scale
            )
            source_width_px = int(source_w)
            source_height_px = int(source_h)
        if (
            source_width_px <= 0
            or source_height_px <= 0
            or rect_w <= 0.0
            or rect_h <= 0.0
        ):
            return red_tinted
        source_to_canvas = self._build_transform(
            rect_x,
            rect_y,
            total_rotation,
            rect_w / source_width_px,
            rect_h / source_height_px,
        )
        use_full_scale_integer_crop = self._is_unrotated_near_native_overlay(
            total_rotation,
            source_to_canvas,
        )
        if use_full_scale_integer_crop:
            source_crop_x = int(tile_x - rect_x)
            source_crop_y = int(tile_y - rect_y)
            source_x = max(0, min(source_width_px, source_crop_x))
            source_y = max(0, min(source_height_px, source_crop_y))
            source_w = min(tile_w, max(0, source_width_px - source_x))
            source_h = min(tile_h, max(0, source_height_px - source_y))
        else:
            canvas_to_source, ok = source_to_canvas.inverted()
            if not ok:
                return red_tinted
            canvas_tile_rect = QRectF(tile_x, tile_y, tile_w, tile_h)
            source_crop_rect = canvas_to_source.mapRect(canvas_tile_rect)
            source_crop_left = math.floor(source_crop_rect.left())
            source_crop_top = math.floor(source_crop_rect.top())
            source_crop_right = math.ceil(source_crop_rect.right())
            source_crop_bottom = math.ceil(source_crop_rect.bottom())
            source_x = max(0, min(source_width_px, source_crop_left))
            source_y = max(0, min(source_height_px, source_crop_top))
            source_right = max(0, min(source_width_px, source_crop_right))
            source_bottom = max(0, min(source_height_px, source_crop_bottom))
            source_w = source_right - source_x
            source_h = source_bottom - source_y
        if source_w <= 0 or source_h <= 0:
            return red_tinted
        blue_tile = self._page_cache.render_region_uncached(
            page.overlay_image_path,
            0,
            overlay_scale,
            source_x,
            source_y,
            source_w,
            source_h,
            rotation,
        )
        if not blue_tile:
            return red_tinted
        blue_tinted = tint_image(blue_tile, 80, 80, 255)
        result = QImage(
            red_tinted.width(),
            red_tinted.height(),
            QImage.Format.Format_ARGB32,
        )
        result.fill(QColor(255, 255, 255))
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(0, 0, red_tinted)
        if use_full_scale_integer_crop:
            dx = int(max(0, -source_crop_x))
            dy = int(max(0, -source_crop_y))
            painter.drawImage(dx, dy, blue_tinted)
        else:
            source_to_tile = self._source_crop_to_tile_transform(
                source_to_canvas,
                tile_x,
                tile_y,
                source_x,
                source_y,
            )
            painter.setTransform(source_to_tile)
            painter.drawImage(0, 0, blue_tinted)
        painter.end()
        return result

    def render_composite_frame(
        self,
        page: Page,
        scale: float,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        rotation: int,
        cancelled_check=None,
    ) -> Optional[QImage]:
        if frame_w_pts <= 0.0 or frame_h_pts <= 0.0:
            return None
        frame = self._clip_frame_to_page(
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            page.effective_width_pts,
            page.effective_height_pts,
        )
        if frame is None:
            return None
        frame_x, frame_y, frame_w, frame_h = frame
        render_scale = _quantize_render_scale(scale)
        red_frame = self._page_cache.render_frame_uncached(
            page.image_path,
            page.page_index,
            render_scale,
            frame_x,
            frame_y,
            frame_w,
            frame_h,
            rotation,
        )
        if not red_frame:
            return None
        red_tinted = tint_image(red_frame, 255, 80, 80)
        if cancelled_check and cancelled_check():
            return None
        result = QImage(
            red_tinted.width(),
            red_tinted.height(),
            QImage.Format.Format_ARGB32,
        )
        result.fill(QColor(255, 255, 255))
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(0, 0, red_tinted)
        if page.overlay_image_path:
            if page.overlay_image_path.lower().endswith(".pdf"):
                self._draw_overlay_pdf_frame(
                    painter,
                    page,
                    render_scale,
                    frame_x,
                    frame_y,
                    frame_w,
                    frame_h,
                    rotation,
                    cancelled_check,
                )
            else:
                blue = self._page_cache.get_tinted_page(
                    page.overlay_image_path,
                    0,
                    1.0,
                    rotation,
                    tint_rgb=(80, 80, 255),
                )
                if blue:
                    painter.save()
                    painter.scale(render_scale, render_scale)
                    painter.translate(-frame_x, -frame_y)
                    self._draw_overlay_image(
                        painter,
                        blue,
                        page,
                        page.effective_width_pts,
                        page.effective_height_pts,
                    )
                    painter.restore()
        painter.end()
        return result

    def _draw_overlay_pdf_frame(
        self,
        painter: QPainter,
        page: Page,
        render_scale: float,
        frame_x: float,
        frame_y: float,
        frame_w: float,
        frame_h: float,
        rotation: int,
        cancelled_check=None,
    ) -> None:
        source_w, source_h = self._page_cache.get_page_size(page.overlay_image_path, 0)
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_page_points()
        if source_w <= 0.0 or source_h <= 0.0 or rect_w <= 0.0 or rect_h <= 0.0:
            return
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        source_to_page = self._build_transform(
            rect_x,
            rect_y,
            total_rotation,
            rect_w / source_w,
            rect_h / source_h,
        )
        page_to_source, ok = source_to_page.inverted()
        if not ok:
            return
        frame_rect = QRectF(frame_x, frame_y, frame_w, frame_h)
        source_rect = page_to_source.mapRect(frame_rect)
        source_x = max(0.0, min(source_w, math.floor(source_rect.left())))
        source_y = max(0.0, min(source_h, math.floor(source_rect.top())))
        source_right = max(0.0, min(source_w, math.ceil(source_rect.right())))
        source_bottom = max(0.0, min(source_h, math.ceil(source_rect.bottom())))
        source_frame_w = source_right - source_x
        source_frame_h = source_bottom - source_y
        if source_frame_w <= 0.0 or source_frame_h <= 0.0:
            return
        overlay_scale = self._overlay_pdf_frame_scale(
            render_scale,
            rect_w / source_w,
            rect_h / source_h,
        )
        blue_frame = self._page_cache.render_frame_uncached(
            page.overlay_image_path,
            0,
            overlay_scale,
            source_x,
            source_y,
            source_frame_w,
            source_frame_h,
            rotation,
        )
        if cancelled_check and cancelled_check():
            return
        if not blue_frame:
            return
        blue_tinted = tint_image(blue_frame, 80, 80, 255)
        painter.save()
        transform = QTransform()
        transform.translate(-frame_x * render_scale, -frame_y * render_scale)
        transform.scale(render_scale, render_scale)
        transform *= source_to_page
        transform.translate(source_x, source_y)
        transform.scale(1.0 / overlay_scale, 1.0 / overlay_scale)
        painter.setTransform(transform)
        painter.drawImage(0, 0, blue_tinted)
        painter.restore()

    def _overlay_pdf_frame_scale(
        self, render_scale: float, scale_x: float, scale_y: float
    ) -> float:
        overlay_scale = render_scale * max(abs(scale_x), abs(scale_y))
        return _quantize_render_scale(max(0.1, overlay_scale))

    def _clip_frame_to_page(
        self,
        frame_x: float,
        frame_y: float,
        frame_w: float,
        frame_h: float,
        page_w: float,
        page_h: float,
    ) -> Optional[tuple[float, float, float, float]]:
        left = max(0.0, frame_x)
        top = max(0.0, frame_y)
        right = min(page_w, frame_x + frame_w)
        bottom = min(page_h, frame_y + frame_h)
        if right <= left or bottom <= top:
            return None
        return left, top, right - left, bottom - top

    def _is_unrotated_near_native_overlay(
        self,
        total_rotation: float,
        source_to_canvas: QTransform,
    ) -> bool:
        return (
            abs(total_rotation) < 1e-12
            and abs(source_to_canvas.m11() - 1.0)
            <= _NEAR_NATIVE_OVERLAY_SCALE_TOLERANCE
            and abs(source_to_canvas.m22() - 1.0)
            <= _NEAR_NATIVE_OVERLAY_SCALE_TOLERANCE
            and abs(source_to_canvas.m12()) < 1e-12
            and abs(source_to_canvas.m21()) < 1e-12
        )

    def _overlay_pdf_region_scale(
        self,
        source_w: float,
        source_h: float,
        rect_w: float,
        rect_h: float,
        total_rotation: float,
        fallback_scale: float,
    ) -> float:
        if (
            abs(total_rotation) >= 1e-12
            or source_w <= 0.0
            or source_h <= 0.0
            or rect_w <= 0.0
            or rect_h <= 0.0
        ):
            return fallback_scale
        scale_x = rect_w / source_w
        scale_y = rect_h / source_h
        if scale_x <= 0.0 or scale_y <= 0.0:
            return fallback_scale
        if abs(scale_x - scale_y) / max(scale_x, scale_y) > 0.001:
            return fallback_scale
        return _quantize_render_scale((scale_x + scale_y) / 2.0)

    def _source_crop_to_tile_transform(
        self,
        source_to_canvas: QTransform,
        tile_x: int,
        tile_y: int,
        source_x: int,
        source_y: int,
    ) -> QTransform:
        transform = QTransform(
            source_to_canvas.m11(),
            source_to_canvas.m12(),
            source_to_canvas.m13(),
            source_to_canvas.m21(),
            source_to_canvas.m22(),
            source_to_canvas.m23(),
            source_to_canvas.m31() - tile_x,
            source_to_canvas.m32() - tile_y,
            source_to_canvas.m33(),
        )
        transform.translate(source_x, source_y)
        return transform

    def clear_cache(self):
        self._composite_cache.clear()
