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

    def execute(self, sql, *parameters):
        self._last_sql = " ".join(sql.split())
        self.executions.append((self._last_sql, parameters))
        return self

    def fetchall(self):
        if self._last_sql.startswith("SELECT [UID], [BidUID] FROM [BidLayers]"):
            return [(10, 7), (11, 7)]
        if self._last_sql.startswith("SELECT [UID] FROM [Bids]"):
            return [(7,)]
        row_type = namedtuple("LayerRow", ("UID", "Sequence"))
        return [
            row_type(10, 1),
            row_type(11, 2),
        ]


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _Schema:
    def require_column(self, _table, _column):
        pass


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
