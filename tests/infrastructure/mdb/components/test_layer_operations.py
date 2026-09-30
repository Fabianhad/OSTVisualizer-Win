from tests.helpers.mdb.operations import (
    _ParameterLimitedSqliteConnectionWrapper,
    _ParameterLimitedSqliteCursorWrapper,
    _ParameterLimitedSqliteOps,
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
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
from collections import namedtuple
from contextlib import contextmanager


class _Cursor:
    def __init__(self):
        self.executions = []
        self._last_sql = ""
        self.forced_update_rowcount = None
        self.forced_preflight_uids = None
        self.forced_postupdate_uids = None

    def execute(self, sql, *parameters):
        self._last_sql = " ".join(sql.split())
        self.executions.append((self._last_sql, parameters))
        return self

    def fetchall(self):
        if "FROM [BidLayers]" in self._last_sql and "[Show] = ?" in self._last_sql:
            uids = self.forced_postupdate_uids
            if uids is None:
                uids = (10, 11)
            return [(uid,) for uid in uids]
        if self._last_sql.startswith("SELECT [UID] FROM [BidLayers]"):
            uids = self.forced_preflight_uids
            if uids is None:
                uids = (10, 11)
            return [(uid,) for uid in uids]
        if self._last_sql.startswith("SELECT [UID], [BidUID] FROM [BidLayers]"):
            return [(10, 7), (11, 7)]
        if self._last_sql.startswith("SELECT [UID] FROM [Bids]"):
            return [(7,)]
        row_type = namedtuple("LayerRow", ("UID", "Sequence"))
        return [
            row_type(10, 1),
            row_type(11, 2),
        ]

    @property
    def rowcount(self):
        if self.forced_update_rowcount is not None:
            return self.forced_update_rowcount
        return 2


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _Schema:
    def require_column(self, _table, _column):
        pass

    def column_exists(self, _table, column):
        return column in {"IsTemplate", "IsLocked"}


class _LayerOperations(LayerOperationsMixin):
    def __init__(self):
        self.cursor = _Cursor()

    @contextmanager
    def _connection(self, _db_path):
        yield _Connection(self.cursor)

    def _schema(self, _connection):
        return _Schema()

    def _require_write_columns(self, schema, table, columns):
        for column in columns:
            schema.require_column(table, column)


class LayerOperationsPersistenceTests(unittest.TestCase):
    def test_delete_layer_clears_indexed_annotation_shape_layer_refs(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidLayers (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                Sequence INTEGER,
                IsTemplate INTEGER,
                IsLocked INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidAnnotationRects (
                UID INTEGER PRIMARY KEY,
                BidLayerUID INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO BidLayers "
            "(UID, BidUID, Sequence, IsTemplate, IsLocked) VALUES (30, 1, 1, 0, 0)"
        )
        conn.execute(
            "INSERT INTO BidLayers "
            "(UID, BidUID, Sequence, IsTemplate, IsLocked) VALUES (31, 1, 2, 0, 0)"
        )
        conn.execute(
            "INSERT INTO BidAnnotationRects (UID, BidLayerUID) VALUES (20, 30)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "30"))
        self.assertIsNone(
            conn.execute(
                "SELECT BidLayerUID FROM BidAnnotationRects WHERE UID = 20"
            ).fetchone()[0]
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers").fetchone()[0], 1
        )

    def test_layer_insert_reserves_dangling_layer_reference_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER, "
            "Sequence INTEGER, IsTemplate INTEGER, IsLocked INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidComments "
            "(UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)"
        )
        conn.execute("INSERT INTO BidLayers VALUES (7, 1, 'Existing', -1, 1, 0, 0)")
        conn.execute("INSERT INTO BidComments VALUES (70, 1, 8)")
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_layer("malformed.mdb", "1", "New", 1),
            "9",
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidLayers ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidComments AS comment "
                "INNER JOIN BidLayers AS layer ON comment.BidLayerUID=layer.UID"
            ).fetchone()[0],
            0,
        )

    def test_layer_update_rejects_duplicate_physical_uid_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Show INTEGER)"
        )
        conn.executemany("INSERT INTO BidLayers VALUES (7, ?, ?)", ((1, 0), (2, -1)))
        with self.assertRaisesRegex(
            RuntimeError,
            "BidLayers contains duplicate UID 7",
        ):
            _SqliteMdbOps(conn).update_layer_show("malformed.mdb", "7", True)
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, Show FROM BidLayers ORDER BY rowid"
            ).fetchall(),
            [(1, 0), (2, -1)],
        )

    def test_bulk_layer_visibility_only_updates_captured_sidebar_layers(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", [(7,), (8,)])
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER, "
            "IsTemplate INTEGER, IsLocked INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, ?, ?, ?, ?, ?)",
            [
                (100, None, "Shared", -1, -1, -1),
                (101, 7, "Shared", -1, 0, 0),
                (102, 7, "Bid 7 only", -1, 0, 0),
            ],
        )
        ops = _SqliteDuplicateOps(conn)
        self.assertTrue(
            ops.update_all_layers_show("fixture.mdb", "7", False, ["101", "102"])
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(100, -1), (101, 0), (102, 0)],
        )

    def test_bulk_layer_visibility_rejects_ineligible_uid_before_any_write(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", [(7,), (8,)])
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER, "
            "IsTemplate INTEGER, IsLocked INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, ?, ?, ?, ?, ?)",
            [
                (101, 7, "Bid 7", -1, 0, 0),
                (201, 8, "Bid 8", -1, 0, 0),
            ],
        )
        ops = _SqliteDuplicateOps(conn)
        self.assertFalse(
            ops.update_all_layers_show("fixture.mdb", "7", False, ["101", "201"])
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(101, -1), (201, -1)],
        )

    def test_large_bulk_layer_visibility_stays_within_parameter_limits(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (7)")
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Show INTEGER, "
            "IsTemplate INTEGER, IsLocked INTEGER)"
        )
        layer_uids = list(range(1000, 1600))
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, 7, -1, 0, 0)",
            ((uid,) for uid in layer_uids),
        )
        self.assertTrue(
            _ParameterLimitedSqliteOps(conn, max_parameters=55).update_all_layers_show(
                "large.mdb", "7", False, [str(uid) for uid in layer_uids]
            )
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers WHERE Show = 0").fetchone()[0],
            len(layer_uids),
        )


