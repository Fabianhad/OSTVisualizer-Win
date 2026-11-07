from ost_visualizer.infrastructure.database.bid_owned_identity import (
    BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE,
    IncoherentBidOwnedScopeError,
)
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
from ost_visualizer.infrastructure.mdb.components.constants import (
    LAYER_REFERENCE_TABLES,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
    _default_layer_update_matched,
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
from tests.helpers.mdb.real_write_contract import RealContractOps
import logging
from collections import namedtuple
from contextlib import contextmanager


class _StrictTestCase(unittest.TestCase):
    """Boolean results are exact: None or 0 must not pass for True/False."""

    def assertIsTrue(self, value, msg=None):
        self.assertIs(value, True, msg)

    def assertIsFalse(self, value, msg=None):
        self.assertIs(value, False, msg)


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


class LayerOperationsPersistenceTests(_StrictTestCase):
    def test_delete_layer_clears_indexed_annotation_shape_layer_refs(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("""
            CREATE TABLE BidLayers (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                Sequence INTEGER,
                IsTemplate INTEGER,
                IsLocked INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE BidAnnotationRects (
                UID INTEGER PRIMARY KEY,
                BidLayerUID INTEGER
            )
            """)
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
        self.assertIsTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "30"))
        self.assertIsNone(
            conn.execute(
                "SELECT BidLayerUID FROM BidAnnotationRects WHERE UID = 20"
            ).fetchone()[0]
        )
        self.assertEqual(
            conn.execute("SELECT UID, Sequence FROM BidLayers").fetchall(),
            [(31, 1)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationRects").fetchall(), [(20,)]
        )

    def test_delete_layer_refuses_template_and_locked_layers_without_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidLayers (UID INTEGER PRIMARY KEY, BidUID INTEGER, "
            "Sequence INTEGER, IsTemplate INTEGER, IsLocked INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidAnnotationRects (UID INTEGER PRIMARY KEY, "
            "BidLayerUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, 1, ?, ?, ?)",
            ((30, 1, -1, 0), (31, 2, 0, -1), (32, 3, 0, 0)),
        )
        conn.execute("INSERT INTO BidAnnotationRects VALUES (20, 30)")
        conn.execute("INSERT INTO BidAnnotationRects VALUES (21, 31)")
        ops = _SqliteMdbOps(conn)
        self.assertIsFalse(ops.delete_layer("bid.mdb", "30"))
        self.assertIsFalse(ops.delete_layer("bid.mdb", "31"))
        self.assertEqual(
            conn.execute("SELECT UID, Sequence FROM BidLayers ORDER BY UID").fetchall(),
            [(30, 1), (31, 2), (32, 3)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidLayerUID FROM BidAnnotationRects ORDER BY UID"
            ).fetchall(),
            [(20, 30), (21, 31)],
        )

    def test_layer_insert_reserves_dangling_layer_reference_uid_and_shifts_later_sequences(
        self,
    ):
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
        conn.execute("INSERT INTO BidLayers VALUES (6, 1, 'Below', -1, 2, 0, 0)")
        conn.execute("INSERT INTO BidComments VALUES (70, 1, 8)")
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_layer("malformed.mdb", "1", "New", 1),
            "9",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name, Show, Sequence, IsTemplate, IsLocked "
                "FROM BidLayers ORDER BY UID"
            ).fetchall(),
            [
                (6, 1, "Below", -1, 3, 0, 0),
                (7, 1, "Existing", -1, 1, 0, 0),
                (9, 1, "New", -1, 2, 0, 0),
            ],
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
        self.assertIsTrue(
            ops.update_all_layers_show("fixture.mdb", "7", False, ["101", "102"])
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(100, -1), (101, 0), (102, 0)],
        )

    def test_swap_layer_sequence_exchanges_sequences_and_rejects_cross_bid_pair(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", [(7,), (8,)])
        conn.execute(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Sequence INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, ?, ?)",
            [(10, 7, 1), (11, 7, 2), (12, 7, 3), (20, 8, 1)],
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsTrue(ops.swap_layer_sequence("bid.mdb", "10", "12"))
        self.assertEqual(
            conn.execute("SELECT UID, Sequence FROM BidLayers ORDER BY UID").fetchall(),
            [(10, 3), (11, 2), (12, 1), (20, 1)],
        )
        with self.assertRaises(IncoherentBidOwnedScopeError):
            ops.swap_layer_sequence("bid.mdb", "10", "20")
        self.assertEqual(
            conn.execute("SELECT UID, Sequence FROM BidLayers ORDER BY UID").fetchall(),
            [(10, 3), (11, 2), (12, 1), (20, 1)],
        )

    def test_bulk_layer_visibility_updates_captured_shared_layer_but_not_uncaptured_bid_layer(
        self,
    ):
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
                (101, 7, "Captured", -1, 0, 0),
                (102, 7, "Uncaptured", -1, 0, 0),
                (201, 8, "Other bid", -1, 0, 0),
            ],
        )
        self.assertIsTrue(
            _SqliteDuplicateOps(conn).update_all_layers_show(
                "fixture.mdb", "7", False, ["100", "101"]
            )
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(100, 0), (101, 0), (102, -1), (201, -1)],
        )

    def test_uncaptured_bulk_layer_visibility_updates_own_and_shared_layers_only(self):
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
                (101, 7, "Bid 7", -1, 0, 0),
                (201, 8, "Bid 8", -1, 0, 0),
                (202, 8, "Bid 8 template only", -1, -1, 0),
            ],
        )
        self.assertIsTrue(
            _SqliteDuplicateOps(conn).update_all_layers_show("fixture.mdb", "7", False)
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(100, 0), (101, 0), (201, -1), (202, -1)],
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
        self.assertIsFalse(
            ops.update_all_layers_show("fixture.mdb", "7", False, ["101", "201"])
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(101, -1), (201, -1)],
        )

    def test_bulk_layer_visibility_rejects_ineligible_uid_in_later_chunk_before_any_write(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", [(7,), (8,)])
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Show INTEGER, "
            "IsTemplate INTEGER, IsLocked INTEGER)"
        )
        own_uids = list(range(1000, 1000 + BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE + 5))
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, 7, -1, 0, 0)",
            ((uid,) for uid in own_uids),
        )
        conn.execute("INSERT INTO BidLayers VALUES (2000, 8, -1, 0, 0)")
        captured = [str(uid) for uid in own_uids] + ["2000"]
        self.assertIsFalse(
            _SqliteDuplicateOps(conn).update_all_layers_show(
                "fixture.mdb", "7", False, captured
            )
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers WHERE Show = 0").fetchone()[0],
            0,
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
        self.assertIsTrue(
            _ParameterLimitedSqliteOps(conn, max_parameters=55).update_all_layers_show(
                "large.mdb", "7", False, [str(uid) for uid in layer_uids]
            )
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers WHERE Show = 0").fetchone()[0],
            len(layer_uids),
        )


class LayerOperationsTests(_StrictTestCase):
    def test_bulk_bid_layer_visibility_uses_one_set_based_update(self):
        operations = _LayerOperations()
        self.assertIsTrue(operations.update_all_layers_show("bid.mdb", "7", False))
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
        self.assertIsTrue(
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
        self.assertIsTrue(
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
        self.assertIsFalse(
            operations.update_all_layers_show("sql-db", "7", False, ["10", "11"])
        )
        self.assertIsFalse(
            any(
                sql.startswith("UPDATE [BidLayers] SET [Show]")
                for sql, _parameters in operations.cursor.executions
            )
        )

    def test_bid_layer_swap_updates_non_template_rows(self):
        operations = _LayerOperations()
        self.assertIsTrue(operations.swap_layer_sequence("bid.mdb", "10", "11"))
        updates = [
            execution
            for execution in operations.cursor.executions
            if execution[0].startswith("UPDATE [BidLayers] SET [Sequence]")
        ]
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


_LAYER_COLUMNS = (
    "UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER, "
    "Sequence INTEGER, IsTemplate INTEGER, IsLocked INTEGER"
)


def _layer_db(layers, columns=_LAYER_COLUMNS, bids=(7, 8)):
    """sqlite stand-in: Bids plus BidLayers rows given as full tuples."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Bids (UID INTEGER)")
    conn.executemany("INSERT INTO Bids VALUES (?)", [(uid,) for uid in bids])
    conn.execute(f"CREATE TABLE BidLayers ({columns})")
    width = len(columns.split(","))
    conn.executemany(f"INSERT INTO BidLayers VALUES ({', '.join('?' * width)})", layers)
    return conn


def _layer_rows(conn, columns="UID, Show, Sequence, Name"):
    return conn.execute(f"SELECT {columns} FROM BidLayers ORDER BY UID").fetchall()


class _RaisingMutationErrorOps(_SqliteDuplicateOps):
    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


class _MatchCursor:
    """Cursor double for the SQL Server no-count fallback of default layers."""

    def __init__(self, rowcount, fetched):
        self.rowcount = rowcount
        self._fetched = fetched
        self.executions = []

    def execute(self, sql, *parameters):
        self.executions.append((" ".join(sql.split()), parameters))

    def fetchone(self):
        return self._fetched


class LayerShowAndNameSemanticsTests(_StrictTestCase):
    def test_bid_layer_show_writes_access_boolean_for_the_target_layer_only(self):
        conn = _layer_db(
            [
                (10, 7, "A", 0, 1, 0, 0),
                (11, 7, "B", 0, 2, 0, 0),
                (20, 8, "C", -1, 1, 0, 0),
            ]
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsTrue(ops.update_layer_show("bid.mdb", "10", True))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, -1), (11, 0), (20, -1)])
        self.assertIsTrue(ops.update_layer_show("bid.mdb", "20", False))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, -1), (11, 0), (20, 0)])

    def test_bid_layer_show_rejects_missing_and_unowned_layers_without_writing(self):
        conn = _layer_db([(10, 7, "A", 0, 1, 0, 0), (30, None, "Shared", 0, 1, -1, -1)])
        ops = _SqliteMdbOps(conn)
        with self.assertRaisesRegex(RuntimeError, "BidLayers has no row for UID 99"):
            ops.update_layer_show("bid.mdb", "99", True)
        with self.assertRaises(IncoherentBidOwnedScopeError):
            ops.update_layer_show("bid.mdb", "30", True)
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, 0), (30, 0)])

    def test_default_layer_show_updates_only_template_layers(self):
        conn = _layer_db(
            [
                (30, None, "T1", 0, 1, -1, -1),
                (31, None, "T2", 0, 2, -1, -1),
                (10, 7, "Bid layer", 0, 1, 0, 0),
            ]
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsTrue(ops.update_default_layer_show("bid.mdb", "30", True))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, 0), (30, -1), (31, 0)])
        self.assertIsTrue(ops.update_default_layer_show("bid.mdb", "30", False))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, 0), (30, 0), (31, 0)])

    def test_default_layer_show_refuses_a_bid_layer_and_a_missing_uid(self):
        conn = _layer_db([(10, 7, "Bid layer", 0, 1, 0, 0)])
        ops = _SqliteMdbOps(conn)
        self.assertIsFalse(ops.update_default_layer_show("bid.mdb", "10", True))
        self.assertIsFalse(ops.update_default_layer_show("bid.mdb", "99", True))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, 0)])

    def test_default_layer_show_rejects_a_duplicated_physical_uid(self):
        conn = _layer_db(
            [(30, None, "T1", 0, 1, -1, -1), (30, None, "T1 copy", 0, 2, -1, -1)]
        )
        with self.assertRaisesRegex(
            RuntimeError, "BidLayers contains duplicate UID 30"
        ):
            _SqliteMdbOps(conn).update_default_layer_show("bid.mdb", "30", True)
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(30, 0), (30, 0)])

    def test_all_default_layers_show_leaves_bid_layers_alone(self):
        conn = _layer_db(
            [
                (30, None, "T1", 0, 1, -1, -1),
                (31, None, "T2", -1, 2, -1, -1),
                (10, 7, "Bid layer", -1, 1, 0, 0),
            ]
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsTrue(ops.update_all_default_layers_show("bid.mdb", False))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, -1), (30, 0), (31, 0)])
        self.assertIsTrue(ops.update_all_default_layers_show("bid.mdb", True))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(10, -1), (30, -1), (31, -1)])

    def test_bid_layer_rename_changes_only_unlocked_non_template_layers(self):
        conn = _layer_db(
            [
                (10, 7, "A", -1, 1, 0, 0),
                (11, 7, "B", -1, 2, 0, -1),
                (12, 7, "C", -1, 3, -1, 0),
                (20, 8, "D", -1, 1, 0, 0),
            ]
        )
        ops = _SqliteMdbOps(conn)
        ops.update_layer_name("bid.mdb", "10", "Renamed")
        ops.update_layer_name("bid.mdb", "11", "Locked rename")
        ops.update_layer_name("bid.mdb", "12", "Template rename")
        self.assertEqual(
            _layer_rows(conn, "UID, Name"),
            [(10, "Renamed"), (11, "B"), (12, "C"), (20, "D")],
        )

    def test_bid_layer_rename_without_template_columns_still_scopes_to_the_uid(self):
        conn = _layer_db(
            [(10, 7, "A"), (11, 7, "B")],
            columns="UID INTEGER, BidUID INTEGER, Name TEXT",
        )
        self.assertIsTrue(_SqliteMdbOps(conn).update_layer_name("bid.mdb", "10", "X"))
        self.assertEqual(_layer_rows(conn, "UID, Name"), [(10, "X"), (11, "B")])

    def test_bid_layer_rename_rejects_duplicate_uid_and_unowned_layer(self):
        conn = _layer_db(
            [
                (10, 7, "A", -1, 1, 0, 0),
                (10, 8, "A2", -1, 1, 0, 0),
                (30, None, "Shared", -1, 1, -1, -1),
            ]
        )
        ops = _SqliteMdbOps(conn)
        with self.assertRaisesRegex(
            RuntimeError, "BidLayers contains duplicate UID 10"
        ):
            ops.update_layer_name("bid.mdb", "10", "X")
        with self.assertRaises(IncoherentBidOwnedScopeError):
            ops.update_layer_name("bid.mdb", "30", "X")
        self.assertEqual(
            _layer_rows(conn, "UID, Name"), [(10, "A"), (10, "A2"), (30, "Shared")]
        )

    def test_default_layer_rename_changes_only_template_layers(self):
        conn = _layer_db(
            [
                (30, None, "T1", -1, 1, -1, -1),
                (31, None, "T2", -1, 2, -1, -1),
                (10, 7, "Bid layer", -1, 1, 0, 0),
            ]
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsTrue(ops.update_default_layer_name("bid.mdb", "30", "Renamed"))
        self.assertIsFalse(ops.update_default_layer_name("bid.mdb", "10", "Nope"))
        self.assertIsFalse(ops.update_default_layer_name("bid.mdb", "99", "Nope"))
        self.assertEqual(
            _layer_rows(conn, "UID, Name"),
            [(10, "Bid layer"), (30, "Renamed"), (31, "T2")],
        )

    def test_default_layer_rename_rejects_duplicate_physical_uid(self):
        conn = _layer_db(
            [(30, None, "T1", -1, 1, -1, -1), (30, None, "T1b", -1, 2, -1, -1)]
        )
        with self.assertRaisesRegex(
            RuntimeError, "BidLayers contains duplicate UID 30"
        ):
            _SqliteMdbOps(conn).update_default_layer_name("bid.mdb", "30", "X")
        self.assertEqual(_layer_rows(conn, "UID, Name"), [(30, "T1"), (30, "T1b")])


class DefaultLayerUpdateMatchTests(_StrictTestCase):
    def test_a_non_negative_rowcount_decides_without_another_query(self):
        for rowcount, expected in ((0, False), (1, True), (3, True)):
            cursor = _MatchCursor(rowcount, fetched=("row",))
            self.assertIs(
                _default_layer_update_matched(cursor, "[Show] = ?", -1, 30),
                expected,
                rowcount,
            )
            self.assertEqual(cursor.executions, [])

    def test_an_unknown_rowcount_verifies_the_stored_value_of_the_template_layer(self):
        cursor = _MatchCursor(-1, fetched=("row",))
        self.assertIs(
            _default_layer_update_matched(cursor, "[Name] = ?", "N", 30), True
        )
        self.assertEqual(
            cursor.executions,
            [
                (
                    "SELECT [UID] FROM [BidLayers] WHERE [UID] = ? AND "
                    "[IsTemplate] <> 0 AND [Name] = ?",
                    (30, "N"),
                )
            ],
        )
        self.assertIs(
            _default_layer_update_matched(
                _MatchCursor(-1, fetched=None), "[Name] = ?", "N", 30
            ),
            False,
        )


class LayerInsertAndDeleteSemanticsTests(_StrictTestCase):
    def test_bid_layer_insert_shifts_only_later_layers_of_that_bid(self):
        conn = _layer_db(
            [
                (1, 7, "A", -1, 1, 0, 0),
                (2, 7, "B", -1, 2, 0, 0),
                (3, 7, "C", -1, 3, 0, 0),
                (4, 8, "Other", -1, 3, 0, 0),
            ]
        )
        new_uid = _SqliteDuplicateOps(conn).insert_layer("bid.mdb", "7", "New", 2)
        self.assertEqual(new_uid, "5")
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name, Show, Sequence, IsTemplate, IsLocked "
                "FROM BidLayers ORDER BY UID"
            ).fetchall(),
            [
                (1, 7, "A", -1, 1, 0, 0),
                (2, 7, "B", -1, 2, 0, 0),
                (3, 7, "C", -1, 4, 0, 0),
                (4, 8, "Other", -1, 3, 0, 0),
                (5, 7, "New", -1, 3, 0, 0),
            ],
        )

    def test_bid_layer_insert_without_a_sequence_column_only_appends_the_row(self):
        conn = _layer_db(
            [(1, 7, "A", -1), (2, 8, "B", -1)],
            columns="UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER",
        )
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_layer("bid.mdb", "7", "New", 5), "3"
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidLayers ORDER BY UID").fetchall(),
            [(1, 7, "A", -1), (2, 8, "B", -1), (3, 7, "New", -1)],
        )

    def test_bid_layer_insert_for_a_missing_bid_raises_and_writes_nothing(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0)])
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            _SqliteDuplicateOps(conn).insert_layer("bid.mdb", "99", "New", 0)
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1)])

    def test_default_layer_insert_shifts_only_later_template_layers(self):
        conn = _layer_db(
            [
                (1, None, "T1", -1, 1, -1, -1),
                (2, None, "T2", -1, 2, -1, -1),
                (3, None, "T3", -1, 3, -1, -1),
                (4, 7, "Bid layer", -1, 3, 0, 0),
            ]
        )
        new_uid = _SqliteDuplicateOps(conn).insert_default_layer("bid.mdb", "New", 2)
        self.assertEqual(new_uid, "5")
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name, Show, Sequence, IsTemplate, IsLocked "
                "FROM BidLayers ORDER BY UID"
            ).fetchall(),
            [
                (1, None, "T1", -1, 1, -1, -1),
                (2, None, "T2", -1, 2, -1, -1),
                (3, None, "T3", -1, 4, -1, -1),
                (4, 7, "Bid layer", -1, 3, 0, 0),
                (5, None, "New", -1, 3, -1, -1),
            ],
        )

    def test_default_layer_insert_without_a_sequence_column_only_appends_the_row(self):
        conn = _layer_db(
            [(1, "T1", -1)], columns="UID INTEGER, Name TEXT, IsTemplate INTEGER"
        )
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_default_layer("bid.mdb", "New", 0), "2"
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidLayers ORDER BY UID").fetchall(),
            [(1, "T1", -1), (2, "New", -1)],
        )

    def test_default_layer_delete_renumbers_only_later_template_layers(self):
        conn = _layer_db(
            [
                (1, None, "T1", -1, 1, -1, -1),
                (2, None, "T2", -1, 2, -1, -1),
                (3, None, "T3", -1, 3, -1, -1),
                (4, 7, "Bid layer", -1, 3, 0, 0),
            ]
        )
        self.assertIsTrue(_SqliteMdbOps(conn).delete_default_layer("bid.mdb", "2"))
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (3, 2), (4, 3)])

    def test_default_layer_delete_without_sequence_column_deletes_the_row_only(self):
        conn = _layer_db(
            [(1, "T1", -1), (2, "T2", -1)],
            columns="UID INTEGER, Name TEXT, IsTemplate INTEGER",
        )
        self.assertIsTrue(_SqliteMdbOps(conn).delete_default_layer("bid.mdb", "1"))
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidLayers").fetchall(), [(2, "T2")]
        )

    def test_default_layer_delete_refuses_bid_layers_and_unknown_uids(self):
        conn = _layer_db(
            [(1, None, "T1", -1, 1, -1, -1), (4, 7, "Bid layer", -1, 1, 0, 0)]
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsFalse(ops.delete_default_layer("bid.mdb", "4"))
        self.assertIsFalse(ops.delete_default_layer("bid.mdb", "99"))
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (4, 1)])

    def test_default_layer_delete_rejects_a_duplicated_physical_uid(self):
        conn = _layer_db(
            [(1, None, "T1", -1, 1, -1, -1), (1, None, "T1b", -1, 2, -1, -1)]
        )
        with self.assertRaisesRegex(RuntimeError, "BidLayers contains duplicate UID 1"):
            _SqliteMdbOps(conn).delete_default_layer("bid.mdb", "1")
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (1, 2)])

    def test_bid_layer_delete_clears_every_layer_reference_table_and_scopes_renumbering(
        self,
    ):
        conn = _layer_db(
            [
                (1, 7, "A", -1, 1, 0, 0),
                (2, 7, "B", -1, 2, 0, 0),
                (3, 7, "C", -1, 3, 0, 0),
                (4, 8, "Other", -1, 3, 0, 0),
            ]
        )
        for table in LAYER_REFERENCE_TABLES:
            conn.execute(f"CREATE TABLE {table} (UID INTEGER, BidLayerUID INTEGER)")
            conn.executemany(
                f"INSERT INTO {table} VALUES (?, ?)", [(100, 2), (101, 3), (102, 4)]
            )
        self.assertIsTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "2"))
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (3, 2), (4, 3)])
        for table in LAYER_REFERENCE_TABLES:
            self.assertEqual(
                conn.execute(
                    f"SELECT UID, BidLayerUID FROM {table} ORDER BY UID"
                ).fetchall(),
                [(100, None), (101, 3), (102, 4)],
                table,
            )

    def test_bid_layer_delete_skips_missing_and_columnless_reference_tables(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0), (2, 7, "B", -1, 2, 0, 0)])
        conn.execute("CREATE TABLE BidTexts (UID INTEGER)")
        conn.execute("INSERT INTO BidTexts VALUES (5)")
        conn.execute("CREATE TABLE BidComments (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidComments VALUES (6, 1)")
        with self.assertNoLogs("test", "WARNING"):
            self.assertIsTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "1"))
        self.assertEqual(conn.execute("SELECT UID FROM BidTexts").fetchall(), [(5,)])
        self.assertEqual(
            conn.execute("SELECT UID, BidLayerUID FROM BidComments").fetchall(),
            [(6, None)],
        )
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(2, 1)])

    def test_bid_layer_delete_needs_the_bid_scope_column_before_touching_anything(
        self,
    ):
        conn = _layer_db([(1, "A"), (2, "B")], columns="UID INTEGER, Name TEXT")
        with self.assertRaises(sqlite3.OperationalError):
            _SqliteMdbOps(conn).delete_layer("bid.mdb", "1")
        self.assertEqual(
            conn.execute("SELECT UID FROM BidLayers").fetchall(), [(1,), (2,)]
        )

    def test_bid_layer_delete_unknown_layer_is_a_missing_owner_error(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0)])
        with self.assertRaisesRegex(RuntimeError, "BidLayers has no row for UID 5"):
            _SqliteMdbOps(conn).delete_layer("bid.mdb", "5")
        self.assertEqual(_layer_rows(conn, "UID"), [(1,)])

    def test_bid_layer_delete_survives_a_failed_reference_clear_with_a_warning(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0), (2, 7, "B", -1, 2, 0, 0)])
        conn.execute("CREATE TABLE BidTexts (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute(
            "CREATE TRIGGER block_clear BEFORE UPDATE ON BidTexts "
            "BEGIN SELECT RAISE(ABORT, 'clear blocked'); END"
        )
        conn.execute("CREATE TABLE BidComments (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidTexts VALUES (5, 1)")
        conn.execute("INSERT INTO BidComments VALUES (6, 1)")
        with self.assertLogs("test", "WARNING") as logs:
            self.assertIsTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "1"))
        self.assertEqual(len(logs.records), 1)
        message = logs.records[0].getMessage()
        self.assertIn("BidTexts", message)
        self.assertIn("layer 1", message)
        self.assertIn("clear blocked", message)
        self.assertEqual(
            conn.execute("SELECT BidLayerUID FROM BidTexts").fetchall(), [(1,)]
        )
        self.assertEqual(
            conn.execute("SELECT BidLayerUID FROM BidComments").fetchall(), [(None,)]
        )
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(2, 1)])

    def test_bid_layer_delete_reraises_a_failed_clear_when_the_error_is_fatal(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0), (2, 7, "B", -1, 2, 0, 0)])
        conn.execute("CREATE TABLE BidTexts (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute(
            "CREATE TRIGGER block_clear BEFORE UPDATE ON BidTexts "
            "BEGIN SELECT RAISE(ABORT, 'clear blocked'); END"
        )
        conn.execute("INSERT INTO BidTexts VALUES (5, 1)")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "clear blocked"):
            _RaisingMutationErrorOps(conn).delete_layer("bid.mdb", "1")
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (2, 2)])

    def test_bid_layer_delete_without_template_columns_deletes_the_layer(self):
        conn = _layer_db(
            [(1, 7, "A", 1), (2, 7, "B", 2)],
            columns="UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER",
        )
        self.assertIsTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "1"))
        self.assertEqual(
            conn.execute("SELECT UID, Sequence FROM BidLayers").fetchall(), [(2, 1)]
        )

    def test_bid_layer_delete_without_a_sequence_column_leaves_other_rows_alone(self):
        conn = _layer_db(
            [(1, 7, "A", 0, 0), (2, 7, "B", 0, 0)],
            columns="UID INTEGER, BidUID INTEGER, Name TEXT, IsTemplate INTEGER, "
            "IsLocked INTEGER",
        )
        self.assertIsTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "1"))
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidLayers").fetchall(), [(2, "B")]
        )

    def test_bid_layer_delete_does_not_renumber_when_the_layer_has_no_sequence(self):
        conn = _layer_db([(1, 7, "A", -1, None, 0, 0), (2, 7, "B", -1, 1, 0, 0)])
        self.assertIsTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "1"))
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(2, 1)])

    def test_bid_layer_delete_refuses_a_locked_layer(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, -1)])
        self.assertIsFalse(_SqliteMdbOps(conn).delete_layer("bid.mdb", "1"))
        self.assertEqual(_layer_rows(conn, "UID"), [(1,)])


class LayerSwapSemanticsTests(_StrictTestCase):
    def test_default_layer_swap_exchanges_template_sequences_only(self):
        conn = _layer_db(
            [
                (1, None, "T1", -1, 1, -1, -1),
                (2, None, "T2", -1, 2, -1, -1),
                (3, None, "T3", -1, 3, -1, -1),
                (4, 7, "Bid layer", -1, 1, 0, 0),
            ]
        )
        self.assertIsTrue(
            _SqliteMdbOps(conn).swap_default_layer_sequence("bid.mdb", "1", "3")
        )
        self.assertEqual(
            _layer_rows(conn, "UID, Sequence"), [(1, 3), (2, 2), (3, 1), (4, 1)]
        )

    def test_default_layer_swap_refuses_a_pair_that_includes_a_bid_layer(self):
        conn = _layer_db(
            [(1, None, "T1", -1, 1, -1, -1), (4, 7, "Bid layer", -1, 2, 0, 0)]
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsFalse(ops.swap_default_layer_sequence("bid.mdb", "1", "4"))
        self.assertIsFalse(ops.swap_default_layer_sequence("bid.mdb", "1", "99"))
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (4, 2)])

    def test_default_layer_swap_refuses_a_pair_with_an_unset_sequence(self):
        conn = _layer_db(
            [(1, None, "T1", -1, 1, -1, -1), (2, None, "T2", -1, None, -1, -1)]
        )
        self.assertIsFalse(
            _SqliteMdbOps(conn).swap_default_layer_sequence("bid.mdb", "1", "2")
        )
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (2, None)])

    def test_default_layer_swap_rejects_a_duplicated_physical_uid(self):
        conn = _layer_db(
            [
                (1, None, "T1", -1, 1, -1, -1),
                (1, None, "T1b", -1, 5, -1, -1),
                (2, None, "T2", -1, 2, -1, -1),
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "BidLayers contains duplicate UID 1"):
            _SqliteMdbOps(conn).swap_default_layer_sequence("bid.mdb", "1", "2")
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (1, 5), (2, 2)])

    def test_bid_layer_swap_refuses_a_pair_with_an_unset_sequence(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0), (2, 7, "B", -1, None, 0, 0)])
        self.assertIsFalse(_SqliteMdbOps(conn).swap_layer_sequence("bid.mdb", "1", "2"))
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (2, None)])

    def test_swapping_a_bid_layer_with_itself_is_refused_without_writing(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0), (2, 7, "B", -1, 2, 0, 0)])
        self.assertIsFalse(_SqliteMdbOps(conn).swap_layer_sequence("bid.mdb", "1", "1"))
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (2, 2)])

    def test_bid_layer_swap_of_a_missing_layer_is_a_missing_owner_error(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0)])
        with self.assertRaisesRegex(RuntimeError, "BidLayers has no row for UID 9"):
            _SqliteMdbOps(conn).swap_layer_sequence("bid.mdb", "1", "9")
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1)])


class BulkLayerVisibilitySemanticsTests(_StrictTestCase):
    def test_uncaptured_bulk_visibility_without_template_columns_only_touches_the_bid(
        self,
    ):
        conn = _layer_db(
            [(1, 7, -1), (2, None, -1), (3, 8, -1)],
            columns="UID INTEGER, BidUID INTEGER, Show INTEGER",
        )
        self.assertIsTrue(
            _SqliteDuplicateOps(conn).update_all_layers_show("bid.mdb", "7", False)
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(1, 0), (2, -1), (3, -1)],
        )

    def test_captured_bulk_visibility_without_template_columns_rejects_shared_layers(
        self,
    ):
        conn = _layer_db(
            [(1, 7, -1), (2, None, -1)],
            columns="UID INTEGER, BidUID INTEGER, Show INTEGER",
        )
        self.assertIsFalse(
            _SqliteDuplicateOps(conn).update_all_layers_show(
                "bid.mdb", "7", False, ["1", "2"]
            )
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(1, -1), (2, -1)],
        )

    def test_captured_bulk_visibility_shows_layers_and_repeats_are_ignored(self):
        conn = _layer_db(
            [
                (1, 7, "A", 0, 1, 0, 0),
                (2, 7, "B", 0, 2, 0, 0),
                (3, 7, "C", 0, 3, 0, 0),
            ]
        )
        self.assertIsTrue(
            _SqliteDuplicateOps(conn).update_all_layers_show(
                "bid.mdb", "7", True, ["1", "1", "02", "2"]
            )
        )
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(1, -1), (2, -1), (3, 0)])

    def test_an_empty_capture_is_a_validated_no_op_for_an_existing_bid(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0)])
        ops = _SqliteDuplicateOps(conn)
        self.assertIsTrue(ops.update_all_layers_show("bid.mdb", "7", False, []))
        self.assertEqual(_layer_rows(conn, "UID, Show"), [(1, -1)])
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            ops.update_all_layers_show("bid.mdb", "99", False, [])
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            ops.update_all_layers_show("bid.mdb", "99", False)

    def test_a_capture_of_exactly_one_chunk_is_validated_and_written_in_one_pass(self):
        size = BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE
        conn = _layer_db([(uid, 7, "L", -1, uid, 0, 0) for uid in range(1, size + 3)])
        ops = _ParameterLimitedSqliteOps(conn, max_parameters=size + 2)
        self.assertIsTrue(
            ops.update_all_layers_show(
                "bid.mdb", "7", False, [str(uid) for uid in range(1, size + 1)]
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID FROM BidLayers WHERE Show = 0 ORDER BY UID"
            ).fetchall(),
            [(uid,) for uid in range(1, size + 1)],
        )

    def test_a_capture_one_over_a_chunk_spills_exactly_one_uid_into_a_second_chunk(
        self,
    ):
        size = BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE
        conn = _layer_db([(uid, 7, "L", -1, uid, 0, 0) for uid in range(1, size + 3)])
        ops = _ParameterLimitedSqliteOps(conn, max_parameters=size + 2)
        self.assertIsTrue(
            ops.update_all_layers_show(
                "bid.mdb", "7", False, [str(uid) for uid in range(1, size + 2)]
            )
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers WHERE Show = 0").fetchone()[0],
            size + 1,
        )

    def test_an_update_that_affects_a_different_count_than_captured_is_an_error(self):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = 3
        with self.assertRaisesRegex(
            RuntimeError,
            r"bulk Layer visibility update affected 3 of 2 captured Layers in a "
            r"2-Layer operation",
        ):
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])

    def test_a_zero_affected_count_is_rejected_not_treated_as_unknown(self):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = 0
        with self.assertRaisesRegex(RuntimeError, "affected 0 of 2 captured Layers"):
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])

    def test_unknown_count_verification_checks_the_written_value_and_scope(self):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = -1
        self.assertIsTrue(
            operations.update_all_layers_show("sql-db", "7", True, ["10", "11"])
        )
        verification = [
            execution
            for execution in operations.cursor.executions
            if execution[0].startswith("SELECT [UID] FROM [BidLayers]")
            and "[Show] = ?" in execution[0]
        ]
        self.assertEqual(
            verification,
            [
                (
                    "SELECT [UID] FROM [BidLayers] WHERE [UID] IN (?, ?) AND "
                    "[Show] = ? AND ([BidUID] = ? OR ([IsTemplate] <> 0 AND "
                    "[IsLocked] <> 0))",
                    (10, 11, -1, 7),
                )
            ],
        )

    def test_unknown_count_verification_reports_a_wrong_uid_set_of_the_right_size(
        self,
    ):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = -1
        operations.cursor.forced_postupdate_uids = (10, 12)
        with self.assertRaisesRegex(
            RuntimeError, "could verify only 2 of 2 captured Layers"
        ):
            operations.update_all_layers_show("sql-db", "7", False, ["10", "11"])

    def test_a_preflight_that_returns_a_wrong_uid_set_of_the_right_size_is_refused(
        self,
    ):
        operations = _LayerOperations()
        operations.cursor.forced_preflight_uids = (10, 12)
        self.assertIsFalse(
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])
        )
        self.assertIsFalse(
            any(
                sql.startswith("UPDATE [BidLayers] SET [Show]")
                for sql, _parameters in operations.cursor.executions
            )
        )

    def test_a_preflight_that_returns_too_few_uids_is_refused(self):
        operations = _LayerOperations()
        operations.cursor.forced_preflight_uids = (10,)
        self.assertIsFalse(
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])
        )


class _RecordingSchema(_SqliteSchema):
    def __init__(self, connection):
        super().__init__(connection)
        self.skips = []

    def log_optional_write_skip(self, table, column, operation):
        self.skips.append((table, column, operation))


class _InsertRecordingOps(_SqliteDuplicateOps):
    def __init__(self, connection):
        super().__init__(connection)
        self._schema_ref = _RecordingSchema(connection)
        self.inserts = []

    def _execute_insert_values(
        self, cursor, schema, table, values, required, operation
    ):
        self.inserts.append((table, tuple(required), operation))
        super()._execute_insert_values(
            cursor, schema, table, values, required, operation
        )


class _SqlLoggingCursor(_SqliteCursorWrapper):
    def __init__(self, connection, log):
        super().__init__(connection)
        self._log = log

    def execute(self, query, *params):
        self._log.append((" ".join(query.split()), params))
        return super().execute(query, *params)


class _SqlLoggingConnection(_SqliteConnectionWrapper):
    def __init__(self, connection, log):
        super().__init__(connection)
        self._log = log

    def cursor(self):
        return _SqlLoggingCursor(self._connection, self._log)


class _SqlLoggingOps(_SqliteDuplicateOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.sql = []

    def _connection(self, _db_path):
        return _SqlLoggingConnection(self._connection_ref, self.sql)

    def statements(self, prefix):
        return [item for item in self.sql if item[0].startswith(prefix)]


class _NoCountCursor:
    """SQL Server style cursor: UPDATE reports rowcount -1, preflights find rows."""

    rowcount = -1

    def __init__(self, verify_row):
        self._verify_row = verify_row
        self.executions = []
        self._last = ""

    def execute(self, sql, *parameters):
        self._last = " ".join(sql.split())
        self.executions.append((self._last, parameters))

    def fetchall(self):
        return [(parameter,) for parameter in self.executions[-1][1]]

    def fetchone(self):
        return self._verify_row


class _NoCountOps(LayerOperationsMixin):
    def __init__(self, verify_row):
        self.cursor = _NoCountCursor(verify_row)

    @contextmanager
    def _connection(self, _db_path):
        yield _Connection(self.cursor)

    def _schema(self, _connection):
        return _Schema()

    def _require_write_columns(self, schema, table, columns):
        pass


_FULL_LAYER_FIXTURE = [
    (1, 7, "A", -1, 1, 0, 0),
    (2, 7, "B", -1, 2, 0, 0),
    (30, None, "T1", -1, 1, -1, -1),
    (31, None, "T2", -1, 2, -1, -1),
]
_ALL_LAYER_COLUMN_NAMES = (
    "UID",
    "BidUID",
    "Name",
    "Show",
    "Sequence",
    "IsTemplate",
    "IsLocked",
)
# (operation, call, required BidLayers columns)
_LAYER_OPERATION_CONTRACTS = (
    (
        "update_layer_show",
        lambda o: o.update_layer_show("db", "1", True),
        ("UID", "Show"),
    ),
    (
        "update_default_layer_show",
        lambda o: o.update_default_layer_show("db", "30", True),
        ("UID", "Show", "IsTemplate"),
    ),
    (
        "insert_layer",
        lambda o: o.insert_layer("db", "7", "N", 1),
        ("UID", "BidUID", "Name"),
    ),
    (
        "insert_default_layer",
        lambda o: o.insert_default_layer("db", "N", 1),
        ("UID", "Name", "IsTemplate"),
    ),
    ("delete_layer", lambda o: o.delete_layer("db", "1"), ("UID",)),
    (
        "delete_default_layer",
        lambda o: o.delete_default_layer("db", "30"),
        ("UID", "IsTemplate"),
    ),
    (
        "update_all_layers_show",
        lambda o: o.update_all_layers_show("db", "7", False),
        ("BidUID", "Show"),
    ),
    (
        "update_all_default_layers_show",
        lambda o: o.update_all_default_layers_show("db", False),
        ("Show", "IsTemplate"),
    ),
    (
        "update_layer_name",
        lambda o: o.update_layer_name("db", "1", "X"),
        ("UID", "Name"),
    ),
    (
        "update_default_layer_name",
        lambda o: o.update_default_layer_name("db", "30", "X"),
        ("UID", "Name", "IsTemplate"),
    ),
    (
        "swap_layer_sequence",
        lambda o: o.swap_layer_sequence("db", "1", "2"),
        ("UID", "Sequence"),
    ),
    (
        "swap_default_layer_sequence",
        lambda o: o.swap_default_layer_sequence("db", "30", "31"),
        ("UID", "Sequence", "IsTemplate"),
    ),
)


class LayerWriteColumnContractTests(_StrictTestCase):
    def test_every_operation_succeeds_when_its_declared_columns_exist(self):
        for name, call, _required in _LAYER_OPERATION_CONTRACTS:
            with self.subTest(operation=name):
                conn = _layer_db(_FULL_LAYER_FIXTURE)
                self.assertIsNotNone(call(RealContractOps(conn)))

    def test_every_operation_refuses_to_start_without_each_declared_column(self):
        for name, call, required in _LAYER_OPERATION_CONTRACTS:
            for dropped in required:
                with self.subTest(operation=name, missing=dropped):
                    keep = [c for c in _ALL_LAYER_COLUMN_NAMES if c != dropped]
                    conn = sqlite3.connect(":memory:")
                    conn.execute("CREATE TABLE Bids (UID INTEGER)")
                    conn.execute("INSERT INTO Bids VALUES (7)")
                    conn.execute(f"CREATE TABLE BidLayers ({', '.join(keep)})")
                    marks = ", ".join("?" for _c in keep)
                    for row in _FULL_LAYER_FIXTURE:
                        values = [
                            v
                            for c, v in zip(_ALL_LAYER_COLUMN_NAMES, row)
                            if c != dropped
                        ]
                        conn.execute(f"INSERT INTO BidLayers VALUES ({marks})", values)
                    before = conn.execute("SELECT * FROM BidLayers").fetchall()
                    with self.assertRaisesRegex(
                        RuntimeError, f"Missing BidLayers.{dropped}$"
                    ):
                        call(RealContractOps(conn))
                    self.assertEqual(
                        conn.execute("SELECT * FROM BidLayers").fetchall(), before
                    )


class LayerInsertContractTests(_StrictTestCase):
    def test_bid_layer_insert_declares_its_required_columns_and_operation_name(self):
        conn = _layer_db(_FULL_LAYER_FIXTURE)
        ops = _InsertRecordingOps(conn)
        ops.insert_layer("db", "7", "N", 1)
        self.assertEqual(
            ops.inserts,
            [("BidLayers", ("UID", "BidUID", "Name"), "insert_layer")],
        )
        self.assertEqual(ops._schema_ref.skips, [])

    def test_default_layer_insert_declares_its_required_columns_and_operation_name(
        self,
    ):
        conn = _layer_db(_FULL_LAYER_FIXTURE)
        ops = _InsertRecordingOps(conn)
        ops.insert_default_layer("db", "N", 1)
        self.assertEqual(
            ops.inserts,
            [("BidLayers", ("UID", "Name", "IsTemplate"), "insert_default_layer")],
        )
        self.assertEqual(ops._schema_ref.skips, [])

    def test_inserts_without_a_sequence_column_report_the_skipped_renumbering(self):
        columns = "UID INTEGER, BidUID INTEGER, Name TEXT, IsTemplate INTEGER"
        conn = _layer_db([(1, 7, "A", 0)], columns=columns)
        ops = _InsertRecordingOps(conn)
        ops.insert_layer("db", "7", "N", 1)
        ops.insert_default_layer("db", "D", 1)
        self.assertEqual(
            ops._schema_ref.skips,
            [
                ("BidLayers", "Sequence", "insert_layer"),
                ("BidLayers", "Sequence", "insert_default_layer"),
            ],
        )


class LayerSqlContractTests(_StrictTestCase):
    def test_bid_layer_delete_selects_the_identity_and_ordering_of_an_unlocked_layer(
        self,
    ):
        conn = _layer_db(_FULL_LAYER_FIXTURE)
        ops = _SqlLoggingOps(conn)
        self.assertIs(ops.delete_layer("db", "1"), True)
        self.assertEqual(
            ops.statements("SELECT [UID], [Sequence]"),
            [
                (
                    "SELECT [UID], [Sequence], [BidUID] FROM [BidLayers] WHERE "
                    "[UID] = ? AND [IsTemplate] = 0 AND [IsLocked] = 0",
                    (1,),
                )
            ],
        )
        self.assertEqual(
            ops.statements("UPDATE [BidLayers] SET [Sequence]"),
            [
                (
                    "UPDATE [BidLayers] SET [Sequence] = [Sequence] - 1 WHERE "
                    "[BidUID] = ? AND [Sequence] > ?",
                    (7, 1),
                )
            ],
        )

    def test_default_layer_delete_selects_a_template_layer_and_renumbers_templates(
        self,
    ):
        conn = _layer_db(_FULL_LAYER_FIXTURE)
        ops = _SqlLoggingOps(conn)
        self.assertIs(ops.delete_default_layer("db", "30"), True)
        self.assertEqual(
            ops.statements("SELECT [UID], [Sequence]"),
            [
                (
                    "SELECT [UID], [Sequence] FROM [BidLayers] WHERE [UID] = ? AND "
                    "[IsTemplate] <> 0",
                    (30,),
                )
            ],
        )
        self.assertEqual(
            ops.statements("UPDATE [BidLayers] SET [Sequence]"),
            [
                (
                    "UPDATE [BidLayers] SET [Sequence] = [Sequence] - 1 WHERE "
                    "[Sequence] > ? AND [IsTemplate] <> 0",
                    (1,),
                )
            ],
        )

    def test_a_deleted_layer_without_a_sequence_value_issues_no_renumbering(self):
        for delete, uid in (("delete_layer", "1"), ("delete_default_layer", "30")):
            with self.subTest(delete=delete):
                conn = _layer_db(
                    [
                        (1, 7, "A", -1, None, 0, 0),
                        (2, 7, "B", -1, 5, 0, 0),
                        (30, None, "T1", -1, None, -1, -1),
                        (31, None, "T2", -1, 5, -1, -1),
                    ]
                )
                ops = _SqlLoggingOps(conn)
                self.assertIs(getattr(ops, delete)("db", uid), True)
                self.assertEqual(
                    ops.statements("UPDATE [BidLayers] SET [Sequence]"), []
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT Sequence FROM BidLayers WHERE UID IN (2, 31) "
                        "ORDER BY UID"
                    ).fetchall(),
                    [(5,), (5,)],
                )

    def test_bid_layer_delete_without_a_sequence_column_issues_no_renumbering(self):
        columns = "UID INTEGER, BidUID INTEGER, IsTemplate INTEGER, IsLocked INTEGER"
        conn = _layer_db([(1, 7, 0, 0), (2, 7, 0, 0)], columns=columns)
        ops = _SqlLoggingOps(conn)
        self.assertIs(ops.delete_layer("db", "1"), True)
        self.assertEqual(
            ops.statements("SELECT [UID]")[-1][0],
            "SELECT [UID], NULL AS [Sequence], [BidUID] FROM [BidLayers] WHERE "
            "[UID] = ? AND [IsTemplate] = 0 AND [IsLocked] = 0",
        )
        self.assertEqual(ops.statements("UPDATE [BidLayers] SET [Sequence]"), [])

    def test_default_layer_delete_without_a_sequence_column_selects_a_null_sequence(
        self,
    ):
        columns = "UID INTEGER, IsTemplate INTEGER"
        conn = _layer_db([(30, -1), (31, -1)], columns=columns)
        ops = _SqlLoggingOps(conn)
        self.assertIs(ops.delete_default_layer("db", "30"), True)
        self.assertEqual(
            ops.statements("SELECT [UID], NULL")[-1],
            (
                "SELECT [UID], NULL AS [Sequence] FROM [BidLayers] WHERE "
                "[UID] = ? AND [IsTemplate] <> 0",
                (30,),
            ),
        )


class DefaultLayerNoCountFallbackTests(_StrictTestCase):
    def test_show_update_with_an_unknown_rowcount_verifies_the_show_value(self):
        ops = _NoCountOps(("row",))
        self.assertIs(ops.update_default_layer_show("db", "30", True), True)
        self.assertEqual(
            ops.cursor.executions[-1],
            (
                "SELECT [UID] FROM [BidLayers] WHERE [UID] = ? AND "
                "[IsTemplate] <> 0 AND [Show] = ?",
                (30, -1),
            ),
        )

    def test_name_update_with_an_unknown_rowcount_verifies_the_name(self):
        ops = _NoCountOps(("row",))
        self.assertIs(ops.update_default_layer_name("db", "30", "Name"), True)
        self.assertEqual(
            ops.cursor.executions[-1],
            (
                "SELECT [UID] FROM [BidLayers] WHERE [UID] = ? AND "
                "[IsTemplate] <> 0 AND [Name] = ?",
                (30, "Name"),
            ),
        )

    def test_unverified_unknown_rowcount_updates_report_no_match(self):
        self.assertIs(
            _NoCountOps(None).update_default_layer_show("db", "30", False), False
        )
        self.assertIs(
            _NoCountOps(None).update_default_layer_name("db", "30", "N"), False
        )


class BulkVisibilityPartialTemplateSchemaTests(_StrictTestCase):
    def test_a_schema_with_only_one_template_marker_never_widens_the_scope(self):
        conn = _layer_db(
            [(1, 7, -1, 0), (2, None, -1, -1), (3, 8, -1, 0)],
            columns="UID INTEGER, BidUID INTEGER, Show INTEGER, IsTemplate INTEGER",
        )
        ops = _SqlLoggingOps(conn)
        self.assertIs(ops.update_all_layers_show("db", "7", False), True)
        self.assertEqual(
            ops.statements("UPDATE [BidLayers] SET [Show]"),
            [("UPDATE [BidLayers] SET [Show] = ? WHERE [BidUID] = ?", (0, 7))],
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(1, 0), (2, -1), (3, -1)],
        )
        conn = _layer_db(
            [(1, 7, -1, 0), (2, None, -1, -1)],
            columns="UID INTEGER, BidUID INTEGER, Show INTEGER, IsLocked INTEGER",
        )
        self.assertIs(
            _SqlLoggingOps(conn).update_all_layers_show("db", "7", False, ["1"]), True
        )
        self.assertEqual(
            conn.execute("SELECT UID, Show FROM BidLayers ORDER BY UID").fetchall(),
            [(1, 0), (2, -1)],
        )


class _NumericTextRejectingCursor(_SqliteCursorWrapper):
    """Fails any numeric-text bind, which sqlite would silently coerce.

    Real Access also accepts numeric text for a Long column (see
    DuplicateBidRealAccessNumericTextTests in test_bid_operations), so this pins
    the typed-binding convention of the writer, not an Access limitation.
    """

    def execute(self, query, *params):
        for parameter in params:
            if isinstance(parameter, str) and parameter.strip().lstrip("-").isdigit():
                raise AssertionError(f"numeric text parameter {parameter!r} in {query}")
        return super().execute(query, *params)


class _NumericTextRejectingConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return _NumericTextRejectingCursor(self._connection)


class _StrictParameterOps(_SqliteDuplicateOps):
    def _connection(self, _db_path):
        return _NumericTextRejectingConnection(self._connection_ref)


class LayerParameterTypingTests(_StrictTestCase):
    """The uid/bid arguments arrive as text; every operation binds them as integers."""

    def _db(self):
        conn = _layer_db(
            [
                (1, 7, "A", -1, 1, 0, 0),
                (2, 7, "B", -1, 2, 0, 0),
                (3, 7, "C", -1, 3, 0, 0),
                (30, None, "T1", -1, 1, -1, -1),
                (31, None, "T2", -1, 2, -1, -1),
                (32, None, "T3", -1, 3, -1, -1),
            ]
        )
        conn.execute("CREATE TABLE BidComments (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidComments VALUES (1, 2)")
        return conn

    def test_every_operation_binds_text_identifiers_as_integers(self):
        ops = _StrictParameterOps(self._db())
        calls = (
            lambda: ops.update_layer_show("d", "1", True),
            lambda: ops.update_default_layer_show("d", "30", True),
            lambda: ops.insert_layer("d", "7", "N", 1),
            lambda: ops.insert_default_layer("d", "N", 1),
            lambda: ops.delete_layer("d", "2"),
            lambda: ops.delete_default_layer("d", "32"),
            lambda: ops.update_all_layers_show("d", "7", False),
            lambda: ops.update_all_layers_show("d", "7", False, ["1", "3"]),
            lambda: ops.update_all_default_layers_show("d", False),
            lambda: ops.update_layer_name("d", "1", "X"),
            lambda: ops.update_default_layer_name("d", "30", "X"),
            lambda: ops.swap_layer_sequence("d", "1", "3"),
            lambda: ops.swap_default_layer_sequence("d", "30", "31"),
        )
        for index, call in enumerate(calls):
            with self.subTest(call=index):
                self.assertIsNotNone(call())

    def test_swap_default_layer_sequence_rejects_a_duplicated_uid_on_either_side(self):
        for duplicate in ("30", "31"):
            with self.subTest(duplicate=duplicate):
                conn = self._db()
                conn.execute(
                    f"INSERT INTO BidLayers VALUES ({duplicate}, NULL, 'dup', -1, 9, -1, -1)"
                )
                before = _layer_rows(conn, "UID, Sequence")
                with self.assertRaisesRegex(
                    RuntimeError, f"BidLayers contains duplicate UID {duplicate}"
                ):
                    _SqliteMdbOps(conn).swap_default_layer_sequence(
                        "bid.mdb", "30", "31"
                    )
                self.assertEqual(_layer_rows(conn, "UID, Sequence"), before)

    def test_swap_layer_sequence_rejects_a_duplicated_uid_on_either_side(self):
        for duplicate in ("1", "3"):
            with self.subTest(duplicate=duplicate):
                conn = self._db()
                conn.execute(
                    f"INSERT INTO BidLayers VALUES ({duplicate}, 7, 'dup', -1, 9, 0, 0)"
                )
                before = _layer_rows(conn, "UID, Sequence")
                with self.assertRaisesRegex(
                    RuntimeError, f"BidLayers contains duplicate UID {duplicate}"
                ):
                    _SqliteMdbOps(conn).swap_layer_sequence("bid.mdb", "1", "3")
                self.assertEqual(_layer_rows(conn, "UID, Sequence"), before)


class LayerTextRowTests(_StrictTestCase):
    """Drivers may report identifier columns as text; comparisons must still hold."""

    def test_captured_visibility_accepts_identifiers_reported_as_text(self):
        operations = _LayerOperations()
        operations.cursor.forced_preflight_uids = ("10", "11")
        self.assertIsTrue(
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])
        )
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = -1
        operations.cursor.forced_preflight_uids = ("10", "11")
        operations.cursor.forced_postupdate_uids = ("10", "11")
        self.assertIsTrue(
            operations.update_all_layers_show("sql-db", "7", False, ["10", "11"])
        )


class _NoCountRenameCursor(_Cursor):
    """SQL Server style cursor: UPDATE reports rowcount -1, read-back is scripted."""

    rowcount = -1

    def __init__(self, verify_row):
        super().__init__()
        self._verify_row = verify_row

    def fetchone(self):
        return self._verify_row


class LayerRenameOutcomeTests(_StrictTestCase):
    """update_layer_name's result says whether the name was stored.

    The ownership preflight only proves the layer exists in one bid; the UPDATE
    itself is further guarded by IsTemplate = 0 AND IsLocked = 0. Callers treat
    False as "not applied" (the sidebar reloads, a queued rename is rejected), so
    a guard that matched nothing must not be reported as success. The default
    layer rename already reports its match (update_default_layer_name).
    """

    def test_a_rename_blocked_by_the_locked_or_template_guard_reports_no_change(self):
        conn = _layer_db(
            [
                (10, 7, "A", -1, 1, 0, 0),
                (11, 7, "Locked", -1, 2, 0, -1),
                (12, 7, "Template", -1, 3, -1, 0),
            ]
        )
        ops = _SqliteMdbOps(conn)
        self.assertIsFalse(ops.update_layer_name("bid.mdb", "11", "Renamed"))
        self.assertIsFalse(ops.update_layer_name("bid.mdb", "12", "Renamed"))
        self.assertEqual(
            _layer_rows(conn, "UID, Name"),
            [(10, "A"), (11, "Locked"), (12, "Template")],
        )
        self.assertIsTrue(ops.update_layer_name("bid.mdb", "10", "Renamed"))
        self.assertEqual(
            _layer_rows(conn, "UID, Name"),
            [(10, "Renamed"), (11, "Locked"), (12, "Template")],
        )

    def test_a_rename_without_the_guard_columns_still_reports_the_match(self):
        conn = _layer_db(
            [(10, 7, "A")], columns="UID INTEGER, BidUID INTEGER, Name TEXT"
        )
        self.assertIsTrue(_SqliteMdbOps(conn).update_layer_name("bid.mdb", "10", "B"))

    def test_an_unknown_rowcount_is_confirmed_by_reading_the_name_back(self):
        for stored, expected in ((("row",), True), (None, False)):
            with self.subTest(stored=stored):
                operations = _LayerOperations()
                operations.cursor = _NoCountRenameCursor(stored)
                self.assertIs(
                    operations.update_layer_name("sql-db", "10", "Renamed"), expected
                )
                self.assertEqual(
                    operations.cursor.executions[-1],
                    (
                        "SELECT [UID] FROM [BidLayers] WHERE [UID] = ? AND "
                        "[IsTemplate] = 0 AND [IsLocked] = 0 AND [Name] = ?",
                        (10, "Renamed"),
                    ),
                )

    def test_a_reported_rowcount_decides_a_rename_without_a_read_back(self):
        for rowcount, expected in ((0, False), (1, True)):
            with self.subTest(rowcount=rowcount):
                operations = _LayerOperations()
                operations.cursor.forced_update_rowcount = rowcount
                self.assertIs(
                    operations.update_layer_name("bid.mdb", "10", "Renamed"), expected
                )
                self.assertEqual(
                    operations.cursor.executions[-1],
                    (
                        "UPDATE [BidLayers] SET [Name] = ? WHERE [UID] = ? AND "
                        "[IsTemplate] = 0 AND [IsLocked] = 0",
                        ("Renamed", 10),
                    ),
                )


class LayerOperationsRealAccessTests(unittest.TestCase):
    """The layer operations against a real Access/ACE database.

    sqlite stands in for Access everywhere else in this module; it cannot show
    how the Jet engine reports an UPDATE's rowcount, evaluates the yes/no
    criteria, or what a rolled-back transaction leaves behind. The scenarios
    run in a child process (Access ODBC state must not leak into the suite) and
    are skipped when the driver is unavailable. Identifiers are passed as text,
    as the application does, and the writer binds them as integers.
    """

    @staticmethod
    def _create_database(folder, seed, references=True):
        from pathlib import Path
        import tests.helpers.mdb.schema_support as access

        db_path = Path(folder) / "layers.mdb"
        if not access.DatabaseCreator().create_database(db_path, "Layers"):
            raise AssertionError("database creation failed")
        connection = access._connect_mdb(db_path)
        cursor = connection.cursor()
        try:
            for bid_uid in (11, 12):
                cursor.execute(
                    "INSERT INTO [Bids] ([UID], [JobName]) VALUES (?, ?)",
                    bid_uid,
                    f"Bid {bid_uid}",
                )
            for uid, bid_uid, name, show, sequence, locked in seed:
                cursor.execute(
                    "INSERT INTO [BidLayers] ([UID], [BidUID], [Name], [Show], "
                    "[Sequence], [IsTemplate], [IsLocked]) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    uid,
                    bid_uid,
                    name,
                    show,
                    sequence,
                    False,
                    locked,
                )
            condition_rows = ((301, 11, 102), (302, 12, 202), (303, 11, 103))
            for uid, bid_uid, layer_uid in condition_rows if references else ():
                cursor.execute(
                    "INSERT INTO [BidConditions] ([UID], [BidUID], [BidLayerUID], "
                    "[Name]) VALUES (?, ?, ?, 'condition')",
                    uid,
                    bid_uid,
                    layer_uid,
                )
            annotation_rows = (
                ("BidComments", 401, 11, 102),
                ("BidAnnotationRects", 501, 11, 102),
                ("BidAnnotationRects", 502, 12, 202),
            )
            for table, uid, bid_uid, layer_uid in annotation_rows if references else ():
                cursor.execute(
                    f"INSERT INTO [{table}] ([UID], [BidUID], [BidLayerUID]) "
                    "VALUES (?, ?, ?)",
                    uid,
                    bid_uid,
                    layer_uid,
                )
            connection.commit()
        finally:
            cursor.close()
            connection.close()
        return db_path

    @staticmethod
    def _query(db_path, sql):
        import tests.helpers.mdb.schema_support as access

        connection = access._connect_mdb(db_path)
        cursor = connection.cursor()
        try:
            cursor.execute(sql)
            # Access yes/no columns come back as bool; compare them as -1 / 0
            return [
                tuple(
                    -int(value) if isinstance(value, bool) else value for value in row
                )
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def _with_writer(db_path, action):
        from ost_visualizer.infrastructure.mdb.connection_manager import (
            MdbConnectionManager,
        )
        from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter

        manager = MdbConnectionManager()
        try:
            return action(MdbWriter(manager), str(db_path))
        finally:
            manager.close()

    @classmethod
    def _fail_then_commit_elsewhere(cls, db_path, writer_class, failing_call, label):
        """Run a failing write, then an unrelated committing write on the same cache.

        A rollback that only happens when the connection is closed would let the
        next committed write of the same cached connection persist the failed
        write's partial changes.
        """
        from ost_visualizer.infrastructure.mdb.connection_manager import (
            MdbConnectionManager,
        )
        from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter

        manager = MdbConnectionManager()
        try:
            cls._expect_raises(
                RuntimeError,
                lambda: failing_call(writer_class(manager), str(db_path)),
                label,
            )
            cls._expect_result(
                MdbWriter(manager).update_layer_show(str(db_path), "202", False),
                True,
                "unrelated write after the failure",
            )
        finally:
            manager.close()

    @classmethod
    def _expect_rows(cls, db_path, sql, expected, label):
        rows = cls._query(db_path, sql)
        if rows != expected:
            raise AssertionError(f"{label}: {rows} != {expected}")

    @staticmethod
    def _expect_raises(error_type, call, label):
        try:
            call()
        except error_type:
            return
        raise AssertionError(f"{label}: {error_type.__name__} was not raised")

    @staticmethod
    def _expect_result(actual, expected, label):
        if actual is not expected:
            raise AssertionError(f"{label}: returned {actual!r}, expected {expected!r}")

    @classmethod
    def _bid_layer_lifecycle_through_real_access(cls):
        import tempfile
        from ost_visualizer.infrastructure.database.bid_owned_identity import (
            IncoherentBidOwnedScopeError,
        )
        from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter

        bid_layers = (
            "SELECT [UID], [BidUID], [Name], [Show], [Sequence] FROM [BidLayers] "
            "WHERE [BidUID] IS NOT NULL ORDER BY [UID]"
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            seed = (
                (101, 11, "A", -1, 1, False),
                (102, 11, "B", -1, 2, False),
                (103, 11, "C", -1, 3, False),
                (104, 11, "Locked", -1, 4, True),
                (201, 12, "X", -1, 1, False),
                (202, 12, "Y", -1, 2, False),
            )
            db_path = cls._create_database(folder, seed)

            def run(action):
                return cls._with_writer(db_path, action)

            # rename: quoting survives parameter binding; the locked guard is reported
            name = 'O\'Brien "A" é; DROP'
            cls._expect_result(
                run(lambda w, p: w.update_layer_name(p, "101", name)),
                True,
                "rename of an unlocked layer",
            )
            cls._expect_result(
                run(lambda w, p: w.update_layer_name(p, "104", "Nope")),
                False,
                "rename of a locked layer",
            )
            cls._expect_raises(
                RuntimeError,
                lambda: run(lambda w, p: w.update_layer_name(p, "999", "Nope")),
                "rename of an unknown layer",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [Name] FROM [BidLayers] WHERE [BidUID] IS NOT NULL "
                "ORDER BY [UID]",
                [
                    (101, name),
                    (102, "B"),
                    (103, "C"),
                    (104, "Locked"),
                    (201, "X"),
                    (202, "Y"),
                ],
                "names after rename",
            )

            # single and bulk visibility
            cls._expect_result(
                run(lambda w, p: w.update_layer_show(p, "101", False)),
                True,
                "show of one layer",
            )
            show_rows = (
                "SELECT [UID], [Show] FROM [BidLayers] WHERE [BidUID] IS NOT NULL "
                "ORDER BY [UID]"
            )
            cls._expect_rows(
                db_path,
                show_rows,
                [(101, 0), (102, -1), (103, -1), (104, -1), (201, -1), (202, -1)],
                "show of one layer",
            )
            cls._expect_result(
                run(
                    lambda w, p: w.update_all_layers_show(
                        p, "11", False, ["102", "201"]
                    )
                ),
                False,
                "captured layer of another bid",
            )
            cls._expect_result(
                run(
                    lambda w, p: w.update_all_layers_show(
                        p, "11", False, ["102", "103"]
                    )
                ),
                True,
                "captured visibility",
            )
            cls._expect_rows(
                db_path,
                show_rows,
                [(101, 0), (102, 0), (103, 0), (104, -1), (201, -1), (202, -1)],
                "captured visibility",
            )
            cls._expect_result(
                run(lambda w, p: w.update_all_layers_show(p, "11", False)),
                True,
                "uncaptured visibility",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [Show] FROM [BidLayers] ORDER BY [UID]",
                [
                    (1, 0),
                    (2, 0),
                    (3, 0),
                    (4, 0),
                    (101, 0),
                    (102, 0),
                    (103, 0),
                    (104, 0),
                    (201, -1),
                    (202, -1),
                ],
                "uncaptured visibility covers the bid and the shared layers only",
            )

            # insert shifts only the later layers of that bid
            new_uid = run(lambda w, p: w.insert_layer(p, "11", "New", 1))
            if new_uid is None or int(new_uid) in (101, 102, 103, 104, 201, 202):
                raise AssertionError(f"inserted layer uid {new_uid!r}")
            cls._expect_rows(
                db_path,
                bid_layers,
                [
                    (101, 11, name, 0, 1),
                    (102, 11, "B", 0, 3),
                    (103, 11, "C", 0, 4),
                    (104, 11, "Locked", 0, 5),
                    (201, 12, "X", -1, 1),
                    (202, 12, "Y", -1, 2),
                    (int(new_uid), 11, "New", -1, 2),
                ],
                "layers after insert",
            )

            # swap exchanges two sequences inside one bid and refuses a cross-bid pair
            cls._expect_result(
                run(lambda w, p: w.swap_layer_sequence(p, "101", "103")),
                True,
                "swap",
            )
            cls._expect_raises(
                IncoherentBidOwnedScopeError,
                lambda: run(lambda w, p: w.swap_layer_sequence(p, "101", "201")),
                "cross-bid swap",
            )
            sequences = (
                "SELECT [UID], [Sequence] FROM [BidLayers] "
                "WHERE [BidUID] IS NOT NULL ORDER BY [UID]"
            )
            cls._expect_rows(
                db_path,
                sequences,
                [
                    (101, 4),
                    (102, 3),
                    (103, 1),
                    (104, 5),
                    (201, 1),
                    (202, 2),
                    (int(new_uid), 2),
                ],
                "sequences after swap",
            )

            # a failing renumber statement rolls back the cascade and the delete
            class _FailingRenumberCursor:
                def __init__(self, cursor):
                    self._cursor = cursor

                def __enter__(self):
                    return self

                def __exit__(self, *_exception):
                    return self._cursor.__exit__(*_exception)

                def execute(self, sql, *parameters):
                    if "[Sequence] = [Sequence] - 1" in sql:
                        raise RuntimeError("renumbering failed")
                    return self._cursor.execute(sql, *parameters)

                def __getattr__(self, attribute):
                    return getattr(self._cursor, attribute)

            class _FailingRenumberConnection:
                def __init__(self, connection):
                    self._connection = connection

                def cursor(self):
                    return _FailingRenumberCursor(self._connection.cursor())

                def __getattr__(self, attribute):
                    return getattr(self._connection, attribute)

            class _FailingRenumberWriter(MdbWriter):
                @contextmanager
                def _connection(self, db_path):
                    with super()._connection(db_path) as connection:
                        yield _FailingRenumberConnection(connection)

            references = (
                "SELECT 'condition', [UID], [BidLayerUID] FROM [BidConditions] "
                "UNION ALL SELECT 'comment', [UID], [BidLayerUID] FROM [BidComments] "
                "UNION ALL SELECT 'rect', [UID], [BidLayerUID] "
                "FROM [BidAnnotationRects]"
            )
            before_layers = cls._query(db_path, bid_layers)
            before_references = sorted(cls._query(db_path, references), key=repr)
            cls._fail_then_commit_elsewhere(
                db_path,
                _FailingRenumberWriter,
                lambda w, p: w.delete_layer(p, "102"),
                "failing delete",
            )
            # only the unrelated write (layer 202 hidden) may have been committed
            hidden_202 = [
                (*row[:3], 0, row[4]) if row[0] == 202 else row for row in before_layers
            ]
            if cls._query(db_path, bid_layers) != hidden_202:
                raise AssertionError("a failed delete changed the layers")
            if sorted(cls._query(db_path, references), key=repr) != before_references:
                raise AssertionError("a failed delete left cleared references")
            cls._expect_result(
                run(lambda w, p: w.update_layer_show(p, "202", True)), True, "restore"
            )

            # the delete: references of that layer only are cleared, only later
            # layers of that bid are renumbered, guarded layers are refused
            cls._expect_result(
                run(lambda w, p: w.delete_layer(p, "102")), True, "delete"
            )
            cls._expect_result(
                run(lambda w, p: w.delete_layer(p, "104")), False, "locked delete"
            )
            cls._expect_rows(
                db_path,
                bid_layers,
                [
                    (101, 11, name, 0, 3),
                    (103, 11, "C", 0, 1),
                    (104, 11, "Locked", 0, 4),
                    (201, 12, "X", -1, 1),
                    (202, 12, "Y", -1, 2),
                    (int(new_uid), 11, "New", -1, 2),
                ],
                "layers after delete",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [BidLayerUID] FROM [BidConditions] ORDER BY [UID]",
                [(301, None), (302, 202), (303, 103)],
                "condition references after delete",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [BidLayerUID] FROM [BidComments]",
                [(401, None)],
                "comment references after delete",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [BidLayerUID] FROM [BidAnnotationRects] ORDER BY [UID]",
                [(501, None), (502, 202)],
                "annotation references after delete",
            )

            # a failing insert leaves the sequences it had already shifted alone
            class _FailingInsertWriter(MdbWriter):
                def _execute_insert_values(self, *_arguments):
                    raise RuntimeError("insert failed")

            before_layers = cls._query(db_path, bid_layers)
            cls._fail_then_commit_elsewhere(
                db_path,
                _FailingInsertWriter,
                lambda w, p: w.insert_layer(p, "11", "Doomed", 0),
                "failing insert",
            )
            hidden_202 = [
                (*row[:3], 0, row[4]) if row[0] == 202 else row for row in before_layers
            ]
            if cls._query(db_path, bid_layers) != hidden_202:
                raise AssertionError("a failed insert left shifted sequences")

    @classmethod
    def _default_layer_lifecycle_through_real_access(cls):
        import tempfile
        import pyodbc
        import tests.helpers.mdb.schema_support as access

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db_path = cls._create_database(
                folder, ((101, 11, "Bid layer", -1, 9, False),), references=False
            )

            def run(action):
                return cls._with_writer(db_path, action)

            seed_connection = access._connect_mdb(db_path)
            try:
                seed_connection.cursor().execute(
                    "INSERT INTO [BidConditions] ([UID], [BidUID], [BidLayerUID], "
                    "[Name]) VALUES (301, 11, 2, 'on the Annotation layer')"
                )
                seed_connection.commit()
            finally:
                seed_connection.close()

            templates = (
                "SELECT [UID], [Name], [Show], [Sequence], [IsTemplate], [IsLocked] "
                "FROM [BidLayers] WHERE [IsTemplate] <> 0 ORDER BY [UID]"
            )
            bid_layer = (
                "SELECT [Name], [Show], [Sequence] FROM [BidLayers] WHERE [UID] = 101"
            )

            name = "Dflt 'q' é"
            cls._expect_result(
                run(lambda w, p: w.update_default_layer_name(p, "1", name)),
                True,
                "default rename",
            )
            cls._expect_result(
                run(lambda w, p: w.update_default_layer_name(p, "101", "No")),
                False,
                "default rename of a bid layer",
            )
            cls._expect_result(
                run(lambda w, p: w.update_default_layer_name(p, "99", "No")),
                False,
                "default rename of an unknown layer",
            )
            cls._expect_result(
                run(lambda w, p: w.update_default_layer_show(p, "2", False)),
                True,
                "default show",
            )
            cls._expect_result(
                run(lambda w, p: w.update_default_layer_show(p, "101", False)),
                False,
                "default show of a bid layer",
            )
            cls._expect_rows(
                db_path,
                templates,
                [
                    (1, name, -1, 2, -1, -1),
                    (2, "Annotation", 0, 1, -1, -1),
                    (3, "Image", -1, 0, -1, -1),
                    (4, "Comments", -1, 3, -1, -1),
                ],
                "default layers after rename and show",
            )
            cls._expect_rows(
                db_path, bid_layer, [("Bid layer", -1, 9)], "bid layer after edits"
            )

            cls._expect_result(
                run(lambda w, p: w.update_all_default_layers_show(p, False)),
                True,
                "default show all",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [Show] FROM [BidLayers] ORDER BY [UID]",
                [(1, 0), (2, 0), (3, 0), (4, 0), (101, -1)],
                "show of every default layer",
            )

            new_uid = run(lambda w, p: w.insert_default_layer(p, "DNew", 1))
            if new_uid is None or int(new_uid) in (1, 2, 3, 4, 101):
                raise AssertionError(f"inserted default layer uid {new_uid!r}")
            cls._expect_rows(
                db_path,
                templates,
                [
                    (1, name, 0, 3, -1, -1),
                    (2, "Annotation", 0, 1, -1, -1),
                    (3, "Image", 0, 0, -1, -1),
                    (4, "Comments", 0, 4, -1, -1),
                    (int(new_uid), "DNew", -1, 2, -1, -1),
                ],
                "default layers after insert",
            )

            cls._expect_result(
                run(lambda w, p: w.swap_default_layer_sequence(p, "1", "3")),
                True,
                "default swap",
            )
            cls._expect_result(
                run(lambda w, p: w.swap_default_layer_sequence(p, "1", "101")),
                False,
                "default swap with a bid layer",
            )
            cls._expect_result(
                run(lambda w, p: w.delete_default_layer(p, "101")),
                False,
                "default delete of a bid layer",
            )
            cls._expect_result(
                run(lambda w, p: w.delete_default_layer(p, "3")),
                True,
                "default delete",
            )
            cls._expect_rows(
                db_path,
                templates,
                [
                    (1, name, 0, 0, -1, -1),
                    (2, "Annotation", 0, 1, -1, -1),
                    (4, "Comments", 0, 3, -1, -1),
                    (int(new_uid), "DNew", -1, 2, -1, -1),
                ],
                "default layers after swap and delete",
            )

            # a default layer that a condition still references is not deleted
            # (Access enforces the relationship), and nothing is half-deleted
            cls._expect_raises(
                pyodbc.Error,
                lambda: run(lambda w, p: w.delete_default_layer(p, "2")),
                "referenced default delete",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [Sequence] FROM [BidLayers] WHERE [IsTemplate] <> 0 "
                "ORDER BY [UID]",
                [(1, 0), (2, 1), (4, 3), (int(new_uid), 2)],
                "default layers after the refused delete",
            )
            cls._expect_rows(
                db_path,
                "SELECT [UID], [BidLayerUID] FROM [BidConditions]",
                [(301, 2)],
                "condition reference after the refused delete",
            )
            cls._expect_rows(
                db_path, bid_layer, [("Bid layer", -1, 9)], "bid layer after all edits"
            )

    def _run_in_child(self, scenario):
        import subprocess
        import sys
        from tests.helpers.mdb.schema_support import _access_available
        from tests.paths import REPO_ROOT

        if not _access_available():
            self.skipTest("Access ODBC/ADOX is not available")
        code = (
            "from tests.infrastructure.mdb.components.test_layer_operations import "
            f"LayerOperationsRealAccessTests as Tests; Tests.{scenario}()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bid_layer_operations_persist_and_roll_back_on_real_access(self):
        self._run_in_child("_bid_layer_lifecycle_through_real_access")

    def test_default_layer_operations_persist_on_real_access(self):
        self._run_in_child("_default_layer_lifecycle_through_real_access")


class _FailingRenumberCursor(_SqliteCursorWrapper):
    def execute(self, query, *params):
        if "[Sequence] = [Sequence] - 1" in query:
            raise RuntimeError("renumbering failed")
        return super().execute(query, *params)


class _FailingRenumberConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return _FailingRenumberCursor(self._connection)


class _FailingRenumberOps(_SqliteMdbOps):
    def _connection(self, _db_path):
        return _FailingRenumberConnection(self._connection_ref)


class LayerFailurePropagationTests(_StrictTestCase):
    def test_a_failed_renumbering_after_a_bid_layer_delete_propagates(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0), (2, 7, "B", -1, 2, 0, 0)])
        with self.assertRaisesRegex(RuntimeError, "renumbering failed"):
            _FailingRenumberOps(conn).delete_layer("bid.mdb", "1")

    def test_a_failed_renumbering_after_a_default_layer_delete_propagates(self):
        conn = _layer_db(
            [(1, None, "T1", -1, 1, -1, -1), (2, None, "T2", -1, 2, -1, -1)]
        )
        with self.assertRaisesRegex(RuntimeError, "renumbering failed"):
            _FailingRenumberOps(conn).delete_default_layer("bid.mdb", "1")

    def test_a_failed_insert_shift_propagates_before_any_row_is_added(self):
        conn = _layer_db([(1, 7, "A", -1, 1, 0, 0), (2, 7, "B", -1, 2, 0, 0)])

        class _FailingShiftOps(_SqliteMdbOps):
            def _connection(self, _db_path):
                return _FailingShiftConnection(self._connection_ref)

        class _FailingShiftCursor(_SqliteCursorWrapper):
            def execute(self, query, *params):
                if "[Sequence] = [Sequence] + 1" in query:
                    raise RuntimeError("shift failed")
                return super().execute(query, *params)

        class _FailingShiftConnection(_SqliteConnectionWrapper):
            def cursor(self):
                return _FailingShiftCursor(self._connection)

        with self.assertRaisesRegex(RuntimeError, "shift failed"):
            _FailingShiftOps(conn).insert_layer("bid.mdb", "7", "New", 1)
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (2, 2)])


class LayerSwapAndReadBackPinTests(_StrictTestCase):
    def test_swapping_a_default_layer_with_itself_is_refused_without_writing(self):
        conn = _layer_db(
            [(1, None, "T1", -1, 1, -1, -1), (2, None, "T2", -1, 2, -1, -1)]
        )
        self.assertIsFalse(
            _SqliteMdbOps(conn).swap_default_layer_sequence("bid.mdb", "1", "1")
        )
        self.assertEqual(_layer_rows(conn, "UID, Sequence"), [(1, 1), (2, 2)])

    def test_a_reported_rowcount_makes_a_captured_update_skip_the_read_back(self):
        operations = _LayerOperations()
        operations.cursor.forced_update_rowcount = 2
        self.assertIsTrue(
            operations.update_all_layers_show("bid.mdb", "7", False, ["10", "11"])
        )
        self.assertFalse(
            any(
                sql.startswith("SELECT [UID] FROM [BidLayers]") and "[Show] = ?" in sql
                for sql, _parameters in operations.cursor.executions
            )
        )
