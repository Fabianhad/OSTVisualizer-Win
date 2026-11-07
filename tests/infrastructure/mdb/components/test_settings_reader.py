import pyodbc
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetPage,
    JobStatus,
)
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.mdb.schema_compatibility import MdbSchemaInspector
from types import SimpleNamespace
from contextlib import contextmanager
from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    SettingsReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
import unittest
from unittest import mock
import sqlite3
import logging
from ost_visualizer.infrastructure.mdb.components.constants import (
    LAYER_REFERENCE_TABLES,
)
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    _clean_optional_text,
)
import os
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.cover_sheet.path_support import (
    _app as _path_support__app,
)
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    CyclicBidOwnedReferenceError,
)
from ost_visualizer.infrastructure.database.settings_cardinality import (
    GlobalSettingsCardinalityError,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def tables(self, tableType=None):
        del tableType
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
        self.logger = SimpleNamespace(warning=lambda *_args, **_call_options: None)

    @contextmanager
    def _connection(self, _file_path):
        yield self._connection_obj

    def _schema(self, connection):
        return MdbSchemaInspector(connection, self.logger)

    def _record_caught_read_error(self, _exc):
        return False


class SettingsReaderPersistenceTests(unittest.TestCase):
    def test_used_employee_uids_include_all_direct_bid_roles(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, EstimatorUID INTEGER, "
            "PrManagerUID INTEGER, JobSiteManagerUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 10, 20, 30)")
        conn.execute("INSERT INTO Bids VALUES (2, 10, NULL, 40)")
        conn.execute("INSERT INTO Bids VALUES (3, NULL, NULL, NULL)")
        used = SettingsReaderMixin._parse_used_employee_uids(
            _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn)
        )
        self.assertEqual(used, {"10", "20", "30", "40"})

    def test_used_employee_uids_ignore_absent_role_columns_and_table(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER PRIMARY KEY, EstimatorUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 10)")
        ops = _SqliteMdbOps(conn)
        self.assertEqual(
            SettingsReaderMixin._parse_used_employee_uids(
                ops, _SqliteConnectionWrapper(conn)
            ),
            {"10"},
        )
        conn.execute("DROP TABLE Bids")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        self.assertEqual(
            SettingsReaderMixin._parse_used_employee_uids(
                ops, _SqliteConnectionWrapper(conn)
            ),
            set(),
        )
        conn.execute("DROP TABLE Bids")
        self.assertEqual(
            SettingsReaderMixin._parse_used_employee_uids(
                ops, _SqliteConnectionWrapper(conn)
            ),
            set(),
        )

    def test_cover_sheet_reader_rejects_duplicate_employee_and_pay_class_uids(self):
        class Reader(SettingsReaderMixin, _SqliteMdbOps):
            def _select_all_unfiltered(self, connection, table):
                return MdbReader._select_all_unfiltered(self, connection, table)

            def _select_all_columns(self, schema, table):
                return MdbReader._select_all_columns(self, schema, table)

        fixtures = (
            (
                "Employees",
                "CREATE TABLE Employees (UID INTEGER, FirstName TEXT)",
                "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                "INSERT INTO Employees VALUES (7, ?)",
                (("First",), ("Conflicting",)),
            ),
            (
                "PayClasses",
                "CREATE TABLE Employees (UID INTEGER, FirstName TEXT)",
                "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                "INSERT INTO PayClasses VALUES (7, ?)",
                (("First",), ("Conflicting",)),
            ),
        )
        for table, employees_ddl, pay_classes_ddl, insert_sql, rows in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(employees_ddl)
                conn.execute(pay_classes_ddl)
                conn.executemany(insert_sql, rows)
                reader = Reader(conn)
                with self.assertRaisesRegex(
                    RuntimeError,
                    f"{table} contains duplicate UID 7",
                ):
                    reader._parse_employees_and_pay_classes(
                        _SqliteConnectionWrapper(conn)
                    )

    def test_cover_sheet_reader_accepts_same_uid_in_distinct_master_tables(self):
        class Reader(SettingsReaderMixin, _SqliteMdbOps):
            def _select_all_unfiltered(self, connection, table):
                return MdbReader._select_all_unfiltered(self, connection, table)

            def _select_all_columns(self, schema, table):
                return MdbReader._select_all_columns(self, schema, table)

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER, FirstName TEXT)")
        conn.execute("CREATE TABLE PayClasses (UID INTEGER, Name TEXT)")
        conn.execute("INSERT INTO Employees VALUES (7, 'Ada')")
        conn.execute("INSERT INTO PayClasses VALUES (7, 'Journeyman')")
        employees, pay_classes = Reader(conn)._parse_employees_and_pay_classes(
            _SqliteConnectionWrapper(conn)
        )
        self.assertEqual([(e.uid, e.first_name) for e in employees], [("7", "Ada")])
        self.assertEqual([(p.uid, p.name) for p in pay_classes], [("7", "Journeyman")])


class OptionalTextCompatibilityTests(unittest.TestCase):
    def test_optional_text_consolidation_preserves_all_old_sentinel_behavior(self):
        unchanged_values = (
            "",
            "   ",
            "null",
            " NULL ",
            "already clean",
            "embedded\x00null",
            b"bytes",
            0,
            42,
        )
        self.assertEqual(_clean_optional_text(None), "")
        self.assertEqual(_clean_optional_text("NULL"), "")
        for value in unchanged_values:
            with self.subTest(value=value):
                self.assertIs(_clean_optional_text(value), value)


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

    def test_layer_uids_in_use_skips_missing_tables_and_layerless_columns(self):
        connection = _FakeConnection(
            columns_by_table={
                "BidConditions": {"BidUID", "BidLayerUID"},
                "BidTexts": {"BidUID"},
            },
            rows_by_table={
                "BidConditions": [SimpleNamespace(BidUID=7, BidLayerUID=101)],
                "BidTexts": [SimpleNamespace(BidUID=7)],
            },
        )
        reader = _LayerUsageReader(connection)
        self.assertEqual(reader.get_layer_uids_in_use("bid.mdb", "7"), {"101"})
        self.assertEqual(reader.get_layer_uids_in_use("bid.mdb", "8"), set())


class SettingsReaderCoverSheetPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_cover_sheet_reader_loads_persisted_multi_page_count(self):
        class Schema:
            @staticmethod
            def require_column(_table, _column):
                pass

            @staticmethod
            def optional_table_missing(table):
                return table == "BidPageFolders"

            @staticmethod
            def optional_column(_table, column, _fallback):
                return f"[{column}]"

            @staticmethod
            def order_by_existing(_table, _columns, fallback):
                return fallback

        class Cursor:
            def __init__(self):
                self.query = ""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, *_args):
                self.query = query

            def fetchall(self):
                return [
                    SimpleNamespace(
                        UID=1,
                        Name="Plan",
                        SheetNo="A1",
                        Width=42.0,
                        Height=30.0,
                        ScaleFactor1=0.125,
                        ScaleFactor2=12.0,
                        ImagePath="plan.pdf",
                        OverlayImagePath=None,
                        Index1=3,
                        MultiPageCount=7,
                        Show=2,
                        BidPageFolderUID=None,
                    )
                ]

        class Connection:
            def __init__(self):
                self.cursors = []

            def cursor(self):
                cursor = Cursor()
                self.cursors.append(cursor)
                return cursor

        class Reader(SettingsReaderMixin):
            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _record_caught_read_error(_error):
                return False

        connection = Connection()
        folders, pages = Reader()._query_cover_sheet_pages(connection, "7")
        self.assertEqual(folders, {})
        self.assertEqual(
            pages,
            [
                CoverSheetPage(
                    uid="1",
                    sheet_no="A1",
                    name="Plan",
                    width=42.0,
                    height=30.0,
                    scale_factor1=0.125,
                    scale_factor2=12.0,
                    image_path="plan.pdf",
                    overlay_image_path="",
                    index=3,
                    show_mode=2,
                    multi_page_count=7,
                )
            ],
        )
        self.assertIn("[MultiPageCount]", connection.cursors[-1].query)

    def test_cover_sheet_reader_rejects_page_folder_cycle(self):
        class Schema:
            @staticmethod
            def require_column(_table, _column):
                pass

            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def optional_column(_table, column, _fallback):
                return f"[{column}]"

            @staticmethod
            def order_by_existing(_table, _columns, fallback):
                return fallback

        class Cursor:
            def __init__(self, folder_rows):
                self.query = ""
                self.folder_rows = folder_rows

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, *_args):
                self.query = query

            def fetchall(self):
                if "FROM [BidPageFolders]" in self.query:
                    return self.folder_rows
                return []

        class Connection:
            def __init__(self, folder_rows):
                self.folder_rows = folder_rows

            def cursor(self):
                return Cursor(self.folder_rows)

        class Reader(SettingsReaderMixin):
            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _record_caught_read_error(_error):
                return False

        cycles = {
            "two-node": [
                SimpleNamespace(UID=7, Name="A", ParentUID=8),
                SimpleNamespace(UID=8, Name="B", ParentUID=7),
            ],
            "self-parent": [SimpleNamespace(UID=9, Name="C", ParentUID=9)],
        }
        for label, rows in cycles.items():
            with self.subTest(cycle=label):
                with self.assertRaisesRegex(
                    CyclicBidOwnedReferenceError,
                    rf"BidPageFolders\.UID={rows[0].UID} participates in a "
                    "ParentUID cycle",
                ):
                    Reader()._query_cover_sheet_pages(Connection(rows), "7")
        folders, pages = Reader()._query_cover_sheet_pages(
            Connection(
                [
                    SimpleNamespace(UID=7, Name="A", ParentUID=None),
                    SimpleNamespace(UID=8, Name="B", ParentUID=7),
                ]
            ),
            "7",
        )
        self.assertEqual(pages, [])
        self.assertEqual(list(folders), ["7"])
        self.assertEqual(list(folders["7"].subfolders), ["8"])