class LayerOperationsTests(unittest.TestCase):
    def test_bulk_bid_layer_visibility_uses_one_set_based_update(self):
        operations = _LayerOperations()
        self.assertTrue(operations.update_all_layers_show("bid.mdb", "7", False))
        updates = [
            execution
            for execution in operations.cursor.executions
            if execution[0].startswith("UPDATE [BidLayers] SET [Show]")
        ]
        self.assertEqual(
            updates,
            [
                (
                    "UPDATE [BidLayers] SET [Show] = ? WHERE [BidUID] = ? OR "
                    "([IsTemplate] <> 0 AND [IsLocked] <> 0)",
                    (0, 7),
                )
            ],
        )

    def test_captured_bulk_layer_visibility_uses_one_exact_set_based_update(self):
        operations = _LayerOperations()
        self.assertTrue(
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])
        )
        updates = [
            execution
            for execution in operations.cursor.executions
            if execution[0].startswith("UPDATE [BidLayers] SET [Show]")
        ]
        self.assertEqual(
            updates,
            [
                (
                    "UPDATE [BidLayers] SET [Show] = ? "
                    "WHERE [UID] IN (?, ?) AND "
                    "([BidUID] = ? OR ([IsTemplate] <> 0 AND [IsLocked] <> 0))",
                    (0, 10, 11, 7),
                )
            ],
        )

    def test_captured_bulk_visibility_rejects_partial_affected_row_count(self):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = 1
        with self.assertRaisesRegex(
            RuntimeError,
            "bulk Layer visibility update affected 1 of 2 captured Layers",
        ):
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])

    def test_captured_bulk_visibility_accepts_sql_nocount_rowcount(self):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = -1
        self.assertTrue(
            operations.update_all_layers_show("sql-db", "7", False, ["10", "11"])
        )

    def test_captured_bulk_visibility_rejects_unverified_sql_nocount_update(self):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = -1
        operations.cursor.forced_postupdate_uids = (10,)
        with self.assertRaisesRegex(
            RuntimeError,
            "bulk Layer visibility update could verify only 1 of 2 captured Layers",
        ):
            operations.update_all_layers_show("sql-db", "7", False, ["10", "11"])

    def test_captured_bulk_visibility_rejects_duplicate_persisted_uid(self):
        operations = _LayerOperations()
        operations.cursor.forced_preflight_uids = (10, 10, 11)
        self.assertFalse(
            operations.update_all_layers_show("sql-db", "7", False, ["10", "11"])
        )
        self.assertFalse(
            any(
                sql.startswith("UPDATE [BidLayers] SET [Show]")
                for sql, _parameters in operations.cursor.executions
            )
        )

    def test_bid_layer_swap_updates_non_template_rows(self):
        operations = _LayerOperations()
        self.assertTrue(operations.swap_layer_sequence("bid.mdb", "10", "11"))
        updates = operations.cursor.executions[3:]
        self.assertEqual(
            updates,
            [
                (
                    "UPDATE [BidLayers] SET [Sequence] = ? WHERE [UID] = ?",
                    (2, 10),
                ),
                (
                    "UPDATE [BidLayers] SET [Sequence] = ? WHERE [UID] = ?",
                    (1, 11),
                ),
            ],
        )
