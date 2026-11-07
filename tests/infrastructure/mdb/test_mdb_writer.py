from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
import unittest
import sqlite3
import tempfile
import threading
import logging
import contextlib
import json
import os
from unittest.mock import patch
import pyodbc
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from tests.helpers.sql.cleanup_support import (
    _CreationCursor as _cleanup_support__CreationCursor,
    _WriterCursor as _cleanup_support__WriterCursor,
    _WriterLease as _cleanup_support__WriterLease,
    _WriterManager as _cleanup_support__WriterManager,
    _canonical_writer_permission_snapshot as _cleanup_support__canonical_writer_permission_snapshot,
)
from types import SimpleNamespace
from contextlib import contextmanager
from ost_visualizer.application.dtos.condition_takeoff_reassignment import (
    ConditionTakeoffReassignment,
)
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    ConcurrencyToken,
    DatabaseMutationResult,
    ExpectedResourceVersion,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    MissingBidOwnedUidError,
)
import tests.application.services.test_project_write_service as parity
from tests.helpers.mdb.operations import (
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class MdbWriterPersistenceTests(unittest.TestCase):
    def test_access_plan_item_preflight_uses_access_dml_and_validates_bid_scope(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, ?, ?)",
            ((10, 1, None), (11, 1, 10), (20, 2, None)),
        )
        conn.execute("CREATE TABLE BidAnnotationRects (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidAnnotationRects VALUES (30, 1)")
        statements = []
        conn.set_trace_callback(statements.append)
        ops = _SqliteDuplicateOps(conn)
        MdbWriter.verify_plan_items_exist(
            ops,
            "large.mdb",
            "1",
            ("10", "11"),
            (("30", "rect"),),
        )
        emitted_sql = "\n".join(statements).upper()
        self.assertIn("BIDTAKEOFFS", emitted_sql)
        self.assertIn("BIDANNOTATIONRECTS", emitted_sql)
        self.assertNotIn("OPENJSON", emitted_sql)
        self.assertNotIn("SET NOCOUNT", emitted_sql)
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "does not belong to Bids.UID=1"
        ):
            MdbWriter.verify_plan_items_exist(
                ops,
                "large.mdb",
                "1",
                ("20",),
                (),
            )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "BidAnnotationRects has no row for UID 31"
        ):
            MdbWriter.verify_plan_items_exist(
                ops, "large.mdb", "1", (), (("31", "rect"),)
            )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "annotation changed or was deleted"
        ):
            MdbWriter.verify_plan_items_exist(
                ops, "large.mdb", "1", (), (("30", "not-an-annotation-type"),)
            )


class MdbWriterSqlCleanupTests(unittest.TestCase):
    def test_access_preconnection_validation_retains_established_false_result(self):
        writer = MdbWriter()
        with patch.object(
            writer,
            "_connection",
            side_effect=AssertionError("invalid UIDs must not open a connection"),
        ) as connection:
            self.assertIs(writer.delete_takeoffs("example.mdb", ["not-a-uid"]), False)
            self.assertIs(
                writer.save_takeoffs_area("example.mdb", ["10"], "bad"), False
            )
            self.assertIs(
                writer.save_takeoffs_condition("example.mdb", ["10"], "bad"), False
            )
            self.assertIs(
                writer.save_takeoffs_area("example.mdb", ["not-a-uid"], "20"), False
            )
            self.assertIs(writer.delete_takeoffs("example.mdb", []), True)
        connection.assert_not_called()

    def test_access_annotation_row_error_rolls_back_the_batch(self):
        writer = MdbWriter(conn_manager=_cleanup_support__WriterManager())
        spec = InsertAnnotationSpec(
            page_uid="10",
            annotation_type="rect",
            position=[1.0, 2.0, 3.0, 4.0],
            color="#ff0000",
            width=1.0,
        )
        with (
            patch(
                "ost_visualizer.infrastructure.mdb.components."
                "annotation_operations.require_existing_bid_scoped_uid_matches"
            ),
            patch.object(writer, "_next_uid", return_value=1),
            patch.object(
                writer,
                "_execute_annotation_insert",
                side_effect=RuntimeError("access row failure"),
            ) as insert,
        ):
            result = writer.insert_annotations("example.mdb", "1", [spec])
        self.assertEqual(result, [])
        insert.assert_called_once()
        self.assertEqual(insert.call_args.args[3:7], ("rect", 1, 1, 10))
        self.assertEqual(writer._conn_manager.lease.commits, 0)
        self.assertEqual(writer._conn_manager.lease.rollbacks, 1)

    def test_access_unsupported_annotation_type_rolls_back_without_inserting(self):
        writer = MdbWriter(conn_manager=_cleanup_support__WriterManager())
        spec = InsertAnnotationSpec(
            page_uid="10",
            annotation_type="not-an-annotation-type",
            position=[1.0, 2.0, 3.0, 4.0],
            color="#ff0000",
            width=1.0,
        )
        with patch.object(writer, "_execute_annotation_insert") as insert:
            result = writer.insert_annotations("example.mdb", "1", [spec])
        self.assertEqual(result, [])
        insert.assert_not_called()
        self.assertEqual(writer._conn_manager.lease.commits, 0)
        self.assertEqual(writer._conn_manager.lease.rollbacks, 1)

    def test_access_takeoff_write_retains_resource_limit_retry(self):
        writer = MdbWriter()
        with patch.object(
            writer,
            "_run_selected_takeoffs_value_update",
            side_effect=[
                pyodbc.Error("HY001", "System resource exceeded"),
                None,
            ],
        ) as update:
            result = writer.save_takeoffs_area("example.mdb", ["10"], "20")
        self.assertIs(result, True)
        self.assertEqual(
            [call.args for call in update.call_args_list],
            [
                ("example.mdb", [10], "BidAreaUID", 20, 50),
                ("example.mdb", [10], "BidAreaUID", 20, 1),
            ],
        )

    def test_access_takeoff_write_does_not_retry_other_errors_and_reports_failed_retry(
        self,
    ):
        writer = MdbWriter()
        with patch.object(
            writer,
            "_run_selected_takeoffs_value_update",
            side_effect=pyodbc.Error("42000", "syntax error"),
        ) as update:
            self.assertIs(writer.save_takeoffs_area("example.mdb", ["10"], "20"), False)
        self.assertEqual(update.call_count, 1)
        with patch.object(
            writer,
            "_run_selected_takeoffs_value_update",
            side_effect=[
                pyodbc.Error("HY001", "System resource exceeded"),
                pyodbc.Error("HY001", "System resource exceeded"),
            ],
        ) as update:
            self.assertIs(writer.save_takeoffs_area("example.mdb", ["10"], "20"), False)
        self.assertEqual(update.call_count, 2)


