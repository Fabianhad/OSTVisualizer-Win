import logging
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
import pyodbc
from ost_visualizer.application.interfaces.i_uom_service import IUOMService
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.database.settings_cardinality import (
    BidNumberAllocationUnavailableError,
    GlobalSettingsCardinalityError,
)
from ost_visualizer.infrastructure.mdb import database_creator
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.mdb.importers import (
    osp_importer as osp_importer_module,
)
from ost_visualizer.infrastructure.mdb.importers.osp_importer import OspImporter
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    RAW_BID_RELATIONSHIPS,
    prepare_raw_bid_data_for_export,
    validate_raw_bid_integrity,
)
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from ost_visualizer.infrastructure.mdb.schema_contract import (
    BID_SECTIONS,
    BID_TAIL_SECTIONS,
    GLOBAL_SECTIONS,
    PAGE_SECTIONS,
)
from ost_visualizer.infrastructure.parsers.ost_serializer import serialize_value
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from ost_visualizer.presentation.visualization.exporters import ost_cab
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
            raise UnsupportedMdbSchemaError(
                f"This OST database is missing required table {table_name} "
                "and cannot be loaded."
            )

    def column_exists(self, table_name, column_name):
        return any(
            row[1] == column_name
            for row in self._connection.execute(f"PRAGMA table_info([{table_name}])")
        )

    def require_column(self, table_name, column_name):
        if not self.column_exists(table_name, column_name):
            raise UnsupportedMdbSchemaError(
                "This OST database is missing required column "
                f"{table_name}.{column_name} and cannot be loaded."
            )

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

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False

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


class _CapturingImportWriter:
    def __init__(self):
        self.takeoffs = ()
        self.called = False

    def import_ost_data(
        self,
        _target_db_path,
        raw_data,
        _transform,
        _target_project_uid,
    ):
        self.called = True
        self.takeoffs = tuple(
            (row["UID"], row.get("ParentUID", "0"), row.get("Name", ""))
            for row in raw_data.page_tables.get("BidTakeoffs", [])
        )
        return True


def _create_import_schema(
    connection, *, unique_page_selected=False, next_bid_numbers=(1,)
):
    connection.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
    connection.executemany(
        "INSERT INTO Settings (NextBidNo) VALUES (?)",
        ((value,) for value in next_bid_numbers),
    )
    connection.execute(
        """
        CREATE TABLE Bids (
            UID INTEGER PRIMARY KEY,
            BidProjectUID INTEGER,
            EstimatorUID INTEGER,
            JobStatusUID INTEGER,
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
                    "UID": "43",
                    "BidUID": "1",
                    "BidPageUID": "20",
                    "BidPageViewUID": "30",
                    "BidLayerUID": "99",
                    "Name": "Orphan Layer",
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


def _reference_shape_export_raw_data() -> RawBidData:
    return RawBidData(
        bid_row={
            "UID": "1",
            "JobName": "Reference Shape",
            "EstimatorUID": "2",
            "JobStatusUID": "79",
        },
        bid_tables={
            "BidConditions": [
                {
                    "UID": "10",
                    "BidUID": "1",
                    "CdnTypeUID": "7",
                    "Name": "Area",
                    "Type": "2",
                    "Width": "0",
                    "Height": "0",
                    "Depth": "0",
                    "Quantity1": "0",
                    "Quantity2": "0",
                    "Quantity3": "0",
                    "UOM1": "0",
                    "UOM2": "0",
                    "UOM3": "0",
                }
            ],
            "BidPages": [
                {
                    "UID": "20",
                    "BidUID": "1",
                    "Name": "Sheet",
                    "Sequence": "1",
                    "CurrentX": serialize_value(2302.4439862543),
                    "CurrentY": serialize_value(1725.01718213058),
                }
            ],
            "BidNamedViews": [
                {
                    "UID": "31",
                    "BidUID": "1",
                    "BidPageUID": "20",
                    "Name": "Second",
                    "Position": "B",
                    "Color": "",
                    "Origin": "",
                },
                {
                    "UID": "30",
                    "BidUID": "1",
                    "BidPageUID": "20",
                    "Name": "First",
                    "Position": "A",
                    "Color": "",
                    "Origin": "",
                },
            ],
            "BidHotLinks": [
                {
                    "UID": "40",
                    "BidUID": "1",
                    "BidPageUID": "20",
                    "BidPageViewUID": "30",
                    "Position": "A",
                },
                {
                    "UID": "41",
                    "BidUID": "1",
                    "BidPageUID": "20",
                    "BidPageViewUID": "31",
                    "Position": "B",
                },
            ],
        },
        global_tables={
            "Employees": [
                {
                    "UID": "2",
                    "PayClassUID": "",
                    "AccessLevelUID": "",
                    "EmployeeNo": "",
                    "FirstName": "Ada",
                    "LastName": "Lovelace",
                    "EnableLogin": "0",
                    "LoginName": "",
                    "Password": "0",
                    "Address1": "",
                    "Address2": "",
                    "City": "",
                    "State": "",
                    "Zip": "",
                    "HomePhone": "",
                    "MobilePhone": "",
                    "EMail": "",
                }
            ],
            "CdnTypes": [{"UID": "7", "Name": "Area", "ExpandState": "0"}],
            "JobStatuses": [
                {"UID": "79", "Locked": "0", "Name": "Pending", "Sequence": "9"}
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
          <BidHotLink UID="43" BidUID="1" BidPageUID="20"
                      BidPageViewUID="30" BidLayerUID="99"
                      Name="Orphan Layer"/>
          <BidHotLink UID="41" BidUID="1" BidPageUID="20"
                      BidPageViewUID="31" Name="Orphan Target"/>
          <BidHotLink UID="42" BidUID="1" BidPageUID="99"
                      BidPageViewUID="30" Name="Orphan Page"/>
        </BidHotLinks>
      </Bid>
    </XML_ROOT>
    """


def _raw_data_with_row(table_name, row):
    raw_data = RawBidData()
    if table_name == "Bids":
        raw_data.bid_row = row
    elif table_name in GLOBAL_SECTIONS:
        raw_data.global_tables[table_name] = [row]
    elif table_name in PAGE_SECTIONS:
        raw_data.page_tables[table_name] = [row]
    elif table_name in BID_SECTIONS or table_name in BID_TAIL_SECTIONS:
        raw_data.bid_tables[table_name] = [row]
    elif table_name == "BidPages":
        raw_data.bid_tables["BidPages"] = [row]
    else:
        raw_data.bid_tables[table_name] = [row]
    return raw_data
