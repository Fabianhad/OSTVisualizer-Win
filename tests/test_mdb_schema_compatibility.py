import gc
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pyodbc

pyodbc.pooling = False
from ost_visualizer.infrastructure.mdb import schema_contract
from ost_visualizer.infrastructure.mdb.bid_settings_contract import (
    BidSettingsCardinalityError,
)
from ost_visualizer.infrastructure.database.settings_cardinality import (
    GlobalSettingsCardinalityError,
)
from ost_visualizer.infrastructure.mdb.components.constants import (
    LAYER_REFERENCE_TABLES,
    PAGE_DELETE_CHILD_TABLES,
)
from ost_visualizer.infrastructure.mdb.database_creator import (
    DatabaseCreator,
    get_reference_schema_model,
)
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import BID_RELATIONSHIPS
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
        self.assertEqual(defaults["next_bid_no"], 1)
        self.assertEqual(defaults["scale_factor1"], 0.125)

    def test_create_bid_rejects_missing_durable_bid_number_allocator(self):
        class Schema:
            @staticmethod
            def optional_table_missing(table):
                return table == "Settings"

            @staticmethod
            def column_exists(_table, _column):
                return False

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.inserted = []

            @contextmanager
            def _connection(self, _db_path):
                yield object()

            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _require_write_columns(_schema, _table, _columns):
                pass

            def _execute_insert_values(self, *_args):
                self.inserted.append(_args)

        writer = RecordingWriter()
        self.assertIsNone(writer.create_bid("legacy.mdb", None, {"job_name": "Bid"}))
        self.assertEqual(writer.inserted, [])

    def test_duplicate_bid_rejects_missing_durable_bid_number_allocator(self):
        class Cursor:
            description = (("JobName",), ("UID",))

            @staticmethod
            def execute(_sql, *_params):
                pass

            @staticmethod
            def fetchone():
                return ("Source", 1)

            @staticmethod
            def fetchall():
                return [(1,)]

        class Connection:
            @staticmethod
            def cursor():
                return Cursor()

        class Schema:
            @staticmethod
            def get_columns(table):
                return {"JobName", "UID"} if table == "Bids" else set()

            @staticmethod
            def optional_table_missing(table):
                return table in {"BidSettings", "Settings"}

            @staticmethod
            def column_exists(_table, _column):
                return False

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.inserted = []

            @contextmanager
            def _connection(self, _db_path):
                yield Connection()

            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _require_write_columns(_schema, _table, _columns):
                pass

            def _execute_insert_values(self, *_args):
                self.inserted.append(_args)

        writer = RecordingWriter()
        self.assertIsNone(writer.duplicate_bid("legacy.mdb", "1"))
        self.assertEqual(writer.inserted, [])

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

    def test_settings_reader_defaults_null_legacy_fields_from_one_row(self):
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

    def test_bid_reader_rejects_multiple_bid_settings_rows(self):
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
                rows = ((10,), (11,))
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
            def require_column(_table, _column):
                pass

            @staticmethod
            def column_exists(_table, _column):
                return True

        class Reader(MdbReader):
            @staticmethod
            def _schema(_connection):
                return Schema()

        with self.assertRaisesRegex(
            BidSettingsCardinalityError,
            "BidSettings has multiple rows for Bids.UID=1",
        ):
            Reader()._parse_bid_selected_page(Connection(), "1")

    def test_schema_contract_builds_raw_table_groups(self):
        self.assertIn("BidLayers", schema_contract.BID_SECTIONS)
        self.assertIn("BidPages", schema_contract.RAW_BID_TABLES)
        self.assertIn("BidNamedViews", schema_contract.RAW_BID_TABLES)
        self.assertIn("Employees", schema_contract.RAW_GLOBAL_TABLES)
        self.assertEqual(schema_contract.singular("BidLayers"), "BidLayer")

    def test_layer_reference_tables_match_the_shared_mdb_and_sql_schema(self):
        schema = get_reference_schema_model()
        schema_layer_tables = {
            table.name
            for table in schema.tables
            if any(column.name == "BidLayerUID" for column in table.columns)
        }
        self.assertEqual(schema_layer_tables, set(LAYER_REFERENCE_TABLES))
        self.assertTrue(
            {
                "BidTakeoffs",
                "BidDimensions",
                "BidArrows",
                "BidALines",
                "BidAnnoInk",
                "BidLegends",
            }.isdisjoint(schema_layer_tables)
        )

    def test_bid_relationship_catalog_covers_schema_foreign_keys(self):
        catalog = {
            (
                relationship.child_table.casefold(),
                relationship.child_column.casefold(),
                relationship.parent_table.casefold(),
                relationship.parent_column.casefold(),
            )
            for relationship in BID_RELATIONSHIPS
        }
        excluded_external_relationships = {
            (
                "conditionsetstyles",
                "conditionstyleuid",
                "bidconditions",
                "uid",
            ),
        }
        schema_relationships = {
            (
                relationship.child_table.casefold(),
                relationship.child_column.casefold(),
                relationship.parent_table.casefold(),
                relationship.parent_column.casefold(),
            )
            for relationship in get_reference_schema_model().foreign_keys
            if relationship.child_table.casefold().startswith("bid")
            or relationship.parent_table.casefold().startswith("bid")
        }
        self.assertEqual(
            schema_relationships - catalog, excluded_external_relationships
        )

    def test_page_delete_catalog_covers_every_direct_page_child(self):
        direct_page_children = {
            table.name
            for table in get_reference_schema_model().tables
            if any(column.name == "BidPageUID" for column in table.columns)
        }
        specially_ordered_children = {
            "BidTakeoffs",
            "BidNamedViews",
            "BidHotLinks",
        }
        self.assertEqual(
            set(PAGE_DELETE_CHILD_TABLES) | specially_ordered_children,
            direct_page_children,
        )

    def test_duplicate_bid_remaps_only_canonical_layer_reference_tables(self):
        class Cursor:
            description = ()

            def execute(self, sql, *_params):
                if "FROM [Bids]" in sql:
                    self.description = (("UID",), ("BidNo",))
                return self

            @staticmethod
            def fetchone():
                return (1, 7)

            @staticmethod
            def fetchall():
                return []

        class Connection:
            @staticmethod
            def cursor():
                return Cursor()

        class Schema:
            @staticmethod
            def get_columns(table):
                if table == "Bids":
                    return {"UID", "BidNo"}
                if table == "BidPages":
                    return {"UID", "BidUID"}
                return set()

            @staticmethod
            def optional_table_missing(table):
                return table in {"Settings", "BidSettings"}

            @staticmethod
            def column_exists(_table, _column):
                return True

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.layer_remap_tables = []

            @contextmanager
            def _connection(self, _db_path):
                yield Connection()

            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _require_write_columns(_schema, _table, _columns):
                pass

            @staticmethod
            def _next_uid(_cursor, _table):
                return 2

            @staticmethod
            def _next_uid_preserving_references(_cursor, _schema, _table):
                return 2

            @staticmethod
            def _execute_insert_values(
                _cursor, _schema, _table, _values, _required_columns, _operation
            ):
                pass

            @staticmethod
            def _copy_bid_table_rows(
                _cursor,
                _table,
                _uid_column,
                _old_uid,
                _new_uid,
                extra_overrides=None,
            ):
                del extra_overrides

            @staticmethod
            def _copy_with_uid_map(_cursor, table, _uid_column, _old_uid, _new_uid):
                return {"10": "20"} if table == "BidLayers" else {}

            def _update_if_columns(
                self,
                _cursor,
                _schema,
                table,
                set_column,
                _set_value,
                _where_columns,
                _where_values,
            ):
                if set_column == "BidLayerUID":
                    self.layer_remap_tables.append(table)

        writer = RecordingWriter()
        duplicated_uid_maps = {
            "BidLayers": {"10": "20"},
            **{
                table: {str(index): str(index + 100)}
                for index, table in enumerate(LAYER_REFERENCE_TABLES, start=1)
            },
        }
        writer._remap_duplicated_relationships(
            Cursor(), Schema(), duplicated_uid_maps, "2"
        )
        self.assertEqual(set(writer.layer_remap_tables), set(LAYER_REFERENCE_TABLES))

    def test_duplicate_remaps_legacy_page_settings_without_uid_column(self):
        class Schema:
            @staticmethod
            def column_exists(table, column):
                return table == "BidPageSettings" and column in {
                    "BidPageUID",
                    "BidAreaUID",
                    "BidTypAreaUID",
                }

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.updates = []

            def _update_if_columns(
                self,
                _cursor,
                _schema,
                table,
                set_column,
                set_value,
                where_columns,
                where_values,
            ):
                self.updates.append(
                    (table, set_column, set_value, where_columns, where_values)
                )

        writer = RecordingWriter()
        writer._remap_duplicated_relationships(
            object(),
            Schema(),
            {
                "BidPages": {"20": "120"},
                "BidAreas": {"10": "110"},
                "BidTypAreas": {"11": "111"},
                "BidPageSettings": {},
            },
            "2",
        )
        self.assertIn(
            (
                "BidPageSettings",
                "BidAreaUID",
                "110",
                ("BidPageUID", "BidAreaUID"),
                ("120", "10"),
            ),
            writer.updates,
        )
        self.assertIn(
            (
                "BidPageSettings",
                "BidTypAreaUID",
                "111",
                ("BidPageUID", "BidTypAreaUID"),
                ("120", "11"),
            ),
            writer.updates,
        )

    def test_duplicate_bid_reconstructs_internal_child_references(self):
        class Cursor:
            description = ()

            def __init__(self):
                self._selected_table = ""
                self._settings_index = 0

            def execute(self, sql, *_params):
                if "FROM [Bids]" in sql:
                    self.description = (
                        ("BidNo",),
                        ("CoverSheetSelItemType",),
                        ("CoverSheetSelItemUID",),
                        ("UID",),
                    )
                    self._selected_table = "Bids"
                elif "FROM [BidPages]" in sql:
                    self.description = (("UID",), ("BidUID",))
                    self._selected_table = "BidPages"
                elif "FROM [Settings]" in sql:
                    self.description = (("NextBidNo",),)
                    self._selected_table = "Settings"
                return self

            def fetchone(self):
                if self._selected_table == "Bids":
                    return (7, 1, 10, 1)
                if self._selected_table == "Settings":
                    rows = ((8,), None)
                    row = rows[self._settings_index]
                    self._settings_index += 1
                    return row
                return None

            def fetchall(self):
                if self._selected_table == "BidPages":
                    return [(1, 10)]
                return []

        cursor = Cursor()

        class Connection:
            @staticmethod
            def cursor():
                return cursor

        class Schema:
            @staticmethod
            def get_columns(table):
                if table == "Bids":
                    return {
                        "UID",
                        "BidNo",
                        "CoverSheetSelItemType",
                        "CoverSheetSelItemUID",
                    }
                if table == "BidPages":
                    return {"UID", "BidUID"}
                return {"UID"}

            @staticmethod
            def optional_table_missing(table):
                return table == "BidSettings"

            @staticmethod
            def require_table(_table):
                pass

            @staticmethod
            def require_column(_table, _column):
                pass

            @staticmethod
            def column_exists(_table, _column):
                return True

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.reference_updates = []
                self.copy_calls = []

            @contextmanager
            def _connection(self, _db_path):
                yield Connection()

            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _require_write_columns(_schema, _table, _columns):
                pass

            @staticmethod
            def _next_uid(_cursor, _table):
                return 2

            @staticmethod
            def _next_uid_preserving_references(_cursor, _schema, _table):
                return 2

            @staticmethod
            def _execute_insert_values(
                _cursor, _schema, _table, _values, _required_columns, _operation
            ):
                pass

            def _copy_bid_table_rows(
                self,
                _cursor,
                table,
                uid_column,
                old_uid,
                new_uid,
                extra_overrides=None,
            ):
                del extra_overrides
                self.copy_calls.append((table, uid_column, old_uid, new_uid))
                return {
                    "BidTakeoffs": {"30": "130", "31": "131"},
                    "BidDimensions": {"40": "140"},
                    "BidComments": {"50": "150", "51": "151"},
                    "BidTypAreas": {"70": "170"},
                    "BidLaborCostCodes": {"80": "180"},
                    "BidLaborActivity": {"81": "181"},
                    "BidTakeoffTotals": {"82": "182"},
                    "BidLaborCostCodeTotals": {"83": "183"},
                    "BidTypicalGroupTotals": {"84": "184"},
                    "BidTypGroupViews": {"85": "185"},
                    "AffectDPCTypGroupViews": {"86": "186"},
                    "Boost": {"87": "187"},
                    "DPCCalcFilter": {"88": "188"},
                    "BidZones": {"90": "190"},
                    "BidConditionUser": {"92": "192"},
                }.get(table, {})

            def _copy_with_uid_map(
                self, _cursor, table, _uid_column, _old_uid, _new_uid
            ):
                del self
                return {
                    "BidConditions": {"30": "130"},
                    "BidAreas": {"60": "160"},
                }.get(table, {})

            def _update_if_columns(
                self,
                _cursor,
                _schema,
                table,
                set_column,
                set_value,
                where_columns,
                where_values,
            ):
                self.reference_updates.append(
                    (table, set_column, set_value, where_columns, where_values)
                )

        writer = RecordingWriter()
        self.assertEqual(writer.duplicate_bid("example.mdb", "1"), "2")
        self.assertIn(
            (
                "BidTakeoffs",
                "ParentUID",
                "130",
                ("BidUID", "ParentUID"),
                ("2", "30"),
            ),
            writer.reference_updates,
        )
        expected_ancillary_updates = {
            (
                "BidLaborActivity",
                "BidConditionUID",
                "130",
                ("BidUID", "BidConditionUID"),
                ("2", "30"),
            ),
            (
                "BidConditionUser",
                "ConditionUID",
                "130",
                ("BidUID", "ConditionUID"),
                ("2", "30"),
            ),
            (
                "BidLaborActivity",
                "BidLaborCostCodeUID",
                "180",
                ("BidUID", "BidLaborCostCodeUID"),
                ("2", "80"),
            ),
            (
                "BidTakeoffTotals",
                "BidPageUID",
                "2",
                ("BidUID", "BidPageUID"),
                ("2", "10"),
            ),
            (
                "BidTakeoffTotals",
                "BidAreaUID",
                "160",
                ("BidUID", "BidAreaUID"),
                ("2", "60"),
            ),
            (
                "BidLaborCostCodeTotals",
                "BidLaborCostCodeUID",
                "180",
                ("BidUID", "BidLaborCostCodeUID"),
                ("2", "80"),
            ),
            (
                "BidTypicalGroupTotals",
                "BidZoneUID",
                "190",
                ("BidUID", "BidZoneUID"),
                ("2", "90"),
            ),
            (
                "AffectDPCTypGroupViews",
                "BidTypGroupViewUID",
                "185",
                ("BidUID", "BidTypGroupViewUID"),
                ("2", "85"),
            ),
            (
                "Boost",
                "BidPageUID",
                "2",
                ("BidUID", "BidPageUID"),
                ("2", "10"),
            ),
            (
                "DPCCalcFilter",
                "BidPageUID",
                "2",
                ("BidUID", "BidPageUID"),
                ("2", "10"),
            ),
        }
        self.assertTrue(
            expected_ancillary_updates.issubset(set(writer.reference_updates)),
            writer.reference_updates,
        )
        self.assertIn(
            (
                "Bids",
                "CoverSheetSelItemUID",
                "2",
                ("UID",),
                ("2",),
            ),
            writer.reference_updates,
        )
        self.assertIn(
            ("BidTypAreaCounts", "BidAreaUID", "60", "160"),
            writer.copy_calls,
        )
        self.assertEqual(
            sum(call[0] == "BidEmployees" for call in writer.copy_calls),
            1,
        )
        copied_tables = {call[0] for call in writer.copy_calls}
        self.assertTrue(
            {"BidTransactionsHistory", "STSTransactionHistory"}.isdisjoint(
                copied_tables
            )
        )
        self.assertIn(
            (
                "BidDimensions",
                "BidTakeoffFromUID",
                "130",
                ("BidUID", "BidTakeoffFromUID"),
                ("2", "30"),
            ),
            writer.reference_updates,
        )
        self.assertIn(
            (
                "BidComments",
                "ParentCommentUID",
                "150",
                ("BidUID", "ParentCommentUID"),
                ("2", "50"),
            ),
            writer.reference_updates,
        )

    def test_duplicate_bid_clears_missing_page_typed_cover_sheet_selection(self):
        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.updates = []

            def _update_if_columns(
                self,
                _cursor,
                _schema,
                table,
                set_column,
                set_value,
                where_columns,
                where_values,
            ):
                self.updates.append(
                    (table, set_column, set_value, where_columns, where_values)
                )

        writer = RecordingWriter()
        writer._remap_duplicated_cover_sheet_selection(
            object(),
            object(),
            {"CoverSheetSelItemType": 1, "CoverSheetSelItemUID": 999},
            {},
            "2",
        )
        self.assertEqual(
            writer.updates,
            [("Bids", "CoverSheetSelItemUID", None, ("UID",), ("2",))],
        )

    def test_duplicate_bid_preserves_unknown_cover_sheet_selection_domain(self):
        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.updates = []

            def _update_if_columns(self, *_args):
                self.updates.append(_args)

        writer = RecordingWriter()
        writer._remap_duplicated_cover_sheet_selection(
            object(),
            object(),
            {"CoverSheetSelItemType": 2, "CoverSheetSelItemUID": 10},
            {"10": "20"},
            "2",
        )
        self.assertEqual(writer.updates, [])

    def test_duplicate_bid_rejects_multiple_bid_settings_rows(self):
        class Cursor:
            description = ()

            def __init__(self):
                self._selected_table = ""
                self._settings_index = 0

            def execute(self, sql, *_params):
                if "FROM [Bids]" in sql:
                    self.description = (("BidNo",), ("UID",))
                    self._selected_table = "Bids"
                elif "FROM [BidSettings]" in sql:
                    self.description = (("UID",),)
                    self._selected_table = "BidSettings"
                return self

            def fetchone(self):
                if self._selected_table == "Bids":
                    return (7, 1)
                if self._selected_table == "BidSettings":
                    rows = ((10,), (11,))
                    if self._settings_index < len(rows):
                        row = rows[self._settings_index]
                        self._settings_index += 1
                        return row
                return None

            def fetchall(self):
                if self._selected_table == "Bids":
                    return [(1,)]
                return []

        cursor = Cursor()

        class Connection:
            @staticmethod
            def cursor():
                return cursor

        class Schema:
            @staticmethod
            def get_columns(table):
                if table == "Bids":
                    return {"UID", "BidNo"}
                return {"UID", "BidUID"}

            @staticmethod
            def optional_table_missing(table):
                return table == "Settings"

            @staticmethod
            def require_column(_table, _column):
                pass

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.inserted = []

            @contextmanager
            def _connection(self, _db_path):
                yield Connection()

            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _require_write_columns(_schema, _table, _columns):
                pass

            def _execute_insert_values(self, *_args):
                self.inserted.append(_args)

        writer = RecordingWriter()
        self.assertIsNone(writer.duplicate_bid("example.mdb", "1"))
        self.assertEqual(writer.inserted, [])

    def test_duplicate_bid_regenerates_copied_entity_guid(self):
        class Cursor:
            connection = object()
            description = (("UID", int), ("BidUID", int), ("GUID", str))

            @staticmethod
            def execute(_sql, *_params):
                pass

            @staticmethod
            def fetchall():
                return [(1, "{SOURCE-GUID}", 10)]

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def column_exists(_table, _column):
                return True

            @staticmethod
            def get_columns(_table):
                return {"UID", "BidUID", "GUID"}

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.inserted = None

            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _next_uid(_cursor, _table):
                return 20

            @staticmethod
            def _next_uid_preserving_references(_cursor, _schema, _table):
                return 20

            def _execute_insert_values(
                self, _cursor, _schema, _table, values, _required, _operation
            ):
                self.inserted = values

        writer = RecordingWriter()
        self.assertEqual(
            writer._copy_bid_table_rows(Cursor(), "BidConditions", "BidUID", "1", "2"),
            {"10": "20"},
        )
        self.assertEqual(writer.inserted["UID"], 20)
        self.assertEqual(writer.inserted["BidUID"], "2")
        self.assertNotEqual(writer.inserted["GUID"], "{SOURCE-GUID}")

    def _run_duplicate_bid_round_trip_reference_graph(self):
        if not _access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "duplicate_graph.mdb"
            self.assertTrue(DatabaseCreator().create_database(db_path, "Duplicate"))
            connection = _connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO [Bids] "
                    "([UID], [BidNo], [JobName], [GUID], [CreateDateTime]) "
                    "VALUES (100, 1, 'Source', '{SOURCE-BID}', ?)",
                    datetime(2000, 1, 1),
                )
                cursor.execute(
                    "INSERT INTO [BidPages] ([UID], [BidUID], [Name], [GUID]) "
                    "VALUES (200, 100, 'Page', '{SOURCE-PAGE}')"
                )
                cursor.execute(
                    "UPDATE [Bids] SET [CoverSheetSelItemType]=1, "
                    "[CoverSheetSelItemUID]=200 WHERE [UID]=100"
                )
                cursor.execute(
                    "INSERT INTO [BidSettings] "
                    "([UID], [BidUID], [BidPageSelectedUID]) "
                    "VALUES (201, 100, 200)"
                )
                cursor.execute(
                    "INSERT INTO [BidConditions] ([UID], [BidUID], [Name], [GUID]) "
                    "VALUES (300, 100, 'Condition', '{SOURCE-CONDITION}')"
                )
                cursor.execute(
                    "INSERT INTO [BidTakeoffs] "
                    "([UID], [BidUID], [BidConditionUID], [BidPageUID], [ParentUID]) "
                    "VALUES (400, 100, 300, 200, NULL)"
                )
                cursor.execute(
                    "INSERT INTO [BidTakeoffs] "
                    "([UID], [BidUID], [BidConditionUID], [BidPageUID], [ParentUID]) "
                    "VALUES (401, 100, 300, 200, 400)"
                )
                cursor.execute(
                    "INSERT INTO [BidDimensions] "
                    "([UID], [BidUID], [BidPageUID], [BidTakeoffFromUID], "
                    "[BidTakeoffToUID]) VALUES (500, 100, 200, 400, 401)"
                )
                cursor.execute(
                    "INSERT INTO [BidComments] "
                    "([UID], [BidUID], [BidPageUID], [ParentCommentUID]) "
                    "VALUES (600, 100, 200, NULL)"
                )
                cursor.execute(
                    "INSERT INTO [BidComments] "
                    "([UID], [BidUID], [BidPageUID], [ParentCommentUID]) "
                    "VALUES (601, 100, 200, 600)"
                )
                cursor.execute(
                    "INSERT INTO [BidAreas] ([UID], [BidUID], [Name], [GUID]) "
                    "VALUES (700, 100, 'Area', '{SOURCE-AREA}')"
                )
                cursor.execute(
                    "INSERT INTO [BidTypAreas] ([UID], [BidUID], [Name]) "
                    "VALUES (800, 100, 'Typical Area')"
                )
                cursor.execute(
                    "INSERT INTO [BidTypAreaCounts] "
                    "([UID], [BidAreaUID], [BidTypAreaUID], [Count]) "
                    "VALUES (900, 700, 800, 3)"
                )
                cursor.execute(
                    "INSERT INTO [BidLaborCostCodes] "
                    "([UID], [BidUID], [GUID]) VALUES (1000, 100, '{SOURCE-COST}')"
                )
                cursor.execute(
                    "INSERT INTO [BidLaborActivity] "
                    "([UID], [BidUID], [BidConditionUID], [BidLaborCostCodeUID]) "
                    "VALUES (1100, 100, 300, 1000)"
                )
                cursor.execute(
                    "INSERT INTO [BidTakeoffTotals] "
                    "([UID], [BidUID], [BidPageUID], [BidAreaUID], "
                    "[BidTypAreaUID], [BidConditionUID]) "
                    "VALUES (1200, 100, 200, 700, 800, 300)"
                )
                cursor.execute(
                    "INSERT INTO [BidLaborCostCodeTotals] "
                    "([UID], [BidUID], [BidPageUID], [BidAreaUID], "
                    "[BidLaborCostCodeUID]) VALUES (1300, 100, 200, 700, 1000)"
                )
                cursor.execute(
                    "INSERT INTO [BidTypGroupViews] "
                    "([UID], [BidUID], [BidConditionUID], [BidPageUID]) "
                    "VALUES (1400, 100, 300, 200)"
                )
                cursor.execute(
                    "INSERT INTO [AffectDPCTypGroupViews] "
                    "([UID], [BidUID], [BidTypGroupViewUID]) "
                    "VALUES (1500, 100, 1400)"
                )
                cursor.execute(
                    "INSERT INTO [BidTypicalGroupTotals] "
                    "([UID], [BidUID], [BidPageUID], [BidAreaUID], "
                    "[BidConditionUID]) VALUES (1600, 100, 200, 700, 300)"
                )
                cursor.execute(
                    "INSERT INTO [Boost] ([UID], [BidUID], [BidPageUID]) "
                    "VALUES (1700, 100, 200)"
                )
                cursor.execute(
                    "INSERT INTO [DPCCalcFilter] ([UID], [BidUID], [BidPageUID]) "
                    "VALUES (1800, 100, 200)"
                )
                cursor.execute(
                    "INSERT INTO [Employees] ([UID], [FirstName], [LastName]) "
                    "VALUES (1900, 'Assigned', 'Employee')"
                )
                cursor.execute(
                    "INSERT INTO [BidEmployees] "
                    "([UID], [BidUID], [EmployeeUID], [GUID]) "
                    "VALUES (1910, 100, 1900, '{SOURCE-ASSIGNMENT}')"
                )
                cursor.execute(
                    "INSERT INTO [BidTransactionsHistory] ([UID], [BidUID]) "
                    "VALUES (1950, 100)"
                )
                cursor.execute(
                    "INSERT INTO [STSTransactionHistory] ([UID], [BidUID]) "
                    "VALUES (1960, 100)"
                )
                connection.commit()
            finally:
                cursor.close()
                connection.close()
            writer = MdbWriter()
            try:
                duplicate_uid = writer.duplicate_bid(str(db_path), "100")
            finally:
                writer._conn_manager.close()
            self.assertIsNotNone(duplicate_uid)

            def assert_ancillary_graph(cursor, owner_uid, forbidden_guids):
                owner = int(owner_uid)

                def owned_row(table, columns):
                    rows = _fetch_dicts(
                        cursor,
                        f"SELECT {', '.join(f'[{column}]' for column in columns)} "
                        f"FROM [{table}] WHERE [BidUID]=?",
                        owner,
                    )
                    self.assertEqual(len(rows), 1, table)
                    return rows[0]

                def assert_owned(table, uid):
                    cursor.execute(
                        f"SELECT [BidUID] FROM [{table}] WHERE [UID]=?", int(uid)
                    )
                    row = cursor.fetchone()
                    self.assertIsNotNone(row, table)
                    self.assertEqual(int(row[0]), owner, table)

                cursor.execute(
                    "SELECT [CoverSheetSelItemType], [CoverSheetSelItemUID] "
                    ", [CreateDateTime] FROM [Bids] WHERE [UID]=?",
                    owner,
                )
                cover_selection = cursor.fetchone()
                self.assertEqual(int(cover_selection[0]), 1)
                assert_owned("BidPages", cover_selection[1])
                self.assertNotEqual(cover_selection[2], datetime(2000, 1, 1))
                settings = owned_row("BidSettings", ("BidPageSelectedUID",))
                assert_owned("BidPages", settings["BidPageSelectedUID"])
                labor = owned_row(
                    "BidLaborActivity",
                    ("BidConditionUID", "BidLaborCostCodeUID"),
                )
                assert_owned("BidConditions", labor["BidConditionUID"])
                assert_owned("BidLaborCostCodes", labor["BidLaborCostCodeUID"])
                takeoff_total = owned_row(
                    "BidTakeoffTotals",
                    (
                        "BidPageUID",
                        "BidAreaUID",
                        "BidTypAreaUID",
                        "BidConditionUID",
                    ),
                )
                assert_owned("BidPages", takeoff_total["BidPageUID"])
                assert_owned("BidAreas", takeoff_total["BidAreaUID"])
                assert_owned("BidTypAreas", takeoff_total["BidTypAreaUID"])
                assert_owned("BidConditions", takeoff_total["BidConditionUID"])
                labor_total = owned_row(
                    "BidLaborCostCodeTotals",
                    ("BidPageUID", "BidAreaUID", "BidLaborCostCodeUID"),
                )
                assert_owned("BidPages", labor_total["BidPageUID"])
                assert_owned("BidAreas", labor_total["BidAreaUID"])
                assert_owned("BidLaborCostCodes", labor_total["BidLaborCostCodeUID"])
                view = owned_row(
                    "BidTypGroupViews", ("UID", "BidPageUID", "BidConditionUID")
                )
                assert_owned("BidPages", view["BidPageUID"])
                assert_owned("BidConditions", view["BidConditionUID"])
                affected = owned_row("AffectDPCTypGroupViews", ("BidTypGroupViewUID",))
                self.assertEqual(affected["BidTypGroupViewUID"], view["UID"])
                typical_total = owned_row(
                    "BidTypicalGroupTotals",
                    ("BidPageUID", "BidAreaUID", "BidConditionUID"),
                )
                assert_owned("BidPages", typical_total["BidPageUID"])
                assert_owned("BidAreas", typical_total["BidAreaUID"])
                assert_owned("BidConditions", typical_total["BidConditionUID"])
                for table in ("Boost", "DPCCalcFilter"):
                    row = owned_row(table, ("BidPageUID",))
                    assert_owned("BidPages", row["BidPageUID"])
                assignment = owned_row("BidEmployees", ("EmployeeUID", "GUID"))
                self.assertEqual(assignment["EmployeeUID"], 1900)
                assignment_guid = str(assignment["GUID"] or "")
                self.assertTrue(assignment_guid)
                self.assertNotIn(assignment_guid, forbidden_guids)
                for table in ("BidTransactionsHistory", "STSTransactionHistory"):
                    cursor.execute(
                        f"SELECT COUNT(*) FROM [{table}] WHERE [BidUID]=?", owner
                    )
                    self.assertEqual(int(cursor.fetchone()[0]), 0, table)
                guids = {}
                for table in (
                    "Bids",
                    "BidPages",
                    "BidConditions",
                    "BidAreas",
                    "BidLaborCostCodes",
                ):
                    key = "UID" if table == "Bids" else "BidUID"
                    cursor.execute(
                        f"SELECT [GUID] FROM [{table}] WHERE [{key}]=?", owner
                    )
                    row = cursor.fetchone()
                    self.assertIsNotNone(row, table)
                    guid = str(row[0] or "")
                    self.assertTrue(guid, table)
                    self.assertNotIn(guid, forbidden_guids, table)
                    guids[table] = guid
                guids["BidEmployees"] = assignment_guid
                self.assertEqual(len(set(guids.values())), len(guids))
                return set(guids.values())

            connection = _connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE [BidTakeoffs] SET [ParentUID]=NULL WHERE [UID]=401"
                )
                cursor.execute("DELETE FROM [BidDimensions] WHERE [UID]=500")
                cursor.execute("DELETE FROM [BidComments] WHERE [UID]=601")
                cursor.execute(
                    "UPDATE [BidTypAreaCounts] SET [Count]=9 WHERE [UID]=900"
                )
                takeoffs = _fetch_dicts(
                    cursor,
                    "SELECT [UID], [ParentUID] FROM [BidTakeoffs] "
                    "WHERE [BidUID]=? ORDER BY [UID]",
                    int(duplicate_uid),
                )
                self.assertEqual(len(takeoffs), 2)
                parent_uid = takeoffs[0]["UID"]
                child_uid = takeoffs[1]["UID"]
                self.assertEqual(takeoffs[1]["ParentUID"], parent_uid)
                self.assertNotIn(parent_uid, {400, 401})
                dimensions = _fetch_dicts(
                    cursor,
                    "SELECT [BidTakeoffFromUID], [BidTakeoffToUID] "
                    "FROM [BidDimensions] WHERE [BidUID]=?",
                    int(duplicate_uid),
                )
                self.assertEqual(
                    dimensions,
                    [
                        {
                            "BidTakeoffFromUID": parent_uid,
                            "BidTakeoffToUID": child_uid,
                        }
                    ],
                )
                comments = _fetch_dicts(
                    cursor,
                    "SELECT [UID], [ParentCommentUID] FROM [BidComments] "
                    "WHERE [BidUID]=? ORDER BY [UID]",
                    int(duplicate_uid),
                )
                self.assertEqual(len(comments), 2)
                self.assertEqual(comments[1]["ParentCommentUID"], comments[0]["UID"])
                self.assertNotEqual(comments[0]["UID"], 600)
                counts = _fetch_dicts(
                    cursor,
                    "SELECT c.[BidAreaUID], c.[BidTypAreaUID], c.[Count] "
                    "FROM ([BidTypAreaCounts] c INNER JOIN [BidAreas] a "
                    "ON c.[BidAreaUID]=a.[UID]) INNER JOIN [BidTypAreas] t "
                    "ON c.[BidTypAreaUID]=t.[UID] "
                    "WHERE a.[BidUID]=? AND t.[BidUID]=?",
                    int(duplicate_uid),
                    int(duplicate_uid),
                )
                self.assertEqual(len(counts), 1)
                self.assertEqual(counts[0]["Count"], 3)
                self.assertNotEqual(counts[0]["BidAreaUID"], 700)
                self.assertNotEqual(counts[0]["BidTypAreaUID"], 800)
                duplicate_guids = assert_ancillary_graph(
                    cursor,
                    duplicate_uid,
                    {
                        "{SOURCE-BID}",
                        "{SOURCE-PAGE}",
                        "{SOURCE-CONDITION}",
                        "{SOURCE-AREA}",
                        "{SOURCE-COST}",
                        "{SOURCE-ASSIGNMENT}",
                    },
                )
                cursor.execute(
                    "SELECT [UID] FROM [BidPages] WHERE [BidUID]=?",
                    int(duplicate_uid),
                )
                duplicate_page_uid = str(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT [UID] FROM [BidConditions] WHERE [BidUID]=?",
                    int(duplicate_uid),
                )
                duplicate_condition_uid = str(cursor.fetchone()[0])
            finally:
                connection.commit()
                cursor.close()
                connection.close()
            reloaded_writer = MdbWriter()
            try:
                second_duplicate_uid = reloaded_writer.duplicate_bid(
                    str(db_path), duplicate_uid
                )
            finally:
                reloaded_writer._conn_manager.close()
            self.assertIsNotNone(second_duplicate_uid)
            connection = _connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                assert_ancillary_graph(cursor, second_duplicate_uid, duplicate_guids)
            finally:
                cursor.close()
                connection.close()
            cleanup_writer = MdbWriter()
            try:
                self.assertTrue(
                    cleanup_writer.delete_pages(str(db_path), ["200"])
                )
                self.assertTrue(
                    cleanup_writer.delete_pages(str(db_path), [duplicate_page_uid])
                )
                self.assertTrue(
                    cleanup_writer.delete_conditions(str(db_path), "100", ["300"])
                )
                self.assertTrue(
                    cleanup_writer.delete_conditions(
                        str(db_path), duplicate_uid, [duplicate_condition_uid]
                    )
                )
            finally:
                cleanup_writer._conn_manager.close()
            connection = _connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                assert_ancillary_graph(cursor, second_duplicate_uid, duplicate_guids)
            finally:
                cursor.close()
                connection.close()
            reader = MdbReader()
            try:
                conditions = reader.get_bid_data(str(db_path), second_duplicate_uid)[0]
            finally:
                reader.close_connection()
            self.assertEqual(len(conditions), 1)
            self.assertIsNone(next(iter(conditions.values())).layer_uid)

    def test_zz_duplicate_bid_round_trip_owns_its_complete_reference_graph(self):
        code = (
            "import sys; sys.path.insert(0, 'tests'); "
            "from test_mdb_schema_compatibility import "
            "MdbSchemaCompatibilityTests as Tests; "
            "Tests()._run_duplicate_bid_round_trip_reference_graph()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
