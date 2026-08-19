import math
import os
import unittest
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
)
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
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


class RemoteProjectionBlockerTests(unittest.TestCase):
    @staticmethod
    def _plan_state(**overrides):
        state = {
            "_editing_annotation_uids": lambda: set(),
            "_drag_plan_item_uid": None,
            "_rotation_drag_active": False,
            "_overlay_move_dragging": False,
            "_annotation_place_dragging": False,
            "_annotation_area_rect_dragging": False,
            "_place_linear_dragging": False,
            "_place_area_rect_dragging": False,
            "_dirty_positions": {},
            "_dirty_ann_positions": {},
            "_place_preview_items": [],
            "_paste_backout_preview_items": [],
        }
        state.update(overrides)
        return SimpleNamespace(**state)

    def test_passive_placement_hover_preview_does_not_block_projection(self):
        view = self._plan_state(_place_preview_items=[object()])
        self.assertFalse(TakeoffPlanView.has_active_remote_projection_blocker(view))

    def test_active_placement_gesture_still_blocks_projection(self):
        view = self._plan_state(
            _place_preview_items=[object()],
            _place_linear_dragging=True,
        )
        self.assertTrue(TakeoffPlanView.has_active_remote_projection_blocker(view))


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


class CtrlDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _rendered_box_side_lengths(self, position):
        points = [
            (position[0], position[1]),
            (position[6], position[7]),
            (position[2], position[3]),
            (position[4], position[5]),
        ]
        return sorted(
            round(
                math.hypot(
                    points[(index + 1) % 4][0] - points[index][0],
                    points[(index + 1) % 4][1] - points[index][1],
                ),
                6,
            )
            for index in range(4)
        )

    def _make_view(self, selected_uids=None):
        view = InputHandlerHarness()
        view._cursor_mode = "select"
        view._selection_enabled = True
        view._ctrl_held = False
        view._use_full_window_crosshairs = False
        view._zoom_press_ctrl = False
        view._select_band_origin = None
        view._select_band_active = False
        view._select_band_dragged = False
        view._press_changed_selection = False
        view._rotation_drag_active = False
        view._rotate_cursor = Qt.CursorShape.CrossCursor
        view._rotate_handle_item = None
        view._panning = False
        view._right_pan_active = False
        view._point_annotation_release_pending = False
        view._last_pan_point = None
        view._drag_plan_item_uid = None
        view._drag_handle_index = -2
        view._drag_orig_position = []
        view._drag_handle_corner_count = 0
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._keyboard_move_dirty = False
        view._selected_uids = set({"t1"} if selected_uids is None else selected_uids)
        view.plan_item_selection_changed = _FakeSignal()
        view.takeoff_selection_changed = _FakeSignal()
        view._handle_infos = []
        view._selection_items = []
        view._current_takeoffs = {
            "t1": Takeoff(
                uid="t1",
                position=[0.0, 0.0, 10.0, 0.0],
                condition_uid="c",
            ),
            "t2": Takeoff(
                uid="t2",
                position=[20.0, 0.0, 30.0, 0.0],
                condition_uid="c",
            ),
        }
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_conditions = {}
        view._scene = None
        view._uid_to_items = {"t1": [FakeItem(1.0, 2.0)], "t2": [FakeItem(3.0, 4.0)]}
        view._takeoff_items = []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        view.find_takeoff_at = lambda _scene_pos: "t1"
        view.find_takeoffs_at = lambda _scene_pos: ["t1"]
        view._flush_dirty_positions = lambda: None
        view.update_selection_visuals = lambda *args, **_call_options: None
        view._rubber_band_origin = None
        view._rubber_band = None
        view._update_cursor = lambda *args, **_call_options: None
        view._snap_increments = 1.0
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        return view

    def _make_transform_view(self, selected_uids):
        view = self._make_view(selected_uids)
        view._scene_builder = FakeSceneBuilder()
        view._linear_geom = LinearGeometry()
        view._current_conditions = {
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                thickness=4.0,
            ),
            "count": Condition(
                uid="count",
                condition_type=Condition.TYPE_COUNT,
                shape=shapes.TRIANGLE,
                width=20.0,
                depth=12.0,
                display_size=150.0,
            ),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "attachment": Condition(
                uid="attachment",
                condition_type=Condition.TYPE_ATTACHMENT,
                shape=shapes.TRIANGLE,
                width=14.0,
                depth=8.0,
            ),
        }
        view._current_takeoffs = {
            "area": Takeoff(
                uid="area",
                condition_uid="area",
                position=[-2.0, 1.0, 11.0, 0.0, 9.0, 12.0, 1.0, 8.0],
            ),
            "linear": Takeoff(
                uid="linear",
                condition_uid="linear",
                position=[12.0, 2.0, 22.0, 2.0],
            ),
            "count": Takeoff(
                uid="count",
                condition_uid="count",
                position=[30.0, 5.0],
                rotation=math.radians(32.0),
            ),
            "attachment": Takeoff(
                uid="attachment",
                condition_uid="attachment",
                position=[45.0, 5.0],
                rotation=math.radians(25.0),
            ),
        }
        view._rotation_before_edit = {}
        view._dirty_rotations = {}
        view.flushed_transform_groups = []

        def flush_rotation_group():
            position_changes = [
                (
                    uid,
                    list(view._position_before_edit[uid]),
                    list(new_position),
                )
                for uid, new_position in view._dirty_positions.items()
            ]
            rotation_changes = [
                (uid, view._rotation_before_edit[uid], new_rotation)
                for uid, new_rotation in view._dirty_rotations.items()
            ]
            view.flushed_transform_groups.append((position_changes, rotation_changes))
            view._position_before_edit.clear()
            view._dirty_positions.clear()
            view._rotation_before_edit.clear()
            view._dirty_rotations.clear()

        view._flush_rotation_group = flush_rotation_group
        return view

    @staticmethod
    def _minimum_rendered_dimensions(view):
        coordinate_system = view._scene_builder.get_coordinate_system()
        screen_units_per_ost = coordinate_system.ost_to_screen_pixels(1.0)
        return (
            MINIMUM_RENDERED_POINT_TAKEOFF_SIZE / screen_units_per_ost,
            MINIMUM_RENDERED_LINEAR_THICKNESS / screen_units_per_ost,
        )

    @staticmethod
    def _takeoff_vertices(view, uid):
        takeoff = view._current_takeoffs[uid]
        minimum_point_dimension, minimum_linear_thickness = (
            CtrlDragTests._minimum_rendered_dimensions(view)
        )
        return compute_takeoff_footprint_vertices(
            takeoff,
            view._current_conditions[takeoff.condition_uid],
            view._linear_geom,
            minimum_point_dimension,
            minimum_linear_thickness,
        )

    def _assert_bounds_almost_equal(self, first, second):
        for first_value, second_value in zip(first, second):
            self.assertAlmostEqual(first_value, second_value, places=9)

    def _assert_vertices_almost_equal(self, first, second):
        normalized_first = sorted((round(x, 9), round(y, 9)) for x, y in first)
        normalized_second = sorted((round(x, 9), round(y, 9)) for x, y in second)
        self.assertEqual(normalized_first, normalized_second)

    def _assert_quarter_turn_bounds(self, before, after):
        before_center = (
            (before[0] + before[2]) / 2.0,
            (before[1] + before[3]) / 2.0,
        )
        after_center = (
            (after[0] + after[2]) / 2.0,
            (after[1] + after[3]) / 2.0,
        )
        self._assert_bounds_almost_equal(before_center, after_center)
        self.assertAlmostEqual(before[2] - before[0], after[3] - after[1], places=9)
        self.assertAlmostEqual(before[3] - before[1], after[2] - after[0], places=9)

    @staticmethod
    def _rendered_takeoff_selection_bounds(view, uids):
        coordinate_system = view._scene_builder.get_coordinate_system()
        renderer = TakeoffRenderer(
            IdentityCoordinateSystem(coordinate_system.ost_to_screen_pixels(1.0)),
            FakeTakeoffRendererColorService(),
        )
        takeoffs = [view._current_takeoffs[uid] for uid in uids]
        color_map = {
            takeoff.condition_uid: ColorWithOpacity("#123456", 1.0)
            for takeoff in takeoffs
        }
        bounds = None
        rendered = renderer.create_all_path_items(
            takeoffs,
            view._current_conditions,
            color_map,
            inactive_object_color="#808080",
        )
        for _uid, takeoff_items in rendered:
            items = (
                takeoff_items if isinstance(takeoff_items, list) else [takeoff_items]
            )
            for item in items:
                if not isinstance(item, QGraphicsPathItem):
                    continue
                item_bounds = item.path().boundingRect()
                bounds = item_bounds if bounds is None else bounds.united(item_bounds)
        return (
            bounds.left(),
            bounds.top(),
            bounds.right(),
            bounds.bottom(),
        )

    def test_each_takeoff_type_flips_about_its_complete_footprint(self):
        for uid in ("linear", "count", "area", "attachment"):
            for horizontal in (True, False):
                with self.subTest(uid=uid, horizontal=horizontal):
                    view = self._make_transform_view({uid})
                    before = self._rendered_takeoff_selection_bounds(view, {uid})
                    view.flip_selected_takeoffs(horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, {uid})
                    self._assert_bounds_almost_equal(before, after)

    def test_every_pairwise_type_flip_preserves_group_bounds(self):
        takeoff_types = ("linear", "count", "area", "attachment")
        for selected in combinations(takeoff_types, 2):
            for horizontal in (True, False):
                with self.subTest(selected=selected, horizontal=horizontal):
                    view = self._make_transform_view(set(selected))
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    view.flip_selected_takeoffs(horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_bounds_almost_equal(before, after)

    def test_full_mixed_flip_reflects_every_authoritative_footprint_once(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                left, top, right, bottom = self._rendered_takeoff_selection_bounds(
                    view, selected
                )
                pivot_x = (left + right) / 2.0
                pivot_y = (top + bottom) / 2.0
                before = {uid: self._takeoff_vertices(view, uid) for uid in selected}
                view.flip_selected_takeoffs(horizontal)
                for uid in selected:
                    expected = [
                        (
                            2.0 * pivot_x - x if horizontal else x,
                            y if horizontal else 2.0 * pivot_y - y,
                        )
                        for x, y in before[uid]
                    ]
                    self._assert_vertices_almost_equal(
                        expected,
                        self._takeoff_vertices(view, uid),
                    )

    def test_full_mixed_flip_keeps_rendered_selection_in_place(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.flip_selected_takeoffs(horizontal)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_bounds_almost_equal(before, after)

    def test_rotated_count_size_matrix_cannot_shift_flip_pivot(self):
        for rotation_degrees in (0.0, 27.0, 90.0, 143.0):
            for display_size in (10.0, 25.0, 50.0, 100.0, 175.0):
                for horizontal in (True, False):
                    with self.subTest(
                        rotation=rotation_degrees,
                        display_size=display_size,
                        horizontal=horizontal,
                    ):
                        view = self._make_transform_view({"area", "count"})
                        view._current_takeoffs["count"].rotation = math.radians(
                            rotation_degrees
                        )
                        view._current_conditions["count"].display_size = display_size
                        rendered_before = self._rendered_takeoff_selection_bounds(
                            view, {"area", "count"}
                        )
                        view.flip_selected_takeoffs(horizontal)
                        rendered_after = self._rendered_takeoff_selection_bounds(
                            view, {"area", "count"}
                        )
                        self._assert_bounds_almost_equal(
                            rendered_before,
                            rendered_after,
                        )

    def test_curved_linear_and_count_flip_preserves_group_bounds(self):
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                selected = {"linear", "count"}
                view = self._make_transform_view(selected)
                view._current_takeoffs["linear"].position = [
                    0.0,
                    0.0,
                    20.0,
                    0.0,
                    10.0,
                    8.0,
                    0.0,
                ]
                view._current_takeoffs["linear"].curve = Takeoff.CURVE_ENABLED
                view._current_conditions["linear"].thickness = 0.25
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.flip_selected_takeoffs(horizontal)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_bounds_almost_equal(before, after)

    def test_curved_linear_flip_reflects_signed_offset_footprint(self):
        selected = {"linear", "count"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                linear = view._current_takeoffs["linear"]
                linear.position = [0.0, 0.0, 20.0, 0.0, 10.0, 8.0, -8.0]
                linear.curve = Takeoff.CURVE_ENABLED
                left, top, right, bottom = self._rendered_takeoff_selection_bounds(
                    view, selected
                )
                pivot_x = (left + right) / 2.0
                pivot_y = (top + bottom) / 2.0
                before = self._takeoff_vertices(view, "linear")
                view.flip_selected_takeoffs(horizontal)
                expected = [
                    (
                        2.0 * pivot_x - x if horizontal else x,
                        y if horizontal else 2.0 * pivot_y - y,
                    )
                    for x, y in before
                ]
                self._assert_vertices_almost_equal(
                    expected,
                    self._takeoff_vertices(view, "linear"),
                )
                self.assertEqual(linear.position[6], 8.0)

    def test_page_scale_and_calibration_preserve_small_count_rendered_bounds(self):
        selected = {"area", "count"}
        for screen_units_per_ost in (0.25, 1.0, 4.0):
            for horizontal in (True, False):
                with self.subTest(
                    screen_units_per_ost=screen_units_per_ost,
                    horizontal=horizontal,
                ):
                    view = self._make_transform_view(selected)
                    view._scene_builder.cs.ost_to_screen_pixels = (
                        lambda value: float(value) * screen_units_per_ost
                    )
                    view._current_conditions["count"].display_size = 10.0
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    view.flip_selected_takeoffs(horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_bounds_almost_equal(before, after)

    def test_page_scale_preserves_thin_linear_rendered_bounds(self):
        selected = {"area", "linear"}
        for screen_units_per_ost in (0.25, 1.0, 4.0):
            for horizontal in (True, False):
                with self.subTest(
                    screen_units_per_ost=screen_units_per_ost,
                    horizontal=horizontal,
                ):
                    view = self._make_transform_view(selected)
                    view._scene_builder.cs.ost_to_screen_pixels = (
                        lambda value: float(value) * screen_units_per_ost
                    )
                    view._current_conditions["linear"].thickness = 0.1
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    view.flip_selected_takeoffs(horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_bounds_almost_equal(before, after)

    def test_mixed_flip_with_multiple_objects_per_type_preserves_bounds(self):
        base_selection = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                selected = set(base_selection)
                view = self._make_transform_view(selected)
                for source_uid in base_selection:
                    duplicate_uid = f"{source_uid}-2"
                    source = view._current_takeoffs[source_uid]
                    duplicate_position = list(source.position)
                    for index in range(0, len(duplicate_position), 2):
                        duplicate_position[index] += 70.0
                        duplicate_position[index + 1] += 30.0
                    view._current_takeoffs[duplicate_uid] = Takeoff(
                        uid=duplicate_uid,
                        condition_uid=source.condition_uid,
                        position=duplicate_position,
                        rotation=source.rotation,
                    )
                    selected.add(duplicate_uid)
                view._selected_uids = set(selected)
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.flip_selected_takeoffs(horizontal)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_bounds_almost_equal(before, after)

    def test_double_mixed_flip_restores_authoritative_geometry_and_rotation(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                original_positions = {
                    uid: list(takeoff.position)
                    for uid, takeoff in view._current_takeoffs.items()
                }
                original_rotations = {
                    uid: takeoff.rotation
                    for uid, takeoff in view._current_takeoffs.items()
                }
                view.flip_selected_takeoffs(horizontal)
                view.flip_selected_takeoffs(horizontal)
                for uid, takeoff in view._current_takeoffs.items():
                    for original, restored in zip(
                        original_positions[uid], takeoff.position
                    ):
                        self.assertAlmostEqual(original, restored, places=9)
                    self.assertAlmostEqual(
                        original_rotations[uid], takeoff.rotation, places=9
                    )
                self.assertEqual(len(view.flushed_transform_groups), 2)

    def test_each_takeoff_type_rotates_about_its_complete_visible_footprint(self):
        for uid in ("linear", "count", "area", "attachment"):
            for degrees in (-90.0, 90.0):
                with self.subTest(uid=uid, degrees=degrees):
                    view = self._make_transform_view({uid})
                    original_rotation = view._current_takeoffs[uid].rotation
                    before = self._rendered_takeoff_selection_bounds(view, {uid})
                    view.rotate_selected_takeoffs(degrees)
                    after = self._rendered_takeoff_selection_bounds(view, {uid})
                    self._assert_quarter_turn_bounds(before, after)
                    condition = view._current_conditions[uid]
                    if condition.is_count or condition.is_attachment:
                        self.assertAlmostEqual(
                            view._current_takeoffs[uid].rotation,
                            original_rotation + math.radians(degrees),
                        )

    def test_every_pairwise_type_rotation_keeps_one_visible_group_center(self):
        takeoff_types = ("linear", "count", "area", "attachment")
        for selected in combinations(takeoff_types, 2):
            for degrees in (-90.0, 90.0):
                with self.subTest(selected=selected, degrees=degrees):
                    view = self._make_transform_view(set(selected))
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    view.rotate_selected_takeoffs(degrees)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_quarter_turn_bounds(before, after)

    def test_full_mixed_rotation_uses_complete_visible_group_pivot(self):
        selected = {"linear", "count", "area", "attachment"}
        for degrees in (-90.0, 90.0):
            with self.subTest(degrees=degrees):
                view = self._make_transform_view(selected)
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.rotate_selected_takeoffs(degrees)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_quarter_turn_bounds(before, after)
                rotation_delta = math.radians(degrees)
                self.assertAlmostEqual(
                    view._current_takeoffs["count"].rotation,
                    math.radians(32.0) + rotation_delta,
                )
                self.assertAlmostEqual(
                    view._current_takeoffs["attachment"].rotation,
                    math.radians(25.0) + rotation_delta,
                )

    def test_point_shape_rotation_matrix_keeps_visible_group_center(self):
        shape_dimensions = (
            (shapes.SQUARE, 20.0, 8.0),
            (shapes.RECTANGLE, 20.0, 8.0),
            (shapes.TRIANGLE, 20.0, 8.0),
            (shapes.ELLIPSE, 20.0, 8.0),
        )
        for point_uid in ("count", "attachment"):
            display_sizes = (10.0, 75.0, 175.0) if point_uid == "count" else (100.0,)
            for shape_id, width, depth in shape_dimensions:
                for display_size in display_sizes:
                    for screen_units_per_ost in (0.25, 1.0, 4.0):
                        for initial_degrees in (0.0, 27.0, 143.0):
                            for degrees in (-90.0, 90.0):
                                with self.subTest(
                                    point_uid=point_uid,
                                    shape_id=shape_id,
                                    display_size=display_size,
                                    screen_units_per_ost=screen_units_per_ost,
                                    initial_degrees=initial_degrees,
                                    degrees=degrees,
                                ):
                                    selected = {"area", point_uid}
                                    view = self._make_transform_view(selected)
                                    view._scene_builder.cs.ost_to_screen_pixels = (
                                        lambda value: float(value)
                                        * screen_units_per_ost
                                    )
                                    condition = view._current_conditions[point_uid]
                                    condition.shape = shape_id
                                    condition.width = width
                                    condition.depth = depth
                                    condition.display_size = display_size
                                    point = view._current_takeoffs[point_uid]
                                    point.rotation = math.radians(initial_degrees)
                                    before = self._rendered_takeoff_selection_bounds(
                                        view, selected
                                    )
                                    view.rotate_selected_takeoffs(degrees)
                                    after = self._rendered_takeoff_selection_bounds(
                                        view, selected
                                    )
                                    self._assert_quarter_turn_bounds(before, after)
                                    self.assertAlmostEqual(
                                        point.rotation,
                                        math.radians(initial_degrees + degrees),
                                    )

    def test_thin_straight_and_curved_linear_rotation_respects_page_scale(self):
        selected = {"area", "linear"}
        for curved in (False, True):
            for screen_units_per_ost in (0.25, 1.0, 4.0):
                for degrees in (-90.0, 90.0):
                    with self.subTest(
                        curved=curved,
                        screen_units_per_ost=screen_units_per_ost,
                        degrees=degrees,
                    ):
                        view = self._make_transform_view(selected)
                        view._scene_builder.cs.ost_to_screen_pixels = (
                            lambda value: float(value) * screen_units_per_ost
                        )
                        view._current_conditions["linear"].thickness = 0.1
                        if curved:
                            linear = view._current_takeoffs["linear"]
                            linear.position = [0.0, 0.0, 20.0, 0.0, 10.0, 8.0, 0.0]
                            linear.curve = Takeoff.CURVE_ENABLED
                        before = self._rendered_takeoff_selection_bounds(view, selected)
                        view.rotate_selected_takeoffs(degrees)
                        after = self._rendered_takeoff_selection_bounds(view, selected)
                        self._assert_quarter_turn_bounds(before, after)

    def test_left_then_right_restores_mixed_authoritative_geometry(self):
        selected = {"linear", "count", "area", "attachment"}
        view = self._make_transform_view(selected)
        original_positions = {
            uid: list(takeoff.position)
            for uid, takeoff in view._current_takeoffs.items()
        }
        original_rotations = {
            uid: takeoff.rotation for uid, takeoff in view._current_takeoffs.items()
        }
        view.rotate_selected_takeoffs(-90.0)
        view.rotate_selected_takeoffs(90.0)
        for uid, takeoff in view._current_takeoffs.items():
            self._assert_bounds_almost_equal(original_positions[uid], takeoff.position)
            self.assertAlmostEqual(original_rotations[uid], takeoff.rotation)

    def test_flip_then_rotate_uses_one_stable_canonical_group_pivot(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            for screen_units_per_ost in (0.25, 1.0, 4.0):
                with self.subTest(
                    horizontal=horizontal,
                    screen_units_per_ost=screen_units_per_ost,
                ):
                    view = self._make_transform_view(selected)
                    view._scene_builder.cs.ost_to_screen_pixels = (
                        lambda value: float(value) * screen_units_per_ost
                    )
                    view._current_conditions["linear"].thickness = 0.1
                    linear = view._current_takeoffs["linear"]
                    linear.position = [0.0, 0.0, 20.0, 0.0, 7.0, 9.0, -8.0]
                    linear.curve = Takeoff.CURVE_ENABLED
                    view._current_conditions["count"].shape = shapes.SQUARE
                    view._current_conditions["count"].display_size = 10.0
                    view._current_conditions["attachment"].shape = shapes.TRIANGLE
                    original_positions = {
                        uid: list(view._current_takeoffs[uid].position)
                        for uid in selected
                    }
                    original_rotations = {
                        uid: view._current_takeoffs[uid].rotation for uid in selected
                    }
                    original_bounds = self._rendered_takeoff_selection_bounds(
                        view, selected
                    )
                    original_center = (
                        (original_bounds[0] + original_bounds[2]) / 2.0,
                        (original_bounds[1] + original_bounds[3]) / 2.0,
                    )
                    view.flip_selected_takeoffs(horizontal)
                    flipped_bounds = self._rendered_takeoff_selection_bounds(
                        view, selected
                    )
                    self._assert_bounds_almost_equal(original_bounds, flipped_bounds)
                    view.rotate_selected_takeoffs(90.0)
                    rotated_bounds = self._rendered_takeoff_selection_bounds(
                        view, selected
                    )
                    rotated_center = (
                        (rotated_bounds[0] + rotated_bounds[2]) / 2.0,
                        (rotated_bounds[1] + rotated_bounds[3]) / 2.0,
                    )
                    self._assert_bounds_almost_equal(original_center, rotated_center)
                    view.rotate_selected_takeoffs(-90.0)
                    view.flip_selected_takeoffs(horizontal)
                    for uid in selected:
                        self._assert_bounds_almost_equal(
                            original_positions[uid],
                            view._current_takeoffs[uid].position,
                        )
                        self.assertAlmostEqual(
                            original_rotations[uid],
                            view._current_takeoffs[uid].rotation,
                            places=9,
                        )

    def test_four_quarter_turns_restore_mixed_visible_geometry(self):
        selected = {"linear", "count", "area", "attachment"}
        for degrees in (-90.0, 90.0):
            with self.subTest(degrees=degrees):
                view = self._make_transform_view(selected)
                original_positions = {
                    uid: list(takeoff.position)
                    for uid, takeoff in view._current_takeoffs.items()
                }
                original_vertices = {
                    uid: self._takeoff_vertices(view, uid) for uid in selected
                }
                original_rotations = {
                    uid: takeoff.rotation
                    for uid, takeoff in view._current_takeoffs.items()
                }
                for _turn in range(4):
                    view.rotate_selected_takeoffs(degrees)
                for uid, takeoff in view._current_takeoffs.items():
                    self._assert_bounds_almost_equal(
                        original_positions[uid], takeoff.position
                    )
                    self._assert_vertices_almost_equal(
                        original_vertices[uid], self._takeoff_vertices(view, uid)
                    )
                    rotation_delta = math.remainder(
                        takeoff.rotation - original_rotations[uid],
                        math.tau,
                    )
                    self.assertAlmostEqual(rotation_delta, 0.0)
                self.assertEqual(len(view.flushed_transform_groups), 4)

    def _make_linear_resize_gesture_view(
        self,
        *,
        scale_ratio=48.0,
        coordinate_view_scale=2.0,
        zoom=1.0,
        position=None,
        snap_increment=1.0,
    ):
        view = self._make_view({"t1"})
        view._advanced_mouse_controls_enabled = False
        view._drag_model_orig_position = None
        view._drag_position_before_edit_existed = False
        view._current_conditions = {
            "c": Condition(uid="c", condition_type=Condition.TYPE_LINEAR)
        }
        view._current_takeoffs["t1"].position = list(position or [0.0, 0.0, 10.0, 0.0])
        view._scene_builder = FakeSceneBuilder()
        coordinate_system = view._scene_builder.get_coordinate_system()
        coordinate_system.scale_ratio = float(scale_ratio)
        coordinate_system.view_scale = float(coordinate_view_scale)
        view._snap_increments = float(snap_increment)
        view.mapToScene = lambda point: QtCore.QPointF(
            point.x() / zoom,
            point.y() / zoom,
        )
        view.mapFromScene = lambda point: QtCore.QPoint(
            round(point.x() * zoom),
            round(point.y() * zoom),
        )
        view._current_page_transform = lambda: None
        view._snap_angle = lambda _ox, _oy, nx, ny: (nx, ny)
        view.find_text_annotation_at = lambda _scene_pos: None
        view.find_selected_movable_at = lambda _scene_pos: "t1"
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: "t1"
        view.find_takeoffs_at = lambda _scene_pos: ["t1"]
        handles = [
            SimpleNamespace(item=FakeItem()),
            SimpleNamespace(item=FakeItem()),
        ]
        view._handle_infos = handles
        view._is_handle_info_at_viewport_pos = lambda info, _pos: info is handles[1]
        view.resize_previews = []
        view.update_drag_handle_positions = (
            lambda new_pos, uid, *_args: view.resize_previews.append(
                (uid, list(new_pos))
            )
        )
        view.positions_flushed = FakeSignal()

        def flush_dirty_positions():
            if not view._dirty_positions and not view._dirty_ann_positions:
                return
            previous = dict(view._position_before_edit)
            takeoff_changes = [
                (uid, previous.get(uid, []), list(new_pos))
                for uid, new_pos in view._dirty_positions.items()
            ]
            annotation_changes = [
                (uid, annotation_type, previous.get(uid, []), list(new_pos))
                for uid, (annotation_type, new_pos) in view._dirty_ann_positions.items()
            ]
            view._dirty_positions.clear()
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()
            view.positions_flushed.emit(takeoff_changes, annotation_changes)

        view._flush_dirty_positions = flush_dirty_positions
        return view

    @staticmethod
    def _perform_linear_resize_gesture(view, points):
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        drag_latches = []
        for x, y in points:
            view.mouseMoveEvent(FakeMouseEvent(x=x, y=y))
            drag_latches.append(view._select_band_dragged)
        release_x, release_y = points[-1] if points else (0, 0)
        release = FakeMouseEvent(
            x=release_x,
            y=release_y,
            buttons=Qt.MouseButton.NoButton,
        )
        view.mouseReleaseEvent(release)
        return drag_latches, release

    def test_three_pixel_snapped_linear_resize_commits_geometry_change(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        drag_latches, release = self._perform_linear_resize_gesture(view, [(3, 0)])
        expected = [0.0, 0.0, 11.0, 0.0]
        self.assertEqual(drag_latches, [False])
        self.assertTrue(release.accepted)
        self.assertEqual(view._current_takeoffs["t1"].position, expected)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("t1", [0.0, 0.0, 10.0, 0.0], expected)], [])],
        )

    def test_exactly_five_pixel_snapped_linear_resize_commits_geometry_change(self):
        view = self._make_linear_resize_gesture_view(zoom=5.0 / 3.0)
        drag_latches, _release = self._perform_linear_resize_gesture(view, [(5, 0)])
        self.assertEqual(drag_latches, [False])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 11.0, 0.0],
        )
        self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_six_pixel_snapped_linear_resize_continues_to_commit(self):
        view = self._make_linear_resize_gesture_view(zoom=2.0)
        drag_latches, _release = self._perform_linear_resize_gesture(view, [(6, 0)])
        self.assertEqual(drag_latches, [True])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 11.0, 0.0],
        )
        self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_linear_resize_overshoot_matches_direct_final_endpoint(self):
        direct = self._make_linear_resize_gesture_view(zoom=1.0)
        overshoot = self._make_linear_resize_gesture_view(zoom=1.0)
        direct_latches, _release = self._perform_linear_resize_gesture(direct, [(3, 0)])
        overshoot_latches, _release = self._perform_linear_resize_gesture(
            overshoot, [(6, 0), (3, 0)]
        )
        self.assertEqual(direct_latches, [False])
        self.assertEqual(overshoot_latches, [True, True])
        self.assertEqual(
            direct._current_takeoffs["t1"].position,
            overshoot._current_takeoffs["t1"].position,
        )
        self.assertEqual(
            direct.positions_flushed.emitted,
            overshoot.positions_flushed.emitted,
        )

    def test_resize_returning_to_original_geometry_reverts_without_persistence(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        drag_latches, release = self._perform_linear_resize_gesture(
            view, [(6, 0), (0, 0)]
        )
        self.assertEqual(drag_latches, [True, True])
        self.assertTrue(release.accepted)
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_resize_handle_click_without_geometry_change_remains_a_click(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        drag_latches, release = self._perform_linear_resize_gesture(view, [])
        self.assertEqual(drag_latches, [])
        self.assertTrue(release.accepted)
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_small_body_drag_still_uses_existing_pixel_threshold(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        view._is_handle_info_at_viewport_pos = lambda _info, _pos: False
        drag_latches, _release = self._perform_linear_resize_gesture(view, [(3, 0)])
        self.assertEqual(drag_latches, [False])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_angled_resize_is_consistent_across_page_scale_and_zoom(self):
        configurations = (
            {"scale_ratio": 48.0, "zoom": 5.0 / 3.0},
            {"scale_ratio": 96.0, "zoom": 10.0 / 3.0},
        )
        results = []
        for configuration in configurations:
            with self.subTest(**configuration):
                view = self._make_linear_resize_gesture_view(
                    **configuration,
                    position=[0.0, 0.0, 6.0, 8.0],
                    snap_increment=0.1,
                )
                drag_latches, _release = self._perform_linear_resize_gesture(
                    view, [(3, 4)]
                )
                self.assertEqual(drag_latches, [False])
                self.assertEqual(len(view.positions_flushed.emitted), 1)
                result = view._current_takeoffs["t1"].position
                self.assertAlmostEqual(result[2], 6.6)
                self.assertAlmostEqual(result[3], 8.8)
                results.append(result)
        self.assertEqual(results[0], results[1])

    def _make_area_control_point_view(self, selected_uids=None, include_hole=False):
        view = self._make_view(set() if selected_uids is None else selected_uids)
        view._scene = QGraphicsScene()
        view._scene_builder = FakeSceneBuilder()
        view._annotation_only_selection = False
        view._hidden_layer_uids = set()
        view._current_page = None
        view._current_conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            ),
        }
        view._current_takeoffs = {
            "area1": Takeoff(
                uid="area1",
                condition_uid="area",
                page_uid="page-1",
                position=list(AREA_CP_ORIGINAL_POSITION),
            ),
            "linear1": Takeoff(
                uid="linear1",
                condition_uid="linear",
                page_uid="page-1",
                position=[200.0, 0.0, 300.0, 0.0],
            ),
        }
        if include_hole:
            view._current_takeoffs["hole1"] = Takeoff(
                uid="hole1",
                condition_uid="area",
                page_uid="page-1",
                parent_uid="area1",
                position=list(AREA_CP_HOLE_ORIGINAL_POSITION),
            )
        area_path = QPainterPath()
        area_path.moveTo(0.0, 0.0)
        area_path.lineTo(100.0, 0.0)
        area_path.lineTo(100.0, 100.0)
        area_path.lineTo(0.0, 100.0)
        area_path.closeSubpath()
        area_item = QGraphicsPathItem(area_path)
        area_item.setData(0, "area1")
        area_item.setZValue(0.5)
        items_by_uid = {"area1": [area_item]}
        if include_hole:
            hole_path = QPainterPath()
            hole_path.moveTo(20.0, 20.0)
            hole_path.lineTo(40.0, 20.0)
            hole_path.lineTo(40.0, 40.0)
            hole_path.lineTo(20.0, 40.0)
            hole_path.closeSubpath()
            hole_item = QGraphicsPathItem(hole_path)
            hole_item.setData(0, "hole1")
            hole_item.setZValue(0.6)
            view._scene.addItem(hole_item)
            items_by_uid["hole1"] = [hole_item]
        linear_path = QPainterPath()
        linear_path.moveTo(200.0, 0.0)
        linear_path.lineTo(300.0, 0.0)
        linear_item = QGraphicsPathItem(linear_path)
        linear_item.setData(0, "linear1")
        linear_item.setZValue(0.5)
        view._scene.addItem(area_item)
        view._scene.addItem(linear_item)
        items_by_uid["linear1"] = [linear_item]
        view._uid_to_items = items_by_uid
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_page_transform = lambda: None
        view._pt_to_scene = lambda x, y: QtCore.QPointF(float(x), float(y))
        view._scene_pos_to_ost = lambda point: QtCore.QPointF(point)
        view.transform = lambda: QTransform()
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        del view.find_takeoff_at
        del view.find_takeoffs_at
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._ann_db_uid_map = {}
        view._refreshing_overlays = False
        view.positions_flushed = FakeSignal()
        view.rebuild_count = 0
        view.selection_update_count = 0
        view.snap_invalidations = 0

        def rebuild_current_overlays_from_model():
            view.rebuild_count += 1

        def update_selection_visuals(*_args, **_options):
            view.selection_update_count += 1

        def invalidate_snap_index():
            view.snap_invalidations += 1

        view._rebuild_current_overlays_from_model = rebuild_current_overlays_from_model
        view.update_selection_visuals = update_selection_visuals
        view._invalidate_snap_index = invalidate_snap_index

        def flush_dirty_positions():
            if view._refreshing_overlays:
                return
            if not view._dirty_positions and not view._dirty_ann_positions:
                return
            if view._dirty_positions:
                view._invalidate_snap_index()
            dirty = dict(view._dirty_positions)
            ann_dirty = dict(view._dirty_ann_positions)
            prev = dict(view._position_before_edit)
            view._dirty_positions.clear()
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()
            takeoff_changes = [
                (uid, prev.get(uid, []), pos) for uid, pos in dirty.items()
            ]
            ann_changes = [
                (view._ann_db_uid_map.get(uid, uid), ann_type, prev.get(uid, []), pos)
                for uid, (ann_type, pos) in ann_dirty.items()
            ]
            view.positions_flushed.emit(takeoff_changes, ann_changes)

        view._flush_dirty_positions = flush_dirty_positions
        view._add_common_context_submenus = lambda _menu: (0, None, None)
        view._add_context_clipboard_actions = lambda _menu: None
        view._add_context_page_actions = lambda _menu, **_options: None
        view._context_menu_command_trigger = None
        view._context_menu_action_state = None
        view._suppress_next_context_menu = False
        view.reset_ctrl_held = lambda: None
        return view

    def _make_annotation_control_point_view(self, annotation_type, selected_uids=None):
        view = self._make_area_control_point_view(set())
        uid = f"{annotation_type}1"
        position = [
            400.0,
            0.0,
            500.0,
            0.0,
            500.0,
            100.0,
            400.0,
            100.0,
        ]
        annotation = BidAnnotation(
            uid=uid,
            annotation_type=annotation_type,
            page_uid="page-1",
            position=list(position),
        )
        path = QPainterPath()
        path.moveTo(400.0, 0.0)
        path.lineTo(500.0, 0.0)
        path.lineTo(500.0, 100.0)
        path.lineTo(400.0, 100.0)
        path.closeSubpath()
        item = QGraphicsPathItem(path)
        item.setData(0, uid)
        item.setZValue(1.0)
        view._scene.addItem(item)
        view._current_annotations = {uid: annotation}
        view._uid_to_items[uid] = [item]
        view._selected_uids = {uid} if selected_uids is None else set(selected_uids)
        return view, annotation

    def _capture_context_menu(self, view, x, y, action_text=None):
        CapturingMenu.instances = []
        CapturingMenu.action_text_to_return = action_text
        with (
            patch.object(input_handler_module, "QMenu", CapturingMenu),
            patch.object(
                input_handler_module,
                "add_reassign_condition_submenu",
                return_value=None,
            ),
            patch.object(
                input_handler_module,
                "add_selected_annotation_style_actions",
                return_value=SimpleNamespace(color_action=None, width_actions={}),
            ),
        ):
            InputHandlerMixin.contextMenuEvent(view, FakeContextMenuEvent(x, y))
        self.assertTrue(CapturingMenu.instances)
        return [
            action.text()
            for action in CapturingMenu.instances[0].actions
            if isinstance(action, QAction)
        ]

    def test_area_control_point_target_returns_edge_near_boundary(self):
        view = self._make_area_control_point_view()
        target = view.polygon_control_point_target_at(QtCore.QPointF(50.0, 0.0))
        self.assertEqual(target.kind, "edge")
        self.assertEqual(target.plan_item_uid, "area1")
        self.assertEqual(target.edge_index, 0)
        self.assertEqual(target.insert_point, (50.0, 0.0))

    def test_area_control_point_target_ignores_fill_click(self):
        view = self._make_area_control_point_view()
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(50.0, 50.0))
        )

    def test_area_control_point_target_prefers_vertex_over_edge(self):
        view = self._make_area_control_point_view()
        target = view.polygon_control_point_target_at(QtCore.QPointF(0.0, 0.0))
        self.assertEqual(target.kind, "vertex")
        self.assertEqual(target.plan_item_uid, "area1")
        self.assertEqual(target.vertex_index, 0)

    def test_area_control_point_target_ignores_non_area_takeoffs(self):
        view = self._make_area_control_point_view()
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(250.0, 0.0))
        )

    def test_area_control_point_target_respects_selection_edit_gate(self):
        view = self._make_area_control_point_view()
        view._selection_enabled = False
        view._editing_enabled = False
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(50.0, 0.0))
        )
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="edge",
            edge_index=0,
            insert_point=(50.0, 0.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_area_control_point_target_supports_parent_with_child_holes(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = view.polygon_control_point_target_at(QtCore.QPointF(50.0, 0.0))
        self.assertEqual(target.kind, "edge")
        self.assertEqual(target.plan_item_uid, "area1")

    def test_hole_control_point_target_returns_edge_near_boundary(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = view.polygon_control_point_target_at(QtCore.QPointF(30.0, 20.0))
        self.assertEqual(target.kind, "edge")
        self.assertEqual(target.plan_item_uid, "hole1")
        self.assertEqual(target.edge_index, 0)
        self.assertEqual(target.insert_point, (30.0, 20.0))

    def test_hole_control_point_target_prefers_vertex_over_edge(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = view.polygon_control_point_target_at(QtCore.QPointF(20.0, 20.0))
        self.assertEqual(target.kind, "vertex")
        self.assertEqual(target.plan_item_uid, "hole1")
        self.assertEqual(target.vertex_index, 0)

    def test_hole_control_point_target_ignores_fill_click(self):
        view = self._make_area_control_point_view(include_hole=True)
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(30.0, 30.0))
        )

    def test_hole_control_point_target_rejects_missing_parent(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["hole1"].parent_uid = "missing-parent"
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(30.0, 20.0))
        )

    def test_hole_control_point_target_rejects_non_area_parent(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["parent-linear"] = Takeoff(
            uid="parent-linear",
            condition_uid="linear",
            page_uid="page-1",
            position=[200.0, 0.0, 300.0, 0.0],
        )
        view._current_takeoffs["hole1"].parent_uid = "parent-linear"
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(30.0, 20.0))
        )
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=0,
            insert_point=(30.0, 20.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_add_area_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="edge",
            edge_index=0,
            insert_point=(50.0, 0.0),
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_ADDED_POSITION)
        self.assertEqual(view._current_takeoffs["area1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )
        self.assertEqual(view.snap_invalidations, 1)
        self.assertEqual(view.rebuild_count, 1)

    def test_subtract_area_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_SUBTRACTED_SECOND_VERTEX_POSITION)
        self.assertEqual(view._current_takeoffs["area1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )

    def test_subtract_area_control_point_rejects_triangle(self):
        view = self._make_area_control_point_view()
        view._current_takeoffs["area1"].position = [0.0, 0.0, 10.0, 0.0, 0.0, 10.0]
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_area_control_point_rejects_invalid_polygon_result(self):
        view = self._make_area_control_point_view()
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="edge",
            edge_index=0,
            insert_point=(50.0, 0.0),
        )
        with patch.object(input_handler_module, "polygon_is_valid", return_value=False):
            self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_add_hole_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view(include_hole=True)
        old_pos = list(view._current_takeoffs["hole1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=0,
            insert_point=(30.0, 20.0),
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_HOLE_ADDED_POSITION)
        self.assertEqual(view._current_takeoffs["hole1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("hole1", old_pos, new_pos)], [])],
        )

    def test_subtract_hole_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view(include_hole=True)
        old_pos = list(view._current_takeoffs["hole1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_HOLE_SUBTRACTED_SECOND_VERTEX_POSITION)
        self.assertEqual(view._current_takeoffs["hole1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("hole1", old_pos, new_pos)], [])],
        )

    def test_subtract_hole_control_point_rejects_triangle(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["hole1"].position = [20.0, 20.0, 40.0, 20.0, 20.0, 40.0]
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_hole_control_point_rejects_invalid_polygon_result(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=0,
            insert_point=(30.0, 20.0),
        )
        with patch.object(input_handler_module, "polygon_is_valid", return_value=False):
            self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_hole_control_point_rejects_position_outside_parent(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=1,
            insert_point=(150.0, 30.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_hole_control_point_rejects_sibling_overlap(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["hole2"] = Takeoff(
            uid="hole2",
            condition_uid="area",
            page_uid="page-1",
            parent_uid="area1",
            position=[45.0, 20.0, 65.0, 20.0, 65.0, 40.0, 45.0, 40.0],
        )
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=1,
            insert_point=(55.0, 30.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_context_menu_shows_add_control_point_only_for_edge_target(self):
        view = self._make_area_control_point_view()
        texts = self._capture_context_menu(view, 50.0, 0.0)
        self.assertIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_context_menu_shows_subtract_control_point_only_for_vertex_target(self):
        view = self._make_area_control_point_view()
        texts = self._capture_context_menu(view, 0.0, 0.0)
        self.assertIn("Subtract Control Point", texts)
        self.assertNotIn("Add Control Point", texts)

    def test_context_menu_shows_add_control_point_for_hole_edge_target(self):
        view = self._make_area_control_point_view(include_hole=True)
        texts = self._capture_context_menu(view, 30.0, 20.0)
        self.assertIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_context_menu_shows_subtract_control_point_for_hole_vertex_target(self):
        view = self._make_area_control_point_view(include_hole=True)
        texts = self._capture_context_menu(view, 20.0, 20.0)
        self.assertIn("Subtract Control Point", texts)
        self.assertNotIn("Add Control Point", texts)

    def test_context_menu_uses_actual_hit_not_stale_selected_area(self):
        view = self._make_area_control_point_view({"area1"})
        texts = self._capture_context_menu(view, 50.0, 50.0)
        self.assertNotIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_context_menu_uses_actual_hole_hit_not_parent_selection(self):
        view = self._make_area_control_point_view({"area1"}, include_hole=True)
        self._capture_context_menu(view, 30.0, 20.0, action_text="Add Control Point")
        self.assertEqual(
            view._current_takeoffs["hole1"].position, AREA_CP_HOLE_ADDED_POSITION
        )
        self.assertEqual(
            view._current_takeoffs["area1"].position, AREA_CP_ORIGINAL_POSITION
        )

    def test_context_menu_add_control_point_uses_existing_flush_path(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        self._capture_context_menu(view, 50.0, 0.0, action_text="Add Control Point")
        new_pos = list(AREA_CP_ADDED_POSITION)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )

    def test_context_menu_subtract_control_point_uses_existing_flush_path(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        self._capture_context_menu(view, 0.0, 0.0, action_text="Subtract Control Point")
        new_pos = list(AREA_CP_SUBTRACTED_FIRST_VERTEX_POSITION)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )

    def test_polygon_and_cloud_annotations_expose_existing_control_point_actions(self):
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                view, annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                add_texts = self._capture_context_menu(view, 450.0, 0.0)
                subtract_texts = self._capture_context_menu(view, 400.0, 0.0)
                self.assertIn("Add Control Point", add_texts)
                self.assertNotIn("Subtract Control Point", add_texts)
                self.assertIn("Subtract Control Point", subtract_texts)
                self.assertNotIn("Add Control Point", subtract_texts)
                self.assertEqual(view._selected_uids, {annotation.uid})

    def test_polygon_and_cloud_add_control_point_use_annotation_flush_path(self):
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                view, annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                old_pos = list(annotation.position)
                self._capture_context_menu(
                    view, 450.0, 0.0, action_text="Add Control Point"
                )
                new_pos = [
                    400.0,
                    0.0,
                    450.0,
                    0.0,
                    500.0,
                    0.0,
                    500.0,
                    100.0,
                    400.0,
                    100.0,
                ]
                self.assertEqual(annotation.position, new_pos)
                self.assertEqual(
                    view.positions_flushed.emitted,
                    [([], [(annotation.uid, annotation_type, old_pos, new_pos)])],
                )
                self.assertEqual(view.rebuild_count, 1)
                self.assertEqual(view.selection_update_count, 1)
                self.assertEqual(view._selected_uids, {annotation.uid})

    def test_polygon_and_cloud_subtract_control_point_enforce_minimum(self):
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                view, annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                old_pos = list(annotation.position)
                target = PolygonControlPointTarget(
                    plan_item_uid=annotation.uid,
                    kind="vertex",
                    vertex_index=0,
                )
                self.assertTrue(view._apply_polygon_control_point_target(target))
                triangle = [500.0, 0.0, 500.0, 100.0, 400.0, 100.0]
                self.assertEqual(annotation.position, triangle)
                self.assertEqual(
                    view.positions_flushed.emitted,
                    [([], [(annotation.uid, annotation_type, old_pos, triangle)])],
                )
                self.assertFalse(view._apply_polygon_control_point_target(target))
                self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_non_polygon_annotations_do_not_expose_control_point_actions(self):
        for annotation_type in ("text", "dimension", "line", "rect", "oval"):
            with self.subTest(annotation_type=annotation_type):
                view, _annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                self.assertIsNone(
                    view.polygon_control_point_target_at(QtCore.QPointF(450.0, 0.0))
                )
                texts = self._capture_context_menu(view, 450.0, 0.0)
                self.assertNotIn("Add Control Point", texts)
                self.assertNotIn("Subtract Control Point", texts)

    def test_polygon_control_points_respect_visibility_and_editability(self):
        view, annotation = self._make_annotation_control_point_view(
            ANNOTATION_TYPE_POLYGON
        )
        annotation.visible = False
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(450.0, 0.0))
        )
        annotation.visible = True
        view._editing_enabled = False
        texts = self._capture_context_menu(view, 450.0, 0.0)
        self.assertNotIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_mixed_selection_does_not_expose_polygon_control_point_actions(self):
        view, annotation = self._make_annotation_control_point_view(
            ANNOTATION_TYPE_POLYGON, {"area1", "polygon1"}
        )
        texts = self._capture_context_menu(view, 450.0, 50.0)
        self.assertNotIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)
        self.assertEqual(view._selected_uids, {"area1", annotation.uid})

    def _make_overlapping_text_cycle_view(self, selected_uid="t1"):
        view = self._make_view({selected_uid})
        view._current_annotations = {
            "a1": BidAnnotation(
                uid="a1",
                annotation_type="text",
                position=[10.0, 10.0, 40.0, 20.0],
                properties={"Text": "Note"},
            )
        }
        view._current_takeoffs = {
            "t1": SimpleNamespace(position=[0.0, 0.0, 10.0, 0.0], condition_uid="c"),
            "t2": SimpleNamespace(position=[20.0, 0.0, 30.0, 0.0], condition_uid="c"),
        }
        view._uid_to_items = {
            "t1": [FakeItem(1.0, 2.0)],
            "t2": [FakeItem(3.0, 4.0)],
            "a1": [FakeItem(5.0, 6.0)],
        }
        hits = ["a1", "t1", "t2"]
        view.find_text_annotation_at = lambda _scene_pos: "a1"
        view.find_takeoffs_at = lambda _scene_pos: list(hits)
        view.find_selected_movable_at = lambda _scene_pos: (
            selected_uid if selected_uid in view._selected_uids else None
        )
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: (
            hits[(hits.index(cycle_from_uid) + 1) % len(hits)]
            if cycle_from_uid in hits
            else hits[0]
        )
        view._on_selection_changed = lambda: None
        return view

    def test_text_takeoff_cycle_press_does_not_activate_text_toolbar(self):
        view = self._make_overlapping_text_cycle_view("t1")
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, [])
        self.assertEqual(view._selected_uids, {"t1"})
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view._selected_uids, {"t2"})
        self.assertEqual(view.selected_text_annotation_uids, [])

    def test_text_takeoff_cycle_back_to_text_shows_toolbar_after_commit(self):
        view = self._make_overlapping_text_cycle_view("t2")
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, [])
        self.assertEqual(view._selected_uids, {"t2"})
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view._selected_uids, {"a1"})
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])

    def test_plain_text_annotation_press_still_shows_toolbar(self):
        view = self._make_overlapping_text_cycle_view("t1")
        view._selected_uids = set()
        view.find_takeoffs_at = lambda _scene_pos: ["a1"]
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: "a1"
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])

    def _make_selected_text_annotation_view(self):
        view = self._make_view({"a1"})
        view._scene = QGraphicsScene()
        view._annotation_only_selection = False
        view._current_takeoffs = {}
        view._current_annotations = {
            "a1": BidAnnotation(
                uid="a1",
                annotation_type="text",
                position=[30.0, 20.0, 40.0, 20.0],
                properties={"Text": "Note"},
            )
        }
        item = QGraphicsTextItem("Note")
        item.setTextWidth(40.0)
        item.setPos(10.0, 10.0)
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._scene_builder = FakeSceneBuilder()
        view._current_page_transform = lambda: None
        view.transform = lambda: QTransform()
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        del view.find_takeoff_at
        del view.find_takeoffs_at
        return view, item

    def _make_hotlink_view(self, *, selected: bool):
        view = self._make_view({"h1"} if selected else set())
        view.hotlink_clicked = FakeSignal()
        view._current_takeoffs = {}
        view._current_annotations = {
            "h1": BidAnnotation(
                uid="h1",
                annotation_type="hotlink",
                position=[10.0, 10.0],
                properties={"BidPageViewUID": "view-1"},
            )
        }
        path = QPainterPath()
        path.addEllipse(QtCore.QPointF(10.0, 10.0), 5.0, 5.0)
        item = QGraphicsPathItem(path)
        item.setData(0, "h1")
        view._uid_to_items = {"h1": [item]}
        view._hotlink_items = [
            (
                item,
                HotlinkDto(
                    uid="h1",
                    bid_page_uid="page-1",
                    target_view_uid="view-1",
                    center_x=10.0,
                    center_y=10.0,
                    radius=5.0,
                ),
            )
        ]
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _scene_pos: []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        return view

    def _make_selected_path_takeoff_view(self):
        view = self._make_view({"t1"})
        view._scene = QGraphicsScene()
        view._annotation_only_selection = False
        view._current_conditions = {
            "c": Condition(
                uid="c",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            )
        }
        view._current_takeoffs = {
            "t1": Takeoff(
                uid="t1",
                condition_uid="c",
                position=[0.0, 0.0, 10.0, 0.0],
            )
        }
        path = QPainterPath()
        path.addRect(0.0, 0.0, 10.0, 10.0)
        item = QGraphicsPathItem(path)
        item.setData(0, "t1")
        view._scene.addItem(item)
        view._uid_to_items = {"t1": [item]}
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        view.transform = lambda: QTransform()
        del view.find_takeoff_at
        del view.find_takeoffs_at
        return view

    def test_ctrl_left_press_uses_zoom_even_if_cached_ctrl_state_is_false(self):
        view = self._make_view()
        event = FakeMouseEvent(Qt.KeyboardModifier.ControlModifier)
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertTrue(view._zoom_press_ctrl)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_named_view_click_away_commit_does_not_start_annotation_placement(self):
        view = self._make_view(set())
        view._cursor_mode = "annotation_place"
        view._editing_named_view_uid = "draft"
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _scene_pos: []
        event = FakeMouseEvent(x=40, y=50)
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view.annotation_place_presses, [])

    def _make_tool_change_commit_view(self):
        view = SimpleNamespace()
        view._editing_enabled = True
        view._cursor_mode = CURSOR_MODE_ANNOTATION_PLACE
        view._editing_named_view_uid = "draft"
        view._editing_text_annotation_uid = None
        view._annotation_place_type = ANNOTATION_TYPE_NAMED_VIEW
        view._current_bid_page_uid = "page-1"
        view.finished_inline_edits = []
        view.exited_annotation_place = 0
        view.entered_annotation_place = []
        view.cursor_mode_change_requested = _FakeSignal()

        def is_text_annotation_inline_edit_active():
            return (
                view._editing_named_view_uid is not None
                or view._editing_text_annotation_uid is not None
            )

        def finish_inline_edit(commit):
            view.finished_inline_edits.append(commit)
            view._editing_named_view_uid = None
            view._editing_text_annotation_uid = None
            view._annotation_place_type = ANNOTATION_TYPE_NAMED_VIEW

        def exit_annotation_place_mode():
            view.exited_annotation_place += 1
            view._annotation_place_type = None

        def enter_annotation_place_mode(annotation_type):
            view.entered_annotation_place.append(annotation_type)
            view._annotation_place_type = annotation_type
            return True

        view.is_text_annotation_inline_edit_active = (
            is_text_annotation_inline_edit_active
        )
        view._finish_active_inline_text_edit = finish_inline_edit
        view._finish_inline_text_edit_before_tool_change = lambda: (
            TakeoffPlanView._finish_inline_text_edit_before_tool_change(view)
        )
        view.cancel_overlay_move_mode = lambda restore_preview=True: None
        view._remove_rotate_handle = lambda: None
        view.finish_intelligent_paste_placement = lambda: None
        view._exit_annotation_place_mode = exit_annotation_place_mode
        view.enter_place_mode = lambda: True
        view._exit_place_mode = lambda: None
        view._clear_backout_state = lambda: None

        def apply_cursor_mode(mode):
            view._cursor_mode = mode

        view._apply_cursor_mode = apply_cursor_mode
        view._can_begin_annotation_placement = lambda: True
        view._enter_annotation_place_mode = enter_annotation_place_mode
        return view

    def test_cursor_mode_change_commits_named_view_edit_before_switching_tool(self):
        view = self._make_tool_change_commit_view()
        TakeoffPlanView.set_cursor_mode(view, CURSOR_MODE_SELECT)
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view._cursor_mode, CURSOR_MODE_SELECT)
        self.assertIsNone(view._annotation_place_type)
        self.assertEqual(
            view.cursor_mode_change_requested.emitted, [(CURSOR_MODE_SELECT,)]
        )

    def test_cursor_mode_change_stays_put_when_named_view_commit_keeps_edit_active(
        self,
    ):
        view = self._make_tool_change_commit_view()

        def finish_invalid_edit(commit):
            view.finished_inline_edits.append(commit)

        view._finish_active_inline_text_edit = finish_invalid_edit
        TakeoffPlanView.set_cursor_mode(view, CURSOR_MODE_SELECT)
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view._cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(view.exited_annotation_place, 0)
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_annotation_tool_change_commits_named_view_edit_before_switching_tool(self):
        view = self._make_tool_change_commit_view()
        self.assertTrue(
            TakeoffPlanView.activate_annotation_placement(
                view, ANNOTATION_TYPE_DIMENSION
            )
        )
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view.entered_annotation_place, [ANNOTATION_TYPE_DIMENSION])
        self.assertEqual(view._cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(view._annotation_place_type, ANNOTATION_TYPE_DIMENSION)
        self.assertEqual(
            view.cursor_mode_change_requested.emitted,
            [(CURSOR_MODE_ANNOTATION_PLACE,)],
        )

    def test_single_click_hotlink_does_not_select_it(self):
        view = self._make_hotlink_view(selected=False)
        view.find_takeoff_at = lambda _scene_pos: "h1"
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._selected_uids, set())
        self.assertIsNone(view._drag_plan_item_uid)

    def test_selected_hotlink_center_press_starts_drag(self):
        view = self._make_hotlink_view(selected=True)
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._drag_plan_item_uid, "h1")
        self.assertEqual(view._drag_orig_position, [10.0, 10.0])
        self.assertEqual(view._drag_handle_index, -1)

    def test_selected_item_click_clears_all_drag_tracking(self):
        view = self._make_hotlink_view(selected=True)
        view._scene = QGraphicsScene()
        view._scene.addItem(view._uid_to_items["h1"][0])
        view.mousePressEvent(FakeMouseEvent())
        view._drag_item_orig_paths = {1: QPainterPath()}
        view._drag_item_orig_text_states = {
            2: ("", -1.0, 0.0, QtCore.QPointF(), None, None)
        }
        view._drag_last_valid_new_pos = [10.0, 10.0]
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_item_orig_positions, {})
        self.assertEqual(view._drag_item_orig_paths, {})
        self.assertEqual(view._drag_item_orig_text_states, {})
        self.assertEqual(view._drag_uid_orig_items, {})
        self.assertEqual(view._drag_last_valid_new_pos, [])

    def test_selected_hotlink_drag_does_not_start_rubber_band(self):
        view = self._make_hotlink_view(selected=True)
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view._scene_builder = FakeSceneBuilder()
        view._snap_increments = 1.0
        view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        press = FakeMouseEvent(x=10, y=10)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        move = FakeMouseEvent(x=18, y=18)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(view._drag_plan_item_uid, "h1")
        self.assertFalse(view._select_band_active)
        self.assertIsNone(view._rubber_band_origin)
        self.assertEqual(view._uid_to_items["h1"][0].pos(), QtCore.QPointF(8.0, 8.0))

    def test_selected_hotlink_hover_uses_move_cursor(self):
        view = self._make_hotlink_view(selected=True)
        cursor = view._resolve_select_cursor(QtCore.QPoint(10, 10))
        self.assertEqual(cursor, Qt.CursorShape.SizeAllCursor)

    def test_unselected_hotlink_release_still_activates_hotlink(self):
        view = self._make_hotlink_view(selected=False)
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)
        self.assertEqual(view._selected_uids, set())

    def test_hotlink_placement_release_skips_hotlink_hit_testing(self):
        view = self._make_hotlink_view(selected=False)
        view._cursor_mode = "annotation_place"
        view._annotation_place_type = "hotlink"
        view.annotation_place_release_consumed = True
        calls = []
        view.find_hotlink_at = lambda _scene_pos: calls.append("hit-test") or None
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(calls, [])
        self.assertEqual(view.hotlink_clicked.emitted, [])

    def test_hotlink_placement_press_does_not_fall_through_to_hit_testing(self):
        view = self._make_hotlink_view(selected=False)
        view._cursor_mode = "annotation_place"
        view._annotation_place_type = "hotlink"
        press_calls = []
        hit_test_calls = []

        def _place_press(event):
            press_calls.append(event.pos())
            event.accept()
            return True

        view.handle_annotation_place_press = _place_press
        view.find_hotlink_at = lambda _scene_pos: hit_test_calls.append("hit") or None
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(len(press_calls), 1)
        self.assertEqual(hit_test_calls, [])
        self.assertEqual(view.hotlink_clicked.emitted, [])

    def test_real_hotlink_click_after_placement_release_still_opens(self):
        view = self._make_hotlink_view(selected=False)
        view._cursor_mode = "annotation_place"
        view._annotation_place_type = "hotlink"
        view.annotation_place_release_consumed = True
        placement_release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(placement_release)
        self.assertFalse(view.annotation_place_release_consumed)
        view._cursor_mode = "select"
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        click_release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(click_release)
        self.assertTrue(click_release.accepted)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)

    def test_repeated_hotlink_placements_do_not_navigate_but_later_clicks_do(self):
        view = self._make_hotlink_view(selected=False)
        hit_test_calls = []

        def _place_press(event):
            event.accept()
            view.annotation_place_release_consumed = True
            return True

        view.handle_annotation_place_press = _place_press
        view.find_hotlink_at = lambda _scene_pos: hit_test_calls.append("hit") or "h1"
        for expected_clicks in (1, 2):
            view._cursor_mode = "annotation_place"
            view._annotation_place_type = "hotlink"
            calls_before_placement = len(hit_test_calls)
            view.mousePressEvent(FakeMouseEvent())
            placement_release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
            view.mouseReleaseEvent(placement_release)
            self.assertTrue(placement_release.accepted)
            self.assertEqual(len(view.hotlink_clicked.emitted), expected_clicks - 1)
            self.assertEqual(len(hit_test_calls), calls_before_placement)
            view._cursor_mode = "select"
            calls_before_click = len(hit_test_calls)
            view.mousePressEvent(FakeMouseEvent())
            view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
            self.assertEqual(len(view.hotlink_clicked.emitted), expected_clicks)
            self.assertGreater(len(hit_test_calls), calls_before_click)

    def test_cancelled_hotlink_placement_release_allows_next_click(self):
        view = self._make_hotlink_view(selected=False)
        hotlink_items = list(view._hotlink_items)
        view.annotation_place_release_consumed = True
        view._hotlink_items = []
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertFalse(view.annotation_place_release_consumed)
        self.assertEqual(view.hotlink_clicked.emitted, [])
        view._hotlink_items = hotlink_items
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        second_release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(second_release)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)

    def test_named_view_draft_commit_ignores_reentrant_focus_commit(self):
        position = [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
        view = SimpleNamespace()
        view._finishing_named_view_rename = False
        view._editing_named_view_uid = "draft"
        view._draft_named_view_uid = "draft"
        view._named_view_name_validator = None
        view._editing_text_original = ""
        view._current_annotations = {
            "draft": BidAnnotation(
                uid="draft",
                annotation_type="namedview",
                page_uid="page-1",
                position=position,
                color="#008000",
                properties={"Text": ""},
            )
        }
        view.named_view_created = _FakeSignal()
        view.text_annotation_edit_mode_changed = _FakeSignal()
        view.removed_drafts = 0
        view.refreshed_labels = []

        class ReentrantItem:
            def toPlainText(self):
                return "Lobby"

            def setTextInteractionFlags(self, _flags):
                pass

            def clearFocus(self):
                TakeoffPlanView._finish_named_view_rename(view, True)

        view._editing_named_view_item = ReentrantItem()
        view._clear_inline_text_item_selection = lambda _item: None
        view._clear_inline_text_document = lambda: None

        def set_inline_text_edit_target(
            *, text_annotation_uid=None, named_view_uid=None, named_view_item=None
        ):
            del text_annotation_uid, named_view_uid, named_view_item
            view._editing_named_view_uid = None

        view._set_inline_text_edit_target = set_inline_text_edit_target
        view._update_cursor = lambda: None
        view._is_named_view_draft_uid = lambda uid: uid == view._draft_named_view_uid

        def clear_edit_state(item=None):
            if item is not None:
                item.setTextInteractionFlags(None)
                item.clearFocus()
            view._set_inline_text_edit_target()
            view.text_annotation_edit_mode_changed.emit(False)

        view._clear_inline_text_edit_state = clear_edit_state

        def remove_draft():
            view.removed_drafts += 1
            view._draft_named_view_uid = None

        view._remove_named_view_draft = remove_draft
        view._refresh_named_view_label_background = (
            lambda uid: view.refreshed_labels.append(uid)
        )
        TakeoffPlanView._finish_named_view_rename(view, True)
        self.assertEqual(view.removed_drafts, 1)
        self.assertEqual(
            view.named_view_created.emitted,
            [
                (
                    position,
                    "page-1",
                    {"Text": "Lobby", "Color": "#008000"},
                )
            ],
        )

    def test_duplicate_named_view_validation_ignores_modal_reentry(self):
        position = [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
        view = SimpleNamespace()
        view._finishing_named_view_rename = False
        view._editing_named_view_uid = "draft"
        view._draft_named_view_uid = "draft"
        view._editing_text_original = ""
        view._current_annotations = {
            "draft": BidAnnotation(
                uid="draft",
                annotation_type="namedview",
                page_uid="page-1",
                position=position,
                color="#008000",
                properties={"Text": ""},
            )
        }
        view.named_view_created = _FakeSignal()
        view.text_annotation_edit_mode_changed = _FakeSignal()
        view.refreshed_labels = []
        validator_calls = []

        class ReentrantInvalidItem:
            def __init__(self):
                self.text = "Lobby"
                self.focus_restores = 0

            def toPlainText(self):
                return self.text

            def setFocus(self, _reason):
                self.focus_restores += 1
                TakeoffPlanView._finish_named_view_rename(view, True)

            def setTextInteractionFlags(self, _flags):
                pass

            def clearFocus(self):
                pass

        item = ReentrantInvalidItem()

        def validate(name, exclude_uid=None):
            validator_calls.append((name, exclude_uid))
            if len(validator_calls) == 1:
                TakeoffPlanView._finish_named_view_rename(view, True)
            return False

        view._editing_named_view_item = item
        view._named_view_name_validator = validate
        view._clear_inline_text_item_selection = lambda _item: None
        view._clear_inline_text_document = lambda: None
        view._is_named_view_draft_uid = lambda uid: uid == view._draft_named_view_uid
        view._remove_named_view_draft = lambda: self.fail(
            "duplicate commit must keep the draft"
        )
        view._refresh_named_view_label_background = (
            lambda uid: view.refreshed_labels.append(uid)
        )
        TakeoffPlanView._finish_named_view_rename(view, True)
        self.assertEqual(validator_calls, [("Lobby", "draft")])
        self.assertEqual(item.focus_restores, 0)
        self.assertEqual(view.named_view_created.emitted, [])
        self.assertEqual(view._editing_named_view_uid, "draft")
        self.assertEqual(view._draft_named_view_uid, "draft")
        self.assertEqual(view.refreshed_labels, ["draft"])

    def test_selected_takeoff_hover_far_away_does_not_use_move_cursor(self):
        view = self._make_selected_path_takeoff_view()
        cursor = view._resolve_select_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(cursor, Qt.CursorShape.ArrowCursor)

    def test_selected_takeoff_hover_on_hit_area_uses_move_cursor(self):
        view = self._make_selected_path_takeoff_view()
        cursor = view._resolve_select_cursor(QtCore.QPoint(5, 5))
        self.assertEqual(cursor, Qt.CursorShape.SizeAllCursor)

    def test_modal_mutation_error_clears_stale_move_cursor_without_override(self):
        view = self._make_selected_path_takeoff_view()
        viewport = FakeCursorViewport()
        view.viewport = lambda: viewport
        view._last_mouse_vp_pos = QtCore.QPoint(5, 5)
        viewport.setCursor(Qt.CursorShape.SizeAllCursor)
        view.prepare_for_modal_mutation_error()
        self.assertIsNone(view._last_mouse_vp_pos)
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)
        self.assertIsNone(QApplication.overrideCursor())
        viewport.setCursor(Qt.CursorShape.SizeAllCursor)
        view._last_mouse_vp_pos = QtCore.QPoint(5, 5)
        view.prepare_for_modal_mutation_error()
        self.assertIsNone(view._last_mouse_vp_pos)
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)
        self.assertIsNone(QApplication.overrideCursor())

    def test_rotate_mode_uses_normal_hover_cursors_except_rotate_handle(self):
        view = self._make_selected_path_takeoff_view()
        view._cursor_mode = "rotate"
        view._rotate_handle_item = FakeItem(0.0, 0.0)
        self.assertEqual(
            view._resolve_cursor(QtCore.QPoint(100, 100)),
            Qt.CursorShape.ArrowCursor,
        )
        view._rotate_handle_item = FakeItem(100.0, 100.0)
        self.assertEqual(
            view._resolve_cursor(QtCore.QPoint(5, 5)),
            Qt.CursorShape.SizeAllCursor,
        )
        view._rotate_handle_item = FakeItem(5.0, 5.0)
        self.assertEqual(
            view._resolve_cursor(QtCore.QPoint(5, 5)),
            Qt.CursorShape.CrossCursor,
        )

    def test_rotate_mode_update_cursor_uses_live_viewport_pos_not_stale_hover(self):
        view = self._make_selected_path_takeoff_view()
        view._cursor_mode = "rotate"
        view._last_mouse_vp_pos = QtCore.QPoint(5, 5)
        view._rotate_handle_item = FakeItem(0.0, 0.0)
        viewport = FakeCursorViewport()
        view.viewport = lambda: viewport
        with patch.object(
            input_handler_module,
            "QCursor",
            SimpleNamespace(pos=lambda: QtCore.QPoint(100, 100)),
        ):
            InputHandlerMixin._update_cursor(view)
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def test_stale_move_drag_index_does_not_force_move_cursor_without_active_press(
        self,
    ):
        view = self._make_selected_path_takeoff_view()
        view._drag_handle_index = -1
        cursor = view._resolve_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(cursor, Qt.CursorShape.ArrowCursor)

    def test_pan_update_accepts_viewport_origin_as_previous_point(self):
        view = self._make_view()
        view._panning = True
        view._last_pan_point = QtCore.QPoint(0, 0)
        horizontal_values = []
        vertical_values = []
        horizontal = SimpleNamespace(
            value=lambda: 10,
            setValue=horizontal_values.append,
        )
        vertical = SimpleNamespace(
            value=lambda: 20,
            setValue=vertical_values.append,
        )
        view.horizontalScrollBar = lambda: horizontal
        view.verticalScrollBar = lambda: vertical
        user_changes = []
        view._mark_user_view_changed_during_load = lambda: user_changes.append(True)
        self.assertTrue(view._apply_pan_update(QtCore.QPoint(3, 4)))
        self.assertEqual(horizontal_values, [7])
        self.assertEqual(vertical_values, [16])
        self.assertEqual(view._last_pan_point, QtCore.QPoint(3, 4))
        self.assertEqual(user_changes, [True])

    def test_zero_vertical_wheel_delta_does_not_zoom(self):
        view = self._make_view()
        calls = []
        view._mark_user_view_changed_during_load = lambda: calls.append("changed")
        view._apply_zoom = lambda _factor: calls.append("zoom")
        view._publish_current_page_view_state = lambda: calls.append("publish")
        view._apply_wheel_zoom(FakeWheelEvent(), 0)
        self.assertEqual(calls, [])

    def test_ctrl_left_press_blocks_multi_select_drag_setup(self):
        view = self._make_view({"t1", "t2"})
        view.find_takeoff_at = lambda _scene_pos: self.fail(
            "Ctrl zoom press should not hit-test takeoff dragging"
        )
        event = FakeMouseEvent(Qt.KeyboardModifier.ControlModifier)
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertTrue(view._zoom_press_ctrl)
        self.assertEqual(view._drag_multi_orig_positions, {})
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_left_press_without_ctrl_still_starts_selected_takeoff_drag(self):
        view = self._make_view()
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertFalse(view._zoom_press_ctrl)
        self.assertEqual(view._drag_plan_item_uid, "t1")
        item = view._uid_to_items["t1"][0]
        self.assertEqual(view._drag_item_orig_positions[id(item)], item.pos())

    def test_selected_text_annotation_cursor_only_moves_over_text_bounds(self):
        view, _item = self._make_selected_text_annotation_view()
        self.assertEqual(
            view._resolve_select_cursor(QtCore.QPoint(20, 20)),
            Qt.CursorShape.SizeAllCursor,
        )
        self.assertEqual(
            view._resolve_select_cursor(QtCore.QPoint(200, 200)),
            Qt.CursorShape.ArrowCursor,
        )

    def test_selected_text_annotation_drag_starts_only_inside_hitbox(self):
        view, item = self._make_selected_text_annotation_view()
        outside_press = FakeMouseEvent(x=200, y=200)
        view.mousePressEvent(outside_press)
        self.assertTrue(outside_press.accepted)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_orig_position, [])
        inside_press = FakeMouseEvent(x=20, y=20)
        view.mousePressEvent(inside_press)
        self.assertTrue(inside_press.accepted)
        self.assertEqual(view._drag_plan_item_uid, "a1")
        self.assertEqual(
            view._drag_orig_position,
            view._current_annotations["a1"].position,
        )
        self.assertEqual(view._drag_item_orig_positions[id(item)], item.pos())

    def test_stale_drag_state_clears_when_mouse_moves_without_left_button(self):
        view = self._make_view()
        overlay = view._uid_to_items["t1"][0]
        overlay_orig = overlay.pos()
        overlay.setPos(25.0, 30.0)
        view._drag_plan_item_uid = "t1"
        view._drag_handle_index = -1
        view._drag_orig_position = [0.0, 0.0, 10.0, 0.0]
        view._drag_item_orig_positions = {id(overlay): overlay_orig}
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        move = FakeMouseEvent(x=200, y=200, buttons=Qt.MouseButton.NoButton)
        view.mouseMoveEvent(move)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertIsNone(view._select_band_origin)
        self.assertEqual(overlay.pos(), overlay_orig)

    def test_single_click_text_annotation_selects_toolbar_target_without_editing(self):
        view, _item = self._make_selected_text_annotation_view()
        press = FakeMouseEvent(x=20, y=20)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])
        self.assertEqual(view.editing_text_annotation_uids, [])

    def test_double_click_text_annotation_enters_inline_edit_without_dragging(self):
        view, _item = self._make_selected_text_annotation_view()
        press = FakeMouseEvent(x=20, y=20)
        view.mouseDoubleClickEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])
        self.assertEqual(view.editing_text_annotation_uids, ["a1"])
        self.assertIsNone(view._drag_plan_item_uid)

    def test_double_click_named_view_label_enters_rename_without_text_toolbar(self):
        view = self._make_view({"nv1"})
        label = QGraphicsTextItem("Named View")
        label.setData(0, "nv1")
        label.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
        view._named_view_label_at = lambda _pos: label
        view._current_annotations = {
            "nv1": BidAnnotation(uid="nv1", annotation_type="namedview")
        }
        press = FakeMouseEvent(x=20, y=20)
        view.mouseDoubleClickEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.editing_named_view_uids, ["nv1"])
        self.assertEqual(view.editing_text_annotation_uids, [])
        self.assertEqual(view.selected_text_annotation_uids, [])
        self.assertIsNone(view._drag_plan_item_uid)

    def test_ctrl_zoom_release_restores_temporary_overlay_and_handle_positions(self):
        view = self._make_view()
        overlay = view._uid_to_items["t1"][0]
        handle = FakeItem(5.0, 6.0)
        view._selection_items = [handle]
        overlay_orig = overlay.pos()
        handle_orig = handle.pos()
        overlay.setPos(21.0, 22.0)
        handle.setPos(25.0, 26.0)
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_positions = {
            id(overlay): overlay_orig,
            id(handle): handle_orig,
        }
        view._ctrl_held = True
        view._zoom_press_ctrl = True
        InputHandlerMixin.keyReleaseEvent(view, FakeKeyEvent())
        self.assertEqual(overlay.pos(), overlay_orig)
        self.assertEqual(handle.pos(), handle_orig)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_ctrl_r_does_not_enter_rotate_mode_when_selection_disabled(self):
        view = self._make_view({"t1"})
        view._selection_enabled = False
        view._rotate_handle_uid = None
        view._advanced_mouse_controls_enabled = False
        view.cursor_mode_change_requested = FakeSignal()
        calls = []
        view._create_rotate_handle = lambda _uids: calls.append("create") or True
        view._create_slope_rotate_handle = lambda: calls.append("slope") or True
        view._remove_rotate_handle = lambda: calls.append("remove")
        view._apply_cursor_mode = lambda mode: calls.append(("mode", mode))
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertFalse(event.accepted)
        self.assertEqual(calls, [])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_ctrl_v_uses_content_specific_paste_state_when_editing_is_disabled(self):
        view = self._make_view(set())
        view._editing_enabled = False
        paste_allowed = [True]
        view._paste_allowed = lambda: paste_allowed[0]
        view.paste_requested = FakeSignal()
        event = FakeKeyEvent(
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(view.paste_requested.emitted, [()])
        paste_allowed[0] = False
        blocked_event = FakeKeyEvent(
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, blocked_event)
        self.assertFalse(blocked_event.accepted)
        self.assertEqual(view.paste_requested.emitted, [()])

    def test_ctrl_r_clears_snap_preview_without_removing_selection_items(self):
        view = self._make_view({"t1"})
        scene = QGraphicsScene()
        snap_preview = QGraphicsRectItem(0.0, 0.0, 4.0, 4.0)
        selection_item = QGraphicsPathItem()
        scene.addItem(snap_preview)
        scene.addItem(selection_item)
        view._scene = scene
        view._place_preview_items = [snap_preview]
        view._place_flashing = False
        view._backout_orig_parent_path = None
        view.clear_place_preview = lambda: PlacementModeMixin.clear_place_preview(view)
        view._rotate_handle_uid = None
        view.cursor_mode_change_requested = FakeSignal()
        view._create_rotate_handle = lambda uids: set(uids) == {"t1"}

        def apply_cursor_mode(mode):
            view._cursor_mode = mode

        view._apply_cursor_mode = apply_cursor_mode
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._cursor_mode, "rotate")
        self.assertEqual(view._place_preview_items, [])
        self.assertIsNone(snap_preview.scene())
        self.assertIs(selection_item.scene(), scene)
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("rotate",)])

    def test_ctrl_r_from_place_mode_exits_placement_before_rotate(self):
        view = self._make_view({"t1"})
        view._cursor_mode = "place"
        view._rotate_handle_uid = None
        view.cursor_mode_change_requested = FakeSignal()
        calls = []

        def exit_place_mode():
            calls.append("exit_place")
            view._cursor_mode = "select"
            view.place_exited.emit()

        def apply_cursor_mode(mode):
            calls.append(("mode", mode))
            view._cursor_mode = mode

        view.place_exited = FakeSignal()
        view._exit_place_mode = exit_place_mode
        view._create_rotate_handle = (
            lambda uids: calls.append(("create", set(uids))) or True
        )
        view.clear_place_preview = lambda: None
        view._apply_cursor_mode = apply_cursor_mode
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(
            calls,
            [
                "exit_place",
                ("create", {"t1"}),
                ("mode", "rotate"),
            ],
        )
        self.assertEqual(view._cursor_mode, "rotate")
        self.assertEqual(view.place_exited.emitted, [()])
        self.assertEqual(
            view.cursor_mode_change_requested.emitted,
            [("rotate",)],
        )

    def test_ctrl_shift_r_clears_snap_preview_before_slope_rotate(self):
        view = self._make_view({"t1"})
        scene = QGraphicsScene()
        snap_preview = QGraphicsRectItem(0.0, 0.0, 4.0, 4.0)
        selection_item = QGraphicsPathItem()
        scene.addItem(snap_preview)
        scene.addItem(selection_item)
        view._scene = scene
        view._place_preview_items = [snap_preview]
        view._place_flashing = False
        view._backout_orig_parent_path = None
        view.clear_place_preview = lambda: PlacementModeMixin.clear_place_preview(view)
        view._cursor_mode = "select"
        view.cursor_mode_change_requested = FakeSignal()
        view._create_slope_rotate_handle = lambda: True

        def apply_cursor_mode(mode):
            view._cursor_mode = mode

        view._apply_cursor_mode = apply_cursor_mode
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._cursor_mode, "slope_rotate")
        self.assertEqual(view._place_preview_items, [])
        self.assertIsNone(snap_preview.scene())
        self.assertIs(selection_item.scene(), scene)
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("slope_rotate",)])

    def test_multi_takeoff_drag_preview_and_commit_preserve_group_offsets(self):
        view = self._make_view({"t1", "t2"})
        view._current_takeoffs["t1"].position = [3.0, 3.0, 13.0, 3.0]
        view._current_takeoffs["t2"].position = [22.0, 22.0, 32.0, 22.0]
        view._uid_to_items = {
            "t1": [FakeItem(100.0, 100.0)],
            "t2": [FakeItem(200.0, 200.0)],
        }
        border1 = FakeItem(300.0, 300.0, uid="t1")
        border2 = FakeItem(400.0, 400.0, uid="t2")
        view._selection_items = [border1, border2]
        view._snap_increments = 10.0
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        press = FakeMouseEvent(x=0, y=0)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(set(view._drag_multi_orig_positions), {"t1", "t2"})
        move = FakeMouseEvent(x=6, y=6)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(
            view._uid_to_items["t1"][0].pos(), QtCore.QPointF(110.0, 110.0)
        )
        self.assertEqual(
            view._uid_to_items["t2"][0].pos(), QtCore.QPointF(210.0, 210.0)
        )
        self.assertEqual(border1.pos(), QtCore.QPointF(310.0, 310.0))
        self.assertEqual(border2.pos(), QtCore.QPointF(410.0, 410.0))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=6, y=6, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [13.0, 13.0, 23.0, 13.0],
        )
        self.assertEqual(
            view._current_takeoffs["t2"].position,
            [32.0, 32.0, 42.0, 32.0],
        )

    def test_multi_drag_moves_unselected_hole_with_selected_area_parent(self):
        view = self._make_view({"parent", "t2"})
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                position=[3.0, 3.0, 13.0, 3.0, 13.0, 13.0, 3.0, 13.0],
            ),
            "hole": Takeoff(
                uid="hole",
                condition_uid="area",
                parent_uid="parent",
                position=[6.0, 6.0, 9.0, 6.0, 9.0, 9.0, 6.0, 9.0],
            ),
            "t2": Takeoff(
                uid="t2",
                condition_uid="linear",
                position=[22.0, 22.0, 32.0, 22.0],
            ),
        }
        view._uid_to_items = {
            "parent": [FakeItem(100.0, 100.0)],
            "hole": [FakeItem(150.0, 150.0)],
            "t2": [FakeItem(200.0, 200.0)],
        }
        view._snap_increments = 10.0
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        view.find_takeoff_at = lambda _scene_pos: "parent"
        view.find_takeoffs_at = lambda _scene_pos: ["parent"]
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        self.assertEqual(set(view._drag_multi_orig_positions), {"parent", "hole", "t2"})
        view.mouseMoveEvent(FakeMouseEvent(x=6, y=6))
        self.assertEqual(
            view._uid_to_items["parent"][0].pos(), QtCore.QPointF(110.0, 110.0)
        )
        self.assertEqual(
            view._uid_to_items["hole"][0].pos(), QtCore.QPointF(160.0, 160.0)
        )
        view.mouseReleaseEvent(
            FakeMouseEvent(x=6, y=6, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(
            view._current_takeoffs["parent"].position,
            [13.0, 13.0, 23.0, 13.0, 23.0, 23.0, 13.0, 23.0],
        )
        self.assertEqual(
            view._current_takeoffs["hole"].position,
            [16.0, 16.0, 19.0, 16.0, 19.0, 19.0, 16.0, 19.0],
        )

    def test_multi_hotlink_arrow_move_updates_graphics_and_dirty_positions(self):
        view = self._make_view({"hot1", "hot2"})
        hot1 = BidAnnotation(
            uid="hot1",
            annotation_type="hotlink",
            position=[10.0, 20.0],
        )
        hot2 = BidAnnotation(
            uid="hot2",
            annotation_type="hotlink",
            position=[30.0, 40.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"hot1": hot1, "hot2": hot2}
        hot1_item = FakeItem(100.0, 200.0, uid="hot1")
        hot2_item = FakeItem(300.0, 400.0, uid="hot2")
        border1 = FakeItem(500.0, 600.0, uid="hot1")
        border2 = FakeItem(700.0, 800.0, uid="hot2")
        view._uid_to_items = {"hot1": [hot1_item], "hot2": [hot2_item]}
        view._selection_items = [border1, border2]
        event = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(hot1.position, [11.0, 20.0])
        self.assertEqual(hot2.position, [31.0, 40.0])
        self.assertEqual(hot1_item.pos(), QtCore.QPointF(101.0, 200.0))
        self.assertEqual(hot2_item.pos(), QtCore.QPointF(301.0, 400.0))
        self.assertEqual(border1.pos(), QtCore.QPointF(501.0, 600.0))
        self.assertEqual(border2.pos(), QtCore.QPointF(701.0, 800.0))
        self.assertEqual(
            view._dirty_ann_positions,
            {
                "hot1": ("hotlink", [11.0, 20.0]),
                "hot2": ("hotlink", [31.0, 40.0]),
            },
        )

    def test_single_hotlink_arrow_move_flushes_on_key_release(self):
        view = self._make_view({"hot1"})
        hotlink = BidAnnotation(
            uid="hot1",
            annotation_type="hotlink",
            position=[10.0, 20.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"hot1": hotlink}
        view._uid_to_items = {"hot1": [FakeItem(100.0, 200.0, uid="hot1")]}
        flushed = []

        def flush_dirty_positions():
            flushed.append(dict(view._dirty_ann_positions))
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()

        view._flush_dirty_positions = flush_dirty_positions
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Down))
        release = FakeKeyEvent(Qt.Key.Key_Down)
        InputHandlerMixin.keyReleaseEvent(view, release)
        self.assertTrue(release.accepted)
        self.assertEqual(hotlink.position, [10.0, 21.0])
        self.assertEqual(flushed, [{"hot1": ("hotlink", [10.0, 21.0])}])
        self.assertFalse(view._keyboard_move_dirty)

    def test_takeoff_arrow_move_uses_same_key_release_flush_boundary(self):
        view = self._make_view({"t1"})
        flushed = []

        def flush_dirty_positions():
            flushed.append(dict(view._dirty_positions))
            view._dirty_positions.clear()
            view._position_before_edit.clear()

        view._flush_dirty_positions = flush_dirty_positions
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        release = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyReleaseEvent(view, release)
        self.assertTrue(release.accepted)
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [1.0, 0.0, 11.0, 0.0],
        )
        self.assertEqual(flushed, [{"t1": [1.0, 0.0, 11.0, 0.0]}])

    def test_takeoff_arrow_move_waits_for_geometry_edit_lease(self):
        view = self._make_view({"t1"})
        requested = []
        view.request_geometry_edit_lease = (
            lambda uids: requested.append(set(uids)) or False
        )
        event = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(requested, [{"t1"}])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(view._dirty_positions, {})

    def test_sql_selection_refreshes_move_cursor_before_async_lease(self):
        view = self._make_view(set())
        viewport = FakeCursorViewport()
        view.viewport = lambda: viewport
        view.find_selected_movable_at = lambda _scene_pos: (
            "t1" if "t1" in view._selected_uids else None
        )
        view._update_cursor = lambda vp_pos=None: InputHandlerMixin._update_cursor(
            view, vp_pos
        )
        view.request_geometry_edit_lease = lambda _uids: False
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(viewport.cursor, Qt.CursorShape.SizeAllCursor)

    def test_programmatic_sql_selection_refreshes_cursor_without_mouse_move(self):
        # Authoritative SQL hydration may rebuild the selected item while keeping
        # the same UID, so the idempotent selection projection must also refresh.
        view = self._make_view({"t1"})
        view._annotation_only_selection = False
        view._current_conditions = {
            "c": Condition(
                uid="c",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            )
        }
        viewport = FakeCursorViewport()
        view.viewport = lambda: viewport
        view._last_mouse_vp_pos = QtCore.QPoint(10, 10)
        view.find_selected_movable_at = lambda _scene_pos: (
            "t1" if "t1" in view._selected_uids else None
        )
        view._update_cursor = lambda vp_pos=None: InputHandlerMixin._update_cursor(
            view, vp_pos
        )
        SelectionManagerMixin.set_selected_uids(view, {"t1"})
        self.assertEqual(viewport.cursor, Qt.CursorShape.SizeAllCursor)
        SelectionManagerMixin.clear_selection(view)
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def test_area_parent_arrow_move_preserves_hole_relative_position(self):
        view = self._make_view({"parent"})
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA)
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                position=[3.0, 3.0, 13.0, 3.0, 13.0, 13.0, 3.0, 13.0],
            ),
            "hole": Takeoff(
                uid="hole",
                condition_uid="area",
                parent_uid="parent",
                position=[6.0, 6.0, 9.0, 6.0, 9.0, 9.0, 6.0, 9.0],
            ),
        }
        view._uid_to_items = {
            "parent": [FakeItem(100.0, 100.0)],
            "hole": [FakeItem(150.0, 150.0)],
        }
        view._snap_increments = 10.0
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        self.assertEqual(
            view._current_takeoffs["parent"].position,
            [13.0, 3.0, 23.0, 3.0, 23.0, 13.0, 13.0, 13.0],
        )
        self.assertEqual(
            view._current_takeoffs["hole"].position,
            [16.0, 6.0, 19.0, 6.0, 19.0, 9.0, 16.0, 9.0],
        )
        self.assertEqual(
            view._uid_to_items["hole"][0].pos(), QtCore.QPointF(160.0, 150.0)
        )
        self.assertEqual(
            set(view._dirty_positions),
            {"parent", "hole"},
        )
        self.assertEqual(
            view._position_before_edit["hole"],
            [6.0, 6.0, 9.0, 6.0, 9.0, 9.0, 6.0, 9.0],
        )

    def test_arrow_auto_repeat_release_does_not_split_move_flush(self):
        view = self._make_view({"t1"})
        flushed = []
        view._flush_dirty_positions = lambda: flushed.append(
            dict(view._dirty_positions)
        )
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        repeat_release = FakeKeyEvent(Qt.Key.Key_Right, auto_repeat=True)
        InputHandlerMixin.keyReleaseEvent(view, repeat_release)
        self.assertTrue(repeat_release.accepted)
        self.assertEqual(flushed, [])
        self.assertTrue(view._keyboard_move_dirty)
        final_release = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyReleaseEvent(view, final_release)
        self.assertTrue(final_release.accepted)
        self.assertEqual(flushed, [{"t1": [1.0, 0.0, 11.0, 0.0]}])
        self.assertFalse(view._keyboard_move_dirty)

    def test_focus_loss_flushes_pending_keyboard_move(self):
        view = self._make_view({"t1"})
        flushed = []
        reset_calls = []
        view._flush_dirty_positions = lambda: flushed.append(
            dict(view._dirty_positions)
        )
        view.reset_ctrl_held = lambda: reset_calls.append(True)
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(flushed, [{"t1": [1.0, 0.0, 11.0, 0.0]}])
        self.assertFalse(view._keyboard_move_dirty)
        self.assertEqual(reset_calls, [True])

    def test_focus_loss_cancels_zoom_rubber_band_started_without_selection(self):
        view = self._make_view()
        hidden = []
        view._rubber_band_origin = QtCore.QPointF(1.0, 2.0)
        view._rubber_band = SimpleNamespace(hide=lambda: hidden.append(True))
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(hidden, [True])
        self.assertIsNone(view._rubber_band_origin)

    def test_focus_loss_finishes_pan_and_publishes_changed_view(self):
        view = self._make_view()
        published = []
        view._panning = True
        view._pan_view_changed = True
        view._last_pan_point = QtCore.QPoint(5, 6)
        view._right_pan_press_pos = None
        view._right_pan_dragged = False
        view._publish_current_page_view_state = lambda: published.append(True)
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertFalse(view._panning)
        self.assertFalse(view._pan_view_changed)
        self.assertIsNone(view._last_pan_point)
        self.assertEqual(published, [True])

    def test_focus_loss_restores_rotation_preview_without_committing(self):
        view = self._make_view()
        preview_item = QGraphicsPathItem()
        preview_item.setRotation(15.0)
        handle_item = FakeItem(15.0, 20.0)
        view._rotation_drag_active = True
        view._rotation_drag_uid = "t1"
        view._rotation_drag_last_angle = 15.0
        view._rotation_drag_accumulated_deg = 15.0
        view._rotation_drag_snapped_deg = 15.0
        view._rotation_drag_preview_items = [preview_item]
        view._rotation_drag_handle_origins = [(handle_item, QtCore.QPointF(10.0, 20.0))]
        view._rotation_drag_orig_positions = {"t1": [0.0, 0.0, 10.0, 0.0]}
        view._rotation_drag_orig_rotations = {"t1": 0.0}
        view._rotate_line_item = None
        view._rotate_line_outline_item = None
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(preview_item.rotation(), 0.0)
        self.assertEqual(handle_item.pos(), QtCore.QPointF(10.0, 20.0))
        self.assertFalse(view._rotation_drag_active)
        self.assertEqual(view._rotation_drag_preview_items, [])
        self.assertEqual(view._rotation_drag_orig_positions, {})

    def test_focus_loss_finishes_pdf_text_selection_drag(self):
        view = self._make_view()
        finished = []
        view._pdf_text_drag_anchor = (0, 1)

        def finish_pdf_text_selection_drag():
            finished.append(True)
            view._pdf_text_drag_anchor = None
            return True

        view._finish_pdf_text_selection_drag = finish_pdf_text_selection_drag
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(finished, [True])
        self.assertIsNone(view._pdf_text_drag_anchor)

    def test_rotation_preview_does_not_rotate_condition_label_items(self):
        view = self._make_view({"t1"})
        view._cursor_mode = "rotate"
        view._rotate_handle_item = QGraphicsPathItem()
        view._rotate_handle_item.setPos(10.0, 0.0)
        view._rotate_center_scene = QtCore.QPointF(0.0, 0.0)
        view._rotate_handle_uid = "t1"
        view._rotate_handle_radius = 10.0
        view._rotate_handle_start_angle_deg = 0.0
        view._is_rotatable_uid = lambda uid: uid == "t1"
        view._current_takeoffs["t1"].rotation = 0.0
        path = QGraphicsPathItem()
        path.setData(0, "t1")
        label = QGraphicsTextItem("Display Name")
        label.setData(0, "t1")
        label.setData(2, "condition_label")
        label.setData(3, "display_name")
        view._uid_to_items = {"t1": [path, label]}
        press = FakeMouseEvent(x=10, y=0)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._rotation_drag_active)
        self.assertIn(path, view._rotation_drag_preview_items)
        self.assertNotIn(label, view._rotation_drag_preview_items)

    def test_multi_rotation_commits_compact_rect_as_rotated_corners(self):
        view = self._make_view({"rect1"})
        annotation = BidAnnotation(
            uid="rect1",
            annotation_type="rect",
            position=[0.0, 0.0, 10.0, 4.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"rect1": annotation}
        view._rotation_drag_orig_positions = {"rect1": list(annotation.position)}
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._dirty_rotations = {}
        view._rotation_before_edit = {}
        view._rotate_ost_center = (20.0, 20.0)
        view._flush_rotation_group = lambda: None
        view._apply_multi_rotation(90.0)
        new_position = annotation.position
        self.assertEqual(len(new_position), 9)
        self.assertAlmostEqual(new_position[-1], math.pi / 2.0)
        self.assertEqual(
            self._rendered_box_side_lengths(new_position),
            [4.0, 4.0, 10.0, 10.0],
        )
        self.assertEqual(
            view._dirty_ann_positions["rect1"],
            ("rect", new_position),
        )

    def test_multi_rotation_commits_compact_highlight_as_rotated_corners(self):
        view = self._make_view({"highlight1"})
        annotation = BidAnnotation(
            uid="highlight1",
            annotation_type="highlight",
            position=[0.0, 0.0, 12.0, 3.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"highlight1": annotation}
        view._rotation_drag_orig_positions = {"highlight1": list(annotation.position)}
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._dirty_rotations = {}
        view._rotation_before_edit = {}
        view._rotate_ost_center = (20.0, 20.0)
        view._flush_rotation_group = lambda: None
        view._apply_multi_rotation(90.0)
        new_position = annotation.position
        self.assertEqual(len(new_position), 9)
        self.assertAlmostEqual(new_position[-1], math.pi / 2.0)
        self.assertEqual(
            self._rendered_box_side_lengths(new_position),
            [3.0, 3.0, 12.0, 12.0],
        )
        self.assertEqual(
            view._dirty_ann_positions["highlight1"],
            ("highlight", new_position),
        )

    def test_rotate_handle_press_takes_priority_over_condition_label(self):
        view = self._make_view({"t1"})
        view._cursor_mode = "rotate"
        view._rotate_handle_item = QGraphicsPathItem()
        view._rotate_handle_item.setPos(10.0, 0.0)
        view._rotate_center_scene = QtCore.QPointF(0.0, 0.0)
        view._rotate_handle_uid = "t1"
        view._rotate_handle_radius = 10.0
        view._rotate_handle_start_angle_deg = 0.0
        view._is_rotatable_uid = lambda uid: uid == "t1"
        view._current_takeoffs["t1"].rotation = 0.0
        path = QGraphicsPathItem()
        path.setData(0, "t1")
        label = QGraphicsTextItem("Display Dimension")
        label.setData(0, "t1")
        label.setData(2, "condition_label")
        label.setData(3, "display_dimension")
        view._uid_to_items = {"t1": [path, label]}
        view._dimension_text_label_at = lambda _pos: label
        view._select_dimension_text_label = lambda _item: self.fail(
            "rotation handle press should not select display text labels"
        )
        press = FakeMouseEvent(x=10, y=0)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._rotation_drag_active)
        self.assertIn(path, view._rotation_drag_preview_items)
        self.assertNotIn(label, view._rotation_drag_preview_items)

    def _make_pattern_resize_view(self, condition_type):
        view = InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = FakeSceneBuilder()
        view._color_service = FakeColorService()
        view._linear_geom = FakeLinearGeom()
        condition = Condition(
            uid="c1",
            condition_type=condition_type,
            pattern=pattern_values.HORIZONTAL,
            spacing=4.0,
            thickness=2.0,
            color_fill=1,
        )
        position = (
            [0.0, 0.0, 10.0, 0.0]
            if condition_type == Condition.TYPE_LINEAR
            else [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        )
        takeoff = SimpleNamespace(
            condition_uid="c1",
            page_uid="page-1",
            area_uid="area-1",
            position=list(position),
            is_hole=False,
            parent_uid=None,
        )
        main_path = QPainterPath()
        main_path.addRect(0.0, 0.0, 10.0, 10.0)
        main_item = QGraphicsPathItem(main_path)
        old_pattern = QGraphicsPathItem(main_path)
        view._scene.addItem(main_item)
        view._scene.addItem(old_pattern)
        view._current_takeoffs = {"t1": takeoff}
        view._current_annotations = {}
        view._current_conditions = {"c1": condition}
        view._current_color_map = {}
        view._current_page_area_selections = {}
        view._uid_to_items = {"t1": [main_item, old_pattern]}
        view._takeoff_items = [main_item, old_pattern]
        view._handle_infos = [SimpleNamespace(item=FakeItem()) for _ in range(8)]
        view._drag_handle_index = 0
        view._drag_handle_corner_count = (
            0 if condition_type == Condition.TYPE_LINEAR else 4
        )
        view._drag_last_valid_new_pos = list(position)
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._selection_items = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        view._validate_hole_position = lambda *_args: True
        view._validate_parent_contains_holes = lambda *_args: True
        view._has_child_holes = lambda *_args: False
        return view, main_item, old_pattern

    def _make_hole_resize_view(self):
        view = InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = FakeSceneBuilder()
        view._color_service = FakeColorService()
        view._linear_geom = FakeLinearGeom()
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            pattern=pattern_values.TRANSPARENT,
            spacing=4.0,
            thickness=2.0,
            color_fill=1,
        )
        parent = Takeoff(
            uid="parent",
            condition_uid="c1",
            page_uid="page-1",
            area_uid="area-1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        hole = Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="page-1",
            area_uid="area-1",
            parent_uid="parent",
            position=[4.0, 4.0, 10.0, 4.0, 10.0, 10.0, 4.0, 10.0],
        )
        parent_path = QPainterPath()
        parent_path.addRect(0.0, 0.0, 20.0, 20.0)
        parent_item = QGraphicsPathItem(parent_path)
        hole_path = QPainterPath()
        hole_path.addRect(4.0, 4.0, 6.0, 6.0)
        hole_item = QGraphicsPathItem(hole_path)
        hole_item.setPen(QPen(Qt.PenStyle.NoPen))
        hole_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        stale_hole_pattern = QGraphicsPathItem(hole_path)
        stale_hole_pattern.setPen(QPen(QColor("#ff00ff")))
        for item in (parent_item, hole_item, stale_hole_pattern):
            view._scene.addItem(item)
        view._current_takeoffs = {"parent": parent, "hole": hole}
        view._current_annotations = {}
        view._current_conditions = {"c1": condition}
        view._current_color_map = {}
        view._current_page_area_selections = {}
        view._uid_to_items = {
            "parent": [parent_item],
            "hole": [hole_item, stale_hole_pattern],
        }
        view._takeoff_items = [parent_item, hole_item, stale_hole_pattern]
        view._handle_infos = [SimpleNamespace(item=FakeItem()) for _ in range(8)]
        view._drag_handle_index = 2
        view._drag_handle_corner_count = 4
        view._drag_last_valid_new_pos = list(hole.position)
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._selection_items = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        view._validate_hole_position = lambda *_args: True
        view._validate_parent_contains_holes = lambda *_args: True
        view._has_child_holes = lambda *_args: False
        view._refresh_condition_text_labels_for_takeoff = lambda _uid: None
        return view, parent_item, hole_item, stale_hole_pattern

    def _make_dimension_resize_view(self, position=None):
        view = InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = FakeSceneBuilder()
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._current_color_map = {}
        view._takeoff_items = []
        view._selection_items = []
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        ann = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            position=list(position or [0.0, 0.0, 120.0, 0.0]),
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        renderer = AnnotationItemRenderer(view._scene_builder.get_coordinate_system())
        results, uid_to_items = renderer.create_all_annotation_items([("d1", ann)])
        items = uid_to_items["d1"]
        for item, _link in results:
            view._scene.addItem(item)
            view._takeoff_items.append(item)
        view._current_annotations = {"d1": ann}
        view._uid_to_items = {"d1": items}
        view._handle_infos = [SimpleNamespace(item=FakeItem()) for _ in range(2)]
        view._drag_plan_item_uid = "d1"
        view._drag_handle_index = 1
        view._drag_handle_corner_count = 0
        view._drag_orig_position = list(ann.position)
        view._drag_item_orig_positions = {id(item): item.pos() for item in items}
        view._drag_item_orig_paths = {
            id(item): QPainterPath(item.path())
            for item in items
            if isinstance(item, QGraphicsPathItem)
        }
        view._drag_item_orig_text_states = {
            id(item): (
                item.toPlainText(),
                item.textWidth(),
                item.rotation(),
                item.transformOriginPoint(),
                item.font(),
                item.defaultTextColor(),
            )
            for item in items
            if isinstance(item, QGraphicsTextItem)
        }
        view._drag_uid_orig_items = {"d1": list(items)}
        return view, ann

    def _make_area_annotation_resize_view(self, annotation_type):
        view = InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = FakeSceneBuilder()
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._current_color_map = {}
        view._takeoff_items = []
        view._selection_items = []
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        ann = BidAnnotation(
            uid="a1",
            annotation_type=annotation_type,
            position=[0.0, 0.0, 60.0, 0.0, 60.0, 40.0, 0.0, 40.0],
            color="#ff0000",
        )
        renderer = AnnotationItemRenderer(view._scene_builder.get_coordinate_system())
        results, uid_to_items = renderer.create_all_annotation_items([("a1", ann)])
        items = uid_to_items["a1"]
        for item, _link in results:
            view._scene.addItem(item)
            view._takeoff_items.append(item)
        view._current_annotations = {"a1": ann}
        view._uid_to_items = {"a1": items}
        view._handle_infos = [SimpleNamespace(item=FakeItem()) for _ in range(8)]
        view._drag_plan_item_uid = "a1"
        view._drag_handle_corner_count = 4
        view._drag_orig_position = list(ann.position)
        view._drag_last_valid_new_pos = list(ann.position)
        view._drag_item_orig_positions = {id(item): item.pos() for item in items}
        view._drag_item_orig_paths = {
            id(item): QPainterPath(item.path())
            for item in items
            if isinstance(item, QGraphicsPathItem)
        }
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {"a1": list(items)}
        return view, ann, items[0]

    def _make_named_view_resize_view(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        ann = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            position=[100.0, 80.0, 10.0, 20.0, 100.0, 20.0, 10.0, 80.0, 0.0],
            color="#008000",
        )
        return view, ann

    def test_rotated_annotation_resize_press_defers_write_and_cancel_restores(self):
        view = self._make_view({"a1"})
        original = [
            0.0,
            0.0,
            10.0,
            0.0,
            10.0,
            4.0,
            0.0,
            4.0,
            math.radians(30.0),
        ]
        ann = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=list(original),
        )
        view._current_takeoffs = {}
        view._current_annotations = {"a1": ann}
        view._drag_plan_item_uid = "a1"
        view._drag_orig_position = list(original)
        view._flush_dirty_positions = lambda: self.fail(
            "resize press must not persist before movement"
        )
        view._unrotate_annotation_for_resize(ann, "a1")
        self.assertNotEqual(ann.position, original)
        self.assertEqual(view._position_before_edit["a1"], original)
        self.assertEqual(view._dirty_ann_positions, {})
        view._clear_drag_tracking(restore_preview=True)
        self.assertEqual(ann.position, original)
        self.assertNotIn("a1", view._position_before_edit)

    def test_ink_annotation_drag_translates_even_path_points_once(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        original = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        moved = view._compute_ink_drag_position(original, 3.0, -4.0)
        self.assertEqual(moved, [13.0, 16.0, 33.0, 36.0, 53.0, 56.0])
        self.assertEqual(original, [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])

    def test_ink_annotation_drag_preserves_rotation_prefix(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        original = [0.25, 10.0, 20.0, 30.0, 40.0]
        moved = view._compute_ink_drag_position(original, 3.0, -4.0)
        self.assertEqual(moved, [0.25, 13.0, 16.0, 33.0, 36.0])

    def test_multi_drag_ink_preview_delta_uses_first_path_point(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        view._scene_builder = FakeSceneBuilder()
        view._current_page_transform = lambda: None
        annotation = BidAnnotation(
            uid="ink1",
            annotation_type="ink",
            position=[0.25, 10.0, 20.0, 30.0, 40.0],
        )
        view._current_annotations = {"ink1": annotation}
        moved = view._translate_group_plan_item_position(
            "ink1", annotation.position, 3.0, -4.0
        )
        self.assertEqual(moved, [0.25, 13.0, 16.0, 33.0, 36.0])
        delta = view._snapped_multi_drag_scene_delta(
            "ink1", annotation.position, moved, 100.0, 200.0
        )
        expected_dx, expected_dy = view.ost_to_scene_delta(3.0, -4.0)
        self.assertEqual(delta, QtCore.QPointF(expected_dx, expected_dy))

    def test_named_view_handles_use_normalized_edit_corner_order(self):
        _view, ann = self._make_named_view_resize_view()
        self.assertEqual(
            SelectionManagerMixin._get_ann_corners_ost(ann),
            [10.0, 20.0, 100.0, 20.0, 100.0, 80.0, 10.0, 80.0],
        )

    def test_named_view_resize_top_middle_changes_top_edge_only(self):
        view, ann = self._make_named_view_resize_view()
        new_pos = view._compute_ann_resize(
            ann,
            ann.position,
            0.0,
            -5.0,
            4,
            4,
        )
        self.assertEqual(
            new_pos,
            [100.0, 80.0, 10.0, 15.0, 100.0, 15.0, 10.0, 80.0, 0.0],
        )

    def test_named_view_resize_bottom_middle_changes_bottom_edge_only(self):
        view, ann = self._make_named_view_resize_view()
        new_pos = view._compute_ann_resize(
            ann,
            ann.position,
            0.0,
            9.0,
            6,
            4,
        )
        self.assertEqual(
            new_pos,
            [100.0, 89.0, 10.0, 20.0, 100.0, 20.0, 10.0, 89.0, 0.0],
        )

    def test_named_view_resize_top_left_corner_changes_expected_corner(self):
        view, ann = self._make_named_view_resize_view()
        new_pos = view._compute_ann_resize(
            ann,
            ann.position,
            -5.0,
            -7.0,
            0,
            4,
        )
        self.assertEqual(
            new_pos,
            [100.0, 80.0, 5.0, 13.0, 100.0, 13.0, 5.0, 80.0, 0.0],
        )

    def _dimension_label(self, view):
        for item in view._uid_to_items["d1"]:
            if isinstance(item, QGraphicsTextItem):
                return item
        self.fail("Dimension label item was not found")

    def _dimension_path(self, view):
        item = view._uid_to_items["d1"][0]
        self.assertIsInstance(item, QGraphicsPathItem)
        return item

    def test_area_pattern_preview_refreshes_during_resize_drag(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        view.update_drag_handle_positions(
            [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0], "t1"
        )
        self.assertIsNone(old_pattern.scene())
        self.assertEqual(len(view._uid_to_items["t1"]), 2)
        self.assertIs(view._uid_to_items["t1"][0], main_item)
        self.assertIsNot(view._uid_to_items["t1"][1], old_pattern)
        self.assertEqual(main_item.path().boundingRect().right(), 20.0)
        self.assertEqual(
            view._uid_to_items["t1"][1].path().boundingRect().right(), 20.0
        )

    def test_inactive_area_resize_preview_uses_configured_appearance(self):
        view, main_item, _old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        view._current_color_map = {"c1": "#00aa00"}
        view._current_page_area_selections = {"page-1": "area-2"}
        view.update_drag_handle_positions(
            [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0], "t1"
        )
        self.assertEqual(main_item.pen().color().name(), "#d0d0d0")

    def test_hole_resize_preview_keeps_child_item_invisible(self):
        view, parent_item, hole_item, stale_hole_pattern = self._make_hole_resize_view()
        view.update_drag_handle_positions(
            [4.0, 4.0, 10.0, 4.0, 14.0, 14.0, 4.0, 10.0], "hole"
        )
        self.assertEqual(hole_item.pen().style(), Qt.PenStyle.NoPen)
        self.assertEqual(hole_item.brush().style(), Qt.BrushStyle.NoBrush)
        self.assertEqual(view._uid_to_items["hole"], [hole_item])
        self.assertIsNone(stale_hole_pattern.scene())
        self.assertFalse(parent_item.path().contains(QtCore.QPointF(8.0, 8.0)))
        self.assertTrue(parent_item.path().contains(QtCore.QPointF(2.0, 2.0)))
        self.assertEqual(len(view._scene_builder.pattern_angles), 1)

    def test_area_resize_preview_recenters_condition_labels(self):
        view, main_item, _old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        dimension_label = QGraphicsTextItem("10 SF")
        dimension_label.setData(0, "t1")
        dimension_label.setData(2, "condition_label")
        dimension_label.setData(3, "display_dimension")
        dimension_label.setPos(200.0, 200.0)
        name_label = QGraphicsTextItem("Area")
        name_label.setData(0, "t1")
        name_label.setData(2, "condition_label")
        name_label.setData(3, "display_name")
        name_label.setPos(200.0, 240.0)
        view._scene.addItem(dimension_label)
        view._scene.addItem(name_label)
        view._uid_to_items["t1"].extend([dimension_label, name_label])
        view.update_drag_handle_positions(
            [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0], "t1"
        )
        dimension_bounds = dimension_label.boundingRect()
        dimension_center = QtCore.QPointF(
            dimension_label.pos().x() + dimension_bounds.width() / 2.0,
            dimension_label.pos().y() + dimension_bounds.height() / 2.0,
        )
        name_bounds = name_label.boundingRect()
        name_center_x = name_label.pos().x() + name_bounds.width() / 2.0
        self.assertEqual(main_item.path().boundingRect().center(), dimension_center)
        self.assertAlmostEqual(name_center_x, dimension_center.x())
        self.assertEqual(
            name_label.pos().y(),
            dimension_label.pos().y() + dimension_bounds.height() + 4.0,
        )

    def test_linear_pattern_preview_refreshes_during_resize_drag(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_LINEAR
        )
        view.update_drag_handle_positions([0.0, 0.0, 20.0, 0.0], "t1")
        self.assertIsNone(old_pattern.scene())
        self.assertEqual(len(view._uid_to_items["t1"]), 2)
        self.assertIs(view._uid_to_items["t1"][0], main_item)
        self.assertIsNot(view._uid_to_items["t1"][1], old_pattern)
        self.assertEqual(main_item.path().boundingRect().right(), 20.0)
        self.assertEqual(
            view._uid_to_items["t1"][1].path().boundingRect().right(), 20.0
        )
        self.assertEqual(view._scene_builder.pattern_angles, [0.0])

    def test_diagonal_linear_pattern_preview_uses_drag_direction(self):
        view, _main_item, _old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_LINEAR
        )
        view.update_drag_handle_positions([0.0, 0.0, 20.0, 20.0], "t1")
        self.assertAlmostEqual(view._scene_builder.pattern_angles[-1], math.pi / 4.0)

    def test_area_invalid_resize_keeps_previous_valid_geometry(self):
        view, main_item, _old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        original_bounds = main_item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        invalid_pos = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 0.0, 10.0]
        view.update_drag_handle_positions(invalid_pos, "t1")
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(main_item.path().boundingRect(), original_bounds)

    def test_horizontal_bid_dimension_resize_updates_label_live(self):
        view, _ann = self._make_dimension_resize_view()
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "d1")
        label = self._dimension_label(view)
        bounds = label.boundingRect()
        label_center_x = label.pos().x() + bounds.width() / 2.0
        self.assertEqual(label.toPlainText(), format_dimension_distance(255.0))
        self.assertAlmostEqual(label_center_x, 127.5, delta=0.5)
        self.assertEqual(self._dimension_path(view).path().elementCount(), 6)

    def test_vertical_bid_dimension_resize_updates_label_live(self):
        view, _ann = self._make_dimension_resize_view([0.0, 0.0, 0.0, 60.0])
        view.update_drag_handle_positions([0.0, 0.0, 0.0, 120.0], "d1")
        label = self._dimension_label(view)
        self.assertEqual(label.toPlainText(), "10' - 0\"")
        self.assertAlmostEqual(abs(label.rotation()), 90.0, delta=0.01)
        path = self._dimension_path(view).path()
        tick_start = path.elementAt(2)
        tick_end = path.elementAt(3)
        self.assertAlmostEqual(tick_start.y, tick_end.y)
        self.assertNotAlmostEqual(tick_start.x, tick_end.x)

    def test_angled_bid_dimension_resize_updates_label_rotation_live(self):
        view, _ann = self._make_dimension_resize_view([0.0, 0.0, 36.0, 0.0])
        view.update_drag_handle_positions([0.0, 0.0, 36.0, 48.0], "d1")
        label = self._dimension_label(view)
        bounds = label.boundingRect()
        label_center = QtCore.QPointF(
            label.pos().x() + bounds.width() / 2.0,
            label.pos().y() + bounds.height() / 2.0,
        )
        self.assertEqual(label.toPlainText(), "5' - 0\"")
        self.assertAlmostEqual(label.rotation(), 53.130102, places=3)
        self.assertLess(abs(label_center.x() - 18.0), 12.0)
        self.assertLess(abs(label_center.y() - 24.0), 12.0)

    def test_bid_dimension_commit_text_matches_last_preview(self):
        view, ann = self._make_dimension_resize_view()
        new_pos = [0.0, 0.0, 255.0, 0.0]
        view.update_drag_handle_positions(new_pos, "d1")
        ann.position = new_pos
        view._clear_drag_tracking()
        self.assertEqual(self._dimension_label(view).toPlainText(), "21' - 3\"")
        self.assertEqual(ann.position, new_pos)

    def test_cancel_bid_dimension_resize_restores_label_and_path(self):
        view, _ann = self._make_dimension_resize_view()
        original_label = self._dimension_label(view).toPlainText()
        original_path_bounds = self._dimension_path(view).path().boundingRect()
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "d1")
        self.assertEqual(self._dimension_label(view).toPlainText(), "21' - 3\"")
        view._clear_drag_tracking(restore_preview=True)
        self.assertEqual(self._dimension_label(view).toPlainText(), original_label)
        self.assertEqual(
            self._dimension_path(view).path().boundingRect(), original_path_bounds
        )

    def test_repeated_bid_dimension_resize_preview_reuses_label_item(self):
        view, _ann = self._make_dimension_resize_view()
        original_items = list(view._uid_to_items["d1"])
        view.update_drag_handle_positions([0.0, 0.0, 180.0, 0.0], "d1")
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "d1")
        self.assertEqual(view._uid_to_items["d1"], original_items)
        self.assertEqual(self._dimension_label(view).toPlainText(), "21' - 3\"")

    def test_collapsed_bid_dimension_preview_removes_and_recreates_label(self):
        view, _ann = self._make_dimension_resize_view()
        original_label = self._dimension_label(view)
        view.update_drag_handle_positions([0.0, 0.0, 0.0, 0.0], "d1")
        self.assertTrue(self._dimension_path(view).path().isEmpty())
        self.assertIsNone(original_label.scene())
        self.assertNotIn(original_label, view._uid_to_items["d1"])
        self.assertNotIn(original_label, view._takeoff_items)
        view.update_drag_handle_positions([0.0, 0.0, 120.0, 0.0], "d1")
        replacement_label = self._dimension_label(view)
        self.assertIsNot(replacement_label, original_label)
        self.assertEqual(replacement_label.data(0), "d1")
        self.assertEqual(replacement_label.data(2), DIMENSION_LABEL_ITEM_KIND)
        self.assertTrue(
            replacement_label.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )

    def test_bid_aline_resize_preview_remains_path_only(self):
        view, _ann = self._make_dimension_resize_view()
        line = BidAnnotation(
            uid="l1",
            annotation_type="line",
            position=[0.0, 0.0, 120.0, 0.0],
            color="#ff0000",
        )
        line_path = QPainterPath()
        line_path.moveTo(0.0, 0.0)
        line_path.lineTo(120.0, 0.0)
        line_item = QGraphicsPathItem(line_path)
        line_item.setData(0, "l1")
        view._scene.addItem(line_item)
        view._current_annotations = {"l1": line}
        view._uid_to_items = {"l1": [line_item]}
        view._handle_infos = [SimpleNamespace(item=FakeItem()) for _ in range(2)]
        view._drag_handle_index = 1
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "l1")
        self.assertEqual(view._uid_to_items["l1"], [line_item])
        self.assertEqual(line_item.path().elementCount(), 2)

    def test_cloud_resize_preview_from_corner_keeps_cloud_silhouette(self):
        view, ann, item = self._make_area_annotation_resize_view("cloud")
        original_position = list(ann.position)
        self.assertTrue(_path_has_curve(item.path()))
        view._drag_handle_index = 2
        view.update_drag_handle_positions(
            [0.0, 0.0, 80.0, 0.0, 80.0, 50.0, 0.0, 40.0], "a1"
        )
        self.assertTrue(_path_has_curve(item.path()))
        self.assertEqual(ann.position, original_position)

    def test_cloud_resize_preview_from_midpoint_keeps_cloud_silhouette(self):
        view, ann, item = self._make_area_annotation_resize_view("cloud")
        original_position = list(ann.position)
        self.assertTrue(_path_has_curve(item.path()))
        view._drag_handle_index = 5
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 0.0, 70.0, 50.0, -10.0, 50.0], "a1"
        )
        self.assertTrue(_path_has_curve(item.path()))
        self.assertEqual(ann.position, original_position)

    def test_polygon_point_edit_cannot_create_self_intersection(self):
        view, _ann, item = self._make_area_annotation_resize_view("polygon")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        view._drag_handle_index = 1
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)

    def test_cloud_point_edit_cannot_create_self_intersection(self):
        view, _ann, item = self._make_area_annotation_resize_view("cloud")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        view._drag_handle_index = 1
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)
        self.assertTrue(_path_has_curve(item.path()))

    def test_polygon_corner_resize_cannot_create_invalid_geometry(self):
        view, _ann, item = self._make_area_annotation_resize_view("polygon")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        view._drag_handle_index = 2
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)

    def test_cloud_midpoint_resize_cannot_create_invalid_geometry(self):
        view, _ann, item = self._make_area_annotation_resize_view("cloud")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        view._drag_handle_index = 5
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)
        self.assertTrue(_path_has_curve(item.path()))

    def test_valid_polygon_and_cloud_edits_update_last_valid_geometry(self):
        valid_pos = [0.0, 0.0, 80.0, 0.0, 80.0, 50.0, 0.0, 40.0]
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view, _ann, item = self._make_area_annotation_resize_view(
                    annotation_type
                )
                original_bounds = item.path().boundingRect()
                view._drag_handle_index = 2
                view.update_drag_handle_positions(valid_pos, "a1")
                self.assertEqual(view._drag_last_valid_new_pos, valid_pos)
                self.assertNotEqual(item.path().boundingRect(), original_bounds)

    def test_polygon_resize_preview_stays_straight_polygon(self):
        view, ann, item = self._make_area_annotation_resize_view("polygon")
        original_position = list(ann.position)
        self.assertFalse(_path_has_curve(item.path()))
        view._drag_handle_index = 2
        view.update_drag_handle_positions(
            [0.0, 0.0, 80.0, 0.0, 80.0, 50.0, 0.0, 40.0], "a1"
        )
        self.assertFalse(_path_has_curve(item.path()))
        self.assertEqual(ann.position, original_position)

    def test_cancel_resize_restores_original_pattern_items(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        original_bounds = main_item.path().boundingRect()
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_paths = {
            id(item): QPainterPath(item.path()) for item in view._uid_to_items["t1"]
        }
        view._drag_uid_orig_items = {"t1": list(view._uid_to_items["t1"])}
        view.update_drag_handle_positions(
            [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0], "t1"
        )
        new_pattern = view._uid_to_items["t1"][1]
        view._clear_drag_tracking(restore_preview=True)
        self.assertIsNone(new_pattern.scene())
        self.assertIs(old_pattern.scene(), view._scene)
        self.assertEqual(view._uid_to_items["t1"], [main_item, old_pattern])
        self.assertEqual(main_item.path().boundingRect(), original_bounds)


class AnnotationPlacementTests(unittest.TestCase):
    def setUp(self):
        _app()

    def test_dimension_annotation_preview_uses_live_dimension_label(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("dimension"))
        view._annotation_place_points = [(0.0, 0.0)]
        view.update_annotation_place_preview(QtCore.QPointF(255.0, 0.0))
        labels = [
            item
            for item in view._place_preview_items
            if isinstance(item, QGraphicsTextItem)
        ]
        paths = _preview_paths(view)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].path().elementCount(), 6)
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0].toPlainText(), "21' - 3\"")
        view.update_annotation_place_preview(QtCore.QPointF(18.0, 0.0))
        labels = [
            item
            for item in view._place_preview_items
            if isinstance(item, QGraphicsTextItem)
        ]
        self.assertEqual(labels[0].toPlainText(), "1' - 6\"")

    def test_dimension_annotation_commit_and_cancel_clear_preview(self):
        view = AnnotationPlacementHarness()
        view._enter_annotation_place_mode("dimension")
        view._annotation_place_points = [(0.0, 0.0)]
        view.update_annotation_place_preview(QtCore.QPointF(12.0, 0.0))
        self.assertTrue(view._place_preview_items)
        self.assertTrue(
            view._commit_annotation_placement("dimension", [0.0, 0.0, 12.0, 0.0])
        )
        self.assertEqual(
            view.annotation_created.emitted,
            [("dimension", [0.0, 0.0, 12.0, 0.0], "page-1")],
        )
        self.assertEqual(view._place_preview_items, [])
        view._enter_annotation_place_mode("dimension")
        view._annotation_place_points = [(0.0, 0.0)]
        view.update_annotation_place_preview(QtCore.QPointF(12.0, 0.0))
        view._exit_annotation_place_mode()
        self.assertEqual(view._annotation_place_type, None)
        self.assertEqual(view._place_preview_items, [])

    def test_polygon_and_cloud_creation_rejects_self_intersection(self):
        invalid_position = [0.0, 0.0, 12.0, 8.0, 12.0, 0.0, 0.0, 8.0]
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = AnnotationPlacementHarness()
                self.assertFalse(
                    view._commit_annotation_placement(
                        annotation_type, list(invalid_position)
                    )
                )
                self.assertEqual(view.annotation_created.emitted, [])

    def test_polygon_and_cloud_simple_click_starts_click_point_placement(self):
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                press = _PlacementMouseEvent(1, 2)
                release = _PlacementMouseEvent(1, 2)
                self.assertTrue(view.handle_annotation_place_press(press))
                self.assertTrue(view.handle_annotation_place_release(release))
                self.assertEqual(view._annotation_place_points, [(1.0, 2.0)])
                self.assertFalse(view._annotation_area_rect_dragging)
                self.assertEqual(view.annotation_created.emitted, [])
                self.assertEqual(view.area_progress_states, [True])
                view._exit_annotation_place_mode()
                self.assertEqual(view.area_progress_states, [True, False])

    def test_polygon_and_cloud_click_drag_creates_area_like_rectangle(self):
        for annotation_type in ("polygon", "cloud"):
            set_annotation_style_for_tool(
                annotation_type, color="#336699", line_width=7.0
            )
        try:
            for annotation_type in ("polygon", "cloud"):
                with self.subTest(annotation_type=annotation_type):
                    view = AnnotationPlacementHarness()
                    self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                    press = _PlacementMouseEvent(0, 0)
                    release = _PlacementMouseEvent(10, 8)
                    self.assertTrue(view.handle_annotation_place_press(press))
                    self.assertTrue(view._annotation_area_rect_dragging)
                    view.update_annotation_place_preview(QtCore.QPointF(10.0, 8.0))
                    paths = _preview_paths(view)
                    self.assertTrue(paths)
                    bounds = paths[0].path().boundingRect()
                    if annotation_type == "cloud":
                        self.assertTrue(
                            bounds.contains(QtCore.QRectF(0.0, 0.0, 10.0, 8.0))
                        )
                    else:
                        self.assertEqual(bounds, QtCore.QRectF(0.0, 0.0, 10.0, 8.0))
                    self.assertEqual(paths[0].pen().color().name(), "#336699")
                    self.assertEqual(paths[0].pen().widthF(), 7.0)
                    self.assertEqual(
                        _path_has_curve(paths[0].path()),
                        annotation_type == "cloud",
                    )
                    self.assertTrue(view.handle_annotation_place_release(release))
                    self.assertEqual(
                        view.annotation_created.emitted,
                        [
                            (
                                annotation_type,
                                [0.0, 0.0, 10.0, 0.0, 10.0, 8.0, 0.0, 8.0],
                                "page-1",
                            )
                        ],
                    )
                    self.assertEqual(view._annotation_place_points, [])
                    self.assertFalse(view._annotation_area_rect_dragging)
                    self.assertEqual(view._annotation_place_type, annotation_type)
                    self.assertEqual(view.area_progress_states, [])
        finally:
            for annotation_type in ("polygon", "cloud"):
                set_annotation_style_for_tool(
                    annotation_type, color="#ff0000", line_width=4.0
                )

    def test_area_takeoff_click_drag_rectangle_placement_is_unchanged(self):
        view = AreaPlacementHarness()
        press = _PlacementMouseEvent(0, 0)
        release = _PlacementMouseEvent(10, 8)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view._place_points, [(0.0, 0.0)])
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.selection_updates, 1)
        self.assertTrue(view.handle_place_release_area(release))
        self.assertTrue(release.accepted)
        self.assertEqual(
            view.takeoff_created.emitted,
            [("area", [0.0, 0.0, 10.0, 0.0, 10.0, 8.0, 0.0, 8.0], "page-1")],
        )
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.snap_invalidations, 1)

    def test_area_takeoff_simple_click_starts_point_placement_lock(self):
        view = AreaPlacementHarness()
        press = _PlacementMouseEvent(0, 0)
        release = _PlacementMouseEvent(0, 0)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_area(release))
        self.assertTrue(release.accepted)
        self.assertEqual(view.takeoff_created.emitted, [])
        self.assertEqual(view._place_points, [(0.0, 0.0)])
        self.assertFalse(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [True])
        view._reset_place_session_state()
        self.assertEqual(view.area_progress_states, [True, False])

    def test_backout_click_drag_rectangle_does_not_enter_placement_lock(self):
        view = AreaPlacementHarness()
        view.enable_backout_placement()
        press = _PlacementMouseEvent(0, 0)
        release = _PlacementMouseEvent(10, 8)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_area(release))
        self.assertEqual(
            view.hole_created.emitted,
            [
                (
                    "area",
                    [0.0, 0.0, 10.0, 0.0, 10.0, 8.0, 0.0, 8.0],
                    "page-1",
                    "parent",
                )
            ],
        )
        self.assertEqual(view._place_points, [])
        self.assertFalse(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.snap_invalidations, 1)

    def test_backout_simple_click_starts_point_placement_lock(self):
        view = AreaPlacementHarness()
        view.enable_backout_placement()
        press = _PlacementMouseEvent(0, 0)
        release = _PlacementMouseEvent(0, 0)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_area(release))
        self.assertEqual(view.hole_created.emitted, [])
        self.assertEqual(view._place_points, [(0.0, 0.0)])
        self.assertFalse(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [True])
        view._reset_place_session_state()
        self.assertEqual(view.area_progress_states, [True, False])

    def test_linear_takeoff_click_drag_does_not_enter_area_placement_lock(self):
        view = AreaPlacementHarness()
        view._place_session_uid = "linear"
        view._current_conditions = {
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            )
        }
        press = _PlacementMouseEvent(1, 2)
        release = _PlacementMouseEvent(13, 14)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_linear_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_linear(release))
        self.assertEqual(
            view.takeoff_created.emitted,
            [("linear", [1.0, 2.0, 13.0, 14.0], "page-1")],
        )
        self.assertFalse(view._place_linear_dragging)
        self.assertEqual(view._place_points, [])
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.snap_invalidations, 1)

    def test_drag_annotation_tools_use_press_drag_release_positions(self):
        expected_positions = {
            "line": [1.0, 2.0, 13.0, 14.0],
            "arrow": [1.0, 2.0, 13.0, 14.0],
            "rect": [1.0, 2.0, 13.0, 14.0],
            "oval": [1.0, 2.0, 13.0, 14.0],
            "highlight": [1.0, 2.0, 13.0, 14.0],
            "text": [7.0, 8.0, 12.0, 12.0],
            "namedview": [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
        }
        for annotation_type, expected_position in expected_positions.items():
            with self.subTest(annotation_type=annotation_type):
                view = AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                press = _PlacementMouseEvent(1, 2)
                release = _PlacementMouseEvent(13, 14)
                self.assertTrue(view.handle_annotation_place_press(press))
                self.assertTrue(press.accepted)
                self.assertEqual(view._annotation_place_points, [(1.0, 2.0)])
                self.assertTrue(view._annotation_place_dragging)
                self.assertTrue(view.handle_annotation_place_release(release))
                self.assertTrue(release.accepted)
                if annotation_type == "text":
                    self.assertEqual(view.annotation_created.emitted, [])
                    self.assertEqual(view.text_drafts, [(expected_position, "page-1")])
                elif annotation_type == "namedview":
                    self.assertEqual(view.annotation_created.emitted, [])
                    self.assertEqual(
                        view.named_view_drafts, [(expected_position, "page-1")]
                    )
                else:
                    self.assertEqual(
                        view.annotation_created.emitted,
                        [(annotation_type, expected_position, "page-1")],
                    )
                self.assertEqual(view._annotation_place_points, [])
                self.assertFalse(view._annotation_place_dragging)
                self.assertEqual(view._annotation_place_type, annotation_type)
                self.assertEqual(view.area_progress_states, [])

    def test_named_view_single_click_does_not_create_draft(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("namedview"))
        press = _PlacementMouseEvent(1, 2)
        release = _PlacementMouseEvent(1, 2)
        self.assertTrue(view.handle_annotation_place_press(press))
        self.assertTrue(view.handle_annotation_place_release(release))
        self.assertEqual(view.named_view_drafts, [])
        self.assertEqual(view._annotation_place_points, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertEqual(view._annotation_place_type, "namedview")

    def test_hotlink_annotation_tool_requests_named_view_selection_on_press(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        press = _PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_press(press))
        self.assertTrue(press.accepted)
        self.assertEqual(
            view.hotlink_placement_requested.emitted,
            [([9.0, 11.0], "page-1")],
        )
        self.assertEqual(view.annotation_created.emitted, [])
        self.assertEqual(view._selected_uids, set())
        self.assertEqual(view._annotation_place_type, "hotlink")

    def test_hotlink_annotation_release_consumes_placement_gesture(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        press = _PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_press(press))
        release = _PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_release(release))
        self.assertTrue(release.accepted)
        second_release = _PlacementMouseEvent(9, 11)
        self.assertFalse(view.handle_annotation_place_release(second_release))
        self.assertFalse(second_release.accepted)

    def test_hotlink_annotation_release_survives_tool_reactivation_after_dialog(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        self.assertTrue(view.handle_annotation_place_press(_PlacementMouseEvent(9, 11)))
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        release = _PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_release(release))
        self.assertTrue(release.accepted)

    def test_point_annotation_pending_release_is_cleared_when_exiting_tool(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        self.assertTrue(view.handle_annotation_place_press(_PlacementMouseEvent(9, 11)))
        view._exit_annotation_place_mode()
        release = _PlacementMouseEvent(9, 11)
        self.assertFalse(view.handle_annotation_place_release(release))
        self.assertFalse(release.accepted)

    def test_point_annotation_pending_release_is_cleared_when_switching_tool(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        self.assertTrue(view.handle_annotation_place_press(_PlacementMouseEvent(9, 11)))
        self.assertTrue(view._enter_annotation_place_mode("rect"))
        release = _PlacementMouseEvent(9, 11)
        self.assertFalse(view.handle_annotation_place_release(release))
        self.assertFalse(release.accepted)

    def test_ink_annotation_uses_freehand_drag_preview_and_commit(self):
        set_annotation_style_for_tool("ink", color="#224466", line_width=6.0)
        try:
            view = AnnotationPlacementHarness()
            self.assertTrue(view._enter_annotation_place_mode("ink"))
            press = _PlacementMouseEvent(1, 2)
            release = _PlacementMouseEvent(9, 10)
            self.assertTrue(view.handle_annotation_place_press(press))
            self.assertTrue(view._annotation_place_dragging)
            self.assertEqual(view._annotation_place_points, [(1.0, 2.0)])
            view.update_annotation_place_preview(QtCore.QPointF(5.0, 7.0))
            paths = _preview_paths(view)
            self.assertEqual(len(paths), 1)
            path = paths[0].path()
            self.assertEqual(path.elementCount(), 2)
            self.assertEqual((path.elementAt(0).x, path.elementAt(0).y), (1.0, 2.0))
            self.assertEqual((path.elementAt(1).x, path.elementAt(1).y), (5.0, 7.0))
            self.assertEqual(paths[0].pen().color().name(), "#224466")
            self.assertEqual(paths[0].pen().widthF(), 6.0)
            self.assertTrue(view.handle_annotation_place_release(release))
            self.assertEqual(
                view.annotation_created.emitted,
                [("ink", [1.0, 2.0, 5.0, 7.0, 9.0, 10.0], "page-1")],
            )
            self.assertEqual(view._annotation_place_points, [])
        finally:
            set_annotation_style_for_tool("ink", color="#ff0000", line_width=4.0)

    def test_tiny_ink_annotation_drag_does_not_persist(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("ink"))
        self.assertTrue(view.handle_annotation_place_press(_PlacementMouseEvent(1, 2)))
        self.assertTrue(
            view.handle_annotation_place_release(_PlacementMouseEvent(1, 2))
        )
        self.assertEqual(view.annotation_created.emitted, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertEqual(view._annotation_place_points, [])

    def test_arrow_preview_preserves_start_to_head_direction(self):
        view = AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("arrow"))
        view._annotation_place_points = [(1.0, 2.0)]
        view.update_annotation_place_preview(QtCore.QPointF(13.0, 14.0))
        paths = _preview_paths(view)
        self.assertEqual(len(paths), 1)
        path = paths[0].path()
        self.assertGreater(path.elementCount(), 2)
        self.assertEqual((path.elementAt(0).x, path.elementAt(0).y), (1.0, 2.0))
        self.assertEqual((path.elementAt(1).x, path.elementAt(1).y), (13.0, 14.0))

    def test_box_annotation_previews_use_drag_bounds(self):
        for annotation_type in ("rect", "oval", "text", "highlight"):
            with self.subTest(annotation_type=annotation_type):
                view = AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                view._annotation_place_points = [(1.0, 2.0)]
                view.update_annotation_place_preview(QtCore.QPointF(13.0, 14.0))
                paths = _preview_paths(view)
                self.assertEqual(len(paths), 1)
                drag_bounds = QtCore.QRectF(1, 2, 12, 12)
                if annotation_type == "highlight":
                    self.assertTrue(
                        paths[0].path().boundingRect().contains(drag_bounds)
                    )
                else:
                    self.assertEqual(paths[0].path().boundingRect(), drag_bounds)
                if annotation_type == "text":
                    self.assertEqual(
                        paths[0].pen().style(), QtCore.Qt.PenStyle.DashLine
                    )
                elif annotation_type == "highlight":
                    self.assertEqual(paths[0].pen().style(), QtCore.Qt.PenStyle.NoPen)
                    self.assertEqual(paths[0].brush().color().alpha(), 255)
                    self.assertFalse(_path_has_curve(paths[0].path()))
                else:
                    self.assertEqual(
                        paths[0].pen().style(), QtCore.Qt.PenStyle.SolidLine
                    )

    def test_polygon_and_cloud_annotations_use_area_like_multi_point_completion(self):
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                first_press = _PlacementMouseEvent(0, 0)
                first_release = _PlacementMouseEvent(0, 0)
                self.assertTrue(view.handle_annotation_place_press(first_press))
                self.assertTrue(view.handle_annotation_place_release(first_release))
                self.assertEqual(view.area_progress_states, [True])
                for point in ((12, 0), (6, 8)):
                    self.assertTrue(
                        view.handle_annotation_place_press(
                            _PlacementMouseEvent(point[0], point[1])
                        )
                    )
                self.assertEqual(
                    view._annotation_place_points,
                    [(0.0, 0.0), (12.0, 0.0), (6.0, 8.0)],
                )
                view.update_annotation_place_preview(QtCore.QPointF(1.0, 1.0))
                paths = _preview_paths(view)
                self.assertTrue(paths)
                if annotation_type == "cloud":
                    self.assertTrue(_path_has_curve(paths[0].path()))
                else:
                    self.assertFalse(_path_has_curve(paths[0].path()))
                self.assertTrue(
                    view.handle_annotation_place_press(_PlacementMouseEvent(1, 1))
                )
                self.assertEqual(
                    view.annotation_created.emitted,
                    [
                        (
                            annotation_type,
                            [0.0, 0.0, 12.0, 0.0, 6.0, 8.0],
                            "page-1",
                        )
                    ],
                )
                self.assertEqual(view._annotation_place_points, [])
                self.assertEqual(view.area_progress_states, [True, False])

    def test_polygon_and_cloud_placement_lock_clears_when_switching_tools(self):
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                self.assertTrue(
                    view.handle_annotation_place_press(_PlacementMouseEvent(1, 2))
                )
                self.assertTrue(
                    view.handle_annotation_place_release(_PlacementMouseEvent(1, 2))
                )
                self.assertEqual(view.area_progress_states, [True])
                self.assertTrue(view._enter_annotation_place_mode("rect"))
                self.assertEqual(view.area_progress_states, [True, False])
                self.assertEqual(view._annotation_place_type, "rect")


if __name__ == "__main__":
    unittest.main()
