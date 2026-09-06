import unittest
import sqlite3
from collections import namedtuple
from ost_visualizer.infrastructure.mdb.components.hierarchy_reader import (
    HierarchyReaderMixin,
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
                with self.assertRaisesRegex(RuntimeError, message):
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
                with self.assertRaisesRegex(RuntimeError, message):
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
        connection.execute("INSERT INTO BidPages VALUES (20, 1, 'A-101', 10)")
        folders, pages_without_folder = _SqliteHierarchyReader(
            connection
        )._get_bid_folder_page_structure(
            _SqliteConnection(connection),
            "1",
            _SqliteHierarchySchema(connection),
        )
        self.assertEqual(list(folders), ["10"])
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


if __name__ == "__main__":
    unittest.main()
