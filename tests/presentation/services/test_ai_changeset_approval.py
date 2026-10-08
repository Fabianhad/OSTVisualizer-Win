import os
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ost_visualizer.application.services.ai_changeset_store import (
    MAX_CLOSED_CHANGESETS,
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.application.services.ai_takeoff_tokens import (
    ProjectDataTokenReader,
)
from ost_visualizer.domain.entities.ai_changeset import (
    CHANGESET_EXPIRY_SECONDS,
    ERROR_CHANGESET_NOT_FOUND,
    IMPACT_HIGH,
    IMPACT_NORMAL,
    KIND_ELEMENTS,
    KIND_SCALE,
    STATUS_APPLIED,
    STATUS_APPLYING,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    STATUS_STALE,
    SUBJECT_OTHER,
    SUBJECT_SCALE,
    SUBJECT_THICKNESS,
    SUBJECT_TOP_ELEVATION,
    AiChangeset,
    ChangesetAssumption,
    ProposedCondition,
    ProposedScale,
    ProposedTakeoff,
)
from ost_visualizer.presentation.dialogs.ai_changeset_review_dialog import (
    REVIEW_DIALOG_TITLE,
    SQL_PER_MACHINE_NOTE,
    AiChangesetReviewDialog,
    valid_override,
)
from ost_visualizer.presentation.services.ai_changeset_approval import (
    APPLY_RAISED_MESSAGE,
    AiChangesetApprovalController,
    AiChangesetPlanPreview,
    ApplyOutcome,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import isValid

SQUARE = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)
INJECTED = "<b>APPROVE</b> <a href='x'>now</a>"


class RecordingApplier:
    def __init__(self):
        self.calls = []
        self.outcome = ApplyOutcome(True, AppliedChangeset(takeoff_uids=("T1",)), "")

    def apply(self, changeset, done):
        self.calls.append(changeset)
        done(self.outcome)


class EventRecorder(QtCore.QObject):
    def __init__(self, watched):
        super().__init__(watched)
        self.types = []
        watched.installEventFilter(self)

    def eventFilter(self, _watched, event):
        self.types.append(event.type())
        return False


class RecordingPreview:
    def __init__(self):
        self.shown = []
        self.cleared = 0
        self.current = None

    def show(self, changeset):
        self.shown.append(changeset.uid)
        self.current = changeset.uid

    def clear(self):
        self.cleared += 1
        self.current = None


def _changeset(assumptions=(), thickness=8.0):
    return AiChangeset(
        uid="",
        database_id="C:/jobs/a.mdb",
        bid_uid="7",
        bid_key="a" * 32,
        kind=KIND_ELEMENTS,
        created_at=0.0,
        conditions=(ProposedCondition("c1", "Slab 8in", thickness, 1200.0),),
        takeoffs=(ProposedTakeoff("t1", "page-1", "c1", SQUARE),),
        assumptions=assumptions,
        summary=INJECTED,
    )


class ApprovalTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.store = AiChangesetStore(clock=lambda: 100.0)
        self.proposals = AiChangesetProposals(self.store)
        self.applier = RecordingApplier()
        self.preview = RecordingPreview()
        self.sql = False
        self.controller = AiChangesetApprovalController(
            self.store,
            self.applier,
            self.preview,
            is_sql=lambda _database_id: self.sql,
        )
        self.addCleanup(self.controller.cleanup)
        self.finished = []
        self.controller.changeset_finished.connect(
            lambda uid, status: self.finished.append((uid, status))
        )

    def requested(self, changeset):
        added = self.proposals.add(changeset)
        self.proposals.request_apply(added.uid)
        self.controller.on_apply_requested(added.uid)
        return added.uid, self.controller.dialog_for(added.uid)

    def rebuild(self, store=None, applier=None, parent_widget=lambda: None):
        self.controller.cleanup()
        if store is not None:
            self.store = store
            self.proposals = AiChangesetProposals(store)
        if applier is not None:
            self.applier = applier
        self.controller = AiChangesetApprovalController(
            self.store,
            self.applier,
            self.preview,
            is_sql=lambda _database_id: self.sql,
            parent_widget=parent_widget,
        )
        self.addCleanup(self.controller.cleanup)
        self.finished = []
        self.controller.changeset_finished.connect(
            lambda uid, status: self.finished.append((uid, status))
        )

    def slot_errors(self):
        errors = []
        previous = sys.excepthook

        def restore():
            sys.excepthook = previous

        sys.excepthook = lambda kind, _value, _traceback: errors.append(kind)
        self.addCleanup(restore)
        return errors

    def prune(self, uid):
        self.proposals.discard(uid)
        for _index in range(MAX_CLOSED_CHANGESETS):
            self.proposals.discard(self.proposals.add(_changeset()).uid)


class ReviewDialogTests(ApprovalTestCase):
    def test_untrusted_text_is_shown_as_plain_text(self):
        assumption = ChangesetAssumption(
            "a1", SUBJECT_OTHER, "c1", "flat", INJECTED, "S-101", IMPACT_NORMAL
        )
        _uid, dialog = self.requested(_changeset((assumption,)))
        self.assertEqual(
            dialog.summary_label.textFormat(), QtCore.Qt.TextFormat.PlainText
        )
        self.assertEqual(dialog.summary_label.text(), INJECTED)
        self.assertEqual(dialog.assumption_table.item(0, 3).text(), INJECTED)
        self.assertFalse(dialog.summary_label.openExternalLinks())

    def test_quantity_delta_and_ghost_preview(self):
        uid, dialog = self.requested(_changeset())
        table = dialog.quantity_table
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "Slab 8in @T 100' - 0\"")
        self.assertEqual(table.item(0, 1).text(), "1")
        self.assertEqual(table.item(0, 2).text(), "1,200.00")
        self.assertEqual(table.item(0, 3).text(), "29.63")
        self.assertEqual(self.preview.shown, [uid])
        dialog.reject_button.click()
        self.assertGreaterEqual(self.preview.cleared, 1)

    def test_the_sql_note_appears_only_for_sql_bids(self):
        _uid, access = self.requested(_changeset())
        self.assertFalse(access.sql_note_label.isVisibleTo(access))
        self.sql = True
        _uid, sql = self.requested(_changeset())
        self.assertTrue(sql.sql_note_label.isVisibleTo(sql))
        self.assertEqual(sql.sql_note_label.text(), SQL_PER_MACHINE_NOTE)

    def test_closing_one_of_two_reviews_shows_the_other_reviews_ghost(self):
        first, _first_dialog = self.requested(_changeset())
        second, second_dialog = self.requested(_changeset())
        self.assertEqual(self.preview.current, second)
        second_dialog.reject_button.click()
        self.assertEqual(self.preview.current, first)
        third, third_dialog = self.requested(_changeset())
        self.assertEqual(self.preview.current, third)
        third_dialog.accept_button.click()
        self.assertEqual(self.finished[-1], (third, STATUS_APPLIED))
        self.assertEqual(self.preview.current, first)
        self.controller.dialog_for(first).close()
        self.assertIsNone(self.preview.current)

    def test_requesting_again_reuses_and_raises_the_open_dialog(self):
        uid, dialog = self.requested(_changeset())
        recorder = EventRecorder(dialog)
        self.controller.on_apply_requested(uid)
        self.assertIs(self.controller.dialog_for(uid), dialog)
        self.assertIn(QtCore.QEvent.Type.ZOrderChange, recorder.types)

    def test_requesting_again_shows_what_the_ai_revised_since(self):
        assumption = ChangesetAssumption(
            "a1", SUBJECT_OTHER, "c1", "flat", "r", "S-101", IMPACT_NORMAL
        )
        uid, dialog = self.requested(_changeset((assumption,)))
        revised = self.proposals.revise_assumption(uid, "a1", "sloped", "seen on S-102")
        self.controller.on_apply_requested(uid)
        self.assertEqual(dialog.shown_revision, revised.revision)
        self.assertEqual(dialog.assumption_table.item(0, 2).text(), "sloped")

    def test_a_review_whose_parent_window_was_destroyed_is_replaced(self):
        parent = QtWidgets.QWidget()
        self.rebuild(parent_widget=lambda: parent)
        uid, dialog = self.requested(_changeset())
        self.assertIs(dialog.parentWidget(), parent)
        parent.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(dialog))
        self.assertIsNone(self.controller.dialog_for(uid))
        parent = None
        self.controller.on_apply_requested(uid)
        replacement = self.controller.dialog_for(uid)
        self.assertIsNotNone(replacement)
        self.assertTrue(replacement.isVisible())

    def test_a_closed_review_is_deleted_once_events_are_processed(self):
        uid, dialog = self.requested(_changeset())
        dialog.close()
        self.assertTrue(isValid(dialog))
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(dialog))
        self.assertEqual(self.store.get(uid).status, STATUS_PENDING_APPROVAL)

    def test_cleanup_closes_every_review_and_clears_the_ghost(self):
        first, first_dialog = self.requested(_changeset())
        second, second_dialog = self.requested(_changeset())
        self.controller.cleanup()
        for uid, dialog in ((first, first_dialog), (second, second_dialog)):
            self.assertFalse(dialog.isVisible())
            self.assertIsNone(self.controller.dialog_for(uid))
            self.assertEqual(self.store.get(uid).status, STATUS_PENDING_APPROVAL)
        self.assertIsNone(self.preview.current)

    def test_cleanup_without_reviews_still_clears_the_ghost(self):
        self.controller.cleanup()
        self.assertEqual(self.preview.cleared, 1)

    def test_a_ghost_whose_changeset_was_pruned_is_cleared(self):
        first, first_dialog = self.requested(_changeset())
        _second, second_dialog = self.requested(_changeset())
        self.prune(first)
        second_dialog.reject_button.click()
        self.assertIsNone(self.preview.current)
        self.assertIs(self.controller.dialog_for(first), first_dialog)
        first_dialog.accept_button.click()
        self.assertEqual(first_dialog.error_label.text(), "Unknown changeset_id")
        self.assertTrue(first_dialog.error_label.isVisibleTo(first_dialog))
        self.assertEqual(self.controller.last_error(first), "Unknown changeset_id")


