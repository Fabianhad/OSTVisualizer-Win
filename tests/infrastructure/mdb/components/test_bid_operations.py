import logging
import re
import sqlite3
import pyodbc
import unittest
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    CyclicBidOwnedReferenceError,
    DanglingBidOwnedReferenceError,
)
from ost_visualizer.infrastructure.database.settings_cardinality import (
    BidNumberAllocationUnavailableError,
)
from ost_visualizer.infrastructure.mdb.bid_settings_contract import (
    BidSettingsCardinalityError,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from contextlib import contextmanager
from ost_visualizer.infrastructure.mdb.components.constants import (
    LAYER_REFERENCE_TABLES,
    PAGE_DELETE_CHILD_TABLES,
)
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
import datetime
from ost_visualizer.infrastructure.mdb.components.serialization import encode_text_blob
from tests.helpers.mdb.real_write_contract import RealContractOps, contract_db


class BidOperationsPersistenceTests(unittest.TestCase):
    def test_delete_bid_removes_bid_scoped_children_without_direct_links(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageUID INTEGER REFERENCES BidPages(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidDimensions (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageUID INTEGER REFERENCES BidPages(UID),
                BidTakeoffFromUID INTEGER REFERENCES BidTakeoffs(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidAreas (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTypAreas (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidLaborCostCodes (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTimeCardStates (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTimeCards (
                UID INTEGER PRIMARY KEY,
                BidTimeCardStateUID INTEGER REFERENCES BidTimeCardStates(UID),
                BidEmployeeUID INTEGER,
                BidAreaUID INTEGER REFERENCES BidAreas(UID),
                BidTypicalAreaUID INTEGER REFERENCES BidTypAreas(UID),
                BidLaborCostCodeUID INTEGER REFERENCES BidLaborCostCodes(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidPercents (
                UID INTEGER PRIMARY KEY,
                BidTakeoffUID INTEGER REFERENCES BidTakeoffs(UID),
                BidLaborCostCodeUID INTEGER REFERENCES BidLaborCostCodes(UID),
                BidTimeCardStateUID INTEGER REFERENCES BidTimeCardStates(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTypAreaCounts (
                UID INTEGER PRIMARY KEY,
                BidAreaUID INTEGER REFERENCES BidAreas(UID),
                BidTypAreaUID INTEGER REFERENCES BidTypAreas(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidPageSettings (
                UID INTEGER PRIMARY KEY,
                BidPageUID INTEGER REFERENCES BidPages(UID),
                BidAreaUID INTEGER REFERENCES BidAreas(UID),
                BidTypAreaUID INTEGER REFERENCES BidTypAreas(UID)
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidAreas (UID, BidUID) VALUES (30, 1)")
        conn.execute("INSERT INTO BidTypAreas (UID, BidUID) VALUES (40, 1)")
        conn.execute("INSERT INTO BidLaborCostCodes (UID, BidUID) VALUES (50, 1)")
        conn.execute("INSERT INTO BidTimeCardStates (UID, BidUID) VALUES (60, 1)")
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, BidPageUID) VALUES (10, 1, NULL)"
        )
        conn.execute(
            "INSERT INTO BidDimensions "
            "(UID, BidUID, BidPageUID, BidTakeoffFromUID) VALUES (20, 1, NULL, 10)"
        )
        conn.execute(
            "INSERT INTO BidTimeCards "
            "(UID, BidTimeCardStateUID, BidEmployeeUID, BidAreaUID, "
            "BidTypicalAreaUID, BidLaborCostCodeUID) "
            "VALUES (70, 60, NULL, 30, 40, 50)"
        )
        conn.execute(
            "INSERT INTO BidPercents "
            "(UID, BidTakeoffUID, BidLaborCostCodeUID, BidTimeCardStateUID) "
            "VALUES (80, NULL, 50, 60)"
        )
        conn.execute(
            "INSERT INTO BidTypAreaCounts (UID, BidAreaUID, BidTypAreaUID) "
            "VALUES (90, 30, 40)"
        )
        conn.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidTypAreaUID) "
            "VALUES (100, NULL, 30, 40)"
        )
        # A sibling bid whose rows must survive the cascade.
        conn.execute("INSERT INTO Bids (UID) VALUES (2)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (11, 2)")
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, BidPageUID) VALUES (12, 2, 11)"
        )
        conn.execute("INSERT INTO BidAreas (UID, BidUID) VALUES (31, 2)")
        conn.execute(
            "INSERT INTO BidTimeCards "
            "(UID, BidTimeCardStateUID, BidEmployeeUID, BidAreaUID, "
            "BidTypicalAreaUID, BidLaborCostCodeUID) "
            "VALUES (71, NULL, NULL, 31, NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO BidPercents "
            "(UID, BidTakeoffUID, BidLaborCostCodeUID, BidTimeCardStateUID) "
            "VALUES (81, 12, NULL, NULL)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [(2,)])
        for table, survivors in (
            ("BidPages", [(11,)]),
            ("BidTakeoffs", [(12,)]),
            ("BidDimensions", []),
            ("BidTimeCards", [(71,)]),
            ("BidPercents", [(81,)]),
            ("BidTypAreaCounts", []),
            ("BidPageSettings", []),
            ("BidAreas", [(31,)]),
            ("BidTypAreas", []),
            ("BidLaborCostCodes", []),
            ("BidTimeCardStates", []),
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT UID FROM {table} ORDER BY UID").fetchall(),
                    survivors,
                )

    def test_delete_bid_removes_bid_settings_before_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.executemany("INSERT INTO Bids (UID) VALUES (?)", ((1,), (4,)))
        conn.executemany(
            "INSERT INTO BidSettings (UID, BidUID) VALUES (?, ?)", ((2, 1), (5, 4))
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute("SELECT UID, BidUID FROM BidSettings").fetchall(), [(5, 4)]
        )
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [(4,)])

    def test_delete_bid_removes_annotation_linked_only_by_to_takeoff(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDimensions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)"
        )
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.executemany("INSERT INTO BidTakeoffs VALUES (?, ?)", ((10, 1), (11, 2)))
        conn.executemany(
            "INSERT INTO BidDimensions VALUES (?, NULL, NULL, NULL, ?)",
            ((20, 10), (21, 11)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute("SELECT UID, BidTakeoffToUID FROM BidDimensions").fetchall(),
            [(21, 11)],
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidTakeoffs").fetchall(), [(11, 2)]
        )
        self.assertEqual(conn.execute("SELECT * FROM Bids").fetchall(), [(2,)])

    def test_delete_bid_clears_cross_bid_selected_page_before_page_delete(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageSelectedUID INTEGER REFERENCES BidPages(UID)
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO Bids (UID) VALUES (2)")
        conn.execute("INSERT INTO Bids (UID) VALUES (3)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (30, 3)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (20, 2, 10)"
        )
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (21, 3, 30)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT UID FROM BidPages").fetchall(), [(30,)])
        self.assertEqual(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 21"
            ).fetchone()[0],
            30,
        )
        self.assertEqual(
            conn.execute("SELECT BidUID FROM BidSettings WHERE UID = 20").fetchone()[0],
            2,
        )
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 20"
            ).fetchone()[0]
        )

    def test_create_bid_rejects_missing_project_owner_before_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (12)")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIsNone(
                _SqliteMdbOps(conn).create_bid(
                    "malformed.mdb", "99", {"job_name": "No owner"}
                )
            )
        self.assertIn("BidProjects has no row for UID 99", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0)
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 12
        )

    def test_create_bid_rejects_folder_references_outside_new_bid_before_insert(self):
        invalid_updates = (
            {
                "job_name": "Cross-bid folder parent",
                "new_folders": [
                    {"local_uid": "new-folder", "name": "Child", "parent_uid": "7"}
                ],
            },
            {
                "job_name": "Cross-bid page folder",
                "pages": [
                    {
                        "name": "Page",
                        "width": 42.0,
                        "height": 30.0,
                        "folder_uid": "7",
                    }
                ],
            },
        )
        for updates in invalid_updates:
            with self.subTest(job_name=updates["job_name"]):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
                conn.execute("INSERT INTO Settings VALUES (2)")
                conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
                conn.execute("INSERT INTO Bids VALUES (1, 'Existing')")
                conn.execute(
                    "CREATE TABLE BidPageFolders ("
                    "UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.execute(
                    "INSERT INTO BidPageFolders VALUES (7, 1, 'Existing', NULL)"
                )
                conn.execute(
                    "CREATE TABLE BidPages ("
                    "UID INTEGER, BidUID INTEGER, Name TEXT, Width REAL, "
                    "Height REAL, BidPageFolderUID INTEGER)"
                )
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIsNone(
                        _SqliteDuplicateOps(conn).create_bid(
                            "malformed.mdb", None, updates
                        )
                    )
                self.assertIs(
                    logs.records[0].exc_info[0], DanglingBidOwnedReferenceError
                )
                self.assertIn("unavailable page folder 7", logs.output[0])
                self.assertEqual(
                    conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 2
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM Bids ORDER BY UID").fetchall(),
                    [(1,)],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID FROM BidPageFolders ORDER BY UID"
                    ).fetchall(),
                    [(7,)],
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidPages").fetchall(), []
                )

    def test_create_bid_rejects_missing_optional_master_references_before_allocation(
        self,
    ):
        for field, value in (("job_status_uid", "8"), ("estimator_uid", "9")):
            with self.subTest(field=field):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
                conn.execute("INSERT INTO Settings VALUES (12)")
                conn.execute(
                    "CREATE TABLE Bids ("
                    "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)"
                )
                conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
                conn.execute("CREATE TABLE Employees (UID INTEGER)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                updates = {"job_name": "Invalid master", field: value}
                if field == "estimator_uid":
                    conn.execute("INSERT INTO JobStatuses VALUES (8)")
                    updates["job_status_uid"] = "8"
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIsNone(
                        _SqliteDuplicateOps(conn).create_bid(
                            "malformed.mdb", None, updates
                        )
                    )
                expected_table = (
                    "JobStatuses" if field == "job_status_uid" else "Employees"
                )
                self.assertIn(
                    f"{expected_table} has no row for UID {value}", logs.output[0]
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
                )
                self.assertEqual(
                    conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 12
                )

    def test_create_bid_accepts_forward_new_folder_reference_after_drag_reorder(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        result = _SqliteDuplicateOps(conn).create_bid(
            "new.mdb",
            None,
            {
                "job_name": "Forward folders",
                "new_folders": [
                    {
                        "local_uid": "child",
                        "name": "Child",
                        "parent_uid": "parent",
                    },
                    {
                        "local_uid": "parent",
                        "name": "Parent",
                        "parent_uid": None,
                    },
                ],
            },
        )
        self.assertEqual(result, "1")
        rows = conn.execute(
            "SELECT child.Name, parent.Name "
            "FROM BidPageFolders AS child "
            "JOIN BidPageFolders AS parent ON parent.UID=child.ParentUID"
        ).fetchall()
        self.assertEqual(rows, [("Child", "Parent")])
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name, ParentUID FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(1, 1, "Parent", None), (2, 1, "Child", 1)],
        )
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 3
        )

    def test_create_bid_rejects_nested_folders_when_schema_is_flat(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)"
        )
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).create_bid(
                "legacy.mdb",
                None,
                {
                    "job_name": "Nested folders",
                    "new_folders": [
                        {
                            "local_uid": "parent",
                            "name": "Parent",
                            "parent_uid": None,
                        },
                        {
                            "local_uid": "child",
                            "name": "Child",
                            "parent_uid": "parent",
                        },
                    ],
                },
            )
        self.assertIn("page-folder hierarchy persistence", logs.output[0])
        self.assertIsNone(result)
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [])
        self.assertEqual(conn.execute("SELECT UID FROM BidPageFolders").fetchall(), [])
        self.assertEqual(
            _SqliteDuplicateOps(conn).create_bid(
                "legacy.mdb",
                None,
                {
                    "job_name": "Flat folders",
                    "new_folders": [
                        {
                            "local_uid": "root",
                            "name": "Root",
                            "parent_uid": None,
                        }
                    ],
                },
            ),
            "1",
        )
        self.assertEqual(
            conn.execute("SELECT BidUID, Name FROM BidPageFolders").fetchall(),
            [(1, "Root")],
        )

    def test_create_bid_rejects_folders_when_legacy_table_is_unavailable(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).create_bid(
                "legacy.mdb",
                None,
                {
                    "job_name": "Folder bid",
                    "new_folders": [
                        {
                            "local_uid": "folder",
                            "name": "Folder",
                            "parent_uid": None,
                        }
                    ],
                },
            )
        self.assertIn("does not support page-folder persistence", logs.output[0])
        self.assertIsNone(result)
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [])
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 2
        )

    def test_duplicate_bid_rejects_dangling_optional_master_references(self):
        for column, value, expected_table in (
            ("JobStatusUID", 8, "JobStatuses"),
            ("EstimatorUID", 9, "Employees"),
            ("PrManagerUID", 10, "Employees"),
            ("JobSiteManagerUID", 11, "Employees"),
        ):
            with self.subTest(column=column):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
                conn.execute("INSERT INTO Settings VALUES (12)")
                conn.execute(
                    "CREATE TABLE Bids ("
                    "UID INTEGER, BidNo INTEGER, GUID TEXT, "
                    "JobStatusUID INTEGER, EstimatorUID INTEGER, "
                    "PrManagerUID INTEGER, JobSiteManagerUID INTEGER)"
                )
                values = {
                    "JobStatusUID": None,
                    "EstimatorUID": None,
                    "PrManagerUID": None,
                    "JobSiteManagerUID": None,
                }
                values[column] = value
                conn.execute(
                    "INSERT INTO Bids VALUES (7, 11, 'source', ?, ?, ?, ?)",
                    (
                        values["JobStatusUID"],
                        values["EstimatorUID"],
                        values["PrManagerUID"],
                        values["JobSiteManagerUID"],
                    ),
                )
                conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
                conn.execute("CREATE TABLE Employees (UID INTEGER)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIsNone(
                        _SqliteDuplicateOps(conn).duplicate_bid("malformed.mdb", "7")
                    )
                self.assertIn(
                    f"{expected_table} has no row for UID {value}", logs.output[0]
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 1
                )
                self.assertEqual(
                    conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 12
                )

    def test_bid_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (7)", ((), ()))
        conn.execute("INSERT INTO BidPages VALUES (70, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(_SqliteMdbOps(conn).delete_bids("malformed.mdb", ["7"]))
        self.assertIn("Bids contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 1)

    def test_duplicate_bid_rejects_duplicate_source_uid_before_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.executemany(
            "INSERT INTO Bids VALUES (7, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIsNone(_SqliteMdbOps(conn).duplicate_bid("malformed.mdb", "7"))
        self.assertIn("Bids contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 2)

    def test_duplicate_bid_rejects_dangling_hotlink_before_uid_collision_retargets_it(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (20, 1)")
        conn.execute(
            "CREATE TABLE BidNamedViews "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (5, 1, 20)")
        conn.execute(
            "CREATE TABLE BidHotLinks "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, BidPageViewUID INTEGER)"
        )
        conn.execute("INSERT INTO BidHotLinks VALUES (40, 1, 20, 6)")
        with self.assertLogs("test", level="ERROR") as logs:
            duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid(
                "malformed.mdb", "1"
            )
        self.assertIsNone(duplicate_uid)
        self.assertIn(
            "BidHotLinks.UID=40 references missing BidNamedViews.UID=6",
            logs.output[0],
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 1)

    def test_duplicate_bid_resets_dangling_derived_totals(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (149805, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (143661, 149805)")
        for table in (
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
        ):
            conn.execute(
                f"CREATE TABLE [{table}] "
                "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
            )
        conn.execute("INSERT INTO BidTakeoffTotals VALUES (9669, 149805, 143662)")
        conn.execute("INSERT INTO BidTakeoffTotals VALUES (8669, 149805, 143661)")
        conn.execute("INSERT INTO BidLaborCostCodeTotals VALUES (9670, 149805, 143662)")
        conn.execute("INSERT INTO BidLaborCostCodeTotals VALUES (8670, 149805, 143661)")
        conn.execute("INSERT INTO BidTypicalGroupTotals VALUES (9671, 149805, 143662)")
        conn.execute("INSERT INTO BidTypicalGroupTotals VALUES (8671, 149805, 143661)")
        duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid(
            "malformed.mdb", "149805"
        )
        self.assertIsNotNone(duplicate_uid)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 2)
        duplicate_page_uid = conn.execute(
            "SELECT UID FROM BidPages WHERE BidUID=?", (int(duplicate_uid),)
        ).fetchone()[0]
        for table in (
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(
                        f"SELECT BidPageUID FROM [{table}] WHERE BidUID=?",
                        (int(duplicate_uid),),
                    ).fetchall(),
                    [(duplicate_page_uid,)],
                )
                self.assertEqual(
                    conn.execute(
                        f"SELECT COUNT(*) FROM [{table}] WHERE BidUID=149805"
                    ).fetchone()[0],
                    2,
                )

    def test_duplicate_bid_remaps_large_condition_layer_graph_without_row_updates(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, 1)",
            ((uid,) for uid in range(1, 101)),
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, 1, ?)",
            ((1000 + uid, uid) for uid in range(1, 101)),
        )
        statements = []
        conn.set_trace_callback(statements.append)
        duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid("large.mdb", "1")
        condition_remap_updates = [
            sql
            for sql in statements
            if sql.lstrip().upper().startswith("UPDATE [BIDCONDITIONS]")
        ]
        self.assertEqual(duplicate_uid, "2")
        self.assertEqual(condition_remap_updates, [])
        copied_links = conn.execute(
            "SELECT COUNT(*) FROM BidConditions AS condition "
            "JOIN BidLayers AS layer ON layer.UID=condition.BidLayerUID "
            "WHERE condition.BidUID=2 AND layer.BidUID=2"
        ).fetchone()[0]
        self.assertEqual(copied_links, 100)

    def test_duplicate_bid_reuses_one_schema_inspector(self):
        class CountingSchemaOps(_SqliteDuplicateOps):
            def __init__(self, connection):
                super().__init__(connection)
                self.schema_calls = 0

            def _schema(self, connection):
                self.schema_calls += 1
                return super()._schema(connection)

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        ops = CountingSchemaOps(conn)
        self.assertEqual(ops.duplicate_bid("large.mdb", "1"), "2")
        self.assertEqual(ops.schema_calls, 1)

    def test_duplicate_bid_copies_indirect_area_counts_without_quadratic_remap(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTypAreaCounts ("
            "UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID INTEGER, Amount REAL)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1)",
            ((uid,) for uid in range(1, 31)),
        )
        conn.executemany(
            "INSERT INTO BidTypAreas VALUES (?, 1)",
            ((100 + uid,) for uid in range(1, 31)),
        )
        conn.executemany(
            "INSERT INTO BidTypAreaCounts VALUES (?, ?, ?, ?)",
            ((200 + uid, uid, 100 + uid, float(uid)) for uid in range(1, 31)),
        )
        statements = []
        conn.set_trace_callback(statements.append)
        duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid("large.mdb", "1")
        count_selects = [
            sql
            for sql in statements
            if "FROM [BIDTYPAREACOUNTS]" in sql.upper()
            and sql.lstrip().upper().startswith("SELECT")
        ]
        count_updates = [
            sql
            for sql in statements
            if sql.lstrip().upper().startswith("UPDATE [BIDTYPAREACOUNTS]")
        ]
        self.assertEqual(duplicate_uid, "2")
        self.assertLessEqual(len(count_selects), 7)
        self.assertEqual(count_updates, [])
        copied_links = conn.execute(
            "SELECT COUNT(*) FROM BidTypAreaCounts AS count_row "
            "JOIN BidAreas AS area ON area.UID=count_row.BidAreaUID "
            "JOIN BidTypAreas AS typical ON typical.UID=count_row.BidTypAreaUID "
            "WHERE area.BidUID=2 AND typical.BidUID=2"
        ).fetchone()[0]
        self.assertEqual(copied_links, 30)

    def test_duplicate_bid_still_rejects_takeoff_with_missing_required_page(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (30, 1)")
        conn.execute(
            "CREATE TABLE BidTakeoffs "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER)"
        )
        conn.execute("INSERT INTO BidTakeoffs VALUES (40, 1, 20, 30)")
        with self.assertLogs("test", level="ERROR") as logs:
            duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid(
                "malformed.mdb", "1"
            )
        self.assertIsNone(duplicate_uid)
        self.assertIn(
            "BidTakeoffs.UID=40 references missing BidPages.UID=20",
            logs.output[0],
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 1)
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 2
        )

    def test_duplicate_bid_does_not_claim_orphan_bid_owned_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidNotes (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidNotes VALUES (10, 2)")
        duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid("malformed.mdb", "1")
        self.assertEqual(duplicate_uid, "3")
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidNotes AS note "
                "INNER JOIN Bids AS bid ON note.BidUID=bid.UID"
            ).fetchone()[0],
            0,
        )

    def test_duplicate_bid_page_does_not_claim_orphan_page_companion(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (20, 1)")
        conn.execute("CREATE TABLE BidMarkedPages (UID INTEGER, BidPageUID INTEGER)")
        conn.execute("INSERT INTO BidMarkedPages VALUES (1, 21)")
        duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid("malformed.mdb", "1")
        self.assertEqual(duplicate_uid, "2")
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPages WHERE BidUID=2").fetchone()[0],
            22,
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidMarkedPages AS marked "
                "INNER JOIN BidPages AS page ON marked.BidPageUID=page.UID "
                "WHERE marked.UID=1"
            ).fetchone()[0],
            0,
        )

    def test_duplicate_bid_relationship_preflight_rejects_cross_bid_target(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidNamedViews "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (5, 2, 20)")
        conn.execute(
            "CREATE TABLE BidHotLinks "
            "(UID INTEGER, BidUID INTEGER, BidPageViewUID INTEGER)"
        )
        conn.execute("INSERT INTO BidHotLinks VALUES (40, 1, 5)")
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            "BidHotLinks.UID=40 references missing BidNamedViews.UID=5",
        ):
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            )

    def test_duplicate_bid_relationship_preflight_rejects_cross_bid_layer(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidLayers VALUES (5, 2)")
        conn.execute(
            "CREATE TABLE BidConditions "
            "(UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (40, 1, 5)")
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            "BidConditions.UID=40 references missing BidLayers.UID=5",
        ):
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            )

    def test_duplicate_bid_relationship_preflight_accepts_null_optional_layer(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions "
            "(UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (40, 1, NULL)")
        ops = _SqliteDuplicateOps(conn)
        self.assertEqual(
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            ),
            {},
        )

    def test_duplicate_bid_relationship_preflight_rejects_takeoff_parent_cycle(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs "
            "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?)",
            ((7, 8), (8, 7)),
        )
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(
            CyclicBidOwnedReferenceError,
            "BidTakeoffs.UID=7 participates in a ParentUID cycle",
        ):
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            )

    def test_duplicate_bid_relationship_preflight_accepts_valid_parent_chain(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs "
            "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?)",
            ((7, None), (8, 7), (9, 8)),
        )
        ops = _SqliteDuplicateOps(conn)
        self.assertEqual(
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            ),
            {},
        )

    def test_duplicate_bid_relationship_preflight_accepts_valid_area_chain(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidAreas " "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?)",
            ((7, None), (8, 7), (9, 8)),
        )
        ops = _SqliteDuplicateOps(conn)
        self.assertEqual(
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            ),
            {},
        )

    def test_duplicate_bid_relationship_preflight_rejects_hierarchy_parent_cycles(self):
        for table in ("BidAreas", "BidConditionFolders", "BidPageFolders"):
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    f"CREATE TABLE {table} "
                    "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
                )
                conn.executemany(
                    f"INSERT INTO {table} VALUES (?, 1, ?)",
                    ((7, 8), (8, 7)),
                )
                ops = _SqliteDuplicateOps(conn)
                with self.assertRaisesRegex(
                    CyclicBidOwnedReferenceError,
                    rf"{table}.UID=7 participates in a ParentUID cycle",
                ):
                    ops._require_duplicable_bid_relationships(
                        _SqliteCursorWrapper(conn), ops._schema_ref, 1
                    )

    def test_duplicate_bid_preflight_rejects_indirect_area_count_target(self):
        for typical_area_rows in ((), ((21, 2),)):
            with self.subTest(typical_area_rows=typical_area_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidTypAreaCounts ("
                    "UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID INTEGER)"
                )
                conn.execute("INSERT INTO BidAreas VALUES (10, 1)")
                conn.execute("INSERT INTO BidTypAreas VALUES (20, 1)")
                conn.executemany(
                    "INSERT INTO BidTypAreas VALUES (?, ?)", typical_area_rows
                )
                conn.execute("INSERT INTO BidTypAreaCounts VALUES (30, 10, 21)")
                ops = _SqliteDuplicateOps(conn)
                with self.assertRaisesRegex(
                    DanglingBidOwnedReferenceError,
                    "BidTypAreaCounts.UID=30 references missing " "BidTypAreas.UID=21",
                ):
                    ops._require_duplicable_bid_relationships(
                        _SqliteCursorWrapper(conn), ops._schema_ref, 1
                    )

    def test_duplicate_bid_preflight_rejects_indirect_page_child_target(self):
        for area_rows in ((), ((21, 2),)):
            with self.subTest(area_rows=area_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidPageSettings ("
                    "UID INTEGER, BidPageUID INTEGER, BidAreaUID INTEGER)"
                )
                conn.execute("INSERT INTO BidPages VALUES (10, 1)")
                conn.execute("INSERT INTO BidAreas VALUES (20, 1)")
                conn.executemany("INSERT INTO BidAreas VALUES (?, ?)", area_rows)
                conn.execute("INSERT INTO BidPageSettings VALUES (30, 10, 21)")
                ops = _SqliteDuplicateOps(conn)
                with self.assertRaisesRegex(
                    DanglingBidOwnedReferenceError,
                    "BidPageSettings.UID=30 references missing BidAreas.UID=21",
                ):
                    ops._require_duplicable_bid_relationships(
                        _SqliteCursorWrapper(conn), ops._schema_ref, 1
                    )

    def test_duplicate_row_copy_rejects_duplicate_source_uid_before_inserting(self):
        class DuplicateOps(_SqliteMdbOps):
            @staticmethod
            def _execute_insert_values(
                cursor,
                _schema,
                table,
                values,
                _required_columns,
                _operation,
            ):
                columns = list(values)
                cursor.execute(
                    f"INSERT INTO [{table}] "
                    f"({', '.join(f'[{column}]' for column in columns)}) "
                    f"VALUES ({', '.join('?' for _column in columns)})",
                    *[values[column] for column in columns],
                )

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO BidLayers VALUES (7, 1, ?)",
            (("First",), ("Conflicting",)),
        )
        ops = DuplicateOps(conn)
        with self.assertRaisesRegex(
            RuntimeError,
            "BidLayers contains duplicate UID 7",
        ):
            ops._copy_bid_table_rows(
                _SqliteCursorWrapper(conn), "BidLayers", "BidUID", "1", "2"
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers").fetchone()[0], 2
        )

    def test_duplicate_uid_map_copy_rejects_duplicate_source_uid_before_inserting(self):
        class DuplicateOps(_SqliteMdbOps):
            @staticmethod
            def _execute_insert_values(
                cursor,
                _schema,
                table,
                values,
                _required_columns,
                _operation,
            ):
                columns = list(values)
                cursor.execute(
                    f"INSERT INTO [{table}] "
                    f"({', '.join(f'[{column}]' for column in columns)}) "
                    f"VALUES ({', '.join('?' for _column in columns)})",
                    *[values[column] for column in columns],
                )

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO BidLayers VALUES (7, 1, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidLayers contains duplicate UID 7",
        ):
            DuplicateOps(conn)._copy_with_uid_map(
                _SqliteCursorWrapper(conn), "BidLayers", "BidUID", "1", "2"
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers").fetchone()[0], 2
        )

    def test_new_bid_batches_page_and_legend_identity_scans(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (1)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, Width REAL, Height REAL)"
        )
        conn.execute(
            "CREATE TABLE BidLegends ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        statements = []
        conn.set_trace_callback(statements.append)
        result = _SqliteDuplicateOps(conn).create_bid(
            "large.mdb",
            None,
            {
                "job_name": "Large Bid",
                "pages": [
                    {"name": f"Page {index}", "width": 42.0, "height": 30.0}
                    for index in range(100)
                ],
            },
        )
        max_uid_queries = [
            sql for sql in statements if sql.lstrip().upper().startswith("SELECT MAX")
        ]
        self.assertEqual(result, "1")
        self.assertEqual(len(max_uid_queries), 6)
        self.assertEqual(
            conn.execute("SELECT UID, BidUID FROM BidPages ORDER BY UID").fetchall(),
            [(uid, 1) for uid in range(1, 101)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidPageUID FROM BidLegends ORDER BY UID"
            ).fetchall(),
            [(uid, 1, uid) for uid in range(1, 101)],
        )

    def test_delete_bids_handles_empty_and_invalid_requests(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        ops = _SqliteMdbOps(conn)
        self.assertTrue(ops.delete_bids("bid.mdb", []))
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertFalse(ops.delete_bids("bid.mdb", ["1", "bad"]))
            self.assertFalse(ops.delete_bids("bid.mdb", "12"))
        self.assertEqual(len(logs.records), 2)
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [(1,)])

    def test_create_bid_persists_defaults_layers_pages_legends_and_advances_number(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Settings (NextBidNo INTEGER, ScaleStyle INTEGER, "
            "ScaleFactor1 REAL, ScaleFactor2 REAL, PageWidth REAL, PageHeight REAL, "
            "MeasureBase INTEGER, TakeoffIncrements REAL)"
        )
        conn.execute("INSERT INTO Settings VALUES (5, 2, 0.25, 12, 36, 24, 1, 0.5)")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute("INSERT INTO BidProjects VALUES (3, 'Project')")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, GUID TEXT, "
            "BidNo INTEGER, JobName TEXT, Notes BLOB, MeasureBase INTEGER, "
            "TakeoffIncrements REAL, ScaleStyle INTEGER, ScaleFactor1 REAL, "
            "PageWidth REAL, PageHeight REAL, CoverSheetSelItemUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Show INTEGER, IsLocked INTEGER, Sequence INTEGER, IsTemplate INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (1, None, "Default", -1, 0, 0, 1),
                (2, None, "Comments", 0, -1, None, 1),
                (3, None, "Plain layer", -1, 0, 1, 0),
            ),
        )
        conn.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Width REAL, Height REAL, ScaleFactor1 REAL, Sequence INTEGER, "
            "Index1 INTEGER, GUID TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidLegends (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, "
            "BidPageSelectedUID INTEGER)"
        )
        new_uid = _SqliteDuplicateOps(conn).create_bid(
            "new.mdb",
            "3",
            {
                "job_name": "New bid",
                "notes": "hello",
                "pages": [
                    {"name": "A", "width": 42.0, "height": 30.0},
                    {
                        "name": "B",
                        "width": 36.0,
                        "height": 24.0,
                        "scale_factor1": 0.5,
                    },
                    {"name": "Unsized", "width": None, "height": None},
                ],
            },
        )
        self.assertEqual(new_uid, "1")
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidProjectUID, BidNo, JobName, Notes, MeasureBase, "
                "TakeoffIncrements, ScaleStyle, ScaleFactor1, PageWidth, PageHeight, "
                "CoverSheetSelItemUID FROM Bids"
            ).fetchall(),
            [(1, 3, 5, "New bid", b"hello", 1, 0.5, 2, 0.25, 36.0, 24.0, 1)],
        )
        self.assertRegex(
            conn.execute("SELECT GUID FROM Bids").fetchone()[0],
            r"^\{[0-9A-F-]{36}\}$",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name, Show, IsLocked, Sequence, IsTemplate "
                "FROM BidLayers WHERE BidUID=1 ORDER BY UID"
            ).fetchall(),
            [(4, 1, "Default", -1, 0, 0, 0), (5, 1, "Comments", 0, -1, 1, 0)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name, Width, Height, ScaleFactor1, Sequence, "
                "Index1 FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(1, 1, "A", 42.0, 30.0, 0.25, 1, 1), (2, 1, "B", 36.0, 24.0, 0.5, 2, 1)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidPageUID FROM BidLegends ORDER BY UID"
            ).fetchall(),
            [(1, 1, 1), (2, 1, 2)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidPageSelectedUID FROM BidSettings"
            ).fetchall(),
            [(1, 1, 1)],
        )
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 6
        )

    def test_duplicate_bid_copies_owned_rows_with_fresh_identities_and_remapped_links(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (7)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, GUID TEXT, JobName TEXT, "
            "CopyFromBidNO INTEGER, CoverSheetSelItemType INTEGER, "
            "CoverSheetSelItemUID INTEGER, CopyTimeStamp TEXT, CreateDateTime TEXT)"
        )
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, 'old')",
            (
                (1, 3, "{SOURCE}", "Source", 1, 20),
                (2, 4, "{OTHER}", "Other", 1, 22),
            ),
        )
        conn.execute(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, ?, ?, ?)",
            ((5, 1, "Source layer", "{LAYER}"), (6, 2, "Other layer", "{OTHER-LAYER}")),
        )
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "BidLayerUID INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?, ?, ?)",
            ((30, 1, "Wall", 5, "{COND}"), (31, 2, "Other wall", 6, "{OTHER-COND}")),
        )
        conn.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?, ?)",
            ((20, 1, "Source page", "{PAGE}"), (22, 2, "Other page", "{OTHER-PAGE}")),
        )
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, ?, ?, ?, ?)",
            ((40, 1, 20, 30, None), (41, 1, 20, 30, 40), (42, 2, 22, 31, None)),
        )
        conn.execute("CREATE TABLE BidMarkedPages (UID INTEGER, BidPageUID INTEGER)")
        conn.executemany(
            "INSERT INTO BidMarkedPages VALUES (?, ?)", ((50, 20), (51, 22))
        )
        new_uid = _SqliteDuplicateOps(conn).duplicate_bid("bid.mdb", "1")
        self.assertEqual(new_uid, "3")
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 8
        )
        new_bid = conn.execute(
            "SELECT BidNo, GUID, JobName, CopyFromBidNO, CoverSheetSelItemType, "
            "CopyTimeStamp, CreateDateTime FROM Bids WHERE UID=3"
        ).fetchone()
        self.assertEqual(
            (new_bid[0], new_bid[2], new_bid[3], new_bid[4]), (7, "Source", 3, 1)
        )
        self.assertIsNotNone(new_bid[5])
        self.assertNotEqual(new_bid[6], "old")
        self.assertRegex(new_bid[1], r"^\{[0-9A-F-]{36}\}$")
        new_layer = conn.execute(
            "SELECT UID, Name, GUID FROM BidLayers WHERE BidUID=3"
        ).fetchall()
        new_condition = conn.execute(
            "SELECT UID, Name, BidLayerUID, GUID FROM BidConditions WHERE BidUID=3"
        ).fetchall()
        new_page = conn.execute(
            "SELECT UID, Name, GUID FROM BidPages WHERE BidUID=3"
        ).fetchall()
        self.assertEqual([row[1] for row in new_layer], ["Source layer"])
        self.assertEqual([row[1] for row in new_condition], ["Wall"])
        self.assertEqual([row[1] for row in new_page], ["Source page"])
        self.assertNotIn(new_layer[0][0], (5, 6))
        self.assertEqual(new_condition[0][2], new_layer[0][0])
        for source_guid, copied_guid in (
            ("{LAYER}", new_layer[0][2]),
            ("{COND}", new_condition[0][3]),
            ("{PAGE}", new_page[0][2]),
        ):
            self.assertNotEqual(copied_guid, source_guid)
            self.assertRegex(copied_guid, r"^\{[0-9A-F-]{36}\}$")
        copied_takeoffs = conn.execute(
            "SELECT UID, BidPageUID, BidConditionUID, ParentUID FROM BidTakeoffs "
            "WHERE BidUID=3 ORDER BY UID"
        ).fetchall()
        self.assertEqual(len(copied_takeoffs), 2)
        (root_uid, root_page, root_condition, root_parent), (
            child_uid,
            child_page,
            child_condition,
            child_parent,
        ) = copied_takeoffs
        self.assertEqual((root_page, child_page), (new_page[0][0],) * 2)
        self.assertEqual((root_condition, child_condition), (new_condition[0][0],) * 2)
        self.assertIn(root_parent, (None, 0))
        self.assertEqual(child_parent, root_uid)
        self.assertEqual(
            conn.execute(
                "SELECT BidPageUID FROM BidMarkedPages WHERE UID NOT IN (50, 51)"
            ).fetchall(),
            [(new_page[0][0],)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT CoverSheetSelItemUID FROM Bids WHERE UID=3"
            ).fetchone()[0],
            new_page[0][0],
        )
        for table, source_rows in (
            ("BidLayers", [(5, 1), (6, 2)]),
            ("BidConditions", [(30, 1), (31, 2)]),
            ("BidPages", [(20, 1), (22, 2)]),
            ("BidTakeoffs", [(40, 1), (41, 1), (42, 2)]),
        ):
            with self.subTest(source_table=table):
                self.assertEqual(
                    conn.execute(
                        f"SELECT UID, BidUID FROM {table} "
                        "WHERE BidUID IN (1, 2) ORDER BY UID"
                    ).fetchall(),
                    source_rows,
                )
        self.assertEqual(
            conn.execute(
                "SELECT BidLayerUID FROM BidConditions WHERE UID=30"
            ).fetchone()[0],
            5,
        )
        self.assertEqual(
            conn.execute("SELECT ParentUID FROM BidTakeoffs WHERE UID=41").fetchone()[
                0
            ],
            40,
        )

    def test_duplicate_bid_returns_none_for_unknown_source_without_writing(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (4)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        self.assertIsNone(_SqliteDuplicateOps(conn).duplicate_bid("bid.mdb", "99"))
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [(1,)])
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 4
        )


