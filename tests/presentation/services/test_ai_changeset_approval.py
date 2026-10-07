import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.domain.entities.ai_changeset import (
    IMPACT_HIGH,
    IMPACT_NORMAL,
    KIND_ELEMENTS,
    STATUS_APPLIED,
    STATUS_FAILED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    SUBJECT_OTHER,
    SUBJECT_THICKNESS,
    SUBJECT_TOP_ELEVATION,
    AiChangeset,
    ChangesetAssumption,
    ProposedCondition,
    ProposedTakeoff,
)
from ost_visualizer.presentation.dialogs.ai_changeset_review_dialog import (
    SQL_PER_MACHINE_NOTE,
    valid_override,
)
from ost_visualizer.presentation.services.ai_changeset_approval import (
    AiChangesetApprovalController,
    AiChangesetPlanPreview,
    ApplyOutcome,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

SQUARE = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)
INJECTED = "<b>APPROVE</b> <a href='x'>now</a>"


class RecordingApplier:
    def __init__(self):
        self.calls = []
        self.outcome = ApplyOutcome(True, AppliedChangeset(takeoff_uids=("T1",)), "")

    def apply(self, changeset, done):
        self.calls.append(changeset)
        done(self.outcome)


class RecordingPreview:
    def __init__(self):
        self.shown = []
        self.cleared = 0

    def show(self, changeset):
        self.shown.append(changeset.uid)

    def clear(self):
        self.cleared += 1


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

    def test_requesting_again_reuses_the_open_dialog(self):
        uid, dialog = self.requested(_changeset())
        self.controller.on_apply_requested(uid)
        self.assertIs(self.controller.dialog_for(uid), dialog)


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


if __name__ == "__main__":
    unittest.main()