class SettingsReaderCompatibilityTests(unittest.TestCase):
    def test_settings_reader_keeps_missing_legacy_table_readable(self):
        class Schema:
            @staticmethod
            def optional_table_missing(table):
                return table == "Settings"

        class Reader(MdbReader):
            @staticmethod
            def _schema(_connection):
                return Schema()

        defaults = Reader()._parse_settings_defaults(object())
        self.assertEqual(
            defaults,
            {
                "scale_style": 1,
                "scale_factor1": 0.125,
                "scale_factor2": 12.0,
                "page_width": 42.0,
                "page_height": 30.0,
                "measure_base": 0,
                "takeoff_increments": 1.0,
                "next_bid_no": 1,
            },
        )

    def test_settings_reader_rejects_multiple_global_settings_rows(self):
        class Cursor:
            def __init__(self):
                self._index = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                pass

            def fetchone(self):
                rows = (
                    SimpleNamespace(
                        ScaleStyle=1,
                        ScaleFactor1=None,
                        ScaleFactor2=None,
                        PageWidth=None,
                        PageHeight=None,
                        MeasureBase=None,
                        TakeoffIncrements=None,
                        NextBidNo=7,
                    ),
                ) * 2
                if self._index < len(rows):
                    row = rows[self._index]
                    self._index += 1
                    return row
                return None

        class Connection:
            @staticmethod
            def cursor():
                return Cursor()

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def optional_column(_table, column, _default):
                return f"[{column}]"

        class Reader(MdbReader):
            @staticmethod
            def _schema(_connection):
                return Schema()

        with self.assertRaisesRegex(
            GlobalSettingsCardinalityError,
            "Settings has multiple rows; expected at most one",
        ):
            Reader()._parse_settings_defaults(Connection())

    def test_settings_reader_defaults_null_optional_fields_from_one_row(self):
        class Cursor:
            def __init__(self):
                self._rows = iter(
                    (
                        SimpleNamespace(
                            ScaleStyle=None,
                            ScaleFactor1=None,
                            ScaleFactor2=None,
                            PageWidth=None,
                            PageHeight=None,
                            MeasureBase=None,
                            TakeoffIncrements=None,
                            NextBidNo=9,
                        ),
                        None,
                    )
                )

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                pass

            def fetchone(self):
                return next(self._rows)

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def optional_column(_table, column, _default):
                return f"[{column}]"

        class Reader(MdbReader):
            @staticmethod
            def _schema(_connection):
                return Schema()

        defaults = Reader()._parse_settings_defaults(
            SimpleNamespace(cursor=lambda: Cursor()),
        )
        self.assertEqual(
            defaults,
            {
                "scale_style": 1,
                "scale_factor1": 0.125,
                "scale_factor2": 12.0,
                "page_width": 42.0,
                "page_height": 30.0,
                "measure_base": 0,
                "takeoff_increments": 1.0,
                "next_bid_no": 9,
            },
        )

    def test_settings_reader_returns_persisted_values_from_one_row(self):
        class Cursor:
            def __init__(self):
                self._rows = iter(
                    (
                        SimpleNamespace(
                            ScaleStyle=3,
                            ScaleFactor1=0.5,
                            ScaleFactor2=24.0,
                            PageWidth=36.0,
                            PageHeight=24.0,
                            MeasureBase=2,
                            TakeoffIncrements=0.5,
                            NextBidNo=15,
                        ),
                        None,
                    )
                )

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                pass

            def fetchone(self):
                return next(self._rows)

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def optional_column(_table, column, _default):
                return f"[{column}]"

        class Reader(MdbReader):
            @staticmethod
            def _schema(_connection):
                return Schema()

        defaults = Reader()._parse_settings_defaults(
            SimpleNamespace(cursor=lambda: Cursor()),
        )
        self.assertEqual(
            defaults,
            {
                "scale_style": 3,
                "scale_factor1": 0.5,
                "scale_factor2": 24.0,
                "page_width": 36.0,
                "page_height": 24.0,
                "measure_base": 2,
                "takeoff_increments": 0.5,
                "next_bid_no": 15,
            },
        )


class _SqliteSettingsReader(SettingsReaderMixin, BidDataReaderMixin, _SqliteMdbOps):
    @staticmethod
    def _record_caught_read_error(_exc, _locator=None):
        return False


class _FatalReadErrors(_SqliteSettingsReader):
    @staticmethod
    def _record_caught_read_error(_exc, _locator=None):
        return True


class _FailingOpen(_SqliteSettingsReader):
    error = RuntimeError("boom")

    def _connection(self, _db_path):
        raise self.error


class _FailingOpenFatal(_FailingOpen, _FatalReadErrors):
    pass


class _FailingCursor(_SqliteCursorWrapper):
    def execute(self, query, *params):
        raise pyodbc.Error("HY000", "driver failure")


class _FailingConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return _FailingCursor(self._connection)


