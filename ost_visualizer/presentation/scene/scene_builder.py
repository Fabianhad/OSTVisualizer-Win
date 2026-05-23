from typing import Any, Dict, List, Optional, Tuple
from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
)
from ...application.dtos.hotlink_dto import HotlinkDto
from ...application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ...domain.entities.annotation import BidAnnotation
from ...domain.entities.condition import Condition
from ...domain.entities.page import Page
from ...domain.entities.takeoff import Takeoff
from ..interfaces.i_annotation_item_renderer import IAnnotationItemRenderer
from ..interfaces.i_takeoff_renderer import ITakeoffRenderer
from ..utils.page_info_builder import build_page_info as build_page_info_util


class SceneBuilder:
    def __init__(
        self,
        takeoff_renderer: ITakeoffRenderer,
        annotation_renderer: IAnnotationItemRenderer,
    ):
        self._takeoff_renderer = takeoff_renderer
        self._annotation_renderer = annotation_renderer

    def get_coordinate_system(self) -> ICoordinateTransformer:
        return self._takeoff_renderer.coordinate_system

    def build_pattern_fill(
        self,
        path: QPainterPath,
        pattern_type: int,
        color: QColor,
        opacity: float,
        spacing: float,
        line_width: float,
    ) -> Tuple[Optional[QBrush], List[QGraphicsPathItem]]:
        return self._takeoff_renderer.build_pattern_fill(
            path, pattern_type, color, opacity, spacing, line_width
        )

    def create_white_canvas(
        self,
        scene: QGraphicsScene,
        width: float,
        height: float,
        color: Optional[QColor] = None,
    ) -> QGraphicsRectItem:
        canvas = QGraphicsRectItem(0, 0, width, height)
        canvas.setBrush(QBrush(color or QColor(255, 255, 255)))
        canvas.setPen(QPen(QColor(200, 200, 200)))
        canvas.setZValue(-1)
        scene.addItem(canvas)
        return canvas

    def build_page_info(
        self,
        page: Page,
        pdf_width_pts: float,
        pdf_height_pts: float,
        view_scale: float,
        rotation: int,
    ) -> Dict:
        return build_page_info_util(
            page, pdf_width_pts, pdf_height_pts, view_scale, rotation
        )

    def add_takeoff_overlays(
        self,
        scene: QGraphicsScene,
        takeoffs: List[Takeoff],
        conditions: Dict[str, Condition],
        color_map: Dict[str, str],
        page_info: Dict,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> Tuple[List[Any], Dict[str, List[Any]]]:
        takeoff_items = []
        uid_to_items: Dict[str, List[Any]] = {}
        items = self._takeoff_renderer.create_all_path_items(
            takeoffs=takeoffs,
            conditions=conditions,
            color_map=color_map,
            opacity=0.5,
            page_info=page_info,
            page_area_selections=page_area_selections,
        )
        for uid, item_or_items in items:
            items_to_add = (
                item_or_items if isinstance(item_or_items, list) else [item_or_items]
            )
            for item in items_to_add:
                item.setZValue(1)
                scene.addItem(item)
                takeoff_items.append(item)
            uid_to_items[uid] = items_to_add
        return takeoff_items, uid_to_items

    def add_annotation_overlays(
        self,
        scene: QGraphicsScene,
        annotations: List[Tuple[str, BidAnnotation]],
        page_info: Dict,
        current_bid_page_uid: Optional[str],
    ) -> Tuple[
        List[QGraphicsItem],
        List[Tuple[QGraphicsItem, HotlinkDto]],
        Dict[str, List[Any]],
    ]:
        annotation_items = []
        hotlink_items = []
        results, uid_to_items = self._annotation_renderer.create_all_annotation_items(
            annotations, page_info, current_bid_page_uid
        )
        for item, hotlink_info in results:
            scene.addItem(item)
            annotation_items.append(item)
            if hotlink_info is not None:
                hotlink_items.append((item, hotlink_info))
        return annotation_items, hotlink_items, uid_to_items

    def update_scene_rect(self, scene: QGraphicsScene):
        items_rect = scene.itemsBoundingRect()
        if not items_rect.isNull():
            margin = 50
            expanded = items_rect.adjusted(-margin, -margin, margin, margin)
            scene.setSceneRect(expanded)
        else:
            scene.setSceneRect(QRectF())
