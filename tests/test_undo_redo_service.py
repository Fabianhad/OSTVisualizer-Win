import unittest
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.services.undo_redo_service import (
    UndoRedoService,
    TakeoffHistoryTarget,
)


class UndoRedoServiceTests(unittest.TestCase):
    def test_restore_rebinds_captured_lifetime_not_later_reused_uid(self):
        bid_ref = BidRef("database", "7")
        first = TakeoffHistoryTarget(bid_ref, "20", "10")
        other_page = TakeoffHistoryTarget(bid_ref, "21", "10")
        self.service.push_local(
            lambda: True, lambda: True, takeoff_targets=(first, other_page)
        )
        first_deleted = self.service.suspend_deleted_takeoffs(bid_ref, (first,))
        self.assertTrue(other_page.available)
        second = TakeoffHistoryTarget(bid_ref, "20", "10")
        self.service.push_local(lambda: True, lambda: True, takeoff_targets=(second,))
        second_deleted = self.service.suspend_deleted_takeoffs(bid_ref, (second,))
        self.assertEqual(len(second_deleted), 1)
        self.assertIs(second_deleted[0], second)
        self.service.rebind_restored_takeoffs(
            bid_ref, {("20", "10"): "50"}, second_deleted
        )
        self.assertFalse(first.available)
        self.assertEqual(first.uid, "10")
        self.service.rebind_restored_takeoffs(
            bid_ref, {("20", "10"): "60"}, first_deleted
        )
        self.assertEqual((first.uid, second.uid, other_page.uid), ("60", "50", "10"))

    def test_cleared_history_cannot_be_rebound_by_late_restore(self):
        bid_ref = BidRef("database", "7")
        target = TakeoffHistoryTarget(bid_ref, "20", "10")
        self.service.push_local(lambda: True, lambda: True, takeoff_targets=(target,))
        suspended = self.service.suspend_deleted_takeoffs(bid_ref, (target,))
        self.service.clear()
        self.service.rebind_restored_takeoffs(bid_ref, {("20", "10"): "50"}, suspended)
        self.assertFalse(target.available)
        self.assertEqual(target.uid, "10")

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

    def test_forward_mutation_blocks_older_undo_until_its_history_is_ready(self):
        calls = []
        self.service.push_local(
            lambda: calls.append("older-undo") or True,
            lambda: True,
        )
        bid_ref = BidRef("database", "7")
        token = self.service.begin_forward_mutation(bid_ref)
        self.assertFalse(self.service.can_undo())
        self.service.undo()
        self.assertEqual(calls, [])
        self.service.push_local(
            lambda: calls.append("newer-undo") or True,
            lambda: True,
        )
        self.assertFalse(self.service.can_undo())
        self.service.finish_forward_mutation(token)
        self.assertTrue(self.service.can_undo())
        self.service.undo()
        self.assertEqual(calls, ["newer-undo"])

    def test_clearing_history_invalidates_forward_mutation_token(self):
        bid_ref = BidRef("database", "7")
        token = self.service.begin_forward_mutation(bid_ref)
        self.service.clear()
        self.service.push_local(lambda: True, lambda: True)
        self.service.finish_forward_mutation(token)
        self.assertTrue(self.service.can_undo())

    def test_out_of_order_forward_completions_keep_submission_history_order(self):
        bid_ref = BidRef("database", "7")
        first = self.service.begin_forward_mutation(bid_ref)
        second = self.service.begin_forward_mutation(bid_ref)
        calls = []
        self.service.push_local(
            lambda: calls.append("second") or True,
            lambda: True,
        )
        self.service.bind_latest_history_to_forward_mutation(second)
        self.service.finish_forward_mutation(second)
        self.assertFalse(self.service.can_undo())
        self.service.push_local(
            lambda: calls.append("first") or True,
            lambda: True,
        )
        self.service.bind_latest_history_to_forward_mutation(first)
        self.service.finish_forward_mutation(first)
        self.service.undo()
        self.assertEqual(calls, ["second"])

    def test_forward_ordering_does_not_reorder_completed_local_history(self):
        calls = []
        bid_ref = BidRef("database", "7")
        first = self.service.begin_forward_mutation(bid_ref)
        self.service.push_local(lambda: calls.append("first") or True, lambda: True)
        self.service.bind_latest_history_to_forward_mutation(first)
        self.service.finish_forward_mutation(first)
        self.service.push_local(lambda: calls.append("local") or True, lambda: True)
        last = self.service.begin_forward_mutation(bid_ref)
        self.service.push_local(lambda: calls.append("last") or True, lambda: True)
        self.service.bind_latest_history_to_forward_mutation(last)
        self.service.finish_forward_mutation(last)
        for _expected in ("last", "local", "first"):
            self.service.undo()
        self.assertEqual(calls, ["last", "local", "first"])

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

    def test_typed_mixed_move_has_no_drift_after_one_hundred_cycles(self):
        selected = {
            ("takeoff", "10"),
            ("line", "10"),
            ("arrow", "10"),
            ("text", "10"),
        }
        unrelated = ("takeoff", "99")
        before = {identity: (0.0, 0.0) for identity in selected}
        before[unrelated] = (99.0, 99.0)
        after = dict(before)
        for identity in selected:
            after[identity] = (10.0, 20.0)
        state = dict(after)

        def restore(snapshot):
            for identity in selected:
                state[identity] = snapshot[identity]
            return True

        self.service.push_local(
            lambda: restore(before),
            lambda: restore(after),
        )
        for _cycle in range(100):
            self.service.undo()
            self.assertEqual(state, before)
            self.service.redo()
            self.assertEqual(state, after)
        self.assertEqual(state[unrelated], (99.0, 99.0))

    def test_main_and_detached_histories_are_isolated(self):
        detached = UndoRedoService()
        detached.set_active_bid(BidRef("database", "7"))
        calls = []
        self.service.push_local(
            lambda: calls.append("main") or True,
            lambda: True,
        )
        detached.push_local(
            lambda: calls.append("detached") or True,
            lambda: True,
        )
        self.service.undo()
        self.assertEqual(calls, ["main"])
        self.assertTrue(detached.can_undo())
        detached.undo()
        self.assertEqual(calls, ["main", "detached"])


if __name__ == "__main__":
    unittest.main()
