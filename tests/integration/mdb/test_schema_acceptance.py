import gc
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from tests.paths import FIXTURES_ROOT, REPO_ROOT
import pyodbc
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_creator import (
    DatabaseCreator,
    get_reference_schema_model,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
    FileProjectRepository,
    MdbFileParser,
)
from tests.helpers.mdb.schema_support import (
    _ACCESS_DRIVER as _schema_support__ACCESS_DRIVER,
    _KEY_TABLES as _schema_support__KEY_TABLES,
    _NEW_MDB_PATH as _schema_support__NEW_MDB_PATH,
    _REFERENCE_SCHEMA_FIXTURE as _schema_support__REFERENCE_SCHEMA_FIXTURE,
    _access_available as _schema_support__access_available,
    _column_names as _schema_support__column_names,
    _connect_mdb as _schema_support__connect_mdb,
    _dao_created_schema_snapshot as _schema_support__dao_created_schema_snapshot,
    _extract_mdb_metadata as _schema_support__extract_mdb_metadata,
    _fetch_dicts as _schema_support__fetch_dicts,
    _load_reference_schema_fixture as _schema_support__load_reference_schema_fixture,
    _next_table_uid as _schema_support__next_table_uid,
    _primary_index_columns as _schema_support__primary_index_columns,
    _relationship_targets as _schema_support__relationship_targets,
    _seed_minimal_bid as _schema_support__seed_minimal_bid,
    _unique_index_columns as _schema_support__unique_index_columns,
    _win32_client as _schema_support__win32_client,
)


