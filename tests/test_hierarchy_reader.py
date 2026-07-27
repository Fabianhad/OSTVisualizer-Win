import unittest
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
        return None

    def optional_column(self, _table, column, _default):
        return f"[{column}]"

    def order_by_existing(self, _table, _columns, fallback):
        return fallback


class _Reader(HierarchyReaderMixin):
    pass


class HierarchyReaderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
