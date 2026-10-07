import unittest
from pathlib import Path
from ost_visualizer.application.dtos.ai_changeset_write_dtos import (
    AiChangesetUndoPlan,
    AiChangesetWritePlan,
    AiScaleUndoPlan,
    AiTakeoffWrite,
)
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_AREA_VOLUME,
    UOM_CUBIC_YARDS,
    UOM_SQUARE_FEET,
)
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.domain.entities.ai_changeset import (
    IMPACT_HIGH,
    KIND_ELEMENTS,
    SUBJECT_TOP_ELEVATION,
    AiChangeset,
    ChangesetAssumption,
    ChangesetError,
    ProposedCondition,
    ProposedTakeoff,
)
from ost_visualizer.presentation.services.ai_changeset_applier import (
    AiChangesetApplier,
)
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from tests.integration.ai_takeoff.access_app_support import (
    configured_app,
    dump_tables,
    run_in_access_child,
    seed_access_bid,
    temporary_home,
)

OUTER = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)
HOLE = (120.0, 120.0, 240.0, 120.0, 240.0, 240.0, 120.0, 240.0)


def _slab_spec(name="Slab 8in @T 100' - 0\""):
    return CreateConditionSpec(
        name=name,
        condition_type=Condition.TYPE_AREA,
        thickness=8.0,
        calc_type1=CALC_AREA,
        uom1=UOM_SQUARE_FEET,
        calc_type2=CALC_AREA_VOLUME,
        uom2=UOM_CUBIC_YARDS,
    )