class BidOperationsCascadeAndDefaultsTests(unittest.TestCase):
    class StrictOps(_SqliteDuplicateOps):
        logger = logging.getLogger("bid-ops-guard")

        def _require_write_columns(self, schema, table, columns):
            for column in columns:
                schema.require_column(table, column)

    def failure_exception(self, call):
        with self.assertLogs("bid-ops-guard", level="ERROR") as logs:
            self.assertIn(call(), (False, None))
        return logs.records[0].exc_info[1]

    @staticmethod
    def cascade_tables():
        from ost_visualizer.infrastructure.mdb.components import (
            bid_operations as module,
        )

        generic = {
            table
            for table in (
                *module._PAGE_SCOPED,
                *module._BID_SCOPED_PRE,
                *module._BID_SCOPED_POST,
            )
            if table
            not in {
                "BidPages",
                "BidSettings",
                "BidPercents",
                "BidTakeoffs",
                "BidTimeCards",
                "BidTypAreaCounts",
                "BidPageSettings",
                "BidLaborCostCodes",
                "BidTimeCardStates",
                "BidEmployees",
                "BidAreas",
                "BidTypAreas",
                "BidConditions",
            }
        }
        return module, sorted(generic)

    def build_cascade(self, page_scoped_columns):
        module, tables = self.cascade_tables()
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.executemany("INSERT INTO BidPages VALUES (?, ?)", ((11, 1), (21, 2)))
        for table in tables:
            page_scoped = table in module._PAGE_SCOPED
            columns = page_scoped_columns if page_scoped else "BidUID INTEGER"
            conn.execute(f"CREATE TABLE [{table}] (UID INTEGER, {columns})")
            if "BidPageUID" in columns:
                rows = ((1, 11), (2, 21))
            else:
                rows = ((1, 1), (2, 2))
            conn.executemany(f"INSERT INTO [{table}] VALUES (?, ?)", rows)
        return conn, tables

    def test_duplicating_a_bid_copies_its_hot_links_onto_the_copied_pages_and_views(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Settings (NextBidNo INTEGER); INSERT INTO Settings VALUES (7);
            CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, GUID TEXT, JobName TEXT);
            INSERT INTO Bids VALUES (1, 3, '{A}', 'Source'), (2, 4, '{B}', 'Other');
            CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, GUID TEXT);
            INSERT INTO BidPages VALUES (11, 1, 'p1', '{P1}'), (21, 2, 'p2', '{P2}');
            CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER,
                Name TEXT, GUID TEXT);
            INSERT INTO BidNamedViews VALUES (31, 1, 11, 'v1', '{V1}'), (32, 2, 21, 'v2', '{V2}');
            CREATE TABLE BidHotLinks (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER,
                BidPageViewUID INTEGER, Name TEXT);
            INSERT INTO BidHotLinks VALUES (41, 1, 11, 31, 'h1'), (42, 2, 21, 32, 'h2');
            """
        )
        new_uid = _SqliteDuplicateOps(conn).duplicate_bid("x.mdb", "1")
        self.assertIsNotNone(new_uid)
        page = conn.execute(
            "SELECT UID FROM BidPages WHERE BidUID=?", (int(new_uid),)
        ).fetchone()[0]
        view = conn.execute(
            "SELECT UID FROM BidNamedViews WHERE BidUID=?", (int(new_uid),)
        ).fetchone()[0]
        self.assertEqual(
            conn.execute(
                "SELECT Name, BidPageUID, BidPageViewUID FROM BidHotLinks WHERE BidUID=?",
                (int(new_uid),),
            ).fetchall(),
            [("h1", page, view)],
        )
        self.assertNotIn(page, (11, 21))
        self.assertNotIn(view, (31, 32))
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidPageUID, BidPageViewUID FROM BidHotLinks "
                "WHERE Name IN ('h1','h2') AND BidUID IN (1, 2) ORDER BY UID"
            ).fetchall(),
            [(41, 1, 11, 31), (42, 2, 21, 32)],
        )

    def test_deleting_a_bid_removes_its_rows_from_every_scoped_table_and_no_others(
        self,
    ):
        for label, columns in (
            ("page only", "BidPageUID INTEGER"),
            ("bid only", "BidUID INTEGER"),
        ):
            with self.subTest(page_scoped_tables=label):
                conn, tables = self.build_cascade(columns)
                self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
                self.assertEqual(
                    conn.execute("SELECT UID FROM Bids").fetchall(), [(2,)]
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidPages").fetchall(), [(21,)]
                )
                for table in tables:
                    self.assertEqual(
                        conn.execute(f"SELECT UID FROM [{table}]").fetchall(),
                        [(2,)],
                        table,
                    )

    def test_deleting_a_bid_removes_percentages_and_condition_styles_of_its_children(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER PRIMARY KEY);
            INSERT INTO Bids VALUES (1), (2);
            CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER);
            INSERT INTO BidTakeoffs VALUES (10, 1, NULL), (20, 2, NULL);
            CREATE TABLE BidPercents (UID INTEGER, BidTakeoffUID INTEGER);
            INSERT INTO BidPercents VALUES (1, 10), (2, 20);
            CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER);
            INSERT INTO BidConditions VALUES (30, 1), (40, 2);
            CREATE TABLE ConditionSetStyles (UID INTEGER, ConditionStyleUID INTEGER);
            INSERT INTO ConditionSetStyles VALUES (1, 30), (2, 40);
            """
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        for table, expected in (
            ("BidPercents", [(2,)]),
            ("ConditionSetStyles", [(2,)]),
            ("BidConditions", [(40,)]),
            ("BidTakeoffs", [(20,)]),
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT UID FROM {table}").fetchall(), expected
                )

    def test_deleting_a_bid_needs_a_bid_uid_column_before_it_touches_anything(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            "CREATE TABLE Bids (Name TEXT); INSERT INTO Bids VALUES ('x');"
        )
        error = self.failure_exception(
            lambda: self.StrictOps(conn).delete_bids("bid.mdb", ["1"])
        )
        self.assertRegex(str(error), "Missing Bids.UID")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone(), (1,))

    def test_duplicating_a_bid_needs_the_uid_column_and_a_bid_column_in_its_settings(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript("CREATE TABLE Bids (Name TEXT);")
        error = self.failure_exception(
            lambda: self.StrictOps(conn).duplicate_bid("bid.mdb", "1")
        )
        self.assertRegex(str(error), "Missing Bids.UID")
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            "CREATE TABLE Bids (UID INTEGER, BidNo INTEGER); INSERT INTO Bids VALUES (1, 1);"
            "CREATE TABLE BidSettings (UID INTEGER);"
            "CREATE TABLE Settings (NextBidNo INTEGER); INSERT INTO Settings VALUES (2);"
        )
        error = self.failure_exception(
            lambda: self.StrictOps(conn).duplicate_bid("bid.mdb", "1")
        )
        self.assertRegex(str(error), "Missing BidSettings.BidUID")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone(), (1,))
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone(), (2,)
        )

    def test_creating_a_bid_needs_a_job_name_column_and_writes_nothing_without_it(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            "CREATE TABLE Bids (UID INTEGER);"
            "CREATE TABLE Settings (NextBidNo INTEGER); INSERT INTO Settings VALUES (4);"
        )
        error = self.failure_exception(
            lambda: self.StrictOps(conn).create_bid("bid.mdb", None, {"job_name": "X"})
        )
        self.assertRegex(str(error), "Missing Bids.JobName")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone(), (0,))
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone(), (4,)
        )

    def new_bid_database(self, settings_values):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Settings (NextBidNo INTEGER, ScaleStyle INTEGER,
                ScaleFactor1 REAL, ScaleFactor2 REAL, PageWidth REAL, PageHeight REAL,
                MeasureBase INTEGER, TakeoffIncrements REAL);
            CREATE TABLE Bids (UID INTEGER, GUID TEXT, BidNo INTEGER, JobName TEXT,
                JobID TEXT, Notes BLOB, BidDate TEXT, MeasureBase INTEGER,
                TakeoffIncrements REAL, ScaleStyle INTEGER, ScaleFactor1 REAL,
                ScaleFactor2 REAL, PageWidth REAL, PageHeight REAL, HoursPerDay INTEGER,
                LegendFlags INTEGER, BidType INTEGER, PriceUsing INTEGER,
                WeekStartDay INTEGER, PageScale REAL, CoverSheetSelItemType INTEGER,
                CoverSheetSelItemUID INTEGER);
            CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, SheetNo TEXT, Name TEXT,
                Width REAL, Height REAL, ScaleFactor1 REAL, ScaleFactor2 REAL, Show INTEGER,
                RasterDrawMethod INTEGER, ScaleStyle INTEGER, GUID TEXT, Index1 INTEGER,
                Sequence INTEGER, MultiPageCount INTEGER, ImagePath TEXT,
                OverlayImagePath TEXT, BidPageFolderUID INTEGER);
            CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT,
                ParentUID INTEGER);
            """
        )
        conn.execute(
            "INSERT INTO Settings VALUES (?, ?, ?, ?, ?, ?, ?, ?)", settings_values
        )
        return conn

    def test_a_new_bid_falls_back_to_the_built_in_defaults_for_unset_settings(self):
        conn = self.new_bid_database((9, None, None, None, None, None, None, None))
        ops = _SqliteDuplicateOps(conn)
        self.assertEqual(
            ops.create_bid(
                "new.mdb",
                None,
                {
                    "pages": [
                        {"width": 10.0, "height": 8.0},
                        {"width": 5.0, "height": 4.0},
                    ]
                },
            ),
            "1",
        )
        columns = (
            "BidNo, JobName, JobID, Notes, BidDate, MeasureBase, TakeoffIncrements, "
            "ScaleStyle, ScaleFactor1, ScaleFactor2, PageWidth, PageHeight, HoursPerDay, "
            "LegendFlags, BidType, PriceUsing, WeekStartDay, PageScale, "
            "CoverSheetSelItemType, CoverSheetSelItemUID"
        )
        self.assertEqual(
            conn.execute(f"SELECT {columns} FROM Bids").fetchall(),
            [
                (
                    9,
                    "",
                    "",
                    b"",
                    None,
                    0,
                    1.0,
                    1,
                    0.125,
                    12.0,
                    42.0,
                    30.0,
                    8,
                    41,
                    0,
                    0,
                    0,
                    0.0,
                    1,
                    1,
                )
            ],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, SheetNo, Name, Width, Height, ScaleFactor1, ScaleFactor2, Show,"
                " RasterDrawMethod, ScaleStyle, Index1, Sequence, MultiPageCount, ImagePath,"
                " OverlayImagePath, BidPageFolderUID FROM BidPages ORDER BY UID"
            ).fetchall(),
            [
                (1, "", "", 10.0, 8.0, 0.125, 12.0, 0, 1, 1, 1, 1, 0, "", "", None),
                (2, "", "", 5.0, 4.0, 0.125, 12.0, 0, 1, 1, 1, 2, 0, "", "", None),
            ],
        )
        self.assertEqual(
            conn.execute("SELECT NextBidNo FROM Settings").fetchone(), (10,)
        )

    def test_a_new_bid_takes_the_settings_values_and_the_callers_overrides(self):
        conn = self.new_bid_database((3, 2, 0.25, 24.0, 36.0, 24.0, 1, 0.5))
        ops = _SqliteDuplicateOps(conn)
        ops.create_bid(
            "new.mdb",
            None,
            {
                "job_name": "Tower",
                "job_id": "J-7",
                "bid_date": "2026-01-02",
                "measure_base": 2,
                "takeoff_increments": 0.75,
                "scale_style": 3,
                "scale_factor1": 0.5,
                "scale_factor2": 6.0,
                "page_width": 48.0,
                "page_height": 36.0,
                "pages": [
                    {
                        "width": 10.0,
                        "height": 8.0,
                        "sheet_no": "S-1",
                        "name": "Plan",
                        "scale_factor1": 1.0,
                        "scale_factor2": 4.0,
                        "show_mode": 2,
                        "index": 7,
                        "sequence": 9,
                        "multi_page_count": 5,
                        "image_path": "a.pdf",
                        "overlay_path": "b.pdf",
                    }
                ],
            },
        )
        self.assertEqual(
            conn.execute(
                "SELECT BidNo, JobName, JobID, BidDate, MeasureBase, TakeoffIncrements,"
                " ScaleStyle, ScaleFactor1, ScaleFactor2, PageWidth, PageHeight FROM Bids"
            ).fetchall(),
            [(3, "Tower", "J-7", "2026-01-02", 2, 0.75, 3, 0.5, 6.0, 48.0, 36.0)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT SheetNo, Name, ScaleFactor1, ScaleFactor2, Show, ScaleStyle,"
                " Index1, Sequence, MultiPageCount, ImagePath, OverlayImagePath"
                " FROM BidPages"
            ).fetchall(),
            [("S-1", "Plan", 1.0, 4.0, 2, 3, 7, 9, 5, "a.pdf", "b.pdf")],
        )

    def test_a_new_bid_uses_the_stored_settings_when_the_caller_gives_none(self):
        conn = self.new_bid_database((3, 2, 0.25, 24.0, 36.0, 24.0, 1, 0.5))
        _SqliteDuplicateOps(conn).create_bid(
            "new.mdb", None, {"pages": [{"width": 10.0, "height": 8.0}]}
        )
        self.assertEqual(
            conn.execute(
                "SELECT MeasureBase, TakeoffIncrements, ScaleStyle, ScaleFactor1,"
                " ScaleFactor2, PageWidth, PageHeight FROM Bids"
            ).fetchall(),
            [(1, 0.5, 2, 0.25, 24.0, 36.0, 24.0)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT ScaleFactor1, ScaleFactor2, ScaleStyle FROM BidPages"
            ).fetchall(),
            [(0.25, 24.0, 2)],
        )

    def test_new_pages_land_in_the_new_folders_they_name(self):
        conn = self.new_bid_database((1, None, None, None, None, None, None, None))
        _SqliteDuplicateOps(conn).create_bid(
            "new.mdb",
            None,
            {
                "new_folders": [
                    {"local_uid": "child", "name": "Child", "parent_uid": "root"},
                    {"local_uid": "root", "name": "Root"},
                    {"local_uid": "other", "name": ""},
                ],
                "pages": [
                    {"width": 1.0, "height": 1.0, "name": "A", "folder_uid": "child"},
                    {"width": 1.0, "height": 1.0, "name": "B"},
                ],
            },
        )
        folders = {
            row[1]: row
            for row in conn.execute("SELECT UID, Name, ParentUID FROM BidPageFolders")
        }
        self.assertEqual(set(folders), {"Child", "Root", "New Folder"})
        self.assertIsNone(folders["Root"][2])
        self.assertIsNone(folders["New Folder"][2])
        self.assertEqual(folders["Child"][2], folders["Root"][0])
        self.assertEqual(
            conn.execute(
                "SELECT Name, BidPageFolderUID FROM BidPages ORDER BY UID"
            ).fetchall(),
            [("A", folders["Child"][0]), ("B", None)],
        )


class BidOperationsCompatibilityTests(unittest.TestCase):
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
        with self.assertLogs(writer.logger.name, level="ERROR") as logs:
            self.assertIsNone(
                writer.create_bid("legacy.mdb", None, {"job_name": "Bid"})
            )
        self.assertIs(logs.records[0].exc_info[0], BidNumberAllocationUnavailableError)
        self.assertIn("Settings table is unavailable", str(logs.records[0].exc_info[1]))
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
        with self.assertLogs(writer.logger.name, level="ERROR") as logs:
            self.assertIsNone(writer.duplicate_bid("legacy.mdb", "1"))
        self.assertIs(logs.records[0].exc_info[0], BidNumberAllocationUnavailableError)
        self.assertIn("Settings table is unavailable", str(logs.records[0].exc_info[1]))
        self.assertEqual(writer.inserted, [])

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
                excluded_source_uids=None,
                schema=None,
            ):
                del extra_overrides, excluded_source_uids, schema

            @staticmethod
            def _copy_with_uid_map(
                _cursor,
                table,
                _uid_column,
                _old_uid,
                _new_uid,
                schema=None,
                relationship_uid_maps=None,
            ):
                del schema, relationship_uid_maps
                return {"10": "20"} if table == "BidLayers" else {}

            @staticmethod
            def _duplicated_reference_uids(_cursor, _table, _column, _bid_uid):
                return {"10"}

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

            @staticmethod
            def _update_if_columns(*_args):
                pass

            def _update_page_owned_relationship(
                self,
                _cursor,
                _schema,
                table,
                set_column,
                set_value,
                old_value,
                bid_uid,
            ):
                self.updates.append((table, set_column, set_value, old_value, bid_uid))

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
        self.assertCountEqual(
            writer.updates,
            [
                ("BidPageSettings", "BidAreaUID", "110", "10", "2"),
                ("BidPageSettings", "BidTypAreaUID", "111", "11", "2"),
            ],
        )

    def test_duplicate_does_not_remap_page_ownership_after_page_scoped_copy(self):
        class Schema:
            @staticmethod
            def column_exists(table, column):
                return (table, column) in {
                    ("BidMarkedPages", "BidPageUID"),
                    ("BidPages", "BidUID"),
                }

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.updates = []

            def _update_if_columns(self, *_args):
                self.updates.append(_args)

            def _update_page_owned_relationship(self, *_args):
                self.updates.append(_args)

            @staticmethod
            def _duplicated_reference_uids(_cursor, _table, _column, _bid_uid):
                return set()

        page_uid_map = {
            str(source_uid): str(source_uid + 1000) for source_uid in range(1, 21)
        }
        writer = RecordingWriter()
        writer._remap_duplicated_relationships(
            object(),
            Schema(),
            {"BidPages": page_uid_map},
            "2",
        )
        self.assertEqual(writer.updates, [])

    def test_duplicate_copies_all_rows_for_a_page_table_in_one_query(self):
        class Cursor:
            description = (("BidPageUID", int), ("UID", int))

            def __init__(self):
                self.queries = []

            def execute(self, sql, *_params):
                self.queries.append(sql)
                return self

            @staticmethod
            def fetchall():
                return [(10, 100), (20, 200)]

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def column_exists(_table, _column):
                return True

            @staticmethod
            def get_columns(_table):
                return {"UID", "BidPageUID"}

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.allocations = []
                self.inserts = []

            def _next_uids_preserving_references(self, _cursor, _schema, table, count):
                self.allocations.append((table, count))
                return range(300, 300 + count)

            def _execute_insert_values(
                self,
                _cursor,
                _schema,
                table,
                values,
                _required_columns,
                _operation,
            ):
                self.inserts.append((table, values))

        cursor = Cursor()
        writer = RecordingWriter()
        uid_map = writer._copy_page_table_rows(
            cursor,
            Schema(),
            "BidMarkedPages",
            "1",
            "2",
            {"10": "110", "20": "120"},
        )
        self.assertEqual(len(cursor.queries), 1)
        self.assertEqual(writer.allocations, [("BidMarkedPages", 2)])
        self.assertEqual(uid_map, {"100": "300", "200": "301"})
        self.assertEqual(
            [values["BidPageUID"] for _table, values in writer.inserts],
            ["110", "120"],
        )
        self.assertEqual(
            [values["UID"] for _table, values in writer.inserts], [300, 301]
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
                self.area_count_copy_calls = []

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
                excluded_source_uids=None,
                schema=None,
            ):
                del extra_overrides, excluded_source_uids, schema
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

            def _copy_page_table_rows(
                self,
                cursor,
                _schema,
                table,
                _source_bid_uid,
                _new_bid_uid,
                page_uid_map,
            ):
                old_page_uid, new_page_uid = next(iter(page_uid_map.items()))
                return self._copy_bid_table_rows(
                    cursor,
                    table,
                    "BidPageUID",
                    old_page_uid,
                    new_page_uid,
                    extra_overrides={"BidUID": _new_bid_uid},
                )

            def _copy_area_count_rows(
                self,
                _cursor,
                _schema,
                source_bid_uid,
                area_uid_map,
                typical_area_uid_map,
            ):
                self.area_count_copy_calls.append(
                    (source_bid_uid, dict(area_uid_map), dict(typical_area_uid_map))
                )
                return {"91": "191"}

            def _copy_with_uid_map(
                self,
                _cursor,
                table,
                _uid_column,
                _old_uid,
                _new_uid,
                schema=None,
                relationship_uid_maps=None,
            ):
                del self, schema, relationship_uid_maps
                return {
                    "BidConditions": {"30": "130"},
                    "BidAreas": {"60": "160"},
                }.get(table, {})

            @staticmethod
            def _duplicated_reference_uids(_cursor, _table, _column, _bid_uid):
                return {str(uid) for uid in range(1, 201)}

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
        self.assertEqual(
            writer.area_count_copy_calls,
            [("1", {"60": "160"}, {"70": "170"})],
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

    def test_duplicate_bid_remaps_page_typed_cover_sheet_selection(self):
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
        for stored in (10, "10"):
            writer._remap_duplicated_cover_sheet_selection(
                object(),
                object(),
                {"CoverSheetSelItemType": 1, "CoverSheetSelItemUID": stored},
                {"10": "20", "11": "21"},
                "2",
            )
        writer._remap_duplicated_cover_sheet_selection(
            object(),
            object(),
            {"CoverSheetSelItemType": 1, "CoverSheetSelItemUID": "not-a-uid"},
            {"10": "20"},
            "2",
        )
        self.assertEqual(
            writer.updates,
            [
                ("Bids", "CoverSheetSelItemUID", "20", ("UID",), ("2",)),
                ("Bids", "CoverSheetSelItemUID", "20", ("UID",), ("2",)),
                ("Bids", "CoverSheetSelItemUID", None, ("UID",), ("2",)),
            ],
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
        with self.assertLogs(writer.logger.name, level="ERROR") as logs:
            self.assertIsNone(writer.duplicate_bid("example.mdb", "1"))
        self.assertIs(logs.records[0].exc_info[0], BidSettingsCardinalityError)
        self.assertIn(
            "BidSettings has multiple rows for Bids.UID=1",
            str(logs.records[0].exc_info[1]),
        )
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
        self.assertRegex(writer.inserted["GUID"], r"^\{[0-9A-F-]{36}\}$")


class BidOperationsRelationshipTests(unittest.TestCase):
    def test_duplicate_page_settings_copies_only_canonical_selected_row(self):
        class Cursor:
            connection = object()
            description = (
                ("UID", int),
                ("BidPageUID", int),
                ("BidAreaUID", int),
                ("BidAreaSelected", int),
            )

            @staticmethod
            def execute(_sql, *_params):
                pass

            @staticmethod
            def fetchall():
                return [
                    (None, 8, 20, 28),
                    (0, 9, 20, 29),
                    (2, 10, 20, 30),
                    (2, 11, 20, 31),
                ]

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def column_exists(_table, _column):
                return True

            @staticmethod
            def get_columns(_table):
                return {"UID", "BidPageUID", "BidAreaUID", "BidAreaSelected"}

        class RecordingWriter(MdbWriter):
            def __init__(self):
                super().__init__()
                self.inserted = []
                self._next = 100

            @staticmethod
            def _schema(_connection):
                return Schema()

            def _next_uid(self, _cursor, _table):
                value = self._next
                self._next += 1
                return value

            def _execute_insert_values(
                self, _cursor, _schema, _table, values, _required, _operation
            ):
                self.inserted.append(dict(values))

        writer = RecordingWriter()
        uid_map = writer._copy_bid_table_rows(
            Cursor(), "BidPageSettings", "BidPageUID", "20", "120"
        )
        self.assertEqual(
            [(row["BidAreaUID"], row["BidAreaSelected"]) for row in writer.inserted],
            [(8, None), (9, 0), (11, 2)],
        )
        self.assertEqual(set(uid_map), {"28", "29", "31"})
        self.assertEqual(
            [(row["UID"], row["BidPageUID"]) for row in writer.inserted],
            [(100, "120"), (101, "120"), (102, "120")],
        )


class BidOperationsLockedStatusInheritanceTests(unittest.TestCase):
    """Decision B6 (risk 2): the duplicate of a Bid copies every column except the
    identity and timestamp overrides, so the copy keeps the source's Job Status: a copy
    of a status-locked Bid is itself locked (a locked Bid can be duplicated and the copy
    is locked too). Fake: sqlite stand-in schema of the duplicate operations helper; the
    Access/SQL engines are not involved."""

    def test_the_duplicate_keeps_the_job_status_of_the_source(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (12)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, GUID TEXT, "
            "JobStatusUID INTEGER, EstimatorUID INTEGER, PrManagerUID INTEGER, "
            "JobSiteManagerUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, ?, ?, NULL, NULL, NULL)",
            ((7, 11, "{LOCKED}", 8), (9, 3, "{OTHER}", 4)),
        )
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
        conn.executemany("INSERT INTO JobStatuses VALUES (?)", ((8,), (4,)))
        conn.execute("CREATE TABLE Employees (UID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        new_uid = _SqliteDuplicateOps(conn).duplicate_bid("locked.mdb", "7")
        self.assertEqual(new_uid, "10")
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidNo, JobStatusUID FROM Bids ORDER BY UID"
            ).fetchall(),
            [(7, 11, 8), (9, 3, 4), (10, 12, 8)],
        )


def _rows(conn, sql):
    return conn.execute(sql).fetchall()


class BidDeleteReturnContractTests(unittest.TestCase):
    def _bids(self):
        return contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
        )

    def test_deleting_no_bids_is_a_successful_no_op(self):
        conn = self._bids()
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", []), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM Bids"), [(1,), (2,)])

    def test_invalid_bid_ids_fail_with_a_warning_and_delete_nothing(self):
        conn = self._bids()
        with self.assertLogs("test", "WARNING") as logs:
            self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["abc"]), False)
        self.assertIn("Invalid bid uids passed to delete_bids", logs.output[0])
        self.assertEqual(_rows(conn, "SELECT UID FROM Bids"), [(1,), (2,)])

    def test_a_successful_delete_returns_true_and_keeps_other_bids(self):
        conn = self._bids()
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM Bids"), [(2,)])

    def test_deleting_bids_needs_a_uid_column_and_reports_failure(self):
        conn = contract_db("CREATE TABLE Bids (Name TEXT)")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), False)
        self.assertIn("Failed to delete bids", logs.records[0].getMessage())
        self.assertIn("Missing Bids.UID", str(logs.records[0].exc_info[1]))

    def test_an_unknown_bid_in_the_batch_is_ignored_and_the_known_bids_are_deleted(self):
        conn = self._bids()
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1", "9"]), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM Bids"), [(2,)])


class BidDeleteCascadeCompletenessTests(unittest.TestCase):
    """Every table the cascade names must really lose the deleted bid's rows."""

    def test_every_bid_scoped_table_loses_only_the_deleted_bids_rows(self):
        # Literal oracle: deliberately not imported from the production module,
        # whose constants are what this test must be able to catch.
        tables = [
            "BidLaborActivity", "BidTakeoffTotals", "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals", "AffectDPCTypGroupViews", "BidTypGroupViews",
            "Boost", "DPCCalcFilter", "BidDPCSubscribers", "BidNotes",
            "BidTransactionsHistory", "STSTransactionHistory", "BidConditionUser",
            "BidPlanRooms", "BidHotLinks", "BidNamedViews", "BidSettings",
            "BidLaborCostCodes", "BidTimeCardStates", "BidEmployees", "BidConditions",
            "BidZones", "BidConditionFolders", "BidLayers", "BidAreas", "BidTypAreas",
            "BidPageFolders",
        ]
        # Parents of the foreign-key children below get explicit rows.
        parent_tables = {
            "BidLaborCostCodes", "BidTimeCardStates", "BidEmployees",
            "BidAreas", "BidTypAreas",
        }
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "INSERT INTO BidPages VALUES (20, 2)",
        )
        for index, table in enumerate(tables):
            conn.execute(f"CREATE TABLE {table} (UID INTEGER, BidUID INTEGER)")
            if table in parent_tables:
                rows = [(101, 1), (201, 2)]
            else:
                rows = [(1000 + index * 2, 1), (1001 + index * 2, 2)]
            conn.executemany(f"INSERT INTO {table} VALUES (?, ?)", rows)
        child_specs = {
            "BidPercents": ("BidLaborCostCodeUID", "BidTimeCardStateUID"),
            "BidTimeCards": (
                "BidEmployeeUID", "BidAreaUID", "BidTypicalAreaUID",
                "BidLaborCostCodeUID", "BidTimeCardStateUID",
            ),
            "BidTypAreaCounts": ("BidAreaUID", "BidTypAreaUID"),
            "BidPageSettings": ("BidAreaUID", "BidTypAreaUID"),
        }
        for child, fks in child_specs.items():
            conn.execute(
                f"CREATE TABLE {child} (UID INTEGER, {', '.join(f'{c} INTEGER' for c in fks)})"
            )
            uid = 0
            for position in range(len(fks)):
                for parent in (101, 201):
                    uid += 1
                    values = [parent if i == position else None for i in range(len(fks))]
                    conn.execute(
                        f"INSERT INTO {child} VALUES (?, {', '.join('?' * len(fks))})",
                        (uid, *values),
                    )
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM Bids"), [(2,)])
        self.assertEqual(_rows(conn, "SELECT UID FROM BidPages"), [(20,)])
        for table in tables:
            with self.subTest(table=table):
                remaining = _rows(conn, f"SELECT UID, BidUID FROM {table}")
                self.assertEqual({bid for _uid, bid in remaining}, {2})
                self.assertEqual(len(remaining), 1)
        for child, fks in child_specs.items():
            with self.subTest(child=child):
                self.assertEqual(
                    [uid for (uid,) in _rows(conn, f"SELECT UID FROM {child} ORDER BY UID")],
                    [2 * (position + 1) for position in range(len(fks))],
                )

    def test_takeoffs_of_a_schema_without_a_bid_column_are_removed_through_their_pages(
        self,
    ):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "INSERT INTO BidPages VALUES (20, 2)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (1, 10)",
            "INSERT INTO BidTakeoffs VALUES (2, 20)",
        )
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM BidTakeoffs"), [(2,)])

    def test_missing_cascade_tables_and_columns_are_skipped_not_errors(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidNotes (UID INTEGER)",
            "INSERT INTO BidNotes VALUES (5)",
        )
        with self.assertNoLogs("test", "ERROR"):
            self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM BidNotes"), [(5,)])


