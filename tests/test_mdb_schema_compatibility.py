import gc
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pyodbc

pyodbc.pooling = False
from ost_visualizer.infrastructure.mdb import schema_contract
from ost_visualizer.infrastructure.mdb.database_creator import DatabaseCreator
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    MdbSchemaInspector,
    UnsupportedMdbSchemaError,
)

try:
    import win32com.client as _win32_client
except ImportError:
    _win32_client = None
_ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"
_NEW_MDB_PATH = Path(r"C:\OCS Documents\OST\OST Projects.mdb")
_REFERENCE_SCHEMA_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "reference_mdb_schema.json"
)
_KEY_TABLES = (
    "Bids",
    "BidPages",
    "BidPageSettings",
    "BidAreas",
    "Employees",
    "PayClasses",
    "BidEmployees",
    "BidTakeoffs",
    "BidConditions",
    "BidConditionFolders",
    "CdnTypes",
    "BidLayers",
    "BidSettings",
    "BidNamedViews",
    "BidHotLinks",
)


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


def _access_available() -> bool:
    return _ACCESS_DRIVER in pyodbc.drivers() and _win32_client is not None


def _connect_mdb(path: Path):
    return pyodbc.connect(
        f"DRIVER={{{_ACCESS_DRIVER}}};DBQ={path};",
        autocommit=False,
    )


def _fetch_dicts(cursor, sql: str, *params):
    cursor.execute(sql, *params)
    column_names = [column[0] for column in cursor.description]
    return [
        {column_names[index]: row[index] for index in range(len(column_names))}
        for row in cursor.fetchall()
    ]


def _extract_mdb_metadata(path: Path) -> dict:
    connection = _connect_mdb(path)
    cursor = connection.cursor()
    try:
        table_names = sorted(
            row.table_name
            for row in cursor.tables(tableType="TABLE")
            if not row.table_name.startswith("MSys")
        )
        metadata = {"tables": table_names, "key_tables": {}}
        adox = _win32_client.Dispatch("ADOX.Catalog")
        try:
            adox.ActiveConnection = (
                "Provider=Microsoft.ACE.OLEDB.12.0;" f"Data Source={path};"
            )
            adox_tables = {
                adox.Tables(index).Name for index in range(adox.Tables.Count)
            }
            for table_name in _KEY_TABLES:
                if table_name not in adox_tables:
                    continue
                table = adox.Tables(table_name)
                columns = [
                    {
                        "name": column.column_name,
                        "type": column.type_name,
                        "nullable": int(column.nullable),
                    }
                    for column in cursor.columns(table=table_name)
                ]
                indexes = []
                for index_number in range(table.Indexes.Count):
                    index = table.Indexes(index_number)
                    index_columns = [
                        index.Columns(column_number).Name
                        for column_number in range(index.Columns.Count)
                    ]
                    indexes.append(
                        {
                            "name": index.Name,
                            "unique": bool(index.Unique),
                            "primary": bool(index.PrimaryKey),
                            "columns": tuple(index_columns),
                        }
                    )
                relationships = []
                for key_number in range(table.Keys.Count):
                    key = table.Keys(key_number)
                    if int(key.Type) != 2:
                        continue
                    key_columns = [
                        key.Columns(column_number).Name
                        for column_number in range(key.Columns.Count)
                    ]
                    related_columns = [
                        key.Columns(column_number).RelatedColumn
                        for column_number in range(key.Columns.Count)
                    ]
                    relationships.append(
                        {
                            "name": key.Name,
                            "columns": tuple(key_columns),
                            "related_table": key.RelatedTable,
                            "related_columns": tuple(related_columns),
                            "delete_rule": int(key.DeleteRule),
                            "update_rule": int(key.UpdateRule),
                        }
                    )
                row_count = _fetch_dicts(
                    cursor, f"SELECT COUNT(*) AS [Count] FROM [{table_name}]"
                )[0]["Count"]
                max_uid = None
                if any(column["name"] == "UID" for column in columns):
                    max_uid = _fetch_dicts(
                        cursor, f"SELECT MAX([UID]) AS [MaxUID] FROM [{table_name}]"
                    )[0]["MaxUID"]
                metadata["key_tables"][table_name] = {
                    "columns": columns,
                    "indexes": indexes,
                    "relationships": relationships,
                    "row_count": row_count,
                    "max_uid": max_uid,
                }
        finally:
            try:
                adox.ActiveConnection.Close()
            except Exception:
                pass
            adox = None
        return metadata
    finally:
        connection.rollback()
        cursor.close()
        connection.close()
        gc.collect()


