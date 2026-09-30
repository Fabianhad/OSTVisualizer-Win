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
        self.assertNotIn("OPENJSON", emitted_sql)
        self.assertNotIn("SET NOCOUNT", emitted_sql)
        with self.assertRaisesRegex(Exception, "does not belong to Bids.UID=1"):
            MdbWriter.verify_plan_items_exist(
                ops,
                "large.mdb",
                "1",
                ("20",),
                (),
            )


class MdbWriterSqlCleanupTests(unittest.TestCase):
    def test_access_preconnection_validation_retains_established_false_result(self):
        writer = MdbWriter()
        self.assertFalse(writer.delete_takeoffs("example.mdb", ["not-a-uid"]))

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
            ),
        ):
            result = writer.insert_annotations("example.mdb", "1", [spec])
        self.assertEqual(result, [])
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
        self.assertEqual(update.call_count, 2)


class PageScaleTransactionTests(unittest.TestCase):
    def test_malformed_legend_rolls_back_earlier_geometry_updates(self):
        from contextlib import contextmanager
        from xml.etree.ElementTree import ParseError
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
                value = b"<Legends" if self.table == "BidLegends" else b"1;2\n"
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

        writer = MdbWriter(conn_manager=Manager())
        with self.assertRaises(ParseError):
            with writer._connection("fixture.mdb") as conn:
                writer._rescale_page_content_for_scale_change(
                    conn, Schema(), 3, 1, 256, rescale_overlay=False
                )
        self.assertEqual(connection.attempted, 1)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.pending, [])
        self.assertEqual(connection.committed, [])


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
