import unittest
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
)
from ost_visualizer.application.dtos.ai_changeset_write_dtos import (
    AiChangesetCommit,
    AiChangesetUndoPlan,
    AiChangesetWritePlan,
    AiChangesetWriteResult,
    AiScaleUndoPlan,
    AiTakeoffWrite,
    AppliedChangeset,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    MutationOutcomeStatus,
    MutationRejectionReason,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationConflict,
)
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.services.project_write_service import (
    _ai_changeset_authoritative_result,
)
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.application.services.ai_takeoff_tokens import ProjectDataTokenReader
from ost_visualizer.domain.entities.ai_takeoff import SidecarWriteRefused
from ost_visualizer.domain.entities.ai_changeset import (
    DATABASE_UNRESOLVED_MESSAGE,
    IMPACT_HIGH,
    IMPACT_NORMAL,
    KIND_ELEMENTS,
    KIND_SCALE,
    STATUS_APPLIED,
    STATUS_UNDONE,
    SUBJECT_OTHER,
    SUBJECT_THICKNESS,
    AiChangeset,
    ChangesetAssumption,
    ProposedCondition,
    ProposedScale,
    ProposedTakeoff,
    apply_block_for,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_AREA_VOLUME,
    UOM_CUBIC_YARDS,
    UOM_SQUARE_FEET,
)
from ost_visualizer.presentation.services.ai_changeset_applier import AiChangesetApplier
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from tests.application.services.test_project_write_service import _Harness, _Seq

DB = "C:/jobs/a.mdb"
SQUARE = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)
HOLE = (120.0, 120.0, 240.0, 120.0, 240.0, 240.0, 120.0, 240.0)


def _queued(status, **fields):
    return QueuedMutationResult(
        database_id=DB,
        runtime_generation=1,
        operation_id="00000000-0000-4000-8000-000000000002",
        outcome_status=status,
        **fields,
    )


def _conflict():
    return SynchronizationConflict(DB, ResourceRef("takeoff", "103", 7), "stale")


class FakeProjectData:
    def __init__(self):
        self.bid_ref = BidRef(DB, "7")
        self.pages = {
            "p1": Page(uid="p1", name="P1", scale_factor1=0.125, scale_factor2=12.0)
        }
        self.conditions = {"42": Condition(uid="42", name="Existing")}
        self.folders = {}
        self.takeoffs = [Takeoff("t-old", "42", "p1", position=[1.0, 2.0, 3.0, 4.0])]
        self.locked = False

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_page(self, uid):
        return self.pages.get(uid)

    def get_bid_conditions(self):
        return dict(self.conditions)

    def get_bid_condition_folders(self):
        return dict(self.folders)

    def get_page_takeoffs(self, page_uid):
        return [t for t in self.takeoffs if t.page_uid == page_uid]

    def get_all_takeoffs(self):
        return list(self.takeoffs)

    def is_current_bid_locked(self):
        return self.locked


class FakeWriteService:
    def __init__(self, project):
        self.project = project
        self.sql = False
        self.calls = []
        self.next_commit = None
        self.next_undo_commit = None
        self.queue_outcome = None
        self.error = None
        self.counter = 100
        self.scale_ok = True

    def uses_sql_collaboration_mutations(self, _database_id):
        return self.sql

    def _fail_or_raise(self):
        if self.error is not None:
            raise self.error

    def _commit_plan(self, plan):
        folder_uid = plan.existing_folder_uid
        created = False
        if plan.conditions and not folder_uid:
            self.counter += 1
            folder_uid = str(self.counter)
            created = True
            self.project.folders[folder_uid] = BidConditionFolder(
                uid=folder_uid, bid_uid="7", name=plan.folder_name
            )
        conditions = []
        for key, spec in plan.conditions:
            self.counter += 1
            uid = str(self.counter)
            conditions.append((key, uid))
            self.project.conditions[uid] = Condition(
                uid=uid, name=spec.name, folder_uid=folder_uid
            )
        uids = []
        mapping = dict(conditions)
        for item in plan.takeoffs:
            for ring in (item.position, *item.holes):
                self.counter += 1
                uids.append(str(self.counter))
                self.project.takeoffs.append(
                    Takeoff(
                        str(self.counter),
                        mapping.get(item.condition_key, item.condition_key),
                        item.page_uid,
                        position=list(ring),
                    )
                )
        return AiChangesetWriteResult(
            folder_uid, created, tuple(conditions), tuple(uids)
        )

    def execute_ai_changeset_local(self, database_id, bid_uid, plan):
        self.calls.append(("apply", database_id, bid_uid, plan))
        self._fail_or_raise()
        if self.next_commit is not None:
            return self.next_commit
        return AiChangesetCommit(True, self._commit_plan(plan))

    def queue_ai_changeset(self, database_id, bid_uid, plan, callback):
        self.calls.append(("queue_apply", database_id, bid_uid, plan))
        self._fail_or_raise()
        if self.queue_outcome is not None:
            callback(self.queue_outcome)
            return 1
        result = self._commit_plan(plan)
        folder_map = (("0", result.folder_uid),) if result.created_folder else ()
        callback(
            QueuedMutationResult(
                database_id=database_id,
                runtime_generation=1,
                operation_id="00000000-0000-4000-8000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=result.takeoff_uids,
                    created_uid_maps=(
                        ("condition_folders", folder_map),
                        ("conditions", result.condition_uids),
                        (
                            "takeoffs",
                            tuple(
                                (str(i), uid)
                                for i, uid in enumerate(result.takeoff_uids)
                            ),
                        ),
                    ),
                ),
            )
        )
        return 1

    def execute_ai_changeset_undo_local(self, database_id, bid_uid, plan):
        self.calls.append(("undo", plan))
        if self.next_undo_commit is not None:
            return self.next_undo_commit
        return self._undo_plan(plan)

    def queue_ai_changeset_undo(self, database_id, bid_uid, plan, callback):
        self.calls.append(("queue_undo", plan))
        if self.queue_outcome is not None:
            callback(self.queue_outcome)
            return 2
        self._undo_plan(plan)
        callback(_queued(MutationOutcomeStatus.COMMITTED))
        return 2

    def queue_page_setting_if_sql(
        self, database_id, page_uid, setting_kind, values, *, owning_surface, callback
    ):
        self.calls.append(
            ("queue_scale", page_uid, setting_kind, tuple(values), owning_surface)
        )
        if self.queue_outcome is not None:
            callback(self.queue_outcome)
            return True
        page = self.project.pages[page_uid]
        self.project.pages[page_uid] = replace(
            page, scale_factor1=values[0], scale_factor2=values[1]
        )
        callback(_queued(MutationOutcomeStatus.COMMITTED))
        return True

    def _undo_plan(self, plan):
        self.project.takeoffs = [
            t for t in self.project.takeoffs if t.uid not in plan.takeoff_uids
        ]
        for uid in plan.condition_uids:
            self.project.conditions.pop(uid, None)
        if plan.folder_uid:
            self.project.folders.pop(plan.folder_uid, None)
        return AiChangesetCommit(True, AiChangesetWriteResult(None, False, (), ()))

    def save_page_scale(self, database_id, page_uid, sf1, sf2):
        self.calls.append(("scale", page_uid, sf1, sf2))
        if not self.scale_ok:
            return False
        page = self.project.pages[page_uid]
        self.project.pages[page_uid] = replace(
            page, scale_factor1=sf1, scale_factor2=sf2
        )
        self.project.takeoffs = [
            replace(t, position=[v * 2 for v in t.position])
            for t in self.project.takeoffs
        ]
        return True

    def execute_ai_scale_undo_local(self, database_id, bid_uid, plan):
        self.calls.append(("scale_undo", plan))
        page = self.project.pages[plan.page_uid]
        self.project.pages[plan.page_uid] = replace(
            page, scale_factor1=plan.scale_factor1, scale_factor2=plan.scale_factor2
        )
        positions = dict(plan.positions)
        self.project.takeoffs = [
            replace(t, position=list(positions.get(t.uid, t.position)))
            for t in self.project.takeoffs
        ]
        return AiChangesetCommit(True, AiChangesetWriteResult(None, False, (), ()))