class SettingsReaderRealSchemaTests(unittest.TestCase):
    def database(self, *statements):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for statement in statements:
            connection.execute(statement)
        return connection

    def test_used_job_status_uids_are_distinct_and_skip_nulls_and_missing_schema(self):
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)",
            "INSERT INTO Bids VALUES (1, 5)",
            "INSERT INTO Bids VALUES (2, 5)",
            "INSERT INTO Bids VALUES (3, 6)",
            "INSERT INTO Bids VALUES (4, NULL)",
        )
        reader = _SqliteSettingsReader(connection)
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "job_statuses"), {"5", "6"}
        )
        connection.execute("DROP TABLE Bids")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "job_statuses"), set()
        )
        connection.execute("DROP TABLE Bids")
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "job_statuses"), set()
        )

    def test_master_data_usage_kinds_cover_employees_statuses_and_pay_classes(self):
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER, EstimatorUID INTEGER)",
            "INSERT INTO Bids VALUES (1, 5, 10)",
            "CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER)",
            "INSERT INTO Employees VALUES (10, 3)",
            "INSERT INTO Employees VALUES (11, 3)",
            "INSERT INTO Employees VALUES (12, 4)",
            "INSERT INTO Employees VALUES (13, NULL)",
        )
        reader = _SqliteSettingsReader(connection)
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "employees"), {"10"}
        )
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "job_statuses"), {"5"}
        )
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "pay_classes"), {"3", "4"}
        )
        self.assertEqual(reader.get_employee_uids_in_use("x.mdb"), {"10"})
        connection.execute("DROP TABLE Employees")
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "pay_classes"), set()
        )
        connection.execute("CREATE TABLE Employees (UID INTEGER)")
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "pay_classes"), set()
        )
        for kind in ("bids", "", "Employees"):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(
                    ValueError, "^Unsupported master-data usage kind$"
                ):
                    reader.get_master_data_uids_in_use("x.mdb", kind)

    def test_employee_usage_read_errors_are_downgraded_only_for_data_errors(self):
        for error in (ValueError("v"), TypeError("t"), pyodbc.Error("HY000", "p")):
            with self.subTest(error=type(error).__name__):

                class Reader(_FailingOpen):
                    pass

                Reader.error = error
                with self.assertLogs("test", level="WARNING") as logs:
                    self.assertEqual(
                        Reader(None).get_employee_uids_in_use("x.mdb"), set()
                    )
                self.assertEqual(len(logs.records), 1)
                self.assertIs(
                    logs.records[0]
                    .getMessage()
                    .startswith("Could not query employee UIDs in use: "),
                    True,
                )
        with self.assertRaisesRegex(RuntimeError, "boom"):
            _FailingOpen(None).get_employee_uids_in_use("x.mdb")
        fatal = type("F", (_FailingOpenFatal,), {"error": ValueError("v")})
        with self.assertRaises(ValueError):
            fatal(None).get_employee_uids_in_use("x.mdb")

    def test_condition_type_uids_in_use_are_distinct_and_tolerate_old_schemas(self):
        connection = self.database(
            "CREATE TABLE BidConditions (UID INTEGER, CdnTypeUID INTEGER)",
            "INSERT INTO BidConditions VALUES (1, 4)",
            "INSERT INTO BidConditions VALUES (2, 4)",
            "INSERT INTO BidConditions VALUES (3, 9)",
            "INSERT INTO BidConditions VALUES (4, NULL)",
        )
        reader = _SqliteSettingsReader(connection)
        self.assertEqual(reader.get_condition_type_uids_in_use("x.mdb"), {"4", "9"})
        connection.execute("DROP TABLE BidConditions")
        connection.execute("CREATE TABLE BidConditions (UID INTEGER)")
        self.assertEqual(reader.get_condition_type_uids_in_use("x.mdb"), set())
        connection.execute("DROP TABLE BidConditions")
        self.assertEqual(reader.get_condition_type_uids_in_use("x.mdb"), set())

    def test_condition_type_and_layer_usage_errors_warn_or_propagate(self):
        for method, args, message in (
            (
                "get_condition_type_uids_in_use",
                ("x.mdb",),
                "Could not query condition type UIDs in use: ",
            ),
            (
                "get_layer_uids_in_use",
                ("x.mdb", "1"),
                "Could not query layer UIDs in use: ",
            ),
        ):
            with self.subTest(method=method):
                failing = type("R", (_FailingOpen,), {"error": ValueError("bad")})
                with self.assertLogs("test", level="WARNING") as logs:
                    self.assertEqual(getattr(failing(None), method)(*args), set())
                self.assertEqual(logs.records[0].getMessage(), message + "bad")
                fatal = type("F", (_FailingOpenFatal,), {"error": ValueError("bad")})
                with self.assertRaisesRegex(ValueError, "bad"):
                    getattr(fatal(None), method)(*args)
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    getattr(_FailingOpen(None), method)(*args)

    def test_layer_usage_filters_by_bid_when_the_table_has_one_and_skips_nulls(self):
        connection = self.database(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)",
            "INSERT INTO BidConditions VALUES (1, 7, 101)",
            "INSERT INTO BidConditions VALUES (2, 7, 101)",
            "INSERT INTO BidConditions VALUES (3, 8, 102)",
            "INSERT INTO BidConditions VALUES (4, 7, NULL)",
            "CREATE TABLE BidHotLinks (UID INTEGER, BidLayerUID INTEGER)",
            "INSERT INTO BidHotLinks VALUES (1, 301)",
            "INSERT INTO BidHotLinks VALUES (2, NULL)",
            "CREATE TABLE BidTexts (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidTexts VALUES (1, 7)",
        )
        reader = _SqliteSettingsReader(connection)
        self.assertEqual(reader.get_layer_uids_in_use("x.mdb", "7"), {"101", "301"})
        self.assertEqual(reader.get_layer_uids_in_use("x.mdb", "8"), {"102", "301"})
        self.assertEqual(reader.get_layer_uids_in_use("x.mdb", "9"), {"301"})

    def test_job_statuses_are_ordered_by_sequence_and_parse_their_flags(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (3, 'Lost', 1, 3)",
            "INSERT INTO JobStatuses VALUES (1, 'Open', 0, 1)",
            "INSERT INTO JobStatuses VALUES (2, NULL, 'False', 2)",
            "INSERT INTO JobStatuses VALUES (4, 'Tie A', '', 2)",
            "INSERT INTO JobStatuses VALUES (5, 'Zero', 'True', 0)",
        )
        self.assertEqual(
            _SqliteSettingsReader(connection).get_job_statuses("x.mdb"),
            [
                JobStatus("5", "Zero", True, 0),
                JobStatus("1", "Open", False, 1),
                JobStatus("2", "", False, 2),
                JobStatus("4", "Tie A", False, 2),
                JobStatus("3", "Lost", True, 3),
            ],
        )

    def test_job_statuses_default_missing_flag_and_sequence_columns(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "INSERT INTO JobStatuses VALUES (2, 'B')",
            "INSERT INTO JobStatuses VALUES (1, 'A')",
        )
        self.assertEqual(
            _SqliteSettingsReader(connection).get_job_statuses("x.mdb"),
            [JobStatus("1", "A", False, 0), JobStatus("2", "B", False, 0)],
        )
        connection.execute("DROP TABLE JobStatuses")
        self.assertEqual(
            _SqliteSettingsReader(connection).get_job_statuses("x.mdb"), []
        )

    def test_a_null_sequence_reads_as_zero_like_every_other_sequence_column(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (3, 'Won', 1, 3)",
            "INSERT INTO JobStatuses VALUES (1, 'Open', 0, 1)",
            "INSERT INTO JobStatuses VALUES (2, 'Lost', 0, NULL)",
        )
        self.assertEqual(
            _SqliteSettingsReader(connection).get_job_statuses("x.mdb"),
            [
                JobStatus("2", "Lost", False, 0),
                JobStatus("1", "Open", False, 1),
                JobStatus("3", "Won", True, 3),
            ],
        )

    def test_null_and_zero_sequences_tie_in_row_order(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (4, 'Null first', 0, NULL)",
            "INSERT INTO JobStatuses VALUES (5, 'Zero', 0, 0)",
            "INSERT INTO JobStatuses VALUES (6, 'Null last', 0, NULL)",
        )
        self.assertEqual(
            [
                s.uid
                for s in _SqliteSettingsReader(connection).get_job_statuses("x.mdb")
            ],
            ["4", "5", "6"],
        )

    def test_sequence_ties_resolve_by_uid_even_when_rows_were_inserted_in_reverse(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (9, 'Tie 9 null', 0, NULL)",
            "INSERT INTO JobStatuses VALUES (8, 'Tie 8 zero', 0, 0)",
            "INSERT INTO JobStatuses VALUES (7, 'Tie 7 null', 0, NULL)",
            "INSERT INTO JobStatuses VALUES (6, 'Tie 6 zero', 0, 0)",
            "INSERT INTO JobStatuses VALUES (5, 'Later', 0, 2)",
            "INSERT INTO JobStatuses VALUES (4, 'Later tie', 0, 2)",
        )
        self.assertEqual(
            [
                s.uid
                for s in _SqliteSettingsReader(connection).get_job_statuses("x.mdb")
            ],
            ["6", "7", "8", "9", "4", "5"],
        )

    def test_only_null_sequences_still_return_every_row(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (1, 'A', 0, NULL)",
            "INSERT INTO JobStatuses VALUES (2, 'B', 0, NULL)",
        )
        self.assertEqual(
            _SqliteSettingsReader(connection).get_job_statuses("x.mdb"),
            [JobStatus("1", "A", False, 0), JobStatus("2", "B", False, 0)],
        )

    def test_a_null_sequence_does_not_break_the_cover_sheet(self):
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER, JobName TEXT)",
            "INSERT INTO Bids VALUES (7, 2, 'Job')",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (2, 'Lost', 0, NULL)",
            "INSERT INTO JobStatuses VALUES (1, 'Open', 0, 1)",
        )
        data = _SqliteSettingsReader(connection).get_cover_sheet_data("x.mdb", "7")
        self.assertEqual(
            data.job_statuses,
            [JobStatus("2", "Lost", False, 0), JobStatus("1", "Open", False, 1)],
        )

    def test_job_status_read_failures_warn_or_propagate(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "INSERT INTO JobStatuses VALUES (7, 'A')",
            "INSERT INTO JobStatuses VALUES (7, 'B')",
        )
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertEqual(
                _SqliteSettingsReader(connection).get_job_statuses("x.mdb"), []
            )
        self.assertEqual(
            logs.records[0].getMessage(), "Could not load job statuses from x.mdb"
        )
        with self.assertRaisesRegex(
            RuntimeError, "JobStatuses contains duplicate UID 7"
        ):
            _FatalReadErrors(connection).get_job_statuses("x.mdb")

    def test_employees_and_pay_classes_map_every_column(self):
        connection = self.database(
            "CREATE TABLE Employees (UID INTEGER, EmployeeNo TEXT, FirstName TEXT, "
            "LastName TEXT, Address1 TEXT, Address2 TEXT, City TEXT, State TEXT, "
            "Zip TEXT, HomePhone TEXT, MobilePhone TEXT, EMail TEXT, PayClassUID INTEGER)",
            "INSERT INTO Employees VALUES (7, 'E1', 'Ann', 'Lee', 'a1', 'a2', 'City', "
            "'ST', '12345', 'hp', 'mp', 'ann@example.com', 4)",
            "INSERT INTO Employees VALUES (8, NULL, NULL, NULL, NULL, NULL, NULL, NULL, "
            "NULL, NULL, NULL, NULL, NULL)",
            "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
            "INSERT INTO PayClasses VALUES (4, 'Journeyman')",
            "INSERT INTO PayClasses VALUES (5, NULL)",
        )
        employees, pay_classes = _SqliteSettingsReader(
            connection
        ).get_employees_and_pay_classes("x.mdb")
        self.assertEqual(
            employees,
            [
                Employee(
                    uid="7",
                    employee_no="E1",
                    first_name="Ann",
                    last_name="Lee",
                    address1="a1",
                    address2="a2",
                    city="City",
                    state="ST",
                    zip="12345",
                    home_phone="hp",
                    mobile_phone="mp",
                    email="ann@example.com",
                    pay_class_uid="4",
                ),
                Employee(uid="8"),
            ],
        )
        self.assertEqual(pay_classes, [PayClass("4", "Journeyman"), PayClass("5", "")])

    def test_employee_read_failures_warn_with_empty_results_or_propagate(self):
        connection = self.database(
            "CREATE TABLE Employees (UID INTEGER)",
            "INSERT INTO Employees VALUES (7)",
            "INSERT INTO Employees VALUES (7)",
        )
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertEqual(
                _SqliteSettingsReader(connection).get_employees_and_pay_classes(
                    "x.mdb"
                ),
                ([], []),
            )
        self.assertEqual(
            logs.records[0].getMessage(),
            "Could not load employees/pay classes from x.mdb",
        )
        with self.assertRaisesRegex(RuntimeError, "Employees contains duplicate UID 7"):
            _FatalReadErrors(connection).get_employees_and_pay_classes("x.mdb")

    def test_bid_areas_are_listed_for_the_bid_and_failures_warn_or_propagate(self):
        connection = self.database(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, Sequence INTEGER, GUID TEXT)",
            "INSERT INTO BidAreas VALUES (11, 7, 0, 'Second', 2, '{G2}')",
            "INSERT INTO BidAreas VALUES (10, 7, NULL, 'First', 1, NULL)",
            "INSERT INTO BidAreas VALUES (12, 8, NULL, 'Other', 1, NULL)",
        )
        reader = _SqliteSettingsReader(connection)
        self.assertEqual(
            reader.get_bid_areas("x.mdb", "7"),
            [
                BidArea(uid="10", bid_uid="7", parent_uid="", name="First", sequence=1),
                BidArea(
                    uid="11",
                    bid_uid="7",
                    parent_uid="",
                    name="Second",
                    sequence=2,
                    guid="{G2}",
                ),
            ],
        )
        connection.execute(
            "INSERT INTO BidAreas VALUES (13, 7, 999, 'Dangling', 3, NULL)"
        )
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertEqual(reader.get_bid_areas("x.mdb", "7"), [])
        self.assertEqual(
            logs.records[0].getMessage(),
            "Could not load bid areas for bid 7 from x.mdb",
        )
        with self.assertRaisesRegex(RuntimeError, "BidAreas.UID=13 references missing"):
            _FatalReadErrors(connection).get_bid_areas("x.mdb", "7")

    def test_settings_defaults_come_from_the_single_settings_row(self):
        connection = self.database(
            "CREATE TABLE Settings (ScaleStyle INTEGER, ScaleFactor1 REAL, "
            "ScaleFactor2 REAL, PageWidth REAL, PageHeight REAL, MeasureBase INTEGER, "
            "TakeoffIncrements REAL, NextBidNo INTEGER)",
        )
        reader = _SqliteSettingsReader(connection)
        defaults = {
            "scale_style": 1,
            "scale_factor1": 0.125,
            "scale_factor2": 12.0,
            "page_width": 42.0,
            "page_height": 30.0,
            "measure_base": 0,
            "takeoff_increments": 1.0,
            "next_bid_no": 1,
        }
        self.assertEqual(reader.get_settings_defaults("x.mdb"), defaults)
        connection.execute(
            "INSERT INTO Settings VALUES (3, 0.5, 24, 36, 24, 2, 0.5, 15)"
        )
        self.assertEqual(
            reader.get_settings_defaults("x.mdb"),
            {
                "scale_style": 3,
                "scale_factor1": 0.5,
                "scale_factor2": 24.0,
                "page_width": 36.0,
                "page_height": 24.0,
                "measure_base": 2,
                "takeoff_increments": 0.5,
                "next_bid_no": 15,
            },
        )
        connection.execute("DELETE FROM Settings")
        connection.execute("INSERT INTO Settings VALUES (0, 0, 0, 0, 0, 0, 0, 0)")
        self.assertEqual(reader.get_settings_defaults("x.mdb"), defaults)

    def test_settings_defaults_fill_columns_missing_from_old_databases(self):
        connection = self.database(
            "CREATE TABLE Settings (ScaleStyle INTEGER, NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (2, 40)",
        )
        self.assertEqual(
            _SqliteSettingsReader(connection).get_settings_defaults("x.mdb"),
            {
                "scale_style": 2,
                "scale_factor1": 0.125,
                "scale_factor2": 12.0,
                "page_width": 42.0,
                "page_height": 30.0,
                "measure_base": 0,
                "takeoff_increments": 1.0,
                "next_bid_no": 40,
            },
        )

    def test_settings_defaults_survive_data_errors_but_not_fatal_ones(self):
        expected = {
            "scale_style": 1,
            "scale_factor1": 0.125,
            "scale_factor2": 12.0,
            "page_width": 42.0,
            "page_height": 30.0,
            "measure_base": 0,
            "takeoff_increments": 1.0,
            "next_bid_no": 1,
        }
        for error in (pyodbc.Error("HY000", "p"), TypeError("t"), ValueError("v")):
            with self.subTest(error=type(error).__name__):
                failing = type("R", (_FailingOpen,), {"error": error})
                self.assertEqual(failing(None).get_settings_defaults("x.mdb"), expected)
                fatal = type("F", (_FailingOpenFatal,), {"error": error})
                with self.assertRaises(type(error)):
                    fatal(None).get_settings_defaults("x.mdb")
        with self.assertRaisesRegex(RuntimeError, "boom"):
            _FailingOpen(None).get_settings_defaults("x.mdb")

    _STORED_SETTINGS = {
        "ScaleStyle": 3,
        "ScaleFactor1": 0.5,
        "ScaleFactor2": 24.0,
        "PageWidth": 36.0,
        "PageHeight": 24.0,
        "MeasureBase": 2,
        "TakeoffIncrements": 0.5,
        "NextBidNo": 15,
    }
    _SETTINGS_KEYS = {
        "ScaleStyle": "scale_style",
        "ScaleFactor1": "scale_factor1",
        "ScaleFactor2": "scale_factor2",
        "PageWidth": "page_width",
        "PageHeight": "page_height",
        "MeasureBase": "measure_base",
        "TakeoffIncrements": "takeoff_increments",
        "NextBidNo": "next_bid_no",
    }
    _BUILT_IN_SETTINGS = {
        "scale_style": 1,
        "scale_factor1": 0.125,
        "scale_factor2": 12.0,
        "page_width": 42.0,
        "page_height": 30.0,
        "measure_base": 0,
        "takeoff_increments": 1.0,
        "next_bid_no": 1,
    }

    def settings_database(self, **overrides):
        stored = {**self._STORED_SETTINGS, **overrides}
        connection = self.database(
            "CREATE TABLE Settings (" + ", ".join(stored) + ")",
        )
        connection.execute(
            "INSERT INTO Settings VALUES (" + ", ".join("?" * len(stored)) + ")",
            tuple(stored.values()),
        )
        return connection

    def expected_settings(self, **defaulted):
        expected = {
            self._SETTINGS_KEYS[column]: value
            for column, value in self._STORED_SETTINGS.items()
        }
        for column in defaulted:
            key = self._SETTINGS_KEYS[column]
            expected[key] = self._BUILT_IN_SETTINGS[key]
        return expected

    def test_one_malformed_settings_field_defaults_only_that_field(self):
        reader = _SqliteSettingsReader(self.settings_database(NextBidNo="abc"))
        with self.assertLogs("test", level="WARNING") as logs:
            defaults = reader.get_settings_defaults("x.mdb")
        self.assertEqual(defaults, self.expected_settings(NextBidNo=None))
        self.assertEqual(defaults["scale_style"], 3)
        self.assertEqual(defaults["next_bid_no"], 1)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Ignoring malformed Settings.NextBidNo value 'abc'; using the default 1"],
        )

    def test_missing_or_blank_settings_fields_default_without_a_warning(self):
        for stored in (None, ""):
            with self.subTest(stored=stored):
                reader = _SqliteSettingsReader(
                    self.settings_database(
                        **{column: stored for column in self._STORED_SETTINGS}
                    )
                )
                with self.assertNoLogs("test", level="WARNING"):
                    defaults = reader.get_settings_defaults("x.mdb")
                self.assertEqual(defaults, self._BUILT_IN_SETTINGS)

    def test_every_settings_field_defaults_on_its_own_when_malformed(self):
        for column in self._STORED_SETTINGS:
            with self.subTest(column=column):
                reader = _SqliteSettingsReader(
                    self.settings_database(**{column: "abc"})
                )
                with self.assertLogs("test", level="WARNING") as logs:
                    defaults = reader.get_settings_defaults("x.mdb")
                self.assertEqual(defaults, self.expected_settings(**{column: None}))
                self.assertEqual(len(logs.records), 1)
                self.assertIn(f"Settings.{column}", logs.records[0].getMessage())

    def test_several_malformed_settings_fields_default_while_the_rest_are_kept(self):
        reader = _SqliteSettingsReader(
            self.settings_database(ScaleStyle="x", PageHeight="y", NextBidNo="z")
        )
        with self.assertLogs("test", level="WARNING") as logs:
            defaults = reader.get_settings_defaults("x.mdb")
        self.assertEqual(
            defaults,
            self.expected_settings(ScaleStyle=None, PageHeight=None, NextBidNo=None),
        )
        self.assertEqual(
            sorted(
                column
                for column in self._STORED_SETTINGS
                if any(f"Settings.{column}" in r.getMessage() for r in logs.records)
            ),
            ["NextBidNo", "PageHeight", "ScaleStyle"],
        )

    def test_numeric_text_in_settings_fields_is_read_as_numbers(self):
        reader = _SqliteSettingsReader(
            self.settings_database(
                ScaleStyle="3",
                ScaleFactor1="0.5",
                ScaleFactor2="24",
                PageWidth="36",
                PageHeight="24.0",
                MeasureBase="2",
                TakeoffIncrements="0.5",
                NextBidNo="15",
            )
        )
        defaults = reader.get_settings_defaults("x.mdb")
        self.assertEqual(defaults, self.expected_settings())
        self.assertEqual(
            [type(defaults[key]) for key in self._SETTINGS_KEYS.values()],
            [int, float, float, float, float, int, float, int],
        )

    def test_unconvertible_settings_values_of_any_type_default_their_field(self):
        row = SimpleNamespace(
            ScaleStyle=float("inf"),
            ScaleFactor1=0.5,
            ScaleFactor2=24.0,
            PageWidth=36.0,
            PageHeight=24.0,
            MeasureBase=[1],
            TakeoffIncrements=0.5,
            NextBidNo=15,
        )
        reader = _SqliteSettingsReader(
            self.settings_database(),
        )
        with mock.patch(
            "ost_visualizer.infrastructure.mdb.components.settings_reader."
            "fetch_optional_global_settings_row",
            return_value=row,
        ):
            with self.assertLogs("test", level="WARNING") as logs:
                defaults = reader.get_settings_defaults("x.mdb")
        self.assertEqual(
            defaults, self.expected_settings(ScaleStyle=None, MeasureBase=None)
        )
        self.assertEqual(len(logs.records), 2)

    def test_a_malformed_settings_field_defaults_where_read_errors_are_fatal(self):
        """SQL readers treat read errors as fatal, but a malformed stored value
        is data, not a read error: it defaults its own field like the MDB reader."""
        reader = _FatalReadErrors(self.settings_database(NextBidNo="abc"))
        with self.assertLogs("test", level="WARNING") as logs:
            defaults = reader.get_settings_defaults("x.mdb")
        self.assertEqual(defaults, self.expected_settings(NextBidNo=None))
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Ignoring malformed Settings.NextBidNo value 'abc'; using the default 1"],
        )

    def test_every_settings_field_defaults_on_its_own_where_read_errors_are_fatal(
        self,
    ):
        for column in self._STORED_SETTINGS:
            with self.subTest(column=column):
                reader = _FatalReadErrors(self.settings_database(**{column: "abc"}))
                with self.assertLogs("test", level="WARNING") as logs:
                    defaults = reader.get_settings_defaults("x.mdb")
                self.assertEqual(defaults, self.expected_settings(**{column: None}))
                self.assertEqual(len(logs.records), 1)
                self.assertIn(f"Settings.{column}", logs.records[0].getMessage())

    def test_the_hydration_parser_defaults_a_malformed_field_for_a_fatal_reader(self):
        """SqlRemoteChangeReader calls _parse_settings_defaults directly."""
        connection = self.settings_database(PageWidth="wide")
        reader = _FatalReadErrors(connection)
        with self.assertLogs("test", level="WARNING"):
            defaults = reader._parse_settings_defaults(
                _SqliteConnectionWrapper(connection)
            )
        self.assertEqual(defaults, self.expected_settings(PageWidth=None))


