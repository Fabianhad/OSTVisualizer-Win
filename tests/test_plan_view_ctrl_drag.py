import math
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.domain.entities import pattern as pattern_values
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    format_dimension_distance,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class BaseKeyHandler:
    def keyReleaseEvent(self, _event):
        pass

    def mouseMoveEvent(self, _event):
        pass


class InputHandlerHarness(
    InputHandlerMixin, DragHandlerMixin, SelectionManagerMixin, BaseKeyHandler
):
    def __init__(self):
        self.selected_text_annotation_uids = []
        self.editing_text_annotation_uids = []
        self.editing_named_view_uids = []
        self._editing_text_annotation_uid = None
        self._editing_named_view_uid = None

    def _condition_text_label_at(self, _vp_pos):
        return None

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

    def _finish_active_inline_text_edit(self, _commit):
        pass

    def _active_inline_text_editor_contains_scene_point(self, _scene_pos):
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


class FakeKeyEvent:
    def __init__(self, key=Qt.Key.Key_Control):
        self._key = key

    def key(self):
        return self._key

    def isAutoRepeat(self):
        return False


class FakeSignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


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

    def data(self, role):
        return self._uid if role == 0 else None

    def scene(self):
        return None


class FakeCoordinateSystem:
    scale_ratio = 1.0
    view_scale = 1.0

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


class CtrlDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

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
        view._panning = False
        view._right_pan_active = False
        view._last_pan_point = None
        view._drag_takeoff_uid = None
        view._drag_handle_index = -2
        view._drag_orig_position = []
        view._drag_handle_corner_count = 0
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._selected_uids = set({"t1"} if selected_uids is None else selected_uids)
        view._handle_infos = []
        view._selection_items = []
        view._current_takeoffs = {
            "t1": SimpleNamespace(position=[0.0, 0.0, 10.0, 0.0], condition_uid="c"),
            "t2": SimpleNamespace(position=[20.0, 0.0, 30.0, 0.0], condition_uid="c"),
        }
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_conditions = {}
        view._uid_to_items = {"t1": [FakeItem(1.0, 2.0)], "t2": [FakeItem(3.0, 4.0)]}
        view._takeoff_items = []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        view.find_takeoff_at = lambda _scene_pos: "t1"
        view.find_takeoffs_at = lambda _scene_pos: ["t1"]
        view._flush_dirty_positions = lambda: None
        view.update_selection_visuals = lambda *args, **kwargs: None
        view._rubber_band_origin = None
        view._rubber_band = None
        view._update_cursor = lambda *args, **kwargs: None
        return view

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
        view.find_takeoff_at = lambda _scene_pos: None
        view.find_takeoffs_at = lambda _scene_pos: []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        return view

    def _make_selected_path_takeoff_view(self):
        view = self._make_view({"t1"})
        view._scene = QGraphicsScene()
        view._annotation_only_selection = False
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
        self.assertIsNone(view._drag_takeoff_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_single_click_hotlink_does_not_select_it(self):
        view = self._make_hotlink_view(selected=False)
        view.find_takeoff_at = lambda _scene_pos: "h1"
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._selected_uids, set())
        self.assertIsNone(view._drag_takeoff_uid)

    def test_selected_hotlink_center_press_starts_drag(self):
        view = self._make_hotlink_view(selected=True)
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._drag_takeoff_uid, "h1")
        self.assertEqual(view._drag_orig_position, [10.0, 10.0])
        self.assertEqual(view._drag_handle_index, -1)

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
        self.assertEqual(view._drag_takeoff_uid, "h1")
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

    def test_selected_takeoff_hover_far_away_does_not_use_move_cursor(self):
        view = self._make_selected_path_takeoff_view()
        cursor = view._resolve_select_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(cursor, Qt.CursorShape.ArrowCursor)

    def test_selected_takeoff_hover_on_hit_area_uses_move_cursor(self):
        view = self._make_selected_path_takeoff_view()
        cursor = view._resolve_select_cursor(QtCore.QPoint(5, 5))
        self.assertEqual(cursor, Qt.CursorShape.SizeAllCursor)

    def test_stale_move_drag_index_does_not_force_move_cursor_without_active_press(
        self,
    ):
        view = self._make_selected_path_takeoff_view()
        view._drag_handle_index = -1
        cursor = view._resolve_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(cursor, Qt.CursorShape.ArrowCursor)

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
        self.assertEqual(view._drag_takeoff_uid, "t1")
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
        self.assertIsNone(view._drag_takeoff_uid)
        self.assertEqual(view._drag_orig_position, [])
        inside_press = FakeMouseEvent(x=20, y=20)
        view.mousePressEvent(inside_press)
        self.assertTrue(inside_press.accepted)
        self.assertEqual(view._drag_takeoff_uid, "a1")
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
        view._drag_takeoff_uid = "t1"
        view._drag_handle_index = -1
        view._drag_orig_position = [0.0, 0.0, 10.0, 0.0]
        view._drag_item_orig_positions = {id(overlay): overlay_orig}
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        move = FakeMouseEvent(x=200, y=200, buttons=Qt.MouseButton.NoButton)
        view.mouseMoveEvent(move)
        self.assertIsNone(view._drag_takeoff_uid)
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
        self.assertIsNone(view._drag_takeoff_uid)

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
        self.assertIsNone(view._drag_takeoff_uid)

    def test_ctrl_zoom_release_restores_temporary_overlay_and_handle_positions(self):
        view = self._make_view()
        overlay = view._uid_to_items["t1"][0]
        handle = FakeItem(5.0, 6.0)
        view._selection_items = [handle]
        overlay_orig = overlay.pos()
        handle_orig = handle.pos()
        overlay.setPos(21.0, 22.0)
        handle.setPos(25.0, 26.0)
        view._drag_takeoff_uid = "t1"
        view._drag_item_orig_positions = {
            id(overlay): overlay_orig,
            id(handle): handle_orig,
        }
        view._ctrl_held = True
        view._zoom_press_ctrl = True
        InputHandlerMixin.keyReleaseEvent(view, FakeKeyEvent())
        self.assertEqual(overlay.pos(), overlay_orig)
        self.assertEqual(handle.pos(), handle_orig)
        self.assertIsNone(view._drag_takeoff_uid)
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_multi_takeoff_drag_preview_uses_snapped_item_deltas(self):
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
            view._uid_to_items["t1"][0].pos(), QtCore.QPointF(107.0, 107.0)
        )
        self.assertEqual(
            view._uid_to_items["t2"][0].pos(), QtCore.QPointF(208.0, 208.0)
        )
        self.assertEqual(border1.pos(), QtCore.QPointF(307.0, 307.0))
        self.assertEqual(border2.pos(), QtCore.QPointF(408.0, 408.0))

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
        view._current_takeoffs["t1"].is_hole = False
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
        view._drag_takeoff_uid = "d1"
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

    def test_cancel_resize_restores_original_pattern_items(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        original_bounds = main_item.path().boundingRect()
        view._drag_takeoff_uid = "t1"
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


if __name__ == "__main__":
    unittest.main()