def _scale_changeset():
    return AiChangeset(
        uid="",
        database_id=DB,
        bid_uid="7",
        bid_key="a" * 32,
        kind=KIND_SCALE,
        created_at=0.0,
        scale=ProposedScale("p1", 0.25, 12.0, 0.125, 12.0, 0.2),
    )


def _elements(holes=(), condition_key="c1", conditions=None):
    return AiChangeset(
        uid="",
        database_id=DB,
        bid_uid="7",
        bid_key="a" * 32,
        kind=KIND_ELEMENTS,
        created_at=0.0,
        conditions=(
            conditions
            if conditions is not None
            else (ProposedCondition("c1", "Slab 8in", 8.0, 1200.0),)
        ),
        takeoffs=(ProposedTakeoff("t1", "p1", condition_key, SQUARE, holes),),
        summary="One slab",
    )


class ApplierTestCase(unittest.TestCase):
    def setUp(self):
        self.project = FakeProjectData()
        self.write = FakeWriteService(self.project)
        self.tokens = ProjectDataTokenReader(self.project)
        self.store = AiChangesetStore(clock=lambda: 10.0, token_reader=self.tokens)
        self.proposals = AiChangesetProposals(self.store)
        self.undo_service = UndoRedoService()
        self.undo_service.set_active_bid(BidRef(DB, "7"))
        self.denial = ""
        self.audit = []
        self.recorded = []
        self.refuse_sidecar = None
        self.refusals = []
        self.applier = AiChangesetApplier(
            write_service=self.write,
            project_data=self.project,
            undo_service=self.undo_service,
            store=self.store,
            token_reader=self.tokens,
            access_check=lambda changeset: self.denial,
            layer_uid=lambda: "L9",
            area_uid=lambda page_uid: "A1",
            session_folder_name="AI 2026-10-07 14:05",
            audit=lambda event, details: self.audit.append((event, details)),
            record_assumptions=self._record,
            undo_refused=lambda label, message, discard: self.refusals.append(
                (label, message, discard)
            ),
        )

    def _record(self, assumptions):
        if self.refuse_sidecar is not None:
            raise self.refuse_sidecar
        self.recorded.append(tuple(assumptions))

    def approve_and_apply(self, changeset):
        added = self.proposals.add(changeset)
        self.proposals.request_apply(added.uid)
        approved = self.store.approve(added.uid)
        outcomes = []
        self.applier.apply(approved, outcomes.append)
        outcome = outcomes[0]
        if outcome.success:
            self.store.mark_applied(added.uid, outcome.record)
        return added.uid, outcome

    def undo(self, uid):
        outcomes = []
        self.applier.undo(uid, outcomes.append)
        return outcomes[0]


class ElementApplyTests(ApplierTestCase):
    def test_slab_conditions_follow_the_conventions(self):
        _uid, outcome = self.approve_and_apply(_elements(holes=(HOLE,)))
        self.assertTrue(outcome.success, outcome.message)
        _kind, database_id, bid_uid, plan = self.write.calls[0]
        self.assertEqual((database_id, bid_uid), (DB, "7"))
        self.assertEqual(plan.folder_name, "AI 2026-10-07 14:05")
        self.assertIsNone(plan.existing_folder_uid)
        ((key, spec),) = plan.conditions
        self.assertEqual(key, "c1")
        self.assertEqual(spec.name, "Slab 8in @T 100' - 0\"")
        self.assertEqual(
            (spec.condition_type, spec.thickness, spec.layer_uid, spec.color_fill),
            (Condition.TYPE_AREA, 8.0, "L9", 33023),
        )
        self.assertEqual(
            (spec.calc_type1, spec.uom1, spec.calc_type2, spec.uom2, spec.uom3),
            (CALC_AREA, UOM_SQUARE_FEET, CALC_AREA_VOLUME, UOM_CUBIC_YARDS, -1),
        )
        (takeoff,) = plan.takeoffs
        self.assertEqual(
            (takeoff.page_uid, takeoff.area_uid, takeoff.holes), ("p1", "A1", (HOLE,))
        )
        self.assertEqual(outcome.record.condition_uids, ("102",))
        self.assertEqual(outcome.record.takeoff_uids, ("103", "104"))
        self.assertTrue(outcome.record.created_folder)
        self.assertEqual(self.undo_service.undo_label(), "AI: One slab")
        self.assertEqual(self.audit[-1][0], "applied")

    def test_existing_conditions_are_referenced_not_created(self):
        _uid, outcome = self.approve_and_apply(
            _elements(condition_key="existing:42", conditions=())
        )
        plan = self.write.calls[0][3]
        self.assertEqual(plan.conditions, ())
        self.assertEqual(plan.takeoffs[0].condition_key, "42")
        self.assertEqual(plan.existing_condition_uids, ("42",))
        self.assertTrue(outcome.success)

    def test_the_session_folder_is_reused_while_it_exists(self):
        self.approve_and_apply(_elements())
        self.approve_and_apply(_elements())
        self.assertEqual(self.write.calls[1][3].existing_folder_uid, "101")
        self.project.folders.clear()
        self.approve_and_apply(_elements())
        self.assertIsNone(self.write.calls[2][3].existing_folder_uid)

    def test_denied_access_writes_nothing(self):
        self.denial = "AI takeoff needs permission to place takeoffs."
        _uid, outcome = self.approve_and_apply(_elements())
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.code, "feature_denied")
        self.assertEqual(self.write.calls, [])

    def test_locked_and_conflicting_writes_map_to_plan_error_codes(self):
        for commit, code in (
            (
                AiChangesetCommit(False, message="The bid is locked.", locked=True),
                "locked_bid",
            ),
            (
                AiChangesetCommit(False, message="Edited elsewhere.", conflict=True),
                "lease_conflict",
            ),
            (AiChangesetCommit(False, message="Disk full."), "apply_failed"),
        ):
            with self.subTest(code=code):
                self.setUp()
                self.write.next_commit = commit
                _uid, outcome = self.approve_and_apply(_elements())
                self.assertEqual((outcome.success, outcome.code), (False, code))
                self.assertEqual(self.undo_service.undo_label(), "")

    def test_sql_bids_use_the_collaboration_queue(self):
        self.write.sql = True
        _uid, outcome = self.approve_and_apply(_elements(holes=(HOLE,)))
        self.assertEqual(self.write.calls[0][0], "queue_apply")
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.record.folder_uid, "101")
        self.assertTrue(outcome.record.created_folder)
        self.assertEqual(outcome.record.condition_uids, ("102",))
        self.assertEqual(outcome.record.takeoff_uids, ("103", "104"))