class CoverSheetRealSchemaTests(unittest.TestCase):
    _BID_COLUMNS = (
        "UID INTEGER, JobStatusUID INTEGER, JobName TEXT, EstimatorUID INTEGER, "
        "Notes TEXT, BidDate TEXT, BidNo INTEGER, JobID TEXT, MeasureBase INTEGER, "
        "TakeoffIncrements REAL, ScaleStyle INTEGER, ScaleFactor1 REAL, "
        "ScaleFactor2 REAL, PageWidth REAL, PageHeight REAL"
    )

    def database(self, *statements):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for statement in statements:
            connection.execute(statement)
        return connection

    def test_cover_sheet_maps_the_bid_row_and_reference_data(self):
        connection = self.database(
            f"CREATE TABLE Bids ({self._BID_COLUMNS})",
            "INSERT INTO Bids VALUES (7, 2, 'Job', 3, 'Some notes', '2024-05-01', 12, "
            "'J-1', 1, 0.5, 2, 0.5, 24, 36, 24)",
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (2, 'Won', 0, 1)",
            "CREATE TABLE Employees (UID INTEGER, FirstName TEXT)",
            "INSERT INTO Employees VALUES (3, 'Eve')",
            "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
            "INSERT INTO PayClasses VALUES (1, 'Std')",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidPages VALUES (20, 7, 'P')",
        )
        data = _SqliteSettingsReader(connection).get_cover_sheet_data("x.mdb", "7")
        self.assertEqual(
            data,
            CoverSheetData(
                bid_uid="7",
                job_status_uid="2",
                job_name="Job",
                estimator_uid="3",
                notes="Some notes",
                bid_date="2024-05-01",
                bid_no="12",
                job_id="J-1",
                measure_base=1,
                takeoff_increments=0.5,
                scale_style=2,
                scale_factor1=0.5,
                scale_factor2=24.0,
                page_width=36.0,
                page_height=24.0,
                folders={},
                pages_without_folder=[
                    CoverSheetPage(
                        uid="20",
                        sheet_no="",
                        name="P",
                        width=0.0,
                        height=0.0,
                        scale_factor1=1.0,
                        scale_factor2=1.0,
                        image_path="",
                        overlay_image_path="",
                        index=1,
                        show_mode=0,
                        multi_page_count=0,
                    )
                ],
                job_statuses=[JobStatus("2", "Won", False, 1)],
                employees=[Employee(uid="3", first_name="Eve")],
                pay_classes=[PayClass("1", "Std")],
                used_job_status_uids={"2"},
            ),
        )

    def test_cover_sheet_uses_documented_defaults_for_null_and_garbage_values(self):
        connection = self.database(
            f"CREATE TABLE Bids ({self._BID_COLUMNS})",
            "INSERT INTO Bids VALUES (7, NULL, NULL, NULL, NULL, NULL, NULL, NULL, "
            "'abc', 'x', 'y', NULL, 'z', NULL, '')",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        )
        data = _SqliteSettingsReader(connection).get_cover_sheet_data("x.mdb", "7")
        self.assertEqual(
            (
                data.job_status_uid,
                data.job_name,
                data.estimator_uid,
                data.notes,
                data.bid_date,
                data.bid_no,
                data.job_id,
                data.measure_base,
                data.takeoff_increments,
                data.scale_style,
                data.scale_factor1,
                data.scale_factor2,
                data.page_width,
                data.page_height,
            ),
            ("", "", "", "", "", "", "", 0, 1.0, 1, 0.25, 12.0, 42.0, 30.0),
        )
        self.assertEqual(
            (
                data.folders,
                data.pages_without_folder,
                data.job_statuses,
                data.employees,
            ),
            ({}, [], [], []),
        )
        self.assertEqual(data.used_job_status_uids, set())

    def test_cover_sheet_of_an_unknown_bid_is_none(self):
        connection = self.database(
            f"CREATE TABLE Bids ({self._BID_COLUMNS})",
            "INSERT INTO Bids (UID) VALUES (7)",
        )
        self.assertIsNone(
            _SqliteSettingsReader(connection).get_cover_sheet_data("x.mdb", "8")
        )

    def test_cover_sheet_page_tree_nests_folders_and_maps_page_columns(self):
        connection = self.database(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "ParentUID INTEGER)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "SheetNo TEXT, Width REAL, Height REAL, ScaleFactor1 REAL, "
            "ScaleFactor2 REAL, ImagePath TEXT, OverlayImagePath TEXT, Index1 INTEGER, "
            "MultiPageCount INTEGER, [Show] INTEGER, BidPageFolderUID INTEGER, "
            "Sequence INTEGER)",
            "INSERT INTO BidPageFolders VALUES (10, 7, 'Zeta', NULL)",
            "INSERT INTO BidPageFolders VALUES (11, 7, 'Alpha', 0)",
            "INSERT INTO BidPageFolders VALUES (12, 7, NULL, 10)",
            "INSERT INTO BidPageFolders VALUES (13, 7, 'Orphan', 999)",
            "INSERT INTO BidPageFolders VALUES (14, 8, 'Other bid', NULL)",
            "INSERT INTO BidPages VALUES (20, 7, 'P1', 'S1', 36.5, 24.5, 0.125, 12, "
            "'a.pdf', 'o.pdf', 3, 7, 2, 12, 2)",
            "INSERT INTO BidPages VALUES (21, 7, NULL, NULL, NULL, NULL, NULL, NULL, "
            "NULL, NULL, NULL, NULL, NULL, 11, 1)",
            "INSERT INTO BidPages VALUES (22, 7, 'Loose', '', 0, 0, 0, 0, '', '', 1, 0, "
            "0, 0, 3)",
            "INSERT INTO BidPages VALUES (23, 7, 'Gone', '', 0, 0, 0, 0, '', '', 1, 0, "
            "0, 555, 4)",
            "INSERT INTO BidPages VALUES (24, 8, 'Other', '', 0, 0, 0, 0, '', '', 1, 0, "
            "0, 0, 1)",
        )
        folders, loose = _SqliteSettingsReader(connection)._query_cover_sheet_pages(
            _SqliteConnectionWrapper(connection), "7"
        )
        self.assertEqual(list(folders), ["11", "13", "10"])
        self.assertEqual(
            [(f.uid, f.name) for f in folders.values()],
            [("11", "Alpha"), ("13", "Orphan"), ("10", "Zeta")],
        )
        self.assertEqual(list(folders["10"].subfolders), ["12"])
        self.assertEqual(folders["10"].subfolders["12"].name, "12")
        self.assertEqual(
            folders["11"].pages,
            [CoverSheetPage("21", "", "", 0.0, 0.0, 1.0, 1.0, "", "", 1, 0, 0)],
        )
        self.assertEqual(folders["13"].pages, [])
        self.assertEqual(
            folders["10"].subfolders["12"].pages,
            [
                CoverSheetPage(
                    "20", "S1", "P1", 36.5, 24.5, 0.125, 12.0, "a.pdf", "o.pdf", 3, 2, 7
                )
            ],
        )
        self.assertEqual([page.uid for page in loose], ["22", "23"])

    def test_cover_sheet_pages_without_optional_tables_or_columns_use_uid_order(self):
        connection = self.database(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (31, 7)",
            "INSERT INTO BidPages VALUES (30, 7)",
        )
        folders, loose = _SqliteSettingsReader(connection)._query_cover_sheet_pages(
            _SqliteConnectionWrapper(connection), "7"
        )
        self.assertEqual(folders, {})
        self.assertEqual(
            loose,
            [
                CoverSheetPage("30", "", "", 0.0, 0.0, 1.0, 1.0, "", "", 1, 0, 0),
                CoverSheetPage("31", "", "", 0.0, 0.0, 1.0, 1.0, "", "", 1, 0, 0),
            ],
        )

    def test_cover_sheet_structure_requires_page_and_folder_identity_columns(self):
        for table, columns, missing in (
            ("BidPages", "BidUID INTEGER", "UID"),
            ("BidPages", "UID INTEGER", "BidUID"),
        ):
            with self.subTest(missing=missing):
                connection = self.database(f"CREATE TABLE {table} ({columns})")
                with self.assertRaisesRegex(RuntimeError, f"Missing {table}.{missing}"):
                    _SqliteSettingsReader(connection)._query_cover_sheet_pages(
                        _SqliteConnectionWrapper(connection), "7"
                    )
        for present, missing in (
            ("BidUID INTEGER, Name TEXT", "UID"),
            ("UID INTEGER, Name TEXT", "BidUID"),
            ("UID INTEGER, BidUID INTEGER", "Name"),
        ):
            with self.subTest(folder_missing=missing):
                connection = self.database(
                    "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
                    f"CREATE TABLE BidPageFolders ({present})",
                )
                with self.assertRaisesRegex(
                    RuntimeError, f"Missing BidPageFolders.{missing}"
                ):
                    _SqliteSettingsReader(connection)._query_cover_sheet_pages(
                        _SqliteConnectionWrapper(connection), "7"
                    )

    def test_cover_sheet_rejects_duplicate_folder_and_page_uids(self):
        for table, statements in (
            (
                "BidPageFolders",
                (
                    "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
                    "INSERT INTO BidPageFolders VALUES (5, 7, 'A')",
                    "INSERT INTO BidPageFolders VALUES (5, 7, 'B')",
                ),
            ),
            (
                "BidPages",
                (
                    "INSERT INTO BidPages VALUES (5, 7)",
                    "INSERT INTO BidPages VALUES (5, 7)",
                ),
            ),
        ):
            with self.subTest(table=table):
                connection = self.database(
                    "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)"
                )
                for statement in statements:
                    connection.execute(statement)
                with self.assertRaisesRegex(
                    RuntimeError, f"{table} contains duplicate UID 5"
                ):
                    _SqliteSettingsReader(connection)._query_cover_sheet_pages(
                        _SqliteConnectionWrapper(connection), "7"
                    )

    def test_cover_sheet_rejects_a_page_without_a_uid_value(self):
        connection = self.database(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidPages VALUES (NULL, 7, 'No uid')",
        )
        with self.assertRaisesRegex(
            RuntimeError, "BidPages contains malformed UID <missing>"
        ):
            _SqliteSettingsReader(connection)._query_cover_sheet_pages(
                _SqliteConnectionWrapper(connection), "7"
            )

    def test_cover_sheet_driver_errors_return_empty_trees_unless_fatal(self):
        connection = self.database(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)"
        )
        failing = _FailingConnection(connection)
        self.assertEqual(
            _SqliteSettingsReader(connection)._query_cover_sheet_pages(failing, "7"),
            ({}, []),
        )
        with self.assertRaises(pyodbc.Error):
            _FatalReadErrors(connection)._query_cover_sheet_pages(failing, "7")


