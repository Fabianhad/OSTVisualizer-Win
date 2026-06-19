import logging
import math
import os
import tempfile
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
from ....application.dtos.export_dto import ExportErrorCode, ExportResultDto
from ....application.dtos.page_export_data_dto import PageExportData
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from ....application.interfaces.i_uom_service import IUOMService
from ....domain.dtos.page_render_info_dto import PageRenderInfo
from ....domain.entities import shape as shapes
from ....domain.entities.annotation import BidAnnotation
from ....domain.entities.condition import Condition
from ....domain.entities.page import Page
from ....domain.entities.takeoff import Takeoff
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
from ..pdf.renderers.annotation_renderer import format_dimension_distance
from ..pdf.services.composite_renderer import CompositeRenderer
from . import ost_pdf_writer

logger = logging.getLogger(__name__)
_PDF_RENDER_SCALE = 2.0
_ROTATION_ASPECT_THRESHOLD = 0.5
_AREA_CONDITION_TYPE = 1
_LINEAR_CONDITION_TYPE = 0
_COUNT_CONDITION_TYPE = 2
_ATTACHMENT_CONDITION_TYPE = 3
_DEFAULT_FILL_OPACITY = 0.5
_DEFAULT_HIGHLIGHT_OPACITY = 1.0
_GRAY_COLOR_HEX = "#808080"
_INCHES_TO_FEET = 1.0 / 12.0
_PDF_POINTS_PER_INCH = 72
_OVERLAY_DIRECT_FULL_PAGE_TOLERANCE_POINTS = 3.0
_OVERLAY_DIRECT_ROTATION_TOLERANCE_RADIANS = 1e-6