class AssumptionPersistenceTests(ApplierTestCase):
    def test_applied_assumptions_are_recorded_with_their_final_values(self):
        assumptions = (
            ChangesetAssumption(
                "a1", SUBJECT_THICKNESS, "c1", "8", "not shown", "S-101", IMPACT_HIGH
            ),
            ChangesetAssumption(
                "a2", SUBJECT_OTHER, "c1", "flat", "ramp", "S-102", IMPACT_NORMAL
            ),
        )
        changeset = replace(
            _elements(),
            conditions=(ProposedCondition("c1", "Slab", None, 0.0),),
            assumptions=assumptions,
        )
        added = self.proposals.add(changeset)
        self.proposals.request_apply(added.uid)
        self.store.override_assumption(added.uid, "a1", "10")
        approved = self.store.approve(added.uid)
        outcomes = []
        self.applier.apply(approved, outcomes.append)
        self.assertTrue(outcomes[0].success)
        (recorded,) = self.recorded
        self.assertEqual(
            [(item.uid, item.value, item.status, item.impact) for item in recorded],
            [
                (f"{added.uid}-a1", "10", "overridden", "high"),
                (f"{added.uid}-a2", "flat", "open", "normal"),
            ],
        )

    def test_a_refused_sidecar_never_undoes_a_committed_apply(self):
        self.refuse_sidecar = SidecarWriteRefused("fingerprint_mismatch")
        changeset = replace(
            _elements(),
            assumptions=(
                ChangesetAssumption(
                    "a1", SUBJECT_OTHER, "c1", "x", "y", "z", IMPACT_NORMAL
                ),
            ),
        )
        _uid, outcome = self.approve_and_apply(changeset)
        self.assertTrue(outcome.success)
        self.assertIn(
            ("sidecar_refused", {"status": "fingerprint_mismatch"}), self.audit
        )


class UndoTests(ApplierTestCase):
    def test_undo_removes_what_it_created_and_the_empty_session_folder(self):
        uid, outcome = self.approve_and_apply(_elements(holes=(HOLE,)))
        result = self.undo(uid)
        self.assertTrue(result.success, result.message)
        plan = self.write.calls[-1][1]
        self.assertEqual(
            (plan.takeoff_uids, plan.condition_uids, plan.folder_uid),
            (("103", "104"), ("102",), "101"),
        )
        self.assertEqual(self.store.get(uid).status, STATUS_UNDONE)
        self.assertEqual(self.audit[-1][0], "undone")

    def test_the_folder_stays_when_other_conditions_use_it(self):
        first, _ = self.approve_and_apply(_elements())
        self.approve_and_apply(_elements())
        self.assertTrue(self.undo(first).success)
        plan = self.write.calls[-1][1]
        self.assertIsNone(plan.folder_uid)

    def test_a_reused_folder_is_never_removed_even_when_empty(self):
        first, _ = self.approve_and_apply(_elements())
        for uid in self.store.applied_record(first).condition_uids:
            self.project.conditions.pop(uid)
        second, _ = self.approve_and_apply(_elements())
        self.assertFalse(self.store.applied_record(second).created_folder)
        self.assertTrue(self.undo(second).success)
        plan = self.write.calls[-1][1]
        self.assertIsNone(plan.folder_uid)

    def test_undo_is_refused_when_created_objects_changed(self):
        uid, _ = self.approve_and_apply(_elements())
        self.project.takeoffs = [
            replace(t, position=[9.0, 9.0, 8.0, 8.0, 7.0, 7.0]) if t.uid == "103" else t
            for t in self.project.takeoffs
        ]
        result = self.undo(uid)
        self.assertEqual((result.success, result.code), (False, "stale_changeset"))
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)

    def test_only_applied_changesets_can_be_undone(self):
        uid, _ = self.approve_and_apply(_elements())
        self.assertTrue(self.undo(uid).success)
        again = self.undo(uid)
        self.assertEqual((again.success, again.code), (False, "invalid_state"))

    def test_the_undo_stack_entry_undoes_and_never_redoes(self):
        uid, _ = self.approve_and_apply(_elements())
        (entry,) = self.undo_service._undo_stack
        self.undo_service.undo()
        self.assertEqual(self.store.get(uid).status, STATUS_UNDONE)
        self.assertEqual(self.undo_service._redo_stack, [entry])
        self.assertFalse(self.undo_service.can_undo())
        self.assertTrue(self.undo_service.can_redo())
        before = len(self.write.calls)
        self.undo_service.redo()
        self.assertEqual(len(self.write.calls), before)
        self.assertEqual(self.store.get(uid).status, STATUS_UNDONE)
        self.assertFalse(self.undo_service.can_undo())
        self.assertTrue(self.undo_service.can_redo())
        refusals = []
        entry.redo_action(refusals.append)
        (refusal,) = refusals
        self.assertEqual(
            (refusal.database_id, refusal.outcome_status, refusal.commit_attempted),
            (DB, MutationOutcomeStatus.REJECTED, False),
        )
        self.assertEqual(
            refusal.message,
            "AI changesets cannot be redone. Ask the AI to propose it again.",
        )

    def test_an_undo_from_the_panel_discards_the_history_entry(self):
        older = self.undo_service.push_for_bid(
            BidRef(DB, "7"), lambda complete: None, lambda complete: None
        )
        uid, _ = self.approve_and_apply(_elements())
        self.assertEqual(len(self.undo_service._undo_stack), 2)
        self.assertTrue(self.undo(uid).success)
        self.assertEqual(self.undo_service._undo_stack, [older])
        self.assertEqual(self.undo_service.undo_label(), "")

    def test_a_stale_refusal_through_the_history_keeps_the_entry_undoable(self):
        uid, _ = self.approve_and_apply(_elements())
        self.project.conditions["102"] = replace(
            self.project.conditions["102"], name="Renamed by hand"
        )
        calls = len(self.write.calls)
        self.undo_service.undo()
        self.assertEqual(len(self.write.calls), calls)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertTrue(self.undo_service.can_undo())
        self.assertFalse(self.undo_service.can_redo())
        self.assertEqual(self.undo_service.undo_label(), "AI: One slab")

    def push_user_entry(self, calls, status=MutationOutcomeStatus.COMMITTED):
        def submit(name):
            def run(complete):
                calls.append(name)
                complete(_queued(status, commit_attempted=True))

            return run

        return self.undo_service.push_for_bid(
            BidRef(DB, "7"), submit("undo"), submit("redo"), label="Move takeoff"
        )

    def test_a_refused_history_undo_can_be_discarded_so_older_entries_undo(self):
        user_calls = []
        self.push_user_entry(user_calls)
        uid, _ = self.approve_and_apply(_elements())
        self.project.conditions["102"] = replace(
            self.project.conditions["102"], name="Renamed by hand"
        )
        writes = len(self.write.calls)
        self.undo_service.undo()
        self.undo_service.undo()
        self.assertEqual(user_calls, [])
        self.assertEqual(
            [(label, message) for label, message, _discard in self.refusals],
            [
                (
                    "AI: One slab",
                    "Something this changeset created was edited since. Undo it by hand.",
                )
            ]
            * 2,
        )
        discard = self.refusals[-1][2]
        self.assertIs(discard(), True)
        self.assertIs(discard(), False)
        self.assertEqual(self.undo_service.undo_label(), "Move takeoff")
        self.assertFalse(self.undo_service.can_redo())
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertEqual(len(self.write.calls), writes)
        self.undo_service.undo()
        self.assertEqual(user_calls, ["undo"])
        self.assertFalse(self.undo_service.can_undo())
        self.assertTrue(self.undo_service.can_redo())
        self.undo_service.redo()
        self.assertEqual(user_calls, ["undo", "redo"])
        self.assertEqual(self.undo_service.undo_label(), "Move takeoff")
        self.assertFalse(self.undo_service.can_redo())
        self.assertEqual(len(self.refusals), 2)
        self.assertFalse(self.undo(uid).success)

    def test_withdrawn_access_also_offers_to_discard_the_entry(self):
        user_calls = []
        self.push_user_entry(user_calls)
        self.approve_and_apply(_elements())
        self.denial = "AI takeoff is turned off."
        self.undo_service.undo()
        ((label, message, discard),) = self.refusals
        self.assertEqual(
            (label, message), ("AI: One slab", "AI takeoff is turned off.")
        )
        self.assertTrue(discard())
        self.undo_service.undo()
        self.assertEqual(user_calls, ["undo"])

    def test_successful_or_pipe_undos_and_normal_entries_never_offer_a_discard(self):
        user_calls = []
        self.push_user_entry(user_calls, MutationOutcomeStatus.REJECTED)
        self.undo_service.undo()
        self.assertEqual(user_calls, ["undo"])
        self.assertEqual(self.undo_service.undo_label(), "Move takeoff")
        uid, _ = self.approve_and_apply(_elements())
        original = self.project.conditions["102"]
        self.project.conditions["102"] = replace(original, name="Renamed by hand")
        self.assertFalse(self.undo(uid).success)
        self.project.conditions["102"] = original
        self.undo_service.undo()
        self.assertEqual(self.store.get(uid).status, "undone")
        self.assertEqual(self.refusals, [])

    def test_undo_after_switching_bids_is_refused_as_stale(self):
        uid, _ = self.approve_and_apply(_elements())
        self.project.bid_ref = BidRef(DB, "8")
        calls = len(self.write.calls)
        result = self.undo(uid)
        self.assertEqual((result.success, result.code), (False, "stale_changeset"))
        self.assertEqual(
            result.message,
            "Something this changeset created was edited since. Undo it by hand.",
        )
        self.assertEqual(len(self.write.calls), calls)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)

    def test_undo_is_refused_when_access_was_withdrawn(self):
        uid, _ = self.approve_and_apply(_elements())
        self.denial = "AI takeoff needs permission to place takeoffs."
        calls = len(self.write.calls)
        result = self.undo(uid)
        self.assertEqual(
            (result.success, result.code, result.message),
            (False, "feature_denied", "AI takeoff needs permission to place takeoffs."),
        )
        self.assertEqual(len(self.write.calls), calls)
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertNotIn("undone", [event for event, _details in self.audit])

    def test_a_failed_undo_write_keeps_the_changeset_applied(self):
        uid, _ = self.approve_and_apply(_elements())
        self.write.next_undo_commit = AiChangesetCommit(
            False, message="Edited elsewhere.", conflict=True
        )
        result = self.undo(uid)
        self.assertEqual(
            (result.success, result.code, result.message),
            (False, "lease_conflict", "Edited elsewhere."),
        )
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertEqual(self.undo_service.undo_label(), "AI: One slab")
        self.assertNotIn("undone", [event for event, _details in self.audit])

    def test_an_unknown_changeset_cannot_be_undone(self):
        result = self.undo("no-such-changeset")
        self.assertEqual((result.success, result.code), (False, "not_found"))
        self.assertTrue(result.message)
        self.assertEqual(self.write.calls, [])

    def test_a_nested_folder_elsewhere_never_keeps_the_session_folder(self):
        uid, _ = self.approve_and_apply(_elements())
        self.project.folders["900"] = BidConditionFolder(
            uid="900", bid_uid="7", name="Theirs", parent_uid="899"
        )
        self.assertTrue(self.undo(uid).success)
        self.assertEqual(self.write.calls[-1][1].folder_uid, "101")

    def test_a_folder_nested_in_the_session_folder_keeps_it(self):
        uid, _ = self.approve_and_apply(_elements())
        self.project.folders["900"] = BidConditionFolder(
            uid="900", bid_uid="7", name="Mine", parent_uid="101"
        )
        self.assertTrue(self.undo(uid).success)
        self.assertIsNone(self.write.calls[-1][1].folder_uid)

    def test_an_apply_the_history_cannot_hold_still_undoes_from_the_panel(self):
        self.undo_service.set_active_bid(BidRef(DB, "8"))
        uid, _ = self.approve_and_apply(_elements())
        self.assertEqual(self.undo_service.undo_label(), "")
        result = self.undo(uid)
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.store.get(uid).status, STATUS_UNDONE)

    def test_without_an_open_bid_no_history_entry_is_pushed(self):
        self.project.bid_ref = None
        self.undo_service.set_active_bid(None)
        changeset = _elements()
        added = self.proposals.add(changeset)
        self.proposals.request_apply(added.uid)
        outcomes = []
        self.applier.apply(self.store.approve(added.uid), outcomes.append)
        self.assertTrue(outcomes[0].success)
        self.assertEqual(self.undo_service._undo_stack, [])


