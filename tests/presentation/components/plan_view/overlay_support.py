import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.application.services.page_load_strategy_service import (
    LoadStrategy,
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.components.page_loader import (
    VISUAL_KIND_COMPOSITE,
    VISUAL_KIND_OVERLAY,
    VISUAL_KIND_PAGE,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    PlanSurfaceAccessState,
)
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PASTE_BACKOUT,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)
from ost_visualizer.presentation.scene.plan_view_z_order import (
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
)
from ost_visualizer.presentation.scene.scene_builder import SceneBuilder
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
    HighlightGraphicsItem,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
)
from ost_visualizer.presentation.windows.view_window import _VIEW_WINDOW_CONFIG
from PySide6 import QtCore, QtTest, QtWidgets
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
)
from shiboken6 import delete


class FakeUiState:
    active_page_uid = "page-1"
    state = type(
        "State",
        (),
        {
            "display_mode_2d": "condition",
            "display_mode_3d": "condition",
            "display_modes_synced": True,
            "grayscale_enabled": False,
        },
    )()
    place_condition_uid = None
    place_condition_uids = []

    def get_selected_bid_ref(self):
        return BidRef(file_path="bid.mdb", bid_uid="bid-1")


class FakeProjectData:
    def __init__(self):
        self.page = Page(uid="page-1", name="Page 1")
        self.bid = Bid(uid="bid-1", name="Bid", takeoff_increments=2.0)

    def get_page(self, page_uid):
        return self.page if page_uid == self.page.uid else None

    def get_all_pages(self):
        return [self.page]

    def get_bid_conditions(self):
        return {}

    def get_page_takeoffs(self, _page_uid):
        return []

    def get_page_annotations(self, _page_uid):
        return []

    def get_page_area_selections(self):
        return {}

    def get_hidden_layer_uids(self):
        return {"annotation-layer"}

    def is_annotation_layer_visible(self):
        return True

    def get_bid(self, _bid_ref):
        return self.bid


class FakeColorService:
    def get_color_mapping(self, *_args):
        return {}, {}

    def is_inactive_area_takeoff(self, takeoff, page_area_selections):
        if not page_area_selections:
            return False
        selected_area_uid = page_area_selections.get(str(takeoff.page_uid))
        return selected_area_uid is not None and takeoff.area_uid != selected_area_uid


class FakeVisualizationService:
    def __init__(self):
        self.mesh_pages = []

    def refresh_mesh_view(self, page_uids):
        self.mesh_pages.append(list(page_uids))


class FakeLinearGeometry:
    pass


class FakeCoordinateSystem:
    scale_ratio = 72.0
    view_scale = 1.0

    @staticmethod
    def parse_position(position):
        return list(position)

    def ost_to_screen_pixels(self, value):
        return value

    def pdf_points_to_screen_pixels(self, value):
        return value

    def transform_to_2d(self, x, y):
        return x, y

    def transform_vertices_to_2d(self, values):
        return list(values)

    def update_page_info(self, _page_info):
        pass


