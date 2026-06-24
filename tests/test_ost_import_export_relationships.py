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
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter


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

    def test_database_creator_defines_page_area_selection_uniqueness(self):
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
        database_creator.pyodbc.connect = lambda *_args, **_kwargs: fake_connection
        try:
            database_creator.DatabaseCreator()._create_schema(Path("test.mdb"))
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertIn(
            "CREATE UNIQUE INDEX [UI_BidPageSettings_PageSelected] "
            "ON [BidPageSettings] ([BidPageUID], [BidAreaSelected])",
            fake_connection.cursor_instance.calls,
        )


if __name__ == "__main__":
    unittest.main()