class ScaleTests(ApplierTestCase):
    def _scale(self):
        return AiChangeset(
            uid="",
            database_id=DB,
            bid_uid="7",
            bid_key="a" * 32,
            kind=KIND_SCALE,
            created_at=0.0,
            scale=ProposedScale("p1", 0.25, 12.0, 0.125, 12.0, 0.2),
        )

    def test_scale_apply_and_exact_undo(self):
        uid, outcome = self.approve_and_apply(self._scale())
        self.assertTrue(outcome.success, outcome.message)
        self.assertEqual(self.write.calls[0], ("scale", "p1", 0.25, 12.0))
        self.assertEqual(outcome.record.previous_scale, (0.125, 12.0))
        self.assertEqual(
            outcome.record.previous_positions, (("t-old", (1.0, 2.0, 3.0, 4.0)),)
        )
        self.assertEqual(self.undo_service.undo_label(), "AI: page scale 0.25 : 12")
        self.assertTrue(self.undo(uid).success)
        self.assertEqual(self.project.takeoffs[0].position, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(self.project.pages["p1"].scale_factor1, 0.125)

    def test_a_refused_scale_write_reports_the_lock(self):
        self.write.scale_ok = False
        self.project.locked = True
        _uid, outcome = self.approve_and_apply(self._scale())
        self.assertEqual(
            (outcome.success, outcome.code, outcome.message),
            (False, "locked_bid", "The bid is locked."),
        )

    def test_a_refused_scale_write_on_an_unlocked_bid_is_a_plain_failure(self):
        self.write.scale_ok = False
        _uid, outcome = self.approve_and_apply(self._scale())
        self.assertEqual(
            (outcome.success, outcome.code, outcome.message),
            (False, "apply_failed", "The scale was not saved."),
        )
        self.assertEqual(self.undo_service.undo_label(), "")
        self.assertEqual(self.audit, [])

    def test_scale_assumptions_are_recorded_and_audited(self):
        changeset = replace(
            self._scale(),
            assumptions=(
                ChangesetAssumption(
                    "a1", SUBJECT_OTHER, "", "1/4", "dimension", "S-101", IMPACT_NORMAL
                ),
            ),
        )
        uid, outcome = self.approve_and_apply(changeset)
        self.assertTrue(outcome.success, outcome.message)
        (recorded,) = self.recorded
        self.assertEqual([item.uid for item in recorded], [f"{uid}-a1"])
        self.assertEqual(
            self.audit, [("applied", {"changeset_id": uid, "scale": [0.25, 12.0]})]
        )

    def test_sql_scale_apply_and_undo_use_the_page_setting_queue(self):
        self.write.sql = True
        uid, outcome = self.approve_and_apply(self._scale())
        self.assertTrue(outcome.success, outcome.message)
        self.assertEqual(
            self.write.calls,
            [("queue_scale", "p1", "scale", (0.25, 12.0), "ai-takeoff")],
        )
        self.assertEqual(self.project.pages["p1"].scale_factor1, 0.25)
        self.assertTrue(self.undo(uid).success)
        self.assertEqual(
            self.write.calls[-1],
            ("queue_scale", "p1", "scale", (0.125, 12.0), "ai-takeoff"),
        )
        self.assertEqual(self.project.pages["p1"].scale_factor1, 0.125)
        self.assertEqual(self.store.get(uid).status, STATUS_UNDONE)

    def test_a_projection_failure_after_a_sql_scale_commit_still_counts(self):
        self.write.sql = True
        self.write.queue_outcome = _queued(
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED
        )
        _uid, outcome = self.approve_and_apply(self._scale())
        self.assertTrue(outcome.success, outcome.message)

    def test_sql_scale_refusals_map_to_plan_error_codes(self):
        for queued, code, message in (
            (
                _queued(MutationOutcomeStatus.CONFLICT, conflict=_conflict()),
                "lease_conflict",
                "Edited elsewhere.",
            ),
            (_queued(MutationOutcomeStatus.REJECTED), "apply_failed", ""),
        ):
            with self.subTest(code=code):
                self.setUp()
                self.write.sql = True
                self.write.queue_outcome = replace(queued, message=message)
                _uid, outcome = self.approve_and_apply(self._scale())
                self.assertEqual(
                    (outcome.success, outcome.code, outcome.message),
                    (False, code, message or "The scale was not saved."),
                )

    def test_a_refused_sql_scale_undo_keeps_the_changeset_applied(self):
        self.write.sql = True
        uid, _outcome = self.approve_and_apply(self._scale())
        self.write.queue_outcome = _queued(
            MutationOutcomeStatus.REJECTED,
            message="The bid is locked.",
            rejection_reason=MutationRejectionReason.BID_LOCKED,
        )
        result = self.undo(uid)
        self.assertEqual(
            (result.success, result.code, result.message),
            (False, "locked_bid", "The bid is locked."),
        )
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)


