import logging
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
        self.assertIs(inspector.optional_table_missing("BidHotLinks"), True)
        self.assertIs(inspector.optional_table_missing("Bids"), False)
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
        with self.assertRaisesRegex(
            UnsupportedMdbSchemaError,
            r"^This OST database is missing required column BidLayers\.Name "
            r"and cannot be loaded\.$",
        ):
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
            UnsupportedMdbSchemaError,
            r"^This OST database is missing required table BidPages "
            r"and cannot be loaded\.$",
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
        self.assertIs(inspector.table_exists("BidPages"), True)
        self.assertIs(inspector.table_exists("BidHotLinks"), False)
        self.assertIs(inspector.optional_table_missing("BidHotLinks"), True)
        self.assertIs(inspector.optional_table_missing("BidPages"), False)
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
        self.assertIs(inspector.table_exists("BidPages"), False)
        self.assertIs(inspector.column_exists("BidPages", "Name"), False)
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

    def test_empty_table_listing_is_cached_and_not_requeried(self):
        connection = _RecordingConnection([], {})
        inspector = MdbSchemaInspector(connection)
        self.assertIs(inspector.optional_table_missing("BidHotLinks"), True)
        self.assertIs(inspector.table_exists("BidPages"), False)
        self.assertEqual(connection.table_calls, [{"tableType": "TABLE"}])
        self.assertEqual(inspector.report.detected_tables, set())

    def test_order_by_existing_keeps_the_requested_priority_order(self):
        inspector = MdbSchemaInspector(
            _RecordingConnection(
                ["BidPages"], {"BidPages": {"Alpha", "Sequence", "FolderUID"}}
            )
        )
        self.assertEqual(
            inspector.order_by_existing(
                "BidPages", ("Sequence", "Missing", "FolderUID", "Alpha"), "[UID]"
            ),
            "[Sequence], [FolderUID], [Alpha]",
        )

    def test_unsupported_schema_error_is_a_runtime_error_subclass(self):
        self.assertTrue(issubclass(UnsupportedMdbSchemaError, RuntimeError))


class _RecordingCursor:
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self._connection.closed_cursors += 1
        return False

    def tables(self, **kwargs):
        self._connection.table_calls.append(kwargs)
        return _schema_support__FakeResult(
            [SimpleNamespace(table_name=name) for name in self._connection.tables]
        )

    def columns(self, **kwargs):
        self._connection.column_calls.append(kwargs)
        return _schema_support__FakeResult(
            [
                SimpleNamespace(column_name=name)
                for name in self._connection.columns_by_table.get(kwargs["table"], ())
            ]
        )


class _RecordingConnection:
    def __init__(self, tables, columns_by_table, database_name="<unset>"):
        self.tables = list(tables)
        self.columns_by_table = columns_by_table
        self.database_name = database_name
        self.table_calls = []
        self.column_calls = []
        self.getinfo_calls = []
        self.closed_cursors = 0

    def cursor(self):
        return _RecordingCursor(self)

    def getinfo(self, info_type):
        self.getinfo_calls.append(info_type)
        if isinstance(self.database_name, BaseException):
            raise self.database_name
        return self.database_name


class SchemaInspectorCatalogQueryTests(unittest.TestCase):
    def test_table_listing_is_restricted_to_user_tables_and_cached(self):
        connection = _RecordingConnection(["BidPages", "Bids"], {})
        inspector = MdbSchemaInspector(connection)
        self.assertIs(inspector.table_exists("BidPages"), True)
        self.assertIs(inspector.table_exists("Bids"), True)
        self.assertEqual(connection.table_calls, [{"tableType": "TABLE"}])
        self.assertEqual(connection.column_calls, [])
        self.assertEqual(inspector.report.detected_tables, {"BidPages", "Bids"})
        self.assertEqual(connection.closed_cursors, 1)

    def test_column_listing_uses_table_keyword_and_is_cached_per_table(self):
        connection = _RecordingConnection(
            [], {"BidPages": {"UID", "Name"}, "BidLayers": {"UID"}}
        )
        inspector = MdbSchemaInspector(connection)
        self.assertEqual(inspector.get_columns("BidPages"), {"UID", "Name"})
        self.assertIs(inspector.column_exists("BidPages", "Name"), True)
        self.assertIs(inspector.column_exists("BidPages", "Missing"), False)
        self.assertEqual(inspector.get_columns("BidLayers"), {"UID"})
        self.assertEqual(
            connection.column_calls, [{"table": "BidPages"}, {"table": "BidLayers"}]
        )
        self.assertEqual(connection.closed_cursors, 2)

    def test_empty_column_listing_is_cached_and_does_not_requery(self):
        connection = _RecordingConnection([], {})
        inspector = MdbSchemaInspector(connection)
        self.assertEqual(inspector.get_columns("Ghost"), set())
        self.assertEqual(inspector.get_columns("Ghost"), set())
        self.assertEqual(connection.column_calls, [{"table": "Ghost"}])

    def test_unlisted_table_is_found_through_its_columns(self):
        connection = _RecordingConnection([], {"BidPages": {"UID"}})
        inspector = MdbSchemaInspector(connection)
        self.assertIs(inspector.table_exists("BidPages"), True)
        self.assertEqual(inspector.report.detected_tables, set())
        inspector.require_table("BidPages")

    def test_non_odbc_errors_while_listing_are_not_swallowed(self):
        class _BrokenCursor(_RecordingCursor):
            def tables(self, **kwargs):
                raise RuntimeError("connection lost")

        class _BrokenConnection(_RecordingConnection):
            def cursor(self):
                return _BrokenCursor(self)

        inspector = MdbSchemaInspector(_BrokenConnection([], {}))
        with self.assertRaisesRegex(RuntimeError, "connection lost"):
            inspector.table_exists("BidPages")
        self.assertEqual(inspector.report.detected_tables, set())

    def test_non_odbc_errors_while_listing_columns_are_not_swallowed(self):
        class _FlakyCursor(_RecordingCursor):
            def columns(self, **kwargs):
                if not self._connection.column_calls:
                    self._connection.column_calls.append(kwargs)
                    raise RuntimeError("connection lost")
                return super().columns(**kwargs)

        class _FlakyConnection(_RecordingConnection):
            def cursor(self):
                return _FlakyCursor(self)

        connection = _FlakyConnection([], {"BidPages": {"UID"}})
        inspector = MdbSchemaInspector(connection)
        with self.assertRaisesRegex(RuntimeError, "connection lost"):
            inspector.get_columns("BidPages")
        self.assertEqual(connection.closed_cursors, 1)
        self.assertEqual(inspector.report.missing_required_columns, set())
        # The failure was not cached as "table has no columns": asking again
        # queries the catalog again and now sees the real columns.
        self.assertEqual(inspector.get_columns("BidPages"), {"UID"})
        self.assertEqual(len(connection.column_calls), 2)

    def test_optional_column_without_alias_defaults_to_column_name_alias(self):
        inspector = MdbSchemaInspector(
            _RecordingConnection(["BidPages"], {"BidPages": {"UID"}})
        )
        self.assertEqual(
            inspector.optional_column("BidPages", "Name", "NULL"),
            "NULL AS [Name]",
        )
        self.assertEqual(
            inspector.optional_column("BidPages", "UID", "0", alias="UID"), "[UID]"
        )
        self.assertEqual(inspector.report.missing_optional_columns, {"BidPages.Name"})


