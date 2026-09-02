import unittest
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService


class UndoRedoServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = UndoRedoService()
        self.service.set_active_bid(BidRef("database", "7"))

    @staticmethod
    def _mutation_result(status: MutationOutcomeStatus) -> QueuedMutationResult:
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
            commit_attempted=status == MutationOutcomeStatus.COMMITTED,
        )

    def test_failed_synchronous_undo_does_not_advance_history(self):
        self.service.push_local(lambda: False, lambda: True)
        self.service.undo()
        self.assertTrue(self.service.can_undo())
        self.assertFalse(self.service.can_redo())

    def test_exception_during_redo_leaves_entry_on_redo_stack(self):
        def fail():
            raise RuntimeError("write failed")

        self.service.push_local(lambda: True, fail)
        self.service.undo()
        self.service.redo()
        self.assertFalse(self.service.can_undo())
        self.assertTrue(self.service.can_redo())

    def test_async_history_waits_for_successful_completion(self):
        undo_completions = []
        redo_completions = []
        self.service.push(
            lambda complete: undo_completions.append(complete),
            lambda complete: redo_completions.append(complete),
        )
        self.service.undo()
        self.assertFalse(self.service.can_undo())
        self.assertFalse(self.service.can_redo())
        undo_completions.pop()(self._mutation_result(MutationOutcomeStatus.REJECTED))
        self.assertTrue(self.service.can_undo())
        self.assertFalse(self.service.can_redo())
        self.service.undo()
        undo_completions.pop()(self._mutation_result(MutationOutcomeStatus.COMMITTED))
        self.assertFalse(self.service.can_undo())
        self.assertTrue(self.service.can_redo())
        self.service.redo()
        redo_completions.pop()(self._mutation_result(MutationOutcomeStatus.COMMITTED))
        self.assertTrue(self.service.can_undo())
        self.assertFalse(self.service.can_redo())

    def test_delayed_history_for_inactive_bid_is_rejected(self):
        originating_bid = BidRef("database", "7")
        self.service.set_active_bid(BidRef("database", "8"))
        self.service.push_for_bid(
            originating_bid,
            lambda _complete: None,
            lambda _complete: None,
        )
        self.assertFalse(self.service.can_undo())

    def test_uncertain_async_history_stays_frozen_until_recovery(self):
        completions = []
        self.service.push(
            lambda complete: completions.append(complete),
            lambda _complete: None,
        )
        self.service.undo()
        complete = completions.pop()
        complete(
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            )
        )
        self.assertFalse(self.service.can_undo())
        self.assertFalse(self.service.can_redo())
        complete(
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertFalse(self.service.can_undo())
        self.assertTrue(self.service.can_redo())

    def test_late_cleared_history_callback_cannot_thaw_new_uncertain_history(self):
        stale_completions = []
        current_completions = []
        self.service.push(
            lambda complete: stale_completions.append(complete),
            lambda _complete: None,
        )
        self.service.undo()
        self.service.clear()
        self.service.push(
            lambda complete: current_completions.append(complete),
            lambda _complete: None,
        )
        self.service.undo()
        current_complete = current_completions.pop()
        current_complete(
            self._mutation_result(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN)
        )
        self.service.push(
            lambda _complete: None,
            lambda _complete: None,
        )
        stale_completions.pop()(self._mutation_result(MutationOutcomeStatus.REJECTED))
        self.assertFalse(self.service.can_undo())
        current_complete(self._mutation_result(MutationOutcomeStatus.COMMITTED))
        self.assertTrue(self.service.can_undo())


if __name__ == "__main__":
    unittest.main()
