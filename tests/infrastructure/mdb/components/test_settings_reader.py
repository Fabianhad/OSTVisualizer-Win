from ost_visualizer.domain.entities.cover_sheet import CoverSheetPage
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
import sqlite3
import logging
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