class MdbWriterTransactionTests(unittest.TestCase):
    class Connection:
        def __init__(self, events, rollback_error=None):
            self.events = events
            self.rollback_error = rollback_error

        def commit(self):
            self.events.append("commit")

        def rollback(self):
            self.events.append("rollback")
            if self.rollback_error is not None:
                raise self.rollback_error

    class Manager:
        def __init__(self, events, rollback_error=None):
            self.events = events
            self.rollback_error = rollback_error

        @contextmanager
        def connection(self, db_path, autocommit=True):
            self.events.append(("open", db_path, autocommit))
            yield MdbWriterTransactionTests.Connection(self.events, self.rollback_error)
            self.events.append("close")

        def use_committed_writer_for_reads(self, db_path):
            self.events.append(("reads", db_path))

    def writer(self, rollback_error=None):
        events = []
        return MdbWriter(conn_manager=self.Manager(events, rollback_error)), events

    def test_an_outermost_transaction_commits_once_then_switches_reads_to_the_writer(
        self,
    ):
        writer, events = self.writer()
        with writer._connection("a.mdb") as connection:
            self.assertEqual(writer._access_transaction_depth.get(), 1)
            events.append("work")
        self.assertEqual(
            events,
            [("open", "a.mdb", False), "work", "commit", "close", ("reads", "a.mdb")],
        )
        self.assertEqual(writer._access_transaction_depth.get(), 0)
        self.assertIsNone(writer._access_transaction_error.get())

    def test_nested_connections_neither_commit_nor_roll_back_on_their_own(self):
        writer, events = self.writer()
        with writer._connection("a.mdb"):
            with writer._connection("a.mdb"):
                self.assertEqual(writer._access_transaction_depth.get(), 2)
                events.append("inner work")
            self.assertEqual(writer._access_transaction_depth.get(), 1)
            events.append("outer work")
        self.assertEqual(events.count("commit"), 1)
        self.assertEqual(events.count("rollback"), 0)
        self.assertEqual(events.count(("reads", "a.mdb")), 1)
        self.assertLess(events.index("outer work"), events.index("commit"))
        self.assertEqual(writer._access_transaction_depth.get(), 0)

    def test_a_failure_the_caller_swallowed_still_rolls_the_whole_transaction_back(
        self,
    ):
        writer, events = self.writer()
        with self.assertRaisesRegex(ValueError, "inner failed"):
            with writer._connection("a.mdb"):
                try:
                    with writer._connection("a.mdb"):
                        raise ValueError("inner failed")
                except ValueError:
                    events.append("swallowed")
        self.assertIn("swallowed", events)
        self.assertEqual(events.count("rollback"), 1)
        self.assertNotIn("commit", events)
        self.assertNotIn(("reads", "a.mdb"), events)
        self.assertEqual(writer._access_transaction_depth.get(), 0)
        self.assertIsNone(writer._access_transaction_error.get())

    def test_the_first_swallowed_failure_is_the_one_reported(self):
        writer, events = self.writer()
        failures = {message: ValueError(message) for message in ("first", "second")}
        with self.assertRaises(ValueError) as raised:
            with writer._connection("a.mdb"):
                for failure in failures.values():
                    try:
                        with writer._connection("a.mdb"):
                            raise failure
                    except ValueError:
                        pass
        self.assertIs(raised.exception, failures["first"])
        self.assertEqual(events.count("rollback"), 1)
        self.assertNotIn("commit", events)

    def test_a_failure_in_the_outermost_block_rolls_back_and_is_not_masked(self):
        writer, events = self.writer()
        with self.assertRaisesRegex(KeyError, "boom"):
            with writer._connection("a.mdb"):
                raise KeyError("boom")
        self.assertEqual(events.count("rollback"), 1)
        self.assertNotIn("commit", events)
        self.assertNotIn(("reads", "a.mdb"), events)

    def test_a_transaction_after_a_failed_one_starts_clean_and_commits(self):
        writer, events = self.writer()
        with self.assertRaises(ValueError):
            with writer._connection("a.mdb"):
                try:
                    with writer._connection("a.mdb"):
                        raise ValueError("first transaction")
                except ValueError:
                    pass
        events.clear()
        with writer._connection("a.mdb"):
            events.append("second transaction")
        self.assertEqual(events.count("commit"), 1)
        self.assertEqual(events.count("rollback"), 0)

    def test_an_error_recorded_outside_a_transaction_does_not_leak_into_the_next_one(
        self,
    ):
        writer, events = self.writer()
        writer._access_transaction_error.set(RuntimeError("stale"))
        self.addCleanup(writer._access_transaction_error.set, None)
        with writer._connection("a.mdb"):
            events.append("work")
        self.assertEqual(events.count("commit"), 1)

    def test_a_rollback_failure_is_reported_with_the_original_failure_as_its_cause(
        self,
    ):
        rollback_error = pyodbc.Error("rollback refused")
        writer, events = self.writer(rollback_error)
        with self.assertRaises(pyodbc.Error) as raised:
            with writer._connection("a.mdb"):
                raise ValueError("original")
        self.assertIs(raised.exception, rollback_error)
        self.assertIsInstance(raised.exception.__cause__, ValueError)
        self.assertEqual(
            raised.exception.__notes__,
            ["The MDB transaction could not be rolled back after ValueError: original"],
        )
        self.assertNotIn(("reads", "a.mdb"), events)

    def test_only_database_errors_inside_a_transaction_count_as_caught_mutation_errors(
        self,
    ):
        writer, _events = self.writer()
        database_error = pyodbc.Error("x")
        self.assertFalse(writer._record_caught_mutation_error(database_error))
        with writer._connection("a.mdb"):
            self.assertTrue(writer._record_caught_mutation_error(database_error))
            self.assertFalse(writer._record_caught_mutation_error(ValueError("x")))
        self.assertFalse(writer._record_caught_mutation_error(database_error))

    def test_schema_inspectors_are_built_for_the_connection_and_logger(self):
        logger = logging.getLogger("writer-test")
        writer = MdbWriter(conn_manager=self.Manager([]), logger=logger)
        connection = object()
        schema = writer._schema(connection)
        self.assertEqual(type(schema).__name__, "MdbSchemaInspector")
        self.assertIs(schema.connection, connection)
        self.assertIs(schema.logger, logger)


