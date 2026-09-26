import unittest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainterPath, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsPathItem
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from tests import test_plan_view_ctrl_drag as fixtures
from tests import test_plan_annotation_placement_keyboard as keyboard_fixtures
from tests import test_plan_view_action_handler as action_fixtures


class SmallSnappedDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def make_view(self, **options):
        view = fixtures.CtrlDragTests()._make_linear_resize_gesture_view(**options)
        view._current_conditions["c"].condition_type = Condition.TYPE_AREA
        view._current_takeoffs["t1"].position = [
            0.0,
            0.0,
            12.0,
            0.0,
            12.0,
            12.0,
            0.0,
            12.0,
        ]
        view._is_handle_info_at_viewport_pos = lambda _info, _pos: False
        view._pt_to_scene = lambda x, y: QPointF(x, y)
        view.ost_to_scene_delta = lambda dx, dy: DragHandlerMixin.ost_to_scene_delta(
            view, dx, dy
        )
        view.update_drag_handle_positions = (
            lambda *args: DragHandlerMixin.update_drag_handle_positions(view, *args)
        )
        return view

    @staticmethod
    def gesture(view, points):
        view.mousePressEvent(fixtures.FakeMouseEvent(x=0, y=0))
        for x, y in points:
            view.mouseMoveEvent(fixtures.FakeMouseEvent(x=x, y=y))
        candidate = list(view._drag_last_valid_new_pos)
        x, y = points[-1] if points else (0, 0)
        view.mouseReleaseEvent(
            fixtures.FakeMouseEvent(x=x, y=y, buttons=Qt.MouseButton.NoButton)
        )
        return candidate

    def test_minimal_increments_in_each_direction_across_scale_and_zoom(self):
        # Cover Sheet accepts positive floating increments; there is no fixed
        # smallest increment. Include 1/64 inch and the metric 1 mm conversion.
        for increment in (1.0, 1.0 / 64.0, 0.1, 1.0 / 25.4, 2.0):
            for scale in (48.0, 96.0):
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1)):
                    with self.subTest(
                        increment=increment, scale=scale, direction=(dx, dy)
                    ):
                        zoom = scale / (144.0 * increment)
                        view = self.make_view(
                            scale_ratio=scale, zoom=zoom, snap_increment=increment
                        )
                        original = list(view._current_takeoffs["t1"].position)
                        candidate = self.gesture(view, [(dx, dy)])
                        self.assertEqual(
                            view._current_takeoffs["t1"].position, candidate
                        )
                        self.assertAlmostEqual(
                            candidate[0] - original[0], dx * increment
                        )
                        self.assertAlmostEqual(
                            candidate[1] - original[1], dy * increment
                        )
                        self.assertEqual(
                            view.positions_flushed.emitted,
                            [([("t1", original, candidate)], [])],
                        )

    def test_raw_two_pixels_snap_to_one_inch_and_large_movement_still_commits(self):
        for pixels, inches in ((2, 1.0), (30, 10.0)):
            with self.subTest(pixels=pixels):
                view = self.make_view()
                candidate = self.gesture(view, [(pixels, 0)])
                self.assertEqual(candidate[0], inches)
                self.assertEqual(view._current_takeoffs["t1"].position, candidate)
                self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_snap_back_and_click_are_no_ops_without_selection_cycling(self):
        for points in ([], [(1, 0)], [(3, 0), (0, 0)], [(30, 0), (0, 0)]):
            with self.subTest(points=points):
                view = self.make_view()
                original = list(view._current_takeoffs["t1"].position)
                self.gesture(view, points)
                self.assertEqual(view._current_takeoffs["t1"].position, original)
                self.assertEqual(view.positions_flushed.emitted, [])
                self.assertEqual(view._selected_uids, {"t1"})

    def test_click_on_off_grid_area_does_not_quantize_its_geometry(self):
        view = self.make_view()
        view._current_takeoffs["t1"].position = [
            v + 0.2 for v in view._current_takeoffs["t1"].position
        ]
        original = list(view._current_takeoffs["t1"].position)
        self.gesture(view, [])
        self.assertEqual(view._current_takeoffs["t1"].position, original)
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_small_drag_uses_page_rotation_and_flip_transform_once(self):
        for angle, expected in (
            (0, (1, 0)),
            (90, (0, -1)),
            (180, (-1, 0)),
            (270, (0, 1)),
        ):
            for flip in (False, True):
                with self.subTest(angle=angle, flip=flip):
                    view = self.make_view()
                    transform = QTransform().rotate(angle).scale(-1 if flip else 1, 1)
                    view._current_page_transform = lambda: transform
                    candidate = self.gesture(view, [(3, 0)])
                    self.assertEqual(
                        candidate[:2],
                        [-expected[0] if flip else expected[0], expected[1]],
                    )
                    self.assertEqual(view._current_takeoffs["t1"].position, candidate)

    def add_children(self, view):
        view._current_conditions["attachment"] = Condition(
            "attachment", condition_type=Condition.TYPE_ATTACHMENT
        )
        for uid, condition, position in (
            ("backout", "c", [2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0]),
            ("attachment", "attachment", [8.0, 8.0]),
        ):
            view._current_takeoffs[uid] = Takeoff(
                uid, condition, parent_uid="t1", position=position, area_uid="area-id"
            )

    def test_minimal_parent_movement_translates_backout_and_attachment_once(self):
        for selected in ({"t1"}, {"t1", "backout", "attachment"}):
            with self.subTest(selected=selected):
                view = self.make_view()
                self.add_children(view)
                view._selected_uids = selected
                original = {
                    uid: list(t.position)
                    for uid, t in view._current_takeoffs.items()
                    if uid != "t2"
                }
                self.gesture(view, [(3, 0)])
                for uid, before in original.items():
                    expected = [
                        v + (1.0 if i % 2 == 0 else 0.0) for i, v in enumerate(before)
                    ]
                    self.assertEqual(view._current_takeoffs[uid].position, expected)
                for uid in ("backout", "attachment"):
                    self.assertEqual(view._current_takeoffs[uid].parent_uid, "t1")
                    self.assertEqual(view._current_takeoffs[uid].area_uid, "area-id")
                self.assertEqual(len(view.positions_flushed.emitted), 1)
                self.assertEqual(len(view.positions_flushed.emitted[0][0]), 3)

    def test_minimal_drag_history_has_identical_mdb_sql_payloads(self):
        view = self.make_view(snap_increment=1.0 / 64.0, zoom=64.0 / 3.0)
        self.add_children(view)
        self.gesture(view, [(1, 0)])
        changes, annotations = view.positions_flushed.emitted[0]
        for sql in (False, True):
            with self.subTest(sql=sql):
                (
                    handler,
                    write,
                    undo,
                ) = action_fixtures.PlanViewActionHandlerTests()._make_group_transform_handler(
                    {uid: (old, 0.0) for uid, old, _new in changes}, sql
                )
                for uid in ("backout", "attachment"):
                    handler._data_svc.takeoffs[uid].parent_uid = "t1"
                handler.on_positions_flushed(changes, annotations)
                expected = [(uid, new) for uid, _old, new in changes]
                if sql:
                    self.assertEqual(
                        write.queued_geometry[-1][2]["takeoff_positions"], expected
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
                    self.assertEqual(write.position_calls[-1][1], expected)
                self.assertEqual(undo.count, 1)
                undo.undo()
                self.assertEqual(
                    (
                        write.queued_geometry[-1][2]["takeoff_positions"]
                        if sql
                        else write.position_calls[-1][1]
                    ),
                    [(uid, old) for uid, old, _new in changes],
                )
                if sql:
                    write.queued_geometry[-1][-1](
                        QueuedMutationResult(
                            database_id="bid.mdb",
                            runtime_generation=1,
                            operation_id="00000000-0000-0000-0000-000000000002",
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                        )
                    )
                undo.redo()
                self.assertEqual(
                    (
                        write.queued_geometry[-1][2]["takeoff_positions"]
                        if sql
                        else write.position_calls[-1][1]
                    ),
                    expected,
                )
                if sql:
                    write.queued_geometry[-1][-1](
                        QueuedMutationResult(
                            database_id="bid.mdb",
                            runtime_generation=1,
                            operation_id="00000000-0000-0000-0000-000000000003",
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                        )
                    )

    def test_adjacent_body_drag_paths_commit_the_same_small_translation(self):
        for kind in ("linear", "count", "backout", "attachment"):
            with self.subTest(kind=kind):
                view = self.make_view()
                condition = view._current_conditions["c"]
                condition.condition_type = {
                    "linear": Condition.TYPE_LINEAR,
                    "count": Condition.TYPE_COUNT,
                    "backout": Condition.TYPE_AREA,
                    "attachment": Condition.TYPE_ATTACHMENT,
                }[kind]
                takeoff = view._current_takeoffs["t1"]
                if kind == "linear":
                    takeoff.position = [0.0, 0.0, 12.0, 0.0]
                elif kind in ("count", "attachment"):
                    takeoff.position = [0.0, 0.0]
                if kind in ("backout", "attachment"):
                    takeoff.parent_uid = "t2"
                    view._current_conditions["parent"] = Condition(
                        "parent", condition_type=Condition.TYPE_AREA
                    )
                    parent = view._current_takeoffs["t2"]
                    parent.condition_uid = "parent"
                    parent.position = [
                        -100.0,
                        -100.0,
                        100.0,
                        -100.0,
                        100.0,
                        100.0,
                        -100.0,
                        100.0,
                    ]
                original = list(takeoff.position)
                self.gesture(view, [(3, 0)])
                expected = [
                    v + (1.0 if i % 2 == 0 else 0.0) for i, v in enumerate(original)
                ]
                self.assertEqual(takeoff.position, expected)
                self.assertEqual(
                    view.positions_flushed.emitted, [([("t1", original, expected)], [])]
                )

    def test_one_inch_area_preview_is_committed_below_pixel_threshold(self):
        view = self.make_view()
        original = list(view._current_takeoffs["t1"].position)
        item = view._uid_to_items["t1"][0]
        original_item_position = item.pos()
        view.mousePressEvent(fixtures.FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(fixtures.FakeMouseEvent(x=3, y=0))
        candidate = list(view._drag_last_valid_new_pos)
        self.assertEqual(candidate[0] - original[0], 1.0)
        self.assertEqual(item.pos() - original_item_position, QPointF(3, 0))
        self.assertEqual(view._current_takeoffs["t1"].position, original)
        view.mouseReleaseEvent(
            fixtures.FakeMouseEvent(x=3, y=0, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._current_takeoffs["t1"].position, candidate)
        self.assertEqual(
            view.positions_flushed.emitted, [([("t1", original, candidate)], [])]
        )

    def test_small_multi_area_preview_is_committed(self):
        view = self.make_view()
        view._selected_uids = {"t1", "t2"}
        original = {uid: list(t.position) for uid, t in view._current_takeoffs.items()}
        view.mousePressEvent(fixtures.FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(fixtures.FakeMouseEvent(x=3, y=0))
        self.assertEqual(view._uid_to_items["t1"][0].pos(), QPointF(4, 2))
        view.mouseReleaseEvent(
            fixtures.FakeMouseEvent(x=3, y=0, buttons=Qt.MouseButton.NoButton)
        )
        for uid, before in original.items():
            self.assertEqual(
                view._current_takeoffs[uid].position,
                [v + (1.0 if i % 2 == 0 else 0.0) for i, v in enumerate(before)],
            )
        self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_real_qt_one_pixel_one_inch_drag_keeps_preview_after_release(self):
        fixture = keyboard_fixtures.AnnotationPlacementKeyboardTests()
        fixture.app = self.app
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view = fixture.make_view()
        view._current_conditions = {
            "area": Condition("area", condition_type=Condition.TYPE_AREA)
        }
        original = [900.0, 900.0, 1100.0, 900.0, 1100.0, 1100.0, 900.0, 1100.0]
        takeoff = Takeoff("area", "area", page_uid="p1", position=list(original))
        view._current_takeoffs = {"area": takeoff}
        path = QPainterPath()
        path.addRect(900, 900, 200, 200)
        item = QGraphicsPathItem(path)
        item.setData(0, "area")
        item.setData(1, "area")
        view._scene.addItem(item)
        view._uid_to_items = {"area": [item]}
        view.set_selected_uids({"area"})
        changes = []
        view.positions_flushed.connect(lambda *args: changes.append(args))
        start = view.mapFromScene(QPointF(1000, 1000))

        def deliver(kind, point, button, buttons):
            event = QMouseEvent(
                kind,
                QPointF(point),
                QPointF(view.viewport().mapToGlobal(point)),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(view.viewport(), event)

        deliver(
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(view._drag_plan_item_uid, "area")
        self.assertEqual(view._drag_handle_index, -1)
        end = start + QPoint(1, 0)
        deliver(
            QEvent.Type.MouseMove,
            end,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
        candidate = list(view._drag_last_valid_new_pos)
        self.assertEqual(candidate[0] - original[0], 1.0)
        self.assertEqual(item.pos(), QPointF(1, 0))
        deliver(
            QEvent.Type.MouseButtonRelease,
            end,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        self.assertEqual(takeoff.position, candidate)
        self.assertEqual(changes, [([("area", original, candidate)], [])])


if __name__ == "__main__":
    unittest.main()
