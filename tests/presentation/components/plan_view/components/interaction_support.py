import math
import os
import unittest
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.domain.entities import pattern as pattern_values
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_POLYGON,
    BidAnnotation,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components import (
    input_handler as input_handler_module,
)
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
    PlacementModeMixin,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    PolygonControlPointTarget,
    SelectionManagerMixin,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_SELECT,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    set_annotation_style_for_tool,
)
from ost_visualizer.presentation.visualization.core.geometry.linear_geometry import (
    LinearGeometry,
)
from ost_visualizer.presentation.visualization.core.geometry.takeoff_geometry import (
    MINIMUM_RENDERED_LINEAR_THICKNESS,
    MINIMUM_RENDERED_POINT_TAKEOFF_SIZE,
    compute_takeoff_footprint_vertices,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    format_dimension_distance,
)
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QMenu,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _path_has_curve(path: QPainterPath) -> bool:
    return any(
        path.elementAt(index).type == QPainterPath.ElementType.CurveToElement
        for index in range(path.elementCount())
    )


def _preview_paths(view) -> list[QGraphicsPathItem]:
    return [
        item
        for item in view._place_preview_items
        if isinstance(item, QGraphicsPathItem)
    ]


class BaseKeyHandler:
    def keyPressEvent(self, _event):
        pass

    def keyReleaseEvent(self, _event):
        pass

    def mouseMoveEvent(self, _event):
        pass

    def focusOutEvent(self, _event):
        pass


class _FakeSignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _IdentityCoordinateSystem:
    def transform_vertices_to_2d(self, position):
        return list(position)

    def pdf_points_to_screen_pixels(self, value):
        return float(value)


class _PlacementSceneBuilder:
    def __init__(self):
        self._cs = _IdentityCoordinateSystem()

    def get_coordinate_system(self):
        return self._cs


class AnnotationPlacementHarness(PlacementModeMixin):
    def __init__(self):
        self._scene = QGraphicsScene()
        self._scene_builder = _PlacementSceneBuilder()
        self._place_preview_items = []
        self._backout_orig_parent_path = None
        self._backout_parent_uid = None
        self._uid_to_items = {}
        self._place_flashing = False
        self._annotation_place_type = None
        self._annotation_place_points = []
        self._annotation_place_dragging = False
        self._annotation_area_rect_dragging = False
        self._area_in_progress = False
        self._current_bid_page_uid = "page-1"
        self._snap_increments = 1.0
        self.annotation_created = _FakeSignal()
        self.hotlink_placement_requested = _FakeSignal()
        self.area_placement_in_progress = _FakeSignal()
        self.area_progress_states = []
        self.text_drafts = []
        self.named_view_drafts = []
        self.preview_repaints = 0
        self.selection_updates = 0
        self._selected_uids = {"old"}
        self._point_annotation_release_pending = False

    def _current_page_transform(self):
        return None

    def mapToScene(self, point):
        return QtCore.QPointF(point)

    def mapFromScene(self, point):
        return QtCore.QPoint(int(point.x()), int(point.y()))

    def _ost_to_scene_pos(self, ost_x, ost_y):
        return QtCore.QPointF(float(ost_x), float(ost_y))

    def _scene_pos_to_ost(self, scene_pos):
        return QtCore.QPointF(float(scene_pos.x()), float(scene_pos.y()))

    def _pt_to_scene(self, x, y):
        return QtCore.QPointF(float(x), float(y))

    def _current_handle_background_color(self):
        return QColor(255, 255, 255)

    def _request_place_preview_repaint(self):
        self.preview_repaints += 1

    def _placement_snap_from_scene(self, cursor_scene):
        x = float(cursor_scene.x())
        y = float(cursor_scene.y())
        return x, y, x, y, 0

    def _snap_angle_for_placement(self, _x1, _y1, x2, y2, _snap_kind):
        return x2, y2

    def update_selection_visuals(self):
        self.selection_updates += 1

    def clear_selection(self):
        self._selected_uids.clear()
        self.update_selection_visuals()

    def begin_text_annotation_draft(self, position, page_uid):
        self.text_drafts.append((list(position), page_uid))
        return True

    def begin_named_view_draft(self, position, page_uid):
        self.named_view_drafts.append((list(position), page_uid))
        return True

    def _set_area_placement_in_progress(self, in_progress):
        if self._area_in_progress == in_progress:
            return
        self._area_in_progress = in_progress
        self.area_progress_states.append(in_progress)
        self.area_placement_in_progress.emit(in_progress)


