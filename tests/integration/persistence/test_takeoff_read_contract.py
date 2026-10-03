import unittest
from unittest.mock import patch
import pyodbc
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from tests.infrastructure.mdb.components.takeoff_hydration_support import (
    _Cursor as _takeoff_hydration_support__Cursor,
    _hydrate as _takeoff_hydration_support__hydrate,
)


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_deleted_record_read_error_never_becomes_empty_takeoff_family(self):
        # Both concrete readers (with their real read-error recorders) share the
        # Takeoff hydration; the cursor/schema are the repo's explicit stand-ins.
        for reader in (
            MdbReader.__new__(MdbReader),
            SqlProjectReader.__new__(SqlProjectReader),
        ):
            # Positive control: the same stand-in connection hydrates the row.
            hydrated = _takeoff_hydration_support__hydrate(reader)
            self.assertEqual(
                (hydrated.uid, hydrated.page_uid, hydrated.condition_uid),
                ("4485", "20", "10"),
            )
            for message in ("HY109", "Record is deleted"):
                with self.subTest(reader=type(reader).__name__, message=message):
                    with patch.object(
                        _takeoff_hydration_support__Cursor,
                        "fetchall",
                        side_effect=pyodbc.Error(message),
                    ):
                        with self.assertRaisesRegex(pyodbc.Error, message):
                            _takeoff_hydration_support__hydrate(reader)