class PDFExporter:
    def __init__(
        self,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
        uom_service: IUOMService,
    ):
        self._coord_system = coord_system
        self._color_service = color_service
        self._takeoff_service = takeoff_service
        self._uom_service = uom_service
        self._writer = ost_pdf_writer.PDFWriter()
        self._export_page_cache = PageCache()
        self._export_composite_renderer = CompositeRenderer(self._export_page_cache)

    def export(
        self,
        pages_data: List[PageExportData],
        output_path: str,
        color_mode: str,
        grayscale_enabled: bool,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        bid_annotations: Optional[List[BidAnnotation]] = None,
        on_progress=None,
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
                        bid_conditions, bid_takeoffs, color_mode, grayscale_enabled
                    )
                    takeoff_data = self._collect_takeoffs(
                        bid_takeoffs,
                        bid_conditions,
                        page_info,
                        color_map,
                        page_area_selections,
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
        self._export_composite_renderer.clear_cache()
        self._export_page_cache.clear()

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
        image = self._render_positioned_overlay_background(page)
        return self._write_raster_background_pdf(image, page_info, temp_dir, "overlay")

    def _render_positioned_overlay_background(self, page: Page) -> Optional[QImage]:
        if not page.overlay_image_path:
            return None
        overlay = self._export_page_cache.get_page(
            page.overlay_image_path,
            0,
            _PDF_RENDER_SCALE,
            0,
        )
        if overlay is None or overlay.isNull():
            return None
        if overlay.width() <= 0 or overlay.height() <= 0:
            return None
        canvas_w = max(1, int(round(page.effective_width_pts * _PDF_RENDER_SCALE)))
        canvas_h = max(1, int(round(page.effective_height_pts * _PDF_RENDER_SCALE)))
        result = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32)
        result.fill(0xFFFFFFFF)
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_canvas(canvas_w, canvas_h)
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
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setClipRect(QRectF(0.0, 0.0, float(canvas_w), float(canvas_h)))
        painter.setTransform(transform)
        painter.drawImage(0, 0, overlay)
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
        if self._is_pdf_path(source_path):
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
        image = self._export_composite_renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=_PDF_RENDER_SCALE,
            raster_rotation=0,
        )
        return self._write_raster_background_pdf(
            image, page_info, temp_dir, "composite"
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
            _PDF_RENDER_SCALE,
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
        page_width = float(page_info.get("width", 612.0) or 612.0)
        page_height = float(page_info.get("height", 792.0) or 792.0)
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
        painter.drawImage(QRectF(0.0, 0.0, page_width, page_height), image)
        painter.end()
        return output_path

    @staticmethod
    def _is_pdf_path(path: str) -> bool:
        return path.lower().endswith(".pdf")

    @staticmethod
    def _use_source_pdf(export_data: Any, source_pdf: str, page_index: int) -> None:
        export_data.source_pdf = source_pdf
        export_data.page_index = page_index
        export_data.is_blank = False

    @staticmethod
    def _use_blank_background(export_data: Any, page_info: PageRenderInfo) -> None:
        export_data.is_blank = True
        export_data.page_width = page_info.get("width", 612.0)
        export_data.page_height = page_info.get("height", 792.0)
        export_data.rotation = page_info.get("rotation", 0)

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
        stored_width_pts = page.width_pts
        stored_height_pts = page.height_pts
        scale_x = 1.0
        scale_y = 1.0
        offset_x = 0.0
        offset_y = 0.0
        is_rotated = False
        image_path = page.image_path or ""
        if image_path.lower().endswith(".pdf"):
            try:
                sizes = self._writer.get_page_sizes(image_path)
                page_idx = page.page_index or 0
                if page_idx < len(sizes):
                    size_data = sizes[page_idx]
                    actual_width = size_data[0]
                    actual_height = size_data[1]
                    offset_x = size_data[2] if len(size_data) > 2 else 0.0
                    offset_y = size_data[3] if len(size_data) > 3 else 0.0
                    stored_ratio = (
                        stored_width_pts / stored_height_pts
                        if stored_height_pts
                        else 1.0
                    )
                    actual_ratio = (
                        actual_width / actual_height if actual_height else 1.0
                    )
                    is_rotated = (
                        abs(stored_ratio - actual_ratio) > _ROTATION_ASPECT_THRESHOLD
                    )
                    if is_rotated:
                        scale_x = (
                            actual_height / stored_width_pts
                            if stored_width_pts
                            else 1.0
                        )
                        scale_y = (
                            actual_width / stored_height_pts
                            if stored_height_pts
                            else 1.0
                        )
                    else:
                        scale_x = (
                            actual_width / stored_width_pts if stored_width_pts else 1.0
                        )
                        scale_y = (
                            actual_height / stored_height_pts
                            if stored_height_pts
                            else 1.0
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to get PDF page size for '%s': %s", image_path, exc
                )
        rotation = page.rotation
        return {
            "scale_factor1": page.scale_factor1 or 1.0,
            "scale_factor2": page.scale_factor2 or 1.0,
            "rotation": rotation,
            "flip_x": 1 if page.flip_x else 0,
            "flip_y": 1 if page.flip_y else 0,
            "width": stored_width_pts,
            "height": stored_height_pts,
            "view_scale": _PDF_RENDER_SCALE,
            "coord_scale_x": scale_x,
            "coord_scale_y": scale_y,
            "coord_offset_x": offset_x,
            "coord_offset_y": offset_y,
            "is_page_rotated": is_rotated,
            "auto_rotate_180": False,
        }

    def _collect_takeoffs(
        self,
        bid_takeoffs: List[Takeoff],
        bid_conditions: Dict[str, Condition],
        page_info: PageRenderInfo,
        color_map: Optional[Dict[str, Any]] = None,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Any]:
        polygons = []
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
            if condition_type != _AREA_CONDITION_TYPE:
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
            if self._color_service.should_gray_out_takeoff(
                takeoff, page_area_selections
            ):
                color_rgb = self._color_service.hex_to_rgb_int(_GRAY_COLOR_HEX)
                fill_opacity = _DEFAULT_FILL_OPACITY
            elif color_map and condition_uid in color_map:
                color_entry = color_map[condition_uid]
                hex_color = color_entry.hex
                fill_opacity = color_entry.opacity
                color_rgb = self._color_service.hex_to_rgb_int(hex_color)
            else:
                color_rgb = self._color_service.get_condition_color(condition)
                fill_opacity = _DEFAULT_FILL_OPACITY
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
            polygon_data.label = label
            polygon_data.color = color_rgb
            polygon_data.fill_opacity = fill_opacity
            polygon_data.area_sf = area_sf
            polygon_data.scale_factor1 = scale_factor1
            polygon_data.scale_factor2 = scale_factor2
            polygon_data.depth = depth_ft
            polygons.append(polygon_data)
        for takeoff in bid_takeoffs:
            condition_uid = takeoff.condition_uid
            if condition_uid not in bid_conditions:
                continue
            condition = bid_conditions[condition_uid]
            if not condition.layer_visible:
                continue
            cond_type = condition.condition_type if condition.condition_type else 0
            if cond_type == _AREA_CONDITION_TYPE:
                continue
            if takeoff.is_hole and cond_type != _ATTACHMENT_CONDITION_TYPE:
                continue
            position = self._coord_system.parse_position(takeoff.position)
            if not position or len(position) < 2:
                continue
            verts = None
            area_sf = 0.0
            depth_inches = 0.0
            if cond_type == _LINEAR_CONDITION_TYPE:
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
            elif cond_type in (_COUNT_CONDITION_TYPE, _ATTACHMENT_CONDITION_TYPE):
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
            if self._color_service.should_gray_out_takeoff(
                takeoff, page_area_selections
            ):
                color_rgb = self._color_service.hex_to_rgb_int(_GRAY_COLOR_HEX)
                fill_opacity = _DEFAULT_FILL_OPACITY
            elif color_map and condition_uid in color_map:
                color_entry = color_map[condition_uid]
                hex_color = color_entry.hex
                fill_opacity = color_entry.opacity
                color_rgb = self._color_service.hex_to_rgb_int(hex_color)
            else:
                color_rgb = self._color_service.get_condition_color(condition)
                fill_opacity = _DEFAULT_FILL_OPACITY
            condition_name = condition.name if condition.name else "Takeoff"
            ref_no = condition.ref_no if condition.ref_no else ""
            label = f"{ref_no} - {condition_name}" if ref_no else condition_name
            polygon_data = ost_pdf_writer.PolygonAnnotationData()
            polygon_data.vertices = pdf_vertices
            polygon_data.holes = []
            polygon_data.label = label
            polygon_data.color = color_rgb
            polygon_data.fill_opacity = fill_opacity
            polygon_data.area_sf = area_sf
            polygon_data.scale_factor1 = scale_factor1
            polygon_data.scale_factor2 = scale_factor2
            polygon_data.depth = (
                depth_inches * _INCHES_TO_FEET if depth_inches > 0 else 0.0
            )
            polygons.append(polygon_data)
        return polygons

    def _collect_arrows(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        arrows = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(annotation, page_uid, "arrow"):
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
            if not self._is_annotation_exportable(annotation, page_uid, "rect"):
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
            if not self._is_annotation_exportable(annotation, page_uid, "line"):
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
            if not self._is_annotation_exportable(annotation, page_uid, "dimension"):
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
            if not self._is_annotation_exportable(annotation, page_uid, "oval"):
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
            oval_data = ost_pdf_writer.OvalAnnotationData()
            oval_data.min_x = min(pdf_x1, pdf_x2)
            oval_data.min_y = min(pdf_y1, pdf_y2)
            oval_data.max_x = max(pdf_x1, pdf_x2)
            oval_data.max_y = max(pdf_y1, pdf_y2)
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
                annotation, page_uid, ("polygon", "cloud")
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
            if not self._is_annotation_exportable(annotation, page_uid, "ink"):
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
            if not self._is_annotation_exportable(annotation, page_uid, "highlight"):
                continue
            position = annotation.position
            n_coords = len(position) - 1 if len(position) % 2 == 1 else len(position)
            if n_coords < 4:
                continue
            pdf_points = self._coord_system.ost_to_pdf_coordinates(
                position[:n_coords], page_info
            )
            if len(pdf_points) < 2:
                continue
            strokes, width = self._highlight_ink_strokes(pdf_points)
            if not strokes:
                continue
            highlight_data = ost_pdf_writer.HighlightAnnotationData()
            highlight_data.strokes = strokes
            highlight_data.color = self._color_service.hex_to_rgb_int(annotation.color)
            highlight_data.width = width
            highlight_data.opacity = _DEFAULT_HIGHLIGHT_OPACITY
            highlight_data.content = annotation.get_text_content()
            highlights.append(highlight_data)
        return highlights

    @staticmethod
    def _highlight_ink_strokes(pdf_points):
        strokes = []
        widths = []
        if len(pdf_points) >= 4 and len(pdf_points) % 4 == 0:
            for idx in range(0, len(pdf_points), 4):
                quad = PDFExporter._order_highlight_quad(pdf_points[idx : idx + 4])
                stroke, width = PDFExporter._highlight_stroke_from_quad(quad)
                strokes.append(stroke)
                widths.append(width)
        else:
            quad = PDFExporter._highlight_rect_quad(pdf_points)
            stroke, width = PDFExporter._highlight_stroke_from_quad(quad)
            strokes.append(stroke)
            widths.append(width)
        if not strokes:
            return [], 0.0
        return strokes, max(widths)

    @staticmethod
    def _highlight_rect_quad(pdf_points):
        min_x = min(point[0] for point in pdf_points)
        max_x = max(point[0] for point in pdf_points)
        min_y = min(point[1] for point in pdf_points)
        max_y = max(point[1] for point in pdf_points)
        return [
            [min_x, max_y],
            [max_x, max_y],
            [min_x, min_y],
            [max_x, min_y],
        ]

    @staticmethod
    def _highlight_stroke_from_quad(quad_points):
        left_x = (quad_points[0][0] + quad_points[2][0]) / 2.0
        left_y = (quad_points[0][1] + quad_points[2][1]) / 2.0
        right_x = (quad_points[1][0] + quad_points[3][0]) / 2.0
        right_y = (quad_points[1][1] + quad_points[3][1]) / 2.0
        left_height = math.hypot(
            quad_points[0][0] - quad_points[2][0],
            quad_points[0][1] - quad_points[2][1],
        )
        right_height = math.hypot(
            quad_points[1][0] - quad_points[3][0],
            quad_points[1][1] - quad_points[3][1],
        )
        width = max(1.0, (left_height + right_height) / 2.0)
        return [[left_x, left_y], [right_x, right_y]], width

    @staticmethod
    def _order_highlight_quad(pdf_points):
        by_y = sorted(pdf_points, key=lambda point: point[1], reverse=True)
        top = sorted(by_y[:2], key=lambda point: point[0])
        bottom = sorted(by_y[2:4], key=lambda point: point[0])
        return [
            [top[0][0], top[0][1]],
            [top[1][0], top[1][1]],
            [bottom[0][0], bottom[0][1]],
            [bottom[1][0], bottom[1][1]],
        ]

    def _collect_texts(
        self,
        page_uid: str,
        bid_annotations: List[BidAnnotation],
        page_info: PageRenderInfo,
    ) -> List[Any]:
        texts = []
        for annotation in bid_annotations:
            if not self._is_annotation_exportable(annotation, page_uid, "text"):
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