class MdbWriterPlanPreflightTests(unittest.TestCase):
    class StrictOps(_SqliteDuplicateOps):
        _require_write_columns = MdbWriter._require_write_columns

    def ops(self, script):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript(script)
        return self.StrictOps(connection)

    def verify(self, ops, takeoffs=(), annotations=(), bid="1", ownership=()):
        MdbWriter.verify_plan_items_exist(
            ops, "x.mdb", bid, takeoffs, annotations, takeoff_ownership=ownership
        )

    def test_the_bid_itself_must_still_exist(self):
        ops = self.ops("CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);")
        self.verify(ops)
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "Bids has no row for UID 99"
        ):
            self.verify(ops, bid="99")

    def test_takeoffs_need_a_bid_column_to_be_scoped(self):
        ops = self.ops(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidTakeoffs (UID INTEGER); INSERT INTO BidTakeoffs VALUES (10);"
        )
        with self.assertRaisesRegex(RuntimeError, "Missing BidTakeoffs.BidUID"):
            self.verify(ops, takeoffs=("10",))

    def test_the_takeoff_ownership_snapshot_must_still_match_the_stored_rows(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanTakeoffOwnership,
        )

        ops = self.ops(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER,"
            " BidConditionUID INTEGER, BidAreaUID INTEGER, ParentUID INTEGER);"
            "INSERT INTO BidTakeoffs VALUES (10, 1, 5, 6, 7, NULL);"
        )
        self.verify(
            ops,
            takeoffs=("10",),
            ownership=(PlanTakeoffOwnership("10", "5", "6", "7", "0"),),
        )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "takeoff ownership changed"
        ):
            self.verify(
                ops,
                takeoffs=("10",),
                ownership=(PlanTakeoffOwnership("10", "5", "6", "8", "0"),),
            )

    def test_an_annotation_whose_table_is_gone_is_reported_as_changed(self):
        ops = self.ops("CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);")
        with self.assertRaises(MissingBidOwnedUidError) as raised:
            self.verify(ops, annotations=(("30", "rect"),))
        self.assertEqual(
            str(raised.exception),
            "An annotation changed or was deleted before the Plan mutation started.",
        )

    def test_annotation_tables_need_a_bid_column_to_be_scoped(self):
        ops = self.ops(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidAnnotationRects (UID INTEGER); INSERT INTO BidAnnotationRects VALUES (30);"
        )
        with self.assertRaisesRegex(
            RuntimeError, r"^Missing BidAnnotationRects\.BidUID$"
        ):
            self.verify(ops, annotations=(("30", "rect"),))