class ApprovalFlowTests(ApprovalTestCase):
    def test_accept_is_disabled_until_high_impact_assumptions_are_resolved(self):
        blocking = ChangesetAssumption(
            "a1",
            SUBJECT_THICKNESS,
            "c1",
            "8",
            "thickness not shown",
            "S-101",
            IMPACT_HIGH,
        )
        uid, dialog = self.requested(_changeset((blocking,), thickness=None))
        self.assertFalse(dialog.accept_button.isEnabled())
        self.assertEqual(dialog.quantity_table.item(0, 3).text(), "-")
        dialog.override_edit(0).setText("10")
        dialog.override_button(0).click()
        self.assertTrue(dialog.accept_button.isEnabled())
        self.assertEqual(dialog.assumption_table.item(0, 5).text(), "overridden: 10")
        dialog.accept_button.click()
        self.assertEqual(len(self.applier.calls), 1)
        self.assertEqual(
            self.applier.calls[0].resolved_conditions()[0].thickness_in, 10.0
        )
        self.assertEqual(self.proposals.get(uid).status, STATUS_APPLIED)
        self.assertEqual(self.finished, [(uid, STATUS_APPLIED)])
        self.assertIsNone(self.controller.dialog_for(uid))

    def test_accepting_an_assumption_as_proposed(self):
        blocking = ChangesetAssumption(
            "a1",
            SUBJECT_THICKNESS,
            "c1",
            "8",
            "thickness not shown",
            "S-101",
            IMPACT_HIGH,
        )
        _uid, dialog = self.requested(_changeset((blocking,), thickness=None))
        dialog.accept_assumption_button(0).click()
        self.assertTrue(dialog.accept_button.isEnabled())

    def test_invalid_overrides_are_refused_in_the_dialog(self):
        blocking = ChangesetAssumption(
            "a1",
            SUBJECT_THICKNESS,
            "c1",
            "8",
            "thickness not shown",
            "S-101",
            IMPACT_HIGH,
        )
        _uid, dialog = self.requested(_changeset((blocking,), thickness=None))
        for text in ("", "abc", "-1", "nan"):
            with self.subTest(text=text):
                dialog.override_edit(0).setText(text)
                dialog.override_button(0).click()
                self.assertFalse(dialog.accept_button.isEnabled())

    def test_reject_records_the_decision(self):
        uid, dialog = self.requested(_changeset())
        dialog.reject_button.click()
        self.assertEqual(self.proposals.get(uid).status, STATUS_REJECTED)
        self.assertEqual(self.applier.calls, [])
        self.assertEqual(self.finished, [(uid, STATUS_REJECTED)])

    def test_closing_the_dialog_leaves_the_request_pending(self):
        uid, dialog = self.requested(_changeset())
        dialog.close()
        self.assertEqual(self.proposals.get(uid).status, STATUS_PENDING_APPROVAL)
        self.assertIsNone(self.controller.dialog_for(uid))

    def test_failed_applies_are_reported_and_marked(self):
        self.applier.outcome = ApplyOutcome(False, None, "The bid is locked.")
        uid, dialog = self.requested(_changeset())
        dialog.accept_button.click()
        self.assertEqual(self.proposals.get(uid).status, STATUS_FAILED)
        self.assertEqual(self.finished, [(uid, STATUS_FAILED)])
        self.assertEqual(self.controller.last_error(uid), "The bid is locked.")

    def test_stale_changesets_cannot_be_accepted(self):
        tokens = {"page:page-1": "v1"}
        self.store = AiChangesetStore(
            clock=lambda: 100.0,
            token_reader=lambda _d, _b, resources: {
                r: tokens.get(r, "") for r in resources
            },
        )
        self.proposals = AiChangesetProposals(self.store)
        self.controller = AiChangesetApprovalController(
            self.store, self.applier, self.preview, is_sql=lambda _d: False
        )
        self.addCleanup(self.controller.cleanup)
        uid, dialog = self.requested(_changeset())
        tokens["page:page-1"] = "v2"
        dialog.accept_button.click()
        self.assertEqual(self.applier.calls, [])
        self.assertIn("changed", self.controller.last_error(uid))