def _column_names(table_metadata: dict) -> set[str]:
    return {column["name"] for column in table_metadata["columns"]}


def _unique_index_columns(table_metadata: dict) -> set[tuple[str, ...]]:
    return {
        tuple(index["columns"])
        for index in table_metadata["indexes"]
        if index["unique"]
    }


def _primary_index_columns(table_metadata: dict) -> set[tuple[str, ...]]:
    return {
        tuple(index["columns"])
        for index in table_metadata["indexes"]
        if index["primary"]
    }


def _relationship_targets(table_metadata: dict) -> set[tuple[tuple[str, ...], str]]:
    return {
        (tuple(relationship["columns"]), relationship["related_table"])
        for relationship in table_metadata["relationships"]
    }


def _load_reference_schema_fixture() -> dict:
    return json.loads(_REFERENCE_SCHEMA_FIXTURE.read_text(encoding="utf-8"))


def _dao_created_schema_snapshot(path: Path) -> dict:
    engine = _win32_client.Dispatch("DAO.DBEngine.120")
    database = engine.OpenDatabase(str(path))
    try:
        table_names = sorted(
            table_def.Name
            for table_number in range(database.TableDefs.Count)
            for table_def in [database.TableDefs(table_number)]
            if not table_def.Name.startswith("MSys")
        )
        relationships = []
        for relation_number in range(database.Relations.Count):
            relation = database.Relations(relation_number)
            field = relation.Fields(0)
            relationships.append(
                {
                    "name": relation.Name,
                    "child_table": relation.ForeignTable,
                    "child_column": field.ForeignName,
                    "parent_table": relation.Table,
                    "parent_column": field.Name,
                }
            )
        relationship_names = {relationship["name"] for relationship in relationships}
        uid_required_tables = []
        field_defaults = []
        primary_index_definitions = []
        explicit_indexes = []
        total_fields = 0
        total_indexes = 0
        total_primary_indexes = 0
        for table_name in table_names:
            table_def = database.TableDefs(table_name)
            total_fields += table_def.Fields.Count
            uid_field = table_def.Fields("UID")
            if bool(uid_field.Required):
                uid_required_tables.append(table_name)
            for field_number in range(table_def.Fields.Count):
                field = table_def.Fields(field_number)
                default_value = str(field.DefaultValue or "")
                if default_value:
                    field_defaults.append(
                        {
                            "table": table_name,
                            "field": field.Name,
                            "default": default_value,
                        }
                    )
            for index_number in range(table_def.Indexes.Count):
                index = table_def.Indexes(index_number)
                total_indexes += 1
                fields = [
                    index.Fields(field_number).Name
                    for field_number in range(index.Fields.Count)
                ]
                if bool(index.Primary):
                    total_primary_indexes += 1
                    primary_index_definitions.append(
                        {
                            "table": table_name,
                            "fields": fields,
                            "unique": bool(index.Unique),
                            "required": bool(index.Required),
                            "ignore_nulls": bool(index.IgnoreNulls),
                            "foreign": bool(index.Foreign),
                            "clustered": bool(index.Clustered),
                        }
                    )
                elif index.Name not in relationship_names:
                    explicit_indexes.append(
                        {
                            "table": table_name,
                            "name": index.Name,
                            "unique": bool(index.Unique),
                            "fields": fields,
                        }
                    )
        return {
            "table_count": len(table_names),
            "field_count": total_fields,
            "index_count": total_indexes,
            "primary_index_count": total_primary_indexes,
            "relationship_count": len(relationships),
            "uid_required_tables": uid_required_tables,
            "field_defaults": sorted(
                field_defaults,
                key=lambda item: (item["table"], item["field"]),
            ),
            "primary_index_definitions": sorted(
                primary_index_definitions,
                key=lambda item: item["table"],
            ),
            "explicit_indexes": sorted(
                explicit_indexes,
                key=lambda item: (item["table"], item["name"], item["fields"]),
            ),
            "relationships": sorted(
                relationships,
                key=lambda item: item["name"],
            ),
        }
    finally:
        database.Close()