class ApplyFailureTests(ApplierTestCase):
    def test_a_commit_without_a_result_is_a_failure(self):
        self.write.next_commit = AiChangesetCommit(True, None)
        _uid, outcome = self.approve_and_apply(_elements())
        self.assertEqual(
            (outcome.success, outcome.code, outcome.message),
            (False, "apply_failed", "The change was not saved."),
        )
        self.assertEqual(self.undo_service.undo_label(), "")
        self.assertEqual(self.audit, [])

    def test_an_unresolvable_changeset_is_reported_not_raised(self):
        for changeset, code in (
            (
                _elements(conditions=(ProposedCondition("c1", "Slab", None, 0.0),)),
                "assumption_unresolved",
            ),
            (replace(_elements(), kind=KIND_SCALE), "invalid_state"),
        ):
            with self.subTest(code=code):
                outcomes = []
                self.applier.apply(changeset, outcomes.append)
                (outcome,) = outcomes
                self.assertEqual((outcome.success, outcome.code), (False, code))
                self.assertTrue(outcome.message)
        self.assertEqual(self.write.calls, [])

    def test_an_exception_from_the_write_service_escapes_without_side_effects(self):
        self.write.error = ActiveBidLockedError()
        added = self.proposals.add(_elements())
        self.proposals.request_apply(added.uid)
        approved = self.store.approve(added.uid)
        outcomes = []
        with self.assertRaises(ActiveBidLockedError):
            self.applier.apply(approved, outcomes.append)
        self.assertEqual(outcomes, [])
        self.assertEqual(self.undo_service.undo_label(), "")
        self.assertEqual((self.audit, self.recorded), ([], []))

    def test_a_restored_session_folder_is_reused(self):
        self.approve_and_apply(_elements())
        folder = self.project.folders.pop("101")
        self.approve_and_apply(_elements(condition_key="existing:42", conditions=()))
        self.assertIsNone(self.write.calls[1][3].existing_folder_uid)
        self.project.folders["101"] = folder
        self.approve_and_apply(_elements())
        self.assertEqual(self.write.calls[2][3].existing_folder_uid, "101")

    def test_no_assumptions_record_nothing(self):
        _uid, outcome = self.approve_and_apply(_elements())
        self.assertTrue(outcome.success)
        self.assertEqual(self.recorded, [])

    def test_an_unwritable_sidecar_is_logged_and_audited(self):
        self.refuse_sidecar = OSError("disk full")
        changeset = replace(
            _elements(),
            assumptions=(
                ChangesetAssumption(
                    "a1", SUBJECT_OTHER, "c1", "x", "y", "z", IMPACT_NORMAL
                ),
            ),
        )
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_changeset_applier", "WARNING"
        ) as logs:
            _uid, outcome = self.approve_and_apply(changeset)
        self.assertTrue(outcome.success)
        self.assertEqual(
            logs.output,
            [
                "WARNING:ost_visualizer.presentation.services.ai_changeset_applier:"
                "AI assumptions were not saved: OSError"
            ],
        )
        self.assertIn(("sidecar_failed", {"error": "OSError"}), self.audit)


class SqlQueueTests(ApplierTestCase):
    def test_sql_undo_uses_the_collaboration_queue(self):
        self.write.sql = True
        uid, _outcome = self.approve_and_apply(_elements())
        result = self.undo(uid)
        self.assertTrue(result.success, result.message)
        kind, plan = self.write.calls[-1]
        self.assertEqual(kind, "queue_undo")
        self.assertEqual(
            (plan.takeoff_uids, plan.condition_uids, plan.folder_uid),
            (("103",), ("102",), "101"),
        )
        self.assertEqual(self.store.get(uid).status, STATUS_UNDONE)

    def test_queued_refusals_map_to_plan_error_codes(self):
        for queued, code in (
            (
                _queued(
                    MutationOutcomeStatus.REJECTED,
                    message="The bid is locked.",
                    rejection_reason=MutationRejectionReason.BID_LOCKED,
                ),
                "locked_bid",
            ),
            (
                _queued(
                    MutationOutcomeStatus.CONFLICT,
                    message="Edited elsewhere.",
                    conflict=_conflict(),
                ),
                "lease_conflict",
            ),
            (
                _queued(MutationOutcomeStatus.FAILED_BEFORE_COMMIT, message="Lost."),
                "apply_failed",
            ),
        ):
            with self.subTest(code=code):
                self.setUp()
                self.write.sql = True
                self.write.queue_outcome = queued
                _uid, outcome = self.approve_and_apply(_elements())
                self.assertEqual(
                    (outcome.success, outcome.code, outcome.message),
                    (False, code, queued.message),
                )
                self.assertEqual(self.undo_service.undo_label(), "")
                self.assertEqual(self.project.conditions.keys(), {"42"})

    def test_a_refused_sql_undo_keeps_the_changeset_applied(self):
        self.write.sql = True
        uid, _outcome = self.approve_and_apply(_elements())
        self.write.queue_outcome = _queued(
            MutationOutcomeStatus.CONFLICT,
            message="Edited elsewhere.",
            conflict=_conflict(),
        )
        result = self.undo(uid)
        self.assertEqual(
            (result.success, result.code, result.message),
            (False, "lease_conflict", "Edited elsewhere."),
        )
        self.assertEqual(self.store.get(uid).status, STATUS_APPLIED)
        self.assertEqual(self.undo_service.undo_label(), "AI: One slab")

    def test_the_queue_decodes_what_the_write_service_encodes(self):
        written = AiChangesetWriteResult(
            "101", True, (("c1", "102"), ("c2", "105")), ("103", "104", "106")
        )
        self.write.sql = True
        self.write.queue_outcome = _queued(
            MutationOutcomeStatus.COMMITTED,
            authoritative_result=_ai_changeset_authoritative_result(written),
        )
        _uid, outcome = self.approve_and_apply(_elements())
        self.assertTrue(outcome.success, outcome.message)
        self.assertEqual(
            (
                outcome.record.folder_uid,
                outcome.record.created_folder,
                outcome.record.condition_uids,
                outcome.record.takeoff_uids,
            ),
            ("101", True, ("102", "105"), ("103", "104", "106")),
        )

    def test_a_reused_folder_round_trips_as_not_created(self):
        written = AiChangesetWriteResult(None, False, (), ("103",))
        self.write.sql = True
        self.write.queue_outcome = _queued(
            MutationOutcomeStatus.COMMITTED,
            authoritative_result=_ai_changeset_authoritative_result(written),
        )
        _uid, outcome = self.approve_and_apply(
            _elements(condition_key="existing:42", conditions=())
        )
        self.assertTrue(outcome.success, outcome.message)
        self.assertEqual(
            (outcome.record.folder_uid, outcome.record.created_folder),
            (None, False),
        )
        self.assertEqual(outcome.record.takeoff_uids, ("103",))