class AiChangesetAccessRoundTripTests(unittest.TestCase):
    def setUp(self):
        if run_in_access_child(self):
            self.skip_body = True
            return
        self.skip_body = False
        self.directory = temporary_home()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.db_path = self.home / "ai.mdb"
        self.bid_uid, self.page_uids, self.existing_condition = seed_access_bid(
            self.db_path, [("S-101", 8.5, 11.0, 0.125, 12.0)]
        )

    def plan(self, takeoffs=None, existing_folder_uid=None):
        return AiChangesetWritePlan(
            folder_name="AI 2026-10-07 14:05",
            existing_folder_uid=existing_folder_uid,
            conditions=(("c1", _slab_spec()),),
            takeoffs=takeoffs
            or (AiTakeoffWrite("c1", self.page_uids[0], OUTER, (HOLE,), "0"),),
        )

    def test_apply_creates_folder_condition_and_takeoffs_and_undo_restores_exactly(
        self,
    ):
        if self.skip_body:
            return
        before = dump_tables(self.db_path)
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            bid_ref,
        ):
            write_service = container.get("project_write_service")
            project = container.get("project_data_service")
            commit = write_service.execute_ai_changeset_local(
                str(self.db_path), self.bid_uid, self.plan()
            )
            self.assertTrue(commit.committed, commit.message)
            result = commit.result
            self.assertTrue(result.created_folder)
            self.assertEqual(len(result.takeoff_uids), 2)
            after = dump_tables(self.db_path)
            self.assertEqual(
                len(after["BidConditionFolders"]),
                len(before["BidConditionFolders"]) + 1,
            )
            condition_uid = dict(result.condition_uids)["c1"]
            conditions = project.get_bid_conditions()
            self.assertEqual(conditions[condition_uid].folder_uid, result.folder_uid)
            self.assertEqual(conditions[condition_uid].z_value, 1200.0)
            takeoffs = project.get_all_takeoffs()
            hole = next(t for t in takeoffs if t.uid == result.takeoff_uids[1])
            self.assertEqual(str(hole.parent_uid), result.takeoff_uids[0])
            quantities = compute_page_quantities(conditions, takeoffs)[condition_uid]
            self.assertAlmostEqual(quantities[0], 1200.0 - 100.0, places=6)
            self.assertAlmostEqual(quantities[1], 1100.0 * 8.0 / 12.0 / 27.0, places=6)
            undo = write_service.execute_ai_changeset_undo_local(
                str(self.db_path),
                self.bid_uid,
                AiChangesetUndoPlan(
                    result.takeoff_uids, (condition_uid,), result.folder_uid
                ),
            )
            self.assertTrue(undo.committed, undo.message)
            self.assertNotIn(condition_uid, project.get_bid_conditions())
        self.assertEqual(dump_tables(self.db_path), before)

    def test_a_failure_part_way_leaves_nothing_behind(self):
        if self.skip_body:
            return
        before = dump_tables(self.db_path)
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            _bid_ref,
        ):
            write_service = container.get("project_write_service")
            commit = write_service.execute_ai_changeset_local(
                str(self.db_path),
                self.bid_uid,
                self.plan(takeoffs=(AiTakeoffWrite("c1", "999999", OUTER, (), "0"),)),
            )
            self.assertFalse(commit.committed)
        self.assertEqual(dump_tables(self.db_path), before)

    def test_a_locked_bid_writes_nothing(self):
        if self.skip_body:
            return
        before = dump_tables(self.db_path)
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            _bid_ref,
        ):
            container.get("project_data_service").set_current_bid_locked(True)
            commit = container.get("project_write_service").execute_ai_changeset_local(
                str(self.db_path), self.bid_uid, self.plan()
            )
            self.assertFalse(commit.committed)
            self.assertTrue(commit.locked)
        self.assertEqual(dump_tables(self.db_path), before)

    def test_reusing_the_session_folder_creates_no_second_folder(self):
        if self.skip_body:
            return
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            _bid_ref,
        ):
            write_service = container.get("project_write_service")
            first = write_service.execute_ai_changeset_local(
                str(self.db_path), self.bid_uid, self.plan()
            ).result
            second = write_service.execute_ai_changeset_local(
                str(self.db_path),
                self.bid_uid,
                self.plan(existing_folder_uid=first.folder_uid),
            ).result
            self.assertFalse(second.created_folder)
            self.assertEqual(second.folder_uid, first.folder_uid)
        folders = dump_tables(self.db_path)["BidConditionFolders"]
        self.assertEqual(
            sum(1 for row in folders if str(row["UID"]) == first.folder_uid), 1
        )

    def test_scale_undo_restores_the_scale_and_takeoff_positions_exactly(self):
        if self.skip_body:
            return
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            _bid_ref,
        ):
            write_service = container.get("project_write_service")
            project = container.get("project_data_service")
            page_uid = self.page_uids[0]
            existing = write_service.insert_takeoffs_result(
                str(self.db_path),
                self.bid_uid,
                [
                    InsertTakeoffSpec(
                        self.existing_condition,
                        page_uid,
                        "0",
                        [0.1, 0.3, 97.7, 0.3, 97.7, 33.3],
                    )
                ],
            ).value[0]
            before = dump_tables(self.db_path)
            positions = tuple(
                (t.uid, tuple(t.position)) for t in project.get_page_takeoffs(page_uid)
            )
            self.assertTrue(
                write_service.save_page_scale(str(self.db_path), page_uid, 0.1875, 12.0)
            )
            moved = {t.uid: t.position for t in project.get_page_takeoffs(page_uid)}
            self.assertNotEqual(moved[existing], list(dict(positions)[existing]))
            undo = write_service.execute_ai_scale_undo_local(
                str(self.db_path),
                self.bid_uid,
                AiScaleUndoPlan(page_uid, 0.125, 12.0, positions),
            )
            self.assertTrue(undo.committed, undo.message)
            page = project.get_page(page_uid)
            self.assertEqual((page.scale_factor1, page.scale_factor2), (0.125, 12.0))
        after = dump_tables(self.db_path)
        self.assertEqual(after["BidTakeoffs"], before["BidTakeoffs"])
        self.assertEqual(after["BidPages"], before["BidPages"])