def _next_table_uid(cursor, table_name: str) -> int:
    cursor.execute(f"SELECT MAX([UID]) FROM [{table_name}]")
    row = cursor.fetchone()
    return int(row[0]) + 1000 if row and row[0] is not None else 1000


def _seed_minimal_bid(cursor) -> dict[str, int]:
    bid_uid = _next_table_uid(cursor, "Bids")
    page_uid = _next_table_uid(cursor, "BidPages")
    area_uid = _next_table_uid(cursor, "BidAreas")
    settings_uid = _next_table_uid(cursor, "BidPageSettings") + 5000
    pay_class_uid = _next_table_uid(cursor, "PayClasses")
    employee_uid = _next_table_uid(cursor, "Employees")
    cursor.execute(
        "INSERT INTO [Bids] ([UID], [JobName], [EstimatorUID]) "
        "VALUES (?, 'Compatibility Bid', NULL)",
        bid_uid,
    )
    cursor.execute(
        "INSERT INTO [BidPages] ([UID], [BidUID], [Name], [Sequence]) "
        "VALUES (?, ?, 'Sheet A', 1)",
        page_uid,
        bid_uid,
    )
    cursor.execute(
        "INSERT INTO [BidPages] ([UID], [BidUID], [Name], [Sequence]) "
        "VALUES (?, ?, 'Sheet B', 2)",
        page_uid + 1,
        bid_uid,
    )
    cursor.execute(
        "INSERT INTO [BidAreas] ([UID], [BidUID], [Name], [Sequence]) "
        "VALUES (?, ?, 'Area A', 1)",
        area_uid,
        bid_uid,
    )
    cursor.execute(
        "INSERT INTO [BidAreas] ([UID], [BidUID], [Name], [Sequence]) "
        "VALUES (?, ?, 'Area B', 2)",
        area_uid + 1,
        bid_uid,
    )
    cursor.execute(
        "INSERT INTO [BidPageSettings] "
        "([UID], [BidPageUID], [BidAreaUID], [BidAreaSelected]) "
        "VALUES (?, ?, ?, 2)",
        settings_uid,
        page_uid + 1,
        area_uid + 1,
    )
    cursor.execute(
        "INSERT INTO [PayClasses] ([UID], [Name]) VALUES (?, 'Compat Pay')",
        pay_class_uid,
    )
    cursor.execute(
        "INSERT INTO [Employees] "
        "([UID], [PayClassUID], [EmployeeNo], [FirstName], [LastName]) "
        "VALUES (?, ?, 'C5000', 'Compat', 'Employee')",
        employee_uid,
        pay_class_uid,
    )
    cursor.execute(
        "UPDATE [Bids] SET [EstimatorUID]=? WHERE [UID]=?",
        employee_uid,
        bid_uid,
    )
    return {
        "bid_uid": bid_uid,
        "page_uid": page_uid,
        "area_uid": area_uid,
        "employee_uid": employee_uid,
    }


