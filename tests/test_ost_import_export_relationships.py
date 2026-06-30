import logging
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pyodbc
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.mdb import database_creator
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.importers.osp_importer import OspImporter
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter

_ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"


def _access_driver_available() -> bool:
    return _ACCESS_DRIVER in pyodbc.drivers()


def _access_conn_str(db_path: Path) -> str:
    return f"DRIVER={{{_ACCESS_DRIVER}}};DBQ={db_path};"


def _connect_access_or_skip(testcase: unittest.TestCase, db_path: Path):
    if not _access_driver_available():
        testcase.skipTest("Microsoft Access ODBC driver is not available")
    try:
        return pyodbc.connect(_access_conn_str(db_path), autocommit=False)
    except pyodbc.OperationalError as exc:
        if "Too many client tasks" in str(exc):
            testcase.skipTest(f"Access ODBC driver is temporarily unavailable: {exc}")
        raise


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _SqliteCursor:
    def __init__(self, connection):
        self._connection = connection
        self._cursor = None
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        try:
            self._cursor = self._connection.execute(query, params)
        except sqlite3.Error as exc:
            raise pyodbc.Error(str(exc)) from exc
        self.description = self._cursor.description
        return self

    def fetchone(self):
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None or self._cursor.description is None:
            return row
        return _named_row(self._cursor.description, row)

    def fetchall(self):
        if self._cursor is None:
            return []
        rows = self._cursor.fetchall()
        if self._cursor.description is None:
            return rows
        return [_named_row(self._cursor.description, row) for row in rows]

    def columns(self, table):
        try:
            rows = self._connection.execute(f"PRAGMA table_info([{table}])").fetchall()
        except sqlite3.Error as exc:
            raise pyodbc.Error(str(exc)) from exc
        return _Rows(
            [SimpleNamespace(column_name=row[1], type_name=row[2]) for row in rows]
        )

    def close(self):
        pass


def _named_row(description, row):
    columns = [column[0] for column in description]
    return namedtuple("SqliteRow", columns, rename=True)(*row)


class _SqliteConnection:
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        return False

    def cursor(self):
        return _SqliteCursor(self._connection)


class _SqliteSchema:
    def __init__(self, connection):
        self._connection = connection

    def optional_table_missing(self, table_name):
        return (
            self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            is None
        )

    def require_table(self, table_name):
        if self.optional_table_missing(table_name):
            raise RuntimeError(f"Missing table {table_name}")

    def column_exists(self, table_name, column_name):
        return any(
            row[1] == column_name
            for row in self._connection.execute(f"PRAGMA table_info([{table_name}])")
        )

    def require_column(self, table_name, column_name):
        if not self.column_exists(table_name, column_name):
            raise RuntimeError(f"Missing column {table_name}.{column_name}")

    def get_columns(self, table_name):
        return {
            row[1]
            for row in self._connection.execute(f"PRAGMA table_info([{table_name}])")
        }

    def log_optional_write_skip(self, _table, _column, _operation):
        pass


class _SqliteMdbWriter(ImportOperationsMixin, PageOperationsMixin):
    logger = logging.getLogger("test")

    def __init__(self, connection):
        self._connection_ref = connection
        self._schema_ref = _SqliteSchema(connection)

    @contextmanager
    def _connection(self, _db_path):
        with _SqliteConnection(self._connection_ref) as connection:
            yield connection

    def _schema(self, _connection):
        return self._schema_ref

    def _require_write_columns(self, schema, table, columns):
        for column in columns:
            schema.require_column(table, column)

    def _next_uid(self, cursor, table):
        cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
        row = cursor.fetchone()
        return int(row[0]) + 1 if row and row[0] is not None else 1

    def _filter_existing_write_values(
        self, schema, table, values, required_columns, operation
    ):
        schema.require_table(table)
        self._require_write_columns(schema, table, required_columns)
        return {
            key: value
            for key, value in values.items()
            if schema.column_exists(table, key)
        }


