import unittest
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
import tests.presentation.handlers.test_plan_view_action_handler as action_fixtures
import tests.presentation.components.plan_view.components.test_input_handler as fixtures


class AttachmentMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

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