class SchemaAcceptanceCompatibilityTests(unittest.TestCase):
    def test_routed_writer_duplicates_app_created_access_bid(self):
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "routed_duplicate.mdb"
            self.assertTrue(DatabaseCreator().create_database(db_path, "Duplicate"))
            connection = _schema_support__connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                ids = _schema_support__seed_minimal_bid(cursor)
                connection.commit()
            finally:
                cursor.close()
                connection.close()
            connection_manager = MdbConnectionManager()
            repository = FileProjectRepository(
                MdbFileParser(parser=MdbReader(conn_manager=connection_manager))
            )
            writer = DatabaseProjectWriter(
                connection_manager,
                DatabaseDescriptorRegistry(),
                object(),
                object(),
            )
            try:
                self.assertTrue(repository.load_file(str(db_path)).success)
                read_connection = next(iter(connection_manager._read_conns.values()))
                duplicate_uid = writer.duplicate_bid(str(db_path), str(ids["bid_uid"]))
                self.assertEqual(connection_manager._active_leases, {})
                write_connection = next(iter(connection_manager._write_conns.values()))
                reload_result = repository.reload_database(
                    str(db_path), close_connections=False
                )
                self.assertTrue(reload_result.success)
                self.assertIs(
                    next(iter(connection_manager._read_conns.values())),
                    read_connection,
                )
                self.assertIs(
                    next(iter(connection_manager._write_conns.values())),
                    write_connection,
                )
                duplicated_bid_uids = {
                    bid.uid
                    for project in reload_result.parsed_hierarchy.bid_projects.values()
                    for bid in project.bids
                } | {bid.uid for bid in reload_result.parsed_hierarchy.orphan_bids}
                self.assertIn(str(duplicate_uid), duplicated_bid_uids)
                explicit_reload = repository.reload_database(
                    str(db_path), close_connections=True
                )
                self.assertTrue(explicit_reload.success)
                self.assertIsNot(
                    next(iter(connection_manager._read_conns.values())),
                    read_connection,
                )
                self.assertEqual(connection_manager._write_conns, {})
            finally:
                connection_manager.close()
            self.assertIsNotNone(duplicate_uid)
            connection = _schema_support__connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM [Bids] WHERE [UID] IN (?, ?)",
                    ids["bid_uid"],
                    int(duplicate_uid),
                )
                self.assertEqual(cursor.fetchone()[0], 2)
            finally:
                cursor.close()
                connection.close()

    def _run_duplicate_bid_round_trip_reference_graph(self):
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "duplicate_graph.mdb"
            self.assertTrue(DatabaseCreator().create_database(db_path, "Duplicate"))
            connection = _schema_support__connect_mdb(db_path)
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
                    rows = _schema_support__fetch_dicts(
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

            connection = _schema_support__connect_mdb(db_path)
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
                takeoffs = _schema_support__fetch_dicts(
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
                dimensions = _schema_support__fetch_dicts(
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
                comments = _schema_support__fetch_dicts(
                    cursor,
                    "SELECT [UID], [ParentCommentUID] FROM [BidComments] "
                    "WHERE [BidUID]=? ORDER BY [UID]",
                    int(duplicate_uid),
                )
                self.assertEqual(len(comments), 2)
                self.assertEqual(comments[1]["ParentCommentUID"], comments[0]["UID"])
                self.assertNotEqual(comments[0]["UID"], 600)
                counts = _schema_support__fetch_dicts(
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
            connection = _schema_support__connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                assert_ancillary_graph(cursor, second_duplicate_uid, duplicate_guids)
            finally:
                cursor.close()
                connection.close()
            cleanup_writer = MdbWriter()
            try:
                self.assertTrue(cleanup_writer.delete_pages(str(db_path), ["200"]))
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
            connection = _schema_support__connect_mdb(db_path)
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
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        code = (
            "from tests.integration.mdb.test_schema_acceptance import "
            "SchemaAcceptanceCompatibilityTests as Tests; "
            "Tests()._run_duplicate_bid_round_trip_reference_graph()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_mdb_key_schema_compatibility(self):
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        if not _schema_support__NEW_MDB_PATH.exists():
            self.skipTest(f"MDB is not available at {_schema_support__NEW_MDB_PATH}")
        metadata = _schema_support__extract_mdb_metadata(_schema_support__NEW_MDB_PATH)
        self.assertEqual(len(metadata["tables"]), 64)
        for table_name in _schema_support__KEY_TABLES:
            self.assertIn(table_name, metadata["key_tables"])
        page_settings = metadata["key_tables"]["BidPageSettings"]
        self.assertIn("UID", _schema_support__column_names(page_settings))
        self.assertIn(("UID",), _schema_support__primary_index_columns(page_settings))
        self.assertIn(("UID",), _schema_support__unique_index_columns(page_settings))
        self.assertNotIn(
            ("BidPageUID", "BidAreaSelected"),
            _schema_support__unique_index_columns(page_settings),
        )
        self.assertEqual(
            _schema_support__relationship_targets(page_settings),
            {
                (("BidAreaUID",), "BidAreas"),
                (("BidPageUID",), "BidPages"),
                (("BidTypAreaUID",), "BidTypAreas"),
            },
        )
        bid_pages = metadata["key_tables"]["BidPages"]
        bid_named_views = metadata["key_tables"]["BidNamedViews"]
        self.assertIn("ALState", _schema_support__column_names(bid_pages))
        self.assertTrue(
            {"Color", "Origin"}.issubset(_schema_support__column_names(bid_named_views))
        )
        employees = metadata["key_tables"]["Employees"]
        pay_classes = metadata["key_tables"]["PayClasses"]
        bid_employees = metadata["key_tables"]["BidEmployees"]
        bids = metadata["key_tables"]["Bids"]
        self.assertIn("EstimatorUID", _schema_support__column_names(bids))
        self.assertIn("PayClassUID", _schema_support__column_names(employees))
        self.assertEqual(
            _schema_support__primary_index_columns(pay_classes), {("UID",)}
        )
        self.assertIn(
            (("EmployeeUID",), "Employees"),
            _schema_support__relationship_targets(bid_employees),
        )

    def test_app_created_mdb_key_schema_compatibility(self):
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "app_created.mdb"
            self.assertTrue(DatabaseCreator().create_database(db_path, "Compat"))
            metadata = _schema_support__extract_mdb_metadata(db_path)
        self.assertEqual(len(metadata["tables"]), 64)
        page_settings = metadata["key_tables"]["BidPageSettings"]
        self.assertIn("UID", _schema_support__column_names(page_settings))
        self.assertEqual(
            _schema_support__primary_index_columns(page_settings), {("UID",)}
        )
        self.assertNotIn(
            ("BidPageUID", "BidAreaSelected"),
            _schema_support__unique_index_columns(page_settings),
        )
        bid_pages = metadata["key_tables"]["BidPages"]
        bid_named_views = metadata["key_tables"]["BidNamedViews"]
        self.assertIn("ALState", _schema_support__column_names(bid_pages))
        self.assertTrue(
            {"Color", "Origin"}.issubset(_schema_support__column_names(bid_named_views))
        )

    def test_app_created_mdb_cover_sheet_accepts_blank_optional_values_and_page(self):
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "cover_sheet.mdb"
            self.assertTrue(DatabaseCreator().create_database(db_path, "Cover Sheet"))
            connection = _schema_support__connect_mdb(db_path)
            cursor = connection.cursor()
            try:
                ids = _schema_support__seed_minimal_bid(cursor)
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
            connection = _schema_support__connect_mdb(db_path)
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
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        fixture = _schema_support__load_reference_schema_fixture()
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
            snapshot = _schema_support__dao_created_schema_snapshot(db_path)
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
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            app_path = temp_path / "app_created.mdb"
            self.assertTrue(DatabaseCreator().create_database(app_path, "Compat"))
            for label in ("new", "app"):
                with self.subTest(database=label):
                    if label == "new":
                        # Machine-local reference OST database (not committed);
                        # the app-created database is still exercised without it.
                        if not _schema_support__NEW_MDB_PATH.exists():
                            self.skipTest(
                                f"MDB is not available at "
                                f"{_schema_support__NEW_MDB_PATH}"
                            )
                        db_path = temp_path / "new.mdb"
                        shutil.copy2(_schema_support__NEW_MDB_PATH, db_path)
                    else:
                        db_path = app_path
                    connection = _schema_support__connect_mdb(db_path)
                    cursor = connection.cursor()
                    try:
                        ids = _schema_support__seed_minimal_bid(cursor)
                        connection.commit()
                    finally:
                        cursor.close()
                        connection.close()

                    def page_settings():
                        reader_connection = _schema_support__connect_mdb(db_path)
                        reader_cursor = reader_connection.cursor()
                        try:
                            return _schema_support__fetch_dicts(
                                reader_cursor,
                                "SELECT [UID], [BidAreaUID], [BidAreaSelected] "
                                "FROM [BidPageSettings] WHERE [BidPageUID]=?",
                                ids["page_uid"],
                            )
                        finally:
                            reader_connection.rollback()
                            reader_cursor.close()
                            reader_connection.close()

                    writer = MdbWriter()
                    try:
                        # Each save leaves exactly one selected row: first the
                        # area, then the sibling area, then "unassigned" (area
                        # NULL with selection value 1).
                        for area_uid, expected_area, expected_selected in (
                            (ids["area_uid"], ids["area_uid"], 2),
                            (ids["area_uid"] + 1, ids["area_uid"] + 1, 2),
                            (0, None, 1),
                        ):
                            self.assertTrue(
                                writer.save_page_area(
                                    str(db_path),
                                    str(ids["page_uid"]),
                                    str(area_uid),
                                )
                            )
                            writer._conn_manager.close_database(str(db_path))
                            rows = page_settings()
                            self.assertEqual(len(rows), 1)
                            self.assertEqual(rows[0]["BidAreaUID"], expected_area)
                            self.assertEqual(
                                rows[0]["BidAreaSelected"], expected_selected
                            )
                    finally:
                        writer._conn_manager.close()
                    self.assertGreater(rows[0]["UID"], ids["page_uid"])

    def test_zz_employee_estimator_export_import_round_trip_on_supported_schema_versions(
        self,
    ):
        if not _schema_support__access_available():
            self.skipTest("Access ODBC/ADOX metadata is not available")
        cases = (
            ("new", _schema_support__NEW_MDB_PATH),
            ("app", None),
        )
        for label, source_path in cases:
            with self.subTest(database=label):
                if source_path is not None and not source_path.exists():
                    self.skipTest(f"{label} MDB is not available at {source_path}")
                source_path_text = None
                if source_path is not None:
                    source_path_text = str(source_path)
                code = (
                    "from tests.helpers.mdb.schema_support import "
                    "_run_employee_estimator_round_trip_for_label as run; "
                    f"run({label!r}, {source_path_text!r})"
                )
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )
