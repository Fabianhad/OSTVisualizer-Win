import logging
import re
import sqlite3
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