class PlanPreviewTests(unittest.TestCase):
    def test_only_takeoffs_on_the_shown_page_are_previewed_with_their_holes(self):
        calls = []
        plan_view = type(
            "PlanView",
            (),
            {
                "current_page_uid": property(lambda self: "page-1"),
                "set_ai_preview": lambda self, page_uid, rings: calls.append(
                    (page_uid, list(rings))
                ),
                "clear_ai_preview": lambda self: calls.append("clear"),
            },
        )()
        hole = (10.0, 10.0, 20.0, 10.0, 20.0, 20.0)
        changeset = AiChangeset(
            uid="cs",
            database_id="d",
            bid_uid="7",
            bid_key="a" * 32,
            kind=KIND_ELEMENTS,
            created_at=0.0,
            takeoffs=(
                ProposedTakeoff("t1", "page-1", "c1", SQUARE, (hole,)),
                ProposedTakeoff("t2", "page-2", "c1", SQUARE),
            ),
        )
        preview = AiChangesetPlanPreview(lambda: plan_view)
        preview.show(changeset)
        preview.clear()
        self.assertEqual(calls, [("page-1", [SQUARE, hole]), "clear"])
        AiChangesetPlanPreview(lambda: None).show(changeset)
        AiChangesetPlanPreview(lambda: None).clear()
        self.assertEqual(calls, [("page-1", [SQUARE, hole]), "clear"])