class CreateBidWriteContractTests(unittest.TestCase):
    _DDL = (
        "CREATE TABLE Settings (NextBidNo INTEGER, ScaleStyle INTEGER, ScaleFactor1 REAL, "
        "ScaleFactor2 REAL, PageWidth REAL, PageHeight REAL, MeasureBase INTEGER, "
        "TakeoffIncrements REAL)",
        "CREATE TABLE BidProjects (UID INTEGER)",
        "CREATE TABLE JobStatuses (UID INTEGER)",
        "CREATE TABLE Employees (UID INTEGER)",
        "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, GUID TEXT, BidNo INTEGER, "
        "JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER, Notes BLOB, "
        "BidDate TEXT, JobID TEXT, CreateDateTime TEXT, MeasureBase INTEGER, "
        "TakeoffIncrements REAL, ScaleStyle INTEGER, ScaleFactor1 REAL, ScaleFactor2 REAL, "
        "PageWidth REAL, PageHeight REAL, HoursPerDay INTEGER, LegendFlags INTEGER, "
        "BidType INTEGER, PriceUsing INTEGER, WeekStartDay INTEGER, PageScale REAL, "
        "CoverSheetSelItemType INTEGER, CoverSheetSelItemUID INTEGER)",
        "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER, "
        "IsLocked INTEGER, Sequence INTEGER, IsTemplate INTEGER)",
        "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, SheetNo TEXT, Name TEXT, "
        "Width REAL, Height REAL, ScaleFactor1 REAL, ScaleFactor2 REAL, Show INTEGER, "
        "RasterDrawMethod INTEGER, ScaleStyle INTEGER, GUID TEXT, Index1 INTEGER, "
        "Sequence INTEGER, MultiPageCount INTEGER, ImagePath TEXT, OverlayImagePath TEXT, "
        "BidPageFolderUID INTEGER)",
        "CREATE TABLE BidLegends (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
        "FontName TEXT, FontSize INTEGER, MoveToCorner INTEGER)",
        "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID INTEGER)",
    )

    def _db(self):
        conn = contract_db(*self._DDL)
        conn.execute("INSERT INTO Settings VALUES (4, 2, 0.25, 24.0, 36.0, 24.0, 1, 0.5)")
        conn.execute("INSERT INTO BidProjects VALUES (3)")
        conn.execute("INSERT INTO JobStatuses VALUES (6)")
        conn.execute("INSERT INTO Employees VALUES (8)")
        conn.executemany(
            "INSERT INTO BidLayers VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, None, "Template shown", 1, -1, 5, -1),
                (2, None, "Template hidden", 0, 0, None, -1),
                (3, None, "Template odd", 2, 2, 7, -1),
                (4, None, "Plain layer", -1, 0, 1, 0),
            ],
        )
        return conn

    def test_a_new_bid_persists_every_column_through_the_real_write_contract(self):
        conn = self._db()
        ops = RealContractOps(conn)
        new_uid = ops.create_bid(
            "x.mdb",
            "3",
            {
                "job_name": "Tower",
                "job_status_uid": "6",
                "estimator_uid": "8",
                "notes": "memo",
                "bid_date": "2026-01-02",
                "job_id": "J-1",
                "new_folders": [{"local_uid": "f", "name": "Folder"}],
                "pages": [
                    {"width": 10.0, "height": 8.0, "name": "A", "folder_uid": "f"},
                    {"width": 5.0, "height": 4.0, "name": "B"},
                    {"height": 4.0, "name": "Skipped"},
                ],
            },
        )
        self.assertEqual(new_uid, "1")
        self.assertEqual(ops.skips, [])
        row = conn.execute(
            "SELECT UID, BidProjectUID, BidNo, JobName, JobStatusUID, EstimatorUID, "
            "BidDate, JobID, MeasureBase, TakeoffIncrements, ScaleStyle, ScaleFactor1, "
            "ScaleFactor2, PageWidth, PageHeight, HoursPerDay, LegendFlags, BidType, "
            "PriceUsing, WeekStartDay, PageScale, CoverSheetSelItemType, "
            "CoverSheetSelItemUID, Notes, GUID, CreateDateTime FROM Bids"
        ).fetchone()
        self.assertEqual(
            row[:22],
            (1, 3, 4, "Tower", 6, 8, "2026-01-02", "J-1", 1, 0.5, 2, 0.25, 24.0, 36.0,
             24.0, 8, 41, 0, 0, 0, 0.0, 1),
        )
        first_page = conn.execute("SELECT MIN(UID) FROM BidPages").fetchone()[0]
        self.assertEqual(row[22], first_page)
        self.assertEqual(row[23], encode_text_blob("memo"))
        self.assertRegex(row[24], r"^\{[0-9A-F-]{36}\}$")
        stamp = datetime.datetime.fromisoformat(row[25])
        self.assertEqual((stamp.second, stamp.microsecond), (0, 0))
        self.assertEqual(_rows(conn, "SELECT NextBidNo FROM Settings"), [(5,)])
        self.assertEqual(
            _rows(
                conn,
                "SELECT UID, BidUID, Name, Show, IsLocked, Sequence, IsTemplate "
                "FROM BidLayers WHERE IsTemplate = 0 AND BidUID = 1 ORDER BY UID",
            ),
            [
                (5, 1, "Template shown", -1, -1, 5, 0),
                (6, 1, "Template hidden", 0, 0, 1, 0),
                (7, 1, "Template odd", 0, 0, 7, 0),
            ],
        )
        folder_uid = conn.execute("SELECT UID FROM BidPageFolders").fetchone()[0]
        self.assertEqual(
            _rows(conn, "SELECT BidUID, Name, ParentUID FROM BidPageFolders"),
            [(1, "Folder", None)],
        )
        self.assertEqual(
            _rows(conn, "SELECT Name, BidPageFolderUID FROM BidPages ORDER BY UID"),
            [("A", folder_uid), ("B", None)],
        )
        legends = _rows(
            conn,
            "SELECT BidUID, BidPageUID, FontName, FontSize, MoveToCorner "
            "FROM BidLegends ORDER BY BidPageUID",
        )
        self.assertEqual(
            legends,
            [
                (1, page, "Arial", 10, -1)
                for (page,) in _rows(conn, "SELECT UID FROM BidPages ORDER BY UID")
            ],
        )
        self.assertEqual(
            _rows(conn, "SELECT UID, BidUID, BidPageSelectedUID FROM BidSettings"),
            [(1, 1, first_page)],
        )

    def test_a_bid_without_pages_has_no_selected_page_or_cover_selection_uid(self):
        conn = self._db()
        ops = RealContractOps(conn)
        self.assertEqual(ops.create_bid("x.mdb", None, {"job_name": "Empty"}), "1")
        self.assertEqual(
            _rows(conn, "SELECT BidProjectUID, CoverSheetSelItemUID FROM Bids"),
            [(None, None)],
        )
        self.assertEqual(
            _rows(conn, "SELECT BidPageSelectedUID FROM BidSettings"), [(None,)]
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidLegends"), [(0,)])

    def test_unset_template_flags_and_missing_job_name_use_documented_values(self):
        conn = self._db()
        RealContractOps(conn).create_bid("x.mdb", None, {"job_name": None})
        self.assertEqual(_rows(conn, "SELECT JobName, JobID FROM Bids"), [("", "")])

    def test_a_new_bid_needs_the_uid_and_job_name_columns(self):
        for dropped in ("UID", "JobName"):
            with self.subTest(missing=dropped):
                conn = self._db()
                conn.execute(f"ALTER TABLE Bids DROP COLUMN {dropped}")
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIsNone(
                        RealContractOps(conn).create_bid("x.mdb", None, {"job_name": "X"})
                    )
                self.assertIn(
                    f"Missing Bids.{dropped}", str(logs.records[0].exc_info[1])
                )

    def test_bid_layer_pages_and_legends_need_their_owner_columns(self):
        for table, dropped, updates in (
            ("BidLayers", "BidUID", {"job_name": "X"}),
            ("BidLayers", "Name", {"job_name": "X"}),
            ("BidPages", "BidUID", {"pages": [{"width": 1.0, "height": 1.0}]}),
            ("BidLegends", "BidPageUID", {"pages": [{"width": 1.0, "height": 1.0}]}),
            ("BidPageFolders", "Name", {"new_folders": [{"name": "F"}]}),
        ):
            with self.subTest(table=table, missing=dropped):
                conn = self._db()
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {dropped}")
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIsNone(
                        RealContractOps(conn).create_bid("x.mdb", None, updates)
                    )
                self.assertIn(
                    f"Missing {table}.{dropped}", str(logs.records[0].exc_info[1])
                )

    def test_a_missing_optional_bid_column_is_reported_with_the_operation_label(self):
        conn = self._db()
        conn.execute("ALTER TABLE Bids DROP COLUMN PageScale")
        ops = RealContractOps(conn)
        ops.create_bid("x.mdb", None, {"job_name": "X"})
        self.assertEqual(ops.skips, [("Bids", "PageScale", "create_bid")])
        conn = self._db()
        conn.execute("ALTER TABLE BidPages DROP COLUMN MultiPageCount")
        ops = RealContractOps(conn)
        ops.create_bid("x.mdb", None, {"pages": [{"width": 1.0, "height": 1.0}]})
        self.assertEqual(ops.skips, [("BidPages", "MultiPageCount", "create_bid_page")])
        conn = self._db()
        conn.execute("ALTER TABLE BidLegends DROP COLUMN MoveToCorner")
        ops = RealContractOps(conn)
        ops.create_bid("x.mdb", None, {"pages": [{"width": 1.0, "height": 1.0}]})
        self.assertEqual(ops.skips, [("BidLegends", "MoveToCorner", "create_bid_legend")])
        conn = self._db()
        conn.execute("ALTER TABLE BidLayers DROP COLUMN IsLocked")
        ops = RealContractOps(conn)
        ops.create_bid("x.mdb", None, {"job_name": "X"})
        self.assertEqual(ops.skips, [("BidLayers", "IsLocked", "create_bid_layer")] * 3)
        conn = self._db()
        conn.execute("ALTER TABLE BidPageFolders DROP COLUMN ParentUID")
        ops = RealContractOps(conn)
        ops.create_bid("x.mdb", None, {"new_folders": [{"name": "F"}]})
        self.assertEqual(
            ops.skips, [("BidPageFolders", "ParentUID", "create_bid_page_folder")]
        )

    def test_missing_cover_sheet_selection_column_is_reported_by_label(self):
        conn = self._db()
        conn.execute("ALTER TABLE Bids DROP COLUMN CoverSheetSelItemUID")
        ops = RealContractOps(conn)
        ops.create_bid("x.mdb", None, {"pages": [{"width": 1.0, "height": 1.0}]})
        self.assertEqual(
            ops.skips, [("Bids", "CoverSheetSelItemUID", "create_bid_cover_sheet_selection")]
        )

    def test_the_selected_page_row_requires_only_its_bid_column(self):
        conn = self._db()
        conn.execute("ALTER TABLE BidSettings DROP COLUMN UID")
        ops = RealContractOps(conn)
        self.assertEqual(ops.create_bid("x.mdb", None, {"job_name": "X"}), "1")
        self.assertEqual(ops.skips, [("BidSettings", "UID", "create_bid_settings")])
        self.assertEqual(_rows(conn, "SELECT BidUID FROM BidSettings"), [(1,)])


class DuplicateBidWriteContractTests(unittest.TestCase):
    def _db(self, *extra):
        return contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (5)",
            "CREATE TABLE Bids (UID INTEGER, GUID TEXT, BidNo INTEGER, JobName TEXT, "
            "CopyFromBidNO INTEGER, CopyTimeStamp TEXT, CreateDateTime TEXT, "
            "ModDateTime TEXT, CoverSheetSelItemType INTEGER, CoverSheetSelItemUID INTEGER)",
            "INSERT INTO Bids VALUES (1, '{OLD-BID}', 3, 'Source', NULL, NULL, NULL, NULL, 1, 20)",
            "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID INTEGER)",
            "INSERT INTO BidSettings VALUES (1, 1, 20)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, GUID TEXT, Name TEXT)",
            "INSERT INTO BidPages VALUES (20, 1, '{OLD-PAGE}', 'Page')",
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
            "INSERT INTO BidPageFolders VALUES (30, 1, 'Root', NULL)",
            "INSERT INTO BidPageFolders VALUES (31, 1, 'Child', 30)",
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidLayers VALUES (40, 1, 'Layer')",
            *extra,
        )

    def test_a_duplicated_bid_gets_fresh_identity_numbers_and_remapped_children(self):
        conn = self._db()
        ops = RealContractOps(conn)
        self.assertEqual(ops.duplicate_bid("x.mdb", "1"), "2")
        self.assertEqual(ops.skips, [])
        row = conn.execute(
            "SELECT UID, GUID, BidNo, JobName, CopyFromBidNO, CopyTimeStamp, "
            "CreateDateTime, ModDateTime, CoverSheetSelItemType FROM Bids WHERE UID = 2"
        ).fetchone()
        self.assertEqual((row[0], row[2], row[3], row[4], row[8]), (2, 5, "Source", 3, 1))
        self.assertRegex(row[1], r"^\{[0-9A-F-]{36}\}$")
        self.assertNotEqual(row[1], "{OLD-BID}")
        self.assertEqual(row[5], row[6])
        self.assertEqual(row[6], row[7])
        self.assertIsNotNone(row[5])
        self.assertEqual(
            conn.execute("SELECT GUID, BidNo FROM Bids WHERE UID = 1").fetchone(),
            ("{OLD-BID}", 3),
        )
        self.assertEqual(_rows(conn, "SELECT NextBidNo FROM Settings"), [(6,)])
        new_page = conn.execute(
            "SELECT UID, GUID, Name FROM BidPages WHERE BidUID = 2"
        ).fetchone()
        self.assertEqual((new_page[0], new_page[2]), (21, "Page"))
        self.assertRegex(new_page[1], r"^\{[0-9A-F-]{36}\}$")
        self.assertNotEqual(new_page[1], "{OLD-PAGE}")
        self.assertEqual(
            conn.execute("SELECT GUID FROM BidPages WHERE UID = 20").fetchone(),
            ("{OLD-PAGE}",),
        )
        self.assertEqual(
            _rows(conn, "SELECT BidPageSelectedUID FROM BidSettings WHERE BidUID = 2"),
            [(21,)],
        )
        self.assertEqual(
            _rows(conn, "SELECT CoverSheetSelItemUID FROM Bids WHERE UID = 2"), [(21,)]
        )
        folders = {
            name: (uid, parent)
            for uid, name, parent in _rows(
                conn, "SELECT UID, Name, ParentUID FROM BidPageFolders WHERE BidUID = 2"
            )
        }
        self.assertEqual(set(folders), {"Root", "Child"})
        self.assertIsNone(folders["Root"][1])
        self.assertEqual(folders["Child"][1], folders["Root"][0])
        self.assertNotIn(folders["Root"][0], (30, 31))
        self.assertEqual(
            _rows(conn, "SELECT Name FROM BidLayers WHERE BidUID = 2"), [("Layer",)]
        )

    def test_a_bid_with_two_settings_rows_cannot_be_duplicated(self):
        conn = self._db("INSERT INTO BidSettings VALUES (2, 1, 20)")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(RealContractOps(conn).duplicate_bid("x.mdb", "1"))
        self.assertIn(
            "BidSettings has multiple rows for Bids.UID=1",
            str(logs.records[0].exc_info[1]),
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM Bids"), [(1,)])

    def test_a_settings_table_without_a_bid_column_blocks_duplication(self):
        conn = self._db()
        conn.execute("ALTER TABLE BidSettings DROP COLUMN BidUID")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(RealContractOps(conn).duplicate_bid("x.mdb", "1"))
        self.assertIn("Missing BidSettings.BidUID", str(logs.records[0].exc_info[1]))

    def test_duplication_needs_the_bid_and_page_uid_columns(self):
        for table, dropped in (("Bids", "UID"), ("BidPages", "BidUID")):
            with self.subTest(table=table, missing=dropped):
                conn = self._db()
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {dropped}")
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIsNone(RealContractOps(conn).duplicate_bid("x.mdb", "1"))
                self.assertIn("Failed to duplicate bid 1", logs.records[0].getMessage())
                self.assertIn(dropped, str(logs.records[0].exc_info[1]))

    def test_the_global_settings_table_sql_is_the_bracketed_settings_table(self):
        self.assertEqual(BidOperationsMixin._global_settings_read_table_sql(), "[Settings]")
        self.assertEqual(BidOperationsMixin._global_settings_write_table_sql(), "[Settings]")


class BidDeletePageChildTableTests(unittest.TestCase):
    def test_page_children_are_deleted_through_their_page_or_their_bid_column(self):
        table = PAGE_DELETE_CHILD_TABLES[0]
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "INSERT INTO BidPages VALUES (20, 2)",
            f"CREATE TABLE {table} (UID INTEGER, BidPageUID INTEGER)",
            f"INSERT INTO {table} VALUES (1, 10)",
            f"INSERT INTO {table} VALUES (2, 20)",
        )
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, f"SELECT UID FROM {table}"), [(2,)])
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            f"CREATE TABLE {table} (UID INTEGER, BidUID INTEGER)",
            f"INSERT INTO {table} VALUES (1, 1)",
            f"INSERT INTO {table} VALUES (2, 2)",
        )
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, f"SELECT UID FROM {table}"), [(2,)])

    def test_a_child_table_without_either_scope_column_is_left_alone(self):
        table = PAGE_DELETE_CHILD_TABLES[0]
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            f"CREATE TABLE {table} (UID INTEGER)",
            f"INSERT INTO {table} VALUES (1)",
        )
        with self.assertNoLogs("test", "ERROR"):
            self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, f"SELECT UID FROM {table}"), [(1,)])


class _QueryLoggingCursor(_SqliteCursorWrapper):
    def __init__(self, connection, queries):
        super().__init__(connection)
        self._queries = queries

    def execute(self, query, *params):
        self._queries.append(" ".join(query.split()))
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        return super().execute(query, *params)


class _QueryLoggingConnection(_SqliteConnectionWrapper):
    def __init__(self, connection, queries):
        super().__init__(connection)
        self._queries = queries

    def cursor(self):
        return _QueryLoggingCursor(self._connection, self._queries)


class _LoggedContractOps(RealContractOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.queries = []

    def _connection(self, _db_path):
        return _QueryLoggingConnection(self._connection_ref, self.queries)


class CreateBidDefaultsAndFoldersTests(unittest.TestCase):
    _BIDS = (
        "CREATE TABLE Bids (UID INTEGER, GUID TEXT, BidNo INTEGER, JobName TEXT, "
        "MeasureBase INTEGER, TakeoffIncrements REAL, ScaleStyle INTEGER, "
        "ScaleFactor1 REAL, ScaleFactor2 REAL, PageWidth REAL, PageHeight REAL)"
    )

    def test_an_empty_settings_table_gives_bid_number_one_and_built_in_defaults(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER, ScaleStyle INTEGER)",
            self._BIDS,
        )
        self.assertEqual(RealContractOps(conn).create_bid("x.mdb", None, {}), "1")
        self.assertEqual(
            _rows(
                conn,
                "SELECT BidNo, MeasureBase, TakeoffIncrements, ScaleStyle, ScaleFactor1, "
                "ScaleFactor2, PageWidth, PageHeight FROM Bids",
            ),
            [(1, 0, 1.0, 1, 0.125, 12.0, 42.0, 30.0)],
        )
        self.assertEqual(_rows(conn, "SELECT NextBidNo FROM Settings"), [(2,)])

    def test_a_settings_table_with_two_rows_cannot_allocate_bid_numbers(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (4)",
            "INSERT INTO Settings VALUES (5)",
            self._BIDS,
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(RealContractOps(conn).create_bid("x.mdb", None, {}))
        self.assertIn("Settings has multiple rows", str(logs.records[0].exc_info[1]))
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM Bids"), [(0,)])

    def test_the_bid_number_is_read_with_the_exact_global_settings_sql(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (4)",
            self._BIDS,
            "INSERT INTO Bids VALUES (1, '{G}', 4, 'Src', 0, 1.0, 1, 1.0, 1.0, 1.0, 1.0)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        )
        ops = _LoggedContractOps(conn)
        self.assertEqual(ops.duplicate_bid("x.mdb", "1"), "2")
        self.assertIn("SELECT [NextBidNo] FROM [Settings]", ops.queries)
        self.assertIn("UPDATE [Settings] SET [NextBidNo] = ?", ops.queries)

    def test_template_layers_are_only_copied_when_the_layer_table_marks_templates(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            self._BIDS,
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidLayers VALUES (1, NULL, 'Not a template')",
        )
        self.assertEqual(RealContractOps(conn).create_bid("x.mdb", None, {}), "1")
        self.assertEqual(_rows(conn, "SELECT UID FROM BidLayers"), [(1,)])

    def test_template_layers_without_optional_columns_copy_with_documented_defaults(
        self,
    ):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            self._BIDS,
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, IsTemplate INTEGER)",
            "INSERT INTO BidLayers VALUES (1, NULL, 'First', -1)",
            "INSERT INTO BidLayers VALUES (2, NULL, 'Second', -1)",
        )
        ops = RealContractOps(conn)
        self.assertEqual(ops.create_bid("x.mdb", None, {}), "1")
        self.assertEqual(
            _rows(conn, "SELECT Name, BidUID, IsTemplate FROM BidLayers WHERE UID > 2"),
            [("First", 1, 0), ("Second", 1, 0)],
        )

    def test_template_layer_visibility_and_lock_flags_are_normalized(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            self._BIDS,
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER, "
            "IsLocked INTEGER, Sequence INTEGER, IsTemplate INTEGER)",
            "INSERT INTO BidLayers VALUES (1, NULL, 'On', 1, 1, 0, -1)",
            "INSERT INTO BidLayers VALUES (2, NULL, 'MinusOne', -1, -1, 0, -1)",
            "INSERT INTO BidLayers VALUES (3, NULL, 'Two', 2, 2, 0, -1)",
            "INSERT INTO BidLayers VALUES (4, NULL, 'Null', NULL, NULL, NULL, -1)",
        )
        RealContractOps(conn).create_bid("x.mdb", None, {})
        self.assertEqual(
            _rows(
                conn,
                "SELECT Name, Show, IsLocked, Sequence FROM BidLayers WHERE UID > 4 ORDER BY UID",
            ),
            [("On", -1, -1, 0), ("MinusOne", -1, -1, 0), ("Two", 0, 0, 0), ("Null", 0, 0, 3)],
        )

    def _folder_db(self):
        return contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            self._BIDS,
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
        )

    def test_blank_zero_and_missing_folder_parents_all_mean_a_root_folder(self):
        for parent in (None, "", 0, "0"):
            with self.subTest(parent=parent):
                conn = self._folder_db()
                folder = {"local_uid": "a", "name": "A"}
                if parent is not None:
                    folder["parent_uid"] = parent
                self.assertEqual(
                    RealContractOps(conn).create_bid(
                        "x.mdb", None, {"new_folders": [folder]}
                    ),
                    "1",
                )
                # A string "0" is stored as the numeric 0 (the int 0 and the
                # blank spellings as NULL); both spell "root" to the readers.
                (stored,) = _rows(conn, "SELECT ParentUID FROM BidPageFolders")
                self.assertIn(stored[0], (None, 0))

    def test_a_folder_hierarchy_is_created_parents_first_and_linked_by_new_uids(self):
        conn = self._folder_db()
        RealContractOps(conn).create_bid(
            "x.mdb",
            None,
            {
                "new_folders": [
                    {"local_uid": "c", "name": "C", "parent_uid": "b"},
                    {"local_uid": "b", "name": "B", "parent_uid": "a"},
                    {"local_uid": "a", "name": "A"},
                ]
            },
        )
        rows = {n: (u, p) for u, n, p in _rows(conn, "SELECT UID, Name, ParentUID FROM BidPageFolders")}
        self.assertIsNone(rows["A"][1])
        self.assertEqual(rows["B"][1], rows["A"][0])
        self.assertEqual(rows["C"][1], rows["B"][0])

    def test_a_cyclic_new_folder_hierarchy_is_rejected_without_writing(self):
        conn = self._folder_db()
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(
                RealContractOps(conn).create_bid(
                    "x.mdb",
                    None,
                    {
                        "new_folders": [
                            {"local_uid": "a", "name": "A", "parent_uid": "b"},
                            {"local_uid": "b", "name": "B", "parent_uid": "a"},
                        ]
                    },
                )
            )
        self.assertIn(
            "BidPageFolders.UID=a participates in a ParentUID cycle",
            str(logs.records[0].exc_info[1]),
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM Bids"), [(0,)])
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidPageFolders"), [(0,)])

    def test_new_pages_get_braced_uppercase_guids(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            self._BIDS,
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, GUID TEXT, Width REAL, Height REAL)",
        )
        RealContractOps(conn).create_bid(
            "x.mdb", None, {"pages": [{"width": 1.0, "height": 1.0}] * 2}
        )
        guids = [g for (g,) in _rows(conn, "SELECT GUID FROM BidPages")]
        self.assertEqual(len(set(guids)), 2)
        for guid in guids:
            self.assertRegex(guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        bid_guid = conn.execute("SELECT GUID FROM Bids").fetchone()[0]
        self.assertRegex(bid_guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertNotIn(bid_guid, guids)

    def test_a_schema_without_the_cover_selection_column_still_creates_the_bid(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            self._BIDS,
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Width REAL, Height REAL)",
        )
        ops = RealContractOps(conn)
        self.assertEqual(
            ops.create_bid("x.mdb", None, {"pages": [{"width": 1.0, "height": 1.0}]}),
            "1",
        )
        self.assertIn(
            ("Bids", "CoverSheetSelItemUID", "create_bid_cover_sheet_selection"),
            ops.skips,
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidPages"), [(1,)])


class _BlobTypedCursor(_SqliteCursorWrapper):
    """Reports bytearray type codes for BLOB columns, like pyodbc over Access."""

    BLOB_COLUMNS = frozenset({"Notes", "Position", "ExtraBlob"})

    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        return super().execute(query, *params)

    @property
    def description(self):
        base = super().description
        if base is None:
            return None
        return tuple(
            (
                column[0],
                bytearray if column[0] in self.BLOB_COLUMNS else str,
                *column[2:],
            )
            for column in base
        )


class _BlobTypedConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return _BlobTypedCursor(self._connection)


class _BlobTypedOps(RealContractOps):
    def _connection(self, _db_path):
        return _BlobTypedConnection(self._connection_ref)


_RICH_DDL = (
    "CREATE TABLE Settings (NextBidNo INTEGER)",
    "INSERT INTO Settings VALUES (5)",
    "CREATE TABLE Bids (UID INTEGER, GUID TEXT, BidNo INTEGER, JobName TEXT, "
    "CopyFromBidNO INTEGER, CopyTimeStamp TEXT, CreateDateTime TEXT, ModDateTime TEXT, "
    "CoverSheetSelItemType INTEGER, CoverSheetSelItemUID INTEGER)",
    "INSERT INTO Bids VALUES (1, '{SRC}', 3, 'Source', NULL, NULL, NULL, NULL, 1, 101)",
    "INSERT INTO Bids VALUES (2, '{OTHER}', 4, 'Other', NULL, NULL, NULL, NULL, 0, NULL)",
    "CREATE TABLE BidPlanRooms (UID INTEGER, BidUID INTEGER, Name TEXT, GUID TEXT, Notes BLOB)",
    "INSERT INTO BidPlanRooms VALUES (10, 1, 'Room', '{ROOM}', 'room-note')",
    "INSERT INTO BidPlanRooms VALUES (11, 2, 'Foreign room', '{FROOM}', 'x')",
    "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER, GUID TEXT)",
    "INSERT INTO BidAreas VALUES (30, 1, 'Root area', NULL, '{A30}')",
    "INSERT INTO BidAreas VALUES (31, 1, 'Child area', 30, '{A31}')",
    "INSERT INTO BidAreas VALUES (32, 2, 'Foreign area', NULL, '{A32}')",
    "CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER, Name TEXT)",
    "INSERT INTO BidTypAreas VALUES (40, 1, 'Typical')",
    "INSERT INTO BidTypAreas VALUES (41, 2, 'Foreign typical')",
    "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID INTEGER, ExtraBlob BLOB)",
    "INSERT INTO BidTypAreaCounts VALUES (50, 30, 40, 'blob50')",
    "INSERT INTO BidTypAreaCounts VALUES (51, 31, NULL, 'blob51')",
    "INSERT INTO BidTypAreaCounts VALUES (52, 32, 41, 'blob52')",
    "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
    "INSERT INTO BidConditionFolders VALUES (60, 1, 'Cond root', NULL)",
    "INSERT INTO BidConditionFolders VALUES (61, 1, 'Cond child', 60)",
    "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
    "INSERT INTO BidPageFolders VALUES (70, 1, 'Page root', NULL)",
    "INSERT INTO BidPageFolders VALUES (71, 1, 'Page child', 70)",
    "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID INTEGER)",
    "INSERT INTO BidSettings VALUES (1, 1, 101)",
    "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)",
    "INSERT INTO BidLayers VALUES (80, 1, 'Layer')",
    "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, BidLayerUID INTEGER, "
    "BidConditionFolderUID INTEGER, Notes BLOB, GUID TEXT)",
    "INSERT INTO BidConditions VALUES (90, 1, 'Cond', 80, 61, 'memo', '{C90}')",
    "CREATE TABLE BidZones (UID INTEGER, BidUID INTEGER, Name TEXT)",
    "INSERT INTO BidZones VALUES (95, 1, 'Zone')",
    "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, GUID TEXT, Name TEXT, "
    "BidPageFolderUID INTEGER, MasterPageUID INTEGER)",
    "INSERT INTO BidPages VALUES (100, 1, '{P100}', 'Page one', 71, NULL)",
    "INSERT INTO BidPages VALUES (101, 1, '{P101}', 'Page two', 70, 100)",
    "INSERT INTO BidPages VALUES (200, 2, '{P200}', 'Foreign page', NULL, NULL)",
    "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
    "BidConditionUID INTEGER, BidAreaUID INTEGER, ParentUID INTEGER, Position BLOB, Tag TEXT)",
    "INSERT INTO BidTakeoffs VALUES (110, 1, 100, 90, 31, NULL, 'pos', 'a')",
    "INSERT INTO BidTakeoffs VALUES (111, 1, 100, 90, 0, 110, 'pos2', 'b')",
    "INSERT INTO BidTakeoffs VALUES (112, 2, 200, 999, 0, NULL, 'x', 'foreign')",
    "CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, Name TEXT)",
    "INSERT INTO BidNamedViews VALUES (120, 1, 100, 'View')",
    "CREATE TABLE BidHotLinks (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
    "BidPageViewUID INTEGER, BidLayerUID INTEGER)",
    "INSERT INTO BidHotLinks VALUES (130, 1, 100, 120, 80)",
    "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER, BidAreaUID INTEGER, "
    "BidTypAreaUID INTEGER, BidAreaSelected INTEGER)",
    "INSERT INTO BidPageSettings VALUES (140, 100, 30, NULL, 1)",
    "INSERT INTO BidPageSettings VALUES (141, 100, 31, 40, 0)",
    "INSERT INTO BidPageSettings VALUES (142, 100, 31, NULL, 2)",
    "CREATE TABLE BidAreaTranslations (UID INTEGER, BidPageUID INTEGER, MasterAreaUID INTEGER, "
    "TranslateAreaUID INTEGER)",
    "INSERT INTO BidAreaTranslations VALUES (150, 100, 30, 31)",
    "CREATE TABLE BidLegends (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, FontName TEXT, GUID TEXT)",
    "INSERT INTO BidLegends VALUES (160, 1, 101, 'Arial', '{L160}')",
)


class DuplicateBidRelationshipFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = contract_db(*_RICH_DDL)
        cls.ops = _BlobTypedOps(cls.conn)
        cls.new_uid = cls.ops.duplicate_bid("x.mdb", "1")

    def rows(self, sql, *params):
        return self.conn.execute(sql, params).fetchall()

    def by_name(self, table, columns="UID"):
        return {
            r[0]: r[1:]
            for r in self.rows(
                f"SELECT Name, {columns} FROM {table} WHERE BidUID = ?", int(self.new_uid)
            )
        }

    def uid_of(self, table, name):
        return self.by_name(table)[name][0]

    def test_the_duplicate_gets_the_next_bid_uid_and_the_source_is_untouched(self):
        self.assertEqual(self.new_uid, "3")
        self.assertEqual(self.rows("SELECT COUNT(*) FROM Bids"), [(3,)])
        self.assertEqual(
            self.rows("SELECT GUID, JobName FROM Bids WHERE UID = 1"), [("{SRC}", "Source")]
        )
        self.assertEqual(self.rows("SELECT NextBidNo FROM Settings"), [(6,)])
        self.assertEqual(self.ops.skips, [])

    def test_generic_tables_are_copied_with_a_new_bid_a_new_uid_and_a_new_guid(self):
        (room,) = self.rows("SELECT UID, GUID FROM BidPlanRooms WHERE BidUID = 3")
        self.assertNotIn(room[0], (10, 11))
        self.assertEqual(self.rows("SELECT Notes FROM BidPlanRooms WHERE BidUID = 3"), [(b"room-note",)])
        self.assertRegex(room[1], r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertEqual(
            self.rows("SELECT GUID FROM BidPlanRooms WHERE UID IN (10, 11) ORDER BY UID"),
            [("{ROOM}",), ("{FROOM}",)],
        )
        self.assertEqual(self.rows("SELECT Name FROM BidZones WHERE BidUID = 3"), [("Zone",)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM BidPlanRooms"), [(3,)])
        for table, expected in (
            ("BidSettings", 1), ("BidLayers", 1), ("BidConditions", 1), ("BidAreas", 2),
            ("BidTypAreas", 1), ("BidPageFolders", 2), ("BidConditionFolders", 2),
            ("BidPages", 2), ("BidTakeoffs", 2), ("BidNamedViews", 1), ("BidHotLinks", 1),
        ):
            self.assertEqual(
                self.rows(f"SELECT COUNT(*) FROM {table} WHERE BidUID = 3"), [(expected,)], table
            )

    def test_areas_copy_with_remapped_parents_and_fresh_guids(self):
        areas = self.by_name("BidAreas", "UID, ParentUID, GUID")
        self.assertEqual(set(areas), {"Root area", "Child area"})
        self.assertIsNone(areas["Root area"][1])
        self.assertEqual(areas["Child area"][1], areas["Root area"][0])
        self.assertNotIn(areas["Root area"][0], (30, 31, 32))
        for _uid, _parent, guid in areas.values():
            self.assertRegex(guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertEqual(self.rows("SELECT COUNT(*) FROM BidAreas"), [(5,)])

    def test_typical_areas_and_their_counts_follow_the_copied_areas(self):
        typical = self.uid_of("BidTypAreas", "Typical")
        self.assertNotIn(typical, (40, 41))
        areas = self.by_name("BidAreas")
        new_area_uids = {areas["Root area"][0], areas["Child area"][0]}
        counts = self.rows(
            "SELECT BidAreaUID, BidTypAreaUID FROM BidTypAreaCounts "
            "WHERE BidAreaUID IN (?, ?)",
            *new_area_uids,
        )
        self.assertEqual(
            sorted(counts, key=lambda r: r[0]),
            sorted(
                [(areas["Root area"][0], typical), (areas["Child area"][0], None)],
                key=lambda r: r[0],
            ),
        )
        self.assertEqual(self.rows("SELECT COUNT(*) FROM BidTypAreaCounts"), [(5,)])
        self.assertEqual(self.rows("SELECT COUNT(DISTINCT UID) FROM BidTypAreaCounts"), [(5,)])
        self.assertEqual(
            sorted(r[0] for r in self.rows(
                "SELECT ExtraBlob FROM BidTypAreaCounts WHERE UID > 52"
            )),
            [b"blob50", b"blob51"],
        )
        self.assertEqual(
            self.rows("SELECT BidAreaUID, BidTypAreaUID FROM BidTypAreaCounts WHERE UID = 52"),
            [(32, 41)],
        )

    def test_folders_copy_with_remapped_parents(self):
        for table, root, child in (
            ("BidConditionFolders", "Cond root", "Cond child"),
            ("BidPageFolders", "Page root", "Page child"),
        ):
            with self.subTest(table=table):
                rows = self.by_name(table, "UID, ParentUID")
                self.assertEqual(
                    self.rows(f"SELECT COUNT(*) FROM {table} WHERE BidUID = 3"), [(2,)]
                )
                self.assertIsNone(rows[root][1])
                self.assertEqual(rows[child][1], rows[root][0])
                self.assertNotIn(rows[root][0], (60, 61, 70, 71))

    def test_conditions_copy_with_remapped_layer_and_folder_and_binary_notes(self):
        cond = self.by_name("BidConditions", "UID, BidLayerUID, BidConditionFolderUID, Notes, GUID")["Cond"]
        self.assertEqual(cond[1], self.uid_of("BidLayers", "Layer"))
        self.assertEqual(cond[2], self.uid_of("BidConditionFolders", "Cond child"))
        self.assertEqual(cond[3], b"memo")
        self.assertIsInstance(cond[3], bytes)
        self.assertRegex(cond[4], r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertEqual(
            self.rows("SELECT Notes, GUID FROM BidConditions WHERE UID = 90"),
            [("memo", "{C90}")],
        )

    def test_pages_copy_with_remapped_folder_master_page_and_fresh_guid(self):
        pages = self.by_name("BidPages", "UID, BidPageFolderUID, MasterPageUID, GUID")
        self.assertEqual(set(pages), {"Page one", "Page two"})
        self.assertEqual(pages["Page one"][1], self.uid_of("BidPageFolders", "Page child"))
        self.assertEqual(pages["Page two"][1], self.uid_of("BidPageFolders", "Page root"))
        self.assertIsNone(pages["Page one"][2])
        self.assertEqual(pages["Page two"][2], pages["Page one"][0])
        self.assertNotEqual(pages["Page one"][3], "{P100}")
        self.assertEqual(
            self.rows("SELECT GUID, BidPageFolderUID FROM BidPages WHERE UID = 100"),
            [("{P100}", 71)],
        )

    def test_takeoffs_copy_with_remapped_owners_parents_and_binary_positions(self):
        pages = self.by_name("BidPages")
        areas = self.by_name("BidAreas")
        condition = self.uid_of("BidConditions", "Cond")
        rows = self.rows(
            "SELECT UID, BidPageUID, BidConditionUID, BidAreaUID, ParentUID, Position, Tag "
            "FROM BidTakeoffs WHERE BidUID = 3 ORDER BY Tag"
        )
        self.assertEqual(len(rows), 2)
        first, second = rows
        self.assertEqual(first[1:4], (pages["Page one"][0], condition, areas["Child area"][0]))
        self.assertIsNone(first[4])
        self.assertEqual(first[5:], (b"pos", "a"))
        self.assertEqual(second[1:3], (pages["Page one"][0], condition))
        self.assertEqual(second[3], 0)
        self.assertEqual(second[4], first[0])
        self.assertEqual(second[5:], (b"pos2", "b"))
        self.assertEqual(
            self.rows("SELECT BidConditionUID, ParentUID FROM BidTakeoffs WHERE UID IN (110, 111, 112) ORDER BY UID"),
            [(90, None), (90, 110), (999, None)],
        )

    def test_named_views_and_hot_links_follow_their_copied_targets(self):
        page = self.uid_of("BidPages", "Page one")
        view = self.uid_of("BidNamedViews", "View")
        self.assertEqual(
            self.rows("SELECT BidPageUID FROM BidNamedViews WHERE BidUID = 3"), [(page,)]
        )
        self.assertEqual(
            self.rows(
                "SELECT BidPageUID, BidPageViewUID, BidLayerUID FROM BidHotLinks WHERE BidUID = 3"
            ),
            [(page, view, self.uid_of("BidLayers", "Layer"))],
        )
        self.assertEqual(
            self.rows("SELECT BidPageUID, BidPageViewUID, BidLayerUID FROM BidHotLinks WHERE UID = 130"),
            [(100, 120, 80)],
        )

    def test_page_settings_keep_the_inactive_rows_and_the_strongest_selected_row(self):
        page = self.uid_of("BidPages", "Page one")
        areas = self.by_name("BidAreas")
        typical = self.uid_of("BidTypAreas", "Typical")
        rows = self.rows(
            "SELECT BidAreaUID, BidTypAreaUID, BidAreaSelected FROM BidPageSettings "
            "WHERE BidPageUID = ? ORDER BY BidAreaSelected",
            page,
        )
        self.assertEqual(
            rows,
            [
                (areas["Child area"][0], typical, 0),
                (areas["Child area"][0], None, 2),
            ],
        )
        self.assertEqual(self.rows("SELECT COUNT(*) FROM BidPageSettings"), [(5,)])

    def test_area_translations_without_a_bid_column_follow_the_copied_page_and_areas(self):
        page = self.uid_of("BidPages", "Page one")
        areas = self.by_name("BidAreas")
        self.assertEqual(
            self.rows(
                "SELECT MasterAreaUID, TranslateAreaUID FROM BidAreaTranslations WHERE BidPageUID = ?",
                page,
            ),
            [(areas["Root area"][0], areas["Child area"][0])],
        )
        self.assertEqual(
            self.rows("SELECT MasterAreaUID, TranslateAreaUID FROM BidAreaTranslations WHERE UID = 150"),
            [(30, 31)],
        )

    def test_page_owned_legends_and_settings_follow_the_copied_pages(self):
        page_two = self.uid_of("BidPages", "Page two")
        self.assertEqual(
            self.rows("SELECT BidPageUID, FontName FROM BidLegends WHERE BidUID = 3"),
            [(page_two, "Arial")],
        )
        (guid,) = self.rows("SELECT GUID FROM BidLegends WHERE BidUID = 3")[0]
        self.assertRegex(guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertEqual(self.rows("SELECT GUID FROM BidLegends WHERE UID = 160"), [("{L160}",)])
        self.assertEqual(
            self.rows("SELECT BidPageSelectedUID FROM BidSettings WHERE BidUID = 3"), [(page_two,)]
        )
        self.assertEqual(
            self.rows("SELECT CoverSheetSelItemUID FROM Bids WHERE UID = 3"), [(page_two,)]
        )
        self.assertEqual(
            self.rows("SELECT CoverSheetSelItemUID FROM Bids WHERE UID = 1"), [(101,)]
        )


class DuplicateBidRelationshipGuardTests(unittest.TestCase):
    def _db(self, *extra):
        return contract_db(*_RICH_DDL, *extra)

    def _failure(self, conn):
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"))
        self.assertEqual(self._count(conn, "Bids"), 2)
        return str(logs.records[0].exc_info[1])

    @staticmethod
    def _count(conn, table):
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_a_dangling_direct_reference_blocks_the_duplicate_with_the_exact_message(self):
        conn = self._db("UPDATE BidConditions SET BidLayerUID = 999 WHERE UID = 90")
        self.assertEqual(
            self._failure(conn),
            "BidConditions.UID=90 references missing BidLayers.UID=999 through BidLayerUID.",
        )

    def test_a_zero_or_null_reference_is_not_dangling(self):
        conn = self._db(
            "UPDATE BidConditions SET BidLayerUID = 0, BidConditionFolderUID = NULL WHERE UID = 90"
        )
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")

    def test_a_dangling_area_count_typical_reference_blocks_the_duplicate(self):
        conn = self._db("UPDATE BidTypAreaCounts SET BidTypAreaUID = 999 WHERE UID = 50")
        self.assertEqual(
            self._failure(conn),
            "BidTypAreaCounts.UID=50 references missing BidTypAreas.UID=999 "
            "through BidTypAreaUID.",
        )

    def test_area_counts_of_a_foreign_area_are_not_validated(self):
        conn = self._db("UPDATE BidTypAreaCounts SET BidTypAreaUID = 999 WHERE UID = 52")
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")

    def test_a_duplicated_count_row_uid_blocks_the_duplicate(self):
        conn = self._db("INSERT INTO BidTypAreaCounts VALUES (50, 30, 40, 'dup')")
        message = self._failure(conn)
        self.assertIn("BidTypAreaCounts contains duplicate UID 50", message)

    def test_a_dangling_page_owned_reference_blocks_the_duplicate_with_the_exact_message(
        self,
    ):
        conn = self._db("UPDATE BidAreaTranslations SET MasterAreaUID = 999 WHERE UID = 150")
        self.assertEqual(
            self._failure(conn),
            "BidAreaTranslations.UID=150 references missing BidAreas.UID=999 "
            "through MasterAreaUID.",
        )

    def test_a_page_owned_row_without_a_uid_column_is_reported_as_unidentified(self):
        conn = self._db(
            "DROP TABLE BidAreaTranslations",
            "CREATE TABLE BidAreaTranslations (BidPageUID INTEGER, MasterAreaUID INTEGER, "
            "TranslateAreaUID INTEGER)",
            "INSERT INTO BidAreaTranslations VALUES (100, 999, 31)",
        )
        self.assertEqual(
            self._failure(conn),
            "BidAreaTranslations.UID=<unidentified-row> references missing BidAreas.UID=999 "
            "through MasterAreaUID.",
        )

    def test_cyclic_parent_graphs_block_the_duplicate_for_every_hierarchy(self):
        for table, ids in (
            ("BidAreas", (30, 31)),
            ("BidConditionFolders", (60, 61)),
            ("BidPageFolders", (70, 71)),
        ):
            with self.subTest(table=table):
                conn = self._db(f"UPDATE {table} SET ParentUID = {ids[1]} WHERE UID = {ids[0]}")
                self.assertIn("participates in a ParentUID cycle", self._failure(conn))
        conn = self._db("UPDATE BidTakeoffs SET ParentUID = 111 WHERE UID = 110")
        self.assertIn("participates in a ParentUID cycle", self._failure(conn))

    def test_a_page_selection_of_another_type_is_not_remapped(self):
        conn = self._db("UPDATE Bids SET CoverSheetSelItemType = 2, CoverSheetSelItemUID = 55 WHERE UID = 1")
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertEqual(
            conn.execute("SELECT CoverSheetSelItemType, CoverSheetSelItemUID FROM Bids WHERE UID = 3").fetchone(),
            (2, 55),
        )

    def test_a_page_selection_pointing_at_no_page_clears_the_copy(self):
        conn = self._db("UPDATE Bids SET CoverSheetSelItemUID = 777 WHERE UID = 1")
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertIsNone(
            conn.execute("SELECT CoverSheetSelItemUID FROM Bids WHERE UID = 3").fetchone()[0]
        )

    def test_a_missing_selection_uid_clears_the_copy_instead_of_selecting_a_page(self):
        conn = self._db("UPDATE Bids SET CoverSheetSelItemUID = NULL WHERE UID = 1")
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertIsNone(
            conn.execute("SELECT CoverSheetSelItemUID FROM Bids WHERE UID = 3").fetchone()[0]
        )

    def test_a_page_owned_row_of_another_bids_page_is_never_copied_or_validated(self):
        conn = self._db(
            "INSERT INTO BidPageSettings VALUES (145, 200, 999, NULL, 1)",
            "INSERT INTO BidLegends VALUES (161, 2, 200, 'Foreign', '{L161}')",
        )
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertEqual(self._count(conn, "BidLegends"), 3)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidPageSettings WHERE UID = 145").fetchone()[0], 1
        )

    def test_derived_total_rows_with_dangling_references_are_left_out_of_the_copy(self):
        conn = self._db(
            "CREATE TABLE BidTakeoffTotals (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)",
            "INSERT INTO BidTakeoffTotals VALUES (300, 1, 100)",
            "INSERT INTO BidTakeoffTotals VALUES (301, 1, 999)",
        )
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffTotals WHERE BidUID = 3").fetchone()[0], 1
        )


class _PyodbcBlobOps(_BlobTypedOps):
    """Typed BLOB descriptions plus Access-style pyodbc errors for failing statements."""

    def _connection(self, _db_path):
        return _PyodbcBlobConnection(self._connection_ref)


class _PyodbcBlobCursor(_BlobTypedCursor):
    def execute(self, query, *params):
        try:
            return super().execute(query, *params)
        except sqlite3.Error as exc:
            raise pyodbc.Error("23000", str(exc)) from exc


class _PyodbcBlobConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return _PyodbcBlobCursor(self._connection)


class _StrictPyodbcBlobOps(_PyodbcBlobOps):
    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


class _RecordingSchemaOps(RealContractOps):
    """RealContractOps whose connection records every executed statement."""

    def __init__(self, connection):
        super().__init__(connection)
        self.queries = []

    def _connection(self, _db_path):
        return _QueryLoggingConnection(self._connection_ref, self.queries)


def _copy_cursor(conn):
    return _SqliteCursorWrapper(conn)


class DuplicateHelperContractTests(unittest.TestCase):
    """Direct contracts of the duplicate_bid copy and remap helpers."""

    def _ops(self, conn):
        ops = _BlobTypedOps(conn)
        return ops, _BlobTypedCursor(conn), ops._schema_ref

    # ---- _copy_bid_table_rows
    def test_a_bid_copy_of_a_missing_table_or_a_table_without_the_scope_column_is_empty(self):
        conn = contract_db("CREATE TABLE NoScope (UID INTEGER, Name TEXT)")
        conn.execute("INSERT INTO NoScope VALUES (1, 'x')")
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_bid_table_rows(cursor, "Absent", "BidUID", "1", "2", schema=schema), {})
        self.assertEqual(ops._copy_bid_table_rows(cursor, "NoScope", "BidUID", "1", "2", schema=schema), {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM NoScope").fetchone(), (1,))

    def test_a_bid_copy_with_no_rows_or_only_excluded_rows_copies_nothing(self):
        conn = contract_db(
            "CREATE TABLE T (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO T VALUES (1, 5, 'a')",
        )
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_bid_table_rows(cursor, "T", "BidUID", "9", "7", schema=schema), {})
        self.assertEqual(
            ops._copy_bid_table_rows(
                cursor, "T", "BidUID", "5", "7", excluded_source_uids={"1"}, schema=schema
            ),
            {},
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM T").fetchone(), (1,))

    def test_a_bid_copy_assigns_new_uids_applies_overrides_and_encodes_binary_values(self):
        conn = contract_db(
            "CREATE TABLE T (UID INTEGER, BidUID INTEGER, Name TEXT, Notes BLOB, Other BLOB)",
            "INSERT INTO T VALUES (1, 5, 'a', 'memo', NULL)",
            "INSERT INTO T VALUES (2, 5, 'b', 'memo2', 'raw')",
            "INSERT INTO T VALUES (3, 6, 'c', 'x', NULL)",
        )
        ops, cursor, schema = self._ops(conn)
        uid_map = ops._copy_bid_table_rows(
            cursor, "T", "BidUID", "5", "7", extra_overrides={"Name": "over"}, schema=schema
        )
        self.assertEqual(set(uid_map), {"1", "2"})
        rows = conn.execute("SELECT UID, BidUID, Name, Notes, Other FROM T WHERE BidUID = 7 ORDER BY UID").fetchall()
        self.assertEqual([r[1:3] for r in rows], [(7, "over"), (7, "over")])
        self.assertEqual(rows[0][3], b"memo")
        self.assertIsNone(rows[0][4])
        self.assertEqual(rows[1][3], b"memo2")
        self.assertNotIn(rows[0][0], (1, 2, 3))
        self.assertEqual({str(r[0]) for r in rows}, set(uid_map.values()))
        self.assertEqual(conn.execute("SELECT COUNT(DISTINCT UID) FROM T").fetchone(), (5,))

    def test_a_bid_copy_without_a_uid_column_returns_no_uid_map(self):
        conn = contract_db(
            "CREATE TABLE T (BidUID INTEGER, Name TEXT)", "INSERT INTO T VALUES (5, 'a')"
        )
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_bid_table_rows(cursor, "T", "BidUID", "5", "7", schema=schema), {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM T WHERE BidUID = 7").fetchone(), (1,))

    def test_a_bid_copy_rejects_duplicate_source_uids_and_honours_the_error_policy(self):
        conn = contract_db(
            "CREATE TABLE T (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO T VALUES (1, 5)",
            "INSERT INTO T VALUES (1, 5)",
        )
        ops, cursor, schema = self._ops(conn)
        with self.assertRaisesRegex(RuntimeError, "T contains duplicate UID 1"):
            ops._copy_bid_table_rows(cursor, "T", "BidUID", "5", "7", schema=schema)

    def test_a_failing_bid_copy_insert_is_swallowed_unless_the_policy_is_strict(self):
        for ops_class, strict in ((_PyodbcBlobOps, False), (_StrictPyodbcBlobOps, True)):
            with self.subTest(strict=strict):
                conn = contract_db(
                    "CREATE TABLE T (UID INTEGER, BidUID INTEGER)",
                    "INSERT INTO T VALUES (1, 5)",
                    "CREATE TRIGGER block BEFORE INSERT ON T BEGIN SELECT RAISE(ABORT, 'x'); END",
                )
                ops = ops_class(conn)
                cursor = _PyodbcBlobCursor(conn)
                call = lambda: ops._copy_bid_table_rows(cursor, "T", "BidUID", "5", "7", schema=ops._schema_ref)
                if strict:
                    with self.assertRaises(pyodbc.Error):
                        call()
                else:
                    self.assertEqual(call(), {})

    # ---- _copy_with_uid_map / _remap_row_relationships
    def test_a_uid_map_copy_remaps_relationships_and_encodes_binary_values(self):
        conn = contract_db(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER, Notes BLOB, GUID TEXT)",
            "INSERT INTO BidConditions VALUES (1, 5, 80, 'memo', '{G}')",
        )
        ops, cursor, schema = self._ops(conn)
        uid_map = ops._copy_with_uid_map(
            cursor, "BidConditions", "BidUID", "5", "7", schema=schema,
            relationship_uid_maps={"BidLayers": {"80": "180"}},
        )
        self.assertEqual(list(uid_map), ["1"])
        row = conn.execute("SELECT BidLayerUID, Notes, GUID FROM BidConditions WHERE BidUID = 7").fetchone()
        self.assertEqual(row[:2], (180, b"memo"))
        self.assertNotEqual(row[2], "{G}")

    def test_a_uid_map_copy_of_a_missing_table_or_scope_column_is_empty(self):
        conn = contract_db("CREATE TABLE T (UID INTEGER)")
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_with_uid_map(cursor, "Absent", "BidUID", "5", "7", schema=schema), {})
        self.assertEqual(ops._copy_with_uid_map(cursor, "T", "BidUID", "5", "7", schema=schema), {})
        conn.execute("CREATE TABLE U (UID INTEGER, BidUID INTEGER)")
        self.assertEqual(ops._copy_with_uid_map(cursor, "U", "BidUID", "5", "7", schema=schema), {})

    def test_a_failing_uid_map_copy_is_swallowed_unless_the_policy_is_strict(self):
        for ops_class, strict in ((_PyodbcBlobOps, False), (_StrictPyodbcBlobOps, True)):
            with self.subTest(strict=strict):
                conn = contract_db(
                    "CREATE TABLE T (UID INTEGER, BidUID INTEGER)",
                    "INSERT INTO T VALUES (1, 5)",
                    "CREATE TRIGGER block BEFORE INSERT ON T BEGIN SELECT RAISE(ABORT, 'x'); END",
                )
                ops = ops_class(conn)
                cursor = _PyodbcBlobCursor(conn)
                call = lambda: ops._copy_with_uid_map(cursor, "T", "BidUID", "5", "7", schema=ops._schema_ref)
                if strict:
                    with self.assertRaises(pyodbc.Error):
                        call()
                else:
                    self.assertEqual(call(), {})

    def test_row_relationship_remapping_follows_only_matching_non_blank_integer_references(self):
        maps = {"BidLayers": {"80": "180"}, "BidConditionFolders": {"61": "161"}}
        remap = BidOperationsMixin._remap_row_relationships
        row = {"BidLayerUID": 80, "BidConditionFolderUID": "61", "Name": "x"}
        remap("BidConditions", row, maps)
        self.assertEqual((row["BidLayerUID"], row["BidConditionFolderUID"]), ("180", "161"))
        for blank in (None, "", 0, "0"):
            row = {"BidLayerUID": blank}
            remap("BidConditions", row, maps)
            self.assertEqual(row["BidLayerUID"], blank)
        row = {"BidLayerUID": "abc"}
        remap("BidConditions", row, maps)
        self.assertEqual(row["BidLayerUID"], "abc")
        row = {"BidLayerUID": 999}
        remap("BidConditions", row, maps)
        self.assertEqual(row["BidLayerUID"], 999)
        row = {"BidLayerUID": 80}
        remap("BidZones", row, {"BidLayers": {"80": "180"}})
        self.assertEqual(row["BidLayerUID"], "180")
        row = {"BidLayerUID": 80}
        remap("NotATable", row, maps)
        self.assertEqual(row["BidLayerUID"], 80)
        row = {"BidLayerUID": 80}
        remap("BidConditions", row, {"BidLayers": {}})
        self.assertEqual(row["BidLayerUID"], 80)
        row = {"BidLayerUID": 80}
        remap("BidConditions", row, {"BidAreas": {"80": "9"}})
        self.assertEqual(row["BidLayerUID"], 80)

    # ---- _copy_page_table_rows
    def _page_db(self):
        return contract_db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 5)",
            "INSERT INTO BidPages VALUES (20, 6)",
            "CREATE TABLE BidTexts (UID INTEGER, BidPageUID INTEGER, BidUID INTEGER, GUID TEXT, Name TEXT, Position BLOB)",
            "INSERT INTO BidTexts VALUES (1, 10, 5, '{T}', 'a', 'pos')",
            "INSERT INTO BidTexts VALUES (2, 20, 6, '{U}', 'b', 'pos')",
            "CREATE TABLE BidMarkedPages (BidPageUID INTEGER, Mark TEXT)",
            "INSERT INTO BidMarkedPages VALUES (10, 'm')",
        )

    def test_a_page_table_copy_follows_the_page_map_and_creates_fresh_identities(self):
        conn = self._page_db()
        ops, cursor, schema = self._ops(conn)
        uid_map = ops._copy_page_table_rows(cursor, schema, "BidTexts", "5", "7", {"10": "110"})
        self.assertEqual(list(uid_map), ["1"])
        row = conn.execute("SELECT UID, BidPageUID, BidUID, GUID, Name, Position FROM BidTexts WHERE BidPageUID = 110").fetchone()
        self.assertEqual((row[1], row[2], row[4], row[5]), (110, 7, "a", b"pos"))
        self.assertNotEqual(row[0], 1)
        self.assertRegex(row[3], r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertEqual(conn.execute("SELECT GUID FROM BidTexts WHERE UID = 1").fetchone(), ("{T}",))

    def test_a_page_table_copy_without_a_uid_column_returns_no_map_but_copies_rows(self):
        conn = self._page_db()
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_page_table_rows(cursor, schema, "BidMarkedPages", "5", "7", {"10": "110"}), {})
        self.assertEqual(conn.execute("SELECT BidPageUID FROM BidMarkedPages ORDER BY BidPageUID").fetchall(), [(10,), (110,)])

    def test_a_page_table_copy_of_a_missing_table_or_without_the_page_column_is_empty(self):
        conn = self._page_db()
        conn.execute("CREATE TABLE Loose (UID INTEGER)")
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_page_table_rows(cursor, schema, "Absent", "5", "7", {}), {})
        self.assertEqual(ops._copy_page_table_rows(cursor, schema, "Loose", "5", "7", {}), {})

    def test_a_page_table_copy_rejects_rows_of_unmapped_pages_duplicates_and_honours_policy(self):
        conn = self._page_db()
        ops, cursor, schema = self._ops(conn)
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            r"^BidTexts references unavailable source BidPages\.UID=10\.$",
        ):
            ops._copy_page_table_rows(cursor, schema, "BidTexts", "5", "7", {})
        conn.execute("INSERT INTO BidTexts VALUES (1, 10, 5, '{D}', 'dup', 'p')")
        with self.assertRaisesRegex(RuntimeError, "BidTexts contains duplicate UID 1"):
            ops._copy_page_table_rows(cursor, schema, "BidTexts", "5", "7", {"10": "110"})
        for ops_class, strict in ((_PyodbcBlobOps, False), (_StrictPyodbcBlobOps, True)):
            with self.subTest(strict=strict):
                conn = self._page_db()
                conn.execute("CREATE TRIGGER block BEFORE INSERT ON BidTexts BEGIN SELECT RAISE(ABORT, 'x'); END")
                ops = ops_class(conn)
                cursor = _PyodbcBlobCursor(conn)
                call = lambda: ops._copy_page_table_rows(cursor, ops._schema_ref, "BidTexts", "5", "7", {"10": "110"})
                if strict:
                    with self.assertRaises(pyodbc.Error):
                        call()
                else:
                    self.assertEqual(call(), {})

    # ---- _copy_area_count_rows
    def _count_db(self):
        return contract_db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (30, 5)",
            "INSERT INTO BidAreas VALUES (31, 6)",
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID, ExtraBlob BLOB)",
            "INSERT INTO BidTypAreaCounts VALUES (1, 30, 40, 'b1')",
            "INSERT INTO BidTypAreaCounts VALUES (2, 30, 0, 'b2')",
            "INSERT INTO BidTypAreaCounts VALUES (3, 30, '0', 'b3')",
            "INSERT INTO BidTypAreaCounts VALUES (4, 30, NULL, 'b4')",
            "INSERT INTO BidTypAreaCounts VALUES (5, 31, 40, 'foreign')",
        )

    def test_area_counts_follow_the_area_and_typical_maps_and_keep_blank_typicals(self):
        conn = self._count_db()
        ops, cursor, schema = self._ops(conn)
        uid_map = ops._copy_area_count_rows(cursor, schema, "5", {"30": "130"}, {"40": "140", "0": "999"})
        self.assertEqual(set(uid_map), {"1", "2", "3", "4"})
        rows = conn.execute(
            "SELECT BidAreaUID, BidTypAreaUID, ExtraBlob FROM BidTypAreaCounts WHERE UID > 5 ORDER BY ExtraBlob"
        ).fetchall()
        self.assertEqual(
            rows,
            [(130, "140", b"b1"), (130, 0, b"b2"), (130, "0", b"b3"), (130, None, b"b4")],
        )
        self.assertEqual(conn.execute("SELECT COUNT(DISTINCT UID) FROM BidTypAreaCounts").fetchone(), (9,))

    def test_area_counts_with_a_typical_that_has_no_copy_keep_the_source_reference(self):
        conn = self._count_db()
        ops, cursor, schema = self._ops(conn)
        ops._copy_area_count_rows(cursor, schema, "5", {"30": "130"}, {})
        copied = conn.execute(
            "SELECT BidTypAreaUID, ExtraBlob FROM BidTypAreaCounts WHERE UID > 5 ORDER BY ExtraBlob"
        ).fetchall()
        self.assertEqual(copied[0], (40, b"b1"))

    def test_area_counts_are_not_copied_without_areas_the_table_or_the_area_column(self):
        conn = self._count_db()
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_area_count_rows(cursor, schema, "5", {}, {}), {})
        self.assertEqual(ops._copy_area_count_rows(cursor, schema, "9", {"30": "130"}, {}), {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidTypAreaCounts").fetchone(), (5,))
        bare = contract_db("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        ops, cursor, schema = self._ops(bare)
        self.assertEqual(ops._copy_area_count_rows(cursor, schema, "5", {"30": "130"}, {}), {})
        bare.execute("CREATE TABLE BidTypAreaCounts (UID INTEGER, Other INTEGER)")
        self.assertEqual(ops._copy_area_count_rows(cursor, schema, "5", {"30": "130"}, {}), {})
        no_area_table = contract_db(
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER)"
        )
        ops, cursor, schema = self._ops(no_area_table)
        self.assertEqual(ops._copy_area_count_rows(cursor, schema, "5", {"30": "130"}, {}), {})

    def test_area_counts_without_a_uid_column_are_copied_with_no_uid_map(self):
        conn = contract_db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (30, 5)",
            "CREATE TABLE BidTypAreaCounts (BidAreaUID INTEGER, BidTypAreaUID INTEGER)",
            "INSERT INTO BidTypAreaCounts VALUES (30, 40)",
        )
        ops, cursor, schema = self._ops(conn)
        self.assertEqual(ops._copy_area_count_rows(cursor, schema, "5", {"30": "130"}, {"40": "140"}), {})
        self.assertEqual(
            conn.execute("SELECT BidAreaUID, BidTypAreaUID FROM BidTypAreaCounts ORDER BY BidAreaUID").fetchall(),
            [(30, 40), (130, 140)],
        )

    def test_area_counts_with_duplicate_uids_are_rejected(self):
        conn = self._count_db()
        conn.execute("INSERT INTO BidTypAreaCounts VALUES (1, 30, 40, 'dup')")
        ops, cursor, schema = self._ops(conn)
        with self.assertRaisesRegex(RuntimeError, "BidTypAreaCounts contains duplicate UID 1"):
            ops._copy_area_count_rows(cursor, schema, "5", {"30": "130"}, {})

    # ---- remap helpers
    def test_references_that_the_copy_left_on_source_rows_are_retargeted_without_uid_or_page_columns(
        self,
    ):
        conn = contract_db(
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER)",
            "INSERT INTO BidTypAreaCounts VALUES (150, 30)",
            "INSERT INTO BidTypAreaCounts VALUES (151, 31)",
            "INSERT INTO BidTypAreaCounts VALUES (152, 0)",
            "INSERT INTO BidTypAreaCounts VALUES (153, NULL)",
            "INSERT INTO BidTypAreaCounts VALUES (50, 30)",
        )
        ops, cursor, schema = self._ops(conn)
        ops._remap_duplicated_relationships(
            cursor,
            schema,
            {
                "BidAreas": {"30": "130"},
                "BidTypAreaCounts": {"50": "150", "51": "151", "52": "152", "53": "153"},
            },
            "7",
        )
        self.assertEqual(
            conn.execute("SELECT UID, BidAreaUID FROM BidTypAreaCounts ORDER BY UID").fetchall(),
            [(50, 30), (150, 130), (151, 31), (152, 0), (153, None)],
        )

    def test_relationships_without_maps_or_columns_are_skipped_by_the_remap(self):
        conn = contract_db("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, ParentUID INTEGER)",
                           "INSERT INTO BidAreas VALUES (130, 7, 30)")
        ops, cursor, schema = self._ops(conn)
        ops._remap_duplicated_relationships(cursor, schema, {}, "7")
        ops._remap_duplicated_relationships(cursor, schema, {"BidAreas": {}}, "7")
        self.assertEqual(conn.execute("SELECT ParentUID FROM BidAreas").fetchone(), (30,))
        ops._remap_duplicated_relationships(cursor, schema, {"BidAreas": {"30": "130"}}, "7")
        self.assertEqual(conn.execute("SELECT ParentUID FROM BidAreas").fetchone(), (130,))
        conn2 = contract_db("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
                            "INSERT INTO BidAreas VALUES (130, 7)")
        ops, cursor, schema = self._ops(conn2)
        ops._remap_duplicated_relationships(cursor, schema, {"BidAreas": {"30": "130"}}, "7")

    def test_child_references_ignore_null_zero_and_unrelated_rows_and_chunk_large_sets(self):
        conn = contract_db(
            "CREATE TABLE C (UID INTEGER, Ref INTEGER)",
            "INSERT INTO C VALUES (1, 30)",
            "INSERT INTO C VALUES (2, 0)",
            "INSERT INTO C VALUES (3, NULL)",
            "INSERT INTO C VALUES (4, 31)",
            "INSERT INTO C VALUES (9, 99)",
        )
        ops, cursor, _schema = self._ops(conn)
        self.assertEqual(
            ops._duplicated_child_references(cursor, "C", "Ref", ["1", "2", "3", "4", 1]),
            {"1": "30", "4": "31"},
        )
        big = [str(i) for i in range(1, 700)]
        conn.executemany("INSERT INTO C VALUES (?, ?)", [(1000 + i, 5) for i in range(700)])
        refs = ops._duplicated_child_references(cursor, "C", "Ref", [str(1000 + i) for i in range(700)])
        self.assertEqual(len(refs), 700)
        self.assertEqual(set(refs.values()), {"5"})
        self.assertEqual(ops._duplicated_child_references(cursor, "C", "Ref", []), {})
        del big

    def test_page_owned_relationship_updates_only_rows_of_pages_in_the_new_bid(self):
        conn = contract_db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (110, 7)",
            "INSERT INTO BidPages VALUES (210, 8)",
            "CREATE TABLE BidAreaTranslations (BidPageUID INTEGER, MasterAreaUID INTEGER)",
            "INSERT INTO BidAreaTranslations VALUES (110, 30)",
            "INSERT INTO BidAreaTranslations VALUES (210, 30)",
        )
        ops, cursor, schema = self._ops(conn)
        ops._update_page_owned_relationship(cursor, schema, "BidAreaTranslations", "MasterAreaUID", 130, 30, "7")
        self.assertEqual(
            conn.execute("SELECT BidPageUID, MasterAreaUID FROM BidAreaTranslations ORDER BY BidPageUID").fetchall(),
            [(110, 130), (210, 30)],
        )

    def test_remap_updates_report_each_missing_column_with_the_update_label(self):
        conn = contract_db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidAreaTranslations (BidPageUID INTEGER)",
            "CREATE TABLE Plain (UID INTEGER)",
        )
        ops, cursor, schema = self._ops(conn)
        ops._update_page_owned_relationship(cursor, schema, "BidAreaTranslations", "MasterAreaUID", 1, 2, "7")
        ops._update_page_owned_relationship(cursor, schema, "Absent", "MasterAreaUID", 1, 2, "7")
        ops._update_if_columns(cursor, schema, "Plain", "Ref", 1, ("UID", "Other"), (1, 2))
        ops._update_if_columns(cursor, schema, "Absent", "Ref", 1, ("UID",), (1,))
        self.assertEqual(
            ops.skips,
            [
                ("BidAreaTranslations", "MasterAreaUID", "update_BidAreaTranslations_MasterAreaUID"),
                ("Plain", "Ref", "update_Plain_Ref"),
                ("Plain", "Other", "update_Plain_Ref"),
            ],
        )

    def test_a_page_owned_update_needs_the_page_table_with_its_identity_columns(self):
        conn = contract_db(
            "CREATE TABLE BidPages (UID INTEGER)",
            "CREATE TABLE BidAreaTranslations (BidPageUID INTEGER, MasterAreaUID INTEGER)",
            "INSERT INTO BidAreaTranslations VALUES (110, 30)",
        )
        ops, cursor, schema = self._ops(conn)
        ops._update_page_owned_relationship(cursor, schema, "BidAreaTranslations", "MasterAreaUID", 130, 30, "7")
        self.assertEqual(conn.execute("SELECT MasterAreaUID FROM BidAreaTranslations").fetchone(), (30,))
        conn = contract_db(
            "CREATE TABLE BidAreaTranslations (BidPageUID INTEGER, MasterAreaUID INTEGER)",
            "INSERT INTO BidAreaTranslations VALUES (110, 30)",
        )
        ops, cursor, schema = self._ops(conn)
        ops._update_page_owned_relationship(cursor, schema, "BidAreaTranslations", "MasterAreaUID", 130, 30, "7")
        self.assertEqual(conn.execute("SELECT MasterAreaUID FROM BidAreaTranslations").fetchone(), (30,))

    # ---- preflight scope rules
    def test_area_count_validation_ignores_blank_spellings_and_needs_both_identity_tables(self):
        check = BidOperationsMixin._require_duplicable_indirect_area_counts
        conn = contract_db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (30, 5)",
            "CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID, BidTypAreaUID)",
        )
        for area, typical in (("", ""), (0, 0), ("0", "0"), (None, None), (30, ""), (30, 0), (30, "0"), (30, None)):
            conn.execute("DELETE FROM BidTypAreaCounts")
            conn.execute("INSERT INTO BidTypAreaCounts VALUES (1, ?, ?)", (area, typical))
            with self.subTest(area=area, typical=typical):
                ops, cursor, schema = self._ops(conn)
                check(cursor, schema, 5)
        conn.execute("DELETE FROM BidTypAreaCounts")
        conn.execute("INSERT INTO BidTypAreaCounts VALUES (1, 30, 99)")
        ops, cursor, schema = self._ops(conn)
        with self.assertRaisesRegex(DanglingBidOwnedReferenceError, r"BidTypAreas\.UID=99"):
            check(cursor, schema, 5)

    def test_area_count_validation_returns_quietly_when_a_required_column_is_absent(self):
        check = BidOperationsMixin._require_duplicable_indirect_area_counts
        for areas, typicals in (
            ("UID INTEGER, BidUID INTEGER", "UID INTEGER"),
            ("UID INTEGER", "UID INTEGER, BidUID INTEGER"),
        ):
            conn = contract_db(
                f"CREATE TABLE BidAreas ({areas})",
                f"CREATE TABLE BidTypAreas ({typicals})",
                "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID INTEGER)",
            )
            ops, cursor, schema = self._ops(conn)
            check(cursor, schema, 5)

    def test_page_relationship_validation_needs_the_page_identity_columns(self):
        check = BidOperationsMixin._require_duplicable_indirect_page_relationships
        for page_columns in ("UID INTEGER", "BidUID INTEGER"):
            conn = contract_db(f"CREATE TABLE BidPages ({page_columns})")
            ops, cursor, schema = self._ops(conn)
            check(cursor, schema, 5)

    def test_validation_ignores_children_that_are_not_page_sections(self):
        conn = contract_db(
            *_RICH_DDL,
            "CREATE TABLE BidLaborCostCodes (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidPercents (UID INTEGER, BidPageUID INTEGER, BidLaborCostCodeUID INTEGER)",
            "INSERT INTO BidPercents VALUES (1, 100, 999)",
        )
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")

    def test_page_children_stamped_with_another_bid_are_not_validated_as_this_bids(self):
        conn = contract_db(*_RICH_DDL, "UPDATE BidTakeoffs SET BidUID = 2, BidConditionUID = 999 WHERE UID = 111")
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")

    def test_the_area_count_and_page_checks_use_the_documented_selects(self):
        conn = contract_db(*_RICH_DDL)
        ops = _RecordingSchemaOps(conn)
        self.assertEqual(ops.duplicate_bid("x.mdb", "1"), "3")
        self.assertIn(
            "SELECT [UID], [BidAreaUID], [BidTypAreaUID] FROM [BidTypAreaCounts]", ops.queries
        )
        self.assertIn(
            "SELECT [child].[UID], [child].[MasterAreaUID] FROM [BidAreaTranslations] AS [child] "
            "INNER JOIN [BidPages] AS [owner_page] ON [child].[BidPageUID]=[owner_page].[UID] "
            "WHERE [owner_page].[BidUID]=? AND [child].[MasterAreaUID] IS NOT NULL "
            "AND [child].[MasterAreaUID] <> 0",
            ops.queries,
        )
        self.assertIn("SELECT [NextBidNo] FROM [Settings]", ops.queries)

    def test_a_duplicated_page_uid_blocks_the_duplicate_with_the_table_label(self):
        conn = contract_db(*_RICH_DDL, "INSERT INTO BidPages VALUES (100, 1, '{DUP}', 'Dup', NULL, NULL)")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"))
        self.assertIn("BidPages contains duplicate UID 100", str(logs.records[0].exc_info[1]))

    def test_a_selection_without_a_type_keeps_the_copied_selection_uid(self):
        conn = contract_db(*_RICH_DDL, "UPDATE Bids SET CoverSheetSelItemType = NULL, CoverSheetSelItemUID = 55 WHERE UID = 1")
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertEqual(
            conn.execute("SELECT CoverSheetSelItemType, CoverSheetSelItemUID FROM Bids WHERE UID = 3").fetchone(),
            (None, 55),
        )

    def test_a_page_selection_without_a_uid_never_selects_a_page_that_has_uid_one(self):
        conn = contract_db(
            *_RICH_DDL,
            "INSERT INTO BidPages VALUES (1, 1, '{ONE}', 'Page uid one', NULL, NULL)",
            "UPDATE Bids SET CoverSheetSelItemUID = NULL WHERE UID = 1",
        )
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertIsNone(conn.execute("SELECT CoverSheetSelItemUID FROM Bids WHERE UID = 3").fetchone()[0])

    def test_failing_copies_inside_a_duplicate_follow_the_error_policy(self):
        for table in ("BidPlanRooms", "BidLegends", "BidConditions"):
            for ops_class, strict in ((_PyodbcBlobOps, False), (_StrictPyodbcBlobOps, True)):
                with self.subTest(table=table, strict=strict):
                    conn = contract_db(
                        *_RICH_DDL,
                        f"CREATE TRIGGER block BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'x'); END",
                    )
                    ops = ops_class(conn)
                    if strict:
                        with self.assertRaises(pyodbc.Error):
                            ops.duplicate_bid("x.mdb", "1")
                    else:
                        self.assertEqual(ops.duplicate_bid("x.mdb", "1"), "3")
                        self.assertEqual(
                            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE BidUID = 3").fetchone(), (0,)
                        )


class CreateBidFolderSpellingTests(unittest.TestCase):
    _BIDS = CreateBidDefaultsAndFoldersTests._BIDS

    def _db(self, folder_columns="UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER"):
        return contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            self._BIDS,
            f"CREATE TABLE BidPageFolders ({folder_columns})",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Width REAL, Height REAL, BidPageFolderUID INTEGER)",
        )

    def test_a_flat_folder_table_accepts_every_blank_parent_spelling_but_not_a_real_parent(self):
        for parent in ("", 0, "0", None):
            with self.subTest(parent=parent):
                conn = self._db("UID INTEGER, BidUID INTEGER, Name TEXT")
                self.assertEqual(
                    RealContractOps(conn).create_bid(
                        "x.mdb", None, {"new_folders": [{"local_uid": "a", "name": "A", "parent_uid": parent}]}
                    ),
                    "1",
                )
        conn = self._db("UID INTEGER, BidUID INTEGER, Name TEXT")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(
                RealContractOps(conn).create_bid(
                    "x.mdb", None,
                    {"new_folders": [{"local_uid": "a", "name": "A"}, {"local_uid": "b", "name": "B", "parent_uid": "a"}]},
                )
            )
        self.assertIn("does not support page-folder hierarchy persistence", str(logs.records[0].exc_info[1]))

    def test_pages_accept_blank_folder_spellings_and_reject_unknown_folders(self):
        for folder in ("", 0, "0", None):
            with self.subTest(folder=folder):
                conn = self._db()
                page = {"width": 1.0, "height": 1.0, "folder_uid": folder}
                self.assertEqual(RealContractOps(conn).create_bid("x.mdb", None, {"pages": [page]}), "1")
                (stored,) = conn.execute("SELECT BidPageFolderUID FROM BidPages").fetchone()
                self.assertIn(stored, (None, 0) if folder == "0" else (None,))
        conn = self._db()
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(
                RealContractOps(conn).create_bid(
                    "x.mdb", None, {"pages": [{"width": 1.0, "height": 1.0, "folder_uid": "9"}]}
                )
            )
        self.assertEqual(
            str(logs.records[0].exc_info[1]),
            "New Bid page references unavailable page folder 9.",
        )

    def test_a_blank_page_folder_never_binds_to_a_folder_whose_local_id_is_zero(self):
        conn = self._db()
        RealContractOps(conn).create_bid(
            "x.mdb", None,
            {
                "new_folders": [{"local_uid": "0", "name": "Zero"}, {"local_uid": "k", "name": "Kid", "parent_uid": 0}],
                "pages": [{"width": 1.0, "height": 1.0, "folder_uid": 0}],
            },
        )
        self.assertEqual(conn.execute("SELECT BidPageFolderUID FROM BidPages").fetchone(), (None,))
        self.assertEqual(
            conn.execute("SELECT ParentUID FROM BidPageFolders WHERE Name = 'Kid'").fetchone(), (None,)
        )

    def test_template_layers_ignore_a_missing_table_name_in_optional_selects(self):
        conn = self._db()
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, IsTemplate INTEGER, Show INTEGER, Sequence INTEGER)")
        conn.execute("INSERT INTO BidLayers VALUES (1, NULL, 'T', -1, 1, 4)")
        RealContractOps(conn).create_bid("x.mdb", None, {})
        self.assertEqual(
            conn.execute("SELECT Name, Show, Sequence FROM BidLayers WHERE BidUID = 1").fetchall(),
            [("T", -1, 4)],
        )


