import unittest
from ost_visualizer.presentation.config import MAIN_WINDOW_TITLE
from ost_visualizer.presentation.utils.window_title import format_main_window_title

TEST_DB_NAME = "OST Projects.mdb"
TEST_DB_PATH = rf"C:\jobs\{TEST_DB_NAME}"
TEST_BID_NO = 24
TEST_BID_NAME = "26-040 Dulles Plaza, VA"


def _database_title(database_name=TEST_DB_NAME):
    return f"{database_name} - {MAIN_WINDOW_TITLE}"


def _bid_title(bid_label, database_name=TEST_DB_NAME):
    return f"{bid_label}; {_database_title(database_name)}"


class MainWindowTitleFormatterTests(unittest.TestCase):
    def test_no_database_uses_default_title(self):
        self.assertEqual(format_main_window_title(None), MAIN_WINDOW_TITLE)

    def test_path_without_filename_uses_default_title(self):
        self.assertEqual(format_main_window_title(r"C:\\"), MAIN_WINDOW_TITLE)

    def test_database_selection_uses_filename_and_app_title(self):
        title = format_main_window_title(TEST_DB_PATH)
        self.assertEqual(title, _database_title())

    def test_bid_selection_uses_bid_number_name_database_and_app_title(self):
        title = format_main_window_title(
            TEST_DB_PATH,
            bid_no=TEST_BID_NO,
            bid_name=TEST_BID_NAME,
        )
        self.assertEqual(
            title,
            _bid_title(f"[{TEST_BID_NO}] {TEST_BID_NAME}"),
        )

    def test_bid_number_already_bracketed_is_not_double_wrapped(self):
        title = format_main_window_title(
            "OST Projects.mdb",
            bid_no="[24]",
            bid_name=TEST_BID_NAME,
        )
        self.assertTrue(title.startswith(f"[{TEST_BID_NO}] {TEST_BID_NAME};"))

    def test_missing_bid_number_or_name_is_omitted_cleanly(self):
        self.assertEqual(
            format_main_window_title(
                "OST Projects.mdb",
                bid_no=0,
                bid_name=TEST_BID_NAME,
            ),
            _bid_title(TEST_BID_NAME),
        )
        self.assertEqual(
            format_main_window_title("OST Projects.mdb", bid_no=24, bid_name=""),
            _bid_title("[24]"),
        )
