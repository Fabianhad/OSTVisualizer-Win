import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import pyodbc
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    MdbSchemaInspector,
    UnsupportedMdbSchemaError,
)
from tests.helpers.mdb.schema_support import (
    _FakeConnection as _schema_support__FakeConnection,
    _FakeCursor as _schema_support__FakeCursor,
    _FakeResult as _schema_support__FakeResult,
)


class SchemaCompatibilityCompatibilityTests(unittest.TestCase):
    def test_optional_column_uses_existing_column(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidPages"}, {"BidPages": {"Name"}})
        )
        sql = inspector.optional_column("BidPages", "Name", "''")
        self.assertEqual(sql, "[Name]")
        self.assertEqual(inspector.report.missing_optional_columns, set())
        self.assertEqual(
            inspector.optional_column("BidPages", "Name", "''", alias="PageName"),
            "[Name] AS [PageName]",
        )
        self.assertEqual(inspector.report.missing_optional_columns, set())

    def test_optional_column_uses_default_and_records_missing_column(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidPages"}, {"BidPages": {"UID"}})
        )
        sql = inspector.optional_column("BidPages", "Name", "''", alias="PageName")
        self.assertEqual(sql, "'' AS [PageName]")
        self.assertEqual(
            inspector.report.missing_optional_columns,
            {"BidPages.Name"},
        )

    def test_optional_table_missing_records_schema_note(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"Bids"}, {"Bids": {"UID"}})
        )
        self.assertTrue(inspector.optional_table_missing("BidHotLinks"))
        self.assertEqual(
            inspector.report.detected_schema_notes,
            {"missing optional table BidHotLinks"},
        )

    def test_optional_write_skip_logs_once_per_database_column_and_operation(self):
        MdbSchemaInspector._logged_optional_write_skips.clear()
        self.addCleanup(MdbSchemaInspector._logged_optional_write_skips.clear)
        logger = Mock()
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidPages"}, {"BidPages": {"UID"}}),
            logger=logger,
        )
        inspector.log_optional_write_skip("BidPages", "Name", "rename_page")
        inspector.log_optional_write_skip("BidPages", "Name", "rename_page")
        logger.warning.assert_called_once_with(
            "Skipping optional MDB write during %s because %s.%s is unavailable.",
            "rename_page",
            "BidPages",
            "Name",
        )
        inspector.log_optional_write_skip("BidPages", "Name", "other_operation")
        inspector.log_optional_write_skip("BidPages", "Other", "rename_page")
        self.assertEqual(logger.warning.call_count, 3)
        other_database = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidPages"}, {"BidPages": {"UID"}}),
            logger=logger,
        )
        other_database.log_optional_write_skip("BidPages", "Name", "rename_page")
        self.assertEqual(logger.warning.call_count, 4)

    def test_require_column_raises_and_records_missing_required_column(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidLayers"}, {"BidLayers": {"UID"}})
        )
        with self.assertRaises(UnsupportedMdbSchemaError):
            inspector.require_column("BidLayers", "Name")
        self.assertEqual(
            inspector.report.missing_required_columns,
            {"BidLayers.Name"},
        )

    def test_require_column_accepts_existing_column_without_recording_it(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidLayers"}, {"BidLayers": {"Name"}})
        )
        inspector.require_column("BidLayers", "Name")
        self.assertEqual(inspector.report.missing_required_columns, set())

    def test_require_table_raises_for_missing_table_and_accepts_existing_table(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidLayers"}, {"BidLayers": {"UID"}})
        )
        inspector.require_table("BidLayers")
        with self.assertRaisesRegex(
            UnsupportedMdbSchemaError, "missing required table BidPages"
        ):
            inspector.require_table("BidPages")
        with self.assertRaisesRegex(
            UnsupportedMdbSchemaError, "missing required table BidPages"
        ):
            inspector.require_column("BidPages", "Name")
        self.assertEqual(inspector.report.missing_required_columns, set())

    def test_table_exists_falls_back_to_column_lookup_when_not_listed(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection(set(), {"BidPages": {"UID"}})
        )
        self.assertTrue(inspector.table_exists("BidPages"))
        self.assertFalse(inspector.table_exists("BidHotLinks"))
        self.assertTrue(inspector.optional_table_missing("BidHotLinks"))
        self.assertFalse(inspector.optional_table_missing("BidPages"))
        self.assertEqual(
            inspector.report.detected_schema_notes,
            {"missing optional table BidHotLinks"},
        )

    def test_driver_errors_while_listing_tables_and_columns_report_missing(self):
        class _RaisingCursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            @staticmethod
            def tables(**_kwargs):
                raise pyodbc.Error("42000", "tables unavailable")

            @staticmethod
            def columns(**_kwargs):
                raise pyodbc.Error("42000", "columns unavailable")

        class _RaisingConnection:
            @staticmethod
            def cursor():
                return _RaisingCursor()

        inspector = MdbSchemaInspector(_RaisingConnection())
        self.assertFalse(inspector.table_exists("BidPages"))
        self.assertFalse(inspector.column_exists("BidPages", "Name"))
        self.assertEqual(inspector.report.detected_tables, set())
        self.assertEqual(
            inspector.optional_column("BidPages", "Name", "NULL"),
            "NULL AS [Name]",
        )

    def test_order_by_existing_uses_existing_columns_or_fallback(self):
        inspector = MdbSchemaInspector(
            _schema_support__FakeConnection({"BidPages"}, {"BidPages": {"PageNumber"}})
        )
        self.assertEqual(
            inspector.order_by_existing(
                "BidPages", ("FolderUID", "PageNumber"), "[UID]"
            ),
            "[PageNumber]",
        )
        self.assertEqual(
            inspector.order_by_existing("BidPages", ("FolderUID", "Sequence"), "[UID]"),
            "[UID]",
        )
        composite = MdbSchemaInspector(
            _schema_support__FakeConnection(
                {"BidPages"}, {"BidPages": {"FolderUID", "PageNumber"}}
            )
        )
        self.assertEqual(
            composite.order_by_existing(
                "BidPages", ("FolderUID", "PageNumber"), "[UID]"
            ),
            "[FolderUID], [PageNumber]",
        )