class DuplicateBlankReferenceTests(unittest.TestCase):
    def test_blank_typical_references_are_copied_unchanged_even_if_the_map_names_zero(self):
        conn = contract_db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (30, 5)",
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID, ExtraBlob BLOB)",
            "INSERT INTO BidTypAreaCounts VALUES (1, 30, '', 'a')",
            "INSERT INTO BidTypAreaCounts VALUES (2, 30, 0, 'b')",
            "INSERT INTO BidTypAreaCounts VALUES (3, 30, '0', 'c')",
        )
        ops = _BlobTypedOps(conn)
        ops._copy_area_count_rows(
            _BlobTypedCursor(conn), ops._schema_ref, "5", {"30": "130"},
            {"0": "999", "": "998"},
        )
        copied = conn.execute(
            "SELECT BidTypAreaUID, ExtraBlob FROM BidTypAreaCounts WHERE UID > 3 ORDER BY ExtraBlob"
        ).fetchall()
        self.assertEqual(copied, [("", b"a"), (0, b"b"), ("0", b"c")])

    def test_area_count_validation_still_sees_rows_with_a_blank_typical_reference(self):
        conn = contract_db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (30, 5)",
            "CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID, BidTypAreaUID)",
            "INSERT INTO BidTypAreaCounts VALUES (1, 30, NULL)",
            "INSERT INTO BidTypAreaCounts VALUES (1, 30, NULL)",
        )
        ops = _BlobTypedOps(conn)
        with self.assertRaisesRegex(RuntimeError, "BidTypAreaCounts contains duplicate UID 1"):
            BidOperationsMixin._require_duplicable_indirect_area_counts(
                _BlobTypedCursor(conn), ops._schema_ref, 5
            )

    def test_row_relationships_with_blank_values_are_never_remapped_even_for_a_zero_key(self):
        maps = {"BidLayers": {"0": "999", "": "998"}}
        for blank in ("", 0, "0", None):
            with self.subTest(blank=blank):
                row = {"BidLayerUID": blank}
                BidOperationsMixin._remap_row_relationships("BidConditions", row, maps)
                self.assertEqual(row["BidLayerUID"], blank)


