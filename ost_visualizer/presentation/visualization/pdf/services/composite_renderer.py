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
        red_tile = self._page_cache.render_region_uncached(
            page.image_path,
            page.page_index,
            scale,
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
        is_overlay_pdf = page.overlay_image_path.lower().endswith(".pdf")
        pdf_width_pts = page.width_pts
        if is_overlay_pdf:
            overlay_scale = scale
        else:
            native_w, _ = self._page_cache.get_page_size(page.overlay_image_path, 0)
            overlay_scale = (
                native_w / pdf_width_pts
                if pdf_width_pts > 0 and native_w > 0
                else scale
            )
        source_w, source_h = self._page_cache.get_page_size(page.overlay_image_path, 0)
        source_w_px = source_w * overlay_scale
        source_h_px = source_h * overlay_scale
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_canvas(
            page.effective_width_pts * scale,
            page.effective_height_pts * scale,
        )
        if source_w_px <= 0.0 or source_h_px <= 0.0 or rect_w <= 0.0 or rect_h <= 0.0:
            return red_tinted
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        source_to_canvas = self._build_transform(
            rect_x,
            rect_y,
            total_rotation,
            rect_w / source_w_px,
            rect_h / source_h_px,
        )
        canvas_to_source, ok = source_to_canvas.inverted()
        if not ok:
            return red_tinted
        source_rect = canvas_to_source.mapRect(QRectF(tile_x, tile_y, tile_w, tile_h))
        ov_src_x = math.floor(source_rect.left())
        ov_src_y = math.floor(source_rect.top())
        ov_src_right = math.ceil(source_rect.right())
        ov_src_bottom = math.ceil(source_rect.bottom())
        source_w_px_int = int(math.ceil(source_w_px))
        source_h_px_int = int(math.ceil(source_h_px))
        source_x = max(0, min(source_w_px_int, ov_src_x))
        source_y = max(0, min(source_h_px_int, ov_src_y))
        source_right = max(0, min(source_w_px_int, ov_src_right))
        source_bottom = max(0, min(source_h_px_int, ov_src_bottom))
        ov_src_w = source_right - source_x
        ov_src_h = source_bottom - source_y
        if ov_src_w <= 0 or ov_src_h <= 0:
            return red_tinted
        blue_tile = self._page_cache.render_region_uncached(
            page.overlay_image_path,
            0,
            overlay_scale,
            source_x,
            source_y,
            ov_src_w,
            ov_src_h,
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
        source_to_tile = QTransform(
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
        painter.setTransform(source_to_tile)
        painter.drawImage(source_x, source_y, blue_tinted)
        painter.end()
        return result

    def clear_cache(self):
        self._composite_cache.clear()
