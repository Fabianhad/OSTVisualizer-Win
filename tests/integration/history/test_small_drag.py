import unittest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
import tests.presentation.components.plan_view.components.test_input_handler as fixtures
import tests.presentation.handlers.test_plan_view_action_handler as action_fixtures


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
