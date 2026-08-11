import logging
import math
import os
import tempfile
from dataclasses import replace
from typing import Any, Dict, List, Optional
from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import (
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTransform,
)
from ....application.dtos.export_dto import (
    ExportErrorCode,
    ExportProgressCallback,
    ExportResultDto,
)
from ....application.dtos.color_dtos import ColorWithOpacity
from ....application.dtos.annotation_caption_dto import AnnotationCaptionSettingsDto
from ....application.dtos.page_export_data_dto import PageExportData
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_annotation_caption_resolver import (
    IAnnotationCaptionResolver,
)
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from ....application.interfaces.i_uom_service import IUOMService
from ....application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
    baseline_render_scale,
)
from ....domain.dtos.page_render_info_dto import PageRenderInfo
from ....domain.entities import shape as shapes
from ....domain.entities.annotation import (
    ANNOTATION_TYPE_ARROW,
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HIGHLIGHT,
    ANNOTATION_TYPE_INK,
    ANNOTATION_TYPE_LINE,
    ANNOTATION_TYPE_OVAL,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ....domain.entities.condition import Condition
from ....domain.entities.config import Config
from ....domain.entities.elevation_callout import (
    DEFAULT_ELEVATION_CALLOUT_SETTINGS,
    ElevationCalloutSettings,
)
from ....domain.entities.file_extensions import is_pdf_suffix
from ....domain.entities.page import Page
from ....domain.entities.takeoff import Takeoff
from ....domain.services.elevation_callout_service import resolve_elevation_callout
from ...utils.image_show_mode import mode_to_flags
from ..core.geometry.ost_linear_geom import (
    gen_curve_pts,
    gen_thick_curve_offsets,
    proc_curved_pos,
)
from ..core.geometry.takeoff_geometry import (
    compute_count_vertices,
    compute_curved_linear_vertices,
    compute_straight_linear_vertices,
)
from ..pdf.page_cache import PageCache
from ..pdf.renderers.annotation_renderer import (
    HIGHLIGHT_OPACITY,
    calculate_highlight_quad_path,
    canonical_highlight_quads,
    format_dimension_distance,
    highlight_position_coordinates,
)
from ..pdf.services.composite_renderer import CompositeRenderer
from . import ost_pdf_writer

logger = logging.getLogger(__name__)
_DEFAULT_FILL_OPACITY = 0.5
_INCHES_TO_FEET = 1.0 / 12.0
_PDF_POINTS_PER_INCH = 72
_OVERLAY_DIRECT_FULL_PAGE_TOLERANCE_POINTS = 3.0
_OVERLAY_DIRECT_ROTATION_TOLERANCE_RADIANS = 1e-6
_ELEVATION_CALLOUT_BOX_WIDTH = 180.0
_ELEVATION_CALLOUT_BOX_HEIGHT = 52.0
_ELEVATION_CALLOUT_FONT_SIZE = 10.0


class PDFExporter:
    def __init__(
        self,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
        uom_service: IUOMService,
        annotation_caption_resolver: IAnnotationCaptionResolver,
    ):
        self._coord_system = coord_system
        self._color_service = color_service
        self._takeoff_service = takeoff_service
        self._uom_service = uom_service
        self._annotation_caption_resolver = annotation_caption_resolver
        self._writer = ost_pdf_writer.PDFWriter()
        self._export_page_cache = PageCache()
        self._export_composite_renderer = CompositeRenderer(self._export_page_cache)

    def export(
        self,
        pages_data: List[PageExportData],
        output_path: str,
        display_mode: str,
        grayscale_enabled: bool,
        caption_settings: AnnotationCaptionSettingsDto,
        elevation_callouts_enabled: bool,
        elevation_callout_settings: ElevationCalloutSettings = (
            DEFAULT_ELEVATION_CALLOUT_SETTINGS
        ),
        elevation_callout_color: str = Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
        *,
        inactive_object_color: str,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        bid_annotations: Optional[List[BidAnnotation]] = None,
        on_progress: Optional[ExportProgressCallback] = None,
    ) -> ExportResultDto:
        try:
            with tempfile.TemporaryDirectory(prefix="ost_pdf_export_") as temp_dir:
                total = len(pages_data)
                page_exports = []
                for idx, page_data in enumerate(pages_data):
                    page: Page = page_data.page
                    if on_progress:
                        on_progress(idx + 1, total, page.name or f"Page {idx + 1}")
                    bid_takeoffs = page_data.bid_takeoffs
                    bid_conditions = page_data.bid_conditions
                    page_info = self._build_page_info(page)
                    _, color_map = self._color_service.get_color_mapping(
                        bid_conditions, bid_takeoffs, display_mode, grayscale_enabled
                    )
                    takeoff_data, elevation_callout_data = self._collect_takeoffs(
                        bid_takeoffs,
                        bid_conditions,
                        page_info,
                        color_map,
                        page_area_selections=page_area_selections,
                        inactive_object_color=inactive_object_color,
                        caption_settings=caption_settings,
                        elevation_callouts_enabled=elevation_callouts_enabled,
                        elevation_callout_settings=elevation_callout_settings,
                        elevation_callout_color=elevation_callout_color,
                    )
                    arrow_data = self._collect_arrows(
                        page.uid, bid_annotations or [], page_info
                    )
                    rect_data = self._collect_rects(
                        page.uid, bid_annotations or [], page_info
                    )
                    line_data = self._collect_lines(
                        page.uid, bid_annotations or [], page_info
                    )
                    dimension_data = self._collect_dimensions(
                        page.uid, bid_annotations or [], page_info
                    )
                    oval_data = self._collect_ovals(
                        page.uid, bid_annotations or [], page_info
                    )
                    polygon_data = self._collect_polygons(
                        page.uid, bid_annotations or [], page_info
                    )
                    ink_data = self._collect_inks(
                        page.uid, bid_annotations or [], page_info
                    )
                    text_data = self._collect_texts(
                        page.uid, bid_annotations or [], page_info
                    )
                    text_data.extend(elevation_callout_data)
                    highlight_data = self._collect_highlights(
                        page.uid, bid_annotations or [], page_info
                    )
                    export_data = ost_pdf_writer.PageExportData()
                    self._configure_page_background(
                        export_data, page, page_info, temp_dir
                    )
                    export_data.takeoffs = takeoff_data
                    export_data.arrows = arrow_data
                    export_data.rects = rect_data
                    export_data.lines = line_data
                    export_data.dimensions = dimension_data
                    export_data.ovals = oval_data
                    export_data.polygons = polygon_data
                    export_data.inks = ink_data
                    export_data.texts = text_data
                    export_data.highlights = highlight_data
                    page_exports.append(export_data)
                if not page_exports:
                    logger.error("No valid pages to export")
                    return ExportResultDto(
                        success=False,
                        format_name="PDF",
                        error_message="No valid pages to export.",
                        error_code=ExportErrorCode.NO_DATA,
                    )
                if not self._writer.merge_pages_with_annotations(
                    page_exports, output_path
                ):
                    err = self._writer.get_last_error()
                    logger.error("Failed to merge pages: %s", err)
                    return ExportResultDto(
                        success=False,
                        format_name="PDF",
                        error_message=err or "Failed to write PDF.",
                        error_code=ExportErrorCode.WRITE_FAILED,
                    )
                return ExportResultDto(
                    success=True,
                    format_name="PDF",
                    page_count=len(page_exports),
                )
        except Exception as e:
            logger.exception("Error during PDF export: %s", e)
            return ExportResultDto(
                success=False,
                format_name="PDF",
                error_message=str(e),
                error_code=ExportErrorCode.UNEXPECTED,
            )
        finally:
            self._clear_export_render_resources()

    def _clear_export_render_resources(self) -> None:
        cleanup_steps = (
            ("composite renderer cache", self._export_composite_renderer.clear_cache),
            ("page cache", self._export_page_cache.clear),
        )
        for resource_name, cleanup in cleanup_steps:
            try:
                cleanup()
            except Exception:
                logger.exception("Failed to clear PDF export %s", resource_name)

    def _configure_page_background(
        self,
        export_data: Any,
        page: Page,
        page_info: PageRenderInfo,
        temp_dir: str,
    ) -> None:
        show_original, show_overlay = mode_to_flags(page.image_show_mode)
        main_path = page.image_path or ""
        overlay_path = page.overlay_image_path or ""
        main_visible = bool(main_path and page.layer_visible and show_original)
        overlay_visible = bool(overlay_path and show_overlay)
        if main_visible and overlay_visible:
            composite_pdf = self._create_composite_background_pdf(
                page, page_info, temp_dir
            )
            if composite_pdf:
                self._use_source_pdf(export_data, composite_pdf, 0)
                return
            if self._try_main_background(export_data, page, page_info, temp_dir):
                return
            if self._try_overlay_background(export_data, page, page_info, temp_dir):
                return
        elif overlay_visible:
            if self._try_overlay_background(export_data, page, page_info, temp_dir):
                return
        elif main_visible:
            if self._try_main_background(export_data, page, page_info, temp_dir):
                return
        self._use_blank_background(export_data, page_info)

    def _try_main_background(
        self,
        export_data: Any,
        page: Page,
        page_info: PageRenderInfo,
        temp_dir: str,
    ) -> bool:
        return self._try_single_source_background(
            export_data,
            page.image_path or "",
            page.page_index or 0,
            page_info,
            temp_dir,
            "image",
        )

    def _try_overlay_background(
        self,
        export_data: Any,
        page: Page,
        page_info: PageRenderInfo,
        temp_dir: str,
    ) -> bool:
        if not self._overlay_rect_matches_page(page):
            source_pdf = self._create_overlay_rect_background_pdf(
                page, page_info, temp_dir
            )
            if source_pdf:
                self._use_source_pdf(export_data, source_pdf, 0)
                return True
            return False
        return self._try_single_source_background(
            export_data,
            page.overlay_image_path or "",
            0,
            page_info,
            temp_dir,
            "overlay",
        )

    @staticmethod
    def _overlay_rect_matches_page(page: Page) -> bool:
        if page.overlay_units_per_sheet_inch is None:
            return False
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        if abs(total_rotation) > _OVERLAY_DIRECT_ROTATION_TOLERANCE_RADIANS:
            return False
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_page_points()
        if rect_w <= 0.0 or rect_h <= 0.0:
            return True
        width_tolerance = _OVERLAY_DIRECT_FULL_PAGE_TOLERANCE_POINTS
        height_tolerance = _OVERLAY_DIRECT_FULL_PAGE_TOLERANCE_POINTS
        return (
            abs(rect_x) <= width_tolerance
            and abs(rect_y) <= height_tolerance
            and abs(rect_w - page.effective_width_pts) <= width_tolerance
            and abs(rect_h - page.effective_height_pts) <= height_tolerance
        )

    def _create_overlay_rect_background_pdf(
        self, page: Page, page_info: PageRenderInfo, temp_dir: str
    ) -> Optional[str]:
        image = self._render_positioned_overlay_background(page, page_info)
        return self._write_raster_background_pdf(image, page_info, temp_dir, "overlay")

    def _render_positioned_overlay_background(
        self, page: Page, page_info: PageRenderInfo
    ) -> Optional[QImage]:
        if not page.overlay_image_path:
            return None
        if page.overlay_units_per_sheet_inch is None:
            return None
        overlay = self._export_page_cache.get_page(
            page.overlay_image_path,
            0,
            baseline_render_scale(is_pdf=is_pdf_suffix(page.overlay_image_path)),
            0,
        )
        if overlay is None or overlay.isNull():
            return None
        if overlay.width() <= 0 or overlay.height() <= 0:
            return None
        export_page = self._page_with_export_geometry(page, page_info)
        canvas_w = max(
            1,
            int(round(export_page.effective_width_pts * INTERACTIVE_PDF_RENDER_SCALE)),
        )
        canvas_h = max(
            1,
            int(round(export_page.effective_height_pts * INTERACTIVE_PDF_RENDER_SCALE)),
        )
        result = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32)
        result.fill(0xFFFFFFFF)
        rect_x, rect_y, rect_w, rect_h = export_page.overlay_rect_canvas(
            canvas_w, canvas_h
        )
        if rect_w <= 0.0 or rect_h <= 0.0:
            return result
        transform = QTransform()
        transform.translate(rect_x, rect_y)
        total_rotation = page.overlay_rotation + page.deskew_rotation_overlay
        if total_rotation != 0:
            transform.rotate(math.degrees(total_rotation))
        transform.scale(rect_w / overlay.width(), rect_h / overlay.height())
        painter = QPainter(result)
        if not painter.isActive():
            return None
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setClipRect(QRectF(0.0, 0.0, float(canvas_w), float(canvas_h)))
            painter.setTransform(transform)
            painter.drawImage(0, 0, overlay)
        finally:
            painter.end()
        return result

    def _try_single_source_background(
        self,
        export_data: Any,
        source_path: str,
        page_index: int,
        page_info: PageRenderInfo,
        temp_dir: str,
        prefix: str,
    ) -> bool:
        if not source_path:
            return False
        if is_pdf_suffix(source_path):
            self._use_source_pdf(export_data, source_path, page_index)
            return True
        source_pdf = self._create_image_source_background_pdf(
            source_path, page_index, page_info, temp_dir, prefix
        )
        if source_pdf:
            self._use_source_pdf(export_data, source_pdf, 0)
            return True
        return False

    def _create_composite_background_pdf(
        self, page: Page, page_info: PageRenderInfo, temp_dir: str
    ) -> Optional[str]:
        export_page = self._page_with_export_geometry(page, page_info)
        image = self._export_composite_renderer.render_composite(
            export_page,
            bid_ref=None,
            render_scale=baseline_render_scale(is_pdf=is_pdf_suffix(page.image_path)),
            raster_rotation=0,
        )
        return self._write_raster_background_pdf(
            image, page_info, temp_dir, "composite"
        )

    @staticmethod
    def _page_with_export_geometry(page: Page, page_info: PageRenderInfo) -> Page:
        return replace(
            page,
            width_pts=float(page_info["width"]),
            height_pts=float(page_info["height"]),
        )

    def _create_image_source_background_pdf(
        self,
        source_path: str,
        page_index: int,
        page_info: PageRenderInfo,
        temp_dir: str,
        prefix: str,
    ) -> Optional[str]:
        image = self._export_page_cache.get_page(
            source_path,
            page_index,
            RASTER_NATIVE_RENDER_SCALE,
            0,
        )
        return self._write_raster_background_pdf(image, page_info, temp_dir, prefix)

    def _write_raster_background_pdf(
        self,
        image: Optional[QImage],
        page_info: PageRenderInfo,
        temp_dir: str,
        prefix: str,
    ) -> Optional[str]:
        if image is None or image.isNull():
            return None
        page_width = float(page_info["width"])
        page_height = float(page_info["height"])
        fd, output_path = tempfile.mkstemp(
            prefix=f"{prefix}_", suffix=".pdf", dir=temp_dir
        )
        os.close(fd)
        writer = QPdfWriter(output_path)
        writer.setResolution(_PDF_POINTS_PER_INCH)
        writer.setPageLayout(
            QPageLayout(
                QPageSize(QSizeF(page_width, page_height), QPageSize.Unit.Point),
                QPageLayout.Orientation.Portrait,
                QMarginsF(0.0, 0.0, 0.0, 0.0),
                QPageLayout.Unit.Point,
            )
        )
        painter = QPainter(writer)
        if not painter.isActive():
            return None
        try:
            painter.drawImage(QRectF(0.0, 0.0, page_width, page_height), image)
        finally:
            painter.end()
        return output_path

    @staticmethod
    def _use_source_pdf(export_data: Any, source_pdf: str, page_index: int) -> None:
        export_data.source_pdf = source_pdf
        export_data.page_index = page_index
        export_data.is_blank = False

    @staticmethod
    def _use_blank_background(export_data: Any, page_info: PageRenderInfo) -> None:
        export_data.is_blank = True
        export_data.page_width = page_info["width"]
        export_data.page_height = page_info["height"]
        export_data.rotation = page_info["rotation"]

    @staticmethod
    def _is_annotation_exportable(
        annotation: BidAnnotation,
        page_uid: str,
        annotation_types: str | tuple[str, ...],
    ) -> bool:
        if isinstance(annotation_types, str):
            type_matches = annotation.annotation_type == annotation_types
        else:
            type_matches = annotation.annotation_type in annotation_types
        return type_matches and annotation.page_uid == page_uid and annotation.visible

    @staticmethod
    def _text_align_to_pdf_value(raw_align: Any) -> str:
        if isinstance(raw_align, str):
            normalized = raw_align.strip().lower()
            return {
                "center": "center",
                "right": "right",
                "1": "center",
                "2": "right",
            }.get(normalized, "left")
        try:
            return {1: "center", 2: "right"}.get(int(raw_align), "left")
        except (TypeError, ValueError):
            return "left"

    def _build_page_info(self, page: Page) -> PageRenderInfo:
        page_width_pts = page.width_pts
        page_height_pts = page.height_pts
        offset_x = 0.0
        offset_y = 0.0
        native_rotation = 0
        image_path = page.image_path or ""
        if is_pdf_suffix(image_path):
            geometries = self._writer.get_page_geometries(image_path)
            page_idx = page.page_index or 0
            if page_idx < 0 or page_idx >= len(geometries):
                raise ValueError(
                    f"Native PDF page geometry is unavailable for page {page_idx}"
                )
            geometry = geometries[page_idx]
            min_x, min_y, max_x, max_y = geometry.visible_box
            native_width = max_x - min_x
            native_height = max_y - min_y
            if native_width <= 0.0 or native_height <= 0.0:
                raise ValueError(
                    f"Native PDF page geometry is invalid for page {page_idx}"
                )
            page_width_pts = native_width
            page_height_pts = native_height
            offset_x = min_x
            offset_y = min_y
            native_rotation = int(geometry.rotation or 0) % 360
        rotation = (native_rotation + page.rotation) % 360
        return {
            "scale_factor1": page.scale_factor1 or 1.0,
            "scale_factor2": page.scale_factor2 or 1.0,
            "rotation": rotation,
            "flip_x": 1 if page.flip_x else 0,
            "flip_y": 1 if page.flip_y else 0,
            "width": page_width_pts,
            "height": page_height_pts,
            "view_scale": INTERACTIVE_PDF_RENDER_SCALE,
            "coord_offset_x": offset_x,
            "coord_offset_y": offset_y,
        }

    def _collect_takeoffs(
        self,
        bid_takeoffs: List[Takeoff],
        bid_conditions: Dict[str, Condition],
        page_info: PageRenderInfo,
        color_map: Optional[Dict[str, Any]] = None,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        *,
        inactive_object_color: str,
        caption_settings: AnnotationCaptionSettingsDto,
        elevation_callouts_enabled: bool,
        elevation_callout_settings: ElevationCalloutSettings = (
            DEFAULT_ELEVATION_CALLOUT_SETTINGS
        ),
        elevation_callout_color: str = Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
    ) -> tuple[List[Any], List[Any]]:
        polygons = []
        elevation_callouts = []
        scale_factor1 = page_info.get("scale_factor1", 1.0)
        scale_factor2 = page_info.get("scale_factor2", 1.0)
        parent_takeoffs, holes_map = (
            self._takeoff_service.group_area_takeoffs_with_holes(
                bid_takeoffs, bid_conditions
            )
        )
        for takeoff in parent_takeoffs:
            condition_uid = takeoff.condition_uid
            if condition_uid not in bid_conditions:
                continue
            condition = bid_conditions[condition_uid]
            if not condition.layer_visible:
                continue
            condition_type = condition.condition_type if condition.condition_type else 0
            if condition_type != Condition.TYPE_AREA:
                continue
            position = self._coord_system.parse_position(takeoff.position)
            if not position or len(position) < 6:
                continue
            pdf_vertices = self._coord_system.ost_to_pdf_coordinates(
                position, page_info
            )
            if not pdf_vertices or len(pdf_vertices) < 3:
                continue
            hole_takeoff_list = holes_map.get(takeoff.uid, [])
            pdf_holes = []
            for hole_takeoff in hole_takeoff_list:
                hole_position = self._coord_system.parse_position(hole_takeoff.position)
                if not hole_position or len(hole_position) < 6:
                    continue
                hole_vertices = self._coord_system.ost_to_pdf_coordinates(
                    hole_position, page_info
                )
                if hole_vertices and len(hole_vertices) >= 3:
                    pdf_holes.append(hole_vertices)
            color_entry = self._resolved_takeoff_color(
                takeoff,
                condition,
                color_map,
                page_area_selections,
                inactive_object_color,
            )
            color_rgb = self._color_service.hex_to_rgb_int(color_entry.hex)
            fill_opacity = color_entry.opacity
            condition_name = condition.name if condition.name else "Takeoff"
            ref_no = condition.ref_no if condition.ref_no else ""
            label = f"{ref_no} - {condition_name}" if ref_no else condition_name
            hole_positions = [ht.position for ht in hole_takeoff_list if ht.position]
            area_sf = self._uom_service.calculate_net_area_sf(
                takeoff.position, hole_positions
            )
            thickness = max(condition.thickness if condition.thickness else 0, 0)
            depth_ft = thickness * _INCHES_TO_FEET if thickness > 0 else 0.0
            polygon_data = ost_pdf_writer.PolygonAnnotationData()
            polygon_data.vertices = pdf_vertices
            polygon_data.holes = pdf_holes
            polygon_data.color = color_rgb
            polygon_data.fill_opacity = fill_opacity
            polygon_data.area_sf = area_sf
            polygon_data.scale_factor1 = scale_factor1
            polygon_data.scale_factor2 = scale_factor2
            polygon_data.depth = depth_ft
            self._set_resolved_caption(
                polygon_data,
                condition,
                takeoff,
                hole_positions,
                caption_settings,
                label,
            )
            polygons.append(polygon_data)
            if elevation_callouts_enabled:
                callout = self._build_elevation_callout_text(
                    condition,
                    takeoff,
                    hole_takeoff_list,
                    pdf_vertices,
                    elevation_callout_settings,
                    elevation_callout_color,
                )
                if callout is not None:
                    elevation_callouts.append(callout)
        for takeoff in bid_takeoffs:
            condition_uid = takeoff.condition_uid
            if condition_uid not in bid_conditions:
                continue
            condition = bid_conditions[condition_uid]
            if not condition.layer_visible:
                continue
            cond_type = condition.condition_type if condition.condition_type else 0
            if cond_type == Condition.TYPE_AREA:
                continue
            if takeoff.is_hole and cond_type != Condition.TYPE_ATTACHMENT:
                continue
            position = self._coord_system.parse_position(takeoff.position)
            if not position or len(position) < 2:
                continue
            verts = None
            area_sf = 0.0
            depth_inches = 0.0
            if cond_type == Condition.TYPE_LINEAR:
                if len(position) < 4:
                    continue
                thickness = condition.thickness if condition.thickness else 1.0
                if thickness <= 0:
                    thickness = 1.0
                x1, y1, x2, y2 = position[0], position[1], position[2], position[3]
                if takeoff.curve >= 0 and len(position) >= 6:
                    rx = list(position[:6])
                    rx[0], rx[1], rx[2], rx[3], rx[4], rx[5] = proc_curved_pos(
                        position, rx[0], rx[1], rx[2], rx[3], rx[4], rx[5]
                    )
                    verts = compute_curved_linear_vertices(
                        rx[0],
                        rx[1],
                        rx[2],
                        rx[3],
                        rx[4],
                        rx[5],
                        gen_curve_pts,
                        gen_thick_curve_offsets,
                        thickness,
                    )
                else:
                    verts = compute_straight_linear_vertices(x1, y1, x2, y2, thickness)
                if not verts:
                    continue
                dx, dy = x2 - x1, y2 - y1
                length_inches = math.sqrt(dx * dx + dy * dy)
                area_sf = (length_inches * thickness) / 144.0
                height = max(condition.height if condition.height else 0, 0)
                depth_inches = height
            elif cond_type in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT):
                cx, cy = position[0], position[1]
                shape_id = condition.shape if condition.shape else shapes.SQUARE
                width_ost = max(condition.width if condition.width else 1, 1)
                if shape_id == shapes.SQUARE or shape_id == shapes.CIRCLE:
                    depth_ost = width_ost
                else:
                    depth_ost = max(
                        condition.depth if condition.depth else width_ost, 1
                    )
                if condition.is_count:
                    display_scale = max(condition.display_size, 0.1) / 100.0
                    width_ost *= display_scale
                    depth_ost *= display_scale
                rotation = takeoff.rotation
                verts = compute_count_vertices(
                    cx, cy, shape_id, width_ost, depth_ost, rotation
                )
                if not verts:
                    continue
                area_sf = (width_ost * depth_ost) / 144.0
                depth_inches = max(condition.height if condition.height else 0, 0)
            else:
                continue
            flat_pos = [c for pt in verts for c in pt]
            pdf_vertices = self._coord_system.ost_to_pdf_coordinates(
                flat_pos, page_info
            )
            if not pdf_vertices or len(pdf_vertices) < 3:
                continue
            color_entry = self._resolved_takeoff_color(
                takeoff,
                condition,
                color_map,
                page_area_selections,
                inactive_object_color,
            )
            color_rgb = self._color_service.hex_to_rgb_int(color_entry.hex)
            fill_opacity = color_entry.opacity
            condition_name = condition.name if condition.name else "Takeoff"
            ref_no = condition.ref_no if condition.ref_no else ""
            label = f"{ref_no} - {condition_name}" if ref_no else condition_name
            polygon_data = ost_pdf_writer.PolygonAnnotationData()
            polygon_data.vertices = pdf_vertices
            polygon_data.holes = []
            polygon_data.color = color_rgb
            polygon_data.fill_opacity = fill_opacity
            polygon_data.area_sf = area_sf
            polygon_data.scale_factor1 = scale_factor1
            polygon_data.scale_factor2 = scale_factor2
            polygon_data.depth = (
                depth_inches * _INCHES_TO_FEET if depth_inches > 0 else 0.0
            )
            self._set_resolved_caption(
                polygon_data,
                condition,
                takeoff,
                [],
                caption_settings,
                label,
            )
            polygons.append(polygon_data)
            if elevation_callouts_enabled:
                callout = self._build_elevation_callout_text(
                    condition,
                    takeoff,
                    [],
                    pdf_vertices,
                    elevation_callout_settings,
                    elevation_callout_color,
                )
                if callout is not None:
                    elevation_callouts.append(callout)
        return polygons, elevation_callouts

    def _resolved_takeoff_color(
        self,
        takeoff: Takeoff,
        condition: Condition,
        color_map: Optional[Dict[str, Any]],
        page_area_selections: Optional[Dict[str, Optional[str]]],
        inactive_object_color: str,
    ) -> ColorWithOpacity:
        effective_color_map = color_map
        if not effective_color_map or condition.uid not in effective_color_map:
            fallback_hex = "#{:02x}{:02x}{:02x}".format(
                *self._color_service.get_condition_color(condition)
            )
            effective_color_map = {
                condition.uid: ColorWithOpacity(
                    fallback_hex,
                    _DEFAULT_FILL_OPACITY,
                )
            }
        return self._color_service.get_2d_color_for_takeoff(
            takeoff,
            condition,
            effective_color_map,
            page_area_selections,
            inactive_object_color=inactive_object_color,
        )

    def _build_elevation_callout_text(
        self,
        condition: Condition,
        takeoff: Takeoff,
        hole_takeoffs: List[Takeoff],
        outer_ring: List[tuple[float, float]],
        settings: ElevationCalloutSettings = DEFAULT_ELEVATION_CALLOUT_SETTINGS,
        color: str = Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
    ) -> Any | None:
        resolved = resolve_elevation_callout(
            condition,
            takeoff,
            hole_takeoffs,
            tuple((float(point[0]), float(point[1])) for point in outer_ring),
            settings,
        )
        if resolved is None:
            return None
        half_width = _ELEVATION_CALLOUT_BOX_WIDTH / 2.0
        half_height = _ELEVATION_CALLOUT_BOX_HEIGHT / 2.0
        text_data = ost_pdf_writer.TextAnnotationData()
        text_data.min_x = resolved.x - half_width
        text_data.min_y = resolved.y - half_height
        text_data.max_x = resolved.x + half_width
        text_data.max_y = resolved.y + half_height
        text_data.content = "\n".join(resolved.lines)
        text_data.font_size = _ELEVATION_CALLOUT_FONT_SIZE
        text_data.color = self._color_service.hex_to_rgb_int(color)
        text_data.text_align = "center"
        return text_data

    def _set_resolved_caption(
        self,
        polygon_data: Any,
        condition: Condition,
        takeoff: Takeoff,
        hole_positions: List[List[float]],
        settings: AnnotationCaptionSettingsDto,
        label: str,
    ) -> None:
        if not settings.enabled:
            return
        resolved = self._annotation_caption_resolver.resolve(
            condition,
            takeoff,
            hole_positions,
            settings,
            label,
        )
        caption = ost_pdf_writer.AnnotationCaptionData()
        caption.lines = list(resolved.lines)
        caption.label = resolved.label
        caption.measurement_types = resolved.measurement_types
        polygon_data.caption = caption

    def _collect_arrows(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        arrows = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_ARROW
            ):
                continue
            line_coords = annotation.get_line_coords()
            if not line_coords:
                continue
            x1, y1, x2, y2 = line_coords
            pdf_coords = self._coord_system.ost_to_pdf_coordinates(
                [x1, y1, x2, y2], page_info
            )
            if len(pdf_coords) < 2:
                continue
            pdf_x1, pdf_y1 = pdf_coords[0]
            pdf_x2, pdf_y2 = pdf_coords[1]
            arrow_data = ost_pdf_writer.ArrowAnnotationData()
            arrow_data.x1 = pdf_x1
            arrow_data.y1 = pdf_y1
            arrow_data.x2 = pdf_x2
            arrow_data.y2 = pdf_y2
            arrow_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            arrow_data.width = annotation.width
            arrows.append(arrow_data)
        return arrows

    def _collect_rects(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        rects = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_RECT
            ):
                continue
            position = annotation.position
            if len(position) < 4:
                continue
            if len(position) >= 8:
                xs = position[0::2]
                ys = position[1::2]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
            else:
                min_x, min_y, max_x, max_y = (
                    position[0],
                    position[1],
                    position[2],
                    position[3],
                )
            pdf_coords = self._coord_system.ost_to_pdf_coordinates(
                [min_x, min_y, max_x, max_y], page_info
            )
            if len(pdf_coords) < 2:
                continue
            pdf_x1, pdf_y1 = pdf_coords[0]
            pdf_x2, pdf_y2 = pdf_coords[1]
            rect_data = ost_pdf_writer.RectAnnotationData()
            rect_data.min_x = min(pdf_x1, pdf_x2)
            rect_data.min_y = min(pdf_y1, pdf_y2)
            rect_data.max_x = max(pdf_x1, pdf_x2)
            rect_data.max_y = max(pdf_y1, pdf_y2)
            rect_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            rect_data.width = annotation.width
            rects.append(rect_data)
        return rects

    def _collect_lines(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        lines = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_LINE
            ):
                continue
            line_coords = annotation.get_line_coords()
            if not line_coords:
                continue
            x1, y1, x2, y2 = line_coords
            pdf_coords = self._coord_system.ost_to_pdf_coordinates(
                [x1, y1, x2, y2], page_info
            )
            if len(pdf_coords) < 2:
                continue
            pdf_x1, pdf_y1 = pdf_coords[0]
            pdf_x2, pdf_y2 = pdf_coords[1]
            line_data = ost_pdf_writer.LineAnnotationData()
            line_data.x1 = pdf_x1
            line_data.y1 = pdf_y1
            line_data.x2 = pdf_x2
            line_data.y2 = pdf_y2
            line_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            line_data.width = annotation.width
            lines.append(line_data)
        return lines

    def _collect_dimensions(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        dimensions = []
        scale_factor1 = float(page_info.get("scale_factor1", 0.0) or 0.0)
        scale_factor2 = float(page_info.get("scale_factor2", 0.0) or 0.0)
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_DIMENSION
            ):
                continue
            line_coords = annotation.get_line_coords()
            if not line_coords:
                continue
            x1, y1, x2, y2 = line_coords
            distance = math.hypot(x2 - x1, y2 - y1)
            if distance <= 1e-9:
                continue
            label = format_dimension_distance(distance)
            if not label:
                continue
            pdf_coords = self._coord_system.ost_to_pdf_coordinates(
                [x1, y1, x2, y2], page_info
            )
            if len(pdf_coords) < 2:
                continue
            pdf_x1, pdf_y1 = pdf_coords[0]
            pdf_x2, pdf_y2 = pdf_coords[1]
            font_size = float(annotation.properties.get("FontSize") or 10.0)
            dimension_data = ost_pdf_writer.DimensionAnnotationData()
            dimension_data.x1 = pdf_x1
            dimension_data.y1 = pdf_y1
            dimension_data.x2 = pdf_x2
            dimension_data.y2 = pdf_y2
            dimension_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            dimension_data.width = annotation.width
            dimension_data.content = label
            dimension_data.font_size = font_size
            dimension_data.scale_factor1 = scale_factor1
            dimension_data.scale_factor2 = scale_factor2
            dimensions.append(dimension_data)
        return dimensions

    def _collect_ovals(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        ovals = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_OVAL
            ):
                continue
            geometry = annotation.get_oval_geometry_ost()
            if (
                geometry is None
                or not math.isfinite(annotation.width)
                or annotation.width < 0.0
            ):
                continue
            center_x, center_y, radius_x, radius_y, rotation = geometry
            cos_r = math.cos(rotation)
            sin_r = math.sin(rotation)
            x_axis_x = center_x + radius_x * cos_r
            x_axis_y = center_y + radius_x * sin_r
            y_axis_x = center_x - radius_y * sin_r
            y_axis_y = center_y + radius_y * cos_r
            pdf_coords = self._coord_system.ost_to_pdf_coordinates(
                [
                    center_x,
                    center_y,
                    x_axis_x,
                    x_axis_y,
                    y_axis_x,
                    y_axis_y,
                ],
                page_info,
            )
            if len(pdf_coords) < 3:
                continue
            pdf_center, pdf_x_axis, pdf_y_axis = pdf_coords[:3]
            oval_data = ost_pdf_writer.OvalAnnotationData()
            oval_data.center_x = pdf_center[0]
            oval_data.center_y = pdf_center[1]
            oval_data.x_axis_dx = pdf_x_axis[0] - pdf_center[0]
            oval_data.x_axis_dy = pdf_x_axis[1] - pdf_center[1]
            oval_data.y_axis_dx = pdf_y_axis[0] - pdf_center[0]
            oval_data.y_axis_dy = pdf_y_axis[1] - pdf_center[1]
            oval_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            oval_data.width = annotation.width
            ovals.append(oval_data)
        return ovals

    def _collect_polygons(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        polygons = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation,
                page_uid,
                (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD),
            ):
                continue
            position = annotation.position
            if len(position) < 6:
                continue
            vertices = self._coord_system.ost_to_pdf_coordinates(position, page_info)
            if len(vertices) < 3:
                continue
            poly_data = ost_pdf_writer.PolygonAnnotationAnnotData()
            poly_data.vertices = vertices
            poly_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            poly_data.width = annotation.width
            poly_data.is_cloud = annotation.is_cloud
            polygons.append(poly_data)
        return polygons

    def _collect_inks(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        inks = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_INK
            ):
                continue
            position = annotation.position
            if len(position) < 4:
                continue
            start_idx = 2 if (len(position) >= 2 and position[0] == 0) else 0
            raw_slice = position[start_idx:]
            pair_count = len(raw_slice) // 2
            flat = []
            for i in range(pair_count):
                flat.append(raw_slice[i * 2 + 1])
                flat.append(raw_slice[i * 2])
            stroke_points = self._coord_system.ost_to_pdf_coordinates(flat, page_info)
            if len(stroke_points) < 2:
                continue
            ink_data = ost_pdf_writer.InkAnnotationData()
            ink_data.strokes = [stroke_points]
            ink_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            ink_data.width = annotation.width
            inks.append(ink_data)
        return inks

    def _collect_highlights(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        highlights = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_HIGHLIGHT
            ):
                continue
            position = highlight_position_coordinates(annotation.position)
            if not position:
                continue
            ost_points = list(zip(position[::2], position[1::2]))
            paths = []
            for ost_quad in canonical_highlight_quads(ost_points):
                flat_quad = [coordinate for point in ost_quad for coordinate in point]
                pdf_quad = self._coord_system.ost_to_pdf_coordinates(
                    flat_quad, page_info
                )
                if len(pdf_quad) != 4:
                    continue
                paths.append(calculate_highlight_quad_path(tuple(pdf_quad)))
            if not paths:
                continue
            highlight_data = ost_pdf_writer.HighlightAnnotationData()
            highlight_data.paths = paths
            highlight_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            highlight_data.opacity = HIGHLIGHT_OPACITY
            highlight_data.content = annotation.get_text_content()
            highlights.append(highlight_data)
        return highlights

    def _collect_texts(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        texts = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(
                annotation, page_uid, ANNOTATION_TYPE_TEXT
            ):
                continue
            position = annotation.position
            if len(position) < 4:
                continue
            center_x = position[0]
            center_y = position[1]
            box_width = position[2]
            box_height = position[3]
            min_x_ost = center_x - box_width / 2
            min_y_ost = center_y - box_height / 2
            max_x_ost = center_x + box_width / 2
            max_y_ost = center_y + box_height / 2
            pdf_coords = self._coord_system.ost_to_pdf_coordinates(
                [min_x_ost, min_y_ost, max_x_ost, max_y_ost], page_info
            )
            if len(pdf_coords) < 2:
                continue
            pdf_x1, pdf_y1 = pdf_coords[0]
            pdf_x2, pdf_y2 = pdf_coords[1]
            content = annotation.get_text_content()
            font_size = float(annotation.properties.get("FontSize") or 12.0)
            text_align = self._text_align_to_pdf_value(
                annotation.properties.get("TextAlign", 0)
            )
            text_data = ost_pdf_writer.TextAnnotationData()
            text_data.min_x = min(pdf_x1, pdf_x2)
            text_data.min_y = min(pdf_y1, pdf_y2)
            text_data.max_x = max(pdf_x1, pdf_x2)
            text_data.max_y = max(pdf_y1, pdf_y2)
            text_data.content = content
            text_data.font_size = font_size
            text_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            text_data.text_align = text_align
            texts.append(text_data)
        return texts