class WriteDtoTests(unittest.TestCase):
    def test_an_empty_applied_record_claims_nothing(self):
        record = AppliedChangeset()
        self.assertEqual(
            (
                record.folder_uid,
                record.created_folder,
                record.condition_uids,
                record.takeoff_uids,
                record.page_uid,
                record.previous_scale,
                record.previous_positions,
                record.resulting_tokens,
            ),
            (None, False, (), (), None, None, (), ()),
        )

    def test_write_dtos_are_immutable(self):
        spec = CreateConditionSpec(name="Slab", condition_type=Condition.TYPE_AREA)
        takeoff = AiTakeoffWrite("c1", "p1", SQUARE)
        result = AiChangesetWriteResult("101", True, (("c1", "102"),), ("103",))
        record = AppliedChangeset()
        plan = AiChangesetWritePlan("AI", None, (("c1", spec),), (takeoff,))
        undo_plan = AiChangesetUndoPlan(("103",), ("102",))
        scale_plan = AiScaleUndoPlan("p1", 0.125, 12.0, ())
        commit = AiChangesetCommit(True, result)
        with self.assertRaises(FrozenInstanceError):
            record.folder_uid = "changed"
        with self.assertRaises(FrozenInstanceError):
            takeoff.page_uid = "changed"
        with self.assertRaises(FrozenInstanceError):
            plan.folder_name = "changed"
        with self.assertRaises(FrozenInstanceError):
            result.folder_uid = "changed"
        with self.assertRaises(FrozenInstanceError):
            undo_plan.folder_uid = "changed"
        with self.assertRaises(FrozenInstanceError):
            scale_plan.page_uid = "changed"
        with self.assertRaises(FrozenInstanceError):
            commit.message = "changed"


HARNESS_DB = _Harness.DATABASE


def _harness_plan(conditions=True, takeoffs=True, existing_folder_uid=None):
    spec = CreateConditionSpec(name="Slab", condition_type=Condition.TYPE_AREA)
    return AiChangesetWritePlan(
        folder_name="AI 2026-10-07 14:05",
        existing_folder_uid=existing_folder_uid,
        conditions=(("c1", spec),) if conditions else (),
        takeoffs=(
            (
                AiTakeoffWrite(
                    "c1" if conditions else "10", "20", SQUARE, (HOLE,), "5"
                ),
                AiTakeoffWrite("10", "21", SQUARE),
            )
            if takeoffs
            else ()
        ),
        existing_condition_uids=("10",) if takeoffs else (),
    )


def _resources(resources):
    return [_Harness.resource_text(resource) for resource in resources]


