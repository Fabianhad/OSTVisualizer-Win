import math
import unittest
from types import SimpleNamespace
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components import placement_mode
from tests.presentation.components.plan_view.components.snap_support import (
    PreviewHarness,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView


class TakeoffLifecyclePlacementTests(unittest.TestCase):
    def _attachment_paste_view(self, rotation):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        condition = Condition(
            uid="attachment",
            condition_type=Condition.TYPE_ATTACHMENT,
            width=4,
            depth=2,
            shape=3,
        )
        view._current_conditions[condition.uid] = condition
        view._editing_enabled = True
        view.cancel_overlay_move_mode = lambda **_: None
        view._remove_rotate_handle = lambda: None
        view.finish_intelligent_paste_placement = lambda: None
        view._exit_place_mode = lambda: None
        view._exit_annotation_place_mode = lambda: None
        view._clear_backout_state = lambda: None
        view._apply_cursor_mode = lambda _: None
        view.cursor_mode_change_requested = SimpleNamespace(emit=lambda _: None)
        view._last_mouse_vp_pos = None
        attachment = Takeoff(
            uid="source",
            condition_uid=condition.uid,
            parent_uid="old-parent",
            position=[5, 5],
            rotation=rotation,
        )
        self.assertTrue(
            TakeoffPlanView.begin_paste_backout(view, [attachment], {}, "7")
        )
        return view

    def test_attachment_only_paste_keeps_full_rotated_footprint(self):
        # Parent is the 10 x 10 square at the origin. The attachment is 4 wide
        # (x, half 2) by 2 deep (y, half 1) before rotation; a quarter turn swaps
        # the half extents. A footprint corner/edge outside the parent rejects.
        accepted = ([("parent", True)], True)
        rejected = ([("", False)], False)
        for rotation, centre, expected in (
            (math.pi / 2, [5, 5], accepted),
            (math.pi / 2, [5, 9], rejected),  # y spans 7..11 once rotated
            (math.pi / 2, [9, 5], accepted),  # x spans 8..10 once rotated
            (math.pi / 2, [9.5, 5], rejected),
            (0, [5, 9], accepted),  # y spans 8..10 unrotated
            (0, [9, 5], rejected),  # x spans 7..11 unrotated
            (0, [5, 9.5], rejected),
        ):
            with self.subTest(rotation=rotation, centre=centre):
                view = self._attachment_paste_view(rotation)
                self.assertEqual(view._paste_backout_validate_all([centre]), expected)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def harness(self, family, start, end, *, backout=False):
        view = PreviewHarness()
        view._paste_backout_sources = []
        cs = view._scene_builder.get_coordinate_system()
        cs.parse_position = list
        view._scene_builder = SimpleNamespace(get_coordinate_system=lambda: cs)
        view._current_conditions["tool"] = Condition(uid="tool", condition_type=family)
        view._place_session_uid = "tool"
        view._current_color_map["tool"] = ("#808080", 1.0)
        view._snap_increments = 0.1
        view._place_points = [start]
        view._place_area_rect_dragging = family == Condition.TYPE_AREA
        view._place_linear_dragging = family == Condition.TYPE_LINEAR
        view._area_in_progress = False
        view.area_placement_in_progress = SimpleNamespace(emit=lambda *_: None)
        view._linear_geom = SimpleNamespace(
            calc_chord_length=lambda x1, y1, x2, y2: math.hypot(x2 - x1, y2 - y1)
        )
        view.snap_result = (*end, *end, placement_mode.GRID)
        view.mapToScene = lambda point: QPointF(point)
        view._snap_angle_for_placement = lambda _x, _y, x, y, _kind: (x, y)
        view.created = []
        view.takeoff_created = SimpleNamespace(
            emit=lambda *args: view.created.append(args)
        )
        view.hole_created = view.takeoff_created
        if backout:
            view._backout_parent_uid = "parent"
            view._backout_active_uid = "tool"
            view._current_takeoffs["parent"] = Takeoff(
                uid="parent",
                condition_uid="tool",
                page_uid=view._current_bid_page_uid,
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            )
            view.is_inside_parent = lambda x, y: 0 <= x <= 10 and 0 <= y <= 10
        return view