class SettingsReaderSparseSchemaTests(unittest.TestCase):
    """Databases that only carry identity columns still read with blank fields."""

    def database(self, *statements):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for statement in statements:
            connection.execute(statement)
        return connection

    def test_employees_pay_classes_and_statuses_without_optional_columns_are_blank(
        self,
    ):
        connection = self.database(
            "CREATE TABLE Employees (UID INTEGER)",
            "INSERT INTO Employees VALUES (7)",
            "CREATE TABLE PayClasses (UID INTEGER)",
            "INSERT INTO PayClasses VALUES (4)",
            "CREATE TABLE JobStatuses (UID INTEGER)",
            "INSERT INTO JobStatuses VALUES (2)",
        )
        reader = _SqliteSettingsReader(connection)
        employees, pay_classes = reader.get_employees_and_pay_classes("x.mdb")
        self.assertEqual(employees, [Employee(uid="7")])
        self.assertEqual(pay_classes, [PayClass(uid="4", name="")])
        self.assertEqual(
            reader.get_job_statuses("x.mdb"), [JobStatus("2", "", False, 0)]
        )

    def test_cover_sheet_of_a_bid_with_only_a_uid_uses_blank_text_and_defaults(self):
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (7)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        )
        data = _SqliteSettingsReader(connection).get_cover_sheet_data("x.mdb", "7")
        self.assertEqual(
            data,
            CoverSheetData(
                bid_uid="7",
                job_status_uid="",
                job_name="",
                estimator_uid="",
                notes="",
                bid_date="",
                bid_no="",
                job_id="",
                measure_base=0,
                takeoff_increments=1.0,
                scale_style=1,
                scale_factor1=0.25,
                scale_factor2=12.0,
                page_width=42.0,
                page_height=30.0,
            ),
        )

    def test_cover_sheet_integer_fields_fall_back_on_blank_null_and_garbage(self):
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER, MeasureBase, ScaleStyle)",
            "INSERT INTO Bids VALUES (7, '', NULL)",
            "INSERT INTO Bids VALUES (8, 'abc', '3')",
            "INSERT INTO Bids VALUES (9, 2, 4)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        )
        reader = _SqliteSettingsReader(connection)
        self.assertEqual(
            [
                (d.measure_base, d.scale_style)
                for d in (
                    reader.get_cover_sheet_data("x.mdb", uid) for uid in ("7", "8", "9")
                )
            ],
            [(0, 1), (0, 3), (2, 4)],
        )

    def test_cover_sheet_pages_follow_sequence_and_folder_parents_of_one_nest(self):
        connection = self.database(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "ParentUID INTEGER)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "BidPageFolderUID INTEGER, Sequence INTEGER)",
            "INSERT INTO BidPageFolders VALUES (1, 7, 'Root', NULL)",
            "INSERT INTO BidPageFolders VALUES (2, 7, 'Kid', 1)",
            "INSERT INTO BidPages VALUES (40, 7, 'late', NULL, 2)",
            "INSERT INTO BidPages VALUES (41, 7, 'early', NULL, 1)",
            "INSERT INTO BidPages VALUES (42, 7, 'in kid', 2, 1)",
        )
        folders, loose = _SqliteSettingsReader(connection)._query_cover_sheet_pages(
            _SqliteConnectionWrapper(connection), "7"
        )
        self.assertEqual([page.uid for page in loose], ["41", "40"])
        self.assertEqual(list(folders), ["1"])
        self.assertEqual(list(folders["1"].subfolders), ["2"])
        self.assertEqual(
            [page.uid for page in folders["1"].subfolders["2"].pages], ["42"]
        )

    def test_settings_defaults_come_from_sql_defaults_when_columns_are_missing(self):
        connection = self.database(
            "CREATE TABLE Settings (PageWidth REAL)",
            "INSERT INTO Settings VALUES (36)",
        )
        self.assertEqual(
            _SqliteSettingsReader(connection).get_settings_defaults("x.mdb"),
            {
                "scale_style": 1,
                "scale_factor1": 0.125,
                "scale_factor2": 12.0,
                "page_width": 36.0,
                "page_height": 30.0,
                "measure_base": 0,
                "takeoff_increments": 1.0,
                "next_bid_no": 1,
            },
        )

    def test_master_data_tables_without_a_uid_column_yield_blank_uids(self):
        connection = self.database(
            "CREATE TABLE Employees (FirstName TEXT)",
            "INSERT INTO Employees VALUES ('Ann')",
            "CREATE TABLE PayClasses (Name TEXT)",
            "INSERT INTO PayClasses VALUES ('Std')",
            "CREATE TABLE JobStatuses (Name TEXT)",
            "INSERT INTO JobStatuses VALUES ('Open')",
        )
        reader = _SqliteSettingsReader(connection)
        employees, pay_classes = reader.get_employees_and_pay_classes("x.mdb")
        self.assertEqual(employees, [Employee(uid="", first_name="Ann")])
        self.assertEqual(pay_classes, [PayClass(uid="", name="Std")])
        self.assertEqual(
            reader.get_job_statuses("x.mdb"), [JobStatus("", "Open", False, 0)]
        )


