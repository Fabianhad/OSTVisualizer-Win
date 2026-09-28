import unittest
from collections import namedtuple
from contextlib import contextmanager
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)


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


if __name__ == "__main__":
    unittest.main()