class ReviewIntegrityTests(ApprovalTestCase):
    def test_a_value_revised_by_the_ai_after_display_is_never_accepted(self):
        blocking = ChangesetAssumption(
            "a1",
            SUBJECT_THICKNESS,
            "c1",
            "8",
            "thickness not shown",
            "S-101",
            IMPACT_HIGH,
        )
        uid, dialog = self.requested(_changeset((blocking,), thickness=None))
        self.proposals.revise_assumption(uid, "a1", "80", "revised by the AI")
        dialog.accept_assumption_button(0).click()
        (assumption,) = self.store.get(uid).assumptions
        self.assertEqual(assumption.status, "open")
        self.assertEqual(dialog.assumption_table.item(0, 2).text(), "80")
        self.assertTrue(dialog.error_label.isVisibleTo(dialog))
        dialog.accept_assumption_button(0).click()
        (assumption,) = self.store.get(uid).assumptions
        self.assertEqual(
            (assumption.status, assumption.effective_value), ("accepted", "80")
        )
        self.assertFalse(dialog.error_label.isVisibleTo(dialog))

    def test_accept_refuses_a_changeset_the_ai_changed_after_display(self):
        uid, dialog = self.requested(_changeset())
        self.proposals.add_assumption(
            uid, SUBJECT_OTHER, "c1", "6 in gap closed", "r", "S-101"
        )
        dialog.accept_button.click()
        self.assertEqual(self.applier.calls, [])
        self.assertEqual(self.store.get(uid).status, STATUS_PENDING_APPROVAL)
        self.assertEqual(dialog.assumption_table.rowCount(), 1)
        dialog.accept_button.click()
        self.assertEqual(len(self.applier.calls), 1)

    def test_enter_in_an_override_field_overrides_and_never_rejects_or_applies(self):
        blocking = ChangesetAssumption(
            "a1",
            SUBJECT_THICKNESS,
            "c1",
            "8",
            "thickness not shown",
            "S-101",
            IMPACT_HIGH,
        )
        other = ChangesetAssumption(
            "a2", SUBJECT_OTHER, "c1", "flat", "r", "S-101", IMPACT_NORMAL
        )
        uid, dialog = self.requested(_changeset((blocking, other), thickness=None))
        dialog.show()
        dialog.override_edit(0).setFocus()
        QTest.keyClicks(dialog.override_edit(0), "10")
        QTest.keyClick(dialog.override_edit(0), QtCore.Qt.Key.Key_Return)
        changeset = self.store.get(uid)
        self.assertEqual(changeset.status, STATUS_PENDING_APPROVAL)
        self.assertEqual(changeset.assumptions[0].effective_value, "10")
        self.assertTrue(dialog.accept_button.isEnabled())
        dialog.accept_button.setFocus()
        dialog.override_edit(1).setFocus()
        QTest.keyClick(dialog.override_edit(1), QtCore.Qt.Key.Key_Return)
        self.assertEqual(self.applier.calls, [])
        self.assertEqual(self.store.get(uid).status, STATUS_PENDING_APPROVAL)
        self.assertEqual(self.finished, [])

    def test_out_of_range_overrides_are_refused(self):
        self.assertFalse(valid_override(SUBJECT_TOP_ELEVATION, "1e300"))
        self.assertFalse(valid_override(SUBJECT_TOP_ELEVATION, "100000.5"))
        self.assertTrue(valid_override(SUBJECT_TOP_ELEVATION, "-100000"))
        self.assertFalse(valid_override(SUBJECT_THICKNESS, "120.5"))
        self.assertTrue(valid_override(SUBJECT_THICKNESS, "120"))

    def test_ai_text_is_shown_without_controls_and_capped(self):
        reason = "\u202eevil\u2066" + "r" * 2000
        assumption = ChangesetAssumption(
            "a1", SUBJECT_OTHER, "c1", "8\x1b[31m", reason, "S\u200f-101", IMPACT_NORMAL
        )
        changeset = replace(
            _changeset((assumption,)), summary="Add\u202e 1 slab" + "s" * 2000
        )
        _uid, dialog = self.requested(changeset)
        shown = [dialog.summary_label.text()] + [
            dialog.assumption_table.item(0, column).text() for column in (2, 3, 4)
        ]
        for text in shown:
            for character in ("\u202e", "\u2066", "\u200f", "\x1b"):
                self.assertNotIn(character, text)
            self.assertLessEqual(len(text), 500)
        self.assertTrue(dialog.summary_label.text().startswith("Add 1 slab"))