class PageScaleTransactionTests(unittest.TestCase):
    def _rescale(self, legend_value):
        from contextlib import contextmanager
        from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter

        class Schema:
            def optional_table_missing(self, table):
                return table not in ("BidTakeoffs", "BidLegends")

            def column_exists(self, table, column):
                return column in ("UID", "BidPageUID", "Position")

        class Connection:
            def __init__(self):
                self.pending = []
                self.committed = []
                self.attempted = 0
                self.rollbacks = 0
                self.table = ""

            def execute(self, query, *params):
                if query.startswith("SELECT UID"):
                    self.table = (
                        "BidLegends" if "BidLegends" in query else "BidTakeoffs"
                    )
                elif query.startswith("UPDATE"):
                    self.pending.append(params)
                    self.attempted += 1

            def fetchone(self):
                return (1.0, 128.0)

            def fetchall(self):
                value = legend_value if self.table == "BidLegends" else b"1;2\n"
                return [SimpleNamespace(UID=7, Position=value)]

            def commit(self):
                self.committed.extend(self.pending)
                self.pending.clear()

            def rollback(self):
                self.rollbacks += 1
                self.pending.clear()

        connection = Connection()

        class Manager:
            @contextmanager
            def connection(self, path, *, autocommit):
                yield connection

            @staticmethod
            def use_committed_writer_for_reads(_path):
                pass

        writer = MdbWriter(conn_manager=Manager())
        error = None
        try:
            with writer._connection("fixture.mdb") as conn:
                writer._rescale_page_content_for_scale_change(
                    conn, Schema(), 3, 1, 256, rescale_overlay=False
                )
        except Exception as exc:
            error = exc
        return connection, error

    def test_malformed_legend_rolls_back_earlier_geometry_updates(self):
        from xml.etree.ElementTree import ParseError

        connection, error = self._rescale(b"<Legends")
        self.assertIsInstance(error, ParseError)
        self.assertEqual(connection.attempted, 1)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.pending, [])
        self.assertEqual(connection.committed, [])

    def test_page_scale_rescale_commits_geometry_and_legend_together(self):
        connection, error = self._rescale(
            b'<Legends dX="10" dY="20"><Legend dX="1"/></Legends>'
        )
        self.assertIsNone(error)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(connection.pending, [])
        self.assertEqual(len(connection.committed), 2)
        position, takeoff_uid = connection.committed[0]
        self.assertEqual(takeoff_uid, 7)
        self.assertEqual(bytes(position).decode("utf-8").strip(), "2;4")
        legend, legend_uid = connection.committed[1]
        self.assertEqual(legend_uid, 7)
        self.assertEqual(
            bytes(legend).decode("utf-8"),
            '<Legends dX="20" dY="40"><Legend dX="2" /></Legends>',
        )


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

    def test_old_selection_only_preflight_reproduces_exact_error_before_writes(self):
        before = self.snapshot()
        with self.assertRaises(MissingBidOwnedUidError) as raised:
            MdbWriter.verify_plan_items_exist(
                self.ops, "database.mdb", "7", ("10", "11", "12"), ()
            )
        self.assertEqual(
            str(raised.exception),
            "The takeoff relationship graph changed before the Plan mutation started.",
        )
        self.assertEqual(self.snapshot(), before)

    def test_preflight_accepts_selection_that_includes_the_child_takeoff(self):
        before = self.snapshot()
        MdbWriter.verify_plan_items_exist(
            self.ops, "database.mdb", "7", ("10", "11", "12", "13"), ()
        )
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


class _TxCursor(_SqliteCursorWrapper):
    """sqlite cursor that accepts pyodbc's single-list parameter form."""

    def __init__(self, connection, statements):
        super().__init__(connection)
        self._statements = statements

    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        self._statements.append((query, params))
        return super().execute(query, *params)


class _TxConnection:
    def __init__(
        self, database, statements, events, commit_error=None, rollback_error=None
    ):
        self._database = database
        self._statements = statements
        self._events = events
        self._commit_error = commit_error
        self._rollback_error = rollback_error

    def cursor(self):
        return _TxCursor(self._database, self._statements)

    def commit(self):
        self._events.append("commit")
        if self._commit_error is not None:
            raise self._commit_error
        self._database.commit()

    def rollback(self):
        self._events.append("rollback")
        if self._rollback_error is not None:
            raise self._rollback_error
        self._database.rollback()


