import logging
import sqlite3
import unittest
from collections import namedtuple
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
import datetime
import pyodbc
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.database.settings_cardinality import (
    BidNumberAllocationUnavailableError,
    GlobalSettingsCardinalityError,
)
from ost_visualizer.infrastructure.database.master_data_identity import (
    AmbiguousMasterDataIdentityError,
)
from ost_visualizer.infrastructure.mdb.components import (
    import_operations as import_operations_module,
)
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import RawBidRelationship
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
        with self.assertRaisesRegex(
            RuntimeError,
            r"^Imported master-data identity is ambiguous for "
            r"JobStatuses[.]Name: matching UIDs 10, 11[.]$",
        ):
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
        with self.assertRaisesRegex(
            RuntimeError,
            r"^Imported master-data identity is ambiguous for "
            r"PayClasses[.]Name: matching UIDs 20, 21[.]$",
        ):
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
            RuntimeError,
            r"^Imported master-data identity is ambiguous for "
            r"AccessLevels[.]Description: matching UIDs 15, 16[.]$",
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
        with self.assertRaisesRegex(
            RuntimeError,
            r"^Imported master-data identity is ambiguous for "
            r"PayClasses[.]Name: matching UIDs 91, 92[.]$",
        ):
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
        with self.assertRaisesRegex(
            RuntimeError,
            r"^Imported master-data identity is ambiguous for "
            r"Employees business key: matching UIDs 30, 31[.]$",
        ):
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
        with self.assertRaisesRegex(
            RuntimeError,
            r"^Imported master-data identity is ambiguous for "
            r"CdnTypes[.]Name: matching UIDs 40, 41[.]$",
        ):
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

        with self.assertLogs("test", level="ERROR") as logs:
            outcome = writer.import_ost_data("target.mdb", raw_data, transform)
        self.assertIs(outcome, False)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed inserting into [BidAreas], row_uid=30, "
                "columns=['BidUID', 'Name', 'UID'], "
                "error=UNIQUE constraint failed: BidAreas.UID",
                "Failed to write imported OST data to target.mdb",
            ],
        )
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


class _RecordingCursor(_import_export_support__SqliteCursor):
    def __init__(self, connection, owner):
        super().__init__(connection)
        self._owner = owner
        self.closed = False

    def execute(self, query, *params):
        self._owner.statements.append(query)
        return super().execute(query, *params)

    def close(self):
        self.closed = True


class _RecordingConnection(_import_export_support__SqliteConnection):
    def __init__(self, connection):
        super().__init__(connection)
        self.cursors = []
        self.statements = []

    def cursor(self):
        cursor = _RecordingCursor(self._connection, self)
        self.cursors.append(cursor)
        return cursor

    def assert_every_cursor_closed(self, testcase):
        testcase.assertGreater(len(self.cursors), 0)
        testcase.assertEqual([c for c in self.cursors if not c.closed], [])


class _ColumnsCursor:
    def __init__(self, rows=(), error=None):
        self._rows = list(rows)
        self._error = error
        self.closed = False
        self.requested = []

    def columns(self, table):
        self.requested.append(table)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(fetchall=lambda: self._rows)

    def close(self):
        self.closed = True


class _ColumnsConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _ambiguity(label, uids):
    return (
        f"Imported master-data identity is ambiguous for {label}: "
        f"matching UIDs {uids}."
    )