class AreaPlacementHarness(PlacementModeMixin):
    def __init__(self):
        self._place_flashing = False
        self._place_points = []
        self._place_area_rect_dragging = False
        self._place_linear_dragging = False
        self._backout_parent_uid = None
        self._backout_active_uid = None
        self._backout_orig_parent_path = None
        self._backout_last_valid_ost = None
        self._scene_builder = _PlacementSceneBuilder()
        self._linear_geom = FakeLinearGeom()
        self._place_session_uid = "area"
        self._current_bid_page_uid = "page-1"
        self._snap_increments = 1.0
        self._current_conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            )
        }
        self._selected_uids = {"old"}
        self.takeoff_created = _FakeSignal()
        self.hole_created = _FakeSignal()
        self.preview_updates = 0
        self.selection_updates = 0
        self.area_progress_states = []
        self.snap_invalidations = 0
        self._area_in_progress = False

    def mapToScene(self, point):
        return QtCore.QPointF(point)

    def _placement_snap_from_scene(self, cursor_scene):
        x = float(cursor_scene.x())
        y = float(cursor_scene.y())
        return x, y, x, y, 0

    def _snap_angle_for_placement(self, _x1, _y1, x2, y2, _snap_kind):
        return x2, y2

    def update_selection_visuals(self):
        self.selection_updates += 1

    def clear_selection(self):
        self._selected_uids.clear()
        self.update_selection_visuals()

    def update_place_preview(self, _scene_pos):
        self.preview_updates += 1

    def clear_place_preview(self):
        pass

    def _set_area_placement_in_progress(self, in_progress):
        if self._area_in_progress == in_progress:
            return
        self._area_in_progress = in_progress
        self.area_progress_states.append(in_progress)

    def _invalidate_snap_index(self):
        self.snap_invalidations += 1

    def is_inside_parent(self, _ost_x, _ost_y):
        return True

    def _point_in_sibling_hole(self, _ost_x, _ost_y):
        return False

    def _check_hole_overlap(self, _pos, parent_uid=None, exclude_uid=None):
        return False

    def enable_backout_placement(self):
        self._backout_parent_uid = "parent"
        self._backout_active_uid = "area"


class _PlacementMouseEvent:
    def __init__(self, x, y):
        self._point = QtCore.QPoint(int(x), int(y))
        self.accepted = False

    def pos(self):
        return self._point

    def position(self):
        return QtCore.QPointF(self._point)

    def accept(self):
        self.accepted = True