class _SqliteWriteSchema(_SqliteSchema):
    """sqlite schema with the require_table/skip-report surface of the real one."""

    def __init__(self, connection):
        super().__init__(connection)
        self.skips = []

    def require_table(self, table):
        if self.optional_table_missing(table):
            raise RuntimeError(f"Missing table {table}")

    def log_optional_write_skip(self, table, column, operation):
        self.skips.append((table, column, operation))


class _SqliteWriteManager:
    def __init__(self, database, commit_error=None, rollback_error=None):
        self.database = database
        self.statements = []
        self.events = []
        self.commit_error = commit_error
        self.rollback_error = rollback_error

    @contextmanager
    def connection(self, db_path, autocommit=True):
        self.events.append(("open", db_path, autocommit))
        try:
            yield _TxConnection(
                self.database,
                self.statements,
                self.events,
                self.commit_error,
                self.rollback_error,
            )
        finally:
            self.events.append("close")

    def use_committed_writer_for_reads(self, db_path):
        self.events.append(("reads", db_path))


class _SqliteWriterCase(unittest.TestCase):
    """Runs the production MdbWriter against a real sqlite database."""

    def writer_for(self, *ddl, commit_error=None, rollback_error=None, path=":memory:"):
        database = sqlite3.connect(path)
        self.addCleanup(database.close)
        for statement in ddl:
            database.execute(statement)
        database.commit()
        manager = _SqliteWriteManager(database, commit_error, rollback_error)
        writer = MdbWriter(conn_manager=manager)
        schema = _SqliteWriteSchema(database)
        writer._schema = lambda _connection: schema
        return writer, database, manager, schema


class MdbWriterSqliteTransactionTests(_SqliteWriterCase):
    DDL = "CREATE TABLE Items (UID INTEGER PRIMARY KEY, Name TEXT)"

    def insert(self, connection, uid, name):
        connection.cursor().execute("INSERT INTO Items VALUES (?, ?)", uid, name)

    def rows(self, database):
        return database.execute("SELECT UID, Name FROM Items ORDER BY UID").fetchall()

    def test_a_committed_transaction_is_visible_to_an_independent_connection(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "tx.sqlite")
        writer, database, manager, _schema = self.writer_for(self.DDL, path=path)
        with writer._connection("x.mdb") as connection:
            self.insert(connection, 1, "one")
            self.insert(connection, 2, "two")
        other = sqlite3.connect(path)
        self.addCleanup(other.close)
        self.assertEqual(self.rows(other), [(1, "one"), (2, "two")])
        self.assertEqual(manager.events[-2:], ["close", ("reads", "x.mdb")])

    def test_a_failure_after_writes_leaves_the_database_unchanged(self):
        writer, database, manager, _schema = self.writer_for(self.DDL)
        database.execute("INSERT INTO Items VALUES (1, 'kept')")
        database.commit()
        with self.assertRaisesRegex(ValueError, "mid-batch"):
            with writer._connection("x.mdb") as connection:
                self.insert(connection, 2, "lost")
                self.insert(connection, 3, "lost too")
                raise ValueError("mid-batch")
        self.assertEqual(self.rows(database), [(1, "kept")])
        self.assertNotIn(("reads", "x.mdb"), manager.events)
        self.assertNotIn("commit", manager.events)

    def test_a_swallowed_database_error_in_a_nested_block_discards_every_write(self):
        writer, database, manager, _schema = self.writer_for(self.DDL)
        failure = pyodbc.Error("23000", "duplicate key")
        with self.assertRaises(pyodbc.Error) as raised:
            with writer._connection("x.mdb") as connection:
                self.insert(connection, 1, "outer write")
                try:
                    with writer._connection("x.mdb"):
                        self.insert(connection, 2, "inner write")
                        raise failure
                except pyodbc.Error:
                    pass
                self.insert(connection, 3, "after the swallowed error")
        self.assertIs(raised.exception, failure)
        self.assertEqual(self.rows(database), [])
        self.assertEqual(manager.events.count("rollback"), 1)
        self.assertEqual(manager.events.count("commit"), 0)

    def test_a_failing_commit_rolls_back_and_never_switches_reads(self):
        commit_error = pyodbc.Error("40001", "commit failed")
        writer, database, manager, _schema = self.writer_for(
            self.DDL, commit_error=commit_error
        )
        with self.assertRaises(pyodbc.Error) as raised:
            with writer._connection("x.mdb") as connection:
                self.insert(connection, 1, "never committed")
        self.assertIs(raised.exception, commit_error)
        self.assertEqual(self.rows(database), [])
        self.assertEqual(manager.events.count("commit"), 1)
        self.assertEqual(manager.events.count("rollback"), 1)
        self.assertNotIn(("reads", "x.mdb"), manager.events)
        self.assertEqual(writer._access_transaction_depth.get(), 0)

    def test_an_interrupt_neither_commits_nor_switches_reads_and_resets_the_depth(
        self,
    ):
        writer, database, manager, _schema = self.writer_for(self.DDL)
        with self.assertRaises(KeyboardInterrupt):
            with writer._connection("x.mdb") as connection:
                self.insert(connection, 1, "interrupted")
                raise KeyboardInterrupt()
        self.assertNotIn("commit", manager.events)
        self.assertNotIn(("reads", "x.mdb"), manager.events)
        self.assertEqual(manager.events[-1], "close")
        self.assertEqual(writer._access_transaction_depth.get(), 0)
        self.assertIsNone(writer._access_transaction_error.get())
        database.rollback()
        self.assertEqual(self.rows(database), [])

    def test_a_non_database_rollback_error_replaces_the_failure_but_resets_state(self):
        writer, database, manager, _schema = self.writer_for(
            self.DDL, rollback_error=RuntimeError("rollback broke")
        )
        with self.assertRaisesRegex(RuntimeError, "rollback broke") as raised:
            with writer._connection("x.mdb"):
                raise ValueError("original")
        self.assertIsInstance(raised.exception.__context__, ValueError)
        self.assertEqual(writer._access_transaction_depth.get(), 0)
        self.assertIsNone(writer._access_transaction_error.get())
        self.assertNotIn(("reads", "x.mdb"), manager.events)

    def test_each_thread_has_its_own_transaction_state(self):
        writer, database, manager, _schema = self.writer_for(self.DDL)
        seen = []

        def other_thread():
            seen.append(writer._access_transaction_depth.get())
            seen.append(writer._access_transaction_error.get())

        with writer._connection("x.mdb"):
            writer._access_transaction_error.set(RuntimeError("only this thread"))
            worker = threading.Thread(target=other_thread)
            worker.start()
            worker.join()
            writer._access_transaction_error.set(None)
        self.assertEqual(seen, [0, None])

    def test_a_nested_database_error_is_recorded_for_the_outer_commit_decision(self):
        writer, _database, _manager, _schema = self.writer_for(self.DDL)
        failure = pyodbc.Error("HY000", "nested")
        with self.assertRaises(pyodbc.Error):
            with writer._connection("x.mdb"):
                with self.assertRaises(pyodbc.Error):
                    with writer._connection("x.mdb"):
                        raise failure
                self.assertIs(writer._access_transaction_error.get(), failure)


