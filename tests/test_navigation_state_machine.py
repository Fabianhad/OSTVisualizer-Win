import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavState,
    NavigationStateMachine,
)


class FakeUiState:
    selected_page_uids = ["p1"]
    active_page_uid = "p1"
    highlighted_condition_uids = {"c1"}
    selected_project_uid = "project-1"
    selected_file_path = "a.mdb"
    place_condition_uid = "c1"
    place_condition_uids = ["c1"]

    def __init__(self, bid_ref=None, database_selected=False):
        self._bid_ref = bid_ref
        self._database_selected = database_selected

    def get_selected_bid_ref(self):
        return self._bid_ref

    def is_database_selected(self):
        return self._database_selected


class FakePlacement:
    def __init__(self, active=False):
        self.is_active = active


class NavigationStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(
            "ost_visualizer.presentation.coordinators.navigation_state_machine"
        )

    def test_rejects_bid_transition_before_file_initialization(self):
        nav = NavigationStateMachine()
        with self.assertLogs(self.logger, level="WARNING"):
            self.assertFalse(nav.transition_to(NavState.BID_ACTIVE_NO_PAGES))
        self.assertEqual(nav.current_state, NavState.NO_FILE)

    def test_repeated_no_file_transition_is_idempotent(self):
        nav = NavigationStateMachine()
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertTrue(nav.transition_to(NavState.NO_FILE))
        self.assertEqual(nav.current_state, NavState.NO_FILE)

    def test_valid_navigation_flow_and_same_state_transitions_work(self):
        nav = NavigationStateMachine()
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertTrue(nav.transition_to(NavState.FILE_LOADED_NO_BID))
            self.assertTrue(nav.transition_to(NavState.FILE_LOADED_NO_BID))
            self.assertTrue(nav.transition_to(NavState.BID_ACTIVE_NO_PAGES))
            self.assertTrue(nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED))
            self.assertTrue(nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED))
            self.assertTrue(nav.transition_to(NavState.PLACE_MODE))
            self.assertTrue(nav.transition_to(NavState.PLACE_MODE))
            self.assertTrue(nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED))
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_PAGES_SELECTED)

    def test_start_refresh_before_file_loaded_is_rejected(self):
        nav = NavigationStateMachine()
        with self.assertLogs(self.logger, level="WARNING"):
            self.assertFalse(nav.start_refresh(FakeUiState(), FakePlacement()))
        self.assertEqual(nav.current_state, NavState.NO_FILE)
        self.assertIsNone(nav.refresh_snapshot)

    def test_duplicate_refresh_start_is_rejected_and_preserves_snapshot(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        bid_ref = SimpleNamespace(file_path="a.mdb", bid_uid="b1")
        self.assertTrue(nav.start_refresh(FakeUiState(bid_ref), FakePlacement()))
        snapshot = nav.refresh_snapshot
        with self.assertLogs(self.logger, level="WARNING"):
            self.assertFalse(nav.start_refresh(FakeUiState(), FakePlacement()))
        self.assertEqual(nav.current_state, NavState.REFRESHING)
        self.assertIs(nav.refresh_snapshot, snapshot)

    def test_direct_transition_out_of_refreshing_is_rejected(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.assertTrue(nav.start_refresh(FakeUiState(), FakePlacement()))
        targets = [
            NavState.NO_FILE,
            NavState.FILE_LOADED_NO_BID,
            NavState.BID_ACTIVE_NO_PAGES,
            NavState.BID_ACTIVE_PAGES_SELECTED,
            NavState.PLACE_MODE,
        ]
        for target in targets:
            with self.subTest(target=target), self.assertLogs(
                self.logger, level="WARNING"
            ):
                self.assertFalse(nav.transition_to(target))
            self.assertEqual(nav.current_state, NavState.REFRESHING)
            self.assertIsNotNone(nav.refresh_snapshot)
        self.assertEqual(nav.current_state, NavState.REFRESHING)
        self.assertIsNotNone(nav.refresh_snapshot)

    def test_finish_without_active_refresh_is_rejected_without_state_corruption(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        with self.assertLogs(self.logger, level="WARNING"):
            self.assertFalse(nav.finish_refresh(NavState.BID_ACTIVE_PAGES_SELECTED))
        self.assertEqual(nav.current_state, NavState.FILE_LOADED_NO_BID)
        self.assertIsNone(nav.refresh_snapshot)

    def test_finish_refresh_transitions_to_target_and_clears_snapshot(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        bid_ref = SimpleNamespace(file_path="a.mdb", bid_uid="b1")
        self.assertTrue(nav.start_refresh(FakeUiState(bid_ref), FakePlacement()))
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertTrue(nav.finish_refresh(NavState.BID_ACTIVE_PAGES_SELECTED))
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_PAGES_SELECTED)
        self.assertIsNone(nav.refresh_snapshot)

    def test_finish_refresh_to_invalid_target_recovers_to_no_file(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.assertTrue(nav.start_refresh(FakeUiState(), FakePlacement()))
        with self.assertLogs(self.logger, level="ERROR"):
            self.assertFalse(nav.finish_refresh(NavState.REFRESHING))
        self.assertEqual(nav.current_state, NavState.NO_FILE)
        self.assertIsNone(nav.refresh_snapshot)


if __name__ == "__main__":
    unittest.main()