# ---------------------------------------------------------------------------
# Round 3: bound parameter types, loosely typed id cells, redundant-guard pins
# ---------------------------------------------------------------------------
from tests.helpers.mdb.real_write_contract import ListParamConnection, ListParamCursor
from ost_visualizer.infrastructure.mdb.components.constants import (
    COVER_SHEET_PAGE_SELECTION_TYPE as _PAGE_SELECTION_TYPE,
)
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    BID_RELATIONSHIPS as _BID_RELATIONSHIPS,
)


class _ParamLogCursor(ListParamCursor):
    log = None

    def execute(self, query, *params):
        flat = tuple(params[0]) if len(params) == 1 and isinstance(params[0], (list, tuple)) else params
        self.log.append((" ".join(query.split()), flat))
        return super().execute(query, *params)


class _ParamLogConnection(ListParamConnection):
    log = None

    def cursor(self):
        cursor = _ParamLogCursor(self._connection)
        cursor.log = self.log
        return cursor


class _ParamLogOps(RealContractOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.log = []

    def _connection(self, _db_path):
        wrapper = _ParamLogConnection(self._connection_ref)
        wrapper.log = self.log
        return wrapper

    def statements(self, prefix):
        return [(sql, params) for sql, params in self.log if sql.startswith(prefix)]


class _ParamLogBlobOps(_BlobTypedOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.log = []

    def _connection(self, _db_path):
        wrapper = _ParamLogBlobConnection(self._connection_ref)
        wrapper.log = self.log
        return wrapper


class _ParamLogBlobCursor(_BlobTypedCursor):
    log = None

    def execute(self, query, *params):
        flat = tuple(params[0]) if len(params) == 1 and isinstance(params[0], (list, tuple)) else params
        self.log.append((" ".join(query.split()), flat))
        return super().execute(query, *params)


class _ParamLogBlobConnection(_BlobTypedConnection):
    log = None

    def cursor(self):
        cursor = _ParamLogBlobCursor(self._connection)
        cursor.log = self.log
        return cursor


class BoundParameterTypeTests(unittest.TestCase):
    """Identifiers reach the database as integers, whatever text the caller handed in."""

    def test_the_duplicate_preflight_binds_the_source_bid_as_an_integer(self):
        conn = contract_db(*_RICH_DDL)
        ops = _ParamLogBlobOps(conn)
        self.assertEqual(ops.duplicate_bid("x.mdb", "1"), "3")
        preflight = [
            params
            for sql, params in ops.log
            if sql.startswith("SELECT [child].[UID]") and "[child].[BidUID] = ?" in sql
        ]
        self.assertTrue(preflight)
        for params in preflight:
            self.assertEqual(params, (1,))
            self.assertIs(type(params[0]), int)

    def test_a_new_bid_binds_its_project_and_folder_references_as_integers(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            CreateBidDefaultsAndFoldersTests._BIDS.replace("(UID INTEGER,", "(UID INTEGER, BidProjectUID INTEGER,"),
            "CREATE TABLE BidProjects (UID INTEGER)",
            "INSERT INTO BidProjects VALUES (7)",
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Width REAL, Height REAL, BidPageFolderUID INTEGER)",
        )
        ops = _ParamLogOps(conn)
        self.assertEqual(
            ops.create_bid(
                "x.mdb",
                "7",
                {
                    "new_folders": [{"local_uid": "a", "name": "A", "parent_uid": "0"}],
                    "pages": [{"width": 1.0, "height": 1.0, "folder_uid": "0"}],
                },
            ),
            "1",
        )
        (bid_insert,) = ops.statements("INSERT INTO [Bids]")
        index = bid_insert[0].split("(")[1].split(")")[0].replace("[", "").replace("]", "").split(", ").index("BidProjectUID")
        self.assertEqual(bid_insert[1][index], 7)
        self.assertIs(type(bid_insert[1][index]), int)
        (folder_insert,) = ops.statements("INSERT INTO [BidPageFolders]")
        self.assertIn(0, folder_insert[1])
        for value in folder_insert[1]:
            self.assertNotEqual(value, "0")
        (page_insert,) = ops.statements("INSERT INTO [BidPages]")
        for value in page_insert[1]:
            self.assertNotEqual(value, "0")
        self.assertIn(0, page_insert[1])

    def test_the_child_reference_lookup_binds_each_new_child_uid_once_as_an_integer(self):
        conn = contract_db("CREATE TABLE C (UID INTEGER, Ref INTEGER)", "INSERT INTO C VALUES (5, 20)")
        ops = _ParamLogOps(conn)
        with ops._connection("x.mdb") as connection:
            references = ops._duplicated_child_references(connection.cursor(), "C", "Ref", ["5", "5", 5])
        self.assertEqual(references, {"5": "20"})
        (lookup,) = ops.statements("SELECT [UID], [Ref]")
        self.assertEqual(lookup[1], (5,))
        self.assertIs(type(lookup[1][0]), int)


class BulkDeleteGuardTests(unittest.TestCase):
    class _StrictOps(RealContractOps):
        def _record_caught_mutation_error(self, exc):
            return True

    def test_an_unusable_uid_list_names_the_bids_in_the_error_the_policy_receives(self):
        conn = contract_db("CREATE TABLE Bids (UID INTEGER)")
        with self.assertRaisesRegex(ValueError, r"^Invalid Bids UID: 'abc'$"):
            self._StrictOps(conn).delete_bids("x.mdb", ["abc"])

    def test_a_bid_scoped_table_without_a_bid_column_is_left_alone(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidNotes (UID INTEGER, Body TEXT)",
            "INSERT INTO BidNotes VALUES (5, 'kept')",
        )
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM Bids"), [])
        self.assertEqual(_rows(conn, "SELECT Body FROM BidNotes"), [("kept",)])


    def test_a_page_scoped_table_without_a_page_column_is_cleared_by_its_bid_column_only(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "CREATE TABLE BidComments (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidComments VALUES (5, 1)",
            "INSERT INTO BidComments VALUES (6, 2)",
        )
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, "SELECT UID FROM BidComments"), [(6,)])

    def test_takeoff_link_tables_are_cleared_by_their_bid_column_when_the_takeoff_table_cannot_be_joined(self):
        for takeoff_table in (
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER)",
            "CREATE TABLE BidTakeoffs (BidUID INTEGER, BidPageUID INTEGER)",
            None,
        ):
            with self.subTest(takeoffs=takeoff_table):
                conn = contract_db(
                    "CREATE TABLE Bids (UID INTEGER)",
                    "INSERT INTO Bids VALUES (1)",
                    "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
                    "CREATE TABLE BidDimensions (UID INTEGER, BidUID INTEGER, BidTakeoffFromUID INTEGER)",
                    "INSERT INTO BidDimensions VALUES (5, 1, 40)",
                    *([takeoff_table] if takeoff_table else []),
                )
                self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
                self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidDimensions"), [(0,)])

    def test_a_page_scoped_table_without_any_bid_or_page_column_is_left_alone(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "CREATE TABLE BidComments (UID INTEGER, Body TEXT)",
            "INSERT INTO BidComments VALUES (5, 'kept')",
        )
        self.assertIs(RealContractOps(conn).delete_bids("x.mdb", ["1"]), True)
        self.assertEqual(_rows(conn, "SELECT Body FROM BidComments"), [("kept",)])


