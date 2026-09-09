import unittest
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.settings_cardinality import (
    GlobalSettingsCardinalityError,
    fetch_optional_global_settings_row,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter


class _RecordingCursor:
    def __init__(self, rows):
        self._rows = iter(rows)
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        return self

    def fetchone(self):
        return next(self._rows, None)


class GlobalSettingsCardinalityTests(unittest.TestCase):
    @staticmethod
    def _routed_writer():
        return DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            object(),
            object(),
        )

    def test_access_router_supplies_plain_settings_table_reference(self):
        writer = self._routed_writer()
        cursor = _RecordingCursor([(27,)])
        with writer._backend_scope("normal.mdb"):
            row = fetch_optional_global_settings_row(
                cursor,
                "[NextBidNo]",
                table_sql=writer._global_settings_read_table_sql(),
            )
        self.assertEqual(row, (27,))
        self.assertEqual(
            cursor.statements,
            ["SELECT [NextBidNo] FROM [Settings]"],
        )
        self.assertNotIn("WITH OWNERACCESS OPTION", cursor.statements[0].upper())
        self.assertNotIn("WITH (", cursor.statements[0].upper())

    def test_sql_settings_reference_retains_transaction_lock_hint(self):
        cursor = _RecordingCursor([(31,)])
        row = fetch_optional_global_settings_row(
            cursor,
            "[NextBidNo]",
            table_sql=SqlProjectWriter._global_settings_read_table_sql(),
        )
        self.assertEqual(row, (31,))
        self.assertEqual(
            cursor.statements,
            ["SELECT [NextBidNo] FROM [dbo].[Settings] " "WITH (UPDLOCK, HOLDLOCK)"],
        )

    def test_zero_global_settings_rows_remain_valid(self):
        cursor = _RecordingCursor([])
        row = fetch_optional_global_settings_row(cursor, "[NextBidNo]")
        self.assertIsNone(row)
        self.assertEqual(
            cursor.statements,
            ["SELECT [NextBidNo] FROM [Settings]"],
        )

    def test_one_global_settings_row_is_returned(self):
        cursor = _RecordingCursor([(42,)])
        row = fetch_optional_global_settings_row(cursor, "[NextBidNo]")
        self.assertEqual(row, (42,))

    def test_duplicate_global_settings_rows_still_reject(self):
        cursor = _RecordingCursor([(42,), (43,)])
        with self.assertRaises(GlobalSettingsCardinalityError):
            fetch_optional_global_settings_row(cursor, "[NextBidNo]")


if __name__ == "__main__":
    unittest.main()