class SchemaInspectorDatabaseKeyTests(unittest.TestCase):
    def setUp(self):
        MdbSchemaInspector._logged_optional_write_skips.clear()
        self.addCleanup(MdbSchemaInspector._logged_optional_write_skips.clear)

    def test_database_key_is_the_odbc_database_name_when_available(self):
        connection = _RecordingConnection([], {}, database_name="C:/data/ost.mdb")
        inspector = MdbSchemaInspector(connection)
        self.assertEqual(inspector._database_key(), "C:/data/ost.mdb")
        self.assertEqual(connection.getinfo_calls, [pyodbc.SQL_DATABASE_NAME])

    def test_database_key_falls_back_to_connection_identity(self):
        for label, database_name in (
            ("empty", ""),
            ("none", None),
            ("attribute", AttributeError("no getinfo")),
            ("odbc", pyodbc.Error("HY000", "no info")),
        ):
            with self.subTest(label):
                connection = _RecordingConnection([], {}, database_name=database_name)
                inspector = MdbSchemaInspector(connection)
                self.assertEqual(inspector._database_key(), str(id(connection)))

    def test_database_key_without_getinfo_uses_connection_identity(self):
        connection = _schema_support__FakeConnection(set(), {})
        inspector = MdbSchemaInspector(connection)
        self.assertEqual(inspector._database_key(), str(id(connection)))

    def test_other_getinfo_errors_are_not_swallowed(self):
        logger = Mock()
        connection = _RecordingConnection(
            [], {}, database_name=RuntimeError("driver crashed")
        )
        inspector = MdbSchemaInspector(connection, logger=logger)
        with self.assertRaisesRegex(RuntimeError, "driver crashed"):
            inspector.log_optional_write_skip("BidPages", "Name", "rename")
        logger.warning.assert_not_called()
        self.assertEqual(MdbSchemaInspector._logged_optional_write_skips, set())

    def test_database_key_stringifies_non_string_names(self):
        inspector = MdbSchemaInspector(
            _RecordingConnection([], {}, database_name=12345)
        )
        self.assertEqual(inspector._database_key(), "12345")

    def test_same_named_database_logs_each_skip_once_across_connections(self):
        logger = Mock()
        first = MdbSchemaInspector(
            _RecordingConnection([], {}, database_name="ost.mdb"), logger=logger
        )
        second = MdbSchemaInspector(
            _RecordingConnection([], {}, database_name="ost.mdb"), logger=logger
        )
        other = MdbSchemaInspector(
            _RecordingConnection([], {}, database_name="other.mdb"), logger=logger
        )
        first.log_optional_write_skip("BidPages", "Name", "rename")
        second.log_optional_write_skip("BidPages", "Name", "rename")
        self.assertEqual(logger.warning.call_count, 1)
        other.log_optional_write_skip("BidPages", "Name", "rename")
        self.assertEqual(logger.warning.call_count, 2)
        self.assertEqual(
            MdbSchemaInspector._logged_optional_write_skips,
            {
                "ost.mdb:BidPages.Name:rename",
                "other.mdb:BidPages.Name:rename",
            },
        )

    def test_unnamed_databases_are_distinguished_by_connection_identity(self):
        logger = Mock()
        first = MdbSchemaInspector(
            _RecordingConnection([], {}, database_name=""), logger=logger
        )
        second = MdbSchemaInspector(
            _RecordingConnection([], {}, database_name=""), logger=logger
        )
        first.log_optional_write_skip("BidPages", "Name", "rename")
        second.log_optional_write_skip("BidPages", "Name", "rename")
        self.assertEqual(logger.warning.call_count, 2)

    def test_default_logger_is_the_module_logger(self):
        inspector = MdbSchemaInspector(_RecordingConnection([], {}))
        self.assertIs(
            inspector.logger,
            logging.getLogger("ost_visualizer.infrastructure.mdb.schema_compatibility"),
        )