class MdbWriterReassignmentPreflightTests(_SqliteWriterCase):
    DDL = (
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        "INSERT INTO Bids VALUES (2)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES (5, 1)",
        "INSERT INTO BidPages VALUES (6, 1)",
        "INSERT INTO BidPages VALUES (50, 2)",
        "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidConditions VALUES (7, 1)",
        "INSERT INTO BidConditions VALUES (8, 1)",
        "INSERT INTO BidConditions VALUES (70, 2)",
        "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, "
        "BidPageUID INTEGER, BidConditionUID INTEGER)",
        "INSERT INTO BidTakeoffs VALUES (10, 1, 5, 7)",
        "INSERT INTO BidTakeoffs VALUES (11, 1, 5, 7)",
        "INSERT INTO BidTakeoffs VALUES (12, 1, 6, 7)",
        "INSERT INTO BidTakeoffs VALUES (13, 1, 5, 8)",
        "INSERT INTO BidTakeoffs VALUES (20, 2, 5, 7)",
    )

    def verify(self, *, condition="7", page="5", takeoffs=("10", "11"), ddl=None):
        writer, database, manager, _schema = self.writer_for(*(ddl or self.DDL))
        before = database.execute("SELECT * FROM BidTakeoffs ORDER BY rowid").fetchall()
        writer.verify_takeoff_reassignment(
            "x.mdb", "1", ConditionTakeoffReassignment(condition, page, takeoffs)
        )
        self.assertEqual(
            database.execute("SELECT * FROM BidTakeoffs ORDER BY rowid").fetchall(),
            before,
        )
        return manager

    def test_a_matching_snapshot_passes_inside_one_committed_read_transaction(self):
        manager = self.verify()
        self.assertEqual(
            manager.events,
            [("open", "x.mdb", False), "commit", "close", ("reads", "x.mdb")],
        )

    def test_a_page_or_condition_of_another_bid_is_rejected_by_name(self):
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            r"^BidPages\.UID=50 does not belong to Bids\.UID=1\.$",
        ):
            self.verify(page="50", takeoffs=("20",))
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            r"^BidConditions\.UID=70 does not belong to Bids\.UID=1\.$",
        ):
            self.verify(condition="70")
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, r"^BidPages has no row for UID 999;"
        ):
            self.verify(page="999")
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, r"^BidConditions has no row for UID 999;"
        ):
            self.verify(condition="999")

    def test_a_takeoff_moved_to_another_page_or_condition_is_reported(self):
        message = "A Takeoff changed Page or Condition before reassignment started."
        with self.assertRaises(MissingBidOwnedUidError) as moved_page:
            self.verify(takeoffs=("10", "12"))
        self.assertEqual(str(moved_page.exception), message)
        with self.assertRaises(MissingBidOwnedUidError) as moved_condition:
            self.verify(takeoffs=("10", "13"))
        self.assertEqual(str(moved_condition.exception), message)

    def test_a_deleted_or_foreign_takeoff_is_reported_as_deleted_or_replaced(self):
        message = "A Takeoff was deleted or replaced before reassignment started."
        with self.assertRaises(MissingBidOwnedUidError) as deleted:
            self.verify(takeoffs=("10", "99"))
        self.assertEqual(str(deleted.exception), message)
        with self.assertRaises(MissingBidOwnedUidError) as foreign:
            self.verify(takeoffs=("10", "20"))
        self.assertEqual(str(foreign.exception), message)

    def test_a_failed_preflight_rolls_back_without_switching_reads(self):
        writer, _database, manager, _schema = self.writer_for(*self.DDL)
        with self.assertRaises(MissingBidOwnedUidError):
            writer.verify_takeoff_reassignment(
                "x.mdb", "1", ConditionTakeoffReassignment("7", "5", ("10", "99"))
            )
        self.assertEqual(
            manager.events, [("open", "x.mdb", False), "rollback", "close"]
        )

    def test_each_required_takeoff_column_is_checked(self):
        for column in ("UID", "BidUID", "BidPageUID", "BidConditionUID"):
            with self.subTest(column=column):
                columns = [
                    name
                    for name in ("UID", "BidUID", "BidPageUID", "BidConditionUID")
                    if name != column
                ]
                ddl = [
                    statement
                    for statement in self.DDL
                    if "BidTakeoffs" not in statement
                ] + [f"CREATE TABLE BidTakeoffs ({', '.join(columns)})"]
                with self.assertRaisesRegex(
                    RuntimeError, rf"^Missing BidTakeoffs\.{column}$"
                ):
                    self.verify(ddl=ddl)

    def test_takeoffs_beyond_one_query_chunk_are_all_verified_in_bounded_queries(self):
        rows = [
            f"INSERT INTO BidTakeoffs VALUES ({uid}, 1, 5, 7)"
            for uid in range(100, 220)
        ]
        ddl = list(self.DDL) + rows
        uids = tuple(str(uid) for uid in range(100, 220))
        writer, database, manager, _schema = self.writer_for(*ddl)
        writer.verify_takeoff_reassignment(
            "x.mdb", "1", ConditionTakeoffReassignment("7", "5", uids)
        )
        takeoff_selects = [
            params
            for sql, params in manager.statements
            if sql.startswith("SELECT [UID], [BidPageUID]")
        ]
        self.assertEqual([len(params) for params in takeoff_selects], [51, 51, 21])
        self.assertEqual([params[0] for params in takeoff_selects], [1, 1, 1])
        self.assertEqual(
            [uid for params in takeoff_selects for uid in params[1:]],
            list(range(100, 220)),
        )
        database.execute("DELETE FROM BidTakeoffs WHERE UID = 219")
        with self.assertRaisesRegex(MissingBidOwnedUidError, "deleted or replaced"):
            writer.verify_takeoff_reassignment(
                "x.mdb", "1", ConditionTakeoffReassignment("7", "5", uids)
            )
        database.execute("UPDATE BidTakeoffs SET BidPageUID = 6 WHERE UID = 150")
        database.execute("INSERT INTO BidTakeoffs VALUES (219, 1, 5, 7)")
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "changed Page or Condition"
        ):
            writer.verify_takeoff_reassignment(
                "x.mdb", "1", ConditionTakeoffReassignment("7", "5", uids)
            )


