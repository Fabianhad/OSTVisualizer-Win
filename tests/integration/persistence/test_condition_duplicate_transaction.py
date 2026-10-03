import json
import logging
import sqlite3
import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    ConcurrencyToken,
    DatabaseMutationResult,
    DurableOperationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.dtos.condition_takeoff_reassignment import (
    ConditionTakeoffReassignment,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.use_cases.project.duplicate_conditions_use_case import (
    DuplicateConditionsUseCase,
)
from ost_visualizer.application.use_cases.project.save_takeoffs_condition_use_case import (
    SaveTakeoffsConditionUseCase,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from tests.helpers.mdb.operations import _SqliteCursorWrapper, _SqliteSchema
from tests.application.services.test_project_write_service import _CapturedQueueProvider


class _Schema(_SqliteSchema):
    def require_table(self, table):
        if self.optional_table_missing(table):
            raise RuntimeError(f"Missing {table}")


class _Cursor(_SqliteCursorWrapper):
    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (tuple, list)):
            params = tuple(params[0])
        return super().execute(query, *params)


class _Connection:
    def __init__(self, database):
        self.database = database
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self.database)

    def commit(self):
        self.database.commit()
        self.commits += 1

    def rollback(self):
        self.database.rollback()
        self.rollbacks += 1


class _Connections:
    def __init__(self, connection):
        self.value = connection

    @contextmanager
    def connection(self, _path, *, autocommit):
        assert not autocommit
        yield self.value

    def use_committed_writer_for_reads(self, _path):
        pass


class _TransactionWriter(MdbWriter):
    def __init__(self, database):
        self.connection = _Connection(database)
        super().__init__(_Connections(self.connection))
        self.schema = _Schema(database)
        self.changes = []

    def _schema(self, _connection):
        return self.schema

    def execute(self, request, operation):
        # The same outer transaction contract used by DatabaseProjectWriter for MDB.
        changes = Mock()
        with self._connection(request.database_id):
            value = operation(changes)
        self.changes.extend(changes.record.call_args_list)
        return DatabaseMutationResult(
            request.operation_id, MutationOutcomeStatus.COMMITTED, value=value
        )