class RaisingApplier:
    def apply(self, changeset, done):
        raise RuntimeError("the queue refused the write")


class ApplyExceptionTests(ApprovalTestCase):
    def test_an_exception_while_applying_never_leaves_the_changeset_applying(self):
        self.controller.cleanup()
        self.controller = AiChangesetApprovalController(
            self.store,
            RaisingApplier(),
            self.preview,
            is_sql=lambda _database_id: False,
        )
        self.addCleanup(self.controller.cleanup)
        self.finished = []
        self.controller.changeset_finished.connect(
            lambda uid, status: self.finished.append((uid, status))
        )
        uid, dialog = self.requested(_changeset())
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_changeset_approval", "ERROR"
        ):
            dialog.accept_button.click()
        self.assertEqual(self.store.get(uid).status, STATUS_FAILED)
        self.assertEqual(self.finished, [(uid, STATUS_FAILED)])
        self.assertTrue(dialog.error_label.isVisibleTo(dialog))
        self.assertNotIn("queue refused", dialog.error_label.text())


LOGGER = "ost_visualizer.presentation.services.ai_changeset_approval"
APPLIED_OUTCOME = ApplyOutcome(True, AppliedChangeset(takeoff_uids=("T1",)), "")


class DeferredApplier:
    def __init__(self):
        self.pending = []

    def apply(self, changeset, done):
        self.pending.append((changeset, done))

    def complete(self, outcome):
        _changeset, done = self.pending.pop(0)
        done(outcome)


class CompletingThenRaisingApplier:
    def apply(self, changeset, done):
        done(APPLIED_OUTCOME)
        raise RuntimeError("raised after reporting")


class AsyncApplyTests(ApprovalTestCase):
    def setUp(self):
        super().setUp()
        self.rebuild(applier=DeferredApplier())
        self.errors = self.slot_errors()

    def test_a_second_accept_while_applying_is_refused(self):
        uid, dialog = self.requested(_changeset())
        dialog.accept_button.click()
        dialog.accept_button.click()
        self.assertEqual(len(self.applier.pending), 1)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLYING)
        self.assertIn("applying", dialog.error_label.text())
        self.assertTrue(dialog.error_label.isVisibleTo(dialog))
        self.assertEqual(self.finished, [])
        self.applier.complete(APPLIED_OUTCOME)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertEqual(self.finished, [(uid, STATUS_APPLIED)])
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(self.controller.dialog_for(uid))
        self.assertEqual(self.errors, [])

    def test_closing_the_review_while_applying_still_records_success(self):
        uid, dialog = self.requested(_changeset())
        dialog.accept_button.click()
        dialog.close()
        self.assertIsNone(self.controller.dialog_for(uid))
        self.assertEqual(self.store.get(uid).status, STATUS_APPLYING)
        self.applier.complete(APPLIED_OUTCOME)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertEqual(self.finished, [(uid, STATUS_APPLIED)])
        self.assertIsNone(self.preview.current)
        self.assertEqual(self.errors, [])

    def test_closing_the_review_while_applying_still_records_a_failure(self):
        uid, dialog = self.requested(_changeset())
        dialog.accept_button.click()
        dialog.close()
        self.applier.complete(ApplyOutcome(False, None, "The bid is locked."))
        self.assertEqual(self.store.get(uid).status, STATUS_FAILED)
        self.assertEqual(self.finished, [(uid, STATUS_FAILED)])
        self.assertEqual(self.controller.last_error(uid), "The bid is locked.")
        self.assertEqual(dialog.error_label.text(), "")
        self.assertEqual(self.errors, [])

    def test_a_completion_arriving_after_cleanup_is_still_recorded(self):
        uid, dialog = self.requested(_changeset())
        dialog.accept_button.click()
        self.controller.cleanup()
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(self.controller.dialog_for(uid))
        self.applier.complete(APPLIED_OUTCOME)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertEqual(self.finished, [(uid, STATUS_APPLIED)])
        self.assertIsNone(self.preview.current)
        self.assertEqual(self.errors, [])


