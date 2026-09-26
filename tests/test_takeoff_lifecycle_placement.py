import math
import unittest
from types import SimpleNamespace
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components import placement_mode
from tests.test_plan_view_snap_helper import PreviewHarness
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView


class TakeoffLifecyclePlacementTests(unittest.TestCase):
    def test_legacy_parented_point_and_linear_paste_use_their_own_geometry(self):
        from ost_visualizer.presentation.visualization.core.geometry import (
            ost_linear_geom,
        )

        for family, position, curve in (
            (Condition.TYPE_COUNT, [5, 5], -1),
            (Condition.TYPE_LINEAR, [2, 2, 6, 2], -1),
            (Condition.TYPE_LINEAR, [3, 3, 7, 3, 5, 3, 1], 0),
        ):
            with self.subTest(family=family, curve=curve):
                view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
                view._linear_geom = ost_linear_geom
                condition = Condition(
                    uid="legacy", condition_type=family, width=1, depth=1
                )
                view._paste_backout_sources = [
                    {
                        "uid": "source",
                        "parent_uid": "old",
                        "condition": condition,
                        "position": position,
                        "rotation": 0,
                        "curve": curve,
                    }
                ]
                self.assertEqual(
                    view._paste_backout_validate_all([position]),
                    ([("parent", True)], True),
                )
                view._paste_backout_group_centroid = (0, 0)
                view._scene_pos_to_ost = lambda point: point
                view.snap_ost = float
                translated = view._paste_backout_compute_translations(QPointF(1, 2))[0]
                self.assertEqual(len(translated), len(position))
                if len(position) % 2:
                    self.assertEqual(translated[-1], position[-1])

    def test_attachment_only_paste_keeps_full_rotated_footprint(self):
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
            rotation=math.pi / 2,
        )
        self.assertTrue(
            TakeoffPlanView.begin_paste_backout(view, [attachment], {}, "7")
        )
        self.assertEqual(
            view._paste_backout_validate_all([[5, 5]]), ([("parent", True)], True)
        )
        self.assertEqual(
            view._paste_backout_validate_all([[5, 9]]), ([("", False)], False)
        )

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

    def release(self, view, family):
        event = SimpleNamespace(position=lambda: QPointF(), accept=lambda: None)
        if family == Condition.TYPE_AREA:
            view.handle_place_release_area(event)
        else:
            view.handle_place_release_linear(event)

    def test_minimum_fractional_linear_and_area_release_preserves_preview(self):
        for family in (Condition.TYPE_LINEAR, Condition.TYPE_AREA):
            for direction in (-1, 1):
                with self.subTest(family=family, direction=direction):
                    start = (0.3, 0.3) if direction < 0 else (0.2, 0.2)
                    end = (0.2, 0.2) if direction < 0 else (0.3, 0.3)
                    if family == Condition.TYPE_LINEAR:
                        end = (end[0], start[1])
                    view = self.harness(family, start, end)
                    view.update_place_preview(QPointF())
                    self.assertTrue(view._place_preview_items)
                    self.release(view, family)
                    expected = (
                        [*start, *end]
                        if family == Condition.TYPE_LINEAR
                        else [
                            start[0],
                            start[1],
                            end[0],
                            start[1],
                            *end,
                            start[0],
                            end[1],
                        ]
                    )
                    self.assertEqual([args[1] for args in view.created], [expected])

    def test_backout_release_without_mouse_move_accepts_minimum_fractional_size(self):
        view = self.harness(Condition.TYPE_AREA, (0.2, 0.2), (0.3, 0.3), backout=True)
        self.release(view, Condition.TYPE_AREA)
        self.assertEqual(len(view.created), 1)

    def test_subminimum_geometry_does_not_commit(self):
        for family in (Condition.TYPE_LINEAR, Condition.TYPE_AREA):
            with self.subTest(family=family):
                view = self.harness(family, (0.2, 0.2), (0.24, 0.24))
                self.release(view, family)
                self.assertEqual(view.created, [])

    def test_subminimum_backout_preview_cannot_be_committed_as_last_valid(self):
        view = self.harness(Condition.TYPE_AREA, (0.2, 0.2), (0.24, 0.24), backout=True)
        view.update_place_preview(QPointF())
        self.release(view, Condition.TYPE_AREA)
        self.assertEqual(view.created, [])

    def test_paste_backout_checks_all_overlapping_candidate_parents(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        view._current_takeoffs["parent"].position = [4, 4, 6, 4, 6, 6, 4, 6]
        view._current_takeoffs["large"] = Takeoff(
            uid="large",
            condition_uid="tool",
            page_uid=view._current_bid_page_uid,
            position=[0, 0, 10, 0, 10, 10, 0, 10],
        )
        results, valid = view._paste_backout_validate_all([[3, 3, 7, 3, 7, 7, 3, 7]])
        self.assertTrue(valid)
        self.assertEqual(results, [("large", True)])

    def test_concave_backout_paste_does_not_require_vertex_average_inside_parent(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        view._current_takeoffs["parent"].position = [
            0,
            0,
            10,
            0,
            10,
            2,
            2,
            2,
            2,
            10,
            0,
            10,
        ]
        candidate = [0.2, 0.2, 9.8, 0.2, 9.8, 1.8, 1.8, 1.8, 1.8, 9.8, 0.2, 9.8]
        self.assertEqual(
            view._paste_backout_validate_all([candidate]), ([("parent", True)], True)
        )

    def test_pasted_backouts_must_not_collide_with_each_other(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        candidates = [[1, 1, 5, 1, 5, 5, 1, 5], [3, 3, 7, 3, 7, 7, 3, 7]]
        _results, valid = view._paste_backout_validate_all(candidates)
        self.assertFalse(valid)

    def test_child_only_paste_retains_nested_source_parent(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        view._paste_backout_sources = [
            {"uid": "child", "parent_uid": "source-root"},
            {"uid": "source-root", "parent_uid": "not-copied"},
        ]
        candidates = [[2, 2, 3, 2, 3, 3, 2, 3], [1, 1, 9, 1, 9, 9, 1, 9]]
        self.assertEqual(
            view._paste_backout_validate_all(candidates),
            ([("source-root", True), ("parent", True)], True),
        )