class ImportOperationsFailureAndRollbackTests(unittest.TestCase):
    def _writer(self, **schema_options):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection, **schema_options)
        connection.commit()
        return connection, _import_export_support__SqliteMdbWriter(connection)

    @staticmethod
    def _transform_to(remapped):
        def transform(_raw, _max_uid, _cdn, _status, _employee, _pay):
            return remapped

        return transform

    def _assert_rolled_back(self, connection, next_bid_numbers):
        for table in ("Bids", "BidAreas", "BidPages", "CdnTypes", "JobStatuses"):
            with self.subTest(table=table):
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    0,
                )
        self.assertEqual(
            connection.execute("SELECT NextBidNo FROM Settings").fetchall(),
            [(value,) for value in next_bid_numbers],
        )

    def test_a_page_table_failure_rolls_back_every_earlier_table_and_is_logged(self):
        connection, writer = self._writer(next_bid_numbers=(7,))
        connection.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidPageUID INTEGER)"
        )
        connection.commit()
        raw_data = RawBidData(
            bid_row={"UID": "5"},
            global_tables={
                "CdnTypes": [{"UID": "9", "Name": "New", "ExpandState": "0"}],
                "JobStatuses": [
                    {"UID": "3", "Name": "Won", "Locked": "0", "Sequence": "1"}
                ],
            },
        )
        remapped = RawBidData(
            bid_row={"UID": "5", "JobName": "Imported"},
            bid_tables={
                "BidAreas": [{"UID": "30", "BidUID": "5", "Name": "Area"}],
                "BidPages": [{"UID": "20", "BidUID": "5", "Name": "Sheet"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {"UID": "40", "BidPageUID": "20"},
                    {"UID": "40", "BidPageUID": "20"},
                ]
            },
        )
        with self.assertLogs("test", level="ERROR") as logs:
            outcome = writer.import_ost_data(
                "target.mdb", raw_data, self._transform_to(remapped)
            )
        self.assertIs(outcome, False)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed inserting into [BidTakeoffs], row_uid=40, "
                "columns=['BidPageUID', 'UID'], "
                "error=UNIQUE constraint failed: BidTakeoffs.UID",
                "Failed to write imported OST data to target.mdb",
            ],
        )
        self.assertIs(logs.records[1].exc_info[0], pyodbc.Error)
        self._assert_rolled_back(connection, (7,))
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 0
        )

    def test_every_pre_write_stage_failure_rolls_back_the_earlier_stages(self):
        def ambiguous_job_status(connection):
            connection.executemany(
                "INSERT INTO JobStatuses (UID, Name, Locked, Sequence) "
                "VALUES (?, 'Open', 0, 1)",
                ((10,), (11,)),
            )

        def exploding_transform(*_arguments):
            raise ValueError("transform exploded")

        good_bid = RawBidData(bid_row={"UID": "5", "JobName": "Imported"})
        cases = (
            (
                "job statuses ambiguous after condition types were inserted",
                ambiguous_job_status,
                self._transform_to(good_bid),
                (7,),
                AmbiguousMasterDataIdentityError,
                2,
            ),
            (
                "transform raised after master data was inserted",
                lambda _connection: None,
                exploding_transform,
                (7,),
                ValueError,
                0,
            ),
            (
                "bid number allocation rejected multiple settings rows",
                lambda _connection: None,
                self._transform_to(good_bid),
                (7, 12),
                GlobalSettingsCardinalityError,
                0,
            ),
        )
        for label, prepare, transform, settings, error_type, statuses in cases:
            with self.subTest(stage=label):
                connection, writer = self._writer(next_bid_numbers=settings)
                prepare(connection)
                connection.commit()
                raw_data = RawBidData(
                    bid_row={"UID": "5"},
                    global_tables={
                        "CdnTypes": [{"UID": "9", "Name": "New", "ExpandState": "0"}],
                        "JobStatuses": [
                            {"UID": "3", "Name": "Open", "Locked": "0", "Sequence": "1"}
                        ],
                    },
                )
                with self.assertLogs("test", level="ERROR") as logs:
                    outcome = writer.import_ost_data("target.mdb", raw_data, transform)
                self.assertIs(outcome, False)
                self.assertEqual(
                    logs.records[-1].getMessage(),
                    "Failed to write imported OST data to target.mdb",
                )
                self.assertIs(logs.records[-1].exc_info[0], error_type)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0],
                    0,
                    "the CdnTypes insert must be rolled back",
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM JobStatuses").fetchone()[0],
                    statuses,
                    "only the pre-existing JobStatuses rows may remain",
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
                )
                self.assertEqual(
                    connection.execute("SELECT NextBidNo FROM Settings").fetchall(),
                    [(value,) for value in settings],
                )

    def test_missing_settings_table_rolls_back_master_data_and_bid_writes(self):
        connection, writer = self._writer(next_bid_numbers=(7,))
        connection.execute("DROP TABLE Settings")
        connection.commit()
        raw_data = RawBidData(
            bid_row={"UID": "5"},
            global_tables={"CdnTypes": [{"UID": "9", "Name": "New", "ExpandState": "0"}]},
        )
        remapped = RawBidData(bid_row={"UID": "5", "JobName": "Imported"})
        with self.assertLogs("test", level="ERROR") as logs:
            outcome = writer.import_ost_data(
                "target.mdb", raw_data, self._transform_to(remapped)
            )
        self.assertIs(outcome, False)
        self.assertIs(logs.records[-1].exc_info[0], BidNumberAllocationUnavailableError)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 0
        )
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0)

    def test_a_non_numeric_uid_in_the_target_stops_the_import_before_any_write(self):
        connection, writer = self._writer(next_bid_numbers=(7,))
        connection.execute("DROP TABLE BidAreas")
        connection.execute("CREATE TABLE BidAreas (UID INTEGER, Name TEXT)")
        connection.execute("INSERT INTO BidAreas (UID, Name) VALUES ('abc', 'corrupt')")
        connection.commit()
        raw_data = RawBidData(
            bid_row={"UID": "5"},
            global_tables={"CdnTypes": [{"UID": "9", "Name": "New", "ExpandState": "0"}]},
        )
        remapped = RawBidData(bid_row={"UID": "5", "JobName": "Imported"})
        with self.assertLogs("test", level="ERROR") as logs:
            outcome = writer.import_ost_data(
                "target.mdb", raw_data, self._transform_to(remapped)
            )
        self.assertIs(outcome, False)
        self.assertIs(logs.records[-1].exc_info[0], ValueError)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 0
        )
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0)
        self.assertEqual(
            connection.execute("SELECT NextBidNo FROM Settings").fetchall(), [(7,)]
        )

    def test_a_successful_import_returns_true_exactly_and_logs_nothing(self):
        connection, writer = self._writer(next_bid_numbers=(7,))
        remapped = RawBidData(bid_row={"UID": "5", "JobName": "Imported"})
        with self.assertNoLogs("test", level="WARNING"):
            outcome = writer.import_ost_data(
                "target.mdb", RawBidData(bid_row={"UID": "1"}), self._transform_to(remapped)
            )
        self.assertIs(outcome, True)

    def test_write_failures_name_the_table_row_and_sorted_columns(self):
        connection, writer = self._writer()
        remapped = RawBidData(
            bid_row={"UID": "5"},
            bid_tables={
                "BidAreas": [
                    {"UID": "30", "Name": "A", "BidUID": "5"},
                    {"Sequence": "1", "UID": "30", "Name": "B"},
                ]
            },
        )
        with self.assertLogs("test", level="ERROR") as logs:
            with self.assertRaises(pyodbc.Error):
                writer._write_to_db(
                    _import_export_support__SqliteConnection(connection), remapped
                )
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed inserting into [BidAreas], row_uid=30, "
                "columns=['Name', 'Sequence', 'UID'], "
                "error=UNIQUE constraint failed: BidAreas.UID"
            ],
        )

    def test_write_failures_without_a_row_uid_log_an_empty_uid(self):
        connection, writer = self._writer()
        connection.execute("CREATE TABLE BidTakeoffs (UID INTEGER, Name TEXT NOT NULL)")
        remapped = RawBidData(
            bid_row={"UID": "5"}, page_tables={"BidTakeoffs": [{"Name": None}]}
        )
        with self.assertLogs("test", level="ERROR") as logs:
            with self.assertRaises(pyodbc.Error):
                writer._write_to_db(
                    _import_export_support__SqliteConnection(connection), remapped
                )
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed inserting into [BidTakeoffs], row_uid=, columns=['Name'], "
                "error=NOT NULL constraint failed: BidTakeoffs.Name"
            ],
        )

    def test_write_order_is_the_documented_dependency_order_for_every_table(self):
        bid_order = [
            "BidPlanRooms",
            "BidAreas",
            "BidTypAreas",
            "BidConditionFolders",
            "BidPageFolders",
            "BidEmployees",
            "BidLayers",
            "BidTypAreaCounts",
            "BidConditions",
            "UserMasterConditions",
            "BidConditionUser",
            "BidZones",
            "OCRProps",
            "BidPages",
            "BidSettings",
            "BidTypGroupViews",
            "BidNamedViews",
            "BidHotLinks",
        ]
        page_order = [
            "BidTakeoffs",
            "BidHighlights",
            "BidTexts",
            "BidDimensions",
            "BidArrows",
            "BidALines",
            "BidCallOuts",
            "BidAnnotationRects",
            "BidAnnotationOvals",
            "BidAnnotationPolygons",
            "BidAnnotationClouds",
            "BidAnnoInk",
            "BidLegends",
            "BidPageSettings",
            "BidAreaTranslations",
            "BidMarkedPages",
            "BidComments",
        ]
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        for table in (*bid_order, *page_order):
            connection.execute(f"CREATE TABLE [{table}] (UID INTEGER)")
        statements = []
        connection.set_trace_callback(statements.append)
        writer = _import_export_support__SqliteMdbWriter(connection)
        # Supplied in reverse so that only the production order can produce the
        # expected sequence; the first page section is empty on purpose.
        remapped = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={table: [{"UID": "1"}] for table in reversed(bid_order)},
            page_tables={
                **{table: [{"UID": "1"}] for table in reversed(page_order)},
                "BidTakeoffs": [],
            },
        )
        writer._write_to_db(
            _import_export_support__SqliteConnection(connection), remapped
        )
        inserted = [
            sql.split("[")[1].split("]")[0]
            for sql in statements
            if sql.startswith("INSERT INTO")
        ]
        self.assertEqual(
            inserted, ["Bids", *bid_order, *page_order[1:]]
        )

    def test_rows_for_tables_outside_the_write_order_are_not_written(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        connection.execute("CREATE TABLE Unlisted (UID INTEGER)")
        writer = _import_export_support__SqliteMdbWriter(connection)
        writer._write_to_db(
            _import_export_support__SqliteConnection(connection),
            RawBidData(
                bid_row={"UID": "1"},
                bid_tables={"Unlisted": [{"UID": "2"}]},
                page_tables={"Unlisted": [{"UID": "3"}]},
            ),
        )
        self.assertEqual(connection.execute("SELECT UID FROM Bids").fetchall(), [(1,)])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM Unlisted").fetchone()[0], 0)


class ImportOperationsUidFloorAndAllocationTests(unittest.TestCase):
    def _floor(self, connection):
        wrapped = _RecordingConnection(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        return writer._get_max_uid(wrapped), wrapped

    def test_floor_ignores_references_into_tables_the_import_never_writes(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER)")
        connection.execute("INSERT INTO Bids VALUES (1, 500)")
        connection.execute("CREATE TABLE BidNotes (UID INTEGER, BidUID INTEGER)")
        connection.execute("INSERT INTO BidNotes VALUES (10, 2)")
        floor, wrapped = self._floor(connection)
        self.assertEqual(floor, 2)
        reference_queries = [s for s in wrapped.statements if "MAX([" in s]
        self.assertEqual(reference_queries, ["SELECT MAX([BidUID]) FROM [BidNotes]"])
        wrapped.assert_every_cursor_closed(self)

    def test_floor_issues_no_reference_query_for_absent_tables_or_columns(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        connection.execute("INSERT INTO Bids VALUES (4)")
        connection.execute("CREATE TABLE BidAreas (UID INTEGER)")
        connection.execute("INSERT INTO BidAreas VALUES (6)")
        connection.execute("CREATE TABLE BidNotes (UID INTEGER)")
        floor, wrapped = self._floor(connection)
        self.assertEqual(floor, 6)
        self.assertEqual([s for s in wrapped.statements if "MAX([" in s], [])
        wrapped.assert_every_cursor_closed(self)

    def test_floor_queries_each_distinct_child_reference_exactly_once(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        connection.execute("CREATE TABLE BidNotes (UID INTEGER, BidUID INTEGER)")
        connection.execute("INSERT INTO BidNotes VALUES (1, 3)")
        connection.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        connection.execute("INSERT INTO BidAreas VALUES (2, 90)")
        relationships = [
            RawBidRelationship("BidNotes", "BidUID", "Bids", "UID"),
            RawBidRelationship("BidNotes", "BidUID", "Bids", "UID"),
            RawBidRelationship("BidAreas", "BidUID", "Bids", "UID"),
        ]
        with patch.object(import_operations_module, "BID_RELATIONSHIPS", relationships):
            floor, wrapped = self._floor(connection)
        self.assertEqual(floor, 90)
        self.assertEqual(
            [s for s in wrapped.statements if "MAX([" in s],
            [
                "SELECT MAX([BidUID]) FROM [BidNotes]",
                "SELECT MAX([BidUID]) FROM [BidAreas]",
            ],
        )

    def test_floor_does_not_swallow_a_non_numeric_uid(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        connection.execute("INSERT INTO Bids VALUES ('abc')")
        wrapped = _RecordingConnection(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with self.assertRaises(ValueError):
            writer._get_max_uid(wrapped)
        wrapped.assert_every_cursor_closed(self)

    def test_bid_number_assignment_uses_exact_sql_and_closes_its_cursor(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection, next_bid_numbers=(5,))
        wrapped = _RecordingConnection(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        remapped = RawBidData(bid_row={})
        writer._assign_next_bid_no(wrapped, remapped)
        self.assertEqual(remapped.bid_row, {"BidNo": "5"})
        self.assertEqual(
            wrapped.statements,
            ["SELECT [NextBidNo] FROM [Settings]", "UPDATE [Settings] SET [NextBidNo] = ?"],
        )
        wrapped.assert_every_cursor_closed(self)
        empty = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(empty, next_bid_numbers=())
        wrapped = _RecordingConnection(empty)
        _import_export_support__SqliteMdbWriter(empty)._assign_next_bid_no(
            wrapped, RawBidData(bid_row={})
        )
        self.assertEqual(
            wrapped.statements,
            [
                "SELECT [NextBidNo] FROM [Settings]",
                "INSERT INTO [Settings] ([NextBidNo]) VALUES (?)",
            ],
        )
        wrapped.assert_every_cursor_closed(self)

    def test_bid_number_assignment_closes_its_cursor_when_it_fails(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(
            connection, next_bid_numbers=(7, 12)
        )
        wrapped = _RecordingConnection(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with self.assertRaises(GlobalSettingsCardinalityError):
            writer._assign_next_bid_no(wrapped, RawBidData(bid_row={}))
        wrapped.assert_every_cursor_closed(self)

    def test_table_uid_allocation_closes_its_cursor_and_respects_references(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE PayClasses (UID INTEGER, Name TEXT)")
        connection.execute("INSERT INTO PayClasses VALUES (3, 'A')")
        connection.execute("CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER)")
        connection.execute("INSERT INTO Employees VALUES (1, 9)")
        wrapped = _RecordingConnection(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertEqual(writer._next_table_uid(wrapped, "PayClasses"), 10)
        wrapped.assert_every_cursor_closed(self)


class ImportOperationsMasterDataContractTests(unittest.TestCase):
    def _writer(self, statements=()):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        for statement in statements:
            connection.execute(statement)
        return connection, _import_export_support__SqliteMdbWriter(connection)

    def _resolvers(self):
        return {
            "CdnTypes": lambda w, c, raw: w._resolve_cdn_types(c, raw, 100)[0],
            "JobStatuses": lambda w, c, raw: w._resolve_job_statuses(c, raw, 100)[0],
            "AccessLevels": lambda w, c, raw: w._resolve_access_levels(c, raw),
            "PayClasses": lambda w, c, raw: w._resolve_pay_classes(c, raw),
            "Employees": lambda w, c, raw: w._resolve_employees(c, raw, {}, {}),
        }

    _ACCESS_LEVELS_WITH_DESCRIPTION = (
        "DROP TABLE AccessLevels",
        "CREATE TABLE AccessLevels (UID INTEGER PRIMARY KEY, Description TEXT)",
    )

    def test_incoming_duplicates_are_rejected_before_anything_is_inserted(self):
        cases = (
            (
                "CdnTypes",
                (),
                [
                    {"UID": "93", "Name": "Concrete"},
                    {"UID": "94", "Name": " concrete "},
                ],
                "CdnTypes.Name",
                "93, 94",
            ),
            (
                "JobStatuses",
                (),
                [{"UID": "7", "Name": "Open"}, {"UID": "8", "Name": "Open"}],
                "JobStatuses.Name",
                "7, 8",
            ),
            (
                "AccessLevels",
                self._ACCESS_LEVELS_WITH_DESCRIPTION,
                [
                    {"UID": "96", "Description": "Full"},
                    {"UID": "97", "Description": "Full"},
                ],
                "AccessLevels.Description",
                "96, 97",
            ),
            (
                "Employees",
                (),
                [
                    {"UID": "90", "EmployeeNo": "E1"},
                    {"UID": "91", "EmployeeNo": " e1 "},
                ],
                "Employees business key",
                "90, 91",
            ),
            (
                "Employees",
                (),
                [
                    {"UID": "90", "FirstName": "Ann", "LastName": "Lee"},
                    {"UID": "91", "FirstName": " ANN", "LastName": "lee "},
                ],
                "Employees business key",
                "90, 91",
            ),
        )
        for table, setup, rows, label, uids in cases:
            with self.subTest(table=table, label=label, uids=uids):
                connection, writer = self._writer(setup)
                raw_data = RawBidData(bid_row={"UID": "1"}, global_tables={table: rows})
                with self.assertRaises(RuntimeError) as caught:
                    self._resolvers()[table](
                        writer,
                        _import_export_support__SqliteConnection(connection),
                        raw_data,
                    )
                self.assertEqual(str(caught.exception), _ambiguity(label, uids))
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def test_nameless_condition_types_and_job_statuses_are_one_identity(self):
        for table in ("CdnTypes", "JobStatuses"):
            with self.subTest(table=table):
                connection, writer = self._writer()
                raw_data = RawBidData(
                    bid_row={"UID": "1"},
                    global_tables={table: [{"UID": "1"}, {"UID": "2"}]},
                )
                with self.assertRaises(RuntimeError) as caught:
                    self._resolvers()[table](
                        writer,
                        _import_export_support__SqliteConnection(connection),
                        raw_data,
                    )
                self.assertEqual(
                    str(caught.exception), _ambiguity(f"{table}.Name", "1, 2")
                )

    def test_empty_identities_never_collide_for_access_levels_and_employees(self):
        connection, writer = self._writer(self._ACCESS_LEVELS_WITH_DESCRIPTION)
        wrapped = _import_export_support__SqliteConnection(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "AccessLevels": [{"UID": "96"}, {"UID": "97", "Description": ""}],
                "Employees": [
                    {"UID": "90", "EmployeeNo": "", "FirstName": " "},
                    {"UID": "91"},
                ],
            },
        )
        self.assertEqual(
            writer._resolve_access_levels(wrapped, raw_data), {"96": "1", "97": "2"}
        )
        self.assertEqual(
            writer._resolve_employees(wrapped, raw_data, {}, {}),
            {"90": "1", "91": "2"},
        )
        self.assertEqual(
            connection.execute("SELECT UID FROM AccessLevels ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )
        self.assertEqual(
            connection.execute("SELECT UID FROM Employees ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )

    def test_no_incoming_rows_yield_empty_maps_for_access_levels_pay_classes_and_employees(self):
        connection, writer = self._writer()
        wrapped = _import_export_support__SqliteConnection(connection)
        empty = RawBidData(bid_row={"UID": "1"})
        self.assertEqual(writer._resolve_access_levels(wrapped, empty), {})
        self.assertEqual(writer._resolve_pay_classes(wrapped, empty), {})
        self.assertEqual(writer._resolve_employees(wrapped, empty, {}, {}), {})

    def test_rows_without_uid_or_name_are_not_mistaken_for_a_literal_xx(self):
        cases = (
            (
                "CdnTypes",
                ("INSERT INTO CdnTypes (UID, Name, ExpandState) VALUES (40, 'XX', 0)",),
                [
                    {"ExpandState": "0"},
                    {"UID": "2", "Name": "XX", "ExpandState": "0"},
                ],
                {"": "101", "2": "40"},
            ),
            (
                "JobStatuses",
                (
                    "INSERT INTO JobStatuses (UID, Name, Locked, Sequence) "
                    "VALUES (50, 'XX', 0, 1)",
                ),
                [
                    {"Locked": "0", "Sequence": "1"},
                    {"UID": "2", "Name": "XX", "Locked": "0", "Sequence": "1"},
                ],
                {"": "101", "2": "50"},
            ),
            (
                "AccessLevels",
                (
                    *self._ACCESS_LEVELS_WITH_DESCRIPTION,
                    "INSERT INTO AccessLevels (UID, Description) VALUES (15, 'XX')",
                ),
                [{}, {"UID": "2", "Description": "XX"}],
                {"": "16", "2": "15"},
            ),
            (
                "PayClasses",
                ("INSERT INTO PayClasses (UID, Name) VALUES (20, 'XX')",),
                [{}, {"UID": "2", "Name": "XX"}],
                {"": "21", "2": "20"},
            ),
            (
                "Employees",
                (
                    "INSERT INTO Employees (UID, EmployeeNo) VALUES (5, 'XX')",
                ),
                [{"FirstName": "Ann"}, {"UID": "2", "EmployeeNo": "XX"}],
                {"": "6", "2": "5"},
            ),
        )
        for table, setup, rows, expected in cases:
            with self.subTest(table=table):
                connection, writer = self._writer(setup)
                raw_data = RawBidData(bid_row={"UID": "1"}, global_tables={table: rows})
                result = self._resolvers()[table](
                    writer, _import_export_support__SqliteConnection(connection), raw_data
                )
                self.assertEqual(result, expected)

    def test_a_nameless_incoming_condition_type_reuses_a_nameless_existing_one(self):
        connection, writer = self._writer(
            ("INSERT INTO CdnTypes (UID, Name, ExpandState) VALUES (40, NULL, 0)",)
        )
        raw_data = RawBidData(
            bid_row={"UID": "1"}, global_tables={"CdnTypes": [{"UID": "9"}]}
        )
        result, max_uid = writer._resolve_cdn_types(
            _import_export_support__SqliteConnection(connection), raw_data, 100
        )
        self.assertEqual((result, max_uid), ({"9": "40"}, 100))

    def test_employee_references_to_unmapped_pay_classes_and_levels_become_null(self):
        connection, writer = self._writer(
            (
                "DROP TABLE Employees",
                "CREATE TABLE Employees (UID INTEGER, EmployeeNo TEXT, "
                "PayClassUID TEXT DEFAULT 'default-pay', "
                "AccessLevelUID TEXT DEFAULT 'default-level')",
            )
        )
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {
                        "UID": "1",
                        "EmployeeNo": "E1",
                        "PayClassUID": "70",
                        "AccessLevelUID": "80",
                    },
                    {
                        "UID": "2",
                        "EmployeeNo": "E2",
                        "PayClassUID": "71",
                        "AccessLevelUID": "81",
                    },
                    {"UID": "3", "EmployeeNo": "E3"},
                    {
                        "UID": "4",
                        "EmployeeNo": "E4",
                        "PayClassUID": "",
                        "AccessLevelUID": "",
                    },
                ]
            },
        )
        result = writer._resolve_employees(
            _import_export_support__SqliteConnection(connection),
            raw_data,
            {"70": "12"},
            {"81": "13"},
        )
        self.assertEqual(result, {"1": "1", "2": "2", "3": "3", "4": "4"})
        self.assertEqual(
            connection.execute(
                "SELECT UID, PayClassUID, AccessLevelUID FROM Employees ORDER BY UID"
            ).fetchall(),
            [
                (1, "12", None),
                (2, None, "13"),
                (3, "default-pay", "default-level"),
                (4, "", ""),
            ],
        )

    def test_employee_identity_keys_use_number_first_then_trimmed_lowercase_names(self):
        key = _import_export_support__SqliteMdbWriter(
            sqlite3.connect(":memory:")
        )._employee_identity_key
        for row, expected in (
            ({"EmployeeNo": " E1 "}, "no:e1"),
            ({"EmployeeNo": "E1", "FirstName": "Ann"}, "no:e1"),
            ({"FirstName": "Ann", "LastName": "Lee", "EMail": "A@X.com"}, "name:ann|lee|a@x.com"),
            ({"FirstName": " Ann "}, "name:ann||"),
            ({"LastName": "LEE"}, "name:|lee|"),
            ({"EMail": " a@x "}, "name:||a@x"),
            ({}, ""),
            ({"EmployeeNo": None, "FirstName": None, "LastName": None, "EMail": None}, ""),
            ({"EmployeeNo": " ", "FirstName": "", "LastName": "  ", "EMail": " "}, ""),
        ):
            with self.subTest(row=row):
                self.assertEqual(key(row), expected)

    def test_existing_employees_are_matched_on_email_and_duplicates_are_rejected(self):
        connection, writer = self._writer(
            (
                "DROP TABLE Employees",
                "CREATE TABLE Employees (UID INTEGER, EmployeeNo TEXT, FirstName TEXT, "
                "LastName TEXT, EMail TEXT)",
                "INSERT INTO Employees VALUES (3, NULL, 'Ann', 'Lee', 'ann@x.test')",
                "INSERT INTO Employees VALUES (4, NULL, 'Ann', 'Lee', 'other@x.test')",
            )
        )
        wrapped = _RecordingConnection(connection)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {"UID": "90", "FirstName": "ann", "LastName": "LEE", "EMail": "ANN@x.test"},
                    {"UID": "91", "FirstName": "Ann", "LastName": "Lee", "EMail": "new@x.test"},
                ]
            },
        )
        self.assertEqual(
            writer._resolve_employees(wrapped, raw_data, {}, {}),
            {"90": "3", "91": "5"},
        )
        wrapped.assert_every_cursor_closed(self)
        connection.execute("INSERT INTO Employees VALUES (3, 'E9', 'Dup', 'Row', NULL)")
        with self.assertRaisesRegex(
            RuntimeError,
            r"^Employees contains duplicate UID 3; "
            r"authoritative master-data UIDs must be unique[.]$",
        ):
            writer._load_existing_employee_uid_candidates_by_key(
                _import_export_support__SqliteConnection(connection)
            )

    def test_existing_master_loaders_return_empty_indexes_without_querying(self):
        connection, writer = self._writer()
        connection.execute("CREATE TABLE NoName (UID INTEGER)")
        connection.execute("CREATE TABLE NoUid (Name TEXT)")
        wrapped = _RecordingConnection(connection)
        load = writer._load_existing_uid_candidates_by_column
        self.assertEqual(load(wrapped, "Missing", "Name"), {})
        self.assertEqual(load(wrapped, "NoName", "Name"), {})
        self.assertEqual(load(wrapped, "NoUid", "Name"), {})
        connection.execute("DROP TABLE Employees")
        self.assertEqual(writer._load_existing_employee_uid_candidates_by_key(wrapped), {})
        connection.execute("CREATE TABLE Employees (EmployeeNo TEXT)")
        self.assertEqual(writer._load_existing_employee_uid_candidates_by_key(wrapped), {})
        self.assertEqual(wrapped.statements, [])

    def test_existing_master_loaders_close_their_cursors(self):
        connection, writer = self._writer(
            ("INSERT INTO PayClasses (UID, Name) VALUES (1, 'A')",)
        )
        wrapped = _RecordingConnection(connection)
        self.assertEqual(
            writer._load_existing_uid_candidates_by_column(wrapped, "PayClasses", "Name"),
            {"A": ["1"]},
        )
        wrapped.assert_every_cursor_closed(self)
        wrapped = _RecordingConnection(connection)
        writer._load_existing_employee_uid_candidates_by_key(wrapped)
        wrapped.assert_every_cursor_closed(self)


class ImportOperationsRowInsertContractTests(unittest.TestCase):
    def test_blank_autonumber_uids_are_omitted_from_the_insert_statement(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Sample (UID COUNTER, Name TEXT)")
        writer = _import_export_support__SqliteMdbWriter(connection)
        wrapped = _RecordingConnection(connection)
        table_info = writer._get_table_info(wrapped, "Sample")
        for blank_uid in ("", "0", "NULL", None):
            writer._insert_raw_row(
                wrapped, "Sample", {"UID": blank_uid, "Name": "n"}, table_info
            )
        writer._insert_raw_row(wrapped, "Sample", {"UID": "5", "Name": "n"}, table_info)
        self.assertEqual(
            wrapped.statements,
            ["INSERT INTO [Sample] ([Name]) VALUES (?)"] * 4
            + ["INSERT INTO [Sample] ([UID], [Name]) VALUES (?, ?)"],
        )
        wrapped.assert_every_cursor_closed(self)

    def test_a_failed_insert_still_closes_its_cursor_and_propagates(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE Sample (UID INTEGER PRIMARY KEY, Name TEXT)")
        connection.execute("INSERT INTO Sample VALUES (1, 'first')")
        writer = _import_export_support__SqliteMdbWriter(connection)
        wrapped = _RecordingConnection(connection)
        table_info = writer._get_table_info(wrapped, "Sample")
        wrapped.cursors.clear()
        with self.assertRaisesRegex(pyodbc.Error, "UNIQUE constraint failed: Sample.UID"):
            writer._insert_raw_row(
                wrapped, "Sample", {"UID": "1", "Name": "dup"}, table_info
            )
        wrapped.assert_every_cursor_closed(self)
        self.assertEqual(
            connection.execute("SELECT Name FROM Sample").fetchall(), [("first",)]
        )

    def test_table_metadata_lookups_close_cursors_and_default_missing_types(self):
        cursor = _ColumnsCursor(
            [
                SimpleNamespace(column_name="A", type_name="INTEGER"),
                SimpleNamespace(column_name="B", type_name=None),
            ]
        )
        writer = _import_export_support__SqliteMdbWriter(sqlite3.connect(":memory:"))
        wrapped = _ColumnsConnection(cursor)
        self.assertEqual(writer._get_table_columns(wrapped, "T"), {"A", "B"})
        self.assertIs(cursor.closed, True)
        cursor.closed = False
        self.assertEqual(writer._get_column_types(wrapped, "T"), {"A": "integer", "B": ""})
        self.assertIs(cursor.closed, True)
        self.assertEqual(cursor.requested, ["T", "T"])

    def test_table_metadata_lookup_errors_yield_empty_results_and_close_cursors(self):
        for method, expected in (
            ("_get_table_columns", set()),
            ("_get_column_types", {}),
        ):
            with self.subTest(method=method):
                cursor = _ColumnsCursor(error=pyodbc.Error("catalog unavailable"))
                writer = _import_export_support__SqliteMdbWriter(
                    sqlite3.connect(":memory:")
                )
                result = getattr(writer, method)(_ColumnsConnection(cursor), "T")
                self.assertEqual(result, expected)
                self.assertIs(cursor.closed, True)