class ControllerEdgeTests(ApprovalTestCase):
    def test_approving_after_expiry_is_refused(self):
        now = [100.0]
        self.rebuild(store=AiChangesetStore(clock=lambda: now[0]))
        uid, dialog = self.requested(_changeset())
        now[0] += CHANGESET_EXPIRY_SECONDS
        dialog.accept_button.click()
        self.assertEqual(self.applier.calls, [])
        self.assertEqual(self.store.get(uid).status, STATUS_EXPIRED)
        self.assertIn("expired", dialog.error_label.text())
        self.assertIn("expired", self.controller.last_error(uid))
        self.assertEqual(self.finished, [])

    def test_switching_bids_between_request_and_accept_makes_it_stale(self):
        bid = [SimpleNamespace(file_path="C:/jobs/a.mdb", bid_uid="7")]
        project = SimpleNamespace(
            get_current_bid_ref=lambda: bid[0], get_page=lambda _uid: None
        )
        self.rebuild(
            store=AiChangesetStore(
                clock=lambda: 100.0, token_reader=ProjectDataTokenReader(project)
            )
        )
        uid, dialog = self.requested(_changeset())
        bid[0] = SimpleNamespace(file_path="C:/jobs/a.mdb", bid_uid="8")
        dialog.accept_button.click()
        self.assertEqual(self.applier.calls, [])
        self.assertEqual(self.store.get(uid).status, STATUS_STALE)
        self.assertIn("changed", dialog.error_label.text())
        self.assertEqual(self.finished, [])

    def test_an_unknown_request_is_ignored_and_logged(self):
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.controller.on_apply_requested("missing")
        self.assertIn(ERROR_CHANGESET_NOT_FOUND, logs.output[0])
        self.assertIsNone(self.controller.dialog_for("missing"))
        self.assertEqual(self.preview.shown, [])

    def test_unknown_changesets_without_a_review_record_the_error(self):
        self.controller.reject("missing")
        self.assertEqual(self.controller.last_error("missing"), "Unknown changeset_id")
        self.controller.accept("missing")
        self.assertEqual(self.controller.last_error("missing"), "Unknown changeset_id")
        self.assertEqual(self.finished, [])

    def test_rejecting_without_a_review_clears_the_ghost(self):
        added = self.proposals.add(_changeset())
        self.proposals.request_apply(added.uid)
        self.preview.show(added)
        self.controller.reject(added.uid)
        self.assertEqual(self.store.get(added.uid).status, STATUS_REJECTED)
        self.assertEqual(self.finished, [(added.uid, STATUS_REJECTED)])
        self.assertIsNone(self.preview.current)

    def test_rejecting_a_hidden_review_forgets_it(self):
        uid, dialog = self.requested(_changeset())
        dialog.hide()
        self.controller.reject(uid)
        self.assertIsNone(self.controller.dialog_for(uid))
        self.assertEqual(self.store.get(uid).status, STATUS_REJECTED)

    def test_rejecting_closes_the_review_at_once(self):
        uid, dialog = self.requested(_changeset())
        self.assertTrue(dialog.isVisible())
        dialog.reject_button.click()
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(self.controller.dialog_for(uid))

    def test_a_refused_reject_is_reported_without_refreshing_the_review(self):
        assumption = ChangesetAssumption(
            "a1", SUBJECT_OTHER, "c1", "flat", "r", "S-101", IMPACT_NORMAL
        )
        uid, dialog = self.requested(_changeset((assumption,)))
        self.proposals.revise_assumption(uid, "a1", "sloped", "r")
        self.proposals.discard(uid)
        dialog.reject_button.click()
        message = "The changeset is discarded and cannot do that"
        self.assertEqual(dialog.error_label.text(), message)
        self.assertTrue(dialog.error_label.isVisibleTo(dialog))
        self.assertEqual(self.controller.last_error(uid), message)
        self.assertEqual(dialog.assumption_table.item(0, 2).text(), "flat")
        self.assertIs(self.controller.dialog_for(uid), dialog)
        self.assertEqual(self.finished, [])

    def test_a_success_without_a_record_is_treated_as_a_failure(self):
        self.applier.outcome = ApplyOutcome(True, None)
        uid, dialog = self.requested(_changeset())
        dialog.accept_button.click()
        message = "The changeset could not be applied."
        self.assertEqual(self.store.get(uid).status, STATUS_FAILED)
        self.assertEqual(self.finished, [(uid, STATUS_FAILED)])
        self.assertEqual(self.controller.last_error(uid), message)
        self.assertEqual(dialog.error_label.text(), message)

    def test_an_applier_that_raises_after_reporting_keeps_its_outcome(self):
        self.rebuild(applier=CompletingThenRaisingApplier())
        uid, _dialog = self.requested(_changeset())
        with self.assertLogs(LOGGER, "ERROR"):
            self.controller.accept(uid)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertEqual(self.finished, [(uid, STATUS_APPLIED)])

    def test_assumption_clicks_from_a_forgotten_review_raise_nothing(self):
        errors = self.slot_errors()
        assumption = ChangesetAssumption(
            "a1", SUBJECT_OTHER, "c1", "flat", "r", "S-101", IMPACT_NORMAL
        )
        uid, dialog = self.requested(_changeset((assumption,)))
        dialog.close()
        dialog.accept_assumption_button(0).click()
        dialog.override_edit(0).setText("5")
        dialog.override_button(0).click()
        self.assertEqual(errors, [])
        self.assertIsNone(self.controller.dialog_for(uid))

    def test_apply_outcomes_are_immutable(self):
        outcome = ApplyOutcome(False, None, APPLY_RAISED_MESSAGE, "apply_failed")
        with self.assertRaises(FrozenInstanceError):
            outcome.success = True


