from ost_visualizer.infrastructure.mdb.components.hierarchy_reader import (
    HierarchyReaderMixin,
)
from collections import namedtuple
import unittest
import sqlite3
import logging
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
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyPageInfo,
)
from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)

_PageRow = namedtuple(
    "_PageRow",
    (
        "UID",
        "Name",
        "BidPageFolderUID",
        "SheetNo",
        "Sequence",
        "ImagePath",
        "Width",
        "Height",
        "ScaleFactor1",
        "ScaleFactor2",
        "Rotation",
        "FlipX",
        "FlipY",
        "Index1",
    ),
)


class _Cursor:
    def __init__(self, folder_rows, page_rows):
        self._folder_rows = folder_rows
        self._page_rows = page_rows
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, *_args):
        if "FROM [BidPageFolders]" in sql:
            self._rows = self._folder_rows
        elif "FROM [BidPages]" in sql:
            self._rows = self._page_rows
        return self

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, folder_rows, page_rows):
        self._folder_rows = folder_rows
        self._page_rows = page_rows

    def cursor(self):
        return _Cursor(self._folder_rows, self._page_rows)


class _Schema:
    def optional_table_missing(self, _table):
        return False

    def require_column(self, _table, _column):
        pass

    def optional_column(self, _table, column, _default):
        return f"[{column}]"

    def order_by_existing(self, _table, _columns, fallback):
        return fallback


class _Reader(HierarchyReaderMixin):
    pass


