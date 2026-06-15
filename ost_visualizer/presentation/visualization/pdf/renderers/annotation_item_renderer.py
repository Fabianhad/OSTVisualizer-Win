import math
from typing import Any, Dict, List, Optional, Tuple
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
)
from .....application.dtos.hotlink_dto import HotlinkDto
from .....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from .....domain.entities.annotation import BidAnnotation
from ....components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
)
from .annotation_renderer import (
    calculate_annotation_geometry,
    calculate_dimension_segments,
    create_cloud_path_points,
    process_text_for_box,
)

AnnotationItemResult = Tuple[QGraphicsItem, Optional[HotlinkDto]]
AnnotationItemsResult = Tuple[
    "List[AnnotationItemResult]", "Dict[str, List[QGraphicsItem]]"
]
DIMENSION_FONT_SIZE_ADJUSTMENT = 0.75
NAMED_VIEW_FONT_SIZE_ADJUSTMENT = 0.75


def create_named_view_label_font(coord_system) -> QFont:
    scaled_font_size = max(
        10,
        coord_system.pdf_points_to_screen_pixels(12) * NAMED_VIEW_FONT_SIZE_ADJUSTMENT,
    )
    font = QFont("Arial", int(scaled_font_size))
    font.setBold(True)
    return font


def build_dimension_path(dimension: Dict, coord_system) -> QPainterPath:
    x1 = dimension["x1"]
    y1 = dimension["y1"]
    x2 = dimension["x2"]
    y2 = dimension["y2"]
    font_size = float(dimension.get("font_size") or 10.0)
    tick_length = max(10.0, coord_system.pdf_points_to_screen_pixels(font_size) * 0.8)
    segments = calculate_dimension_segments(x1, y1, x2, y2, tick_length)
    path = QPainterPath()
    for sx1, sy1, sx2, sy2 in segments:
        path.moveTo(sx1, sy1)
        path.lineTo(sx2, sy2)
    return path


def update_dimension_text_item(
    text_item: QGraphicsTextItem,
    dimension: Dict,
    color: str,
    coord_system,
    font_size_adjustment: float,
) -> bool:
    label = dimension.get("label", "")
    if not label:
        return False
    x1 = dimension["x1"]
    y1 = dimension["y1"]
    x2 = dimension["x2"]
    y2 = dimension["y2"]
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return False
    font_size = float(dimension.get("font_size") or 10.0)
    scaled_font_size = max(
        6.0,
        coord_system.pdf_points_to_screen_pixels(font_size) * font_size_adjustment,
    )
    font = QFont(dimension.get("font_name", "Arial"), int(scaled_font_size))
    font.setBold(dimension.get("font_bold", False))
    font.setItalic(dimension.get("font_italic", False))
    font.setUnderline(dimension.get("font_underline", False))
    metrics = QFontMetrics(font)
    text_width = max(1.0, float(metrics.horizontalAdvance(label)))
    text_height = max(1.0, float(metrics.height()))
    nx = -dy / length
    ny = dx / length
    offset = max(6.0, min(18.0, text_height * 0.45))
    center_x = (x1 + x2) / 2.0 - nx * offset
    center_y = (y1 + y2) / 2.0 - ny * offset
    angle = math.degrees(math.atan2(dy, dx))
    if angle > 90.0 or angle < -90.0:
        angle += 180.0
    text_item.setPlainText(label)
    text_item.document().setDocumentMargin(0.0)
    text_item.setFont(font)
    text_item.setDefaultTextColor(QColor(color))
    text_item.setTextWidth(text_width)
    text_item.setPos(center_x - text_width / 2.0, center_y - text_height / 2.0)
    text_item.setTransformOriginPoint(text_width / 2.0, text_height / 2.0)
    text_item.setRotation(angle)
    text_item.setZValue(3)
    return True


def create_dimension_text_item(
    dimension: Dict,
    color: str,
    coord_system,
    font_size_adjustment: float,
) -> Optional[QGraphicsTextItem]:
    text_item = QGraphicsTextItem()
    if not update_dimension_text_item(
        text_item, dimension, color, coord_system, font_size_adjustment
    ):
        return None
    return text_item