def _scale_changeset(
    scale=ProposedScale("page-1", 0.25, 48.0, 1.0, 96.0), assumptions=()
):
    return AiChangeset(
        uid="cs",
        database_id="d",
        bid_uid="7",
        bid_key="a" * 32,
        kind=KIND_SCALE,
        created_at=0.0,
        scale=scale,
        assumptions=assumptions,
    )


def _assumption(uid, subject, impact=IMPACT_HIGH):
    return ChangesetAssumption(uid, subject, "c1", "8", "r", "S-101", impact)


class ReviewDialogWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def dialog(self, changeset, is_sql=False):
        dialog = AiChangesetReviewDialog(changeset, is_sql)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def elements(self, assumptions=()):
        return replace(_changeset(assumptions), uid="cs", summary="")

    def test_the_window_is_a_titled_modeless_dialog_kept_after_close(self):
        dialog = self.dialog(self.elements())
        self.assertEqual(dialog.windowTitle(), REVIEW_DIALOG_TITLE)
        self.assertFalse(dialog.isModal())
        self.assertFalse(
            dialog.testAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        )
        self.assertEqual(dialog.changeset_uid, "cs")
        self.assertFalse(dialog.error_label.isVisibleTo(dialog))
        self.assertEqual(dialog.error_label.text(), "")

    def test_the_layout_stacks_text_tables_notes_and_buttons(self):
        dialog = self.dialog(self.elements())
        layout = dialog.layout()
        self.assertEqual(layout.count(), 7)
        intro = layout.itemAt(0).widget()
        self.assertTrue(intro.text().startswith("An AI client asked"))
        expected = (
            dialog.summary_label,
            dialog.quantity_table,
            dialog.assumption_table,
            dialog.sql_note_label,
            dialog.error_label,
        )
        for index, widget in enumerate(expected, start=1):
            self.assertIs(layout.itemAt(index).widget(), widget)
        buttons = layout.itemAt(6).layout()
        self.assertEqual(buttons.count(), 3)
        self.assertIsNotNone(buttons.itemAt(0).spacerItem())
        self.assertEqual(buttons.stretch(0), 1)
        self.assertIs(buttons.itemAt(1).widget(), dialog.reject_button)
        self.assertIs(buttons.itemAt(2).widget(), dialog.accept_button)
        for label in (intro, dialog.summary_label, dialog.sql_note_label):
            self.assertEqual(label.textFormat(), QtCore.Qt.TextFormat.PlainText)
            self.assertEqual(
                label.textInteractionFlags(),
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse,
            )
            self.assertTrue(label.wordWrap())
            self.assertFalse(label.openExternalLinks())

    def test_tables_have_headers_and_read_only_items(self):
        dialog = self.dialog(self.elements((_assumption("a1", SUBJECT_OTHER),)))
        for table, columns in (
            (
                dialog.quantity_table,
                ["Condition", "Takeoffs", "Area (SF)", "Volume (CY)"],
            ),
            (
                dialog.assumption_table,
                ["Subject", "Impact", "Proposed", "Reason", "Sheet", "Status", ""],
            ),
        ):
            self.assertEqual(
                [
                    table.horizontalHeaderItem(c).text()
                    for c in range(table.columnCount())
                ],
                columns,
            )
            self.assertTrue(table.verticalHeader().isHidden())
            self.assertEqual(table.rowCount(), 1)
            for column in range(
                table.columnCount() - (table is dialog.assumption_table)
            ):
                flags = table.item(0, column).flags()
                self.assertFalse(flags & QtCore.Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(dialog.assumption_table.item(0, 5).text(), "open")

    def test_assumption_rows_carry_their_own_action_widgets(self):
        dialog = self.dialog(self.elements((_assumption("a1", SUBJECT_OTHER),)))
        actions = dialog.assumption_table.cellWidget(0, 6)
        self.assertIs(dialog.accept_assumption_button(0).parentWidget(), actions)
        layout = actions.layout()
        self.assertEqual(layout.contentsMargins(), QtCore.QMargins(0, 0, 0, 0))
        self.assertEqual(
            [layout.itemAt(index).widget() for index in range(layout.count())],
            [
                dialog.accept_assumption_button(0),
                dialog.override_edit(0),
                dialog.override_button(0),
            ],
        )
        self.assertEqual(dialog.override_edit(0).placeholderText(), "Value")
        for button in (
            dialog.reject_button,
            dialog.accept_button,
            dialog.accept_assumption_button(0),
            dialog.override_button(0),
        ):
            self.assertFalse(button.isDefault())
            self.assertFalse(button.autoDefault())

    def test_scale_assumptions_can_only_be_accepted(self):
        dialog = self.dialog(
            _scale_changeset(
                assumptions=(
                    _assumption("a1", SUBJECT_SCALE),
                    _assumption("a2", SUBJECT_OTHER, IMPACT_NORMAL),
                )
            )
        )
        self.assertFalse(dialog.override_edit(0).isEnabled())
        self.assertFalse(dialog.override_button(0).isEnabled())
        self.assertTrue(dialog.accept_assumption_button(0).isEnabled())
        self.assertTrue(dialog.override_edit(1).isEnabled())
        self.assertTrue(dialog.override_button(1).isEnabled())

    def test_default_summaries_describe_the_change(self):
        cases = (
            (_scale_changeset(), "Set the page scale to 0.25 : 48 (was 1 : 96)."),
            (_scale_changeset(scale=None), "Add 0 takeoff(s) in 0 new condition(s)."),
            (
                replace(
                    self.elements(), scale=ProposedScale("page-1", 1.0, 2.0, 3.0, 4.0)
                ),
                "Add 1 takeoff(s) in 1 new condition(s).",
            ),
        )
        for changeset, summary in cases:
            with self.subTest(summary=summary):
                self.assertEqual(self.dialog(changeset).summary_label.text(), summary)

    def test_tables_without_rows_are_hidden_until_rows_arrive(self):
        dialog = self.dialog(_scale_changeset())
        self.assertTrue(dialog.quantity_table.isHidden())
        self.assertTrue(dialog.assumption_table.isHidden())
        dialog.refresh(self.elements((_assumption("a1", SUBJECT_OTHER),)))
        self.assertFalse(dialog.quantity_table.isHidden())
        self.assertFalse(dialog.assumption_table.isHidden())

    def test_invalid_overrides_name_the_expected_unit_and_valid_ones_clear_it(self):
        dialog = self.dialog(
            self.elements(
                (
                    _assumption("a1", SUBJECT_THICKNESS),
                    _assumption("a2", SUBJECT_TOP_ELEVATION),
                    _assumption("a3", SUBJECT_OTHER, IMPACT_NORMAL),
                )
            )
        )
        overridden = []
        dialog.assumption_overridden.connect(
            lambda uid, value: overridden.append((uid, value))
        )
        for row, unit in ((0, "inches"), (1, "inches"), (2, "a number")):
            with self.subTest(row=row):
                dialog.override_edit(row).setText("abc")
                dialog.override_button(row).click()
                self.assertEqual(
                    dialog.error_label.text(), f"Enter a valid value in {unit}."
                )
                self.assertTrue(dialog.error_label.isVisibleTo(dialog))
                dialog.override_edit(row).setText(" 5 ")
                dialog.override_button(row).click()
                self.assertFalse(dialog.error_label.isVisibleTo(dialog))
        self.assertEqual(overridden, [("a1", "5"), ("a2", "5"), ("a3", "5")])

    def test_override_bounds_per_subject(self):
        cases = (
            (SUBJECT_THICKNESS, "0", False),
            (SUBJECT_THICKNESS, "0.5", True),
            (SUBJECT_THICKNESS, "inf", False),
            (SUBJECT_TOP_ELEVATION, "100000", True),
            (SUBJECT_TOP_ELEVATION, "nan", False),
            (SUBJECT_OTHER, "inf", False),
            (SUBJECT_OTHER, "abc", False),
            (SUBJECT_OTHER, "0", False),
            (SUBJECT_OTHER, "0.5", True),
            (SUBJECT_OTHER, "200", True),
            (SUBJECT_SCALE, "-1", False),
        )
        for subject, text, expected in cases:
            with self.subTest(subject=subject, text=text):
                self.assertIs(valid_override(subject, text), expected)


if __name__ == "__main__":
    unittest.main()
