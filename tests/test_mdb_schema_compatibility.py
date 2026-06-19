import unittest
from types import SimpleNamespace

from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    MdbSchemaInspector,
    UnsupportedMdbSchemaError,
)
from ost_visualizer.domain import ost_schema as domain_ost_schema
from ost_visualizer.infrastructure.mdb import schema_contract


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeCursor:
    def __init__(self, tables, columns_by_table):
        self._tables = tables
        self._columns_by_table = columns_by_table

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def tables(self, tableType=None):
        self.table_type = tableType
        return _FakeResult(
            [SimpleNamespace(table_name=table_name) for table_name in self._tables]
        )

    def columns(self, table):
        return _FakeResult(
            [
                SimpleNamespace(column_name=column_name)
                for column_name in self._columns_by_table.get(table, set())
            ]
        )


class _FakeConnection:
    def __init__(self, tables, columns_by_table):
        self._tables = set(tables)
        self._columns_by_table = {
            table: set(columns) for table, columns in columns_by_table.items()
        }

    def cursor(self):
        return _FakeCursor(self._tables, self._columns_by_table)


class MdbSchemaCompatibilityTests(unittest.TestCase):
    def test_domain_schema_compatibility_copy_matches_infrastructure_contract(self):
        self.assertEqual(domain_ost_schema.BID_SECTIONS, schema_contract.BID_SECTIONS)
        self.assertEqual(
            domain_ost_schema.BID_TAIL_SECTIONS,
            schema_contract.BID_TAIL_SECTIONS,
        )
        self.assertEqual(
            domain_ost_schema.GLOBAL_SECTIONS,
            schema_contract.GLOBAL_SECTIONS,
        )
        self.assertEqual(domain_ost_schema.PAGE_SECTIONS, schema_contract.PAGE_SECTIONS)
        self.assertEqual(
            domain_ost_schema.RAW_BID_TABLES,
            schema_contract.RAW_BID_TABLES,
        )
        self.assertEqual(
            domain_ost_schema.RAW_GLOBAL_TABLES,
            schema_contract.RAW_GLOBAL_TABLES,
        )
        self.assertEqual(domain_ost_schema.singular("BidLayers"), "BidLayer")
        self.assertEqual(
            domain_ost_schema.singular("BidLayers"),
            schema_contract.singular("BidLayers"),
        )

    def test_optional_column_uses_existing_column(self):
        inspector = MdbSchemaInspector(
            _FakeConnection({"BidPages"}, {"BidPages": {"Name"}})
        )

        sql = inspector.optional_column("BidPages", "Name", "''")

        self.assertEqual(sql, "[Name]")
        self.assertEqual(inspector.report.missing_optional_columns, set())

    def test_optional_column_uses_default_and_records_missing_column(self):
        inspector = MdbSchemaInspector(
            _FakeConnection({"BidPages"}, {"BidPages": {"UID"}})
        )

        sql = inspector.optional_column("BidPages", "Name", "''", alias="PageName")

        self.assertEqual(sql, "'' AS [PageName]")
        self.assertEqual(
            inspector.report.missing_optional_columns,
            {"BidPages.Name"},
        )

    def test_optional_table_missing_records_schema_note(self):
        inspector = MdbSchemaInspector(_FakeConnection({"Bids"}, {"Bids": {"UID"}}))

        self.assertTrue(inspector.optional_table_missing("BidHotLinks"))

        self.assertEqual(
            inspector.report.detected_schema_notes,
            {"missing optional table BidHotLinks"},
        )

    def test_require_column_raises_and_records_missing_required_column(self):
        inspector = MdbSchemaInspector(
            _FakeConnection({"BidLayers"}, {"BidLayers": {"UID"}})
        )

        with self.assertRaises(UnsupportedMdbSchemaError):
            inspector.require_column("BidLayers", "Name")

        self.assertEqual(
            inspector.report.missing_required_columns,
            {"BidLayers.Name"},
        )

    def test_order_by_existing_uses_existing_columns_or_fallback(self):
        inspector = MdbSchemaInspector(
            _FakeConnection({"BidPages"}, {"BidPages": {"PageNumber"}})
        )

        self.assertEqual(
            inspector.order_by_existing("BidPages", ("FolderUID", "PageNumber"), "[UID]"),
            "[PageNumber]",
        )
        self.assertEqual(
            inspector.order_by_existing("BidPages", ("FolderUID", "Sequence"), "[UID]"),
            "[UID]",
        )


if __name__ == "__main__":
    unittest.main()
