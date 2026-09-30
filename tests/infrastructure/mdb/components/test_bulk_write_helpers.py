import logging
import unittest
from contextlib import contextmanager
import pyodbc
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from tests.helpers.mdb.operations import (
    _RecordingConnection,
    _RecordingCursor,
    _RecordingSchema,
    _RecordingTakeoffOps,
)


class BulkWriteHelpersPersistenceTests(unittest.TestCase):
    def test_takeoff_bulk_uid_normalization_deduplicates_in_order(self):
        ops = _RecordingTakeoffOps()
        self.assertEqual(
            ops._normalize_int_uids(["2", 1, "2", "003"], "takeoff"),
            [2, 1, 3],
        )
        with self.assertRaises(ValueError):
            ops._normalize_int_uids(["1", "bad"], "takeoff")
        with self.assertRaises(ValueError):
            ops._normalize_int_uids("123", "takeoff")
