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
