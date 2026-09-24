import sqlite3
import unittest
from unittest.mock import Mock
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import MutationOutcomeStatus
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from tests.test_infrastructure_lifecycle import (
    _SqliteDuplicateOps,
    _SqliteCursorWrapper,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    ExpectedResourceVersion,
    ConcurrencyToken,
    ResourceRef,
)
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    MissingBidOwnedUidError,
)
from tests import test_mdb_sql_behavior_parity as parity


class PlanPropertyOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER PRIMARY KEY);
            INSERT INTO Bids VALUES (7);
            CREATE TABLE BidAreas (UID INTEGER PRIMARY KEY, BidUID INTEGER);
            INSERT INTO BidAreas VALUES (1,7),(2,7),(3,7),(4,8);
            CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidUID INTEGER,
                BidPageUID INTEGER, BidConditionUID INTEGER, BidAreaUID INTEGER,
                ParentUID INTEGER, Position BLOB);
            INSERT INTO BidTakeoffs VALUES
                (10,7,20,30,1,NULL,'0;0;10;0;10;10'),
                (11,7,20,30,2,NULL,'20;0;30;0;30;10'),
                (12,7,20,30,NULL,NULL,'40;0;50;0;50;10'),
                (13,7,20,30,1,10,'1;1;2;1;2;2');
        """
        )
        self.conn.commit()
        self.ops = _SqliteDuplicateOps(self.conn)
        manager = SimpleNamespace(
            connection=self.connection,
            use_committed_writer_for_reads=lambda _path: None,
        )
        self.transaction_writer = MdbWriter(conn_manager=manager)
        self.ops._connection = self.transaction_writer._connection
        self.service = parity.MdbSqlBehaviorParityTests._local_composite_service()
        self.service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("database.mdb", "7"),
            get_all_takeoffs=self.takeoffs,
        )
        self.service._mutation_executor = SimpleNamespace(
            verify_plan_items_exist=lambda *args, **kwargs: MdbWriter.verify_plan_items_exist(
                self.ops, *args, **kwargs
            )
        )
        self.service._save_takeoffs_area = SimpleNamespace(
            execute=self.ops.save_takeoffs_area
        )
        self.service._execute_database_mutation = self.execute_mutation
        self.service._concurrency_tokens = SimpleNamespace(
            expected_versions=lambda _database, resources: tuple(
                ExpectedResourceVersion(resource, ConcurrencyToken(b"a" * 8))
                for resource in resources
            )
        )

    @contextmanager
    def connection(self, _path, *, autocommit):
        self.assertFalse(autocommit)
        yield SimpleNamespace(
            cursor=lambda: _SqliteCursorWrapper(self.conn),
            commit=self.conn.commit,
            rollback=self.conn.rollback,
        )

    def execute_mutation(self, database_id, _resources, operation, **_options):
        with self.transaction_writer._connection(database_id):
            value = operation(SimpleNamespace(record=lambda *_args, **_kwargs: None))
        return DatabaseMutationResult(
            operation_id="00000000-0000-0000-0000-000000000001",
            outcome_status=MutationOutcomeStatus.COMMITTED,
            value=value,
        )

    def snapshot(self):
        return self.conn.execute("SELECT * FROM BidTakeoffs ORDER BY UID").fetchall()

    def test_mdb_composite_restore_validates_external_parent_before_insert(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.insert_takeoff_spec_dto import (
            InsertTakeoffSpec,
        )

        self.conn.executescript(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER); INSERT INTO BidConditions VALUES (30,7); CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER); INSERT INTO BidPages VALUES (20,7); INSERT INTO Bids VALUES (8); INSERT INTO BidTakeoffs VALUES (90,8,20,30,1,NULL,'foreign');"
        )
        self.service._insert_takeoffs = SimpleNamespace(
            execute=self.ops.insert_takeoffs
        )
        spec = InsertTakeoffSpec("30", "20", "1", [1, 1, 2, 1, 2, 2], parent_uid="10")
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("10",),
            takeoff_specs=(spec,),
            takeoff_external_parent_sources=("10",),
        )
        result = self.service.execute_plan_items_paste_local(
            "database.mdb", payload, publish_database_refreshed_after_write=False
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        created = result.created_resource_ids[0]
        self.assertEqual(
            self.conn.execute(
                "SELECT ParentUID FROM BidTakeoffs WHERE UID=?", (created,)
            ).fetchone()[0],
            10,
        )
        before = self.snapshot()
        for parent_uid in ("90", "999"):
            result = self.service.execute_plan_items_paste_local(
                "database.mdb",
                replace(payload, takeoff_specs=(replace(spec, parent_uid=parent_uid),)),
                publish_database_refreshed_after_write=False,
            )
            self.assertEqual(
                result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
            self.assertEqual(self.snapshot(), before)
        # Restore an external-parent Backout first, then fail an internal child
        # insert. The outer MDB transaction must undo the first allocation.
        result = self.service.execute_plan_items_paste_local(
            "database.mdb",
            replace(
                payload,
                takeoff_source_uids=("10", "nested"),
                takeoff_specs=(spec, replace(spec, condition_uid="999")),
            ),
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertEqual(self.snapshot(), before)

    def test_external_parent_bindings_reject_incomplete_or_ambiguous_sources(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.insert_takeoff_spec_dto import (
            InsertTakeoffSpec,
        )

        for sources, parent_uid in (
            (("missing",), "10"),
            (("10", "10"), "10"),
            (("10",), "0"),
        ):
            with self.subTest(sources=sources, parent_uid=parent_uid):
                with self.assertRaises(ValueError):
                    PlanItemsPastePayload(
                        source_bid_uid="7",
                        destination_bid_uid="7",
                        takeoff_source_uids=("10",),
                        takeoff_specs=(
                            InsertTakeoffSpec(
                                "30", "20", "1", [0, 0, 1, 1], parent_uid=parent_uid
                            ),
                        ),
                        takeoff_external_parent_sources=sources,
                    )

    def capture(self):
        return self.service._plan_property_payload(
            "database.mdb",
            "7",
            "takeoff_area",
            [(uid, "3") for uid in ("10", "11", "12")],
        )

    def apply(self, payload):
        with self.transaction_writer._connection("database.mdb"):
            return self.service._apply_plan_property_payload(
                "database.mdb",
                "7",
                payload,
                tuple(ResourceRef("takeoff", str(uid), 7) for uid in (10, 11, 12)),
            )

    def test_old_selection_only_preflight_reproduces_exact_error_before_writes(self):
        before = self.snapshot()
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            "relationship graph changed before the Plan mutation",
        ):
            MdbWriter.verify_plan_items_exist(
                self.ops, "database.mdb", "7", ("10", "11", "12"), ()
            )
        self.assertEqual(self.snapshot(), before)

    def test_external_changes_reject_entire_captured_batch(self):
        mutations = (
            "DELETE FROM BidTakeoffs WHERE UID=11",
            "DELETE FROM BidTakeoffs WHERE UID=13",
            "UPDATE BidTakeoffs SET ParentUID=12 WHERE UID=13",
            "UPDATE BidTakeoffs SET ParentUID=12 WHERE UID=11",
            "UPDATE BidTakeoffs SET BidAreaUID=2 WHERE UID=10",
            "UPDATE BidTakeoffs SET BidPageUID=21 WHERE UID=10",
            "UPDATE BidTakeoffs SET BidConditionUID=31 WHERE UID=10",
            "UPDATE BidTakeoffs SET BidUID=8 WHERE UID=10",
            "INSERT INTO BidTakeoffs VALUES (14,7,20,30,1,10,'new')",
        )
        initial = self.snapshot()
        for sql in mutations:
            with self.subTest(sql=sql):
                self.conn.execute("DELETE FROM BidTakeoffs")
                self.conn.executemany(
                    "INSERT INTO BidTakeoffs VALUES (?,?,?,?,?,?,?)", initial
                )
                self.conn.commit()
                payload = self.capture()
                self.conn.execute(sql)
                self.conn.commit()
                before = self.snapshot()
                with self.assertRaises(MissingBidOwnedUidError):
                    self.apply(payload)
                self.assertEqual(self.snapshot(), before)

    def test_late_group_failure_rolls_back_earlier_group(self):
        before = self.snapshot()
        result = self.service.execute_plan_properties_local(
            "database.mdb",
            "7",
            "takeoff_area",
            [("10", "3"), ("11", "4")],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertEqual(self.snapshot(), before)

    def test_capture_rejects_wrong_bid_and_missing_selection(self):
        self.service._project_data.get_current_bid_ref = lambda: BidRef(
            "other.mdb", "7"
        )
        with self.assertRaisesRegex(ValueError, "current Bid"):
            self.capture()
        self.service._project_data.get_current_bid_ref = lambda: BidRef(
            "database.mdb", "7"
        )
        self.conn.execute("DELETE FROM BidTakeoffs WHERE UID=11")
        with self.assertRaisesRegex(ValueError, "no longer authoritative"):
            self.capture()

    def test_local_capture_rejection_returns_failure_without_raising_into_ui(self):
        self.conn.execute("DELETE FROM BidTakeoffs WHERE UID=11")
        self.conn.commit()
        before = self.snapshot()
        result = self.service.execute_plan_properties_local(
            "database.mdb",
            "7",
            "takeoff_area",
            [("10", "3"), ("11", "3")],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertIn("no longer authoritative", result.message)
        self.assertEqual(self.snapshot(), before)

    def test_queued_batch_freezes_child_ownership_and_declares_dependencies(self):
        queued = []
        self.service._sql_collaboration_provider = lambda: SimpleNamespace(
            queue_request=lambda *args: queued.append(args) or 1
        )
        self.service.queue_plan_properties(
            "database.mdb",
            "7",
            "takeoff_area",
            [("10", "3"), ("11", "3"), ("12", "3")],
            lambda _result: None,
        )
        request, execute, _callback = queued.pop()
        self.assertEqual(
            {item.uid for item in request.payload.takeoff_ownership},
            {"10", "11", "12", "13"},
        )
        self.assertIn(ResourceRef("takeoff", "13", 7), request.dependency_resources)
        self.assertNotIn(ResourceRef("takeoff", "13", 7), request.resources)
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual([row[4] for row in self.snapshot()], [3, 3, 3, 1])

    def test_queued_external_reparent_rejects_without_assignment(self):
        queued = []
        self.service._sql_collaboration_provider = lambda: SimpleNamespace(
            queue_request=lambda *args: queued.append(args) or 1
        )
        self.service.queue_plan_properties(
            "database.mdb",
            "7",
            "takeoff_area",
            [("10", "3"), ("11", "3")],
            lambda _result: None,
        )
        self.conn.execute("UPDATE BidTakeoffs SET ParentUID=12 WHERE UID=13")
        self.conn.commit()
        before = self.snapshot()
        with self.assertRaises(MissingBidOwnedUidError):
            queued[0][1]()
        self.assertEqual(self.snapshot(), before)

    def test_grouped_undo_redo_preserves_distinct_areas_and_child(self):
        before = self.snapshot()
        for assignments in (
            [("10", "3"), ("11", "3"), ("12", "3")],
            [("10", "1"), ("11", "2"), ("12", "0")],
            [("10", "3"), ("11", "3"), ("12", "3")],
            [("10", "1"), ("11", "2"), ("12", "0")],
        ):
            result = self.service.execute_plan_properties_local(
                "database.mdb",
                "7",
                "takeoff_area",
                assignments,
                publish_database_refreshed_after_write=False,
            )
            self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(self.snapshot(), before)

    def test_queued_resource_replacement_cannot_adopt_new_concurrency_version(self):
        from ost_visualizer.application.dtos.collaboration_dtos import ConcurrencyToken
        from ost_visualizer.application.services.base_write_service import (
            DatabaseMutationWriteService,
        )
        from ost_visualizer.application.services.database_concurrency_token_service import (
            DatabaseConcurrencyTokenService,
        )
        from ost_visualizer.application.services.database_session_registry import (
            DatabaseSessionRegistry,
        )
        from ost_visualizer.application.services.local_draft_registry import (
            LocalDraftRegistry,
        )

        queued = []
        self.service._sql_collaboration_provider = lambda: SimpleNamespace(
            queue_request=lambda *args: queued.append(args) or 1
        )
        resources = tuple(
            ResourceRef("takeoff", str(uid), 7) for uid in (10, 11, 12, 13)
        ) + (
            ResourceRef("area", "3", 7),
        )
        current_versions = {
            resource: ConcurrencyToken(b"a" * 8) for resource in resources
        }
        tokens = DatabaseConcurrencyTokenService(
            SimpleNamespace(read_bid_versions=lambda *_args: dict(current_versions)),
            LocalDraftRegistry(),
        )
        tokens.load_bid("database.mdb", "7")
        self.service._concurrency_tokens = tokens
        self.service._session_registry = DatabaseSessionRegistry()
        self.service._database_capability_service = SimpleNamespace(
            is_editable=lambda *_args: True
        )
        self.service._event_bus = Mock()
        self.service._execute_database_mutation = (
            DatabaseMutationWriteService._execute_database_mutation.__get__(
                self.service
            )
        )

        def execute(request, operation):
            if any(
                item.expected != current_versions[item.resource]
                for item in request.expected_versions
            ):
                return DatabaseMutationResult(
                    request.operation_id, MutationOutcomeStatus.CONFLICT
                )
            return self.execute_mutation(
                request.database_id, request.resources, operation
            )

        self.service._mutation_executor.execute = execute
        for replaced_resource in (
            ResourceRef("area", "3", 7),
            ResourceRef("takeoff", "10", 7),
            ResourceRef("takeoff", "13", 7),
        ):
            with self.subTest(replaced_resource=replaced_resource):
                self.service.queue_plan_properties(
                    "database.mdb",
                    "7",
                    "takeoff_area",
                    [("10", "3"), ("11", "3")],
                    lambda _result: None,
                    dependency_resources=(ResourceRef("area", "3", 7),),
                )
                # Recreate the physical row with the same UID/ownership, then
                # hydrate fresh objects and tokens before the queued write runs.
                if replaced_resource.resource_type == "area":
                    self.conn.execute("DELETE FROM BidAreas WHERE UID=3")
                    self.conn.execute("INSERT INTO BidAreas VALUES (3,7)")
                else:
                    row = list(
                        self.conn.execute(
                            "SELECT * FROM BidTakeoffs WHERE UID=?",
                            (replaced_resource.resource_id,),
                        ).fetchone()
                    )
                    self.conn.execute(
                        "DELETE FROM BidTakeoffs WHERE UID=?",
                        (replaced_resource.resource_id,),
                    )
                    row[-1] = "100;100;110;100;110;110"
                    self.conn.execute(
                        "INSERT INTO BidTakeoffs VALUES (?,?,?,?,?,?,?)", row
                    )
                self.conn.commit()
                before = self.snapshot()
                current_versions[replaced_resource] = ConcurrencyToken(b"b" * 8)
                tokens.load_bid("database.mdb", "7")
                self.service._project_data.get_all_takeoffs = lambda: [
                    replace(item) for item in self.takeoffs()
                ]
                result = queued[-1][1]()
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(self.snapshot(), before)
        self.service.queue_plan_properties(
            "database.mdb",
            "7",
            "takeoff_area",
            [("10", "3"), ("11", "3")],
            lambda _result: None,
            dependency_resources=(ResourceRef("area", "3", 7),),
        )
        self.assertEqual(
            queued[-1][1]().outcome_status, MutationOutcomeStatus.COMMITTED
        )

    def test_condition_multi_edit_uses_same_dependency_contract(self):
        self.conn.executescript(
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER);"
            "INSERT INTO BidConditions VALUES (30,7),(31,7);"
        )
        self.service._save_takeoffs_condition = SimpleNamespace(
            execute=self.ops.save_takeoffs_condition
        )
        before = self.snapshot()
        result = self.service.execute_plan_properties_local(
            "database.mdb",
            "7",
            "takeoff_condition",
            [("10", "31"), ("11", "31"), ("12", "31")],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        after = self.snapshot()
        self.assertEqual([row[3] for row in after], [31, 31, 31, 30])
        self.assertEqual(
            [row[:3] + row[4:] for row in after],
            [row[:3] + row[4:] for row in before],
        )

    def test_nested_descendants_duplicate_selection_and_snapshot_order(self):
        self.conn.execute(
            "INSERT INTO BidTakeoffs VALUES (14,7,20,30,2,13,'grandchild')"
        )
        self.conn.commit()
        updates = [("13", "3"), ("10", "3"), ("10", "3")]
        payload = self.service._plan_property_payload(
            "database.mdb", "7", "takeoff_area", updates
        )
        self.assertEqual(
            [item.uid for item in payload.takeoff_ownership], ["10", "13", "14"]
        )
        before = self.snapshot()
        self.apply(
            replace(
                payload, takeoff_ownership=tuple(reversed(payload.takeoff_ownership))
            )
        )
        after = self.snapshot()
        self.assertEqual([row[4] for row in after], [3, 2, None, 3, 2])
        self.assertEqual(
            [row[:4] + row[5:] for row in after], [row[:4] + row[5:] for row in before]
        )

    def test_selected_backout_does_not_modify_its_parent_or_siblings(self):
        before = self.snapshot()
        result = self.service.execute_plan_properties_local(
            "database.mdb",
            "7",
            "takeoff_area",
            [("13", "3")],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        after = self.snapshot()
        self.assertEqual(after[:3], before[:3])
        self.assertEqual(after[3][4:6], (3, 10))

    def test_snapshot_is_detached_from_hydrated_objects_and_updates(self):
        takeoffs = self.takeoffs()
        self.service._project_data.get_all_takeoffs = lambda: takeoffs
        updates = [["10", "3"], ["11", "3"]]
        payload = self.service._plan_property_payload(
            "database.mdb", "7", "takeoff_area", updates
        )
        updates[0][1] = "2"
        takeoffs[0].area_uid = "2"
        self.assertEqual(payload.decoded_updates(), [["10", "3"], ["11", "3"]])
        self.assertEqual(payload.takeoff_ownership[0].area_uid, "1")
        with self.assertRaises(FrozenInstanceError):
            payload.takeoff_ownership[0].area_uid = "2"

    def test_deleted_target_area_rejects_without_partial_assignment(self):
        payload = self.capture()
        self.conn.execute("DELETE FROM BidAreas WHERE UID=3")
        self.conn.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.apply(payload)
        self.assertEqual(self.snapshot(), before)

    def test_new_foreign_bid_child_rejects_captured_graph(self):
        payload = self.capture()
        self.conn.execute("INSERT INTO Bids VALUES (8)")
        self.conn.execute(
            "INSERT INTO BidTakeoffs VALUES (14,8,99,30,1,10,'foreign child')"
        )
        self.conn.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(MissingBidOwnedUidError, "relationship graph"):
            self.apply(payload)
        self.assertEqual(self.snapshot(), before)

    def test_later_condition_failure_rolls_back_earlier_group(self):
        self.conn.executescript(
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER); INSERT INTO BidConditions VALUES (30,7),(31,7),(32,8);"
        )
        self.service._save_takeoffs_condition = SimpleNamespace(
            execute=self.ops.save_takeoffs_condition
        )
        before = self.snapshot()
        result = self.service.execute_plan_properties_local(
            "database.mdb",
            "7",
            "takeoff_condition",
            [("10", "31"), ("11", "32")],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertEqual(self.snapshot(), before)

    def test_unassigned_area_is_not_a_persistent_concurrency_dependency(self):
        queued = []
        self.service._sql_collaboration_provider = lambda: SimpleNamespace(
            queue_request=lambda *args: queued.append(args) or 1
        )
        versions = self.service._concurrency_tokens.expected_versions
        self.service._concurrency_tokens.expected_versions = (
            lambda database, resources: versions(
                database,
                tuple(
                    resource
                    for resource in resources
                    if resource.resource_type != "area"
                ),
            )
        )
        self.service.queue_plan_properties(
            "database.mdb",
            "7",
            "takeoff_area",
            [("10", "0")],
            lambda _result: None,
            dependency_resources=(ResourceRef("area", "0", 7),),
        )
        result = queued[0][1]()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertIsNone(self.snapshot()[0][4])

    def test_missing_submission_version_rejects_before_queueing(self):
        queued = []
        self.service._sql_collaboration_provider = lambda: SimpleNamespace(
            queue_request=lambda *args: queued.append(args) or 1
        )
        self.service._concurrency_tokens.expected_versions = lambda *_args: ()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Refresh the Bid"):
            self.service.queue_plan_properties(
                "database.mdb", "7", "takeoff_area", [("10", "3")], lambda _result: None
            )
        self.assertEqual(queued, [])
        self.assertEqual(self.snapshot(), before)

    def takeoffs(self):
        return [
            Takeoff(
                uid=str(uid),
                page_uid=str(page),
                condition_uid=str(condition),
                area_uid=str(area or "0"),
                parent_uid=str(parent or "0"),
            )
            for uid, page, condition, area, parent in self.conn.execute(
                "SELECT UID,BidPageUID,BidConditionUID,BidAreaUID,ParentUID FROM BidTakeoffs"
            )
        ]

    def test_multi_assignment_includes_children_in_validation_not_in_updates(self):
        geometry = self.conn.execute(
            "SELECT UID,Position,ParentUID FROM BidTakeoffs"
        ).fetchall()
        for uids in (("10", "11"), ("10", "11", "12"), ("10", "11", "12")):
            result = self.service.execute_plan_properties_local(
                "database.mdb",
                "7",
                "takeoff_area",
                [(uid, "3") for uid in uids],
                publish_database_refreshed_after_write=False,
            )
            self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
            for uid in uids:
                self.assertEqual(
                    self.conn.execute(
                        "SELECT BidAreaUID FROM BidTakeoffs WHERE UID=?", (uid,)
                    ).fetchone()[0],
                    3,
                )
        self.assertEqual(
            self.conn.execute(
                "SELECT BidAreaUID FROM BidTakeoffs WHERE UID=13"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT UID,Position,ParentUID FROM BidTakeoffs"
            ).fetchall(),
            geometry,
        )
