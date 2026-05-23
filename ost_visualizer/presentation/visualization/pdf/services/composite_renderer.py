import math
from collections import OrderedDict
from typing import Optional
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
                str(page.overlay_offset_x),
                str(page.overlay_offset_y),
                str(page.overlay_rotation),
                str(page.deskew_rotation_overlay),
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
        pdf_width_pts = page.width_pts
        pdf_height_pts = page.height_pts
        view_scale = canvas_w / pdf_width_pts if pdf_width_pts > 0 else 1.0
        expected_width = pdf_width_pts * view_scale
        expected_height = pdf_height_pts * view_scale
        overlay_scale = self._calculate_overlay_scale(
            blue.width(), blue.height(), expected_width, expected_height
        )
        offset_x = page.overlay_offset_x * 72 * view_scale
        offset_y = page.overlay_offset_y * 72 * view_scale
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        transform = self._build_transform(
            offset_x, offset_y, total_rotation, overlay_scale
        )
        painter.save()
        painter.setTransform(transform)
        painter.drawImage(0, 0, blue)
        painter.restore()
        painter.end()
        return result

    def _calculate_overlay_scale(
        self, overlay_w: float, overlay_h: float, expected_w: float, expected_h: float
    ) -> float:
        if overlay_w <= 0 or overlay_h <= 0:
            return 1.0
        scale_x = expected_w / overlay_w
        scale_y = expected_h / overlay_h
        return min(scale_x, scale_y)

    def _build_transform(
        self, offset_x: float, offset_y: float, rotation_radians: float, scale: float
    ) -> QTransform:
        transform = QTransform()
        transform.translate(offset_x, offset_y)
        if rotation_radians != 0:
            rotation_degrees = math.degrees(rotation_radians)
            transform.rotate(rotation_degrees)
        if scale != 1.0:
            transform.scale(scale, scale)
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
        overlay_offset_x = page.overlay_offset_x * 72 * scale
        overlay_offset_y = page.overlay_offset_y * 72 * scale
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        ov_tile_x = tile_x - overlay_offset_x
        ov_tile_y = tile_y - overlay_offset_y
        if total_rotation != 0:
            cx = ov_tile_x + tile_w / 2
            cy = ov_tile_y + tile_h / 2
            cos_a = math.cos(-total_rotation)
            sin_a = math.sin(-total_rotation)
            ov_tile_x = cx * cos_a - cy * sin_a - tile_w / 2
            ov_tile_y = cx * sin_a + cy * cos_a - tile_h / 2
        ov_src_x = int(ov_tile_x * overlay_scale / scale)
        ov_src_y = int(ov_tile_y * overlay_scale / scale)
        ov_src_w = int(tile_w * overlay_scale / scale)
        ov_src_h = int(tile_h * overlay_scale / scale)
        if ov_src_w <= 0 or ov_src_h <= 0:
            return red_tinted
        blue_tile = self._page_cache.render_region_uncached(
            page.overlay_image_path,
            0,
            overlay_scale,
            max(0, ov_src_x),
            max(0, ov_src_y),
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
        dx = max(0, -ov_src_x) * scale / overlay_scale if ov_src_x < 0 else 0
        dy = max(0, -ov_src_y) * scale / overlay_scale if ov_src_y < 0 else 0
        painter.drawImage(int(dx), int(dy), blue_tinted)
        painter.end()
        return result

    def clear_cache(self):
        self._composite_cache.clear()
