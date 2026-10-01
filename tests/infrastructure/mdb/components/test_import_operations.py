import logging
import sqlite3
import unittest
from collections import namedtuple
from contextlib import contextmanager
from types import SimpleNamespace
import datetime
import pyodbc
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.database.settings_cardinality import (
    BidNumberAllocationUnavailableError,
    GlobalSettingsCardinalityError,
)
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from tests.helpers.mdb.import_export_support import (
    _Rows as _import_export_support__Rows,
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteCursor as _import_export_support__SqliteCursor,
    _SqliteMdbWriter as _import_export_support__SqliteMdbWriter,
    _SqliteSchema as _import_export_support__SqliteSchema,
    _create_import_schema as _import_export_support__create_import_schema,
    _named_row as _import_export_support__named_row,
)


class ImportOperationsRelationshipTests(unittest.TestCase):
    def test_access_import_uid_floor_includes_dangling_target_references(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        connection.execute("INSERT INTO Bids VALUES (1)")
        connection.execute("CREATE TABLE BidNotes (UID INTEGER, BidUID INTEGER)")
        connection.execute("INSERT INTO BidNotes VALUES (10, 2)")
        writer = _import_export_support__SqliteMdbWriter(connection)
        max_uid = writer._get_max_uid(
            _import_export_support__SqliteConnection(connection)
        )
        self.assertEqual(max_uid, 2)

    def test_access_import_uid_floor_uses_highest_uid_across_import_tables(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        connection.execute("CREATE TABLE BidAreas (UID INTEGER)")
        connection.execute("CREATE TABLE CdnTypes (UID INTEGER)")
        connection.execute("CREATE TABLE BidTakeoffs (UID INTEGER)")
        connection.execute("INSERT INTO Bids VALUES (4)")
        connection.executemany("INSERT INTO BidAreas VALUES (?)", ((9,), (50,)))
        connection.execute("INSERT INTO CdnTypes VALUES (17)")
        connection.execute("INSERT INTO BidTakeoffs VALUES (31)")
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertEqual(
            writer._get_max_uid(_import_export_support__SqliteConnection(connection)),
            50,
        )
        empty = sqlite3.connect(":memory:")
        self.assertEqual(
            _import_export_support__SqliteMdbWriter(empty)._get_max_uid(
                _import_export_support__SqliteConnection(empty)
            ),
            0,
        )

    def test_bid_number_assignment_initializes_missing_global_settings_once(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection, next_bid_numbers=())
        writer = _import_export_support__SqliteMdbWriter(connection)
        first = RawBidData(bid_row={})
        second = RawBidData(bid_row={})
        writer._assign_next_bid_no(
            _import_export_support__SqliteConnection(connection), first
        )
        writer._assign_next_bid_no(
            _import_export_support__SqliteConnection(connection), second
        )
        self.assertEqual(first.bid_row["BidNo"], "1")
        self.assertEqual(second.bid_row["BidNo"], "2")
        self.assertEqual(
            connection.execute("SELECT NextBidNo FROM Settings").fetchall(),
            [(3,)],
        )

    def test_bid_number_assignment_rejects_multiple_global_settings_rows(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(
            connection, next_bid_numbers=(7, 12)
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        remapped = RawBidData(bid_row={})
        with self.assertRaisesRegex(
            GlobalSettingsCardinalityError,
            "Settings has multiple rows; expected at most one",
        ):
            writer._assign_next_bid_no(
                _import_export_support__SqliteConnection(connection), remapped
            )
        self.assertNotIn("BidNo", remapped.bid_row)
        self.assertEqual(
            connection.execute(
                "SELECT NextBidNo FROM Settings ORDER BY NextBidNo"
            ).fetchall(),
            [(7,), (12,)],
        )

    def test_bid_number_assignment_normalizes_zero_to_the_documented_default(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection, next_bid_numbers=(0,))
        writer = _import_export_support__SqliteMdbWriter(connection)
        remapped = RawBidData(bid_row={})
        writer._assign_next_bid_no(
            _import_export_support__SqliteConnection(connection), remapped
        )
        self.assertEqual(remapped.bid_row["BidNo"], "1")
        self.assertEqual(
            connection.execute("SELECT NextBidNo FROM Settings").fetchall(),
            [(2,)],
        )

    def test_bid_number_assignment_rejects_nonnumeric_malformed_value(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(
            connection, next_bid_numbers=("not-a-number",)
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        remapped = RawBidData(bid_row={})
        with self.assertRaises(ValueError):
            writer._assign_next_bid_no(
                _import_export_support__SqliteConnection(connection), remapped
            )
        self.assertNotIn("BidNo", remapped.bid_row)
        self.assertEqual(
            connection.execute("SELECT NextBidNo FROM Settings").fetchall(),
            [("not-a-number",)],
        )

    def test_bid_number_assignment_does_not_swallow_sequence_write_failure(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "CREATE TRIGGER fail_settings_update BEFORE UPDATE ON Settings "
            "BEGIN SELECT RAISE(FAIL, 'sequence write failed'); END"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with self.assertRaisesRegex(pyodbc.Error, "sequence write failed"):
            writer._assign_next_bid_no(
                _import_export_support__SqliteConnection(connection),
                RawBidData(bid_row={}),
            )

    def test_bid_number_assignment_rejects_missing_settings_table(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE Settings")
        writer = _import_export_support__SqliteMdbWriter(connection)
        with self.assertRaisesRegex(
            BidNumberAllocationUnavailableError,
            "Settings table is unavailable",
        ):
            writer._assign_next_bid_no(
                _import_export_support__SqliteConnection(connection),
                RawBidData(bid_row={}),
            )

    def test_bid_number_assignment_rejects_missing_next_bid_number_column(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE Settings")
        connection.execute("CREATE TABLE Settings (Name TEXT)")
        writer = _import_export_support__SqliteMdbWriter(connection)
        with self.assertRaisesRegex(
            BidNumberAllocationUnavailableError,
            "Settings.NextBidNo is unavailable",
        ):
            writer._assign_next_bid_no(
                _import_export_support__SqliteConnection(connection),
                RawBidData(bid_row={}),
            )

    def test_access_import_rejects_ambiguous_job_status_name(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.executemany(
            "INSERT INTO JobStatuses (UID, Name, Locked, Sequence) "
            "VALUES (?, 'Open', ?, ?)",
            ((10, 0, 1), (11, 1, 2)),
        )
        connection.commit()
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "JobStatuses": [
                    {"UID": "90", "Name": "Open", "Locked": "0", "Sequence": "1"}
                ]
            },
        )
        with self.assertRaisesRegex(RuntimeError, "ambiguous.*JobStatuses.Name"):
            writer._resolve_job_statuses(
                _import_export_support__SqliteConnection(connection),
                raw_data,
                max_uid=100,
            )
        self.assertEqual(
            connection.execute("SELECT UID FROM JobStatuses ORDER BY UID").fetchall(),
            [(10,), (11,)],
        )

    def test_access_import_rejects_duplicate_target_master_uid(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE CdnTypes")
        connection.execute(
            "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT, ExpandState INTEGER)"
        )
        connection.executemany(
            "INSERT INTO CdnTypes (UID, Name) VALUES (7, ?)",
            (("Concrete",), ("Conflicting",)),
        )
        raw_data = RawBidData(
            global_tables={"CdnTypes": [{"UID": "90", "Name": "Concrete"}]}
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "CdnTypes contains duplicate UID 7",
        ):
            _import_export_support__SqliteMdbWriter(connection)._resolve_cdn_types(
                _import_export_support__SqliteConnection(connection),
                raw_data,
                max_uid=100,
            )

    def test_access_import_rejects_ambiguous_pay_class_name(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.executemany(
            "INSERT INTO PayClasses (UID, Name) VALUES (?, 'Regular')",
            ((20,), (21,)),
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"PayClasses": [{"UID": "91", "Name": "Regular"}]},
        )
        with self.assertRaisesRegex(RuntimeError, "ambiguous.*PayClasses.Name"):
            writer._resolve_pay_classes(
                _import_export_support__SqliteConnection(connection), raw_data
            )
        self.assertEqual(
            connection.execute("SELECT UID FROM PayClasses ORDER BY UID").fetchall(),
            [(20,), (21,)],
        )

    def test_access_import_rejects_ambiguous_access_level_description(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE AccessLevels")
        connection.execute(
            "CREATE TABLE AccessLevels "
            "(UID INTEGER PRIMARY KEY, Description TEXT, Privileges INTEGER)"
        )
        connection.executemany(
            "INSERT INTO AccessLevels (UID, Description) VALUES (?, 'Full')",
            ((15,), (16,)),
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"AccessLevels": [{"UID": "96", "Description": "Full"}]},
        )
        with self.assertRaisesRegex(
            RuntimeError, "ambiguous.*AccessLevels.Description"
        ):
            writer._resolve_access_levels(
                _import_export_support__SqliteConnection(connection), raw_data
            )

    def test_access_import_rejects_duplicate_incoming_pay_class_name(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "PayClasses": [
                    {"UID": "91", "Name": "Regular"},
                    {"UID": "92", "Name": "Regular"},
                ]
            },
        )
        with self.assertRaisesRegex(RuntimeError, "ambiguous.*PayClasses.Name"):
            writer._resolve_pay_classes(
                _import_export_support__SqliteConnection(connection), raw_data
            )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM PayClasses").fetchone()[0], 0
        )

    def test_access_import_rejects_ambiguous_employee_business_key(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.executemany(
            "INSERT INTO Employees "
            "(UID, EmployeeNo, FirstName, LastName) VALUES (?, 'E100', ?, ?)",
            ((30, "Alice", "One"), (31, "Alex", "Two")),
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {
                        "UID": "92",
                        "EmployeeNo": "e100",
                        "FirstName": "Imported",
                        "LastName": "Employee",
                    }
                ]
            },
        )
        with self.assertRaisesRegex(RuntimeError, "ambiguous.*Employees"):
            writer._resolve_employees(
                _import_export_support__SqliteConnection(connection), raw_data, {}, {}
            )
        self.assertEqual(
            connection.execute("SELECT UID FROM Employees ORDER BY UID").fetchall(),
            [(30,), (31,)],
        )

    def test_access_import_master_inserts_preserve_dangling_reference_uids(self):
        fixtures = (
            (
                "AccessLevels",
                (
                    "CREATE TABLE AccessLevels (UID INTEGER, Description TEXT)",
                    "CREATE TABLE Employees (UID INTEGER, AccessLevelUID INTEGER)",
                ),
                (
                    "INSERT INTO AccessLevels VALUES (1, 'Existing')",
                    "INSERT INTO Employees VALUES (10, 2)",
                ),
                RawBidData(
                    bid_row={"UID": "1"},
                    global_tables={
                        "AccessLevels": [{"UID": "90", "Description": "New"}]
                    },
                ),
                lambda writer, connection, raw: writer._resolve_access_levels(
                    connection, raw
                ),
                {"90": "3"},
            ),
            (
                "PayClasses",
                (
                    "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                    "CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER)",
                ),
                (
                    "INSERT INTO PayClasses VALUES (1, 'Existing')",
                    "INSERT INTO Employees VALUES (10, 2)",
                ),
                RawBidData(
                    bid_row={"UID": "1"},
                    global_tables={"PayClasses": [{"UID": "90", "Name": "New"}]},
                ),
                lambda writer, connection, raw: writer._resolve_pay_classes(
                    connection, raw
                ),
                {"90": "3"},
            ),
            (
                "Employees",
                (
                    "CREATE TABLE Employees ("
                    "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT)",
                    "CREATE TABLE Bids (UID INTEGER, EstimatorUID INTEGER)",
                ),
                (
                    "INSERT INTO Employees VALUES (1, 'E1', 'Ava', 'Lee')",
                    "INSERT INTO Bids VALUES (10, 2)",
                ),
                RawBidData(
                    bid_row={"UID": "1"},
                    global_tables={
                        "Employees": [
                            {
                                "UID": "90",
                                "EmployeeNo": "E2",
                                "FirstName": "Mia",
                                "LastName": "Ray",
                            }
                        ]
                    },
                ),
                lambda writer, connection, raw: writer._resolve_employees(
                    connection, raw, {}, {}
                ),
                {"90": "3"},
            ),
        )
        for table, ddl, inserts, raw_data, resolve, expected in fixtures:
            with self.subTest(table=table):
                connection = sqlite3.connect(":memory:")
                for statement in ddl:
                    connection.execute(statement)
                for statement in inserts:
                    connection.execute(statement)
                writer = _import_export_support__SqliteMdbWriter(connection)
                result = resolve(
                    writer,
                    _import_export_support__SqliteConnection(connection),
                    raw_data,
                )
                self.assertEqual(result, expected)
                self.assertEqual(
                    connection.execute(
                        f"SELECT [UID] FROM [{table}] ORDER BY [UID]"
                    ).fetchall(),
                    [(1,), (3,)],
                )

    def test_access_import_uses_condition_type_name_contract(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "INSERT INTO CdnTypes (UID, Name, ExpandState) "
            "VALUES (40, ' Concrete ', 0)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "CdnTypes": [{"UID": "93", "Name": "concrete", "ExpandState": "0"}]
            },
        )
        uid_map, max_uid = writer._resolve_cdn_types(
            _import_export_support__SqliteConnection(connection), raw_data, max_uid=100
        )
        self.assertEqual(uid_map, {"93": "40"})
        self.assertEqual(max_uid, 100)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 1
        )

    def test_access_import_rejects_ambiguous_condition_type_name_contract(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.executemany(
            "INSERT INTO CdnTypes (UID, Name, ExpandState) VALUES (?, ?, 0)",
            ((40, "Concrete"), (41, " concrete ")),
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "CdnTypes": [{"UID": "93", "Name": "CONCRETE", "ExpandState": "0"}]
            },
        )
        with self.assertRaisesRegex(RuntimeError, "ambiguous.*CdnTypes.Name"):
            writer._resolve_cdn_types(
                _import_export_support__SqliteConnection(connection),
                raw_data,
                max_uid=100,
            )
        self.assertEqual(
            connection.execute("SELECT UID FROM CdnTypes ORDER BY UID").fetchall(),
            [(40,), (41,)],
        )

    def test_access_import_inserts_new_master_rows_above_the_uid_floor(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "INSERT INTO CdnTypes (UID, Name, ExpandState) VALUES (40, 'Existing', 0)"
        )
        connection.execute(
            "INSERT INTO JobStatuses (UID, Name, Locked, Sequence) "
            "VALUES (50, 'Open', 0, 1)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        wrapped = _import_export_support__SqliteConnection(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "CdnTypes": [
                    {"UID": "93", "Name": "Existing", "ExpandState": "0"},
                    {"UID": "94", "Name": "Footings", "ExpandState": "-1"},
                    {"UID": "95", "Name": "Slabs", "ExpandState": ""},
                ],
                "JobStatuses": [
                    {"UID": "7", "Name": "Open", "Locked": "0", "Sequence": "1"},
                    {"UID": "8", "Name": "Won", "Locked": "1", "Sequence": "2"},
                ],
            },
        )
        cdn_map, max_uid = writer._resolve_cdn_types(wrapped, raw_data, max_uid=100)
        self.assertEqual(cdn_map, {"93": "40", "94": "101", "95": "102"})
        self.assertEqual(max_uid, 102)
        status_map, max_uid = writer._resolve_job_statuses(wrapped, raw_data, max_uid)
        self.assertEqual(status_map, {"7": "50", "8": "103"})
        self.assertEqual(max_uid, 103)
        self.assertEqual(
            connection.execute(
                "SELECT UID, Name, ExpandState FROM CdnTypes ORDER BY UID"
            ).fetchall(),
            [(40, "Existing", 0), (101, "Footings", -1), (102, "Slabs", None)],
        )
        self.assertEqual(
            connection.execute(
                "SELECT UID, Name, Locked, Sequence FROM JobStatuses ORDER BY UID"
            ).fetchall(),
            [(50, "Open", 0, 1), (103, "Won", 1, 2)],
        )
        # Re-resolving the same payload reuses the rows inserted above.
        again, max_uid = writer._resolve_cdn_types(wrapped, raw_data, max_uid=103)
        self.assertEqual(again, {"93": "40", "94": "101", "95": "102"})
        self.assertEqual(max_uid, 103)

    def test_access_import_empty_or_missing_master_tables_return_empty_maps(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE PayClasses")
        connection.execute("DROP TABLE AccessLevels")
        connection.execute("DROP TABLE Employees")
        writer = _import_export_support__SqliteMdbWriter(connection)
        wrapped = _import_export_support__SqliteConnection(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "PayClasses": [{"UID": "1", "Name": "Regular"}],
                "AccessLevels": [{"UID": "2", "Description": "Full"}],
                "Employees": [{"UID": "3", "EmployeeNo": "E1"}],
            },
        )
        self.assertEqual(writer._resolve_pay_classes(wrapped, raw_data), {})
        self.assertEqual(writer._resolve_access_levels(wrapped, raw_data), {})
        self.assertEqual(writer._resolve_employees(wrapped, raw_data, {}, {}), {})
        empty = RawBidData(bid_row={"UID": "1"})
        self.assertEqual(writer._resolve_cdn_types(wrapped, empty, 7), ({}, 7))
        self.assertEqual(writer._resolve_job_statuses(wrapped, empty, 7), ({}, 7))

    def test_access_import_employees_reuse_business_key_and_remap_references(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE Employees")
        connection.execute(
            "CREATE TABLE Employees (UID INTEGER, EmployeeNo TEXT, FirstName TEXT, "
            "LastName TEXT, EMail TEXT, PayClassUID INTEGER, AccessLevelUID INTEGER)"
        )
        connection.execute(
            "INSERT INTO Employees VALUES (4, 'E1', 'Ava', 'Lee', NULL, NULL, NULL)"
        )
        connection.execute(
            "INSERT INTO Employees VALUES (8, NULL, 'Bo', 'Kay', NULL, NULL, NULL)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {"UID": "90", "EmployeeNo": " e1 ", "FirstName": "Renamed"},
                    {
                        "UID": "91",
                        "EmployeeNo": "",
                        "FirstName": "Mia",
                        "LastName": "Ray",
                        "EMail": "mia@example.test",
                        "PayClassUID": "70",
                        "AccessLevelUID": "80",
                    },
                    {
                        "UID": "92",
                        "EmployeeNo": "E3",
                        "FirstName": "Zed",
                        "PayClassUID": "71",
                        "AccessLevelUID": "81",
                    },
                    {"UID": "93", "EmployeeNo": "", "FirstName": "", "LastName": ""},
                    {"UID": "94", "FirstName": " BO ", "LastName": "kay"},
                ]
            },
        )
        employee_map = writer._resolve_employees(
            _import_export_support__SqliteConnection(connection),
            raw_data,
            {"70": "12"},
            {"81": "13"},
        )
        self.assertEqual(
            employee_map, {"90": "4", "91": "9", "92": "10", "93": "11", "94": "8"}
        )
        self.assertEqual(
            connection.execute(
                "SELECT UID, EmployeeNo, FirstName, LastName, EMail, PayClassUID, "
                "AccessLevelUID FROM Employees ORDER BY UID"
            ).fetchall(),
            [
                (4, "E1", "Ava", "Lee", None, None, None),
                (8, None, "Bo", "Kay", None, None, None),
                (9, "", "Mia", "Ray", "mia@example.test", 12, None),
                (10, "E3", "Zed", None, None, None, 13),
                (11, "", "", "", None, None, None),
            ],
        )

    def test_access_import_pay_classes_and_access_levels_reuse_names_and_insert_rest(
        self,
    ):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE AccessLevels")
        connection.execute(
            "CREATE TABLE AccessLevels "
            "(UID INTEGER, Description TEXT, Privileges INTEGER)"
        )
        connection.execute("INSERT INTO PayClasses VALUES (20, 'Regular')")
        connection.execute("INSERT INTO AccessLevels VALUES (15, 'Full', 7)")
        writer = _import_export_support__SqliteMdbWriter(connection)
        wrapped = _import_export_support__SqliteConnection(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "PayClasses": [
                    {"UID": "91", "Name": "Regular"},
                    {"UID": "92", "Name": "Overtime"},
                    {"UID": "93", "Name": ""},
                    {"UID": "94", "Name": ""},
                ],
                "AccessLevels": [
                    {"UID": "96", "Description": "Full", "Privileges": "1"},
                    {"UID": "97", "Description": "Read", "Privileges": "2"},
                    {"UID": "98", "Description": "", "Privileges": "3"},
                ],
            },
        )
        self.assertEqual(
            writer._resolve_pay_classes(wrapped, raw_data),
            {"91": "20", "92": "21", "93": "22", "94": "23"},
        )
        self.assertEqual(
            writer._resolve_access_levels(wrapped, raw_data),
            {"96": "15", "97": "16", "98": "17"},
        )
        self.assertEqual(
            connection.execute(
                "SELECT UID, Name FROM PayClasses ORDER BY UID"
            ).fetchall(),
            [(20, "Regular"), (21, "Overtime"), (22, ""), (23, "")],
        )
        self.assertEqual(
            connection.execute(
                "SELECT UID, Description, Privileges FROM AccessLevels ORDER BY UID"
            ).fetchall(),
            [(15, "Full", 7), (16, "Read", 2), (17, "", 3)],
        )

    def test_access_import_value_conversion_follows_access_column_types(self):
        writer = _import_export_support__SqliteMdbWriter(sqlite3.connect(":memory:"))
        convert = writer._convert_access_value
        for value in (None, "NULL"):
            for type_name in ("yesno", "datetime", "longbinary", "integer", "text"):
                with self.subTest(value=value, type_name=type_name):
                    self.assertIsNone(convert(value, type_name))
        for value, expected in (
            ("True", -1),
            ("true", -1),
            ("-1", -1),
            ("1", -1),
            ("0", 0),
            ("False", 0),
            ("", 0),
        ):
            with self.subTest(yesno=value):
                self.assertEqual(convert(value, "yesno"), expected)
        self.assertEqual(
            convert("2024 3 9 14 5 7", "datetime"),
            datetime.datetime(2024, 3, 9, 14, 5, 7),
        )
        for bad_date in (
            "",
            "2024-03-09",
            "2024 3 9",
            "2024 13 9 1 1 1",
            "a b c d e f",
        ):
            with self.subTest(bad_date=bad_date):
                self.assertIsNone(convert(bad_date, "datetime"))
        self.assertEqual(
            convert("note", "longbinary", table="BidNotes", column="Notes"), b"note"
        )
        self.assertEqual(convert("caf\u00e9", "memo"), "caf\u00e9".encode("utf-8"))
        self.assertEqual(
            convert("caf\u00e9", "longbinary", table="BidTexts", column="Name"),
            "caf\u00e9".encode("latin-1"),
        )
        self.assertEqual(
            convert("caf\u00e9", "longbinary", table="BidTexts", column="Other"),
            "caf\u00e9".encode("utf-8"),
        )
        self.assertIsNone(convert("", "longbinary"))
        self.assertIsNone(convert("", "memo"))
        for type_name, value, expected in (
            ("integer", "7", 7),
            ("integer", "0", 0),
            ("integer", "-3", -3),
            ("double", "1.5", 1.5),
            ("double", "4", 4),
            ("integer", "", None),
            ("integer", "abc", None),
            ("counter", "12", 12),
            ("varchar", "007", "007"),
            ("", "plain", "plain"),
        ):
            with self.subTest(type_name=type_name, value=value):
                self.assertEqual(convert(value, type_name), expected)
                self.assertIs(type(convert(value, type_name)), type(expected))

    def test_access_import_raw_row_insert_filters_columns_and_omits_blank_autonumber(
        self,
    ):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE Sample (UID COUNTER, Name TEXT, Count INTEGER, Flag YESNO)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        wrapped = _import_export_support__SqliteConnection(connection)
        table_info = writer._get_table_info(wrapped, "Sample")
        self.assertEqual(
            table_info,
            (
                {"UID", "Name", "Count", "Flag"},
                {"UID": "counter", "Name": "text", "Count": "integer", "Flag": "yesno"},
            ),
        )
        for blank_uid in ("", "0", "NULL", None):
            writer._insert_raw_row(
                wrapped,
                "Sample",
                {"UID": blank_uid, "Name": f"blank-{blank_uid}", "Unknown": "x"},
                table_info,
            )
        writer._insert_raw_row(
            wrapped,
            "Sample",
            {"UID": "5", "Name": "explicit", "Count": "9", "Flag": "True"},
            table_info,
        )
        writer._insert_raw_row(wrapped, "Sample", {"Unknown": "only"}, table_info)
        self.assertEqual(
            connection.execute("SELECT UID, Name, Count, Flag FROM Sample").fetchall(),
            [
                (None, "blank-", None, None),
                (None, "blank-0", None, None),
                (None, "blank-NULL", None, None),
                (None, "blank-None", None, None),
                (5, "explicit", 9, -1),
            ],
        )

    def test_access_import_writes_bid_tables_in_dependency_order_before_page_tables(
        self,
    ):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER)")
        statements = []
        connection.set_trace_callback(statements.append)
        writer = _import_export_support__SqliteMdbWriter(connection)
        remapped = RawBidData(
            bid_row={"UID": "5", "JobName": "Imported"},
            bid_tables={
                "BidPages": [
                    {"UID": "20", "BidUID": "5", "Name": "P", "Sequence": "1"}
                ],
                "BidAreas": [{"UID": "30", "BidUID": "5", "Name": "A"}],
            },
            page_tables={"BidTakeoffs": [{"UID": "40", "BidPageUID": "20"}]},
        )
        writer._write_to_db(
            _import_export_support__SqliteConnection(connection), remapped
        )
        inserted = [
            sql.split("[")[1].split("]")[0]
            for sql in statements
            if sql.startswith("INSERT INTO")
        ]
        self.assertEqual(inserted, ["Bids", "BidAreas", "BidPages", "BidTakeoffs"])

    def test_access_import_rolls_back_every_write_when_a_bid_row_fails(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection, next_bid_numbers=(7,))
        connection.commit()
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "5", "JobName": "Imported"},
            global_tables={
                "CdnTypes": [{"UID": "9", "Name": "New", "ExpandState": "0"}]
            },
        )

        def transform(_raw, _max_uid, _cdn, _status, _employee, _pay):
            return RawBidData(
                bid_row={"UID": "5", "JobName": "Imported"},
                bid_tables={
                    "BidAreas": [
                        {"UID": "30", "BidUID": "5", "Name": "A"},
                        {"UID": "30", "BidUID": "5", "Name": "Duplicate primary key"},
                    ]
                },
            )

        with self.assertLogs("test", level="ERROR"):
            self.assertFalse(writer.import_ost_data("target.mdb", raw_data, transform))
        for table, column, expected in (
            ("Bids", "UID", []),
            ("BidAreas", "UID", []),
            ("CdnTypes", "UID", []),
            ("Settings", "NextBidNo", [(7,)]),
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    connection.execute(f"SELECT {column} FROM {table}").fetchall(),
                    expected,
                )

    def test_access_import_passes_resolved_maps_to_transform_and_assigns_project(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection, next_bid_numbers=(7,))
        connection.execute(
            "INSERT INTO CdnTypes (UID, Name, ExpandState) VALUES (40, 'Concrete', 0)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Imported"},
            global_tables={
                "CdnTypes": [{"UID": "9", "Name": "concrete", "ExpandState": "0"}],
                "JobStatuses": [
                    {"UID": "3", "Name": "Won", "Locked": "0", "Sequence": "1"}
                ],
                "PayClasses": [{"UID": "4", "Name": "Regular"}],
            },
        )
        captured = []

        def transform(raw, max_uid, cdn, status, employee, pay):
            captured.append((raw, max_uid, cdn, status, employee, pay))
            return RawBidData(
                bid_row={"UID": "50", "JobName": "Imported", "BidProjectUID": "99"}
            )

        for target, expected_row in (
            (None, (50, None, "Imported", 7)),
            ("12", (50, 12, "Imported", 8)),
        ):
            with self.subTest(target_project_uid=target):
                connection.execute("DELETE FROM Bids")
                self.assertTrue(
                    writer.import_ost_data("target.mdb", raw_data, transform, target)
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT UID, BidProjectUID, JobName, BidNo FROM Bids"
                    ).fetchall(),
                    [expected_row],
                )
        self.assertEqual(len(captured), 2)
        for raw, max_uid, cdn, status, employee, pay in captured:
            self.assertIs(raw, raw_data)
            self.assertEqual(max_uid, 41)
            self.assertEqual(cdn, {"9": "40"})
            self.assertEqual(status, {"3": "41"})
            self.assertEqual(employee, {})
            self.assertEqual(pay, {"4": "1"})
        self.assertEqual(
            connection.execute("SELECT UID, Name FROM JobStatuses").fetchall(),
            [(41, "Won")],
        )
