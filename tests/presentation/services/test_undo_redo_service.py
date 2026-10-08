import unittest
import uuid
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    MutationRejectionReason,
    QueuedMutationResult,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.services.undo_redo_service import (
    MutationHistoryState,
    TakeoffHistoryTarget,
    UndoRedoService,
)
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    EditLeaseHandle,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
    ProjectWritePayload,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.presentation.services.selection_commands import (
    InsertTakeoffsCommand,
)
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from PySide6 import QtWidgets


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
        self.assertTrue(first.available)
        self.assertTrue(second.available)
        self.assertTrue(other_page.available)

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
        calls = []
        self.service.push_local(lambda: calls.append("undo") or False, lambda: True)
        self.service.undo()
        self.assertEqual(calls, ["undo"])
        self.assertTrue(self.service.can_undo())
        self.assertFalse(self.service.can_redo())
        self.service.undo()
        self.assertEqual(calls, ["undo", "undo"])

    def test_failed_synchronous_redo_keeps_entry_on_redo_stack(self):
        calls = []
        self.service.push_local(lambda: True, lambda: calls.append("redo") or False)
        self.service.undo()
        self.service.redo()
        self.assertEqual(calls, ["redo"])
        self.assertFalse(self.service.can_undo())
        self.assertTrue(self.service.can_redo())

    def test_exception_during_redo_leaves_entry_on_redo_stack(self):
        def fail():
            raise RuntimeError("write failed")

        self.service.push_local(lambda: True, fail)
        self.service.undo()
        with self.assertLogs(self.service.logger, level="ERROR") as logs:
            self.service.redo()
        self.assertIn("Error during local history mutation", logs.output[0])
        self.assertFalse(self.service.can_undo())
        self.assertTrue(self.service.can_redo())

    def test_exception_during_undo_leaves_entry_on_undo_stack(self):
        def fail():
            raise RuntimeError("write failed")

        self.service.push_local(fail, lambda: True)
        with self.assertLogs(self.service.logger, level="ERROR"):
            self.service.undo()
        self.assertTrue(self.service.can_undo())
        self.assertFalse(self.service.can_redo())

    def test_exception_while_submitting_async_history_releases_the_transition(self):
        def explode(_complete):
            raise RuntimeError("submit failed")

        self.service.push(explode, lambda _complete: None)
        with self.assertLogs(self.service.logger, level="ERROR"):
            self.service.undo()
        self.assertTrue(self.service.can_undo())
        self.assertFalse(self.service.can_redo())

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
        self.service.undo()
        self.service.redo()
        self.assertEqual(len(undo_completions), 1)
        self.assertEqual(redo_completions, [])
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
        changes = []
        self.service.set_change_callback(lambda: changes.append("changed"))
        self.service.push_for_bid(
            originating_bid,
            lambda _complete: None,
            lambda _complete: None,
        )
        self.assertFalse(self.service.can_undo())
        self.assertEqual(changes, [])
        self.service.set_active_bid(originating_bid)
        changes.clear()
        self.service.push_for_bid(
            originating_bid,
            lambda complete: complete(
                self._mutation_result(MutationOutcomeStatus.COMMITTED)
            ),
            lambda _complete: None,
        )
        self.assertEqual(changes, ["changed"])
        self.assertTrue(self.service.can_undo())

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
        self.assertTrue(self.service.is_forward_mutation_current(token))
        self.service.clear()
        self.assertFalse(self.service.is_forward_mutation_current(token))
        self.service.push_local(lambda: True, lambda: True)
        self.assertTrue(self.service.can_undo())
        self.service.bind_latest_history_to_forward_mutation(token)
        self.service.finish_forward_mutation(token)
        self.assertTrue(self.service.can_undo())

    def test_forward_mutation_for_inactive_bid_is_not_tracked(self):
        self.assertIsNone(self.service.begin_forward_mutation(BidRef("database", "8")))
        self.service.push_local(lambda: True, lambda: True)
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
        self.service.undo()
        self.assertEqual(calls, ["second", "first"])

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
        self.service.undo()
        self.service.redo()
        self.assertEqual(completions, [])
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
        self.assertTrue(self.service.can_redo())
        self.assertTrue(detached.can_redo())
        self.assertFalse(self.service.can_undo())
        self.assertFalse(detached.can_undo())

    def test_write_guard_blocks_undo_and_redo_without_running_actions(self):
        calls = []
        allowed = [False]
        self.service.set_write_guard(lambda: allowed[0])
        self.service.push_local(
            lambda: calls.append("undo") or True,
            lambda: calls.append("redo") or True,
        )
        self.service.undo()
        self.assertEqual(calls, [])
        self.assertTrue(self.service.can_undo())
        allowed[0] = True
        self.service.undo()
        allowed[0] = False
        self.service.redo()
        self.assertEqual(calls, ["undo"])
        self.assertTrue(self.service.can_redo())

    def test_new_push_discards_redo_stack(self):
        self.service.push_local(lambda: True, lambda: True)
        self.service.undo()
        self.assertTrue(self.service.can_redo())
        self.service.push_local(lambda: True, lambda: True)
        self.assertFalse(self.service.can_redo())
        self.assertTrue(self.service.can_undo())

    def test_history_is_bounded_and_drops_oldest_entries(self):
        service = UndoRedoService(max_size=2)
        service.set_active_bid(BidRef("database", "7"))
        calls = []
        for name in ("one", "two", "three"):
            service.push_local(
                lambda name=name: calls.append(name) or True, lambda: True
            )
        for _attempt in range(3):
            service.undo()
        self.assertEqual(calls, ["three", "two"])
        self.assertFalse(service.can_undo())

    def test_push_without_active_bid_is_ignored(self):
        service = UndoRedoService()
        service.push_local(lambda: True, lambda: True)
        self.assertFalse(service.can_undo())
        service.set_active_bid(BidRef("database", "7"))
        self.assertFalse(service.can_undo())

    def test_switching_active_bid_clears_history_and_invalidates_targets(self):
        target = TakeoffHistoryTarget(BidRef("database", "7"), "20", "10")
        self.service.push_local(lambda: True, lambda: True, takeoff_targets=(target,))
        self.service.set_active_bid(BidRef("database", "7"))
        self.assertTrue(self.service.can_undo())
        self.assertTrue(target.available)
        self.service.set_active_bid(BidRef("database", "8"))
        self.assertFalse(self.service.can_undo())
        self.assertFalse(target.available)

    def test_conflicting_history_operation_freezes_the_entry(self):
        self.service.push(
            lambda complete: complete(
                QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.CONFLICT,
                )
            ),
            lambda _complete: None,
        )
        self.service.undo()
        self.assertFalse(self.service.can_undo())
        self.assertFalse(self.service.can_redo())


