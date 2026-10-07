import unittest
from dataclasses import replace
from types import SimpleNamespace
from ost_visualizer.application.dtos.ai_changeset_write_dtos import (
    AiChangesetCommit,
    AiChangesetWriteResult,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.application.services.ai_takeoff_tokens import ProjectDataTokenReader
from ost_visualizer.domain.entities.ai_takeoff import SidecarWriteRefused
from ost_visualizer.domain.entities.ai_changeset import (
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

DB = "C:/jobs/a.mdb"
SQUARE = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)
HOLE = (120.0, 120.0, 240.0, 120.0, 240.0, 240.0, 120.0, 240.0)


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
        self.counter = 100
        self.scale_ok = True

    def uses_sql_collaboration_mutations(self, _database_id):
        return self.sql

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
        if self.next_commit is not None:
            return self.next_commit
        return AiChangesetCommit(True, self._commit_plan(plan))

    def queue_ai_changeset(self, database_id, bid_uid, plan, callback):
        self.calls.append(("queue_apply", database_id, bid_uid, plan))
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
            (spec.condition_type, spec.thickness, spec.layer_uid),
            (Condition.TYPE_AREA, 8.0, "L9"),
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
        self.undo_service.undo()
        self.assertEqual(self.store.get(uid).status, STATUS_UNDONE)
        before = len(self.write.calls)
        self.undo_service.redo()
        self.assertEqual(len(self.write.calls), before)


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
        self.assertEqual((outcome.success, outcome.code), (False, "locked_bid"))


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


if __name__ == "__main__":
    unittest.main()