class RelationshipTableInvariantTests(unittest.TestCase):
    def test_no_relationship_is_declared_twice(self):
        # The duplicate preflights skip a repeated (child, column, parent, column) key;
        # that skip is only invisible while the declaration list has no repeats.
        keys = [
            (r.child_table, r.child_column, r.parent_table, r.parent_column)
            for r in _BID_RELATIONSHIPS
        ]
        self.assertEqual(len(keys), len(set(keys)))


class DuplicateKeepsAreaCountsOnTheirOwnPathTests(unittest.TestCase):
    def test_counts_that_carry_a_bid_column_are_still_copied_only_through_their_areas(self):
        conn = contract_db(*_RICH_DDL)
        conn.execute("ALTER TABLE BidTypAreaCounts ADD COLUMN BidUID INTEGER")
        conn.execute("UPDATE BidTypAreaCounts SET BidUID = 1 WHERE UID IN (50, 51)")
        conn.execute("UPDATE BidTypAreaCounts SET BidUID = 2 WHERE UID = 52")
        self.assertEqual(_BlobTypedOps(conn).duplicate_bid("x.mdb", "1"), "3")
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidTypAreaCounts"), [(5,)])
        self.assertEqual(
            _rows(
                conn,
                "SELECT COUNT(*) FROM BidTypAreaCounts WHERE BidAreaUID IN "
                "(SELECT UID FROM BidAreas WHERE BidUID = 3)",
            ),
            [(2,)],
        )


class CreateBidLayerSelectTests(unittest.TestCase):
    def test_a_layer_table_without_a_uid_column_does_not_break_a_bid_with_no_template_layers(self):
        conn = contract_db(
            "CREATE TABLE Settings (NextBidNo INTEGER)",
            "INSERT INTO Settings VALUES (1)",
            CreateBidDefaultsAndFoldersTests._BIDS,
            "CREATE TABLE BidLayers (BidUID INTEGER, Name TEXT, IsTemplate INTEGER)",
        )
        self.assertEqual(RealContractOps(conn).create_bid("x.mdb", None, {}), "1")
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidLayers"), [(0,)])


class _TextCellOps(RealContractOps):
    """Run a helper against loosely typed cells: ids stored as text, with leading zeros."""

    def cursor_and_schema(self):
        connection = self._connection("x.mdb").__enter__()
        return connection.cursor(), self._schema(connection)


class DuplicateTextIdentifierTests(unittest.TestCase):
    """Older files keep ids as text; every helper must canonicalise them like integers."""

    def ops(self, *ddl):
        return _TextCellOps(contract_db(*ddl))

    def test_the_bid_row_copy_keys_its_uid_map_and_exclusions_by_integer_value(self):
        ops = self.ops(
            "CREATE TABLE T (UID, BidUID INTEGER, Name TEXT)",
            "INSERT INTO T VALUES ('040', 1, 'a')",
            "INSERT INTO T VALUES ('041', 1, 'b')",
        )
        cursor, schema = ops.cursor_and_schema()
        uid_map = ops._copy_bid_table_rows(cursor, "T", "BidUID", "1", "2", schema=schema)
        self.assertEqual(set(uid_map), {"40", "41"})
        ops = self.ops(
            "CREATE TABLE T (UID, BidUID INTEGER, Name TEXT)",
            "INSERT INTO T VALUES ('040', 1, 'a')",
            "INSERT INTO T VALUES ('041', 1, 'b')",
        )
        cursor, schema = ops.cursor_and_schema()
        uid_map = ops._copy_bid_table_rows(
            cursor, "T", "BidUID", "1", "2", excluded_source_uids={"40"}, schema=schema
        )
        self.assertEqual(set(uid_map), {"41"})
        self.assertEqual(_rows(ops._connection_ref, "SELECT COUNT(*) FROM T WHERE BidUID = 2"), [(1,)])

    def test_the_uid_map_copy_keys_its_map_by_integer_value(self):
        ops = self.ops(
            "CREATE TABLE T (UID, BidUID INTEGER, Name TEXT)",
            "INSERT INTO T VALUES ('040', 1, 'a')",
        )
        cursor, schema = ops.cursor_and_schema()
        self.assertEqual(
            set(ops._copy_with_uid_map(cursor, "T", "BidUID", "1", "2", schema=schema)), {"40"}
        )

    def test_the_page_child_copy_follows_the_page_map_by_integer_value(self):
        ops = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (20, 1)",
            "CREATE TABLE C (UID, BidPageUID, Name TEXT)",
            "INSERT INTO C VALUES ('040', '020', 'a')",
        )
        cursor, schema = ops.cursor_and_schema()
        uid_map = ops._copy_page_table_rows(cursor, schema, "C", "1", "2", {"20": "99"})
        self.assertEqual(set(uid_map), {"40"})
        self.assertEqual(
            _rows(ops._connection_ref, "SELECT BidPageUID FROM C WHERE UID <> '040'"), [("99",)]
        )

    def test_the_area_count_copy_follows_both_maps_by_integer_value(self):
        ops = self.ops(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (30, 1)",
            "CREATE TABLE BidTypAreaCounts (UID, BidAreaUID, BidTypAreaUID)",
            "INSERT INTO BidTypAreaCounts VALUES ('050', '030', '040')",
        )
        cursor, schema = ops.cursor_and_schema()
        uid_map = ops._copy_area_count_rows(cursor, schema, "1", {"30": "130"}, {"40": "140"})
        self.assertEqual(set(uid_map), {"50"})
        self.assertEqual(
            _rows(
                ops._connection_ref,
                "SELECT BidAreaUID, BidTypAreaUID FROM BidTypAreaCounts WHERE UID <> '050'",
            ),
            [("130", "140")],
        )

    def test_the_child_reference_lookup_canonicalises_the_stored_reference(self):
        ops = self.ops("CREATE TABLE C (UID INTEGER, Ref)", "INSERT INTO C VALUES (5, '020')")
        cursor, _schema = ops.cursor_and_schema()
        self.assertEqual(ops._duplicated_child_references(cursor, "C", "Ref", ["5"]), {"5": "20"})

    def test_the_reference_scan_canonicalises_the_stored_reference(self):
        ops = self.ops(
            "CREATE TABLE C (UID INTEGER, BidUID INTEGER, Ref)",
            "INSERT INTO C VALUES (5, 2, '020')",
            "INSERT INTO C VALUES (6, 2, '021')",
        )
        cursor, _schema = ops.cursor_and_schema()
        self.assertEqual(ops._duplicated_reference_uids(cursor, "C", "Ref", "2"), {"20", "21"})

    def test_a_row_reference_with_leading_zeros_is_remapped_by_integer_value(self):
        row = {"BidLayerUID": "080", "BidConditionFolderUID": "0"}
        BidOperationsMixin._remap_row_relationships(
            "BidConditions", row, {"BidLayers": {"80": "180"}, "BidConditionFolders": {"0": "9"}}
        )
        self.assertEqual(row["BidLayerUID"], "180")
        self.assertEqual(row["BidConditionFolderUID"], "0")

    def test_a_copied_cover_sheet_selection_is_found_by_integer_value(self):
        ops = self.ops(
            "CREATE TABLE Bids (UID INTEGER, CoverSheetSelItemUID INTEGER)",
            "INSERT INTO Bids VALUES (2, NULL)",
        )
        cursor, schema = ops.cursor_and_schema()
        ops._remap_duplicated_cover_sheet_selection(
            cursor,
            schema,
            {"CoverSheetSelItemType": str(_PAGE_SELECTION_TYPE), "CoverSheetSelItemUID": "0101"},
            {"101": "201"},
            "2",
        )
        self.assertEqual(_rows(ops._connection_ref, "SELECT CoverSheetSelItemUID FROM Bids"), [(201,)])


class DuplicatePreflightTextIdentifierTests(unittest.TestCase):
    """The pre-duplication integrity scans compare ids by integer value, not by spelling."""

    def ops(self, *ddl):
        return _TextCellOps(contract_db(*ddl))

    _RELATION_DDL = (
        "CREATE TABLE BidPages (UID, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES ('020', 1)",
        "CREATE TABLE BidTakeoffs (UID, BidUID INTEGER, BidPageUID)",
        "CREATE TABLE BidTakeoffTotals (UID, BidUID INTEGER, BidPageUID)",
    )

    def test_a_text_reference_to_a_text_uid_is_not_dangling(self):
        ops = self.ops(*self._RELATION_DDL, "INSERT INTO BidTakeoffs VALUES ('040', 1, '020')")
        cursor, schema = ops.cursor_and_schema()
        self.assertEqual(ops._require_duplicable_bid_relationships(cursor, schema, 1), {})

    def test_a_dangling_text_reference_is_reported_with_canonical_uids(self):
        ops = self.ops(*self._RELATION_DDL, "INSERT INTO BidTakeoffs VALUES ('040', 1, '021')")
        cursor, schema = ops.cursor_and_schema()
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            r"^BidTakeoffs\.UID=40 references missing BidPages\.UID=21 through BidPageUID\.$",
        ):
            ops._require_duplicable_bid_relationships(cursor, schema, 1)

    def test_dangling_derived_totals_are_listed_by_canonical_uid(self):
        ops = self.ops(*self._RELATION_DDL, "INSERT INTO BidTakeoffTotals VALUES ('050', 1, '099')")
        cursor, schema = ops.cursor_and_schema()
        self.assertEqual(
            ops._require_duplicable_bid_relationships(cursor, schema, 1),
            {"BidTakeoffTotals": {"50"}},
        )

    _COUNT_DDL = (
        "CREATE TABLE BidAreas (UID, BidUID INTEGER)",
        "INSERT INTO BidAreas VALUES ('030', 1)",
        "CREATE TABLE BidTypAreas (UID, BidUID INTEGER)",
        "INSERT INTO BidTypAreas VALUES ('040', 1)",
        "CREATE TABLE BidTypAreaCounts (UID, BidAreaUID, BidTypAreaUID)",
    )

    def test_text_area_counts_with_known_references_pass(self):
        ops = self.ops(*self._COUNT_DDL, "INSERT INTO BidTypAreaCounts VALUES ('050', '030', '040')")
        cursor, schema = ops.cursor_and_schema()
        ops._require_duplicable_indirect_area_counts(cursor, schema, 1)

    def test_a_text_area_count_with_an_unknown_typical_is_reported_with_canonical_uids(self):
        ops = self.ops(*self._COUNT_DDL, "INSERT INTO BidTypAreaCounts VALUES ('051', '030', '041')")
        cursor, schema = ops.cursor_and_schema()
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            r"^BidTypAreaCounts\.UID=51 references missing BidTypAreas\.UID=41 through BidTypAreaUID\.$",
        ):
            ops._require_duplicable_indirect_area_counts(cursor, schema, 1)

    def test_a_count_of_area_one_is_validated_like_any_other_area(self):
        ops = self.ops(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (1, 1)",
            "CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidTypAreas VALUES (40, 1)",
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID INTEGER)",
            "INSERT INTO BidTypAreaCounts VALUES (60, 1, 99)",
        )
        cursor, schema = ops.cursor_and_schema()
        with self.assertRaisesRegex(DanglingBidOwnedReferenceError, r"BidTypAreaCounts\.UID=60 "):
            ops._require_duplicable_indirect_area_counts(cursor, schema, 1)

    def test_a_count_naming_area_zero_is_never_validated_even_if_an_area_row_has_uid_zero(self):
        ops = self.ops(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (0, 1)",
            "INSERT INTO BidAreas VALUES (30, 1)",
            "CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidTypAreas VALUES (40, 1)",
            "CREATE TABLE BidTypAreaCounts (UID, BidAreaUID, BidTypAreaUID)",
            "INSERT INTO BidTypAreaCounts VALUES (60, '0', 99)",
        )
        cursor, schema = ops.cursor_and_schema()
        ops._require_duplicable_indirect_area_counts(cursor, schema, 1)

    def test_a_non_numeric_page_uid_fails_the_indirect_page_scan(self):
        ops = self.ops(
            "CREATE TABLE BidPages (UID, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES ('abc', 1)",
        )
        cursor, schema = ops.cursor_and_schema()
        with self.assertRaises(ValueError):
            ops._require_duplicable_indirect_page_relationships(cursor, schema, 1)

    _PAGE_OWNED_DDL = (
        "CREATE TABLE BidPages (UID, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES ('020', 1)",
        "CREATE TABLE BidAreas (UID, BidUID INTEGER)",
        "INSERT INTO BidAreas VALUES ('030', 1)",
        "CREATE TABLE BidPageSettings (UID, BidPageUID, BidAreaUID)",
    )

    def test_text_page_owned_references_to_known_parents_pass(self):
        ops = self.ops(*self._PAGE_OWNED_DDL, "INSERT INTO BidPageSettings VALUES ('060', '020', '030')")
        cursor, schema = ops.cursor_and_schema()
        ops._require_duplicable_indirect_page_relationships(cursor, schema, 1)

    def test_a_page_owned_text_reference_to_an_unknown_parent_is_reported_with_canonical_uids(self):
        ops = self.ops(*self._PAGE_OWNED_DDL, "INSERT INTO BidPageSettings VALUES ('060', '020', '031')")
        cursor, schema = ops.cursor_and_schema()
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            r"^BidPageSettings\.UID=60 references missing BidAreas\.UID=31 through BidAreaUID\.$",
        ):
            ops._require_duplicable_indirect_page_relationships(cursor, schema, 1)