class UndoRedoServiceLabelTests(unittest.TestCase):
    def setUp(self):
        self.service = UndoRedoService()
        self.service.set_active_bid(BidRef("database", "7"))

    def test_entries_carry_an_optional_label_for_the_top_of_the_stack(self):
        self.assertEqual(self.service.undo_label(), "")
        self.service.push_local(lambda: True, lambda: True)
        self.assertEqual(self.service.undo_label(), "")
        self.service.push_local(lambda: True, lambda: False, label="AI: 1 slab")
        self.assertEqual(self.service.undo_label(), "AI: 1 slab")
        self.service.push_for_bid(
            BidRef("database", "7"),
            lambda complete: None,
            lambda complete: None,
            label="AI: scale",
        )
        self.assertEqual(self.service.undo_label(), "AI: scale")
        self.service.push(lambda complete: None, lambda complete: None)
        self.assertEqual(self.service.undo_label(), "")

    def test_a_ready_entry_can_be_discarded_from_anywhere_in_history(self):
        bid_ref = BidRef("database", "7")
        undone = []
        older = self.service.push_for_bid(
            bid_ref, lambda complete: undone.append("older"), lambda complete: None
        )
        discarded = self.service.push_for_bid(
            bid_ref, lambda complete: undone.append("discarded"), lambda complete: None
        )
        newer = self.service.push_for_bid(
            bid_ref, lambda complete: undone.append("newer"), lambda complete: None
        )
        self.assertIsNotNone(older)
        self.assertIsNone(
            self.service.push_for_bid(
                BidRef("database", "8"), lambda complete: None, lambda complete: None
            )
        )
        self.assertTrue(self.service.discard_entry(discarded))
        self.assertFalse(self.service.discard_entry(discarded))
        self.assertEqual(self.service._undo_stack, [older, newer])
        newer.state = MutationHistoryState.UNDO_PENDING
        self.assertFalse(self.service.discard_entry(newer))
        self.assertEqual(self.service._undo_stack, [older, newer])

    def test_discarding_notifies_only_when_an_entry_was_removed(self):
        changes = []
        bid_ref = BidRef("database", "7")
        entry = self.service.push_for_bid(
            bid_ref, lambda complete: None, lambda complete: None
        )
        self.service.set_change_callback(lambda: changes.append("changed"))
        self.assertIs(self.service.discard_entry(entry), True)
        self.assertEqual(changes, ["changed"])
        self.assertIs(self.service.discard_entry(entry), False)
        self.assertEqual(changes, ["changed"])

    def test_an_entry_on_the_redo_stack_can_be_discarded(self):
        bid_ref = BidRef("database", "7")
        entry = self.service.push_for_bid(
            bid_ref,
            lambda complete: complete(
                QueuedMutationResult(
                    database_id="database",
                    runtime_generation=0,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            ),
            lambda complete: None,
        )
        self.service.undo()
        self.assertTrue(self.service.can_redo())
        self.assertIs(self.service.discard_entry(entry), True)
        self.assertEqual(self.service._redo_stack, [])
        self.assertFalse(self.service.can_redo())
        self.assertFalse(self.service.can_undo())

    def test_pending_and_uncertain_entries_are_never_discarded(self):
        bid_ref = BidRef("database", "7")
        for state in (
            MutationHistoryState.UNDO_PENDING,
            MutationHistoryState.REDO_PENDING,
            MutationHistoryState.UNCERTAIN,
            MutationHistoryState.CONFLICTED,
        ):
            with self.subTest(state=state):
                changes = []
                entry = self.service.push_for_bid(
                    bid_ref, lambda complete: None, lambda complete: None
                )
                self.service.set_change_callback(lambda: changes.append("changed"))
                entry.state = state
                self.assertIs(self.service.discard_entry(entry), False)
                self.assertIs(self.service._undo_stack[-1], entry)
                self.assertEqual(changes, [])
                self.service.set_change_callback(None)

    def test_an_uncertain_undo_keeps_its_entry_until_recovery(self):
        bid_ref = BidRef("database", "7")
        completions = []
        entry = self.service.push_for_bid(
            bid_ref, completions.append, lambda complete: None
        )
        self.service.undo()
        completions[0](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=0,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            )
        )
        self.assertEqual(entry.state, MutationHistoryState.UNCERTAIN)
        self.assertIs(self.service.discard_entry(entry), False)
        self.assertEqual(self.service._undo_stack, [entry])


class MdbSqlBehaviorParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @staticmethod
    def _result(status: MutationOutcomeStatus) -> QueuedMutationResult:
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
            commit_attempted=status == MutationOutcomeStatus.COMMITTED,
        )

    def test_failed_history_operation_stays_undoable_for_mdb_and_sql(self):
        for backend in ("mdb", "sql"):
            with self.subTest(backend=backend):
                history = UndoRedoService()
                history.set_active_bid(BidRef("database", "7"))
                if backend == "mdb":
                    view = SimpleNamespace(
                        clear_selection=lambda: None,
                        set_selected_uids=lambda _uids: None,
                    )
                    command = InsertTakeoffsCommand(
                        ["1"],
                        BidRef("database", "7"),
                        [object()],
                        None,
                        view,
                        insert_takeoffs_fn=lambda _bid, _specs: ["2"],
                        delete_takeoffs_fn=lambda _path, _uids: False,
                    )
                    history.push_local(command.undo, command.redo)
                else:
                    history.push(
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.REJECTED)
                        ),
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.COMMITTED)
                        ),
                    )
                history.undo()
                self.assertTrue(history.can_undo())
                self.assertFalse(history.can_redo())

    def test_committed_history_operation_advances_for_mdb_and_sql(self):
        for backend in ("mdb", "sql"):
            with self.subTest(backend=backend):
                history = UndoRedoService()
                history.set_active_bid(BidRef("database", "7"))
                if backend == "mdb":
                    history.push_local(lambda: True, lambda: True)
                else:
                    history.push(
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.COMMITTED)
                        ),
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.COMMITTED)
                        ),
                    )
                history.undo()
                self.assertFalse(history.can_undo())
                self.assertTrue(history.can_redo())