class _InspectedReader(SettingsReaderMixin):
    """Reader sharing one real schema inspector so its compatibility report is visible."""

    def __init__(self, connection):
        self._connection_obj = connection
        self.logger = logging.getLogger("test")
        self.inspector = MdbSchemaInspector(connection, self.logger)

    @contextmanager
    def _connection(self, _file_path):
        yield self._connection_obj

    def _schema(self, _connection):
        return self.inspector

    @staticmethod
    def _record_caught_read_error(_exc, _locator=None):
        return False


class SettingsReaderSchemaReportTests(unittest.TestCase):
    def test_a_missing_optional_table_is_reported_and_reads_as_unused(self):
        cases = (
            ("get_condition_type_uids_in_use", ("x.mdb",), "BidConditions"),
            ("get_master_data_uids_in_use", ("x.mdb", "employees"), "Bids"),
            ("get_master_data_uids_in_use", ("x.mdb", "job_statuses"), "Bids"),
        )
        for method, args, table in cases:
            with self.subTest(method=method, args=args):
                reader = _InspectedReader(_FakeConnection({}, {}))
                self.assertEqual(getattr(reader, method)(*args), set())
                self.assertEqual(
                    reader.inspector.report.detected_schema_notes,
                    {f"missing optional table {table}"},
                )

    def test_a_present_table_without_the_reference_column_is_not_reported_missing(
        self,
    ):
        cases = (
            ("get_condition_type_uids_in_use", ("x.mdb",), "BidConditions"),
            ("get_master_data_uids_in_use", ("x.mdb", "employees"), "Bids"),
            ("get_master_data_uids_in_use", ("x.mdb", "job_statuses"), "Bids"),
        )
        for method, args, table in cases:
            with self.subTest(method=method, args=args):
                reader = _InspectedReader(_FakeConnection({table: {"UID"}}, {}))
                self.assertEqual(getattr(reader, method)(*args), set())
                self.assertEqual(reader.inspector.report.detected_schema_notes, set())

    def test_the_employee_role_query_selects_every_present_role_column_from_bids(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute(
            "CREATE TABLE Bids (UID INTEGER, EstimatorUID INTEGER, "
            "PrManagerUID INTEGER, JobSiteManagerUID INTEGER)"
        )
        connection.execute("INSERT INTO Bids VALUES (1, 10, 20, 30)")
        statements = []
        connection.set_trace_callback(statements.append)
        used = _SqliteSettingsReader(connection).get_master_data_uids_in_use(
            "x.mdb", "employees"
        )
        self.assertEqual(used, {"10", "20", "30"})
        self.assertIn(
            "SELECT [EstimatorUID], [PrManagerUID], [JobSiteManagerUID] FROM [Bids]",
            statements,
        )


class JobStatusSequenceBoundaryTests(unittest.TestCase):
    _DDL = "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence)"

    def database(self, *statements):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for statement in statements:
            connection.execute(statement)
        return connection

    def statuses(self, *rows, reader_class=_SqliteSettingsReader):
        connection = self.database(self._DDL)
        connection.executemany("INSERT INTO JobStatuses VALUES (?, ?, 0, ?)", rows)
        return reader_class(connection).get_job_statuses("x.mdb")

    def test_negative_blank_text_and_padded_sequences_order_numerically(self):
        result = self.statuses(
            (1, "pos", 5),
            (2, "neg", -3),
            (3, "null", None),
            (4, "sentinel", "NULL"),
            (5, "blank", ""),
            (6, "text", " 4 "),
            (7, "digits", "12"),
        )
        self.assertEqual(
            [(s.uid, s.sequence) for s in result],
            [("2", -3), ("3", 0), ("4", 0), ("5", 0), ("6", 4), ("1", 5), ("7", 12)],
        )

    def test_a_very_large_sequence_sorts_last_without_overflow(self):
        result = self.statuses((1, "huge", 10**15), (2, "small", 1), (3, "none", None))
        self.assertEqual([s.uid for s in result], ["3", "2", "1"])
        self.assertEqual(result[-1].sequence, 10**15)

    def test_a_row_with_every_optional_column_null_is_blank_not_an_error(self):
        connection = self.database(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked INTEGER, "
            "Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (NULL, NULL, 0, NULL)",
        )
        self.assertEqual(
            _SqliteSettingsReader(connection).get_job_statuses("x.mdb"),
            [JobStatus("", "", False, 0)],
        )

    def test_locked_follows_access_yes_no_and_numeric_spellings(self):
        for stored, expected in (
            (0, False),
            (1, True),
            (-1, True),
            ("0", False),
            ("1", True),
            ("True", True),
            ("False", False),
        ):
            with self.subTest(locked=stored):
                connection = self.database(self._DDL)
                connection.execute(
                    "INSERT INTO JobStatuses VALUES (1, 'S', ?, 1)", (stored,)
                )
                (status,) = _SqliteSettingsReader(connection).get_job_statuses("x.mdb")
                self.assertIs(status.locked, expected)

    def test_a_malformed_sequence_degrades_the_status_list_but_fails_the_cover_sheet(
        self,
    ):
        # Characterisation of the current policy for non-numeric Sequence data (only
        # NULL/blank/"NULL" are tolerated), not an endorsement. The standalone status read
        # warns and returns [] (the generic degrade-to-empty policy of the tolerant
        # readers), the cover sheet read surfaces the ValueError. Note the consequence:
        # The status list that ProjectReadService.is_bid_locked searches is then empty;
        # since the lock read fails closed, that bid reads as locked (see
        # test_a_degraded_status_list_makes_the_bid_read_as_locked below).
        connection = self.database(
            self._DDL,
            "INSERT INTO JobStatuses VALUES (1, 'Open', 0, 1)",
            "INSERT INTO JobStatuses VALUES (2, 'Bad', 0, 'abc')",
            "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)",
            "INSERT INTO Bids VALUES (7, 2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        )
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertEqual(
                _SqliteSettingsReader(connection).get_job_statuses("x.mdb"), []
            )
        self.assertEqual(
            logs.records[0].getMessage(), "Could not load job statuses from x.mdb"
        )
        with self.assertRaises(ValueError):
            _FatalReadErrors(connection).get_job_statuses("x.mdb")
        with self.assertRaises(ValueError):
            _SqliteSettingsReader(connection).get_cover_sheet_data("x.mdb", "7")

    def test_a_degraded_status_list_makes_the_bid_read_as_locked(self):
        # End to end through the real status reader: one malformed Sequence degrades
        # the whole list to [], and the lock read must then fail closed.
        from ost_visualizer.application.services.project_read_service import (
            ProjectReadService,
        )

        connection = self.database(
            self._DDL,
            "INSERT INTO JobStatuses VALUES (1, 'Open', 0, 1)",
            "INSERT INTO JobStatuses VALUES (2, 'Locked', 1, 'abc')",
        )
        service = ProjectReadService(_SqliteSettingsReader(connection))
        with self.assertLogs("test", level="WARNING"):
            self.assertIs(service.is_bid_locked("x.mdb", "1"), True)
            self.assertIs(service.is_bid_locked("x.mdb", "2"), True)
        healthy = self.database(
            self._DDL,
            "INSERT INTO JobStatuses VALUES (1, 'Open', 0, 1)",
            "INSERT INTO JobStatuses VALUES (2, 'Locked', 1, 2)",
        )
        service = ProjectReadService(_SqliteSettingsReader(healthy))
        self.assertIs(service.is_bid_locked("x.mdb", "1"), False)
        self.assertIs(service.is_bid_locked("x.mdb", "2"), True)

    def test_a_cover_sheet_with_null_sequences_keeps_the_bid_and_status_links(self):
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER, JobName TEXT)",
            "INSERT INTO Bids VALUES (7, 2, 'Job')",
            "INSERT INTO Bids VALUES (8, NULL, 'Other')",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            self._DDL,
            "INSERT INTO JobStatuses VALUES (2, 'Lost', 0, NULL)",
            "INSERT INTO JobStatuses VALUES (1, 'Open', 0, NULL)",
            "INSERT INTO JobStatuses VALUES (3, 'Won', 1, 2)",
        )
        reader = _SqliteSettingsReader(connection)
        data = reader.get_cover_sheet_data("x.mdb", "7")
        self.assertEqual(data.job_status_uid, "2")
        self.assertEqual(data.job_name, "Job")
        self.assertEqual(data.used_job_status_uids, {"2"})
        self.assertEqual(
            data.job_statuses,
            [
                JobStatus("1", "Open", False, 0),
                JobStatus("2", "Lost", False, 0),
                JobStatus("3", "Won", True, 2),
            ],
        )
        other = reader.get_cover_sheet_data("x.mdb", "8")
        self.assertEqual(other.job_status_uid, "")
        self.assertEqual(other.job_statuses, data.job_statuses)


