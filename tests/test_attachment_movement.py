import math
import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsRectItem
from tests import test_plan_annotation_placement_keyboard as keyboard_fixtures
from tests import test_plan_view_action_handler as action_fixtures
from tests import test_plan_view_ctrl_drag as fixtures


class AttachmentMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def make_view(self):
        view = fixtures.CtrlDragTests()._make_view({"attachment"})
        view._scene_builder = fixtures.FakeSceneBuilder()
        view._scene_builder.cs = fixtures.IdentityCoordinateSystem()
        view._linear_geom = fixtures.FakeLinearGeom()
        view._rotation_before_edit = {}
        view._dirty_rotations = {}
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            ),
            "attachment": Takeoff(
                uid="attachment",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5.0, 5.0],
                area_uid="bid-area",
            ),
        }
        view._uid_to_items = {"attachment": [fixtures.FakeItem()]}
        view._handle_infos = [SimpleNamespace(item=fixtures.FakeItem(5.0, 5.0))]
        view._pt_to_scene = lambda x, y: QPointF(x, y)
        return view

    def add_backout(self, view, position):
        view._current_takeoffs["backout"] = Takeoff(
            uid="backout",
            condition_uid="area",
            page_uid="page",
            parent_uid="parent",
            position=list(position),
        )

    def set_attachment_dimensions(self, view, width, depth):
        condition = view._current_conditions["attachment"]
        condition.width = width
        condition.depth = depth

    def test_keyboard_collides_at_every_edge(self):
        for dx, dy in ((-6, 0), (6, 0), (0, -6), (0, 6)):
            with self.subTest(delta=(dx, dy)):
                view = self.make_view()
                self.assertFalse(view._apply_position_keyboard_move(dx, dy))
                self.assertEqual(
                    view._current_takeoffs["attachment"].position, [5.0, 5.0]
                )
                self.assertEqual(view._dirty_positions, {})

    def test_mouse_preview_collides_at_every_edge(self):
        for position in ([-1.0, 5.0], [11.0, 5.0], [5.0, -1.0], [5.0, 11.0]):
            with self.subTest(position=position):
                view = self.make_view()
                view._drag_last_valid_new_pos = [5.0, 5.0]
                view.update_drag_handle_positions(position, "attachment")
                self.assertEqual(view._handle_infos[0].item.pos(), QPointF(5.0, 5.0))

    def test_attachment_full_footprint_must_remain_inside_area(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)

        self.assertFalse(view._apply_position_keyboard_move(4.0, 0.0))
        self.assertEqual(view._current_takeoffs["attachment"].position, [5.0, 5.0])

    def test_concave_area_rejects_notch_not_just_bounding_box(self):
        view = self.make_view()
        view._current_takeoffs["parent"].position = [
            0.0,
            0.0,
            10.0,
            0.0,
            10.0,
            3.0,
            3.0,
            3.0,
            3.0,
            10.0,
            0.0,
            10.0,
        ]
        view._current_takeoffs["attachment"].position = [2.0, 2.0]
        self.assertFalse(view._apply_position_keyboard_move(3, 3))
        self.assertTrue(view._apply_position_keyboard_move(5, 0))
        self.assertEqual(view._current_takeoffs["attachment"].position, [7.0, 2.0])

    def test_mouse_release_outside_preserves_last_valid_position(self):
        for handle in (-1, 0):
            with self.subTest(handle=handle):
                view = self.make_view()
                view._select_band_origin = QPointF(5.0, 5.0)
                view._select_band_dragged = True
                view._drag_plan_item_uid = "attachment"
                view._drag_handle_index = handle
                view._drag_orig_position = [5.0, 5.0]
                view._drag_last_valid_new_pos = [5.0, 5.0]
                view.mapToScene = lambda point: QPointF(point)
                view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
                view.update_drag_handle_positions([8.0, 5.0], "attachment")
                view.update_drag_handle_positions([20.0, 5.0], "attachment")
                view.mouseReleaseEvent(
                    fixtures.FakeMouseEvent(x=20, y=5, buttons=Qt.MouseButton.NoButton)
                )
                self.assertEqual(
                    view._current_takeoffs["attachment"].position, [8.0, 5.0]
                )
                self.assertEqual(view._dirty_positions, {"attachment": [8.0, 5.0]})

    def test_boundary_nudge_is_consumed_without_scroll_or_dirty_state(self):
        view = self.make_view()
        view._current_takeoffs["attachment"].position = [9.0, 5.0]
        for _ in range(3):
            event = fixtures.FakeKeyEvent(Qt.Key.Key_Right)
            view.keyPressEvent(event)
            self.assertTrue(event.accepted)
        self.assertEqual(view._current_takeoffs["attachment"].position, [9.0, 5.0])
        self.assertEqual(view._dirty_positions, {})
        self.assertFalse(view._keyboard_move_dirty)

    def test_missing_wrong_page_and_non_area_parent_reject(self):
        for mutation in ("missing", "page", "condition", "backout"):
            with self.subTest(mutation=mutation):
                view = self.make_view()
                parent = view._current_takeoffs["parent"]
                if mutation == "missing":
                    del view._current_takeoffs["parent"]
                elif mutation == "page":
                    parent.page_uid = "other-page"
                elif mutation == "condition":
                    parent.condition_uid = "attachment"
                else:
                    parent.parent_uid = "another-area"
                self.assertFalse(view._apply_position_keyboard_move(1, 0))
                self.assertEqual(view._dirty_positions, {})

    def test_parent_and_attachment_move_together_without_double_translation(self):
        view = self.make_view()
        view._selected_uids = {"parent", "attachment"}
        self.assertTrue(view._apply_position_keyboard_move(100, 100))
        self.assertEqual(view._current_takeoffs["attachment"].position, [105.0, 105.0])
        self.assertEqual(view._current_takeoffs["parent"].position[:2], [100.0, 100.0])
        self.assertEqual(view._current_takeoffs["attachment"].parent_uid, "parent")
        self.assertEqual(view._current_takeoffs["attachment"].area_uid, "bid-area")

    def test_invalid_group_move_does_not_partially_move_other_items(self):
        view = self.make_view()
        view._current_conditions["count"] = Condition(
            uid="count", condition_type=Condition.TYPE_COUNT
        )
        view._current_takeoffs["count"] = Takeoff(
            uid="count", condition_uid="count", position=[50.0, 50.0]
        )
        view._selected_uids.add("count")
        self.assertFalse(view._apply_position_keyboard_move(6, 0))
        self.assertEqual(view._current_takeoffs["count"].position, [50.0, 50.0])
        self.assertEqual(view._dirty_positions, {})

    def test_parent_resize_cannot_exclude_attachment(self):
        view = self.make_view()
        self.assertFalse(
            view._validate_parent_contains_holes(
                "parent", [0.0, 0.0, 3.0, 0.0, 3.0, 3.0, 0.0, 3.0]
            )
        )
        self.assertTrue(
            view._validate_parent_contains_holes(
                "parent", [0.0, 0.0, 8.0, 0.0, 8.0, 8.0, 0.0, 8.0]
            )
        )

    def test_group_backout_move_cannot_enter_unselected_attachment(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 2.0, 2.0)
        self.add_backout(view, [1.0, 4.0, 3.0, 4.0, 3.0, 6.0, 1.0, 6.0])
        view._selected_uids = {"backout"}

        self.assertFalse(view._apply_position_keyboard_move(3.0, 0.0))
        self.assertEqual(
            view._current_takeoffs["backout"].position,
            [1.0, 4.0, 3.0, 4.0, 3.0, 6.0, 1.0, 6.0],
        )
        self.assertEqual(view._dirty_positions, {})

    def test_backout_placement_rejects_attachment_footprint(self):
        state = self.make_view()
        placement = fixtures.AnnotationPlacementHarness()
        placement._current_conditions = state._current_conditions
        placement._current_takeoffs = state._current_takeoffs
        placement._backout_parent_uid = "parent"
        placement._scene_builder._cs.parse_position = lambda position: list(position)
        self.set_attachment_dimensions(state, 2.0, 2.0)

        self.assertTrue(
            placement._check_hole_overlap([4.0, 4.0, 6.0, 4.0, 6.0, 6.0, 4.0, 6.0])
        )

    def test_backout_placement_rejects_stale_parent(self):
        state = self.make_view()
        placement = fixtures.AnnotationPlacementHarness()
        placement._current_conditions = state._current_conditions
        placement._current_takeoffs = state._current_takeoffs
        placement._scene_builder._cs.parse_position = lambda position: list(position)

        self.assertTrue(
            placement._check_hole_overlap(
                [4.0, 4.0, 6.0, 4.0, 6.0, 6.0, 4.0, 6.0],
                parent_uid="deleted-parent",
            )
        )

    def test_single_attachment_rotation_updates_rotation(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        view._rotation_drag_orig_positions = {"attachment": [5.0, 5.0]}
        view._rotation_drag_orig_rotations = {"attachment": 0.0}
        flushed = []
        view._flush_dirty_rotations = lambda: flushed.append(True)
        view._create_rotate_handle = lambda _uids: True

        view._apply_single_rotation("attachment", 90.0)

        self.assertAlmostEqual(
            view._current_takeoffs["attachment"].rotation, math.pi / 2.0
        )
        self.assertEqual(flushed, [True])

    def test_single_attachment_rotation_rejects_footprint_outside_area(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        attachment = view._current_takeoffs["attachment"]
        attachment.position = [5.0, 1.0]
        view._rotation_drag_orig_positions = {"attachment": [5.0, 1.0]}
        view._rotation_drag_orig_rotations = {"attachment": 0.0}
        flushed = []
        view._flush_dirty_rotations = lambda: flushed.append(True)
        view._create_rotate_handle = lambda _uids: True

        view._apply_single_rotation("attachment", 90.0)

        self.assertEqual(attachment.rotation, 0.0)
        self.assertEqual(view._dirty_rotations, {})
        self.assertEqual(flushed, [])

    def test_single_attachment_rotation_rejects_backout_collision(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        attachment = view._current_takeoffs["attachment"]
        attachment.position = [3.0, 5.0]
        self.add_backout(view, [2.0, 1.0, 4.0, 1.0, 4.0, 3.9, 2.0, 3.9])
        view._rotation_drag_orig_positions = {"attachment": [3.0, 5.0]}
        view._rotation_drag_orig_rotations = {"attachment": 0.0}
        view._create_rotate_handle = lambda _uids: True
        flushed = []
        view._flush_dirty_rotations = lambda: flushed.append(True)

        view._apply_single_rotation("attachment", 90.0)

        self.assertEqual(attachment.rotation, 0.0)
        self.assertEqual(view._dirty_rotations, {})
        self.assertEqual(flushed, [])

    def test_toolbar_attachment_rotation_rejects_footprint_outside_area(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        attachment = view._current_takeoffs["attachment"]
        attachment.position = [5.0, 1.0]
        view._scene_builder.cs.ost_to_screen_pixels = lambda value: float(value)
        flushed = []
        view._flush_rotation_group = lambda: flushed.append(True)

        view.rotate_selected_takeoffs(90.0)

        self.assertEqual(attachment.position, [5.0, 1.0])
        self.assertEqual(attachment.rotation, 0.0)
        self.assertEqual(view._dirty_positions, {})
        self.assertEqual(view._dirty_rotations, {})
        self.assertEqual(flushed, [])

    def test_area_rotation_rotates_attachment_footprint_with_parent(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        view._selected_uids = {"parent"}
        view._rotation_drag_orig_positions = {
            "parent": list(view._current_takeoffs["parent"].position)
        }
        view._rotation_drag_orig_rotations = {"parent": 0.0}
        view._flush_dirty_positions = lambda: None
        view._flush_rotation_group = lambda: None

        view._apply_single_rotation("parent", 90.0)

        self.assertAlmostEqual(
            view._current_takeoffs["attachment"].rotation, math.pi / 2.0
        )
        self.assertIn("attachment", view._dirty_rotations)

    def test_group_backout_rotation_cannot_enter_unselected_attachment(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 2.0, 2.0)
        original = [1.0, 4.0, 3.0, 4.0, 3.0, 6.0, 1.0, 6.0]
        self.add_backout(view, original)
        view._selected_uids = {"backout"}
        view._rotation_drag_orig_positions = {"backout": list(original)}
        view._rotation_drag_orig_rotations = {"backout": 0.0}
        view._rotate_ost_center = (3.5, 5.0)
        flushed = []
        view._flush_rotation_group = lambda: flushed.append(True)

        view._apply_multi_rotation(180.0)

        self.assertEqual(view._current_takeoffs["backout"].position, original)
        self.assertEqual(view._dirty_positions, {})
        self.assertEqual(flushed, [])

    def test_toolbar_backout_rotation_cannot_enter_unselected_attachment(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 2.0, 2.0)
        original = [2.5, 2.0, 3.5, 2.0, 3.5, 8.0, 2.5, 8.0]
        self.add_backout(view, original)
        view._selected_uids = {"backout"}
        view._scene_builder.cs.ost_to_screen_pixels = lambda value: float(value)
        flushed = []
        view._flush_rotation_group = lambda: flushed.append(True)

        view.rotate_selected_takeoffs(90.0)

        self.assertEqual(view._current_takeoffs["backout"].position, original)
        self.assertEqual(view._dirty_positions, {})
        self.assertEqual(flushed, [])

    def test_overlapping_area_parent_search_skips_area_blocked_by_backout(self):
        state = self.make_view()
        self.set_attachment_dimensions(state, 2.0, 2.0)
        self.add_backout(state, [4.0, 4.0, 6.0, 4.0, 6.0, 6.0, 4.0, 6.0])
        state._current_takeoffs["second-parent"] = Takeoff(
            uid="second-parent",
            condition_uid="area",
            page_uid="page",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
        )
        placement = fixtures.AnnotationPlacementHarness()
        placement._scene_builder._cs.parse_position = lambda position: list(position)
        placement._current_conditions = state._current_conditions
        placement._current_takeoffs = state._current_takeoffs

        self.assertEqual(
            placement._find_attachment_parent_at(
                state._current_conditions["attachment"], [5.0, 5.0]
            ),
            "second-parent",
        )

    def test_real_main_and_detached_keyboard_collision_and_flush(self):
        for detached in (False, True):
            with self.subTest(detached=detached):
                fixture = keyboard_fixtures.AnnotationPlacementKeyboardTests()
                fixture.app = self.app
                self.addCleanup(fixture.doCleanups)
                view = fixture.make_view(detached=detached)
                view.set_annotation_only_selection(False)
                state = self.make_view()
                view._current_takeoffs = state._current_takeoffs
                view._current_conditions = state._current_conditions
                item = QGraphicsRectItem(0, 0, 2, 2)
                item.setData(0, "attachment")
                view._scene.addItem(item)
                view._uid_to_items = {"attachment": [item]}
                view._selected_uids = {"attachment"}
                attachment = view._current_takeoffs["attachment"]
                attachment.position = [9.0, 5.0]
                scroll = fixture.scroll_position(view)
                changes = []
                view.positions_flushed.connect(lambda *args: changes.append(args))
                QTest.keyClick(view, Qt.Key.Key_Right)
                self.assertEqual(attachment.position, [9.0, 5.0])
                self.assertEqual(fixture.scroll_position(view), scroll)
                self.assertEqual(changes, [])
                QTest.keyClick(view, Qt.Key.Key_Left)
                self.assertEqual(attachment.position, [8.0, 5.0])
                self.assertEqual(
                    changes, [([("attachment", [9.0, 5.0], [8.0, 5.0])], [])]
                )
                self.assertEqual(fixture.scroll_position(view), scroll)

    def test_movement_history_and_backend_payload_parity(self):
        old, new = [5.0, 5.0], [8.0, 5.0]
        for sql in (False, True):
            with self.subTest(sql=sql):
                (
                    handler,
                    write,
                    undo,
                ) = action_fixtures.PlanViewActionHandlerTests()._make_group_transform_handler(
                    {
                        "attachment": (old, 0.0),
                        "parent": ([0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0], 0.0),
                    },
                    sql,
                )
                attachment = handler._data_svc.takeoffs["attachment"]
                attachment.parent_uid = "parent"
                attachment.area_uid = "bid-area"
                handler.on_positions_flushed([("attachment", old, new)], [])
                if sql:
                    self.assertEqual(
                        write.queued_geometry[-1][2]["takeoff_positions"],
                        [("attachment", new)],
                    )
                    write.queued_geometry[-1][-1](
                        QueuedMutationResult(
                            database_id="bid.mdb",
                            runtime_generation=1,
                            operation_id="00000000-0000-0000-0000-000000000001",
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                        )
                    )
                else:
                    self.assertEqual(write.position_calls[-1][1], [("attachment", new)])
                self.assertEqual(undo.count, 1)
                undo.undo()
                if sql:
                    self.assertEqual(
                        write.queued_geometry[-1][2]["takeoff_positions"],
                        [("attachment", old)],
                    )
                else:
                    self.assertEqual(write.position_calls[-1][1], [("attachment", old)])
                undo.redo()
                if sql:
                    self.assertEqual(
                        write.queued_geometry[-1][2]["takeoff_positions"],
                        [("attachment", new)],
                    )
                else:
                    self.assertEqual(write.position_calls[-1][1], [("attachment", new)])
                self.assertEqual(attachment.parent_uid, "parent")
                self.assertEqual(attachment.area_uid, "bid-area")

    def test_authoritative_parent_replacement_cancels_unflushed_move(self):
        fixture = keyboard_fixtures.AnnotationPlacementKeyboardTests()
        fixture.app = self.app
        self.addCleanup(fixture.doCleanups)
        view = fixture.make_view()
        state = self.make_view()
        view._current_takeoffs = state._current_takeoffs
        view._current_conditions = state._current_conditions
        view._selected_uids = {"attachment"}
        changes = []
        view.positions_flushed.connect(lambda *args: changes.append(args))
        QTest.keyPress(view, Qt.Key.Key_Right)
        attachment = view._current_takeoffs["attachment"]
        self.assertEqual(attachment.position, [6.0, 5.0])
        view.prepare_for_authoritative_refresh()
        view._current_takeoffs["parent"] = Takeoff(
            uid="parent",
            condition_uid="area",
            page_uid="page",
            position=[20.0, 20.0, 30.0, 20.0, 30.0, 30.0, 20.0, 30.0],
        )
        QTest.keyRelease(view, Qt.Key.Key_Right)
        QTest.keyClick(view, Qt.Key.Key_Right)
        self.assertEqual(attachment.position, [5.0, 5.0])
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