class _SqliteRow:
    def __init__(self, columns, values):
        self._values = tuple(values)
        self._by_name = dict(zip(columns, values))

    def __getitem__(self, index):
        return self._values[index]

    def __getattr__(self, name):
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class _SqliteCursor:
    def __init__(self, connection):
        self._connection = connection
        self._cursor = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, *params):
        self._cursor = self._connection.execute(query, params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        columns = [description[0] for description in self._cursor.description]
        return [_SqliteRow(columns, row) for row in rows]


class _SqliteConnection:
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return _SqliteCursor(self._connection)


class _SqliteHierarchySchema:
    def __init__(self, connection):
        self._connection = connection

    def optional_table_missing(self, table):
        return (
            self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            is None
        )

    def column_exists(self, table, column):
        return any(
            row[1] == column
            for row in self._connection.execute(f"PRAGMA table_info({table})")
        )

    def require_column(self, table, column):
        if not self.column_exists(table, column):
            raise RuntimeError(f"Missing {table}.{column}")

    def optional_column(self, table, column, default):
        if self.column_exists(table, column):
            return f"[{column}]"
        return f"{default} AS [{column}]"

    def order_by_existing(self, table, columns, fallback):
        present = [column for column in columns if self.column_exists(table, column)]
        return ", ".join(f"[{column}]" for column in present) or fallback


class _SqliteHierarchyReader(HierarchyReaderMixin):
    def __init__(self, connection):
        self._schema_ref = _SqliteHierarchySchema(connection)

    def _schema(self, _connection):
        return self._schema_ref


class HierarchyReaderTests(unittest.TestCase):
    def _hierarchy_connection(self, project_rows, bid_rows):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE BidProjects (UID, Name TEXT)")
        connection.execute("CREATE TABLE Bids (UID, BidProjectUID, JobName TEXT)")
        connection.execute("CREATE TABLE BidPages (UID, BidUID, Name TEXT)")
        connection.execute("CREATE TABLE BidConditions (UID, BidUID)")
        connection.executemany("INSERT INTO BidProjects VALUES (?, ?)", project_rows)
        connection.executemany("INSERT INTO Bids VALUES (?, ?, ?)", bid_rows)
        return connection

    def test_hierarchy_rejects_duplicate_and_malformed_project_uids(self):
        fixtures = (
            (((7, "First"), (7, "Conflicting")), "duplicate UID 7"),
            (((None, "Missing"),), "malformed UID <missing>"),
            (((0, "Zero"),), "malformed UID 0"),
            ((("not-a-uid", "Text"),), "malformed UID not-a-uid"),
        )
        for project_rows, message in fixtures:
            with self.subTest(project_rows=project_rows):
                connection = self._hierarchy_connection(project_rows, ())
                with self.assertRaisesRegex(
                    RuntimeError, f"BidProjects contains {message}"
                ):
                    _SqliteHierarchyReader(connection)._parse_hierarchy(
                        _SqliteConnection(connection), "malformed.mdb"
                    )

    def test_hierarchy_rejects_duplicate_and_malformed_bid_uids(self):
        fixtures = (
            (((7, 1, "First"), (7, 1, "Conflicting")), "duplicate UID 7"),
            (((None, 1, "Missing"),), "malformed UID <missing>"),
            (((0, 1, "Zero"),), "malformed UID 0"),
            ((("not-a-uid", 1, "Text"),), "malformed UID not-a-uid"),
        )
        for bid_rows, message in fixtures:
            with self.subTest(bid_rows=bid_rows):
                connection = self._hierarchy_connection(((1, "Project"),), bid_rows)
                with self.assertRaisesRegex(RuntimeError, f"Bids contains {message}"):
                    _SqliteHierarchyReader(connection)._parse_hierarchy(
                        _SqliteConnection(connection), "malformed.mdb"
                    )

    def test_orphaned_page_folder_is_recovered_as_a_root(self):
        connection = _Connection(
            folder_rows=[(10, "Recovered", "", 999)],
            page_rows=[
                _PageRow(
                    20,
                    "A-101",
                    10,
                    "A-101",
                    1,
                    "A-101.pdf",
                    36.0,
                    24.0,
                    1.0,
                    96.0,
                    0,
                    0,
                    0,
                    1,
                )
            ],
        )
        folders, pages_without_folder = _Reader()._get_bid_folder_page_structure(
            connection, "1", _Schema()
        )
        self.assertEqual(list(folders), ["10"])
        self.assertEqual(folders["10"].name, "Recovered")
        self.assertEqual(folders["10"].subfolders, {})
        self.assertEqual([page.uid for page in folders["10"].pages], ["20"])
        self.assertEqual(pages_without_folder, [])

    def test_cross_bid_page_folder_parent_is_recovered_as_a_root(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        connection.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, BidPageFolderUID INTEGER)"
        )
        connection.executemany(
            "INSERT INTO BidPageFolders VALUES (?, ?, ?, ?)",
            ((10, 1, "Recovered", 99), (99, 2, "Other bid", None)),
        )
        connection.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?, ?)",
            ((20, 1, "A-101", 10), (21, 2, "Other bid page", 99)),
        )
        folders, pages_without_folder = _SqliteHierarchyReader(
            connection
        )._get_bid_folder_page_structure(
            _SqliteConnection(connection),
            "1",
            _SqliteHierarchySchema(connection),
        )
        self.assertEqual(list(folders), ["10"])
        self.assertEqual(folders["10"].subfolders, {})
        self.assertEqual([page.uid for page in folders["10"].pages], ["20"])
        self.assertEqual(pages_without_folder, [])

    def test_page_hierarchy_rejects_folder_parent_cycles(self):
        fixtures = (
            ([(10, "Self", "", 10)], "UID=10"),
            (
                [(10, "First", "", 11), (11, "Second", "", 10)],
                "UID=10",
            ),
            (
                [
                    (10, "First", "", 11),
                    (11, "Second", "", 12),
                    (12, "Third", "", 10),
                ],
                "UID=10",
            ),
        )
        for folder_rows, message in fixtures:
            with self.subTest(folder_rows=folder_rows):
                with self.assertRaisesRegex(
                    RuntimeError,
                    rf"BidPageFolders\.{message} participates in a ParentUID cycle",
                ):
                    _Reader()._get_bid_folder_page_structure(
                        _Connection(folder_rows, []), "1", _Schema()
                    )

    def test_page_hierarchy_accepts_valid_multi_level_folder_chain(self):
        page = _PageRow(
            20,
            "A-101",
            12,
            "A-101",
            1,
            "A-101.pdf",
            36.0,
            24.0,
            1.0,
            96.0,
            0,
            0,
            0,
            1,
        )
        folders, pages_without_folder = _Reader()._get_bid_folder_page_structure(
            _Connection(
                [
                    (10, "Root", "", None),
                    (11, "Middle", "", 10),
                    (12, "Leaf", "", 11),
                ],
                [page],
            ),
            "1",
            _Schema(),
        )
        self.assertEqual(list(folders), ["10"])
        self.assertEqual(list(folders["10"].subfolders), ["11"])
        self.assertEqual(list(folders["10"].subfolders["11"].subfolders), ["12"])
        self.assertEqual(
            [
                item.uid
                for item in folders["10"].subfolders["11"].subfolders["12"].pages
            ],
            ["20"],
        )
        self.assertEqual(folders["10"].pages, [])
        self.assertEqual(folders["10"].subfolders["11"].pages, [])
        self.assertEqual(pages_without_folder, [])

    def test_page_hierarchy_rejects_duplicate_folder_uid(self):
        connection = _Connection(
            folder_rows=[(10, "First", "", None), (10, "Conflicting", "", None)],
            page_rows=[],
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidPageFolders contains duplicate UID 10",
        ):
            _Reader()._get_bid_folder_page_structure(connection, "1", _Schema())

    def test_page_hierarchy_rejects_duplicate_page_uid(self):
        pages = [
            _PageRow(
                20,
                name,
                None,
                "A-101",
                1,
                "A-101.pdf",
                36.0,
                24.0,
                1.0,
                96.0,
                0,
                0,
                0,
                1,
            )
            for name in ("First", "Conflicting")
        ]
        with self.assertRaisesRegex(
            RuntimeError,
            "BidPages contains duplicate UID 20",
        ):
            _Reader()._get_bid_folder_page_structure(
                _Connection([], pages), "1", _Schema()
            )