class InputHandlerHarness(
    InputHandlerMixin, DragHandlerMixin, SelectionManagerMixin, BaseKeyHandler
):
    def __init__(self):
        self._is_cleaning_up = False
        self._editing_enabled = True
        self._inactive_object_color = Config.DEFAULT_INACTIVE_OBJECT_COLOR
        self._pending_mutation_uids = set()
        self._annotation_only_selection = False
        self.selected_text_annotation_uids = []
        self.editing_text_annotation_uids = []
        self.editing_named_view_uids = []
        self.finished_inline_edits = []
        self.annotation_place_presses = []
        self.annotation_place_releases = []
        self.annotation_place_release_consumed = False
        self._editing_text_annotation_uid = None
        self._editing_named_view_uid = None

    def window(self):
        return self

    def _condition_text_label_at(self, _vp_pos):
        return None

    def reset_ctrl_held(self):
        self._ctrl_held = False

    def _dimension_text_label_at(self, _vp_pos):
        return None

    def _named_view_label_at(self, _vp_pos):
        return None

    def _select_condition_text_label(self, _item):
        pass

    def _select_dimension_text_label(self, _item):
        return False

    def _clear_text_selection(self):
        pass

    def _select_text_annotation_label(self, uid):
        self.selected_text_annotation_uids.append(uid)
        return True

    def _begin_text_annotation_edit(self, uid):
        self.editing_text_annotation_uids.append(uid)
        return True

    def _begin_named_view_rename(self, uid):
        self.editing_named_view_uids.append(uid)
        return True

    def is_text_annotation_inline_edit_active(self):
        return (
            self._editing_text_annotation_uid is not None
            or self._editing_named_view_uid is not None
        )

    def _finish_text_annotation_edit(self, _commit):
        pass

    def _finish_active_inline_text_edit(self, commit):
        self.finished_inline_edits.append(commit)
        self._editing_text_annotation_uid = None
        self._editing_named_view_uid = None

    def _editing_cursor_mode_allowed(self):
        return self._editing_enabled

    def _paste_allowed(self):
        return self._editing_enabled

    def _active_inline_text_editor_contains_scene_point(self, _scene_pos):
        return False

    def handle_annotation_place_press(self, event):
        self.annotation_place_presses.append(event.pos())
        event.accept()
        return True

    def handle_annotation_place_release(self, event):
        self.annotation_place_releases.append(event.pos())
        if self.annotation_place_release_consumed:
            self.annotation_place_release_consumed = False
            event.accept()
            return True
        return False

    def _refresh_condition_text_labels_for_takeoff(self, takeoff_uid):
        path_item = None
        dimension_item = None
        name_item = None
        for item in self._uid_to_items.get(takeoff_uid, []):
            if (
                isinstance(item, QGraphicsPathItem)
                and item.data(2) != "condition_label"
            ):
                path_item = item
            elif (
                isinstance(item, QGraphicsTextItem)
                and item.data(2) == "condition_label"
            ):
                if item.data(3) == "display_dimension":
                    dimension_item = item
                elif item.data(3) == "display_name":
                    name_item = item
        if path_item is None:
            return
        center = path_item.path().boundingRect().center()
        if dimension_item is not None:
            bounds = dimension_item.boundingRect()
            dimension_item.setPos(
                center.x() - bounds.width() / 2.0,
                center.y() - bounds.height() / 2.0,
            )
        if name_item is not None:
            bounds = name_item.boundingRect()
            if dimension_item is not None:
                dim_bounds = dimension_item.boundingRect()
                dim_center_x = dimension_item.pos().x() + dim_bounds.width() / 2.0
                name_item.setPos(
                    dim_center_x - bounds.width() / 2.0,
                    dimension_item.pos().y() + dim_bounds.height() + 4.0,
                )
            else:
                name_item.setPos(
                    center.x() - bounds.width() / 2.0,
                    center.y() - bounds.height() / 2.0,
                )


class FakeMouseEvent:
    def __init__(
        self,
        modifiers=Qt.KeyboardModifier.NoModifier,
        x=10,
        y=10,
        buttons=Qt.MouseButton.LeftButton,
    ):
        self._modifiers = modifiers
        self._point = QtCore.QPoint(x, y)
        self._buttons = buttons
        self.accepted = False

    def button(self):
        return Qt.MouseButton.LeftButton

    def buttons(self):
        return self._buttons

    def modifiers(self):
        return self._modifiers

    def pos(self):
        return self._point

    def position(self):
        return QtCore.QPointF(self._point)

    def accept(self):
        self.accepted = True


class FakeWheelEvent:
    def __init__(self, x=10, y=10):
        self._point = QtCore.QPointF(x, y)

    def position(self):
        return self._point


class FakeCursorViewport:
    def __init__(self):
        self.cursor = None

    def rect(self):
        return QtCore.QRect(0, 0, 200, 200)

    def mapFromGlobal(self, point):
        return QtCore.QPoint(point)

    def setCursor(self, cursor):
        self.cursor = cursor


class FakeKeyEvent:
    def __init__(
        self,
        key=Qt.Key.Key_Control,
        modifiers=Qt.KeyboardModifier.NoModifier,
        auto_repeat=False,
    ):
        self._key = key
        self._modifiers = modifiers
        self._auto_repeat = auto_repeat
        self.accepted = False

    def key(self):
        return self._key

    def modifiers(self):
        return self._modifiers

    def isAutoRepeat(self):
        return self._auto_repeat

    def accept(self):
        self.accepted = True


class FakeSignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class FakeContextMenuEvent:
    def __init__(self, x, y):
        self._point = QtCore.QPoint(int(x), int(y))
        self.accepted = False

    def pos(self):
        return self._point

    def globalPos(self):
        return self._point

    def accept(self):
        self.accepted = True


class CapturingMenu:
    instances = []
    action_text_to_return = None

    def __init__(self, _parent=None):
        self.actions = []
        CapturingMenu.instances.append(self)

    def addAction(self, text):
        action = QAction(str(text))
        self.actions.append(action)
        return action

    def addSeparator(self):
        pass

    def exec(self, _pos):
        if CapturingMenu.action_text_to_return is None:
            return None
        for action in self.actions:
            if (
                isinstance(action, QAction)
                and action.text() == CapturingMenu.action_text_to_return
            ):
                return action
        return None

    def deleteLater(self):
        pass