class MdbWriterWriteContractTests(_SqliteWriterCase):
    DDL = "CREATE TABLE Items (UID INTEGER, BidUID INTEGER, Name TEXT, Extra TEXT)"

    def test_inserts_keep_only_existing_columns_and_report_each_skipped_one(self):
        writer, database, manager, schema = self.writer_for(self.DDL)
        statements = []
        cursor = _TxCursor(database, statements)
        result = writer._execute_insert_values(
            cursor,
            schema,
            "Items",
            {"UID": 4, "BidUID": 1, "Name": "n", "Ghost": "x", "Phantom": "y"},
            ("UID", "BidUID"),
            "ghost insert",
        )
        self.assertIsNone(result)
        self.assertEqual(
            statements,
            [
                (
                    "INSERT INTO [Items] ([UID], [BidUID], [Name]) VALUES (?, ?, ?)",
                    (4, 1, "n"),
                )
            ],
        )
        self.assertEqual(
            schema.skips,
            [("Items", "Ghost", "ghost insert"), ("Items", "Phantom", "ghost insert")],
        )
        self.assertEqual(
            database.execute("SELECT UID, BidUID, Name, Extra FROM Items").fetchall(),
            [(4, 1, "n", None)],
        )

    def test_insert_needs_its_required_columns_in_the_schema_the_table_and_the_values(
        self,
    ):
        writer, database, _manager, schema = self.writer_for(self.DDL)
        cursor = _TxCursor(database, [])
        with self.assertRaisesRegex(RuntimeError, r"^Missing table Nope$"):
            writer._execute_insert_values(
                cursor, schema, "Nope", {"UID": 1}, ("UID",), "op"
            )
        with self.assertRaisesRegex(RuntimeError, r"^Missing Items\.Required$"):
            writer._execute_insert_values(
                cursor, schema, "Items", {"UID": 1}, ("UID", "Required"), "op"
            )
        with self.assertRaises(UnsupportedMdbSchemaError) as missing:
            writer._execute_insert_values(
                cursor,
                schema,
                "Items",
                {"UID": 1, "Name": "n"},
                ("UID", "BidUID", "Extra"),
                "add item",
            )
        self.assertEqual(
            str(missing.exception),
            "This OST database is missing required writable columns "
            "Items.BidUID, Extra for add item.",
        )
        with self.assertRaises(UnsupportedMdbSchemaError) as empty:
            writer._execute_insert_values(
                cursor, schema, "Items", {"Ghost": 1}, (), "add ghost"
            )
        self.assertEqual(
            str(empty.exception),
            "This OST database has no writable columns for add ghost.",
        )
        self.assertEqual(
            database.execute("SELECT COUNT(*) FROM Items").fetchone(), (0,)
        )

    def test_an_optional_value_for_a_missing_column_is_skipped_not_fatal(self):
        writer, database, _manager, schema = self.writer_for(self.DDL)
        filtered = writer._filter_existing_write_values(
            schema, "Items", {"UID": 1, "Ghost": 2, "Name": "n"}, ("UID",), "op"
        )
        self.assertEqual(filtered, {"UID": 1, "Name": "n"})
        self.assertEqual(schema.skips, [("Items", "Ghost", "op")])

    def test_a_required_column_that_vanishes_after_the_precheck_is_not_skipped(self):
        class FlappingSchema:
            def __init__(self):
                self.calls = []

            def require_table(self, table):
                self.calls.append(("table", table))

            def require_column(self, table, column):
                self.calls.append(("column", table, column))
                if len([c for c in self.calls if c == ("column", table, column)]) > 1:
                    raise RuntimeError(f"Missing {table}.{column}")

            def column_exists(self, table, column):
                return column != "UID"

            def log_optional_write_skip(self, table, column, operation):
                self.calls.append(("skip", table, column, operation))

        writer = MdbWriter(conn_manager=object())
        schema = FlappingSchema()
        with self.assertRaisesRegex(RuntimeError, r"^Missing Items\.UID$"):
            writer._filter_existing_write_values(
                schema, "Items", {"UID": 1}, ("UID",), "op"
            )
        self.assertEqual(
            schema.calls,
            [
                ("table", "Items"),
                ("column", "Items", "UID"),
                ("column", "Items", "UID"),
            ],
        )

    def test_updates_set_only_existing_columns_with_parameters_in_clause_order(self):
        writer, database, _manager, schema = self.writer_for(
            self.DDL,
            "INSERT INTO Items VALUES (1, 1, 'old', 'keep')",
            "INSERT INTO Items VALUES (2, 1, 'other', 'keep')",
        )
        statements = []
        cursor = _TxCursor(database, statements)
        changed = writer._execute_update_values(
            cursor,
            schema,
            "Items",
            {"Name": "new", "Extra": "set", "Ghost": "x"},
            ("UID",),
            "[UID]=? AND [BidUID]=?",
            [1, 1],
            "rename",
        )
        self.assertIs(changed, True)
        self.assertEqual(
            statements,
            [
                (
                    "UPDATE [Items] SET [Name]=?, [Extra]=? WHERE [UID]=? AND [BidUID]=?",
                    ("new", "set", 1, 1),
                )
            ],
        )
        self.assertEqual(schema.skips, [("Items", "Ghost", "rename")])
        self.assertEqual(
            database.execute(
                "SELECT UID, Name, Extra FROM Items ORDER BY UID"
            ).fetchall(),
            [(1, "new", "set"), (2, "other", "keep")],
        )

    def test_an_update_with_no_writable_column_is_refused_unless_empty_is_allowed(
        self,
    ):
        writer, database, _manager, schema = self.writer_for(
            self.DDL, "INSERT INTO Items VALUES (1, 1, 'old', 'keep')"
        )
        statements = []
        cursor = _TxCursor(database, statements)
        with self.assertRaises(UnsupportedMdbSchemaError) as refused:
            writer._execute_update_values(
                cursor, schema, "Items", {"Ghost": 1}, (), "[UID]=?", [1], "retag"
            )
        self.assertEqual(
            str(refused.exception),
            "This OST database has no writable columns for retag.",
        )
        refused_again = writer._execute_update_values(
            cursor,
            schema,
            "Items",
            {"Ghost": 1},
            (),
            "[UID]=?",
            [1],
            "retag",
            allow_empty=True,
        )
        self.assertIs(refused_again, False)
        self.assertEqual(statements, [])
        self.assertEqual(
            database.execute("SELECT Name FROM Items").fetchall(), [("old",)]
        )
