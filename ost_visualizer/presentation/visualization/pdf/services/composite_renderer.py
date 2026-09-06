import math
from dataclasses import replace
from typing import Optional
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from .....application.render_quality import (
    RASTER_NATIVE_RENDER_SCALE,
    align_rendered_frame_origin,
    baseline_render_scale,
    quantize_constrained_render_scale,
)
from .....domain.entities.file_extensions import (
    TIFF_EXTENSIONS,
    is_pdf_suffix,
    normalized_suffix,
)
from .....domain.entities.identity_refs import BidRef
from .....domain.entities.page import Page
from ...utils.image_effects import tint_image
from ..page_cache import PageCache


class CompositeRenderer:
    def __init__(self, page_cache: PageCache):
        self._page_cache = page_cache

    def render_composite(
        self,
        page: Page,
        bid_ref: Optional[BidRef],
        render_scale: float,
        raster_rotation: int,
        cancelled_check=None,
        wait_for_in_flight: bool = True,
    ) -> Optional[QImage]:
        page = replace(
            page,
            overlay_rect=(
                tuple(page.overlay_rect) if page.overlay_rect is not None else None
            ),
        )
        cache_key = self._build_cache_key(page, bid_ref, render_scale, raster_rotation)
        return self._page_cache.get_composite(
            cache_key,
            lambda: self._render_composite_sources(
                page, render_scale, raster_rotation, cancelled_check, wait_for_in_flight
            ),
            cancelled_check=cancelled_check,
            is_current=lambda: self._build_cache_key(
                page, bid_ref, render_scale, raster_rotation
            )
            == cache_key,
            wait_for_in_flight=wait_for_in_flight,
        )

    def _render_composite_sources(
        self, page, render_scale, raster_rotation, cancelled_check, wait_for_in_flight
    ) -> tuple[Optional[QImage], bool]:
        if cancelled_check and cancelled_check():
            return None, False
        red_tinted = self._get_tinted_page(
            page.image_path,
            page.page_index,
            render_scale,
            raster_rotation,
            (255, 80, 80),
            wait_for_in_flight,
        )
        if not red_tinted:
            return None, False
        if cancelled_check and cancelled_check():
            return None, False
        is_overlay_pdf = is_pdf_suffix(page.overlay_image_path)
        overlay_scale = baseline_render_scale(is_pdf=is_overlay_pdf)
        blue_tinted = self._get_tinted_page(
            page.overlay_image_path,
            0,
            overlay_scale,
            raster_rotation,
            (80, 80, 255),
            wait_for_in_flight,
        )
        if not blue_tinted:
            return red_tinted, False
        if cancelled_check and cancelled_check():
            return None, False
        composited = self._composite_images(red_tinted, blue_tinted, page)
        if cancelled_check and cancelled_check():
            return None, False
        return composited, True

    def render_overlay_only(
        self, page: Page, render_scale: float, *, tint_rgb=None
    ) -> Optional[QImage]:
        page = replace(
            page,
            overlay_rect=(
                tuple(page.overlay_rect) if page.overlay_rect is not None else None
            ),
        )
        tint_rgb = tuple(tint_rgb) if tint_rgb is not None else None
        key = self._overlay_cache_key(page, render_scale, tint_rgb)
        return self._page_cache.get_composite(
            key,
            lambda: self._render_overlay_canvas(page, render_scale, tint_rgb),
            is_current=lambda: self._overlay_cache_key(page, render_scale, tint_rgb)
            == key,
        )

    def _overlay_cache_key(self, page: Page, render_scale: float, tint_rgb) -> tuple:
        return (
            "overlay-only",
            page.uid,
            page.overlay_image_path,
            self._page_cache.file_signature(page.overlay_image_path),
            max(1, round(page.effective_width_pts * render_scale)),
            max(1, round(page.effective_height_pts * render_scale)),
            page.effective_width_pts,
            page.effective_height_pts,
            page.overlay_rect,
            page.overlay_units_per_sheet_inch,
            page.overlay_rotation,
            page.deskew_rotation_overlay,
            tint_rgb,
        )

    def _render_overlay_canvas(
        self, page: Page, render_scale: float, tint_rgb
    ) -> tuple[Optional[QImage], bool]:
        overlay_scale = baseline_render_scale(
            is_pdf=is_pdf_suffix(page.overlay_image_path)
        )
        if tint_rgb is None:
            overlay = self._page_cache.get_page(
                page.overlay_image_path, 0, overlay_scale, 0
            )
        else:
            overlay = self._page_cache.get_tinted_page(
                page.overlay_image_path, 0, overlay_scale, 0, tint_rgb=tint_rgb
            )
        if overlay is None or overlay.isNull():
            return None, False
        canvas_w = max(1, round(page.effective_width_pts * render_scale))
        canvas_h = max(1, round(page.effective_height_pts * render_scale))
        result = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32)
        result.fill(QColor(255, 255, 255))
        painter = QPainter(result)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._draw_overlay_image(painter, overlay, page, canvas_w, canvas_h)
        finally:
            painter.end()
        return result, True

    def _build_cache_key(
        self,
        page: Page,
        bid_ref: Optional[BidRef],
        render_scale: float,
        raster_rotation: int,
    ) -> tuple:
        bid_file_path = bid_ref.file_path if bid_ref else ""
        bid_uid = bid_ref.bid_uid if bid_ref else ""
        base_signature = self._page_cache.file_signature(page.image_path)
        overlay_signature = (
            self._page_cache.file_signature(page.overlay_image_path)
            if page.overlay_image_path
            else None
        )
        return tuple(
            [
                bid_file_path,
                bid_uid,
                page.uid,
                str(page.page_index),
                page.image_path or "",
                repr(base_signature),
                page.overlay_image_path or "",
                repr(overlay_signature),
                str(quantize_constrained_render_scale(render_scale)),
                str(raster_rotation),
                str(page.image_show_mode),
                str(page.layer_visible),
                str(page.overlay_rotation),
                str(page.deskew_rotation_overlay),
                str(page.overlay_rect),
                str(page.overlay_units_per_sheet_inch),
                str(page.effective_width_pts),
                str(page.effective_height_pts),
            ]
        )

    def _get_page(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        rotation: int,
        wait_for_in_flight: bool,
    ) -> Optional[QImage]:
        return self._page_cache.get_page(
            file_path,
            page_index,
            scale,
            rotation,
            wait_for_in_flight=wait_for_in_flight,
        )

    def _get_tinted_page(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        rotation: int,
        tint_rgb: tuple[int, int, int],
        wait_for_in_flight: bool,
    ) -> Optional[QImage]:
        return self._page_cache.get_tinted_page(
            file_path,
            page_index,
            scale,
            rotation,
            tint_rgb=tint_rgb,
            wait_for_in_flight=wait_for_in_flight,
        )

    def _get_frame(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        frame_x: float,
        frame_y: float,
        frame_w: float,
        frame_h: float,
        rotation: int,
        wait_for_in_flight: bool,
    ) -> Optional[QImage]:
        return self._page_cache.get_frame(
            file_path,
            page_index,
            scale,
            frame_x,
            frame_y,
            frame_w,
            frame_h,
            rotation,
            wait_for_in_flight=wait_for_in_flight,
        )

    def _composite_images(self, red: QImage, blue: QImage, page: Page) -> QImage:
        canvas_w = red.width()
        canvas_h = red.height()
        result = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32)
        result.fill(QColor(255, 255, 255))
        painter = QPainter(result)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(0, 0, red)
            self._draw_overlay_image(painter, blue, page, canvas_w, canvas_h)
        finally:
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
        wait_for_in_flight: bool = True,
    ) -> Optional[QImage]:
        page = replace(
            page,
            overlay_rect=(
                tuple(page.overlay_rect) if page.overlay_rect is not None else None
            ),
        )

        def render():
            return self._render_composite_frame_sources(
                page,
                scale,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
                rotation,
                cancelled_check,
                wait_for_in_flight,
            )

        if not (
            is_pdf_suffix(page.image_path)
            and (
                is_pdf_suffix(page.overlay_image_path)
                or normalized_suffix(page.overlay_image_path) in TIFF_EXTENSIONS
            )
        ):
            return render()[0]
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

        def key():
            return (
                "pdf-frame",
                self._build_cache_key(page, None, scale, rotation),
                frame,
            )

        cache_key = key()
        return self._page_cache.get_composite(
            cache_key,
            render,
            cancelled_check=cancelled_check,
            is_current=lambda: key() == cache_key,
            wait_for_in_flight=wait_for_in_flight,
        )

    def _render_composite_frame_sources(
        self,
        page: Page,
        scale: float,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        rotation: int,
        cancelled_check=None,
        wait_for_in_flight: bool = True,
    ) -> tuple[Optional[QImage], bool]:
        if frame_w_pts <= 0.0 or frame_h_pts <= 0.0:
            return None, False
        frame = self._clip_frame_to_page(
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            page.effective_width_pts,
            page.effective_height_pts,
        )
        if frame is None:
            return None, False
        frame_x, frame_y, frame_w, frame_h = frame
        render_scale = quantize_constrained_render_scale(scale)
        red_frame = self._get_frame(
            page.image_path,
            page.page_index,
            render_scale,
            frame_x,
            frame_y,
            frame_w,
            frame_h,
            rotation,
            wait_for_in_flight,
        )
        if not red_frame:
            return None, False
        red_tinted = tint_image(red_frame, 255, 80, 80)
        if cancelled_check and cancelled_check():
            return None, False
        result = QImage(
            red_tinted.width(),
            red_tinted.height(),
            QImage.Format.Format_ARGB32,
        )
        result.fill(QColor(255, 255, 255))
        complete = False
        painter = QPainter(result)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(0, 0, red_tinted)
            if page.overlay_image_path:
                if is_pdf_suffix(page.overlay_image_path):
                    complete = self._draw_overlay_pdf_frame(
                        painter,
                        page,
                        render_scale,
                        frame_x,
                        frame_y,
                        frame_w,
                        frame_h,
                        rotation,
                        cancelled_check,
                        wait_for_in_flight,
                    )
                else:
                    complete = self._draw_overlay_raster_frame(
                        painter,
                        page,
                        render_scale,
                        frame_x,
                        frame_y,
                        frame_w,
                        frame_h,
                        rotation,
                        cancelled_check,
                        wait_for_in_flight,
                    )
        finally:
            painter.end()
        if cancelled_check and cancelled_check():
            return None, False
        return result, complete

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
        wait_for_in_flight: bool = True,
    ) -> bool:
        source_w, source_h = self._page_cache.get_page_size(page.overlay_image_path, 0)
        context = self._build_overlay_frame_context(
            page,
            source_w,
            source_h,
            render_scale,
            frame_x,
            frame_y,
            frame_w,
            frame_h,
        )
        if context is None:
            return False
        blue_frame = self._get_frame(
            page.overlay_image_path,
            0,
            context["overlay_scale"],
            context["source_x"],
            context["source_y"],
            context["source_frame_w"],
            context["source_frame_h"],
            rotation,
            wait_for_in_flight,
        )
        if not blue_frame:
            return False
        if cancelled_check and cancelled_check():
            return False
        blue_tinted = tint_image(blue_frame, 80, 80, 255)
        painter.save()
        painter.setTransform(context["transform"])
        painter.drawImage(0, 0, blue_tinted)
        painter.restore()
        return True

    def _draw_overlay_raster_frame(
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
        wait_for_in_flight: bool = True,
    ) -> bool:
        source_w, source_h = self._page_cache.get_page_size(page.overlay_image_path, 0)
        context = self._build_overlay_frame_context(
            page,
            source_w,
            source_h,
            render_scale,
            frame_x,
            frame_y,
            frame_w,
            frame_h,
            image_scale=RASTER_NATIVE_RENDER_SCALE,
        )
        if context is None:
            self._draw_overlay_raster_fallback(
                painter,
                page,
                render_scale,
                frame_x,
                frame_y,
                rotation,
                wait_for_in_flight,
            )
            return False
        if cancelled_check and cancelled_check():
            return False
        blue_source = self._get_page(
            page.overlay_image_path,
            0,
            context["overlay_scale"],
            rotation,
            wait_for_in_flight,
        )
        if not blue_source:
            return False
        source_x = context["source_x"]
        source_y = context["source_y"]
        source_frame_w = context["source_frame_w"]
        source_frame_h = context["source_frame_h"]
        overlay_scale = context["overlay_scale"]
        source_left = max(0.0, source_x * overlay_scale)
        source_top = max(0.0, source_y * overlay_scale)
        source_right = max(
            source_left,
            (source_x + source_frame_w) * overlay_scale,
        )
        source_bottom = max(
            source_top,
            (source_y + source_frame_h) * overlay_scale,
        )
        source_left_i = max(
            0,
            min(blue_source.width(), int(math.floor(source_left))),
        )
        source_top_i = max(
            0,
            min(blue_source.height(), int(math.floor(source_top))),
        )
        source_right_i = max(
            0,
            min(blue_source.width(), int(math.ceil(source_right))),
        )
        source_bottom_i = max(
            0,
            min(blue_source.height(), int(math.ceil(source_bottom))),
        )
        source_frame_w_i = source_right_i - source_left_i
        source_frame_h_i = source_bottom_i - source_top_i
        if source_frame_w_i <= 0 or source_frame_h_i <= 0:
            return False
        blue_frame_source = blue_source.copy(
            source_left_i,
            source_top_i,
            source_frame_w_i,
            source_frame_h_i,
        )
        if blue_frame_source.isNull():
            return False
        if cancelled_check and cancelled_check():
            return False
        blue_frame = tint_image(blue_frame_source, 80, 80, 255)
        painter.save()
        painter.setTransform(context["transform"])
        painter.drawImage(0, 0, blue_frame)
        painter.restore()
        return True

    def _draw_overlay_raster_fallback(
        self,
        painter: QPainter,
        page: Page,
        render_scale: float,
        frame_x: float,
        frame_y: float,
        rotation: int,
        wait_for_in_flight: bool = True,
    ) -> None:
        blue = self._get_tinted_page(
            page.overlay_image_path,
            0,
            RASTER_NATIVE_RENDER_SCALE,
            rotation,
            (80, 80, 255),
            wait_for_in_flight,
        )
        if not blue:
            return
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

    def _build_overlay_frame_context(
        self,
        page: Page,
        source_w: float,
        source_h: float,
        render_scale: float,
        frame_x: float,
        frame_y: float,
        frame_w: float,
        frame_h: float,
        image_scale: Optional[float] = None,
    ) -> Optional[dict[str, float | QTransform]]:
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_page_points()
        if source_w <= 0.0 or source_h <= 0.0 or rect_w <= 0.0 or rect_h <= 0.0:
            return None
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
            return None
        frame_rect = QRectF(frame_x, frame_y, frame_w, frame_h)
        source_rect = page_to_source.mapRect(frame_rect)
        source_x = max(0.0, min(source_w, math.floor(source_rect.left())))
        source_y = max(0.0, min(source_h, math.floor(source_rect.top())))
        source_right = max(0.0, min(source_w, math.ceil(source_rect.right())))
        source_bottom = max(0.0, min(source_h, math.ceil(source_rect.bottom())))
        source_frame_w = source_right - source_x
        source_frame_h = source_bottom - source_y
        if source_frame_w <= 0.0 or source_frame_h <= 0.0:
            return None
        overlay_scale = self._overlay_frame_scale(
            render_scale,
            rect_w / source_w,
            rect_h / source_h,
        )
        if image_scale is not None:
            overlay_scale = quantize_constrained_render_scale(image_scale)
        rendered_source_x = align_rendered_frame_origin(source_x, overlay_scale)
        rendered_source_y = align_rendered_frame_origin(source_y, overlay_scale)
        rendered_frame_x = align_rendered_frame_origin(frame_x, render_scale)
        rendered_frame_y = align_rendered_frame_origin(frame_y, render_scale)
        image_to_source = QTransform()
        image_to_source.scale(1.0 / overlay_scale, 1.0 / overlay_scale)
        source_offset = QTransform()
        source_offset.translate(rendered_source_x, rendered_source_y)
        page_to_frame = QTransform()
        page_to_frame.scale(render_scale, render_scale)
        frame_offset = QTransform()
        frame_offset.translate(
            -rendered_frame_x * render_scale,
            -rendered_frame_y * render_scale,
        )
        transform = (
            image_to_source
            * source_offset
            * source_to_page
            * page_to_frame
            * frame_offset
        )
        return {
            "overlay_scale": overlay_scale,
            "source_x": source_x,
            "source_y": source_y,
            "source_frame_w": source_frame_w,
            "source_frame_h": source_frame_h,
            "transform": transform,
        }

    def _overlay_frame_scale(
        self, render_scale: float, scale_x: float, scale_y: float
    ) -> float:
        overlay_scale = render_scale * max(abs(scale_x), abs(scale_y))
        return quantize_constrained_render_scale(overlay_scale)

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

    def clear_cache(self):
        self._page_cache.clear_composites()