class FakeItem:
    def __init__(self, x=0.0, y=0.0, uid=None):
        self._pos = QtCore.QPointF(x, y)
        self._uid = uid

    def pos(self):
        return QtCore.QPointF(self._pos)

    def setPos(self, *args):
        if len(args) == 1:
            self._pos = QtCore.QPointF(args[0])
        else:
            self._pos = QtCore.QPointF(args[0], args[1])

    def moveBy(self, dx, dy):
        self._pos += QtCore.QPointF(float(dx), float(dy))

    def data(self, role):
        return self._uid if role == 0 else None

    def scene(self):
        return None


AREA_CP_ORIGINAL_POSITION = [
    0.0,
    0.0,
    100.0,
    0.0,
    100.0,
    100.0,
    0.0,
    100.0,
]
AREA_CP_ADDED_POSITION = [
    0.0,
    0.0,
    50.0,
    0.0,
    100.0,
    0.0,
    100.0,
    100.0,
    0.0,
    100.0,
]
AREA_CP_SUBTRACTED_SECOND_VERTEX_POSITION = [
    0.0,
    0.0,
    100.0,
    100.0,
    0.0,
    100.0,
]
AREA_CP_SUBTRACTED_FIRST_VERTEX_POSITION = [
    100.0,
    0.0,
    100.0,
    100.0,
    0.0,
    100.0,
]
AREA_CP_HOLE_ORIGINAL_POSITION = [
    20.0,
    20.0,
    40.0,
    20.0,
    40.0,
    40.0,
    20.0,
    40.0,
]
AREA_CP_HOLE_ADDED_POSITION = [
    20.0,
    20.0,
    30.0,
    20.0,
    40.0,
    20.0,
    40.0,
    40.0,
    20.0,
    40.0,
]
AREA_CP_HOLE_SUBTRACTED_SECOND_VERTEX_POSITION = [
    20.0,
    20.0,
    40.0,
    40.0,
    20.0,
    40.0,
]


class FakeCoordinateSystem:
    scale_ratio = 1.0
    view_scale = 1.0

    @staticmethod
    def parse_position(position):
        return list(position)

    def transform_vertices_to_2d(self, pos):
        return list(pos)

    def ost_to_screen_pixels(self, value):
        return float(value)

    def pdf_points_to_screen_pixels(self, value):
        return float(value)


class FakeColorService:
    def int_to_hex(self, _color):
        return "#123456"

    def as_hex_with_opacity(self, _entry):
        return "#123456", 1.0

    def get_2d_color_for_takeoff(
        self,
        takeoff,
        _condition,
        color_map,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        color = color_map.get(takeoff.condition_uid, "#123456")
        if (
            page_area_selections
            and page_area_selections.get(takeoff.page_uid) is not None
            and takeoff.area_uid != page_area_selections[takeoff.page_uid]
        ):
            color = inactive_object_color
        return color, 1.0


class FakeTakeoffRendererColorService:
    @staticmethod
    def get_2d_color_for_takeoff(
        takeoff,
        _condition,
        color_map,
        _page_area_selections=None,
        *,
        inactive_object_color,
    ):
        return color_map[takeoff.condition_uid]


class FakeSceneBuilder:
    def __init__(self):
        self.cs = FakeCoordinateSystem()
        self.pattern_angles = []

    def get_coordinate_system(self):
        return self.cs

    def build_pattern_fill(
        self,
        path,
        _pattern_type,
        color,
        _opacity,
        _spacing,
        _line_width,
        orientation_angle=None,
    ):
        self.pattern_angles.append(orientation_angle)
        bounds = path.boundingRect()
        pattern_path = QPainterPath()
        pattern_path.moveTo(bounds.left(), bounds.center().y())
        pattern_path.lineTo(bounds.right(), bounds.center().y())
        item = QGraphicsPathItem(pattern_path)
        item.setPen(QPen(color))
        return None, [item]


class FakeLinearGeom:
    def calc_chord_length(self, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        return (dx * dx + dy * dy) ** 0.5


class IdentityCoordinateSystem:
    def __init__(self, screen_units_per_ost=1.0):
        self.page_info = {"view_scale": 1.0}
        self._screen_units_per_ost = float(screen_units_per_ost)

    @staticmethod
    def parse_position(position):
        return list(position)

    def transform_vertices_to_2d(self, position):
        return [value * self._screen_units_per_ost for value in position]

    def ost_to_pdf_points(self, value):
        return float(value) * self._screen_units_per_ost