def _run_employee_estimator_round_trip_for_label(
    label: str, source_path_text: str | None
) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        if source_path_text is None:
            db_path = temp_path / "app_created.mdb"
            if not DatabaseCreator().create_database(db_path, "Compat"):
                raise AssertionError("failed to create app compatibility MDB")
        else:
            source_path = Path(source_path_text)
            if not source_path.exists():
                raise AssertionError(f"{label} MDB is not available at {source_path}")
            db_path = temp_path / f"{label}.mdb"
            shutil.copy2(source_path, db_path)
        connection = _connect_mdb(db_path)
        cursor = connection.cursor()
        try:
            ids = _seed_minimal_bid(cursor)
            connection.commit()
        finally:
            cursor.close()
            connection.close()
        reader = MdbReader()
        try:
            raw_data = reader.get_raw_bid_data(str(db_path), str(ids["bid_uid"]))
        finally:
            reader.close_connection(str(db_path))
        ost_path = temp_path / f"{label}.ost"
        export_result = OstExporter(SimpleNamespace()).export(raw_data, str(ost_path))
        if not export_result.success:
            raise AssertionError(export_result.error_message)
        root = ET.parse(ost_path).getroot()
        if root.find("./Bid").get("EstimatorUID") != str(ids["employee_uid"]):
            raise AssertionError("export did not preserve Bids.EstimatorUID")
        if root.find("./Employees/Employee").get("UID") != str(ids["employee_uid"]):
            raise AssertionError("export did not preserve Employees.UID")
        if root.find("./PayClasses/PayClass").get("Name") != "Compat Pay":
            raise AssertionError("export did not preserve PayClasses.Name")
        imported_path = temp_path / f"{label}_imported.mdb"
        if not DatabaseCreator().create_database(imported_path, "Imported"):
            raise AssertionError("failed to create import target MDB")
        writer = MdbWriter()
        try:
            if not OstImporter(writer).import_ost(str(ost_path), str(imported_path)):
                raise AssertionError("OST import failed")
        finally:
            writer._conn_manager.close()
        connection = _connect_mdb(imported_path)
        cursor = connection.cursor()
        try:
            rows = _fetch_dicts(
                cursor,
                "SELECT [EstimatorUID] FROM [Bids] "
                "WHERE [JobName]='Compatibility Bid'",
            )
            if len(rows) != 1:
                raise AssertionError("imported bid row was not found")
            estimator_uid = rows[0]["EstimatorUID"]
            employee_rows = _fetch_dicts(
                cursor,
                "SELECT [UID], [PayClassUID] FROM [Employees] "
                "WHERE [EmployeeNo]='C5000'",
            )
        finally:
            connection.rollback()
            cursor.close()
            connection.close()
        if len(employee_rows) != 1:
            raise AssertionError("imported employee row was not found")
        if estimator_uid != employee_rows[0]["UID"]:
            raise AssertionError("imported estimator does not point to employee")