class WriteServiceAiChangesetTests(unittest.TestCase):
    def test_local_apply_creates_folder_conditions_takeoffs_and_holes(self):
        harness = _Harness(
            {
                "insert_condition_folder": "f9",
                "insert_condition": "c9",
                "insert_takeoffs": _Seq(["t1", "t2"], ["t3"]),
            },
            sql=False,
        )
        commit = harness.service.execute_ai_changeset_local(
            HARNESS_DB, "7", _harness_plan()
        )
        self.assertEqual(
            commit,
            AiChangesetCommit(
                True,
                AiChangesetWriteResult("f9", True, (("c1", "c9"),), ("t1", "t2", "t3")),
            ),
        )
        folder_call, condition_call, primary_call, hole_call = harness.calls
        self.assertEqual(
            folder_call[:3],
            (
                "insert_condition_folder",
                "execute",
                (HARNESS_DB, "7", "AI 2026-10-07 14:05", None),
            ),
        )
        self.assertEqual(condition_call[2][2].folder_uid, "f9")
        self.assertEqual(
            [
                (spec.condition_uid, spec.page_uid, spec.area_uid, spec.parent_uid)
                for spec in primary_call[2][2]
            ],
            [("c9", "20", "5", None), ("10", "21", None, None)],
        )
        self.assertEqual(
            [
                (spec.condition_uid, spec.position, spec.parent_uid)
                for spec in hole_call[2][2]
            ],
            [("c9", list(HOLE), "t1")],
        )
        (request,) = harness.executor.requests
        self.assertEqual(
            _resources(request.resources),
            [
                "condition:10@7",
                "conditions_collection:7@7",
                "page:20@7",
                "page:21@7",
                "takeoffs_collection:7@7",
            ],
        )
        self.assertEqual(
            harness.record_lines(),
            [
                "record condition:c9@7 create",
                "record condition_folder:f9@7 create",
                "record conditions_collection:7@7 update",
                "record takeoff:t1@7 create",
                "record takeoff:t2@7 create",
                "record takeoff:t3@7 create",
                "record takeoffs_collection:7@7 update",
            ],
        )
        self.assertEqual(harness.reloads, [HARNESS_DB])
        ((event, payload),) = harness.events.published
        self.assertEqual(
            (event.__name__, payload["page_scale_uids"]), ("DatabaseRefreshedEvent", ())
        )

    def test_a_plan_on_existing_conditions_creates_no_folder(self):
        harness = _Harness({"insert_takeoffs": _Seq(["t1", "t2"], ["t3"])}, sql=False)
        commit = harness.service.execute_ai_changeset_local(
            HARNESS_DB,
            "7",
            _harness_plan(conditions=False, existing_folder_uid="f1"),
        )
        self.assertEqual(
            commit,
            AiChangesetCommit(
                True, AiChangesetWriteResult("f1", False, (), ("t1", "t2", "t3"))
            ),
        )
        self.assertEqual(
            [name for name, _method, _args, _kwargs in harness.calls],
            ["insert_takeoffs", "insert_takeoffs"],
        )
        self.assertEqual(
            _resources(harness.executor.requests[0].resources),
            [
                "condition:10@7",
                "condition_folder:f1@7",
                "page:20@7",
                "page:21@7",
                "takeoffs_collection:7@7",
            ],
        )
        self.assertEqual(
            harness.record_lines(),
            [
                "record takeoff:t1@7 create",
                "record takeoff:t2@7 create",
                "record takeoff:t3@7 create",
                "record takeoffs_collection:7@7 update",
            ],
        )

    def test_a_plan_without_takeoffs_never_inserts_takeoffs(self):
        harness = _Harness(
            {"insert_condition_folder": "f9", "insert_condition": "c9"}, sql=False
        )
        commit = harness.service.execute_ai_changeset_local(
            HARNESS_DB, "7", _harness_plan(takeoffs=False)
        )
        self.assertEqual(
            commit,
            AiChangesetCommit(
                True, AiChangesetWriteResult("f9", True, (("c1", "c9"),), ())
            ),
        )
        self.assertEqual(
            [name for name, _method, _args, _kwargs in harness.calls],
            ["insert_condition_folder", "insert_condition"],
        )

    def test_each_failed_insert_rolls_the_whole_changeset_back(self):
        for label, results, message, calls in (
            (
                "folder",
                {"insert_condition_folder": None},
                "The AI condition folder could not be created.",
                ["insert_condition_folder"],
            ),
            (
                "condition",
                {"insert_condition_folder": "f9", "insert_condition": None},
                "An AI condition could not be created.",
                ["insert_condition_folder", "insert_condition"],
            ),
            (
                "short takeoffs",
                {
                    "insert_condition_folder": "f9",
                    "insert_condition": "c9",
                    "insert_takeoffs": ["t1"],
                },
                "The AI takeoff insertion was incomplete.",
                ["insert_condition_folder", "insert_condition", "insert_takeoffs"],
            ),
            (
                "duplicate takeoffs",
                {
                    "insert_condition_folder": "f9",
                    "insert_condition": "c9",
                    "insert_takeoffs": ["t1", "t1"],
                },
                "The AI takeoff insertion was incomplete.",
                ["insert_condition_folder", "insert_condition", "insert_takeoffs"],
            ),
            (
                "no takeoffs",
                {
                    "insert_condition_folder": "f9",
                    "insert_condition": "c9",
                    "insert_takeoffs": None,
                },
                "The AI takeoff insertion was incomplete.",
                ["insert_condition_folder", "insert_condition", "insert_takeoffs"],
            ),
        ):
            with self.subTest(label):
                harness = _Harness(results, sql=False)
                commit = harness.service.execute_ai_changeset_local(
                    HARNESS_DB, "7", _harness_plan()
                )
                self.assertEqual(commit, AiChangesetCommit(False, message=message))
                self.assertEqual(
                    [name for name, _method, _args, _kwargs in harness.calls], calls
                )
                self.assertEqual(harness.reloads, [])

    def test_refused_mutations_map_to_locked_conflict_or_rejected(self):
        conflict = SynchronizationConflict(
            HARNESS_DB, ResourceRef("takeoff", "1", 7), "Edited elsewhere."
        )
        for label, status, reason, sync_conflict, expected in (
            (
                "locked",
                MutationOutcomeStatus.REJECTED,
                MutationRejectionReason.BID_LOCKED,
                None,
                AiChangesetCommit(False, message="The bid is locked.", locked=True),
            ),
            (
                "rejected",
                MutationOutcomeStatus.REJECTED,
                None,
                None,
                AiChangesetCommit(False, message="The database rejected the change."),
            ),
            (
                "conflict",
                MutationOutcomeStatus.CONFLICT,
                None,
                conflict,
                AiChangesetCommit(False, message="Edited elsewhere.", conflict=True),
            ),
        ):
            with self.subTest(label):
                harness = _Harness(sql=False)
                harness.executor.status = status
                harness.executor.rejection_reason = reason
                harness.executor.conflict = sync_conflict
                self.assertEqual(
                    harness.service.execute_ai_changeset_local(
                        HARNESS_DB, "7", _harness_plan()
                    ),
                    expected,
                )
                self.assertEqual(
                    harness.service.execute_ai_changeset_undo_local(
                        HARNESS_DB, "7", AiChangesetUndoPlan(("t1",), ())
                    ),
                    expected,
                )
                self.assertEqual(harness.reloads, [])
                self.assertEqual(harness.events.published, [])

    def test_local_writes_refuse_sql_databases(self):
        harness = _Harness(sql=True)
        for write in (
            lambda: harness.service.execute_ai_changeset_local(
                HARNESS_DB, "7", _harness_plan()
            ),
            lambda: harness.service.execute_ai_changeset_undo_local(
                HARNESS_DB, "7", AiChangesetUndoPlan(("t1",), ())
            ),
            lambda: harness.service.execute_ai_scale_undo_local(
                HARNESS_DB, "7", AiScaleUndoPlan("20", 0.125, 12.0, ())
            ),
        ):
            with self.assertRaises(ValueError) as raised:
                write()
            self.assertEqual(
                str(raised.exception),
                "SQL AI changesets must use the collaboration queue",
            )
        self.assertEqual(harness.executor.calls, 0)

    def test_queued_writes_refuse_a_locked_active_bid(self):
        harness = _Harness(sql=True)
        harness.data.locked = True
        with self.assertRaises(ActiveBidLockedError):
            harness.service.queue_ai_changeset(
                HARNESS_DB, "7", _harness_plan(), lambda _result: None
            )
        with self.assertRaises(ActiveBidLockedError):
            harness.service.queue_ai_changeset_undo(
                HARNESS_DB, "7", AiChangesetUndoPlan(("t1",), ()), lambda _result: None
            )
        self.assertEqual(harness.provider.requests, [])

    def test_a_queued_apply_reports_what_it_created(self):
        harness = _Harness(
            {
                "insert_condition_folder": "f9",
                "insert_condition": "c9",
                "insert_takeoffs": _Seq(["t1", "t2"], ["t3"]),
            },
            sql=True,
        )
        self.assertEqual(
            harness.service.queue_ai_changeset(
                HARNESS_DB, "7", _harness_plan(), lambda _result: None
            ),
            41,
        )
        request, execute, _callback = harness.provider.requests[0]
        self.assertEqual(
            (request.owning_surface, request.payload.write_kind),
            ("ai-takeoff", "apply_ai_changeset"),
        )
        self.assertEqual(
            _resources(request.resources),
            ["conditions_collection:7@7", "takeoffs_collection:7@7"],
        )
        self.assertEqual(
            _resources(request.dependency_resources),
            ["condition:10@7", "page:20@7", "page:21@7"],
        )
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            result.authoritative_result.created_uid_maps,
            (
                ("condition_folders", (("0", "f9"),)),
                ("conditions", (("c1", "c9"),)),
                ("takeoffs", (("0", "t1"), ("1", "t2"), ("2", "t3"))),
            ),
        )
        self.assertEqual(result.created_resource_ids, ("t1", "t2", "t3"))

    def test_local_undo_deletes_takeoffs_conditions_and_the_folder(self):
        harness = _Harness(sql=False)
        commit = harness.service.execute_ai_changeset_undo_local(
            HARNESS_DB, "7", AiChangesetUndoPlan(("t1", "t2"), ("c9",), "f9")
        )
        self.assertEqual(
            commit, AiChangesetCommit(True, AiChangesetWriteResult(None, False, (), ()))
        )
        self.assertEqual(
            [(name, args) for name, _method, args, _kwargs in harness.calls],
            [
                ("delete_takeoffs", (HARNESS_DB, ["t1", "t2"])),
                ("delete_conditions", (HARNESS_DB, "7", ["c9"])),
                ("delete_condition_folders", (HARNESS_DB, ["f9"])),
            ],
        )
        self.assertEqual(
            _resources(harness.executor.requests[0].resources),
            [
                "condition:c9@7",
                "condition_folder:f9@7",
                "conditions_collection:7@7",
                "takeoff:t1@7",
                "takeoff:t2@7",
                "takeoffs_collection:7@7",
            ],
        )
        self.assertEqual(
            harness.record_lines(),
            [
                "record condition:c9@7 delete",
                "record condition_folder:f9@7 delete",
                "record conditions_collection:7@7 update",
                "record takeoff:t1@7 delete",
                "record takeoff:t2@7 delete",
                "record takeoffs_collection:7@7 update",
            ],
        )
        self.assertEqual(harness.reloads, [HARNESS_DB])

    def test_undo_touches_only_what_the_plan_names(self):
        for label, plan, calls, resources, records in (
            (
                "takeoffs only",
                AiChangesetUndoPlan(("t1",), ()),
                ["delete_takeoffs"],
                ["takeoff:t1@7", "takeoffs_collection:7@7"],
                ["record takeoff:t1@7 delete", "record takeoffs_collection:7@7 update"],
            ),
            (
                "conditions kept folder",
                AiChangesetUndoPlan((), ("c9",)),
                ["delete_conditions"],
                [
                    "condition:c9@7",
                    "conditions_collection:7@7",
                    "takeoffs_collection:7@7",
                ],
                [
                    "record condition:c9@7 delete",
                    "record conditions_collection:7@7 update",
                    "record takeoffs_collection:7@7 update",
                ],
            ),
            (
                "folder only",
                AiChangesetUndoPlan((), (), "f9"),
                ["delete_condition_folders"],
                [
                    "condition_folder:f9@7",
                    "conditions_collection:7@7",
                    "takeoffs_collection:7@7",
                ],
                [
                    "record condition_folder:f9@7 delete",
                    "record conditions_collection:7@7 update",
                    "record takeoffs_collection:7@7 update",
                ],
            ),
        ):
            with self.subTest(label):
                harness = _Harness(sql=False)
                commit = harness.service.execute_ai_changeset_undo_local(
                    HARNESS_DB, "7", plan
                )
                self.assertTrue(commit.committed, commit.message)
                self.assertEqual(
                    [name for name, _method, _args, _kwargs in harness.calls], calls
                )
                self.assertEqual(
                    _resources(harness.executor.requests[0].resources), resources
                )
                self.assertEqual(harness.record_lines(), records)

    def test_each_failed_delete_rolls_the_undo_back(self):
        plan = AiChangesetUndoPlan(("t1",), ("c9",), "f9")
        for name, message in (
            ("delete_takeoffs", "The AI takeoffs could not be removed."),
            ("delete_conditions", "The AI conditions could not be removed."),
            (
                "delete_condition_folders",
                "The AI condition folder could not be removed.",
            ),
        ):
            with self.subTest(name):
                harness = _Harness({name: False}, sql=False)
                self.assertEqual(
                    harness.service.execute_ai_changeset_undo_local(
                        HARNESS_DB, "7", plan
                    ),
                    AiChangesetCommit(False, message=message),
                )
                self.assertEqual(harness.reloads, [])

    def test_a_queued_undo_reports_the_conditions_it_removed(self):
        harness = _Harness(sql=True)
        plan = AiChangesetUndoPlan(("t1",), ("c9",), "f9")
        self.assertEqual(
            harness.service.queue_ai_changeset_undo(
                HARNESS_DB, "7", plan, lambda _result: None
            ),
            41,
        )
        request, execute, _callback = harness.provider.requests[0]
        self.assertEqual(
            (request.owning_surface, request.payload.write_kind),
            ("ai-takeoff", "undo_ai_changeset"),
        )
        self.assertEqual(
            _resources(request.resources),
            [
                "condition:c9@7",
                "condition_folder:f9@7",
                "conditions_collection:7@7",
                "takeoff:t1@7",
                "takeoffs_collection:7@7",
            ],
        )
        result = execute()
        self.assertEqual(
            (
                result.authoritative_result.affected_condition_uids,
                result.authoritative_result.affected_families,
            ),
            (("c9",), ("takeoffs", "conditions")),
        )

    def test_scale_undo_restores_the_scale_then_the_positions(self):
        harness = _Harness(sql=False)
        plan = AiScaleUndoPlan("20", 0.125, 12.0, (("30", (1.0, 2.0, 3.0, 4.0)),))
        self.assertEqual(
            harness.service.execute_ai_scale_undo_local(HARNESS_DB, "7", plan),
            AiChangesetCommit(True, AiChangesetWriteResult(None, False, (), ())),
        )
        self.assertEqual(
            [(name, args) for name, _method, args, _kwargs in harness.calls],
            [
                ("save_page_scale", (HARNESS_DB, "20", 0.125, 12.0)),
                (
                    "save_takeoff_positions",
                    (HARNESS_DB, [("30", [1.0, 2.0, 3.0, 4.0])]),
                ),
            ],
        )
        self.assertEqual(
            harness.record_lines(),
            ["record page:20@7 update", "record takeoff:30@7 update"],
        )
        ((event, payload),) = harness.events.published
        self.assertEqual(
            (event.__name__, payload["page_scale_uids"]),
            ("DatabaseRefreshedEvent", ("20",)),
        )

    def test_scale_undo_without_takeoffs_only_restores_the_scale(self):
        harness = _Harness(sql=False)
        commit = harness.service.execute_ai_scale_undo_local(
            HARNESS_DB, "7", AiScaleUndoPlan("20", 0.125, 12.0, ())
        )
        self.assertTrue(commit.committed, commit.message)
        self.assertEqual(
            [name for name, _method, _args, _kwargs in harness.calls],
            ["save_page_scale"],
        )

    def test_a_failed_scale_restore_rolls_the_undo_back(self):
        plan = AiScaleUndoPlan("20", 0.125, 12.0, (("30", (1.0, 2.0)),))
        for name, message in (
            ("save_page_scale", "The previous page scale could not be restored."),
            (
                "save_takeoff_positions",
                "The previous takeoff positions could not be restored.",
            ),
        ):
            with self.subTest(name):
                harness = _Harness({name: False}, sql=False)
                self.assertEqual(
                    harness.service.execute_ai_scale_undo_local(HARNESS_DB, "7", plan),
                    AiChangesetCommit(False, message=message),
                )
                self.assertEqual(harness.reloads, [])