class HierarchyReaderPersistenceTests(unittest.TestCase):
    def test_hierarchy_reader_rejects_duplicate_job_status_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO JobStatuses VALUES (7, ?)",
            (("Open",), ("Conflicting",)),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "JobStatuses contains duplicate UID 7",
        ):
            MdbReader._load_status_map(
                _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn)
            )

    def test_hierarchy_reader_rejects_duplicate_employee_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Employees (UID INTEGER, FirstName TEXT, LastName TEXT)"
        )
        conn.executemany(
            "INSERT INTO Employees VALUES (7, ?, 'Smith')",
            (("Ann",), ("Bob",)),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "Employees contains duplicate UID 7",
        ):
            MdbReader._load_employee_map(
                _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn)
            )

    def test_status_and_employee_maps_decode_names_and_tolerate_missing_tables(self):
        conn = sqlite3.connect(":memory:")
        ops = _SqliteMdbOps(conn)
        wrapper = _SqliteConnectionWrapper(conn)
        self.assertEqual(MdbReader._load_status_map(ops, wrapper), {})
        self.assertEqual(MdbReader._load_employee_map(ops, wrapper), {})
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO JobStatuses VALUES (?, ?)", ((1, "Open"), (2, None))
        )
        conn.execute(
            "CREATE TABLE Employees (UID INTEGER, FirstName TEXT, LastName TEXT)"
        )
        conn.executemany(
            "INSERT INTO Employees VALUES (?, ?, ?)",
            ((3, " Ann ", "Smith"), (4, None, "Cher"), (5, "Solo", None)),
        )
        self.assertEqual(
            MdbReader._load_status_map(ops, wrapper), {"1": "Open", "2": ""}
        )
        self.assertEqual(
            MdbReader._load_employee_map(ops, wrapper),
            {"3": "Ann Smith", "4": "Cher", "5": "Solo"},
        )

    def test_parse_hierarchy_projects_bids_with_counts_status_and_estimator(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidProjects (UID INTEGER, Name TEXT, Description TEXT)"
        )
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, JobName TEXT, "
            "JobID TEXT, BidNo INTEGER, JobStatusUID INTEGER, EstimatorUID INTEGER, "
            "MeasureBase INTEGER, TakeoffIncrements REAL)"
        )
        conn.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "BidPageFolderUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Employees (UID INTEGER, FirstName TEXT, LastName TEXT)"
        )
        conn.execute("INSERT INTO BidProjects VALUES (1, 'Project', 'Described')")
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (10, 1, "Bid ten", "J-10", 2, 5, 6, 1, 0.5),
                (11, 99, "Orphan bid", None, 0, None, None, None, None),
            ),
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?, NULL)",
            ((20, 10, "P1"), (21, 10, "P2"), (22, 11, "P3")),
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?)", ((30, 10), (31, 11), (32, 11))
        )
        conn.execute("INSERT INTO JobStatuses VALUES (5, 'Won')")
        conn.execute("INSERT INTO Employees VALUES (6, 'Eve', 'Estimator')")
        entry = _SqliteHierarchyReader(conn)._parse_hierarchy(
            _SqliteConnection(conn), "C:/data/sample.mdb"
        )
        self.assertEqual(entry.database_name, "sample")
        self.assertEqual(list(entry.bid_projects), ["1"])
        project = entry.bid_projects["1"]
        self.assertEqual((project.name, project.description), ("Project", "Described"))
        self.assertEqual([bid.uid for bid in project.bids], ["10"])
        bid = project.bids[0]
        self.assertEqual(
            (
                bid.name,
                bid.job_id,
                bid.bid_no,
                bid.status,
                bid.status_uid,
                bid.estimator,
                bid.page_count,
                bid.condition_count,
                bid.measure_base,
                bid.takeoff_increments,
            ),
            ("Bid ten", "J-10", 2, "Won", "5", "Eve Estimator", 2, 1, 1, 0.5),
        )
        self.assertEqual([page.uid for page in bid.pages_without_folder], ["20", "21"])
        self.assertEqual([item.uid for item in entry.orphan_bids], ["11"])
        orphan = entry.orphan_bids[0]
        self.assertEqual(
            (
                orphan.status,
                orphan.status_uid,
                orphan.estimator,
                orphan.page_count,
                orphan.condition_count,
                orphan.takeoff_increments,
            ),
            ("", None, "", 1, 2, 1.0),
        )