class MdbSchemaCompatibilityTests(unittest.TestCase):
    def test_schema_contract_builds_raw_table_groups(self):
        self.assertIn("BidLayers", schema_contract.BID_SECTIONS)
        self.assertIn("BidPages", schema_contract.RAW_BID_TABLES)
        self.assertIn("BidNamedViews", schema_contract.RAW_BID_TABLES)
        self.assertIn("Employees", schema_contract.RAW_GLOBAL_TABLES)
        self.assertEqual(schema_contract.singular("BidLayers"), "BidLayer")

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

    def test_optional_write_skip_logs_once_per_database_column_and_operation(self):
        MdbSchemaInspector._logged_optional_write_skips.clear()
        self.addCleanup(MdbSchemaInspector._logged_optional_write_skips.clear)
        logger = Mock()
        inspector = MdbSchemaInspector(
            _FakeConnection({"BidPages"}, {"BidPages": {"UID"}}),
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
            inspector.order_by_existing(
                "BidPages", ("FolderUID", "PageNumber"), "[UID]"
            ),
            "[PageNumber]",
        )
        self.assertEqual(
            inspector.order_by_existing("BidPages", ("FolderUID", "Sequence"), "[UID]"),
            "[UID]",
        )

    def test_real_mdb_key_schema_compatibility(self):
        if not _access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        if not _NEW_MDB_PATH.exists():
            self.skipTest(f"MDB is not available at {_NEW_MDB_PATH}")
        metadata = _extract_mdb_metadata(_NEW_MDB_PATH)
        self.assertEqual(len(metadata["tables"]), 64)
        for table_name in _KEY_TABLES:
            self.assertIn(table_name, metadata["key_tables"])
        page_settings = metadata["key_tables"]["BidPageSettings"]
        self.assertIn("UID", _column_names(page_settings))
        self.assertIn(("UID",), _primary_index_columns(page_settings))
        self.assertIn(("UID",), _unique_index_columns(page_settings))
        self.assertNotIn(
            ("BidPageUID", "BidAreaSelected"),
            _unique_index_columns(page_settings),
        )
        self.assertEqual(
            _relationship_targets(page_settings),
            {
                (("BidAreaUID",), "BidAreas"),
                (("BidPageUID",), "BidPages"),
                (("BidTypAreaUID",), "BidTypAreas"),
            },
        )
        bid_pages = metadata["key_tables"]["BidPages"]
        bid_named_views = metadata["key_tables"]["BidNamedViews"]
        self.assertIn("ALState", _column_names(bid_pages))
        self.assertTrue({"Color", "Origin"}.issubset(_column_names(bid_named_views)))
        employees = metadata["key_tables"]["Employees"]
        pay_classes = metadata["key_tables"]["PayClasses"]
        bid_employees = metadata["key_tables"]["BidEmployees"]
        bids = metadata["key_tables"]["Bids"]
        self.assertIn("EstimatorUID", _column_names(bids))
        self.assertIn("PayClassUID", _column_names(employees))
        self.assertEqual(_primary_index_columns(pay_classes), {("UID",)})
        self.assertIn(
            (("EmployeeUID",), "Employees"),
            _relationship_targets(bid_employees),
        )

    def test_app_created_mdb_key_schema_compatibility(self):
        if not _access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "app_created.mdb"
            self.assertTrue(DatabaseCreator().create_database(db_path, "Compat"))
            metadata = _extract_mdb_metadata(db_path)
        self.assertEqual(len(metadata["tables"]), 64)
        page_settings = metadata["key_tables"]["BidPageSettings"]
        self.assertIn("UID", _column_names(page_settings))
        self.assertEqual(_primary_index_columns(page_settings), {("UID",)})
        self.assertNotIn(
            ("BidPageUID", "BidAreaSelected"),
            _unique_index_columns(page_settings),
        )
        bid_pages = metadata["key_tables"]["BidPages"]
        bid_named_views = metadata["key_tables"]["BidNamedViews"]
        self.assertIn("ALState", _column_names(bid_pages))
        self.assertTrue({"Color", "Origin"}.issubset(_column_names(bid_named_views)))

    def test_app_created_mdb_cover_sheet_accepts_blank_optional_values_and_page(self):
        if not _access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "cover_sheet.mdb"
            self.assertTrue(DatabaseCreator().create_database(db_path, "Cover Sheet"))
            connection = _connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                ids = _seed_minimal_bid(cursor)
                cursor.execute(
                    "UPDATE [Bids] SET [JobStatusUID]=NULL, [EstimatorUID]=NULL, "
                    "[BidDate]=NULL, [BidNo]=NULL WHERE [UID]=?",
                    ids["bid_uid"],
                )
                connection.commit()
            finally:
                cursor.close()
                connection.close()
            writer = MdbWriter()
            try:
                self.assertTrue(
                    writer.save_cover_sheet(
                        str(db_path),
                        str(ids["bid_uid"]),
                        {
                            "job_status_uid": "",
                            "job_name": "Compatibility Bid",
                            "estimator_uid": "",
                            "bid_date": "",
                            "bid_no": "",
                            "measure_base": 0,
                            "pages": [
                                {
                                    "uid": None,
                                    "sequence": 3,
                                    "sheet_no": "3",
                                    "name": "",
                                    "width": 42.0,
                                    "height": 30.0,
                                    "scale_factor1": 0.25,
                                    "scale_factor2": 12.0,
                                    "show_mode": 0,
                                    "index": 1,
                                }
                            ],
                        },
                    )
                )
            finally:
                writer._conn_manager.close()
            connection = _connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT [JobStatusUID], [EstimatorUID], [BidDate], [BidNo] "
                    "FROM [Bids] WHERE [UID]=?",
                    ids["bid_uid"],
                )
                self.assertEqual(tuple(cursor.fetchone()), (None, None, None, None))
                cursor.execute(
                    "SELECT COUNT(*) FROM [BidPages] WHERE [BidUID]=?",
                    ids["bid_uid"],
                )
                self.assertEqual(cursor.fetchone()[0], 3)
            finally:
                cursor.close()
                connection.close()

    def test_app_created_mdb_matches_reference_dao_schema_metadata(self):
        if not _access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        fixture = _load_reference_schema_fixture()
        fixture["uid_required_tables"] = sorted(fixture["uid_required_tables"])
        fixture["field_defaults"] = sorted(
            fixture["field_defaults"],
            key=lambda item: (item["table"], item["field"]),
        )
        fixture["explicit_indexes"] = sorted(
            fixture["explicit_indexes"],
            key=lambda item: (item["table"], item["name"], item["fields"]),
        )
        fixture["relationships"] = sorted(
            fixture["relationships"],
            key=lambda item: item["name"],
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "reference_shape.mdb"
            if not DatabaseCreator().create_database(db_path, "Reference Shape"):
                self.skipTest("Could not create an Access test database")
            snapshot = _dao_created_schema_snapshot(db_path)
        self.assertEqual(snapshot["table_count"], 64)
        self.assertEqual(snapshot["field_count"], 668)
        self.assertEqual(snapshot["index_count"], 278)
        self.assertEqual(snapshot["primary_index_count"], 64)
        self.assertEqual(snapshot["relationship_count"], 83)
        self.assertEqual(
            snapshot["uid_required_tables"],
            fixture["uid_required_tables"],
        )
        self.assertEqual(snapshot["field_defaults"], fixture["field_defaults"])
        self.assertEqual(
            snapshot["primary_index_definitions"],
            [
                {
                    "table": table_name,
                    "fields": ["UID"],
                    "unique": True,
                    "required": True,
                    "ignore_nulls": False,
                    "foreign": False,
                    "clustered": False,
                }
                for table_name in fixture["uid_required_tables"]
            ],
        )
        self.assertEqual(snapshot["explicit_indexes"], fixture["explicit_indexes"])
        self.assertEqual(snapshot["relationships"], fixture["relationships"])
        self.assertIn(
            {
                "name": "BidPlanrooms_BidUID1",
                "child_table": "BidPlanrooms",
                "child_column": "BidUID",
                "parent_table": "Bids",
                "parent_column": "UID",
            },
            snapshot["relationships"],
        )

    def test_page_area_and_employee_writes_work_on_supported_schema_versions(self):
        if not _access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            db_paths = []
            if not _NEW_MDB_PATH.exists():
                self.skipTest(f"MDB is not available at {_NEW_MDB_PATH}")
            copied_path = temp_path / "new.mdb"
            shutil.copy2(_NEW_MDB_PATH, copied_path)
            db_paths.append(("new", copied_path))
            app_path = temp_path / "app_created.mdb"
            self.assertTrue(DatabaseCreator().create_database(app_path, "Compat"))
            db_paths.append(("app", app_path))
            for label, db_path in db_paths:
                with self.subTest(database=label):
                    connection = _connect_mdb(db_path)
                    cursor = connection.cursor()
                    try:
                        ids = _seed_minimal_bid(cursor)
                        connection.commit()
                    finally:
                        cursor.close()
                        connection.close()
                    writer = MdbWriter()
                    try:
                        self.assertTrue(
                            writer.save_page_area(
                                str(db_path),
                                str(ids["page_uid"]),
                                str(ids["area_uid"]),
                            )
                        )
                        self.assertTrue(
                            writer.save_page_area(
                                str(db_path),
                                str(ids["page_uid"]),
                                str(ids["area_uid"] + 1),
                            )
                        )
                        self.assertTrue(
                            writer.save_page_area(
                                str(db_path), str(ids["page_uid"]), "0"
                            )
                        )
                    finally:
                        writer._conn_manager.close()
                    connection = _connect_mdb(db_path)
                    cursor = connection.cursor()
                    try:
                        rows = _fetch_dicts(
                            cursor,
                            "SELECT [UID], [BidAreaUID], [BidAreaSelected] "
                            "FROM [BidPageSettings] WHERE [BidPageUID]=?",
                            ids["page_uid"],
                        )
                    finally:
                        connection.rollback()
                        cursor.close()
                        connection.close()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["BidAreaSelected"], 1)
                    self.assertIsNone(rows[0]["BidAreaUID"])
                    self.assertGreater(rows[0]["UID"], ids["page_uid"])

    def test_zz_employee_estimator_export_import_round_trip_on_supported_schema_versions(
        self,
    ):
        if not _access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        cases = (
            ("new", _NEW_MDB_PATH),
            ("app", None),
        )
        for label, source_path in cases:
            if source_path is not None and not source_path.exists():
                self.skipTest(f"{label} MDB is not available at {source_path}")
            with self.subTest(database=label):
                source_path_text = None
                if source_path is not None:
                    source_path_text = str(source_path)
                code = (
                    "import sys; sys.path.insert(0, 'tests'); "
                    "from test_mdb_schema_compatibility import "
                    "_run_employee_estimator_round_trip_for_label as run; "
                    f"run({label!r}, {source_path_text!r})"
                )
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )


if __name__ == "__main__":
    unittest.main()