class AnnotationDeletionScopeTests(unittest.TestCase):
    def test_deletion_invalidation_requires_database_bid_page_and_type(self):
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )
        from ost_visualizer.domain.entities.identity_refs import BidRef

        bid = BidRef("one.mdb", "7")
        history = UndoRedoService()
        history.set_active_bid(bid)
        text = AnnotationHistoryTarget(bid, "p1", "text", "1")
        rect = AnnotationHistoryTarget(bid, "p1", "rect", "1")
        other_page = AnnotationHistoryTarget(bid, "p2", "text", "1")
        history.push_local(
            lambda: True, lambda: True, annotation_targets=(text, rect, other_page)
        )
        for database, bid_uid in (("two.mdb", "7"), ("one.mdb", "8")):
            history.invalidate_deleted_annotation_lifetimes(
                database, bid_uid, (("p1", "text", "1"),), "peer"
            )
            self.assertTrue(text.available)
        history.invalidate_deleted_annotation_lifetimes(
            "one.mdb", "7", (("p1", "text", "1"),), "peer"
        )
        self.assertFalse(text.available)
        self.assertTrue(rect.available)
        self.assertTrue(other_page.available)

    def test_own_history_owner_does_not_invalidate_its_own_targets(self):
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )

        bid = BidRef("one.mdb", "7")
        history = UndoRedoService()
        history.set_active_bid(bid)
        text = AnnotationHistoryTarget(bid, "p1", "text", "1")
        history.push_local(lambda: True, lambda: True, annotation_targets=(text,))
        history.invalidate_deleted_annotation_lifetimes(
            "one.mdb", "7", (("p1", "text", "1"),), history._annotation_history_owner
        )
        self.assertTrue(text.available)

    def test_suspended_deletion_publishes_scoped_event_and_restore_rebinds_targets(
        self,
    ):
        from ost_visualizer.application.events.app_events import AppEvents
        from ost_visualizer.infrastructure.events.event_bus import EventBus
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )

        bid = BidRef("one.mdb", "7")
        events = EventBus()
        published = []
        events.subscribe(
            AppEvents.ANNOTATION_LIFETIMES_DELETED,
            lambda **payload: published.append(payload),
        )
        history = UndoRedoService(event_bus=events)
        history.set_active_bid(bid)
        text = AnnotationHistoryTarget(bid, "p1", "text", "1")
        rect = AnnotationHistoryTarget(bid, "p1", "rect", "1")
        history.push_local(lambda: True, lambda: True, annotation_targets=(text, rect))
        suspended = history.suspend_deleted_annotations(bid, (text,))
        self.assertEqual(suspended, (text,))
        self.assertFalse(text.available)
        self.assertTrue(rect.available)
        self.assertEqual(
            published,
            [
                {
                    "database_id": "one.mdb",
                    "bid_uid": "7",
                    "identities": (("p1", "text", "1"),),
                    "history_owner": history._annotation_history_owner,
                }
            ],
        )
        history.rebind_restored_annotations(bid, {("p1", "text", "1"): "55"}, suspended)
        self.assertEqual((text.uid, text.available), ("55", True))
        self.assertEqual((rect.uid, rect.available), ("1", True))

    def test_deletion_for_inactive_bid_notifies_peers_but_suspends_nothing(self):
        from ost_visualizer.application.events.app_events import AppEvents
        from ost_visualizer.infrastructure.events.event_bus import EventBus
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )

        events = EventBus()
        published = []
        events.subscribe(
            AppEvents.ANNOTATION_LIFETIMES_DELETED,
            lambda **payload: published.append(payload),
        )
        history = UndoRedoService(event_bus=events)
        history.set_active_bid(BidRef("one.mdb", "7"))
        other = BidRef("one.mdb", "8")
        target = AnnotationHistoryTarget(other, "p1", "text", "1")
        self.assertEqual(history.suspend_deleted_annotations(other, (target,)), ())
        self.assertTrue(target.available)
        self.assertEqual(
            [(payload["bid_uid"], payload["identities"]) for payload in published],
            [("8", (("p1", "text", "1"),))],
        )

    def test_cleared_history_cannot_be_rebound_by_late_annotation_restore(self):
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )

        bid = BidRef("one.mdb", "7")
        history = UndoRedoService()
        history.set_active_bid(bid)
        text = AnnotationHistoryTarget(bid, "p1", "text", "1")
        history.push_local(lambda: True, lambda: True, annotation_targets=(text,))
        suspended = history.suspend_deleted_annotations(bid, (text,))
        history.clear()
        history.rebind_restored_annotations(bid, {("p1", "text", "1"): "55"}, suspended)
        self.assertEqual((text.uid, text.available), ("1", False))