class JobStatusLockedContractTests(unittest.TestCase):
    """A status whose lock flag cannot be read is locked: fail closed.
    This mirrors the SQL write guard `[Locked] IS NULL OR [Locked]=1` in
    infrastructure/sql/writer.py, so both backends agree on what is locked.
    """

    def read(self, locked_values):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked, Sequence)"
        )
        connection.executemany(
            "INSERT INTO JobStatuses VALUES (?, 'S', ?, 0)",
            list(enumerate(locked_values, start=1)),
        )
        return [
            status.locked
            for status in _SqliteSettingsReader(connection).get_job_statuses("x.mdb")
        ]

    def test_a_null_lock_flag_reads_as_locked(self):
        self.assertEqual(self.read([None]), [True])
        self.assertEqual(self.read(["NULL"]), [True])

    def test_only_blank_zero_and_false_spellings_read_as_unlocked(self):
        self.assertEqual(self.read(["", "0", "False", 0, 0.0]), [False] * 5)

    def test_every_other_lock_flag_reads_as_locked(self):
        self.assertEqual(self.read([1, -1, 2, "1", "True"]), [True] * 5)

    def test_a_missing_lock_column_reads_as_unlocked(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)")
        connection.execute("INSERT INTO JobStatuses VALUES (1, 'S')")
        (status,) = _SqliteSettingsReader(connection).get_job_statuses("x.mdb")
        self.assertIs(status.locked, False)