def _create_import_schema(connection, *, unique_page_selected=False):
    connection.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
    connection.execute("INSERT INTO Settings (NextBidNo) VALUES (1)")
    connection.execute(
        """
        CREATE TABLE Bids (
            UID INTEGER PRIMARY KEY,
            BidProjectUID INTEGER,
            EstimatorUID INTEGER,
            JobName TEXT,
            BidNo INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE Employees (
            UID INTEGER PRIMARY KEY,
            EmployeeNo TEXT,
            FirstName TEXT,
            LastName TEXT,
            PayClassUID INTEGER
        )
        """
    )
    connection.execute("CREATE TABLE PayClasses (UID INTEGER PRIMARY KEY, Name TEXT)")
    connection.execute("CREATE TABLE AccessLevels (UID INTEGER PRIMARY KEY, Name TEXT)")
    connection.execute(
        "CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT, ExpandState INTEGER)"
    )
    connection.execute(
        """
        CREATE TABLE JobStatuses (
            UID INTEGER PRIMARY KEY,
            Name TEXT,
            Locked INTEGER,
            Sequence INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE BidAreas (
            UID INTEGER PRIMARY KEY,
            BidUID INTEGER,
            ParentUID INTEGER,
            Name TEXT,
            Sequence INTEGER,
            GUID TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE BidPages (
            UID INTEGER PRIMARY KEY,
            BidUID INTEGER,
            Name TEXT,
            Sequence INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE BidSettings (
            UID INTEGER PRIMARY KEY,
            BidUID INTEGER,
            BidPageSelectedUID INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE BidPageSettings (
            UID INTEGER PRIMARY KEY,
            BidPageUID INTEGER,
            BidAreaUID INTEGER,
            BidTypAreaUID INTEGER,
            BidAreaSelected INTEGER
        )
        """
    )
    if unique_page_selected:
        connection.execute(
            "CREATE UNIQUE INDEX ux_page_selected "
            "ON BidPageSettings (BidPageUID, BidAreaSelected)"
        )