class AiChangesetApplierAccessTests(unittest.TestCase):
    def setUp(self):
        if run_in_access_child(self):
            self.skip_body = True
            return
        self.skip_body = False
        self.directory = temporary_home()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.db_path = self.home / "ai.mdb"
        self.bid_uid, self.page_uids, _existing = seed_access_bid(
            self.db_path, [("S-101", 8.5, 11.0, 0.125, 12.0)]
        )

    def harness(self, container, bid_ref):
        project = container.get("project_data_service")
        tokens = container.get("ai_takeoff_token_reader")
        store = AiChangesetStore(token_reader=tokens)
        undo = UndoRedoService()
        undo.set_active_bid(bid_ref)
        applier = AiChangesetApplier(
            write_service=container.get("project_write_service"),
            project_data=project,
            undo_service=undo,
            store=store,
            token_reader=tokens,
            access_check=lambda _changeset: "",
            layer_uid=lambda: None,
            area_uid=lambda _page_uid: "0",
            session_folder_name="AI 2026-10-07 14:05",
        )
        return store, AiChangesetProposals(store), undo, applier

    def changeset(self, top_elev_in=1200.0, assumptions=()):
        return AiChangeset(
            uid="",
            database_id=str(self.db_path),
            bid_uid=self.bid_uid,
            bid_key="a" * 32,
            kind=KIND_ELEMENTS,
            created_at=0.0,
            conditions=(ProposedCondition("c1", "Slab 8in", 8.0, top_elev_in),),
            takeoffs=(ProposedTakeoff("t1", self.page_uids[0], "c1", OUTER),),
            assumptions=assumptions,
            summary="AI slab",
        )

    def apply(self, store, proposals, applier, changeset):
        added = proposals.add(changeset)
        proposals.request_apply(added.uid)
        approved = store.approve(added.uid)
        outcomes = []
        applier.apply(approved, outcomes.append)
        (outcome,) = outcomes
        self.assertTrue(outcome.success, outcome.message)
        store.mark_applied(added.uid, outcome.record)
        return added.uid, outcome.record

    def test_a_pipe_undo_leaves_the_users_older_undo_entries_reachable(self):
        if self.skip_body:
            return
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            bid_ref,
        ):
            store, proposals, undo, applier = self.harness(container, bid_ref)
            user_undos = []

            def user_undo(complete):
                user_undos.append("user edit undone")
                complete(
                    QueuedMutationResult(
                        database_id=str(self.db_path),
                        runtime_generation=0,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        commit_attempted=True,
                    )
                )

            undo.push_for_bid(bid_ref, user_undo, lambda _complete: None)
            uid, _record = self.apply(store, proposals, applier, self.changeset())
            outcomes = []
            applier.undo(uid, outcomes.append)
            self.assertTrue(outcomes[0].success, outcomes[0].message)
            undo.undo()
            self.assertEqual(user_undos, ["user edit undone"])
            self.assertFalse(undo.can_undo())

    def test_undo_never_removes_a_takeoff_the_user_drew_on_the_ai_condition(self):
        if self.skip_body:
            return
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            bid_ref,
        ):
            store, proposals, undo, applier = self.harness(container, bid_ref)
            uid, record = self.apply(store, proposals, applier, self.changeset())
            write_service = container.get("project_write_service")
            inserted = write_service.insert_takeoffs_result(
                str(self.db_path),
                self.bid_uid,
                [
                    InsertTakeoffSpec(
                        condition_uid=record.condition_uids[0],
                        page_uid=self.page_uids[0],
                        area_uid="0",
                        position=list(HOLE),
                    )
                ],
            )
            self.assertTrue(inserted.write_success)
            before_undo = dump_tables(self.db_path)
            outcomes = []
            applier.undo(uid, outcomes.append)
            self.assertFalse(outcomes[0].success)
            self.assertEqual(outcomes[0].code, "stale_changeset")
            self.assertEqual(dump_tables(self.db_path), before_undo)
            self.assertEqual(store.get(uid).status, "applied")

    def test_an_out_of_range_elevation_override_is_never_written(self):
        if self.skip_body:
            return
        before = dump_tables(self.db_path)
        with configured_app(self.home, self.db_path, self.bid_uid) as (
            container,
            bid_ref,
        ):
            store, proposals, _undo, _applier = self.harness(container, bid_ref)
            assumption = ChangesetAssumption(
                "a1", SUBJECT_TOP_ELEVATION, "c1", "", "not given", "", IMPACT_HIGH
            )
            added = proposals.add(
                self.changeset(top_elev_in=None, assumptions=(assumption,))
            )
            proposals.request_apply(added.uid)
            store.override_assumption(added.uid, "a1", "1e300")
            with self.assertRaises(ChangesetError) as raised:
                store.approve(added.uid)
            self.assertEqual(raised.exception.code, "assumption_unresolved")
        self.assertEqual(dump_tables(self.db_path), before)


if __name__ == "__main__":
    unittest.main()