class CoverSheetFolderTreeTests(unittest.TestCase):
    def test_get_cover_sheet_data_carries_the_folder_tree_and_loose_pages(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for statement in (
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
            "INSERT INTO Bids VALUES (7, 'J')",
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "ParentUID INTEGER)",
            "INSERT INTO BidPageFolders VALUES (1, 7, 'Root', NULL)",
            "INSERT INTO BidPageFolders VALUES (2, 7, 'Child', 1)",
            "INSERT INTO BidPageFolders VALUES (3, 8, 'Other bid', NULL)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "BidPageFolderUID INTEGER, Sequence INTEGER)",
            "INSERT INTO BidPages VALUES (10, 7, 'Nested', 2, 1)",
            "INSERT INTO BidPages VALUES (11, 7, 'Loose', NULL, 2)",
            "INSERT INTO BidPages VALUES (12, 7, 'Root page', 1, 3)",
            "INSERT INTO BidPages VALUES (13, 8, 'Other page', NULL, 1)",
        ):
            connection.execute(statement)
        data = _SqliteSettingsReader(connection).get_cover_sheet_data("x.mdb", "7")
        self.assertEqual(list(data.folders), ["1"])
        root = data.folders["1"]
        self.assertEqual(root.name, "Root")
        self.assertEqual([page.name for page in root.pages], ["Root page"])
        self.assertEqual(list(root.subfolders), ["2"])
        self.assertEqual(root.subfolders["2"].name, "Child")
        self.assertEqual([page.name for page in root.subfolders["2"].pages], ["Nested"])
        self.assertEqual([page.name for page in data.pages_without_folder], ["Loose"])


class ReadErrorLocatorTests(unittest.TestCase):
    """The failing database path is forwarded as the locator of every recorded read error."""

    class _Recording(_FailingOpen):
        def __init__(self, error):
            super().__init__(None)
            self.error = error
            self.recorded = []
            self.logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)

        def _record_caught_read_error(self, exc, locator=None):
            self.recorded.append((exc, locator))
            return False

    def test_every_tolerant_read_records_its_error_against_the_database_path(self):
        calls = (
            ("get_job_statuses", ("a.mdb",)),
            ("get_employees_and_pay_classes", ("a.mdb",)),
            ("get_bid_areas", ("a.mdb", "7")),
            ("get_settings_defaults", ("a.mdb",)),
            ("get_employee_uids_in_use", ("a.mdb",)),
            ("get_condition_type_uids_in_use", ("a.mdb",)),
            ("get_layer_uids_in_use", ("a.mdb", "7")),
        )
        for method, args in calls:
            with self.subTest(method=method):
                error = ValueError("boom")
                reader = self._Recording(error)
                getattr(reader, method)(*args)
                self.assertEqual(len(reader.recorded), 1)
                recorded_error, locator = reader.recorded[0]
                self.assertIs(recorded_error, error)
                self.assertEqual(locator, "a.mdb")


class SettingsReaderRoundTwoBoundaryTests(unittest.TestCase):
    def database(self, *statements):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for statement in statements:
            connection.execute(statement)
        return connection

    def test_each_page_integer_column_is_read_from_its_own_column(self):
        # MultiPageCount, Index1 and Show are independent: a NULL in one must not borrow
        # the NULL-ness (or the value) of another column.
        connection = self.database(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Index1 INTEGER, [Show] INTEGER, MultiPageCount INTEGER, Sequence INTEGER)",
            "INSERT INTO BidPages VALUES (1, 7, 'named', 4, 2, NULL, 1)",
            "INSERT INTO BidPages VALUES (2, 7, NULL, NULL, NULL, 5, 2)",
            "INSERT INTO BidPages VALUES (3, 7, 'full', 3, 1, 6, 3)",
        )
        _folders, pages = _SqliteSettingsReader(connection)._query_cover_sheet_pages(
            _SqliteConnectionWrapper(connection), "7"
        )
        self.assertEqual(
            [(p.name, p.index, p.show_mode, p.multi_page_count) for p in pages],
            [("named", 4, 2, 0), ("", 1, 0, 5), ("full", 3, 1, 6)],
        )

    def test_condition_type_and_layer_usage_reads_tolerate_every_data_error_type(self):
        for method, args, message in (
            (
                "get_condition_type_uids_in_use",
                ("x.mdb",),
                "Could not query condition type UIDs in use: ",
            ),
            (
                "get_layer_uids_in_use",
                ("x.mdb", "1"),
                "Could not query layer UIDs in use: ",
            ),
        ):
            for error in (pyodbc.Error("HY000", "p"), TypeError("t"), ValueError("v")):
                with self.subTest(method=method, error=type(error).__name__):
                    failing = type("R", (_FailingOpen,), {"error": error})
                    with self.assertLogs("test", level="WARNING") as logs:
                        self.assertEqual(getattr(failing(None), method)(*args), set())
                    self.assertTrue(logs.records[0].getMessage().startswith(message))
                    fatal = type("F", (_FailingOpenFatal,), {"error": error})
                    with self.assertRaises(type(error)):
                        getattr(fatal(None), method)(*args)

    def test_missing_pay_class_and_layer_tables_are_reported_as_missing(self):
        reader = _InspectedReader(_FakeConnection({}, {}))
        self.assertEqual(
            reader.get_master_data_uids_in_use("x.mdb", "pay_classes"), set()
        )
        self.assertEqual(
            reader.inspector.report.detected_schema_notes,
            {"missing optional table Employees"},
        )
        reader = _InspectedReader(_FakeConnection({}, {}))
        self.assertEqual(reader.get_layer_uids_in_use("x.mdb", "7"), set())
        self.assertEqual(
            reader.inspector.report.detected_schema_notes,
            {f"missing optional table {table}" for table in LAYER_REFERENCE_TABLES},
        )