_FULL_PAGE_COLUMNS = (
    "UID INTEGER, BidUID INTEGER, Name TEXT, BidPageFolderUID INTEGER, "
    "SheetNo TEXT, Sequence INTEGER, ImagePath TEXT, Width REAL, Height REAL, "
    "ScaleFactor1 REAL, ScaleFactor2 REAL, Rotation INTEGER, FlipX INTEGER, "
    "FlipY INTEGER, Index1 INTEGER"
)


class HierarchyRealSchemaTests(unittest.TestCase):
    def connection(self, *statements):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for statement in statements:
            connection.execute(statement)
        return connection

    def structure(self, connection, bid_uid="1"):
        return _SqliteHierarchyReader(connection)._get_bid_folder_page_structure(
            _SqliteConnection(connection), bid_uid, _SqliteHierarchySchema(connection)
        )

    def test_page_info_carries_every_stored_field_in_sequence_name_uid_order(self):
        connection = self.connection(
            f"CREATE TABLE BidPages ({_FULL_PAGE_COLUMNS})",
            "INSERT INTO BidPages VALUES (20, 1, 'A-101', NULL, 'S1', 2, 'a.pdf', "
            "36.5, 24.25, 0.125, 12.0, 90, -1, 0, 3)",
            "INSERT INTO BidPages VALUES (21, 1, NULL, 0, NULL, NULL, NULL, NULL, "
            "NULL, NULL, NULL, NULL, 0, 1, NULL)",
            "INSERT INTO BidPages VALUES (22, 1, 'B', NULL, '', 1, '', 0, 0, 0, 0, 0, "
            "1, -1, 0)",
            "INSERT INTO BidPages VALUES (23, 1, 'A', NULL, '', 1, '', 0, 0, 0, 0, 0, "
            "0, 0, 7)",
            "INSERT INTO BidPages VALUES (24, 2, 'Other', NULL, '', 1, '', 0, 0, 1, 1, "
            "0, 0, 0, 1)",
        )
        folders, loose = self.structure(connection)
        self.assertEqual(folders, {})
        self.assertEqual(
            loose,
            [
                HierarchyPageInfo(
                    "21", "", "", 0, None, 0.0, 0.0, 1.0, 1.0, 0, False, True, 0
                ),
                HierarchyPageInfo(
                    "23", "A", "", 1, None, 0.0, 0.0, 0.0, 0.0, 0, False, False, 6
                ),
                HierarchyPageInfo(
                    "22", "B", "", 1, None, 0.0, 0.0, 0.0, 0.0, 0, True, True, 0
                ),
                HierarchyPageInfo(
                    "20",
                    "A-101",
                    "S1",
                    2,
                    "a.pdf",
                    36.5,
                    24.25,
                    0.125,
                    12.0,
                    90,
                    True,
                    False,
                    2,
                ),
            ],
        )

    def test_pages_of_a_database_without_optional_columns_use_defaults_and_uid_order(
        self,
    ):
        connection = self.connection(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (31, 1)",
            "INSERT INTO BidPages VALUES (30, 1)",
            "INSERT INTO BidPages VALUES (32, 2)",
        )
        folders, loose = self.structure(connection)
        self.assertEqual(folders, {})
        self.assertEqual(
            loose,
            [
                HierarchyPageInfo(
                    "30", "", "", 0, None, 0.0, 0.0, 1.0, 1.0, 0, False, False, 0
                ),
                HierarchyPageInfo(
                    "31", "", "", 0, None, 0.0, 0.0, 1.0, 1.0, 0, False, False, 0
                ),
            ],
        )

    def test_folders_nest_by_parent_drop_empty_branches_and_keep_name_order(self):
        connection = self.connection(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Description TEXT, ParentUID INTEGER)",
            f"CREATE TABLE BidPages ({_FULL_PAGE_COLUMNS})",
            "INSERT INTO BidPageFolders VALUES (10, 1, 'Zeta', 'zd', NULL)",
            "INSERT INTO BidPageFolders VALUES (11, 1, 'Alpha', 'ad', 0)",
            "INSERT INTO BidPageFolders VALUES (12, 1, 'Child B', NULL, 10)",
            "INSERT INTO BidPageFolders VALUES (13, 1, 'Child A', 'cd', 10)",
            "INSERT INTO BidPageFolders VALUES (14, 1, 'Empty', '', NULL)",
            "INSERT INTO BidPageFolders VALUES (15, 1, 'Orphan', '', 999)",
            "INSERT INTO BidPageFolders VALUES (16, 2, 'Other bid', '', NULL)",
            "INSERT INTO BidPages (UID, BidUID, Name, BidPageFolderUID, Sequence) "
            "VALUES (20, 1, 'P-a', 13, 1)",
            "INSERT INTO BidPages (UID, BidUID, Name, BidPageFolderUID, Sequence) "
            "VALUES (21, 1, 'P-b', 12, 1)",
            "INSERT INTO BidPages (UID, BidUID, Name, BidPageFolderUID, Sequence) "
            "VALUES (22, 1, 'P-c', 11, 1)",
            "INSERT INTO BidPages (UID, BidUID, Name, BidPageFolderUID, Sequence) "
            "VALUES (23, 1, 'P-d', 15, 1)",
            "INSERT INTO BidPages (UID, BidUID, Name, BidPageFolderUID, Sequence) "
            "VALUES (24, 1, 'P-e', 16, 1)",
            "INSERT INTO BidPages (UID, BidUID, Name, BidPageFolderUID, Sequence) "
            "VALUES (25, 1, 'P-f', 14, 1)",
            "DELETE FROM BidPages WHERE UID=25",
        )
        folders, loose = self.structure(connection)
        self.assertEqual(list(folders), ["11", "15", "10"])
        self.assertEqual(
            (folders["11"].name, folders["11"].description, folders["11"].parent_uid),
            ("Alpha", "ad", None),
        )
        self.assertEqual([page.uid for page in folders["11"].pages], ["22"])
        self.assertEqual([page.uid for page in folders["15"].pages], ["23"])
        self.assertEqual(folders["15"].parent_uid, "999")
        top = folders["10"]
        self.assertEqual(
            (top.name, top.description, top.parent_uid), ("Zeta", "zd", None)
        )
        self.assertEqual(top.pages, [])
        self.assertEqual(list(top.subfolders), ["13", "12"])
        self.assertEqual(
            (top.subfolders["13"].name, top.subfolders["13"].description),
            ("Child A", "cd"),
        )
        self.assertEqual(top.subfolders["13"].parent_uid, "10")
        self.assertEqual(top.subfolders["12"].description, "")
        self.assertEqual([p.uid for p in top.subfolders["13"].pages], ["20"])
        self.assertEqual([p.uid for p in top.subfolders["12"].pages], ["21"])
        self.assertEqual([page.uid for page in loose], ["24"])

    def test_page_structure_without_a_folder_table_lists_pages_loose(self):
        connection = self.connection(
            f"CREATE TABLE BidPages ({_FULL_PAGE_COLUMNS})",
            "INSERT INTO BidPages (UID, BidUID, BidPageFolderUID) VALUES (20, 1, 10)",
        )
        folders, loose = self.structure(connection)
        self.assertEqual((folders, [page.uid for page in loose]), ({}, ["20"]))

    def test_hierarchy_requires_each_structural_column(self):
        columns = {
            "BidProjects": ["UID", "Name"],
            "Bids": ["UID", "JobName"],
            "BidPages": ["UID", "BidUID"],
            "BidConditions": ["UID", "BidUID"],
        }
        for table, column in (
            ("BidProjects", "UID"),
            ("BidProjects", "Name"),
            ("Bids", "UID"),
            ("Bids", "JobName"),
            ("BidPages", "UID"),
            ("BidPages", "BidUID"),
            ("BidConditions", "UID"),
            ("BidConditions", "BidUID"),
        ):
            with self.subTest(table=table, column=column):
                connection = sqlite3.connect(":memory:")
                self.addCleanup(connection.close)
                for name, names in columns.items():
                    present = [c for c in names if (name, c) != (table, column)]
                    connection.execute(f"CREATE TABLE {name} ({', '.join(present)})")
                with self.assertRaisesRegex(RuntimeError, f"Missing {table}.{column}"):
                    _SqliteHierarchyReader(connection)._parse_hierarchy(
                        _SqliteConnection(connection), "x.mdb"
                    )

    def test_folder_tables_require_their_structural_columns(self):
        for column in ("UID", "BidUID", "Name"):
            with self.subTest(column=column):
                present = [c for c in ("UID", "BidUID", "Name") if c != column]
                connection = self.connection(
                    f"CREATE TABLE BidPageFolders ({', '.join(present)})",
                    f"CREATE TABLE BidPages ({_FULL_PAGE_COLUMNS})",
                )
                with self.assertRaisesRegex(
                    RuntimeError, f"Missing BidPageFolders.{column}"
                ):
                    self.structure(connection)

    def test_full_hierarchy_maps_every_bid_field_and_orders_bids_and_projects(self):
        connection = self.connection(
            "CREATE TABLE BidProjects (UID INTEGER, Name TEXT, Description TEXT)",
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, "
            "OrigBidProjectUID INTEGER, JobName TEXT, JobID TEXT, BidNo INTEGER, "
            "BidDate TEXT, Notes BLOB, JobStatusUID INTEGER, EstimatorUID INTEGER, "
            "CopyFromBidNO INTEGER, CopyTimeStamp TEXT, MeasureBase INTEGER, "
            "TakeoffIncrements REAL)",
            f"CREATE TABLE BidPages ({_FULL_PAGE_COLUMNS})",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "CREATE TABLE Employees (UID INTEGER, FirstName TEXT, LastName TEXT)",
            "INSERT INTO BidProjects VALUES (2, 'Beta', 'd2')",
            "INSERT INTO BidProjects VALUES (1, 'Alpha', 'd1')",
            "INSERT INTO BidProjects VALUES (3, 'Alpha', NULL)",
            "INSERT INTO Bids VALUES (10, 1, 7, 'B10', 'J10', 2, '2024-05-01', "
            "X'6E6F7465207465FA', 5, 6, 3, 'ts', 1, 0.5)",
            "INSERT INTO Bids VALUES (11, 1, 0, 'B11', NULL, 1, NULL, NULL, 0, 0, "
            "NULL, NULL, NULL, 0)",
            "INSERT INTO Bids VALUES (12, 2, NULL, 'B12', 'J12', 0, NULL, 'plain', "
            "77, 99, 4, NULL, 2, 2.5)",
            "INSERT INTO Bids VALUES (13, 99, NULL, 'Lost', NULL, 0, NULL, NULL, NULL, "
            "NULL, NULL, NULL, NULL, NULL)",
            "INSERT INTO Bids VALUES (14, 0, NULL, 'Free', NULL, 0, NULL, NULL, NULL, "
            "NULL, NULL, NULL, NULL, NULL)",
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (20, 10, 'p')",
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (21, 10, 'q')",
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (22, 12, 'r')",
            "INSERT INTO BidConditions VALUES (30, 10)",
            "INSERT INTO BidConditions VALUES (31, 10)",
            "INSERT INTO BidConditions VALUES (32, 10)",
            "INSERT INTO JobStatuses VALUES (5, 'Won')",
            "INSERT INTO Employees VALUES (6, 'Eve', 'Estimator')",
        )
        entry = _SqliteHierarchyReader(connection)._parse_hierarchy(
            _SqliteConnection(connection), "C:/data/dir/sample.mdb"
        )
        self.assertEqual(entry.file_path, "")
        self.assertEqual(entry.database_name, "sample")
        self.assertEqual(list(entry.bid_projects), ["1", "3", "2"])
        self.assertEqual(
            [
                (p.name, p.description)
                for p in (entry.bid_projects[uid] for uid in ("1", "3", "2"))
            ],
            [("Alpha", "d1"), ("Alpha", ""), ("Beta", "d2")],
        )
        alpha = entry.bid_projects["1"]
        self.assertEqual([bid.uid for bid in alpha.bids], ["11", "10"])
        ten = alpha.bids[1]
        self.assertEqual(
            ten,
            HierarchyBidInfo(
                uid="10",
                name="B10",
                job_id="J10",
                bid_no=2,
                bid_date="2024-05-01",
                notes="note te\ufffd",
                status="Won",
                status_uid="5",
                estimator="Eve Estimator",
                page_count=2,
                condition_count=3,
                measure_base=1,
                takeoff_increments=0.5,
                orig_bid_project_uid="7",
                copy_from_bid_no=3,
                copy_timestamp="ts",
                folders={},
                pages_without_folder=ten.pages_without_folder,
            ),
        )
        self.assertEqual([page.uid for page in ten.pages_without_folder], ["20", "21"])
        eleven = alpha.bids[0]
        self.assertEqual(
            (
                eleven.job_id,
                eleven.bid_no,
                eleven.bid_date,
                eleven.notes,
                eleven.status,
                eleven.status_uid,
                eleven.estimator,
                eleven.page_count,
                eleven.condition_count,
                eleven.measure_base,
                eleven.takeoff_increments,
                eleven.orig_bid_project_uid,
                eleven.copy_from_bid_no,
                eleven.copy_timestamp,
            ),
            ("", 1, None, "", "", "0", "", 0, 0, 0, 1.0, None, 0, None),
        )
        twelve = entry.bid_projects["2"].bids[0]
        self.assertEqual(
            (
                twelve.notes,
                twelve.status,
                twelve.status_uid,
                twelve.estimator,
                twelve.measure_base,
                twelve.takeoff_increments,
                twelve.copy_from_bid_no,
            ),
            ("plain", "", "77", "", 2, 2.5, 4),
        )
        self.assertEqual(entry.bid_projects["3"].bids, [])
        self.assertEqual([bid.uid for bid in entry.orphan_bids], ["14", "13"])
        self.assertEqual(
            [(bid.name, bid.status_uid) for bid in entry.orphan_bids],
            [("Free", None), ("Lost", None)],
        )

    def test_minimal_schema_hierarchy_uses_documented_defaults(self):
        connection = self.connection(
            "CREATE TABLE BidProjects (UID INTEGER, Name TEXT)",
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidProjects VALUES (1, 'P')",
            "INSERT INTO Bids VALUES (9, 'Only')",
            "INSERT INTO Bids VALUES (8, 'Earlier')",
        )
        entry = _SqliteHierarchyReader(connection)._parse_hierarchy(
            _SqliteConnection(connection), "min.mdb"
        )
        self.assertEqual(entry.bid_projects["1"].description, "")
        self.assertEqual(entry.bid_projects["1"].bids, [])
        self.assertEqual(
            entry.orphan_bids,
            [
                HierarchyBidInfo(
                    uid="8", name="Earlier", bid_no=0, takeoff_increments=1.0
                ),
                HierarchyBidInfo(
                    uid="9", name="Only", bid_no=0, takeoff_increments=1.0
                ),
            ],
        )

    def test_status_and_employee_maps_require_their_identity_columns(self):
        for load, table, setup in (
            (
                "_load_status_map",
                "JobStatuses",
                "CREATE TABLE JobStatuses (UID INTEGER)",
            ),
            (
                "_load_status_map",
                "JobStatuses",
                "CREATE TABLE JobStatuses (Name TEXT)",
            ),
            ("_load_employee_map", "Employees", "CREATE TABLE Employees (Name TEXT)"),
        ):
            with self.subTest(load=load, setup=setup):
                connection = self.connection(setup)
                ops = _SqliteMdbOps(connection)
                missing = "UID" if "UID" not in setup else "Name"
                with self.assertRaisesRegex(RuntimeError, f"Missing {table}.{missing}"):
                    getattr(MdbReader, load)(ops, _SqliteConnectionWrapper(connection))

    def test_employee_map_without_name_columns_yields_blank_names(self):
        connection = self.connection(
            "CREATE TABLE Employees (UID INTEGER, FirstName TEXT)",
            "INSERT INTO Employees VALUES (3, ' Ann ')",
            "INSERT INTO Employees VALUES (4, NULL)",
        )
        self.assertEqual(
            MdbReader._load_employee_map(
                _SqliteMdbOps(connection), _SqliteConnectionWrapper(connection)
            ),
            {"3": "Ann", "4": ""},
        )

    def test_folder_whose_parent_uid_is_one_nests_under_it(self):
        connection = self.connection(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "ParentUID INTEGER)",
            f"CREATE TABLE BidPages ({_FULL_PAGE_COLUMNS})",
            "INSERT INTO BidPageFolders VALUES (1, 1, 'Root', NULL)",
            "INSERT INTO BidPageFolders VALUES (2, 1, 'Kid', 1)",
            "INSERT INTO BidPages (UID, BidUID, BidPageFolderUID) VALUES (20, 1, 2)",
        )
        folders, loose = self.structure(connection)
        self.assertEqual(list(folders), ["1"])
        self.assertEqual(folders["1"].parent_uid, None)
        self.assertEqual(list(folders["1"].subfolders), ["2"])
        self.assertEqual(folders["1"].subfolders["2"].parent_uid, "1")
        self.assertEqual(loose, [])

    def test_a_textual_zero_parent_uid_is_a_root_folder(self):
        # Hand-built rows: some drivers hand ParentUID back as text.
        page = _PageRow(20, "P", 10, "S", 1, "p.pdf", 1.0, 1.0, 1.0, 1.0, 0, 0, 0, 1)
        folders, loose = _Reader()._get_bid_folder_page_structure(
            _Connection([(10, "Top", "", "0")], [page]), "1", _Schema()
        )
        self.assertEqual(list(folders), ["10"])
        self.assertEqual(folders["10"].parent_uid, "0")
        self.assertEqual([p.uid for p in folders["10"].pages], ["20"])
        self.assertEqual(loose, [])

    def test_bids_with_equal_project_and_number_are_ordered_by_uid(self):
        connection = self.connection(
            "CREATE TABLE BidProjects (UID INTEGER, Name TEXT)",
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, JobName TEXT, "
            "BidNo INTEGER)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidProjects VALUES (1, 'P')",
            "INSERT INTO Bids VALUES (12, 1, 'third', 5)",
            "INSERT INTO Bids VALUES (10, 1, 'first', 5)",
            "INSERT INTO Bids VALUES (11, 1, 'second', 5)",
        )
        entry = _SqliteHierarchyReader(connection)._parse_hierarchy(
            _SqliteConnection(connection), "x.mdb"
        )
        self.assertEqual(
            [bid.uid for bid in entry.bid_projects["1"].bids], ["10", "11", "12"]
        )

    def test_folders_without_a_parent_column_are_all_roots(self):
        connection = self.connection(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
            f"CREATE TABLE BidPages ({_FULL_PAGE_COLUMNS})",
            "INSERT INTO BidPageFolders VALUES (10, 1, 'A')",
            "INSERT INTO BidPageFolders VALUES (11, 1, 'B')",
            "INSERT INTO BidPages (UID, BidUID, BidPageFolderUID) VALUES (20, 1, 10)",
            "INSERT INTO BidPages (UID, BidUID, BidPageFolderUID) VALUES (21, 1, 11)",
        )
        folders, loose = self.structure(connection)
        self.assertEqual(list(folders), ["10", "11"])
        self.assertEqual(
            [(f.description, f.parent_uid, f.subfolders) for f in folders.values()],
            [("", None, {}), ("", None, {})],
        )
        self.assertEqual(loose, [])

    def test_pages_without_a_uid_column_are_rejected_as_malformed(self):
        connection = self.connection(
            "CREATE TABLE BidPages (BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidPages VALUES (1, 'orphan row')",
        )
        with self.assertRaisesRegex(
            RuntimeError, "BidPages contains malformed UID <missing>"
        ):
            self.structure(connection)

    def test_pages_with_equal_sequence_and_name_are_ordered_by_uid(self):
        connection = self.connection(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Sequence INTEGER)",
            "INSERT INTO BidPages VALUES (32, 1, 'Same', 4)",
            "INSERT INTO BidPages VALUES (30, 1, 'Same', 4)",
            "INSERT INTO BidPages VALUES (31, 1, 'Same', 4)",
        )
        _folders, loose = self.structure(connection)
        self.assertEqual([page.uid for page in loose], ["30", "31", "32"])

    def test_page_query_without_any_sort_column_reaches_the_uid_guard(self):
        # Without Sequence, Name and UID the ORDER BY fallback "[UID]" resolves to
        # the NULL default alias, so the malformed-UID guard (not an SQL error)
        # reports it.
        connection = self.connection(
            "CREATE TABLE BidPages (BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (1)",
        )
        with self.assertRaisesRegex(
            RuntimeError, "BidPages contains malformed UID <missing>"
        ):
            self.structure(connection)

    def test_status_map_reads_with_the_exact_select_statement(self):
        connection = self.connection(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "INSERT INTO JobStatuses VALUES (1, 'Open')",
        )
        statements = []
        connection.set_trace_callback(statements.append)
        MdbReader._load_status_map(
            _SqliteMdbOps(connection), _SqliteConnectionWrapper(connection)
        )
        self.assertIn("SELECT [UID], [Name] FROM [JobStatuses]", statements)

    def test_employee_map_without_a_first_name_column_uses_last_names(self):
        connection = self.connection(
            "CREATE TABLE Employees (UID INTEGER, LastName TEXT)",
            "INSERT INTO Employees VALUES (3, ' Lee ')",
        )
        self.assertEqual(
            MdbReader._load_employee_map(
                _SqliteMdbOps(connection), _SqliteConnectionWrapper(connection)
            ),
            {"3": "Lee"},
        )
