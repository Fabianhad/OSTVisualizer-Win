import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    SettingsReaderMixin,
)


class _FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def tables(self, tableType=None):
        self._rows = [
            SimpleNamespace(table_name=table_name)
            for table_name in self._connection.columns_by_table
        ]
        return self

    def columns(self, table=None):
        self._rows = [
            SimpleNamespace(column_name=column_name)
            for column_name in self._connection.columns_by_table.get(table, ())
        ]
        return self

    def execute(self, query, *params):
        table = query.split("FROM [", 1)[1].split("]", 1)[0]
        bid_uid = int(params[0]) if params else None
        rows = []
        for row in self._connection.rows_by_table.get(table, ()):
            if bid_uid is not None and int(row.BidUID) != bid_uid:
                continue
            rows.append(row)
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, columns_by_table, rows_by_table):
        self.columns_by_table = columns_by_table
        self.rows_by_table = rows_by_table

    def cursor(self):
        return _FakeCursor(self)


class _LayerUsageReader(SettingsReaderMixin):
    def __init__(self, connection):
        self._connection_obj = connection
        self.logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)

    @contextmanager
    def _connection(self, _file_path):
        yield self._connection_obj


class LayerUsageReaderTests(unittest.TestCase):
    def test_layer_uids_in_use_includes_condition_and_annotation_tables(self):
        connection = _FakeConnection(
            columns_by_table={
                "BidConditions": {"BidUID", "BidLayerUID"},
                "BidAnnotationRects": {"BidUID", "BidLayerUID"},
                "BidHotLinks": {"BidUID", "BidLayerUID"},
                "BidTexts": {"BidUID", "BidLayerUID"},
            },
            rows_by_table={
                "BidConditions": [
                    SimpleNamespace(BidUID=7, BidLayerUID=101),
                    SimpleNamespace(BidUID=8, BidLayerUID=102),
                ],
                "BidAnnotationRects": [
                    SimpleNamespace(BidUID=7, BidLayerUID=201),
                    SimpleNamespace(BidUID=8, BidLayerUID=202),
                ],
                "BidHotLinks": [
                    SimpleNamespace(BidUID=7, BidLayerUID=None),
                ],
                "BidTexts": [
                    SimpleNamespace(BidUID=7, BidLayerUID=301),
                ],
            },
        )
        reader = _LayerUsageReader(connection)
        self.assertEqual(
            reader.get_layer_uids_in_use("bid.mdb", "7"),
            {"101", "201", "301"},
        )


if __name__ == "__main__":
    unittest.main()