class ConditionDuplicateTransactionTests(unittest.TestCase):
    def setUp(self):
        from ost_visualizer.application.services.database_concurrency_token_service import (
            DatabaseConcurrencyTokenService,
        )
        from ost_visualizer.application.services.database_session_registry import (
            DatabaseSessionRegistry,
        )
        from ost_visualizer.application.services.local_draft_registry import (
            LocalDraftRegistry,
        )

        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript(
            """
            CREATE TABLE Bids (UID INTEGER PRIMARY KEY);
            INSERT INTO Bids VALUES (7);
            CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER);
            INSERT INTO BidPages VALUES (10, 7), (11, 7);
            CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT,
                Height REAL, BidLayerUID INTEGER, BidConditionFolderUID INTEGER, Type INTEGER);
            INSERT INTO BidConditions VALUES (20, 7, 'source-guid', 1, 'Source', 12.5, 8, 9, 0),
                (21, 7, 'other-guid', 2, 'Other', 0, 8, 9, 0);
            CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, BidConditionUID INTEGER);
            INSERT INTO BidTakeoffs VALUES (1, 7, 10, 20), (2, 7, 10, 20), (3, 7, 11, 20), (4, 7, 10, 21);
            CREATE TABLE BidTexts (UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, Text TEXT);
            INSERT INTO BidTexts VALUES (1, 7, 10, 'Same raw UID');
        """
        )
        self.assignment = ConditionTakeoffReassignment("20", "10", ("1", "2"))
        self.writer = _TransactionWriter(self.db)
        self.service = ProjectWriteService.__new__(ProjectWriteService)
        self.service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("database", "7"),
            get_all_takeoffs=self.takeoffs,
        )
        self.service._duplicate_conditions = DuplicateConditionsUseCase(self.writer)
        self.service._save_takeoffs_condition = SaveTakeoffsConditionUseCase(
            self.writer
        )
        self.service._mutation_executor = self.writer
        self.service._bid_write_guard = Mock()
        self.service._bid_write_guard.blocks_active_locked_bid_write.return_value = (
            False
        )
        self.service._database_capability_service = Mock()
        self.service._database_capability_service.is_editable.return_value = True
        self.service._session_registry = DatabaseSessionRegistry()
        self.service.logger = logging.getLogger(__name__)
        self.service._event_bus = Mock()
        self.service._reload_database = Mock(return_value=True)
        self.tokens = {
            ResourceRef(kind, uid, 7): ConcurrencyToken(bytes([index]) * 8)
            for index, (kind, uid) in enumerate(
                (
                    ("takeoff", "1"),
                    ("takeoff", "2"),
                    ("condition", "20"),
                    ("page", "10"),
                ),
                1,
            )
        }
        reader = Mock()
        reader.read_bid_versions.return_value = self.tokens
        self.service._concurrency_tokens = DatabaseConcurrencyTokenService(
            reader, LocalDraftRegistry()
        )
        self.service._concurrency_tokens.load_bid("database", "7")
        self.provider = _CapturedQueueProvider()
        self.service._sql_collaboration_provider = lambda: self.provider

    def takeoffs(self):
        columns = self.writer.schema.get_columns("BidTakeoffs")
        parent_column = "ParentUID" if "ParentUID" in columns else "NULL"
        return [
            Takeoff(
                uid=str(uid),
                page_uid=str(page),
                condition_uid=str(condition),
                parent_uid=str(parent or 0),
            )
            for uid, page, condition, parent in self.db.execute(
                f"SELECT UID, BidPageUID, BidConditionUID, {parent_column} FROM BidTakeoffs"
            )
        ]

    def run_duplicate(self, *, sql=False):
        if not sql:
            return self.service.duplicate_conditions_result(
                "database", "7", ["20"], reassign_takeoffs=self.assignment
            )
        self.service.queue_conditions_duplicate(
            "database", "7", ["20"], Mock(), reassign_takeoffs=self.assignment
        )
        _request, execute, _callback = self.provider.requests[-1]
        return execute()

    def rows(self):
        return self.db.execute(
            "SELECT UID, BidPageUID, BidConditionUID FROM BidTakeoffs ORDER BY UID"
        ).fetchall()

    def test_mdb_transaction_duplicates_all_fields_and_reassigns_only_captured_page(
        self,
    ):
        result = self.run_duplicate()
        self.assertTrue(result.success)
        # BidConditions held UIDs 20 and 21, so the duplicate is the next row.
        self.assertEqual(result.value, ["22"])
        new_uid = int(result.value[0])
        self.assertEqual(
            self.rows(), [(1, 10, new_uid), (2, 10, new_uid), (3, 11, 20), (4, 10, 21)]
        )
        new = self.db.execute(
            "SELECT Name, Height, BidLayerUID, BidConditionFolderUID, Type, GUID, RefNo FROM BidConditions WHERE UID=?",
            (new_uid,),
        ).fetchone()
        self.assertEqual(new[:5], ("Source", 12.5, 8, 9, 0))
        self.assertNotEqual(new[5], "source-guid")
        self.assertEqual(new[6], 3)
        self.assertEqual(
            self.db.execute("SELECT * FROM BidTexts").fetchall(),
            [(1, 7, 10, "Same raw UID")],
        )
        self.assertEqual(self.writer.connection.commits, 1)
        self.service._reload_database.assert_called_once()
        self.service._event_bus.publish.assert_called_once()
        event_args = self.service._event_bus.publish.call_args
        self.assertEqual(
            (
                event_args.kwargs["condition_uids"],
                event_args.kwargs["change_operations"],
                event_args.kwargs["bid_uid"],
            ),
            (["22"], ["create"], "7"),
        )

    def test_duplicate_reassign_preserves_unselected_child_from_other_condition(self):
        self.db.execute("ALTER TABLE BidTakeoffs ADD COLUMN ParentUID INTEGER")
        self.db.execute("UPDATE BidTakeoffs SET ParentUID=1 WHERE UID=4")
        self.db.commit()
        result = self.run_duplicate()
        self.assertTrue(result.success, result.failure_reason)
        self.assertEqual(self.rows()[-1], (4, 10, 21))
        self.assertEqual(
            self.db.execute("SELECT ParentUID FROM BidTakeoffs WHERE UID=4").fetchone(),
            (1,),
        )

    def test_queued_duplicate_reassign_preserves_unselected_child(self):
        self.db.execute("ALTER TABLE BidTakeoffs ADD COLUMN ParentUID INTEGER")
        self.db.execute("UPDATE BidTakeoffs SET ParentUID=1 WHERE UID=4")
        self.db.commit()
        self.service._concurrency_tokens.apply_result(
            "database", {ResourceRef("takeoff", "4", 7): ConcurrencyToken(b"c" * 8)}
        )
        result = self.run_duplicate(sql=True)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(self.rows()[-1], (4, 10, 21))

    def test_queued_duplicate_retains_child_snapshot_and_rolls_back_on_reparent(self):
        self.db.execute("ALTER TABLE BidTakeoffs ADD COLUMN ParentUID INTEGER")
        self.db.execute("UPDATE BidTakeoffs SET ParentUID=1 WHERE UID=4")
        self.db.commit()
        child_resource = ResourceRef("takeoff", "4", 7)
        self.service._concurrency_tokens.apply_result(
            "database", {child_resource: ConcurrencyToken(b"c" * 8)}
        )
        self.service.queue_conditions_duplicate(
            "database", "7", ["20"], Mock(), reassign_takeoffs=self.assignment
        )
        request, execute, _callback = self.provider.requests[-1]
        self.assertIn(child_resource, request.dependency_resources)
        self.assertNotIn(child_resource, request.resources)
        self.assertEqual(
            json.loads(request.payload.values_json)["takeoff_ownership"][-1][
                "parent_uid"
            ],
            "1",
        )
        self.db.execute("UPDATE BidTakeoffs SET ParentUID=2 WHERE UID=4")
        self.db.commit()
        before = self.rows()
        with self.assertRaisesRegex(RuntimeError, "ownership changed"):
            execute()
        self.assertEqual(self.rows(), before)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(self.writer.connection.rollbacks, 1)

    def test_queued_sql_work_uses_same_duplicate_and_property_paths_in_one_transaction(
        self,
    ):
        result = self.run_duplicate(sql=True)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.authoritative_result.created_resource_ids, ("22",))
        new_uid = int(result.authoritative_result.created_resource_ids[0])
        self.assertEqual(
            self.rows(), [(1, 10, new_uid), (2, 10, new_uid), (3, 11, 20), (4, 10, 21)]
        )
        self.assertEqual(
            result.authoritative_result.affected_families, ("conditions", "takeoffs")
        )
        self.assertEqual(result.authoritative_result.affected_page_uids, ("10",))
        self.assertEqual(self.writer.connection.commits, 1)
        self.assertEqual(len(self.provider.requests), 1)
        # The recorder (what SQL collaboration broadcasts) sees the reassigned
        # takeoffs, the new condition and its collection exactly once each.
        reassigned = ("condition",)
        self.assertEqual(
            self.writer.changes,
            [
                call(
                    ResourceRef("takeoff", "1", 7),
                    ChangeOperation.UPDATE,
                    changed_fields=reassigned,
                ),
                call(
                    ResourceRef("takeoff", "2", 7),
                    ChangeOperation.UPDATE,
                    changed_fields=reassigned,
                ),
                call(ResourceRef("condition", "22", 7), ChangeOperation.CREATE),
                call(
                    ResourceRef("conditions_collection", "7", 7),
                    ChangeOperation.UPDATE,
                ),
            ],
        )
        self.service._reload_database.assert_not_called()
        self.service._event_bus.publish.assert_not_called()

    def test_failed_reassignment_rolls_back_duplicate_and_every_takeoff(self):
        self.db.executescript(
            """CREATE TRIGGER reject_reassign BEFORE UPDATE ON BidTakeoffs
            BEGIN SELECT RAISE(ABORT, 'Rejected assignment'); END;"""
        )
        result = self.run_duplicate()
        self.assertFalse(result.write_success)
        self.assertEqual(
            self.db.execute("SELECT UID FROM BidConditions ORDER BY UID").fetchall(),
            [(20,), (21,)],
        )
        self.assertEqual(
            self.rows(), [(1, 10, 20), (2, 10, 20), (3, 11, 20), (4, 10, 21)]
        )
        self.assertEqual(self.writer.connection.rollbacks, 1)
        self.service._reload_database.assert_not_called()

    def test_duplicate_failure_never_reassigns(self):
        self.db.executescript(
            """CREATE TRIGGER reject_duplicate BEFORE INSERT ON BidConditions
            BEGIN SELECT RAISE(ABORT, 'Rejected duplicate'); END;"""
        )
        result = self.run_duplicate()
        self.assertFalse(result.write_success)
        self.assertEqual(
            self.rows(), [(1, 10, 20), (2, 10, 20), (3, 11, 20), (4, 10, 21)]
        )
        self.assertEqual(self.writer.connection.commits, 0)
        self.service._reload_database.assert_not_called()

    def test_moved_takeoff_rejects_entire_transaction_before_duplication(self):
        self.db.execute("UPDATE BidTakeoffs SET BidPageUID=11 WHERE UID=2")
        self.db.commit()
        result = self.run_duplicate()
        self.assertFalse(result.write_success)
        self.assertIn("changed Page or Condition", result.failure_reason)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(
            self.rows(), [(1, 10, 20), (2, 11, 20), (3, 11, 20), (4, 10, 21)]
        )

    def test_queued_work_revalidates_takeoffs_at_execution(self):
        self.service.queue_conditions_duplicate(
            "database", "7", ["20"], Mock(), reassign_takeoffs=self.assignment
        )
        self.db.execute("UPDATE BidTakeoffs SET BidConditionUID=21 WHERE UID=2")
        self.db.commit()
        with self.assertRaisesRegex(RuntimeError, "changed Page or Condition"):
            self.provider.requests[0][1]()
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(
            self.rows(), [(1, 10, 20), (2, 10, 21), (3, 11, 20), (4, 10, 21)]
        )

    def test_deleted_captured_takeoff_rejects_local_and_queued_duplicate(self):
        self.service.queue_conditions_duplicate(
            "database", "7", ["20"], Mock(), reassign_takeoffs=self.assignment
        )
        self.db.execute("DELETE FROM BidTakeoffs WHERE UID=2")
        self.db.commit()
        expected_rows = [(1, 10, 20), (3, 11, 20), (4, 10, 21)]
        with self.assertRaisesRegex(RuntimeError, "deleted or replaced"):
            self.provider.requests[0][1]()
        self.assertEqual(self.rows(), expected_rows)
        local = self.run_duplicate()
        self.assertFalse(local.write_success)
        self.assertIn("no longer authoritative", local.failure_reason)
        self.assertEqual(self.rows(), expected_rows)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(self.writer.connection.commits, 0)

    def test_queued_work_retains_submission_versions_across_remote_projection(self):
        self.service.queue_conditions_duplicate(
            "database", "7", ["20"], Mock(), reassign_takeoffs=self.assignment
        )
        self.service._concurrency_tokens.apply_result(
            "database",
            {resource: ConcurrencyToken(b"changed!") for resource in self.tokens},
        )
        with patch.object(self.writer, "execute", wraps=self.writer.execute) as execute:
            self.provider.requests[0][1]()
        request = execute.call_args.args[0]
        self.assertEqual(
            {item.resource: item.expected for item in request.expected_versions},
            self.tokens,
        )

    def test_missing_loaded_versions_rejects_sql_submission(self):
        self.service._concurrency_tokens.clear_database("database")
        with self.assertRaisesRegex(ValueError, "Refresh the Bid"):
            self.service.queue_conditions_duplicate(
                "database", "7", ["20"], Mock(), reassign_takeoffs=self.assignment
            )
        self.assertEqual(self.provider.requests, [])

    def test_refresh_failure_reports_committed_combined_operation(self):
        self.service._reload_database.return_value = False
        result = self.run_duplicate()
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(self.rows()[2:], [(3, 11, 20), (4, 10, 21)])
        self.assertEqual(self.writer.connection.commits, 1)

    def test_driver_reassignment_failure_rolls_back_and_returns_failure(self):
        import pyodbc

        with patch.object(
            self.writer,
            "save_takeoffs_condition",
            side_effect=pyodbc.Error("driver rejected assignment"),
        ):
            result = self.run_duplicate()
        self.assertFalse(result.write_success)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(self.writer.connection.rollbacks, 1)
        self.service._reload_database.assert_not_called()

    def test_queued_reassignment_failure_rolls_back_the_created_condition(self):
        self.db.executescript(
            """CREATE TRIGGER reject_reassign BEFORE UPDATE ON BidTakeoffs
            BEGIN SELECT RAISE(ABORT, 'Rejected assignment'); END;"""
        )
        with self.assertRaisesRegex(
            RuntimeError, "plan property update was incomplete"
        ):
            self.run_duplicate(sql=True)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(
            self.rows(), [(1, 10, 20), (2, 10, 20), (3, 11, 20), (4, 10, 21)]
        )
        self.assertEqual(self.writer.connection.rollbacks, 1)

    def test_durable_recovery_retains_both_families_and_original_page(self):
        import json
        from ost_visualizer.application.services.sql_collaboration_coordinator import (
            SqlCollaborationCoordinator,
        )

        result = self.run_duplicate(sql=True)
        request = self.provider.requests[0][0]
        durable = DurableOperationResult(
            database_id=request.database_id,
            operation_id=request.operation_id,
            found=True,
            mutation_type=request.mutation_type.value,
            request_hash=request.request_hash,
            result_format_version=1,
            result_payload=json.dumps(
                {"value": list(result.created_resource_ids), "value_available": True}
            ),
        )
        recovered = SqlCollaborationCoordinator._recovered_authoritative_result(
            request, durable
        )
        self.assertEqual(result.created_resource_ids, ("22",))
        self.assertEqual(recovered.created_resource_ids, ("22",))
        self.assertEqual(set(recovered.affected_families), {"conditions", "takeoffs"})
        self.assertEqual(recovered.affected_page_uids, ("10",))
        self.assertEqual(len(self.provider.requests), 1)

    def test_plain_duplicate_returns_the_new_uids_and_leaves_takeoffs_alone(self):
        self.assertEqual(
            self.service.duplicate_conditions("database", "7", ["20"]), ["22"]
        )
        self.assertEqual(
            self.rows(), [(1, 10, 20), (2, 10, 20), (3, 11, 20), (4, 10, 21)]
        )
        self.assertEqual(self.writer.connection.commits, 1)
        self.service._reload_database.assert_called_once()

    def test_plain_duplicate_failure_returns_no_uids(self):
        self.db.executescript(
            """CREATE TRIGGER reject_duplicate BEFORE INSERT ON BidConditions
            BEGIN SELECT RAISE(ABORT, 'Rejected duplicate'); END;"""
        )
        self.assertEqual(self.service.duplicate_conditions("database", "7", ["20"]), [])
        self.assertEqual(self.writer.connection.commits, 0)
        self.service._reload_database.assert_not_called()

    def test_a_blocked_bid_refuses_the_duplicate_before_any_database_work(self):
        guard = self.service._bid_write_guard.blocks_active_locked_bid_write
        guard.return_value = True
        result = self.run_duplicate()
        self.assertFalse(result.write_success)
        self.assertFalse(result.reload_success)
        guard.assert_called_once_with("database", "7")
        self.assertEqual(
            self.rows(), [(1, 10, 20), (2, 10, 20), (3, 11, 20), (4, 10, 21)]
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(self.writer.connection.commits, 0)
        self.service._reload_database.assert_not_called()

    def test_a_mutation_that_is_not_committed_reports_failure_without_reload(self):
        rejected = DatabaseMutationResult(
            str(uuid.uuid4()), MutationOutcomeStatus.REJECTED
        )
        with patch.object(self.writer, "execute", return_value=rejected):
            result = self.run_duplicate()
        self.assertFalse(result.write_success)
        self.assertFalse(result.reload_success)
        self.assertEqual(result.value, [])
        self.service._reload_database.assert_not_called()
        self.service._event_bus.publish.assert_not_called()

    def test_an_incomplete_identity_map_from_the_duplicate_rolls_everything_back(self):
        for label, returned in (("empty", []), ("none", None)):
            with self.subTest(label):
                self.setUp()
                with patch.object(
                    DuplicateConditionsUseCase, "execute", return_value=returned
                ):
                    result = self.run_duplicate()
                self.assertFalse(result.write_success)
                self.assertIn("incomplete identity map", result.failure_reason)
                self.assertEqual(
                    self.rows(), [(1, 10, 20), (2, 10, 20), (3, 11, 20), (4, 10, 21)]
                )
                self.assertEqual(self.writer.connection.rollbacks, 1)
                self.service._reload_database.assert_not_called()

    def queue_with_target_changes(self, update_result):
        calls = []

        class _UpdateCondition:
            def execute(inner, database_id, bid_uid, condition_uid, updates):
                calls.append(
                    (database_id, bid_uid, condition_uid, updates.get_changes())
                )
                return update_result

        self.service._update_condition = _UpdateCondition()
        self.service.queue_conditions_duplicate(
            "database",
            "7",
            ["20"],
            Mock(),
            target_changes={"folder_uid": "9", "cdn_type_uid": "4", "name": "Copy"},
        )
        return self.provider.requests[-1], calls

    def test_target_changes_are_applied_to_the_duplicate_in_the_same_transaction(self):
        from ost_visualizer.application.dtos.update_condition_dto import (
            UpdateConditionResultDto,
        )

        (request, execute, _callback), calls = self.queue_with_target_changes(
            UpdateConditionResultDto(success=True)
        )
        dependencies = set(request.dependency_resources)
        self.assertIn(ResourceRef("condition_folder", "9", 7), dependencies)
        self.assertIn(ResourceRef("condition_type", "4"), dependencies)
        self.assertIn(
            ResourceRef("condition_types_collection", "database"), dependencies
        )
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            calls,
            [
                (
                    "database",
                    "7",
                    "22",
                    {"folder_uid": "9", "cdn_type_uid": "4", "name": "Copy"},
                )
            ],
        )
        self.assertEqual(
            json.loads(request.payload.values_json)["target_changes"],
            {"folder_uid": "9", "cdn_type_uid": "4", "name": "Copy"},
        )
        self.assertEqual(self.writer.connection.commits, 1)

    def test_a_target_change_that_fails_rolls_the_duplicate_back(self):
        from ost_visualizer.application.dtos.update_condition_dto import (
            UpdateConditionResultDto,
        )

        for error, expected in (
            ("Folder is locked.", "Folder is locked."),
            (None, "The duplicated condition target update was incomplete."),
        ):
            with self.subTest(error=error):
                self.setUp()
                (_request, execute, _callback), _calls = self.queue_with_target_changes(
                    UpdateConditionResultDto(success=False, error=error)
                )
                with self.assertRaisesRegex(RuntimeError, expected):
                    execute()
                self.assertEqual(
                    self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0],
                    2,
                )
                self.assertEqual(self.writer.connection.rollbacks, 1)

    def test_the_captured_page_and_condition_must_belong_to_the_bid(self):
        for label, statement in (
            ("page", "UPDATE BidPages SET BidUID=8 WHERE UID=10"),
            ("condition", "UPDATE BidConditions SET BidUID=8 WHERE UID=20"),
        ):
            with self.subTest(label):
                self.setUp()
                self.db.execute(statement)
                self.db.commit()
                result = self.run_duplicate()
                self.assertFalse(result.write_success)
                self.assertEqual(
                    self.rows(), [(1, 10, 20), (2, 10, 20), (3, 11, 20), (4, 10, 21)]
                )
                self.assertEqual(
                    self.db.execute(
                        "SELECT COUNT(*) FROM BidConditions WHERE BidUID=7"
                    ).fetchone()[0],
                    1 if label == "condition" else 2,
                )
                self.service._reload_database.assert_not_called()

    def test_missing_takeoff_columns_are_reported_by_name_before_any_change(self):
        captured = self.takeoffs()
        self.service._project_data.get_all_takeoffs = lambda: captured
        self.db.execute("ALTER TABLE BidTakeoffs DROP COLUMN BidPageUID")
        self.db.commit()
        result = self.run_duplicate()
        self.assertFalse(result.write_success)
        self.assertEqual(result.failure_reason, "Missing BidTakeoffs.BidPageUID")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(self.writer.connection.commits, 0)
