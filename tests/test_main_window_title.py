import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.config import MAIN_WINDOW_TITLE
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.utils.window_title import format_main_window_title

TEST_DB_NAME = "OST Projects.mdb"
TEST_DB_PATH = rf"C:\jobs\{TEST_DB_NAME}"
TEST_BID_UID = "bid-24"
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


class MainWindowTitleRefreshTests(unittest.TestCase):
    def _window(self, selected_file_path=None, bid_ref=None, bid=None):
        titles = []

        class UiState:
            @property
            def selected_file_path(self):
                return selected_file_path

            def get_selected_bid_ref(self):
                return bid_ref

        class ProjectData:
            def __init__(self):
                self.get_bid_calls = []

            def get_bid(self, ref):
                self.get_bid_calls.append(ref)
                return bid

        project_data = ProjectData()
        window = SimpleNamespace(
            ui_state_manager=UiState(),
            _project_data_service=project_data,
            setWindowTitle=titles.append,
        )
        return window, titles, project_data

    def test_refresh_uses_default_when_nothing_selected(self):
        window, titles, _project_data = self._window()
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [MAIN_WINDOW_TITLE])

    def test_refresh_uses_selected_database_for_database_or_folder(self):
        window, titles, _project_data = self._window(
            selected_file_path=TEST_DB_PATH,
        )
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [_database_title()])

    def test_refresh_uses_selected_bid_ref_and_loaded_bid_metadata(self):
        bid_ref = BidRef(TEST_DB_PATH, TEST_BID_UID)
        bid = Bid(uid=TEST_BID_UID, name=TEST_BID_NAME, bid_no=TEST_BID_NO)
        window, titles, project_data = self._window(bid_ref=bid_ref, bid=bid)
        MainWindow.refresh_window_title(window)
        self.assertEqual(project_data.get_bid_calls, [bid_ref])
        self.assertEqual(
            titles,
            [_bid_title(f"[{TEST_BID_NO}] {TEST_BID_NAME}")],
        )

    def test_orphaned_bid_uses_same_bid_title_format(self):
        bid_ref = BidRef(TEST_DB_PATH, "orphan-bid")
        bid = Bid(uid="orphan-bid", name="Orphaned Project", bid_no=7)
        window, titles, _project_data = self._window(bid_ref=bid_ref, bid=bid)
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [_bid_title("[7] Orphaned Project")])

    def test_refresh_falls_back_to_database_title_when_bid_metadata_missing(self):
        bid_ref = BidRef(TEST_DB_PATH, "missing-bid")
        window, titles, _project_data = self._window(bid_ref=bid_ref, bid=None)
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [_database_title()])

    def test_switching_from_bid_to_folder_removes_bid_prefix(self):
        titles = []
        bid_ref = BidRef(TEST_DB_PATH, TEST_BID_UID)
        bid = Bid(uid=TEST_BID_UID, name=TEST_BID_NAME, bid_no=TEST_BID_NO)

        class UiState:
            selected_file_path = TEST_DB_PATH

            def __init__(self):
                self.bid_ref = bid_ref

            def get_selected_bid_ref(self):
                return self.bid_ref

        class ProjectData:
            def get_bid(self, _ref):
                return bid

        window = SimpleNamespace(
            ui_state_manager=UiState(),
            _project_data_service=ProjectData(),
            setWindowTitle=titles.append,
        )
        MainWindow.refresh_window_title(window)
        window.ui_state_manager.bid_ref = None
        MainWindow.refresh_window_title(window)
        self.assertEqual(
            titles,
            [
                _bid_title(f"[{TEST_BID_NO}] {TEST_BID_NAME}"),
                _database_title(),
            ],
        )

    def test_opened_database_title_uses_event_file_path(self):
        titles = []
        window = SimpleNamespace(setWindowTitle=titles.append)
        MainWindow.set_database_window_title(window, TEST_DB_PATH)
        self.assertEqual(titles, [_database_title()])


if __name__ == "__main__":
    unittest.main()