class UndoRedoServiceStaleCompletionTests(unittest.TestCase):
    """A duplicate terminal delivery of an earlier history transition must not
    release the in-flight guard of a newer transition."""

    @staticmethod
    def _result(status):
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
        )

    def test_duplicate_terminal_of_a_finished_transition_does_not_unblock_the_next(
        self,
    ):
        history = UndoRedoService()
        history.set_active_bid(BidRef("database", "7"))
        submitted = []
        for label in ("first", "second"):
            history.push(
                lambda complete, label=label: submitted.append(
                    (label, "undo", complete)
                ),
                lambda complete, label=label: submitted.append(
                    (label, "redo", complete)
                ),
            )
        history.undo()
        label, kind, complete_second_undo = submitted[-1]
        self.assertEqual((label, kind), ("second", "undo"))
        complete_second_undo(self._result(MutationOutcomeStatus.COMMITTED))
        # The next transition (undo of the first entry) is now in flight.
        history.undo()
        self.assertEqual(
            [item[:2] for item in submitted], [("second", "undo"), ("first", "undo")]
        )
        # A duplicate terminal delivery of the second entry's undo arrives late.
        complete_second_undo(self._result(MutationOutcomeStatus.REJECTED))
        # The first entry's undo is still in flight: nothing else may start.
        history.redo()
        self.assertEqual(len(submitted), 2)
        self.assertFalse(history.can_redo())
        self.assertFalse(history.can_undo())
        # Its own completion releases the guard exactly once.
        submitted[1][2](self._result(MutationOutcomeStatus.COMMITTED))
        history.redo()
        self.assertEqual([item[:2] for item in submitted][-1], ("first", "redo"))


class UndoRedoServiceLockedBidRefusalTests(unittest.TestCase):
    """Decision P2: a history replay whose queued write is refused with
    ActiveBidLockedError (the Bid was locked after the entry was recorded) is a silent
    refusal: one warning (not the error log of an unexpected failure), no exception,
    the in-flight guard is released, the entry stays on its stack in the READY state and
    can be replayed once the Bid is unlocked."""

    def setUp(self):
        self.history = UndoRedoService()
        self.history.set_active_bid(BidRef("database", "7"))
        self.locked = True
        self.submitted = []
        self.changes = 0
        self.history.set_change_callback(self._changed)

    def _changed(self):
        self.changes += 1

    def _submit(self, label):
        def submit(complete):
            if self.locked:
                raise ActiveBidLockedError()
            self.submitted.append((label, complete))

        return submit

    @staticmethod
    def _committed():
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )

    def test_a_refused_undo_replay_is_silent_and_replayable(self):
        self.history.push(self._submit("undo"), self._submit("redo"))
        changes_before = self.changes
        with self.assertLogs(self.history.logger, "WARNING") as logged:
            self.history.undo()
        self.assertEqual(
            [(record.levelname, record.getMessage()) for record in logged.records],
            [("WARNING", "History mutation blocked: the active bid is locked")],
        )
        self.assertIsNone(logged.records[0].exc_info)
        # One notification when the replay started, one when it was refused.
        self.assertEqual(self.changes - changes_before, 2)
        self.assertTrue(self.history.can_undo())
        self.assertFalse(self.history.can_redo())
        self.assertEqual(self.submitted, [])
        self.locked = False
        self.history.undo()
        self.assertEqual([label for label, _complete in self.submitted], ["undo"])
        self.submitted[0][1](self._committed())
        self.assertTrue(self.history.can_redo())
        self.assertFalse(self.history.can_undo())

    def test_a_refused_redo_replay_is_silent_and_replayable(self):
        self.locked = False
        self.history.push(self._submit("undo"), self._submit("redo"))
        self.history.undo()
        self.submitted[0][1](self._committed())
        self.assertTrue(self.history.can_redo())
        self.locked = True
        with self.assertLogs(self.history.logger, "WARNING") as logged:
            self.history.redo()
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["History mutation blocked: the active bid is locked"],
        )
        self.assertTrue(self.history.can_redo())
        self.assertFalse(self.history.can_undo())
        self.locked = False
        self.history.redo()
        self.assertEqual(
            [label for label, _complete in self.submitted], ["undo", "redo"]
        )

    def test_another_replay_failure_is_still_logged_as_an_error(self):
        # Scope pin: only the lock refusal is silent; any other submit failure keeps
        # the error log with its traceback and the same state reset.
        def failing(_complete):
            raise RuntimeError("submit failed")

        self.history.push(failing, failing)
        with self.assertLogs(self.history.logger, "ERROR") as logged:
            self.history.undo()
        self.assertEqual(
            logged.records[0].getMessage(), "Error while submitting history mutation"
        )
        self.assertTrue(self.history.can_undo())


