from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    ACCESS_BULK_CHUNK_SIZE,
)
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
            self.assertFalse(writer.delete_takeoffs("example.mdb", ["not-a-uid"]))
            self.assertFalse(writer.save_takeoffs_area("example.mdb", ["10"], "bad"))
            self.assertFalse(
                writer.save_takeoffs_condition("example.mdb", ["10"], "bad")
            )
            self.assertFalse(
                writer.save_takeoffs_area("example.mdb", ["not-a-uid"], "20")
            )
            self.assertTrue(writer.delete_takeoffs("example.mdb", []))
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
        self.assertTrue(result)
        self.assertEqual(
            [call.args for call in update.call_args_list],
            [
                ("example.mdb", [10], "BidAreaUID", 20, ACCESS_BULK_CHUNK_SIZE),
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
            self.assertFalse(writer.save_takeoffs_area("example.mdb", ["10"], "20"))
        self.assertEqual(update.call_count, 1)
        with patch.object(
            writer,
            "_run_selected_takeoffs_value_update",
            side_effect=[
                pyodbc.Error("HY001", "System resource exceeded"),
                pyodbc.Error("HY001", "System resource exceeded"),
            ],
        ) as update:
            self.assertFalse(writer.save_takeoffs_area("example.mdb", ["10"], "20"))
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
        with self.assertRaisesRegex(ValueError, "first"):
            with writer._connection("a.mdb"):
                for message in ("first", "second"):
                    try:
                        with writer._connection("a.mdb"):
                            raise ValueError(message)
                    except ValueError:
                        pass
        self.assertEqual(events.count("rollback"), 1)

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
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "annotation changed or was deleted"
        ):
            self.verify(ops, annotations=(("30", "rect"),))

    def test_annotation_tables_need_a_bid_column_to_be_scoped(self):
        ops = self.ops(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidAnnotationRects (UID INTEGER); INSERT INTO BidAnnotationRects VALUES (30);"
        )
        with self.assertRaisesRegex(RuntimeError, "Missing BidAnnotationRects.BidUID"):
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
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            "relationship graph changed before the Plan mutation",
        ):
            MdbWriter.verify_plan_items_exist(
                self.ops, "database.mdb", "7", ("10", "11", "12"), ()
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