class SqlBackstopTests(ApplierTestCase):
    def test_sql_bids_are_never_applied_or_undone(self):
        applied_uid, _outcome = self.approve_and_apply(_elements())
        blocked = AiChangesetApplier(
            write_service=self.write,
            project_data=self.project,
            undo_service=self.undo_service,
            store=self.store,
            token_reader=self.tokens,
            access_check=lambda changeset: "",
            layer_uid=lambda: "L9",
            area_uid=lambda page_uid: "A1",
            session_folder_name="AI 2026-10-07 14:05",
            apply_blocked=lambda database_id: "SQL Server bids cannot be applied yet.",
        )
        calls = len(self.write.calls)
        added = self.proposals.add(_elements())
        self.proposals.request_apply(added.uid)
        outcomes = []
        blocked.apply(self.store.approve(added.uid), outcomes.append)
        self.assertEqual(
            (outcomes[0].success, outcomes[0].code), (False, "sql_apply_unavailable")
        )
        blocked.undo(applied_uid, outcomes.append)
        self.assertEqual(
            (outcomes[1].success, outcomes[1].code), (False, "sql_apply_unavailable")
        )
        self.assertEqual(len(self.write.calls), calls)

    def test_an_unresolvable_database_is_never_applied_or_undone(self):
        applied_uid, _outcome = self.approve_and_apply(_elements())

        def failing_lookup(_database_id):
            raise LookupError("registry unavailable")

        for label, resolve in (
            ("unregistered", {}.get),
            ("lookup raises", failing_lookup),
        ):
            with self.subTest(label):
                blocked = AiChangesetApplier(
                    write_service=self.write,
                    project_data=self.project,
                    undo_service=self.undo_service,
                    store=self.store,
                    token_reader=self.tokens,
                    access_check=lambda changeset: "",
                    layer_uid=lambda: "L9",
                    area_uid=lambda page_uid: "A1",
                    session_folder_name="AI 2026-10-07 14:05",
                    apply_blocked=lambda database_id, resolve=resolve: apply_block_for(
                        resolve, database_id
                    ),
                )
                calls = len(self.write.calls)
                outcomes = []
                for changeset in (_elements(), _scale_changeset()):
                    added = self.proposals.add(changeset)
                    self.proposals.request_apply(added.uid)
                    blocked.apply(self.store.approve(added.uid), outcomes.append)
                blocked.undo(applied_uid, outcomes.append)
                self.assertEqual(
                    [(item.success, item.code) for item in outcomes],
                    [(False, "sql_apply_unavailable")] * 3,
                )
                self.assertEqual(
                    {item.message for item in outcomes}, {DATABASE_UNRESOLVED_MESSAGE}
                )
                self.assertEqual(len(self.write.calls), calls)
                self.assertEqual(self.store.get(applied_uid).status, STATUS_APPLIED)


if __name__ == "__main__":
    unittest.main()
