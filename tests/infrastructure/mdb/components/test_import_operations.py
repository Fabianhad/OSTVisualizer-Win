import logging
import sqlite3
import unittest
from collections import namedtuple
from contextlib import contextmanager
from types import SimpleNamespace
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
        uid_map, _max_uid = writer._resolve_cdn_types(
            _import_export_support__SqliteConnection(connection), raw_data, max_uid=100
        )
        self.assertEqual(uid_map, {"93": "40"})
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
