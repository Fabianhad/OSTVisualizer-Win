import unittest
from types import SimpleNamespace
from PySide6 import QtCore
from PySide6.QtCore import Qt
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)


class BaseKeyHandler:
    def keyReleaseEvent(self, _event):
        pass


class InputHandlerHarness(InputHandlerMixin, DragHandlerMixin, BaseKeyHandler):
    pass


class FakeMouseEvent:
    def __init__(self, modifiers=Qt.KeyboardModifier.NoModifier, x=10, y=10):
        self._modifiers = modifiers
        self._point = QtCore.QPoint(x, y)
        self.accepted = False

    def button(self):
        return Qt.MouseButton.LeftButton

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


class CtrlDragTests(unittest.TestCase):
    def _make_view(self, selected_uids=None):
        view = InputHandlerHarness()
        view._cursor_mode = "select"
        view._selection_enabled = True
        view._ctrl_held = False
        view._zoom_press_ctrl = False
        view._select_band_origin = None
        view._select_band_active = False
        view._select_band_dragged = False
        view._press_changed_selection = False
        view._rotation_drag_active = False
        view._drag_takeoff_uid = None
        view._drag_handle_index = -2
        view._drag_orig_position = []
        view._drag_handle_corner_count = 0
        view._drag_item_orig_positions = {}
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._selected_uids = set(selected_uids or {"t1"})
        view._handle_infos = []
        view._selection_items = []
        view._current_takeoffs = {
            "t1": SimpleNamespace(position=[0.0, 0.0, 10.0, 0.0], condition_uid="c"),
            "t2": SimpleNamespace(position=[20.0, 0.0, 30.0, 0.0], condition_uid="c"),
        }
        view._current_annotations = {}
        view._current_conditions = {}
        view._uid_to_items = {"t1": [FakeItem(1.0, 2.0)], "t2": [FakeItem(3.0, 4.0)]}
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

    def test_ctrl_left_press_uses_zoom_even_if_cached_ctrl_state_is_false(self):
        view = self._make_view()
        event = FakeMouseEvent(Qt.KeyboardModifier.ControlModifier)
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertTrue(view._zoom_press_ctrl)
        self.assertIsNone(view._drag_takeoff_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertEqual(view._drag_item_orig_positions, {})

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


if __name__ == "__main__":
    unittest.main()
