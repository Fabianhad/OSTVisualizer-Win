import logging
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
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
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    RAW_BID_RELATIONSHIPS,
    prepare_raw_bid_data_for_export,
    validate_raw_bid_integrity,
)
from ost_visualizer.infrastructure.mdb.schema_contract import (
    BID_SECTIONS,
    BID_TAIL_SECTIONS,
    GLOBAL_SECTIONS,
    PAGE_SECTIONS,
)
from ost_visualizer.infrastructure.parsers.ost_serializer import serialize_value
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter
from ost_visualizer.presentation.visualization.exporters import ost_cab

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

    def import_ost_data(
        self,
        _target_db_path,
        raw_data,
        _transform,
        _target_project_uid,
    ):
        self.takeoffs = tuple(
            (row["UID"], row.get("ParentUID", "0"), row.get("Name", ""))
            for row in raw_data.page_tables.get("BidTakeoffs", [])
        )
        return True


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


class OstImportExportRelationshipTests(unittest.TestCase):
    def test_sql_import_mutation_records_every_authoritative_family(self):
        value = {
            "project_uids": {"target": "9"},
            "bid_uids": {"1": "10"},
            "page_uids": {"2": "20"},
            "condition_uids": {"3": "30"},
            "layer_uids": {"4": "40"},
            "area_uids": {"5": "50"},
            "takeoff_uids": {"6": "60"},
            "annotation_uids": {"7": "70"},
            "table_uid_maps": {},
            "global_uid_maps": {},
        }
        writer = SimpleNamespace(import_ost_data=lambda *_args: value)
        importer = OstImporter(writer)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "CdnTypes": [{"UID": "1"}],
                "JobStatuses": [{"UID": "2"}],
                "Employees": [{"UID": "3"}],
                "PayClasses": [{"UID": "4"}],
            },
        )
        records = []
        recorder = SimpleNamespace(
            record=lambda resource, operation, **_kwargs: records.append(
                (resource, operation)
            )
        )
        with patch.object(importer, "_validated_raw_data", return_value=raw_data):
            result = importer.import_ost_mutation(
                "source.ost", "database", "9", recorder
            )
        self.assertIs(result, value)
        self.assertEqual(
            {resource.resource_type for resource, _operation in records},
            {
                "bid",
                "project_bids",
                "conditions_collection",
                "areas_collection",
                "pages_collection",
                "layers_collection",
                "takeoffs_collection",
                "annotations_collection",
                "cover_sheet",
                "condition_types_collection",
                "job_statuses_collection",
                "employees_collection",
                "pay_classes_collection",
            },
        )

    def test_ost_import_restores_database_column_name_for_copy_timestamp(self):
        xml = '<XML_ROOT><Bid UID="1" CopyTimestamp="2026 7 19 0 39 2"/></XML_ROOT>'
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "copy_timestamp.ost"
            ost_path.write_text(xml, encoding="utf-8")
            raw_data = OstImporter(object())._parse_ost_xml(str(ost_path))
        self.assertEqual(raw_data.bid_row["CopyTimeStamp"], "2026 7 19 0 39 2")
        self.assertNotIn("CopyTimestamp", raw_data.bid_row)

    def test_raw_bid_integrity_map_reports_each_declared_relationship(self):
        for relationship in RAW_BID_RELATIONSHIPS:
            with self.subTest(
                table=relationship.child_table,
                column=relationship.child_column,
                parent=relationship.parent_table,
            ):
                raw_data = _raw_data_with_row(
                    relationship.child_table,
                    {"UID": "1", relationship.child_column: "999"},
                )
                issues = validate_raw_bid_integrity(raw_data)
                self.assertTrue(
                    any(
                        issue.table == relationship.child_table
                        and issue.column == relationship.child_column
                        and issue.missing_uid == "999"
                        and issue.parent_table == relationship.parent_table
                        for issue in issues
                    ),
                    issues,
                )

    def test_prepare_export_prunes_named_views_and_hotlinks_for_missing_pages(self):
        prepared = prepare_raw_bid_data_for_export(
            _orphan_named_view_hotlink_raw_data()
        )
        self.assertEqual(
            [row["Name"] for row in prepared.bid_tables["BidNamedViews"]],
            ["Valid"],
        )
        self.assertEqual(
            [row["Name"] for row in prepared.bid_tables["BidHotLinks"]],
            ["Valid Link"],
        )
        self.assertEqual(validate_raw_bid_integrity(prepared), [])

    def test_ost_import_skips_orphaned_takeoffs_and_cascading_children(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions>
              <BidCondition UID="10" BidUID="1" Name="Footing"/>
            </BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="Primary"/>
                  <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="30"
                              Name="Valid Child"/>
                  <BidTakeoff UID="32" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="999"
                              Name="Orphan"/>
                  <BidTakeoff UID="33" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="32"
                              Name="Cascading Orphan"/>
                  <BidTakeoff UID="34" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="33"
                              Name="Nested Cascading Orphan"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        connection.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        connection.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "orphan_takeoffs.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="WARNING",
            ) as logs:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        takeoffs = connection.execute(
            "SELECT UID, ParentUID, Name FROM BidTakeoffs ORDER BY Name"
        ).fetchall()
        self.assertEqual([row[2] for row in takeoffs], ["Primary", "Valid Child"])
        takeoff_uids = {row[2]: row[0] for row in takeoffs}
        parent_uids = {row[2]: row[1] for row in takeoffs}
        self.assertIsNone(parent_uids["Primary"])
        self.assertEqual(parent_uids["Valid Child"], takeoff_uids["Primary"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("missing-parent roots", logs.output[0])
        self.assertIn("BidTakeoffs.UID=32 ParentUID=999", logs.output[0])
        self.assertIn("skipped dependent descendants", logs.output[0])
        self.assertIn("BidTakeoffs.UID=33 ParentUID=32", logs.output[0])
        self.assertIn("BidTakeoffs.UID=34 ParentUID=33", logs.output[0])

    def test_ost_import_resolves_child_before_parent_after_full_parse(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="30" Name="Child"/>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="Parent"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        connection.execute(
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER)"
        )
        connection.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidUID INTEGER, "
            "BidPageUID INTEGER, BidConditionUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "child_first.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                OstImporter(_SqliteMdbWriter(connection)).import_ost(
                    str(ost_path), "target.mdb"
                )
            )
        rows = connection.execute(
            "SELECT UID, ParentUID, Name FROM BidTakeoffs ORDER BY Name"
        ).fetchall()
        by_name = {name: (uid, parent_uid) for uid, parent_uid, name in rows}
        self.assertEqual(by_name["Child"][1], by_name["Parent"][0])

    def test_ost_import_rejects_duplicate_takeoff_uid_before_remapping(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="First"/>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="Duplicate"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "duplicate_takeoff.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("BidTakeoffs.UID=30 occurs 2 times", logs.output[0])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_ost_import_rejects_duplicate_page_uid_before_backend_remapping(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="First"/>
              <BidPage UID="20" BidUID="1" Name="Duplicate"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        writer = _CapturingImportWriter()
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "duplicate_page.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("BidPages.UID=20 occurs 2 times", logs.output[0])
        self.assertEqual(writer.takeoffs, ())

    def test_ost_import_rejects_malformed_takeoff_uid_before_remapping(self):
        cases = (
            (
                'UID="not-a-uid"',
                "BidTakeoffs.UID=not-a-uid has malformed UID=not-a-uid",
            ),
            (
                'UID="30" ParentUID="not-a-uid"',
                "BidTakeoffs.UID=30 has malformed ParentUID=not-a-uid",
            ),
        )
        for takeoff_identity, expected_diagnostic in cases:
            with self.subTest(takeoff_identity=takeoff_identity):
                xml = f"""
                <XML_ROOT>
                  <Bid UID="1" JobName="Imported">
                    <BidConditions>
                      <BidCondition UID="10" BidUID="1"/>
                    </BidConditions>
                    <BidPages>
                      <BidPage UID="20" BidUID="1" Name="Sheet">
                        <BidTakeoffs>
                          <BidTakeoff {takeoff_identity} BidUID="1"
                                      BidPageUID="20" BidConditionUID="10"/>
                        </BidTakeoffs>
                      </BidPage>
                    </BidPages>
                  </Bid>
                </XML_ROOT>
                """
                writer = _CapturingImportWriter()
                with tempfile.TemporaryDirectory() as temp_dir:
                    ost_path = Path(temp_dir) / "malformed_takeoff_uid.ost"
                    ost_path.write_text(xml, encoding="utf-8")
                    with self.assertLogs(
                        "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                        level="ERROR",
                    ) as logs:
                        self.assertFalse(
                            OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                        )
                self.assertIn(expected_diagnostic, logs.output[0])
                self.assertEqual(writer.takeoffs, ())

    def test_ost_import_rejects_takeoff_parent_cycle(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="31"/>
                  <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="30"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "takeoff_cycle.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("participates in a ParentUID cycle", logs.output[0])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_access_and_sql_writers_receive_same_pruned_takeoff_graph(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="30" Name="Child"/>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="Parent"/>
                  <BidTakeoff UID="32" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="999" Name="Orphan"/>
                  <BidTakeoff UID="33" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="32" Name="Descendant"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        captured_graphs = []
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "backend_neutral_graph.ost"
            ost_path.write_text(xml, encoding="utf-8")
            for writer_type in (MdbWriter, SqlProjectWriter):
                with self.subTest(writer_type=writer_type.__name__), self.assertLogs(
                    "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                    level="WARNING",
                ):
                    writer = writer_type.__new__(writer_type)
                    captured = _CapturingImportWriter()
                    writer.import_ost_data = captured.import_ost_data
                    self.assertTrue(
                        OstImporter(writer).import_ost(
                            str(ost_path), f"{writer_type.__name__}-target"
                        )
                    )
                    captured_graphs.append(captured.takeoffs)
        self.assertEqual(captured_graphs[0], captured_graphs[1])
        self.assertEqual(
            captured_graphs[0],
            (("31", "30", "Child"), ("30", "0", "Parent")),
        )

    def test_export_prunes_orphan_takeoff_graph_and_keeps_valid_graph(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Exported"},
            bid_tables={
                "BidConditions": [{"UID": "10", "BidUID": "1"}],
                "BidPages": [{"UID": "20", "BidUID": "1"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "Name": "Parent",
                    },
                    {
                        "UID": "31",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "ParentUID": "30",
                        "Name": "Child",
                    },
                    {
                        "UID": "32",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "ParentUID": "999",
                        "Name": "Orphan",
                    },
                    {
                        "UID": "33",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "ParentUID": "32",
                        "Name": "Descendant",
                    },
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "takeoff_graph.ost"
            result = OstExporter(
                SimpleNamespace(
                    calculate_condition_quantities=lambda **_kwargs: (0.0, 0.0, 0.0)
                )
            ).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            takeoffs = (
                ET.parse(output_path)
                .getroot()
                .findall("./Bid/BidPages/BidPage/BidTakeoffs/BidTakeoff")
            )
        self.assertEqual(
            {takeoff.get("Name") for takeoff in takeoffs}, {"Parent", "Child"}
        )
        by_name = {takeoff.get("Name"): takeoff for takeoff in takeoffs}
        self.assertEqual(
            by_name["Child"].get("ParentUID"), by_name["Parent"].get("UID")
        )
        self.assertEqual(
            [row["Name"] for row in raw_data.page_tables["BidTakeoffs"]],
            ["Parent", "Child", "Orphan", "Descendant"],
        )

    def test_ost_import_rejects_takeoff_missing_required_condition(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "missing_condition.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("BidConditionUID=<missing>", logs.output[0])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_ost_import_clears_missing_annotation_takeoff_attachments(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidDimensions>
                  <BidDimension UID="31" BidUID="1" BidPageUID="20"
                                BidTakeoffFromUID="901" BidTakeoffToUID="902"
                                Position="dimension-geometry"/>
                </BidDimensions>
                <BidArrows>
                  <BidArrow UID="32" BidUID="1" BidPageUID="20"
                            BidTakeoffFromUID="903" BidTakeoffToUID="904"
                            Position="arrow-geometry"/>
                </BidArrows>
                <BidALines>
                  <BidALine UID="33" BidUID="1" BidPageUID="20"
                            BidTakeoffFromUID="905" BidTakeoffToUID="906"
                            Position="line-geometry"/>
                </BidALines>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        for table in ("BidDimensions", "BidArrows", "BidALines"):
            connection.execute(
                f"CREATE TABLE {table} ("
                "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
                "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER, Position TEXT)"
            )
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "missing_annotation_attachments.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="WARNING",
            ) as logs:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        expected_geometry = {
            "BidDimensions": "dimension-geometry",
            "BidArrows": "arrow-geometry",
            "BidALines": "line-geometry",
        }
        for table, geometry in expected_geometry.items():
            with self.subTest(table=table):
                row = connection.execute(
                    f"SELECT BidTakeoffFromUID, BidTakeoffToUID, Position "
                    f"FROM {table}"
                ).fetchone()
                self.assertEqual(row, (None, None, geometry))
        warning = logs.output[0]
        self.assertIn("6 missing annotation takeoff attachment reference(s)", warning)
        for uid in range(901, 907):
            self.assertIn(f"={uid} missing BidTakeoffs.UID", warning)

    def test_ost_import_still_rejects_takeoff_with_missing_condition(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions/>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="999" Name="Unsafe Orphan"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        connection.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        connection.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "missing_condition.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("BidTakeoffs.UID=30 BidConditionUID=999", logs.output[0])
        bid_count = connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0]
        self.assertEqual(bid_count, 0)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 0
        )

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

    def test_ost_export_writes_bid_layers_by_descending_uid(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={
                "BidLayers": [
                    {"UID": "12", "BidUID": "1", "Name": "High", "Sequence": "20"},
                    {"UID": "10", "BidUID": "1", "Name": "Low", "Sequence": "0"},
                    {"UID": "11", "BidUID": "1", "Name": "Mid", "Sequence": "10"},
                ],
                "BidConditions": [],
                "BidPages": [],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        layers = root.findall("./Bid/BidLayers/BidLayer")
        self.assertEqual([layer.get("UID") for layer in layers], ["12", "11", "10"])

    def test_ost_export_write_failure_preserves_existing_destination(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={"BidConditions": [], "BidPages": []},
        )

        def fail_after_partial_write(file_obj, _root):
            file_obj.write("<partial>")
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "existing.ost"
            output_path.write_text("existing export", encoding="utf-8")
            with patch(
                "ost_visualizer.infrastructure.mdb.exporters.ost_exporter._write_element",
                side_effect=fail_after_partial_write,
            ):
                result = OstExporter(SimpleNamespace()).export(
                    raw_data,
                    str(output_path),
                )
            self.assertFalse(result.success)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "existing export",
            )
            self.assertEqual(list(Path(temp_dir).iterdir()), [output_path])

    def test_ost_export_uses_native_area_page_setting_and_text_order(self):
        text_row = {
            "FontItalic": "0",
            "Position": "1;2;3;4",
            "Name": "Note",
            "UID": "40",
            "BidLayerUID": "5",
            "FontName": "Arial",
            "BidUID": "1",
            "FontBold": "1",
            "BidPageUID": "20",
            "TextAlign": "0",
            "FontColor": "255",
            "FontSize": "12",
            "FontUnderline": "0",
        }
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={
                "BidAreas": [
                    {"UID": "10", "BidUID": "1", "Name": "Low"},
                    {"UID": "12", "BidUID": "1", "Name": "High"},
                    {"UID": "11", "BidUID": "1", "Name": "Mid"},
                ],
                "BidLayers": [
                    {"UID": "5", "BidUID": "1", "Name": "Annotation"},
                ],
                "BidConditions": [],
                "BidPages": [
                    {"UID": "20", "BidUID": "1", "Name": "Sheet", "Sequence": "1"},
                ],
            },
            page_tables={
                "BidPageSettings": [
                    {
                        "UID": "31",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidAreaUID": "10",
                        "BidAreaSelected": "0",
                    },
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidAreaUID": "11",
                        "BidAreaSelected": "1",
                    },
                    {
                        "UID": "32",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidAreaUID": "12",
                        "BidAreaSelected": "1",
                    },
                ],
                "BidTexts": [text_row],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "native_order.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        areas = root.findall("./Bid/BidAreas/BidArea")
        self.assertEqual([row.get("UID") for row in areas], ["12", "11", "10"])
        page_settings = root.findall(
            "./Bid/BidPages/BidPage/BidPageSettings/BidPageSetting"
        )
        self.assertEqual(
            [row.get("UID") for row in page_settings],
            ["32", "30", "31"],
        )
        text = root.find("./Bid/BidPages/BidPage/BidTexts/BidText")
        self.assertIsNotNone(text)
        self.assertEqual(
            list(text.attrib),
            [
                "UID",
                "BidUID",
                "BidPageUID",
                "BidLayerUID",
                "Name",
                "FontName",
                "FontColor",
                "FontSize",
                "FontBold",
                "FontItalic",
                "FontUnderline",
                "TextAlign",
                "Position",
            ],
        )

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

    def test_ost_import_remaps_area_translation_and_comment_parent_refs(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidAreas>
              <BidArea UID="10" BidUID="1" Name="Area" Sequence="1"/>
            </BidAreas>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidAreaTranslations>
                  <BidAreaTranslation UID="30" BidPageUID="20"
                                      MasterAreaUID="10" TranslateAreaUID="10"/>
                </BidAreaTranslations>
                <BidComments>
                  <BidComment UID="40" BidUID="1" BidPageUID="20"/>
                  <BidComment UID="41" BidUID="1" BidPageUID="20"
                              ParentCommentUID="40"/>
                </BidComments>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        connection.execute(
            """
            CREATE TABLE BidAreaTranslations (
                UID INTEGER PRIMARY KEY,
                BidPageUID INTEGER,
                MasterAreaUID INTEGER,
                TranslateAreaUID INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE BidComments (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                ParentCommentUID INTEGER
            )
            """
        )
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        area_uid = connection.execute(
            "SELECT UID FROM BidAreas WHERE Name='Area'"
        ).fetchone()[0]
        translation = connection.execute(
            "SELECT MasterAreaUID, TranslateAreaUID FROM BidAreaTranslations"
        ).fetchone()
        comments = connection.execute(
            "SELECT UID, ParentCommentUID FROM BidComments ORDER BY UID"
        ).fetchall()
        self.assertEqual(translation, (area_uid, area_uid))
        self.assertEqual(comments[1][1], comments[0][0])

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
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="WARNING",
            ) as logs:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("missing selected-page reference", logs.output[0])
        self.assertIn("BidSettings.UID=30 BidPageSelectedUID=999", logs.output[0])
        selected_uid = connection.execute(
            "SELECT BidPageSelectedUID FROM BidSettings"
        ).fetchone()[0]
        self.assertIsNone(selected_uid)

    def test_ost_import_clears_zero_and_blank_selected_page(self):
        for selected_value in ("0", ""):
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

    def test_ost_import_rejects_non_numeric_selected_page_uid(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="not-a-uid"/>
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
            self.assertFalse(
                OstImporter(writer).import_ost(str(ost_path), "target.mdb")
            )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidSettings").fetchone()[0],
            0,
        )

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
        connection = sqlite3.connect(":memory:")
        _create_import_schema(connection)
        writer = _SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            drawing_paths = []
            for directory_name, content in (
                ("first", b"%PDF-1.4 first"),
                ("second", b"%PDF-1.4 second"),
            ):
                drawing_dir = temp_path / directory_name
                drawing_dir.mkdir()
                drawing_path = drawing_dir / "sheet.pdf"
                drawing_path.write_bytes(content)
                drawing_paths.append(drawing_path)
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Imported"},
                bid_tables={
                    "BidSettings": [
                        {"UID": "2", "BidUID": "1", "BidPageSelectedUID": "3"}
                    ],
                    "BidPages": [
                        {
                            "UID": "3",
                            "BidUID": "1",
                            "Name": "Sheet One",
                            "Sequence": "1",
                            "ImagePath": str(drawing_paths[0]),
                        },
                        {
                            "UID": "4",
                            "BidUID": "1",
                            "Name": "Sheet Two",
                            "Sequence": "2",
                            "ImagePath": str(drawing_paths[1]),
                        },
                    ],
                },
            )
            osp_path = temp_path / "roundtrip.osp"
            exporter = OspExporter(
                SimpleNamespace(),
                "test",
                lambda _uom_service: OstExporter(SimpleNamespace()),
            )
            result = exporter.export(raw_data, str(osp_path), bid_name="Roundtrip")
            self.assertTrue(result.success, result.error_message)
            archive_names = list(ost_cab.list_cab(str(osp_path)))
            image_members = [
                name for name in archive_names if name.startswith("TempImages!.tmp\\")
            ]
            self.assertEqual(len(image_members), 2)
            self.assertEqual(len(set(image_members)), 2)
            self.assertFalse(any(name.count("\\") > 1 for name in image_members))
            working_dir = temp_path / "working"
            with patch.object(
                osp_importer_module,
                "get_default_working_dir",
                return_value=working_dir,
            ):
                self.assertTrue(
                    OspImporter(OstImporter(writer)).import_osp(
                        str(osp_path), "target.mdb"
                    )
                )
            page_uid = connection.execute(
                "SELECT UID FROM BidPages WHERE Name='Sheet One'"
            ).fetchone()[0]
            imported_drawings = sorted((working_dir / "Roundtrip").glob("*.pdf"))
            self.assertEqual(len(imported_drawings), 2)
            self.assertEqual(
                {path.read_bytes() for path in imported_drawings},
                {b"%PDF-1.4 first", b"%PDF-1.4 second"},
            )
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
        self.assertIn("invalid database references", logs.output[0])
        self.assertIn("BidHotLinks.UID=43 BidLayerUID=99", logs.output[0])
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

    def test_ost_export_matches_reference_xml_shape_for_core_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference.ost"
            result = OstExporter(SimpleNamespace()).export(
                _reference_shape_export_raw_data(),
                str(output_path),
            )
            self.assertTrue(result.success, result.error_message)
            raw_bytes = output_path.read_bytes()
            text = raw_bytes.decode("utf-8")
            root = ET.fromstring(text)
        self.assertFalse(raw_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(text.startswith("<?xml"))
        self.assertTrue(raw_bytes.endswith(b"\r\n"))
        self.assertIn(b"\r\n", raw_bytes)
        self.assertNotIn(b" />", raw_bytes)
        self.assertNotIn(b"\n", raw_bytes.replace(b"\r\n", b""))
        self.assertEqual(
            [child.tag for child in root],
            ["OST", "Bid", "Employees", "CdnTypes", "JobStatuses"],
        )
        self.assertNotIn("<AccessLevels", text)
        self.assertNotIn("<BidEmployees", text)
        self.assertIn('<JobStatuse UID="79"', text)
        self.assertNotIn('<JobStatus UID="79"', text)
        self.assertIn('PayClassUID="0" AccessLevelUID="0"', text)
        self.assertLess(text.index('LoginName=""'), text.index('Password="0"'))
        self.assertLess(text.index('Password="0"'), text.index('Address1=""'))
        self.assertNotIn('Color=""', text)
        self.assertNotIn('Origin=""', text)
        self.assertLess(
            text.index('BidNamedView UID="31"'), text.index('BidNamedView UID="30"')
        )
        self.assertLess(
            text.index('BidHotLink UID="41"'), text.index('BidHotLink UID="40"')
        )
        self.assertIn('CurrentX="2302.443986254299944"', text)
        self.assertIn('CurrentY="1725.017182130580068"', text)
        self.assertIn('Quantity1="0" Quantity2="0" Quantity3="0"', text)

    def test_ost_export_preserves_page_overlay_and_source_rows(self):
        overlay_fields = (
            "ImagePath",
            "OverlayImagePath",
            "OverlayRect",
            "OverlayOffsetX",
            "OverlayOffsetY",
            "OverlayRotation",
            "DeskewRotationOverlay",
            "OverlayResized",
            "Show",
            "RasterDrawMethod",
        )
        page_row = {
            "UID": "20",
            "BidUID": "1",
            "Name": "Overlay sheet",
            "Sequence": "1",
            "ImagePath": r"C:\plans\sheet.pdf",
            "OverlayImagePath": r"C:\plans\overlay.pdf",
            "OverlayRect": "-12.5,7.25,2688,1920",
            "OverlayOffsetX": "-12.5",
            "OverlayOffsetY": "7.25",
            "OverlayRotation": "90",
            "DeskewRotationOverlay": "0.125",
            "OverlayResized": "1",
            "Show": "3",
            "RasterDrawMethod": "2",
        }
        raw_data = RawBidData(
            bid_row={
                "UID": "1",
                "JobName": "Overlay bid",
                "ExternalID": "",
                "GUID": "{ABCDEF01-2345-6789-ABCD-EF0123456789}",
                "CopyTimeStamp": "2026 7 19 0 39 2",
            },
            bid_tables={
                "BidSettings": [
                    {"UID": "2", "BidUID": "1", "BidPageSelectedUID": "999"}
                ],
                "BidPages": [page_row],
            },
        )
        original_bid_row = dict(raw_data.bid_row)
        original_settings_row = dict(raw_data.bid_tables["BidSettings"][0])
        original_page_row = dict(page_row)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "overlay.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        exported_bid = root.find("./Bid")
        exported_page = root.find("./Bid/BidPages/BidPage")
        self.assertIsNotNone(exported_bid)
        self.assertIsNotNone(exported_page)
        self.assertEqual(
            exported_bid.get("GUID"),
            "{ABCDEF01-2345-6789-ABCD-EF0123456789}",
        )
        self.assertEqual(exported_bid.get("CopyTimestamp"), "2026 7 19 0 39 2")
        self.assertEqual(
            {name: exported_page.get(name) for name in overlay_fields},
            {name: page_row[name] for name in overlay_fields},
        )
        self.assertEqual(raw_data.bid_row, original_bid_row)
        self.assertEqual(raw_data.bid_tables["BidSettings"][0], original_settings_row)
        self.assertEqual(raw_data.bid_tables["BidPages"][0], original_page_row)

    def test_ost_numeric_serializer_uses_reference_float_shape(self):
        self.assertEqual(serialize_value(0.0), "0")
        self.assertEqual(serialize_value(12.0), "12")
        self.assertEqual(serialize_value(2302.4439862543), "2302.443986254299944")

    def test_ost_export_preserves_non_empty_bid_employees_section(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid Employee"},
            bid_tables={
                "BidEmployees": [
                    {
                        "UID": "5",
                        "BidUID": "1",
                        "EmployeeUID": "2",
                        "PayClassUID": "0",
                    }
                ]
            },
            global_tables={
                "Employees": [
                    {
                        "UID": "2",
                        "PayClassUID": "",
                        "AccessLevelUID": "",
                        "FirstName": "Ada",
                    }
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid_employee.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            text = output_path.read_text(encoding="utf-8")
        self.assertIn("<BidEmployees>", text)
        self.assertIn('<BidEmployee UID="5" BidUID="1" EmployeeUID="2"', text)

    def test_ost_export_formats_calculated_area_condition_quantities(self):
        uom_service = SimpleNamespace(
            calculate_condition_quantities=lambda **_kwargs: (734.012, 0.0, 1.25)
        )
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Quantities"},
            bid_tables={
                "BidConditions": [
                    {
                        "UID": "10",
                        "BidUID": "1",
                        "Name": "Linear",
                        "Type": "1",
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
                    {"UID": "20", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidConditionUID": "10",
                        "BidPageUID": "20",
                        "Position": "1;2;3;4",
                    }
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "quantities.ost"
            result = OstExporter(uom_service).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            text = output_path.read_text(encoding="utf-8")
        self.assertIn(
            'Quantity1="734.011999999999944" Quantity2="0" Quantity3="1.25"',
            text,
        )

    def test_ost_export_converts_aggregated_area_condition_quantities_once(self):
        calculation_order = []

        def calculate_condition_quantities(**kwargs):
            x = kwargs["position"][0]
            calculation_order.append(int(x))
            self.assertEqual(
                (kwargs["uom1"], kwargs["uom2"], kwargs["uom3"]),
                (0, 0, 0),
            )
            return x, 0.0, 0.0

        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Area order"},
            bid_tables={
                "BidAreas": [
                    {"UID": "10", "BidUID": "1", "Name": "Low"},
                    {"UID": "20", "BidUID": "1", "Name": "High"},
                ],
                "BidConditions": [
                    {
                        "UID": "100",
                        "BidUID": "1",
                        "Name": "Linear",
                        "Type": "1",
                        "UOM1": "2",
                    }
                ],
                "BidPages": [
                    {"UID": "200", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "1",
                        "BidUID": "1",
                        "BidConditionUID": "100",
                        "BidPageUID": "200",
                        "BidAreaUID": "10",
                        "Position": "1;0;2;0",
                    },
                    {
                        "UID": "3",
                        "BidUID": "1",
                        "BidConditionUID": "100",
                        "BidPageUID": "200",
                        "BidAreaUID": "10",
                        "Position": "3;0;4;0",
                    },
                    {
                        "UID": "2",
                        "BidUID": "1",
                        "BidConditionUID": "100",
                        "BidPageUID": "200",
                        "BidAreaUID": "20",
                        "Position": "2;0;3;0",
                    },
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "area_order.ost"
            result = OstExporter(
                SimpleNamespace(
                    calculate_condition_quantities=calculate_condition_quantities
                )
            ).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            rows = (
                ET.parse(output_path)
                .getroot()
                .findall("./Bid/BidConditions/BidCondition/BidAreaConditions/*")
            )
        self.assertEqual(calculation_order, [1, 3, 2])
        self.assertEqual(
            [
                (row.get("UID"), row.get("AreaUID"), row.get("Quantity1"))
                for row in rows
            ],
            [
                ("2", "20", "0.166666666666667"),
                ("1", "10", "0.333333333333333"),
            ],
        )

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
            creator = database_creator.DatabaseCreator()
            creator._apply_reference_schema_metadata = lambda *_args, **_kwargs: None
            creator._create_schema(Path("test.mdb"))
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertNotIn(
            "CREATE UNIQUE INDEX [UI_BidPageSettings_PageSelected] "
            "ON [BidPageSettings] ([BidPageUID], [BidAreaSelected])",
            fake_connection.cursor_instance.calls,
        )


if __name__ == "__main__":
    unittest.main()