class UndoRedoServiceBidLockedRejectionTests(unittest.TestCase):
    """Decision B4: a history replay whose queued write the SQL writer then refused
    with REJECTED / bid_locked (the lock flag was stale when the replay was queued) is
    a plain refusal, like the queue-time ActiveBidLockedError: the entry returns to
    READY on the stack it came from (not CONFLICTED, not moved, still replayable once
    the Bid is unlocked), the in-flight guard is released and nothing is logged by the
    service (the coordinator's hook logs the one warning). A CONFLICT outcome still
    marks the entry CONFLICTED."""

    def setUp(self):
        self.history = UndoRedoService()
        self.history.set_active_bid(BidRef("database", "7"))
        self.submitted = []
        self.changes = 0
        self.history.set_change_callback(self._changed)

    def _changed(self):
        self.changes += 1

    def _submit(self, label):
        def submit(complete):
            self.submitted.append((label, complete))

        return submit

    @staticmethod
    def _result(status, reason=None):
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
            rejection_reason=reason,
        )

    def _bid_locked(self):
        return self._result(
            MutationOutcomeStatus.REJECTED, MutationRejectionReason.BID_LOCKED
        )

    def test_a_bid_locked_undo_rejection_keeps_the_entry_ready_and_replayable(self):
        self.history.push(self._submit("undo"), self._submit("redo"))
        entry = self.history._undo_stack[-1]
        self.history.undo()
        self.assertEqual(entry.state, MutationHistoryState.UNDO_PENDING)
        changes_before = self.changes
        refusal = self._bid_locked()
        with self.assertNoLogs(self.history.logger, "WARNING"):
            self.submitted[0][1](refusal)
            self.submitted[0][1](refusal)
        self.assertEqual(self.changes - changes_before, 1)
        self.assertEqual(entry.state, MutationHistoryState.READY)
        self.assertIs(self.history._undo_stack[-1], entry)
        self.assertTrue(self.history.can_undo())
        self.assertFalse(self.history.can_redo())
        # the in-flight guard is released: the same entry replays once unlocked
        self.history.undo()
        self.assertEqual([label for label, _ in self.submitted], ["undo", "undo"])
        self.submitted[1][1](self._result(MutationOutcomeStatus.COMMITTED))
        self.assertEqual(entry.state, MutationHistoryState.READY)
        self.assertTrue(self.history.can_redo())
        self.assertFalse(self.history.can_undo())

    def test_a_bid_locked_redo_rejection_keeps_the_entry_ready_and_replayable(self):
        self.history.push(self._submit("undo"), self._submit("redo"))
        self.history.undo()
        self.submitted[0][1](self._result(MutationOutcomeStatus.COMMITTED))
        entry = self.history._redo_stack[-1]
        self.history.redo()
        self.assertEqual(entry.state, MutationHistoryState.REDO_PENDING)
        with self.assertNoLogs(self.history.logger, "WARNING"):
            self.submitted[1][1](self._bid_locked())
        self.assertEqual(entry.state, MutationHistoryState.READY)
        self.assertIs(self.history._redo_stack[-1], entry)
        self.assertTrue(self.history.can_redo())
        self.assertFalse(self.history.can_undo())
        self.history.redo()
        self.assertEqual(
            [label for label, _ in self.submitted], ["undo", "redo", "redo"]
        )

    def test_a_conflict_outcome_still_marks_the_entry_conflicted(self):
        # negative control: only the refusal reason is a plain refusal
        self.history.push(self._submit("undo"), self._submit("redo"))
        entry = self.history._undo_stack[-1]
        self.history.undo()
        self.submitted[0][1](self._result(MutationOutcomeStatus.CONFLICT))
        self.assertEqual(entry.state, MutationHistoryState.CONFLICTED)
        self.history.undo()
        self.assertEqual(len(self.submitted), 1)

    def test_a_rejection_without_a_reason_is_also_a_plain_refusal(self):
        self.history.push(self._submit("undo"), self._submit("redo"))
        entry = self.history._undo_stack[-1]
        self.history.undo()
        self.submitted[0][1](self._result(MutationOutcomeStatus.REJECTED))
        self.assertEqual(entry.state, MutationHistoryState.READY)
        self.assertTrue(self.history.can_undo())