class FakeTakeoffRenderer:
    coordinate_system = FakeCoordinateSystem()

    def create_all_path_items(
        self,
        takeoffs,
        conditions,
        color_map,
        opacity,
        page_info,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = (color_map, opacity, page_area_selections, inactive_object_color)
        return []


class RecordingPathTakeoffRenderer:
    coordinate_system = FakeCoordinateSystem()

    def __init__(self):
        self.calls = []

    def create_all_path_items(
        self,
        takeoffs,
        conditions,
        color_map,
        opacity,
        page_info,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = (conditions, color_map, opacity, page_info, page_area_selections)
        self.calls.append([takeoff.uid for takeoff in takeoffs])
        results = []
        for takeoff in takeoffs:
            path = QPainterPath()
            path.addRect(0.0, 0.0, 10.0, 10.0)
            item = QGraphicsPathItem(path)
            item.setData(0, takeoff.uid)
            item.setData(1, takeoff.condition_uid)
            results.append((takeoff.uid, item))
        return results


class FakeAnnotationRenderer:
    def create_all_annotation_items(
        self, annotations, _page_info, _current_bid_page_uid
    ):
        results = []
        uid_to_items = {}
        for uid, annotation in annotations:
            if annotation.is_hotlink:
                position = annotation.position or []
                item = QGraphicsPathItem()
                item.setData(0, uid)
                item.setPos(
                    position[0] if position else 0.0,
                    position[1] if len(position) > 1 else 0.0,
                )
                hotlink = HotlinkDto(
                    uid=annotation.uid,
                    bid_page_uid=annotation.page_uid,
                    target_view_uid=annotation.properties.get("BidPageViewUID"),
                    center_x=item.pos().x(),
                    center_y=item.pos().y(),
                    radius=10.0,
                )
                results.append((item, hotlink))
                uid_to_items[uid] = [item]
                continue
            if annotation.is_dimension:
                item = QGraphicsTextItem("21' - 3\"")
                item.setData(0, uid)
                item.setData(2, DIMENSION_LABEL_ITEM_KIND)
                font = QFont(
                    str(annotation.properties.get("FontName", "Arial")),
                    int(annotation.properties.get("FontSize", 10) or 10),
                )
                font.setBold(bool(annotation.properties.get("FontBold", False)))
                font.setItalic(bool(annotation.properties.get("FontItalic", False)))
                font.setUnderline(
                    bool(annotation.properties.get("FontUnderline", False))
                )
                item.setFont(font)
                color = int(annotation.properties.get("FontColor", 0) or 0)
                item.setDefaultTextColor(
                    QColor(color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF)
                )
                if len(annotation.position) >= 4:
                    item.setPos(
                        (annotation.position[0] + annotation.position[2]) / 2.0,
                        (annotation.position[1] + annotation.position[3]) / 2.0,
                    )
                results.append((item, None))
                uid_to_items[uid] = [item]
                continue
            if annotation.is_namedview:
                rect_item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
                rect_item.setData(0, uid)
                label_item = QGraphicsTextItem(
                    str(annotation.properties.get("Text", ""))
                )
                label_item.setData(0, uid)
                label_item.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
                background_item = QGraphicsRectItem(0.0, 0.0, 10.0, 4.0)
                background_item.setData(0, uid)
                background_item.setData(2, NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND)
                items = [rect_item, background_item, label_item]
                results.extend((item, None) for item in items)
                uid_to_items[uid] = items
                continue
            if not annotation.is_text:
                continue
            width = annotation.position[2] if len(annotation.position) >= 4 else 80.0
            height = annotation.position[3] if len(annotation.position) >= 4 else 24.0
            item = ClippedTextGraphicsItem(
                str(annotation.properties.get("Text", "")),
                QtCore.QRectF(0.0, 0.0, width, height),
            )
            item.setData(0, uid)
            item.setTextWidth(width)
            font = QFont(
                str(annotation.properties.get("FontName", "Arial")),
                int(annotation.properties.get("FontSize", 12) or 12),
            )
            font.setBold(bool(annotation.properties.get("FontBold", False)))
            font.setItalic(bool(annotation.properties.get("FontItalic", False)))
            font.setUnderline(bool(annotation.properties.get("FontUnderline", False)))
            item.setFont(font)
            color = int(annotation.properties.get("FontColor", 0) or 0)
            item.setDefaultTextColor(
                QColor(color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF)
            )
            option = QTextOption(item.document().defaultTextOption())
            text_align = int(annotation.properties.get("TextAlign", 0) or 0)
            if text_align == 1:
                option.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            elif text_align == 2:
                option.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            else:
                option.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            item.document().setDefaultTextOption(option)
            if len(annotation.position) >= 4:
                item.setPos(
                    annotation.position[0] - width / 2.0,
                    annotation.position[1] - height / 2.0,
                )
            results.append((item, None))
            uid_to_items[uid] = [item]
        return results, uid_to_items


class FakeRenderingService:
    def __init__(self):
        self.page_requests = []
        self.overlay_requests = []
        self.composite_requests = []
        self.frame_requests = []
        self.composite_frame_requests = []
        self.job_requests = []
        self.cancelled_requests = []
        self._request_counter = 0
        self.shutdown_calls = 0

    def _next_request_id(self, prefix):
        self._request_counter += 1
        return f"{prefix}-{self._request_counter}"

    def render_page_async(
        self,
        file_path,
        page_index,
        scale,
        rotation,
        callback,
        priority=0,
        invert=False,
        bitonal=False,
        tint_rgb=None,
        apply_invert_effect=True,
        apply_bitonal_effect=True,
    ):
        request_id = self._next_request_id("page")
        render_options = {
            "file_path": file_path,
            "page_index": page_index,
            "scale": scale,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
            "invert": invert,
            "bitonal": bitonal,
            "tint_rgb": tint_rgb,
            "apply_invert_effect": apply_invert_effect,
            "apply_bitonal_effect": apply_bitonal_effect,
        }
        self.page_requests.append((request_id, render_options))
        return request_id

    def render_overlay_async(
        self,
        page,
        show_mode,
        rotation,
        render_scale,
        callback,
        priority=0,
        apply_invert_effect=True,
        apply_bitonal_effect=True,
    ):
        request_id = self._next_request_id("overlay")
        render_options = {
            "page": page,
            "show_mode": show_mode,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
            "render_scale": render_scale,
            "apply_invert_effect": apply_invert_effect,
            "apply_bitonal_effect": apply_bitonal_effect,
        }
        self.overlay_requests.append((request_id, render_options))
        return request_id

    def render_composite_async(
        self,
        page,
        bid_ref,
        render_scale,
        rotation,
        callback,
        priority=0,
    ):
        request_id = self._next_request_id("composite")
        render_options = {
            "page": page,
            "bid_ref": bid_ref,
            "render_scale": render_scale,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
        }
        self.composite_requests.append((request_id, render_options))
        return request_id

    def render_frame_async(
        self,
        file_path,
        page_index,
        scale,
        rotation,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        callback,
        priority=1,
        invert=False,
        bitonal=False,
        tint_rgb=None,
    ):
        request_id = self._next_request_id("frame")
        render_options = {
            "file_path": file_path,
            "page_index": page_index,
            "scale": scale,
            "rotation": rotation,
            "frame_x_pts": frame_x_pts,
            "frame_y_pts": frame_y_pts,
            "frame_w_pts": frame_w_pts,
            "frame_h_pts": frame_h_pts,
            "callback": callback,
            "priority": priority,
            "invert": invert,
            "bitonal": bitonal,
            "tint_rgb": tint_rgb,
        }
        self.frame_requests.append((request_id, render_options))
        return request_id

    def render_composite_frame_async(
        self,
        page,
        bid_ref,
        scale,
        rotation,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        callback,
        priority=1,
    ):
        request_id = self._next_request_id("composite-frame")
        render_options = {
            "page": page,
            "bid_ref": bid_ref,
            "scale": scale,
            "rotation": rotation,
            "frame_x_pts": frame_x_pts,
            "frame_y_pts": frame_y_pts,
            "frame_w_pts": frame_w_pts,
            "frame_h_pts": frame_h_pts,
            "callback": callback,
            "priority": priority,
        }
        self.composite_frame_requests.append((request_id, render_options))
        return request_id

    def cancel_request(self, request_id):
        self.cancelled_requests.append(request_id)

    def run_job_async(self, job, callback, priority=2):
        request_id = self._next_request_id("job")
        self.job_requests.append((request_id, job, callback, priority))
        return request_id

    def extract_pdf_text_async(self, file_path, page_index, callback, priority=2):
        del file_path, page_index, callback, priority
        return self._next_request_id("text")

    def shutdown(self):
        self.shutdown_calls += 1


class FakeLoadCoordinator:
    def determine_load_strategy(self, page):
        load_composite = bool(
            page.image_path and page.overlay_image_path and page.image_show_mode == 2
        )
        return LoadStrategy(
            needs_async_loading=bool(page.image_path or page.overlay_image_path),
            view_scale=2.0,
            show_canvas=True,
            pdf_width_pts=page.width_pts or 612.0,
            pdf_height_pts=page.height_pts or 792.0,
            placeholder_width=(page.width_pts or 612.0) * 2.0,
            placeholder_height=(page.height_pts or 792.0) * 2.0,
            load_composite=load_composite,
            load_main=bool(page.image_path and not load_composite),
            load_overlay=bool(page.overlay_image_path and not page.image_path),
            main_scale=2.0,
        )

    def create_pending_page_data(self, page, strategy, pdf_width_pts, pdf_height_pts):
        return {
            "page": page,
            "rotation": page.rotation,
            "show_mode": page.image_show_mode,
            "show_overlay": page.image_show_mode in (1, 2) and page.has_overlay,
            "pdf_width_pts": pdf_width_pts,
            "pdf_height_pts": pdf_height_pts,
            "view_scale": strategy.view_scale,
        }


class FakePlanView:
    def __init__(self, current_page_uid="page-1", overlay_result=True):
        self.current_page_uid = current_page_uid
        self.overlay_result = overlay_result
        self.overlay_calls = 0
        self.load_calls = 0
        self.clear_calls = 0
        self.snap_settings = []
        self.overlay_options = []
        self.load_options = []
        self.prefetch_calls = []

    def clear(self):
        self.clear_calls += 1
        self.current_page_uid = None

    def refresh_current_page_overlays(
        self,
        page,
        takeoffs,
        conditions,
        color_map,
        bid_ref=None,
        annotations=None,
        page_area_selections=None,
        hidden_layer_uids=None,
        changed_takeoff_uids=None,
        changed_annotation_uids=None,
        changed_annotation_types=None,
        force_overlay_refresh=False,
    ):
        self.overlay_calls += 1
        self.overlay_options.append(
            {
                "page": page,
                "takeoffs": takeoffs,
                "conditions": conditions,
                "color_map": color_map,
                "bid_ref": bid_ref,
                "annotations": annotations,
                "page_area_selections": page_area_selections,
                "hidden_layer_uids": hidden_layer_uids,
                "changed_takeoff_uids": changed_takeoff_uids,
                "changed_annotation_uids": changed_annotation_uids,
                "changed_annotation_types": changed_annotation_types,
                "force_overlay_refresh": force_overlay_refresh,
            }
        )
        return self.overlay_result

    def load_page(
        self,
        page,
        takeoffs,
        conditions,
        color_map,
        bid_ref=None,
        annotations=None,
        page_area_selections=None,
        hidden_layer_uids=None,
    ):
        self.load_calls += 1
        self.load_options.append(
            {
                "page": page,
                "takeoffs": takeoffs,
                "conditions": conditions,
                "color_map": color_map,
                "bid_ref": bid_ref,
                "annotations": annotations,
                "page_area_selections": page_area_selections,
                "hidden_layer_uids": hidden_layer_uids,
            }
        )
        return True

    def set_snap_settings(self, increments, measure_base):
        self.snap_settings.append((increments, measure_base))

    def prefetch_nearby_pages(self, page, ordered_pages, bid_ref):
        self.prefetch_calls.append((page, ordered_pages, bid_ref))


class FakeViewport:
    def __init__(self, calls):
        self._calls = calls

    def update(self):
        self._calls.append("viewport.update")


class FakeScene:
    def __init__(self):
        self._scene_rect = QtCore.QRectF(-50.0, -50.0, 10050.0, 10050.0)
        self.set_scene_rect_calls = 0

    def sceneRect(self):
        return self._scene_rect

    def setSceneRect(self, rect):
        self.set_scene_rect_calls += 1
        self._scene_rect = rect


class FakePageItem:
    def __init__(self, scene, rect=None):
        self._scene = scene
        self._rect = rect or QtCore.QRectF(0.0, 0.0, 100.0, 200.0)

    def scene(self):
        return self._scene

    def sceneBoundingRect(self):
        return self._rect

    def pos(self):
        return QtCore.QPointF(0.0, 0.0)


class FakeTransform:
    def m11(self):
        return 1.0


class FakeDebouncer:
    def __init__(self, calls):
        self._calls = calls

    def handle_scale_changed(self, value):
        self._calls.append(("scale", value))


class FakeSignal:
    def __init__(self, calls):
        self._calls = calls

    def emit(self, value):
        self._calls.append(("zoom", value))


class FakeScrollBar:
    def maximum(self):
        return 0

    def setValue(self, _value):
        pass


class FakeSizedViewport:
    def size(self):
        return QtCore.QSize(100, 100)

    def rect(self):
        return QtCore.QRect(0, 0, 100, 100)


class FakePageSizeProvider:
    def get_page_size(self, _file_path, _page_index):
        return 612.0, 792.0