def _orphan_named_view_hotlink_raw_data() -> RawBidData:
    return RawBidData(
        bid_row={"UID": "1", "JobName": "Exported"},
        bid_tables={
            "BidPages": [
                {"UID": "20", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
            ],
            "BidNamedViews": [
                {"UID": "30", "BidUID": "1", "BidPageUID": "20", "Name": "Valid"},
                {"UID": "31", "BidUID": "1", "BidPageUID": "99", "Name": "Orphan"},
            ],
            "BidHotLinks": [
                {
                    "UID": "40",
                    "BidUID": "1",
                    "BidPageUID": "20",
                    "BidPageViewUID": "30",
                    "Name": "Valid Link",
                },
                {
                    "UID": "41",
                    "BidUID": "1",
                    "BidPageUID": "20",
                    "BidPageViewUID": "31",
                    "Name": "Orphan Target",
                },
                {
                    "UID": "42",
                    "BidUID": "1",
                    "BidPageUID": "99",
                    "BidPageViewUID": "30",
                    "Name": "Orphan Page",
                },
            ],
        },
    )


def _orphan_named_view_hotlink_xml() -> str:
    return """
    <XML_ROOT>
      <Bid UID="1" JobName="Imported">
        <BidPages>
          <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
        </BidPages>
        <BidNamedViews>
          <BidNamedView UID="30" BidUID="1" BidPageUID="20" Name="Valid"/>
          <BidNamedView UID="31" BidUID="1" BidPageUID="99" Name="Orphan"/>
        </BidNamedViews>
        <BidHotLinks>
          <BidHotLink UID="40" BidUID="1" BidPageUID="20"
                      BidPageViewUID="30" Name="Valid Link"/>
          <BidHotLink UID="41" BidUID="1" BidPageUID="20"
                      BidPageViewUID="31" Name="Orphan Target"/>
          <BidHotLink UID="42" BidUID="1" BidPageUID="99"
                      BidPageViewUID="30" Name="Orphan Page"/>
        </BidHotLinks>
      </Bid>
    </XML_ROOT>
    """


class OstImportExportRelationshipTests(unittest.TestCase):
    def test_ost_export_includes_referenced_estimator_employee_and_pay_class(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "EstimatorUID": "7", "JobName": "Bid"},
            bid_tables={"BidConditions": [], "BidPages": []},
            global_tables={
                "Employees": [
                    {
                        "UID": "7",
                        "EmployeeNo": "E100",
                        "FirstName": "Alice",
                        "LastName": "Estimator",
                        "PayClassUID": "3",
                    },
                    {
                        "UID": "8",
                        "EmployeeNo": "E200",
                        "FirstName": "Unused",
                        "LastName": "Employee",
                        "PayClassUID": "4",
                    },
                ],
                "PayClasses": [
                    {"UID": "3", "Name": "Regular"},
                    {"UID": "4", "Name": "Unused"},
                ],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        employee_uids = [
            elem.get("UID") for elem in root.findall("./Employees/Employee")
        ]
        pay_class_uids = [
            elem.get("UID") for elem in root.findall("./PayClasses/PayClass")
        ]
        self.assertEqual(employee_uids, ["7"])
        self.assertEqual(pay_class_uids, ["3"])
        self.assertEqual(root.find("./Bid").get("EstimatorUID"), "7")

    def test_ost_import_remaps_estimator_to_imported_employee(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" EstimatorUID="7" JobName="Imported">
            <BidAreas/>
            <BidPages/>
          </Bid>
          <PayClasses>
            <PayClass UID="3" Name="Regular"/>
          </PayClasses>
          <Employees>
            <Employee UID="7" EmployeeNo="E100" FirstName="Alice"
                      LastName="Estimator" PayClassUID="3"/>
          </Employees>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        connection.execute(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName, LastName) "
            "VALUES (7, 'EXISTING', 'Existing', 'Employee')"
        )
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                OstImporter(writer).import_ost(str(ost_path), "target.mdb", "5")
            )
        imported_employee = connection.execute(
            "SELECT UID, PayClassUID FROM Employees WHERE EmployeeNo='E100'"
        ).fetchone()
        imported_pay_class = connection.execute(
            "SELECT UID FROM PayClasses WHERE Name='Regular'"
        ).fetchone()
        imported_bid = connection.execute(
            "SELECT BidProjectUID, EstimatorUID FROM Bids WHERE JobName='Imported'"
        ).fetchone()
        self.assertIsNotNone(imported_employee)
        self.assertIsNotNone(imported_pay_class)
        self.assertEqual(imported_employee[1], imported_pay_class[0])
        self.assertEqual(imported_bid, (5, imported_employee[0]))

    def test_ost_import_remaps_bid_settings_selected_page_to_imported_page(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="20"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        page_uid = connection.execute(
            "SELECT UID FROM BidPages WHERE Name='Sheet'"
        ).fetchone()[0]
        selected_uid = connection.execute(
            "SELECT BidPageSelectedUID FROM BidSettings"
        ).fetchone()[0]
        self.assertEqual(selected_uid, page_uid)

    def test_ost_import_clears_missing_bid_settings_selected_page(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="999"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        selected_uid = connection.execute(
            "SELECT BidPageSelectedUID FROM BidSettings"
        ).fetchone()[0]
        self.assertIsNone(selected_uid)

    def test_ost_import_clears_zero_blank_and_invalid_selected_page(self):
        for selected_value in ("0", "", "not-a-uid"):
            with self.subTest(selected_value=selected_value):
                xml = f"""
                <XML_ROOT>
                  <Bid UID="1" JobName="Imported">
                    <BidSettings>
                      <BidSetting UID="30" BidUID="1"
                                  BidPageSelectedUID="{selected_value}"/>
                    </BidSettings>
                    <BidPages>
                      <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
                    </BidPages>
                  </Bid>
                </XML_ROOT>
                """
                connection = sqlite3.connect(":memory:")
                _create_import_schema(connection)
                writer = _SqliteMdbWriter(connection)
                with tempfile.TemporaryDirectory() as temp_dir:
                    ost_path = Path(temp_dir) / "import.ost"
                    ost_path.write_text(xml, encoding="utf-8")
                    self.assertTrue(
                        OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                    )
                selected_uid = connection.execute(
                    "SELECT BidPageSelectedUID FROM BidSettings"
                ).fetchone()[0]
                self.assertIsNone(selected_uid)

    def test_ost_import_does_not_insert_stale_source_selected_page_uid(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="999"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        stale_count = connection.execute(
            "SELECT COUNT(*) FROM BidSettings WHERE BidPageSelectedUID=999"
        ).fetchone()[0]
        self.assertEqual(stale_count, 0)

    def test_access_import_clears_old_ost_missing_selected_page_reference(self):
        if not _access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        xml = """
        <XML_ROOT>
          <Bid UID="757" JobName="Imported">
            <BidSettings>
              <BidSetting UID="740" BidUID="757" BidPageSelectedUID="138631"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="138791" BidUID="757" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            ost_path = temp_path / "old_shape.ost"
            db_path = temp_path / "old_shape.mdb"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                database_creator.DatabaseCreator().create_database(db_path, "Old Shape")
            )
            writer = MdbWriter()
            try:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), str(db_path))
                )
            finally:
                writer._conn_manager.close()
            conn = _connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT [BidPageSelectedUID] FROM [BidSettings]")
                self.assertIsNone(cursor.fetchone()[0])
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_access_import_handles_new_ost_zero_bid_settings_uid(self):
        if not _access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="0" BidUID="1" BidPageSelectedUID="0"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            ost_path = temp_path / "new_shape.ost"
            db_path = temp_path / "new_shape.mdb"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                database_creator.DatabaseCreator().create_database(db_path, "New Shape")
            )
            writer = MdbWriter()
            try:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), str(db_path))
                )
            finally:
                writer._conn_manager.close()
            conn = _connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT [UID], [BidPageSelectedUID] FROM [BidSettings]")
                row = cursor.fetchone()
                self.assertIsNotNone(row[0])
                self.assertIsNone(row[1])
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_database_creator_enforces_nullable_bid_settings_page_relationship(self):
        if not _access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "relationship.mdb"
            if not database_creator.DatabaseCreator().create_database(
                db_path, "Relationship"
            ):
                self.skipTest("Could not create an Access test database")
            conn = _connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO [Bids] ([UID], [JobName]) VALUES (?, ?)", 100, "Bid"
                )
                cursor.execute(
                    "INSERT INTO [BidSettings] ([BidUID], [BidPageSelectedUID]) "
                    "VALUES (?, ?)",
                    100,
                    None,
                )
                with self.assertRaises(pyodbc.IntegrityError):
                    cursor.execute(
                        "INSERT INTO [BidSettings] "
                        "([BidUID], [BidPageSelectedUID]) VALUES (?, ?)",
                        100,
                        999,
                    )
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_access_bid_delete_clears_cross_bid_selected_page_reference(self):
        if not _access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "delete_cross_bid_selected_page.mdb"
            if not database_creator.DatabaseCreator().create_database(
                db_path, "Delete Relationship"
            ):
                self.skipTest("Could not create an Access test database")
            conn = _connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO [Bids] ([UID], [JobName]) VALUES (?, ?)",
                    100,
                    "Delete Me",
                )
                cursor.execute(
                    "INSERT INTO [Bids] ([UID], [JobName]) VALUES (?, ?)",
                    200,
                    "Keep Me",
                )
                cursor.execute(
                    "INSERT INTO [BidPages] ([UID], [BidUID], [Name]) "
                    "VALUES (?, ?, ?)",
                    300,
                    100,
                    "Selected Elsewhere",
                )
                cursor.execute(
                    "INSERT INTO [BidSettings] ([BidUID], [BidPageSelectedUID]) "
                    "VALUES (?, ?)",
                    200,
                    300,
                )
                conn.commit()
            finally:
                cursor.close()
                conn.close()
            writer = MdbWriter()
            try:
                self.assertTrue(writer.delete_bids(str(db_path), ["100"]))
            finally:
                writer._conn_manager.close()
            conn = _connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM [Bids] WHERE [UID]=100")
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute("SELECT COUNT(*) FROM [BidPages] WHERE [UID]=300")
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT [BidPageSelectedUID] FROM [BidSettings] "
                    "WHERE [BidUID]=200"
                )
                self.assertIsNone(cursor.fetchone()[0])
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_osp_export_import_preserves_valid_selected_page_reference(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Imported"},
            bid_tables={
                "BidSettings": [{"UID": "2", "BidUID": "1", "BidPageSelectedUID": "3"}],
                "BidPages": [
                    {"UID": "3", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
                ],
            },
        )
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            osp_path = Path(temp_dir) / "roundtrip.osp"
            exporter = OspExporter(
                SimpleNamespace(),
                "test",
                lambda _uom_service: OstExporter(SimpleNamespace()),
            )
            result = exporter.export(raw_data, str(osp_path), bid_name="Roundtrip")
            self.assertTrue(result.success, result.error_message)
            self.assertTrue(
                OspImporter(OstImporter(writer)).import_osp(str(osp_path), "target.mdb")
            )
        page_uid = connection.execute(
            "SELECT UID FROM BidPages WHERE Name='Sheet'"
        ).fetchone()[0]
        selected_uid = connection.execute(
            "SELECT BidPageSelectedUID FROM BidSettings"
        ).fetchone()[0]
        self.assertEqual(selected_uid, page_uid)

    def test_ost_import_rejects_named_views_and_hotlinks_for_missing_pages(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys=ON")
        _create_import_schema(connection)
        connection.execute(
            """
            CREATE TABLE BidNamedViews (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER REFERENCES BidPages(UID),
                Name TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE BidHotLinks (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER REFERENCES BidPages(UID),
                BidPageViewUID INTEGER REFERENCES BidNamedViews(UID),
                Name TEXT
            )
            """
        )
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(_orphan_named_view_hotlink_xml(), encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("invalid page references", logs.output[0])
        bid_count = connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0]
        named_view_count = connection.execute(
            "SELECT COUNT(*) FROM BidNamedViews"
        ).fetchone()[0]
        hotlink_count = connection.execute(
            "SELECT COUNT(*) FROM BidHotLinks"
        ).fetchone()[0]
        self.assertEqual((bid_count, named_view_count, hotlink_count), (0, 0, 0))

    def test_ost_export_skips_named_views_and_hotlinks_for_missing_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid.ost"
            result = OstExporter(SimpleNamespace()).export(
                _orphan_named_view_hotlink_raw_data(),
                str(output_path),
            )
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        named_view_names = [
            elem.get("Name")
            for elem in root.findall("./Bid/BidNamedViews/BidNamedView")
        ]
        hotlink_names = [
            elem.get("Name") for elem in root.findall("./Bid/BidHotLinks/BidHotLink")
        ]
        self.assertEqual(named_view_names, ["Valid"])
        self.assertEqual(hotlink_names, ["Valid Link"])

    def test_save_page_area_handles_duplicate_selected_settings_rows(self):
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection, unique_page_selected=True)
        connection.execute("INSERT INTO Bids (UID, JobName) VALUES (1, 'Bid')")
        connection.execute(
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (20, 1, 'Sheet')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (10, 1, 'Area 1')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (11, 1, 'Area 2')"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (1, 20, 10, 1)"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (2, 20, 11, 2)"
        )
        writer = _SqliteMdbWriter(connection)
        self.assertTrue(writer.save_page_area("target.mdb", "20", "11"))
        rows = connection.execute(
            "SELECT BidAreaUID, BidAreaSelected FROM BidPageSettings "
            "WHERE BidPageUID=20 ORDER BY UID"
        ).fetchall()
        self.assertEqual(rows, [(11, 2)])

    def test_import_canonicalizes_duplicate_page_area_selection_then_save_succeeds(
        self,
    ):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidAreas>
              <BidArea UID="10" BidUID="1" Name="Area 1" Sequence="1"/>
              <BidArea UID="11" BidUID="1" Name="Area 2" Sequence="2"/>
            </BidAreas>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidPageSettings>
                  <BidPageSetting UID="30" BidPageUID="20"
                                  BidAreaUID="10" BidAreaSelected="1"/>
                  <BidPageSetting UID="31" BidPageUID="20"
                                  BidAreaUID="11" BidAreaSelected="2"/>
                </BidPageSettings>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection, unique_page_selected=True)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        page_uid = connection.execute(
            "SELECT UID FROM BidPages WHERE Name='Sheet'"
        ).fetchone()[0]
        selected_count = connection.execute(
            "SELECT COUNT(*) FROM BidPageSettings "
            "WHERE BidPageUID=? AND BidAreaSelected > 0",
            (page_uid,),
        ).fetchone()[0]
        area_uid = connection.execute(
            "SELECT UID FROM BidAreas WHERE Name='Area 2'"
        ).fetchone()[0]
        self.assertEqual(selected_count, 1)
        self.assertTrue(
            writer.save_page_area("target.mdb", str(page_uid), str(area_uid))
        )

    def test_access_page_area_insert_uses_explicit_uid_after_imported_uid_gap(self):
        if not _access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        settings = [
            (86, 451, 81),
            (87, 450, 82),
            (88, 449, 83),
            (89, 448, 84),
            (90, 447, 85),
            (91, 444, 86),
            (92, 440, 87),
            (93, 436, 88),
            (94, 428, 89),
            (906, 183, 0),
            (907, 409, 94),
            (908, 410, 93),
            (909, 417, 92),
            (910, 418, 91),
            (911, 424, 90),
        ]
        page_uids = sorted({452} | {page_uid for _uid, page_uid, _area in settings})
        pages = []
        for page_uid in page_uids:
            nested = []
            for uid, settings_page_uid, area_uid in settings:
                if settings_page_uid != page_uid:
                    continue
                area_attr = "" if area_uid == 0 else f' BidAreaUID="{area_uid}"'
                nested.append(
                    f'<BidPageSetting UID="{uid}" BidPageUID="{settings_page_uid}"'
                    f'{area_attr} BidAreaSelected="2"/>'
                )
            if nested:
                pages.append(
                    f'<BidPage UID="{page_uid}" BidUID="80" Name="P{page_uid}">'
                    f'<BidPageSettings>{"".join(nested)}</BidPageSettings>'
                    f"</BidPage>"
                )
            else:
                pages.append(
                    f'<BidPage UID="{page_uid}" BidUID="80" Name="P{page_uid}"/>'
                )
        areas = "".join(
            f'<BidArea UID="{area_uid}" BidUID="80" Name="A{area_uid}" '
            f'Sequence="{area_uid}"/>'
            for area_uid in range(81, 95)
        )
        xml = (
            '<XML_ROOT><Bid UID="80" JobName="Mini">'
            f"<BidAreas>{areas}</BidAreas>"
            f'<BidPages>{"".join(pages)}</BidPages>'
            "</Bid></XML_ROOT>"
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            ost_path = temp_path / "mini.ost"
            db_path = temp_path / "mini.mdb"
            ost_path.write_text(xml, encoding="utf-8")
            if not database_creator.DatabaseCreator().create_database(db_path, "Mini"):
                self.skipTest("Could not create an Access test database")
            writer = MdbWriter()
            try:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), str(db_path))
                )
            finally:
                writer._conn_manager.close()
            conn = _connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT [UID] FROM [BidPages] WHERE [Name]='P452'")
                page_uid = int(cursor.fetchone()[0])
                with self.assertRaises(pyodbc.IntegrityError):
                    cursor.execute(
                        "INSERT INTO [BidPageSettings] "
                        "([BidPageUID], [BidAreaUID], [BidAreaSelected]) "
                        "VALUES (?, NULL, 1)",
                        page_uid,
                    )
                conn.rollback()
            finally:
                cursor.close()
                conn.close()
            writer = MdbWriter()
            try:
                self.assertTrue(writer.save_page_area(str(db_path), str(page_uid), "0"))
            finally:
                writer._conn_manager.close()
            conn = _connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT [UID], [BidAreaUID], [BidAreaSelected] "
                    "FROM [BidPageSettings] WHERE [BidPageUID]=?",
                    page_uid,
                )
                row = cursor.fetchone()
                self.assertEqual((int(row[0]), row[1], int(row[2])), (42, None, 1))
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_database_creator_does_not_add_non_ost_page_area_selection_uniqueness(self):
        class FakeCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql):
                self.calls.append(sql)

            def close(self):
                pass

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect
        database_creator.pyodbc.connect = (
            lambda *_args, **_call_options: fake_connection
        )
        try:
            database_creator.DatabaseCreator()._create_schema(Path("test.mdb"))
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertNotIn(
            "CREATE UNIQUE INDEX [UI_BidPageSettings_PageSelected] "
            "ON [BidPageSettings] ([BidPageUID], [BidAreaSelected])",
            fake_connection.cursor_instance.calls,
        )


if __name__ == "__main__":
    unittest.main()
