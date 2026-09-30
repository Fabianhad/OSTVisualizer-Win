import unittest
from unittest.mock import patch
import pyodbc
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from tests.infrastructure.mdb.components.takeoff_hydration_support import (
    _Connection as _takeoff_hydration_support__Connection,
    _Cursor as _takeoff_hydration_support__Cursor,
    _Schema as _takeoff_hydration_support__Schema,
    _hydrate as _takeoff_hydration_support__hydrate,
)


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_deleted_record_read_error_never_becomes_empty_takeoff_family(self):
        for reader in (
            BidDataReaderMixin(),
            SqlProjectReader.__new__(SqlProjectReader),
        ):
            for message in ("HY109", "Record is deleted"):
                with self.subTest(reader=type(reader).__name__, message=message):
                    reader._record_caught_read_error = lambda _error: False
                    with patch.object(
                        _takeoff_hydration_support__Cursor,
                        "fetchall",
                        side_effect=pyodbc.Error(message),
                    ):
                        with self.assertRaises(pyodbc.Error):
                            _takeoff_hydration_support__hydrate(reader)
