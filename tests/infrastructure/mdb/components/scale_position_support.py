import unittest
from types import SimpleNamespace
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.utils.position import parse_position
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    TEXT_POSITION_TABLES,
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)


class _Schema:
    def __init__(self, position_table):
        self.position_table = position_table

    def optional_table_missing(self, _table):
        return False

    def column_exists(self, table, column):
        return table == self.position_table and column in (
            "UID",
            "BidPageUID",
            "Position",
        )


class _Cursor:
    def __init__(self, table, rows):
        self.table = table
        self.rows = list(rows)
        self.updates = []

    def execute(self, query, *params):
        if query.startswith(f"UPDATE [{self.table}]"):
            self.updates.append((params[0], params[1]))

    def fetchall(self):
        return list(self.rows)


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args)


class _PageOps(PageOperationsMixin):
    def __init__(self):
        self.logger = _Logger()

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False
