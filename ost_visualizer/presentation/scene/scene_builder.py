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

_TAKEOFF_BODY_Z = 0.5
_TAKEOFF_LABEL_Z = 20.0
_TAKEOFF_DRAW_ORDER_STEP = 0.0000001


def _numeric_takeoff_uid(uid: str) -> int:
    uid_text = str(uid).strip()
    if not uid_text.isdecimal():
        raise ValueError(f"Takeoff UID must be numeric for draw ordering: {uid!r}")
    return int(uid_text)


def _takeoffs_in_draw_order(takeoffs: List[Takeoff]) -> List[Takeoff]:
    indexed_takeoffs = list(enumerate(takeoffs))

    def sort_key(indexed_takeoff: tuple[int, Takeoff]) -> tuple[int, int]:
        index, takeoff = indexed_takeoff
        return (_numeric_takeoff_uid(takeoff.uid), index)

    return [takeoff for _index, takeoff in sorted(indexed_takeoffs, key=sort_key)]


def _takeoff_z_value(base_z: float, draw_index: int) -> float:
    return base_z + (draw_index * _TAKEOFF_DRAW_ORDER_STEP)


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
        orientation_angle: float | None = None,
    ) -> Tuple[Optional[QBrush], List[QGraphicsPathItem]]:
        return self._takeoff_renderer.build_pattern_fill(
            path,
            pattern_type,
            color,
            opacity,
            spacing,
            line_width,
            orientation_angle,
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
        ordered_takeoffs = _takeoffs_in_draw_order(takeoffs)
        uid_to_draw_index = {
            str(takeoff.uid): draw_index
            for draw_index, takeoff in enumerate(ordered_takeoffs)
        }
        items = self._takeoff_renderer.create_all_path_items(
            takeoffs=ordered_takeoffs,
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
                draw_index = uid_to_draw_index[str(uid)]
                if item.data(2) == "condition_label":
                    item.setZValue(_takeoff_z_value(_TAKEOFF_LABEL_Z, draw_index))
                else:
                    item.setZValue(_takeoff_z_value(_TAKEOFF_BODY_Z, draw_index))
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
