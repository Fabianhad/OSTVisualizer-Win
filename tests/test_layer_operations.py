import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)


class _Cursor:
    def __init__(self):
        self.executions = []

    def execute(self, sql, *parameters):
        self.executions.append((" ".join(sql.split()), parameters))
        return self

    def fetchall(self):
        return [
            SimpleNamespace(UID=10, Sequence=1),
            SimpleNamespace(UID=11, Sequence=2),
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
        updates = operations.cursor.executions[1:]
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