class AnnotationItemRenderer:
    FONT_SIZE_ADJUSTMENT = DIMENSION_FONT_SIZE_ADJUSTMENT

    def __init__(self, coord_system: ICoordinateTransformer):
        self._cs = coord_system

    @property
    def coordinate_system(self) -> ICoordinateTransformer:
        return self._cs

    def set_page_info(self, page_info: Dict[str, Any]) -> None:
        self._cs.update_page_info(page_info)

    def create_all_annotation_items(
        self,
        annotations: List[Tuple[str, BidAnnotation]],
        page_info: Optional[Dict[str, Any]] = None,
        bid_page_uid: Optional[str] = None,
    ) -> AnnotationItemsResult:
        if page_info:
            self.set_page_info(page_info)
        results: List[AnnotationItemResult] = []
        uid_to_items: Dict[str, List[QGraphicsItem]] = {}
        for key, annotation in annotations:
            geom = calculate_annotation_geometry(
                annotation, self._cs.transform_vertices_to_2d
            )
            if not geom:
                continue
            items = self._create_items_from_geometry(geom, bid_page_uid)
            for item, _ in items:
                item.setData(0, key)
            uid_to_items[key] = [item for item, _ in items]
            results.extend(items)
        return results, uid_to_items

    def _create_items_from_geometry(
        self, geom: Dict, bid_page_uid: Optional[str]
    ) -> List[AnnotationItemResult]:
        anno_type = geom["type"]
        color = geom["color"]
        width = geom["width"]
        if anno_type == "text" and "text" in geom:
            return self._render_text(geom["text"], color)
        elif anno_type in ("cloud", "polygon", "ink") and "points" in geom:
            return self._render_path(anno_type, geom["points"], color, width)
        elif anno_type == "oval" and "oval" in geom:
            return self._render_oval(geom["oval"], color, width)
        elif anno_type in ("rect", "highlight") and "shape" in geom:
            return self._render_rotated_shape(anno_type, geom["shape"], color, width)
        elif anno_type in ("oval", "rect") and "bounds" in geom:
            return self._render_shape(anno_type, geom["bounds"], color, width)
        elif anno_type in ("line", "arrow") and "line" in geom:
            return self._render_line(anno_type, geom["line"], color, width)
        elif anno_type == "dimension" and "dimension" in geom:
            return self._render_dimension(geom["dimension"], color, width)
        elif anno_type == "highlight" and "bounds" in geom:
            return self._render_highlight(geom["bounds"], color)
        elif anno_type == "namedview" and "namedview" in geom:
            return self._render_namedview(geom["namedview"])
        elif anno_type == "hotlink" and "hotlink" in geom:
            return self._render_hotlink(geom["hotlink"], color, width, bid_page_uid)
        return []

    def _render_text(self, text_info: Dict, color: str) -> List[AnnotationItemResult]:
        content = text_info.get("content", "")
        center_x = text_info["center_x"]
        center_y = text_info["center_y"]
        box_width = text_info["box_width"]
        box_height = text_info["box_height"]
        rotation = text_info.get("rotation", 0)
        top_left_x = center_x - box_width / 2
        top_left_y = center_y - box_height / 2
        screen_x, screen_y = self._cs.transform_to_2d(top_left_x, top_left_y)
        scaled_font_size = (
            self._cs.pdf_points_to_screen_pixels(text_info["font_size"])
            * self.FONT_SIZE_ADJUSTMENT
        )
        scaled_box_width = self._cs.ost_to_screen_pixels(box_width)
        font = QFont(text_info["font_name"], int(scaled_font_size))
        font.setBold(text_info.get("font_bold", False))
        font.setItalic(text_info.get("font_italic", False))
        font.setUnderline(text_info.get("font_underline", False))
        metrics = QFontMetrics(font)
        final_text = process_text_for_box(content, scaled_box_width, 0, metrics)
        scaled_box_height = self._cs.ost_to_screen_pixels(box_height)
        text_item = ClippedTextGraphicsItem(
            final_text, QRectF(0.0, 0.0, scaled_box_width, scaled_box_height)
        )
        text_item.setFont(font)
        text_item.setDefaultTextColor(QColor(color))
        text_item.setTextWidth(scaled_box_width)
        doc = text_item.document()
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        text_align = text_info.get("text_align", 0)
        if text_align == 1:
            option.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif text_align == 2:
            option.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            option.setAlignment(Qt.AlignmentFlag.AlignLeft)
        doc.setDefaultTextOption(option)
        text_item.setPos(screen_x, screen_y)
        if rotation != 0:
            text_item.setTransformOriginPoint(
                scaled_box_width / 2, scaled_box_height / 2
            )
            text_item.setRotation(rotation)
        text_item.setZValue(2)
        return [(text_item, None)]

    def _render_path(
        self,
        anno_type: str,
        points: List[Tuple[float, float]],
        color: str,
        width: float,
    ) -> List[AnnotationItemResult]:
        if len(points) < 2:
            return []
        path = QPainterPath()
        if anno_type == "cloud":
            segments = create_cloud_path_points(points)
            for idx, (start, cp1, cp2, end) in enumerate(segments):
                if idx == 0:
                    path.moveTo(points[0][0], points[0][1])
                path.cubicTo(cp1[0], cp1[1], cp2[0], cp2[1], end[0], end[1])
            path.closeSubpath()
        else:
            path.moveTo(points[0][0], points[0][1])
            for x, y in points[1:]:
                path.lineTo(x, y)
            if anno_type == "polygon":
                path.closeSubpath()
        item = self._create_path_item(path, color, width)
        if item is None:
            return []
        return [(item, None)]

    def _render_oval(
        self, oval_info: Dict, color: str, width: float
    ) -> List[AnnotationItemResult]:
        cx = oval_info["cx"]
        cy = oval_info["cy"]
        w = oval_info["w"]
        h = oval_info["h"]
        vis_deg = oval_info.get("rotation_deg", 0.0)
        rect = QRectF(cx - w / 2, cy - h / 2, w, h)
        path = QPainterPath()
        path.addEllipse(rect)
        item = self._create_path_item(path, color, width)
        if item is None:
            return []
        if vis_deg != 0.0:
            item.setTransformOriginPoint(cx, cy)
            item.setRotation(vis_deg)
        return [(item, None)]

    def _render_rotated_shape(
        self, anno_type: str, shape: Dict, color: str, width: float
    ) -> List[AnnotationItemResult]:
        corners = shape["corners"]
        ordered = [corners[0], corners[3], corners[1], corners[2]]
        path = QPainterPath()
        path.moveTo(ordered[0][0], ordered[0][1])
        for c in ordered[1:]:
            path.lineTo(c[0], c[1])
        path.closeSubpath()
        item = self._create_path_item(path, color, width)
        if item is None:
            return []
        if anno_type == "highlight":
            qcolor = QColor(color)
            qcolor.setAlphaF(0.3)
            item.setBrush(qcolor)
            item.setZValue(1)
        return [(item, None)]

    def _render_shape(
        self, anno_type: str, bounds: Dict, color: str, width: float
    ) -> List[AnnotationItemResult]:
        min_x = bounds["min_x"]
        max_x = bounds["max_x"]
        min_y = bounds["min_y"]
        max_y = bounds["max_y"]
        rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        path = QPainterPath()
        if anno_type == "oval":
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        item = self._create_path_item(path, color, width)
        if item is None:
            return []
        return [(item, None)]

    def _render_line(
        self, anno_type: str, line: Dict, color: str, width: float
    ) -> List[AnnotationItemResult]:
        x1, y1 = line["x1"], line["y1"]
        x2, y2 = line["x2"], line["y2"]
        path = QPainterPath()
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
        if anno_type == "arrow":
            arrow_size = max(width * 20, 24.0)
            angle = math.atan2(y2 - y1, x2 - x1)
            arrow_angle = math.radians(30)
            left_x = x2 - arrow_size * math.cos(angle - arrow_angle)
            left_y = y2 - arrow_size * math.sin(angle - arrow_angle)
            right_x = x2 - arrow_size * math.cos(angle + arrow_angle)
            right_y = y2 - arrow_size * math.sin(angle + arrow_angle)
            path.moveTo(left_x, left_y)
            path.lineTo(x2, y2)
            path.lineTo(right_x, right_y)
        item = self._create_path_item(path, color, width)
        if item is None:
            return []
        return [(item, None)]

    def _build_dimension_path(self, dimension: Dict) -> QPainterPath:
        return build_dimension_path(dimension, self._cs)

    def _render_dimension(
        self, dimension: Dict, color: str, width: float
    ) -> List[AnnotationItemResult]:
        path = self._build_dimension_path(dimension)
        if path.isEmpty():
            return []
        path_item = self._create_path_item(path, color, width)
        if path_item is None:
            return []
        results: List[AnnotationItemResult] = [(path_item, None)]
        label = dimension.get("label", "")
        if label:
            text_item = create_dimension_text_item(
                dimension, color, self._cs, self.FONT_SIZE_ADJUSTMENT
            )
            if text_item is not None:
                text_item.setData(2, DIMENSION_LABEL_ITEM_KIND)
                text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
                results.append((text_item, None))
        return results

    def _render_highlight(self, bounds: Dict, color: str) -> List[AnnotationItemResult]:
        min_x = bounds["min_x"]
        max_x = bounds["max_x"]
        min_y = bounds["min_y"]
        max_y = bounds["max_y"]
        rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        item = QGraphicsRectItem(rect)
        qcolor = QColor(color)
        qcolor.setAlphaF(0.3)
        item.setBrush(qcolor)
        item.setPen(Qt.PenStyle.NoPen)
        item.setZValue(1)
        return [(item, None)]

    def _render_namedview(self, view_info: Dict) -> List[AnnotationItemResult]:
        min_x = view_info["min_x"]
        min_y = view_info["min_y"]
        max_x = view_info["max_x"]
        max_y = view_info["max_y"]
        content = view_info.get("content", "")
        rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        rect_item = QGraphicsRectItem(rect)
        green_color = QColor(0, 128, 0)
        rect_item.setBrush(Qt.GlobalColor.transparent)
        pen = QPen(green_color)
        pen.setWidthF(2.0)
        pen.setCosmetic(True)
        rect_item.setPen(pen)
        rect_item.setZValue(2)
        results: List[AnnotationItemResult] = [(rect_item, None)]
        if content:
            font = create_named_view_label_font(self._cs)
            metrics = QFontMetrics(font)
            text_width = metrics.horizontalAdvance(content)
            text_height = metrics.height()
            padding = 3
            text_x = min_x + padding
            text_y = min_y + padding
            bg_rect = QRectF(
                text_x - padding,
                text_y - padding,
                text_width + padding * 2,
                text_height + padding * 2,
            )
            bg_item = QGraphicsRectItem(bg_rect)
            bg_item.setBrush(green_color)
            bg_item.setPen(Qt.PenStyle.NoPen)
            bg_item.setZValue(3)
            bg_item.setData(2, NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND)
            results.append((bg_item, None))
            text_item = QGraphicsTextItem(content)
            text_item.setFont(font)
            text_item.setDefaultTextColor(QColor("white"))
            text_item.setPos(text_x - 4, text_y - 4)
            text_item.setZValue(4)
            text_item.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
            results.append((text_item, None))
        return results

    def _render_hotlink(
        self,
        link_info: Dict,
        color: str,
        width: float,
        bid_page_uid: Optional[str],
    ) -> List[AnnotationItemResult]:
        center_x = link_info["center_x"]
        center_y = link_info["center_y"]
        radius = self._cs.pdf_points_to_screen_pixels(15.0)
        rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)
        path = QPainterPath()
        path.addEllipse(rect)
        triangle_size = radius * 0.5
        tx1 = center_x + triangle_size
        ty1 = center_y
        tx2 = center_x - triangle_size * 0.5
        ty2 = center_y - triangle_size * 0.8
        tx3 = center_x - triangle_size * 0.5
        ty3 = center_y + triangle_size * 0.8
        path.moveTo(tx1, ty1)
        path.lineTo(tx2, ty2)
        path.lineTo(tx3, ty3)
        path.closeSubpath()
        item = QGraphicsPathItem(path)
        qcolor = QColor(color)
        pen = QPen(qcolor)
        pen.setWidthF(width)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(Qt.GlobalColor.transparent)
        item.setZValue(2)
        full_link_info = HotlinkDto(
            uid=link_info.get("uid", ""),
            bid_page_uid=link_info.get("bid_page_uid") or bid_page_uid or "",
            target_view_uid=link_info.get("target_view_uid")
            or link_info.get("BidPageViewUID"),
            center_x=center_x,
            center_y=center_y,
            radius=radius,
        )
        return [(item, full_link_info)]

    @staticmethod
    def _create_path_item(
        path: QPainterPath, color: str, width: float
    ) -> Optional[QGraphicsPathItem]:
        if path.isEmpty():
            return None
        item = QGraphicsPathItem(path)
        qcolor = QColor(color)
        pen = QPen(qcolor)
        pen.setWidthF(width)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(Qt.GlobalColor.transparent)
        item.setZValue(2)
        return item
