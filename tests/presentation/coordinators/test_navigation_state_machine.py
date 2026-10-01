import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
    NavState,
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

    def test_rejects_selected_page_transition_before_file_initialization(self):
        nav = NavigationStateMachine()
        with self.assertLogs(self.logger, level="WARNING"):
            self.assertFalse(nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED))
        self.assertEqual(nav.current_state, NavState.NO_FILE)

    def test_begin_bid_load_projects_required_file_stage(self):
        nav = NavigationStateMachine()
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertTrue(nav.begin_bid_load(has_file=True))
            self.assertTrue(nav.transition_to(NavState.BID_ACTIVE_NO_PAGES))
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_begin_bid_load_without_authoritative_file_is_rejected(self):
        nav = NavigationStateMachine()
        with self.assertLogs(self.logger, level="WARNING") as logs:
            self.assertFalse(nav.begin_bid_load(has_file=False))
        self.assertEqual(nav.current_state, NavState.NO_FILE)
        self.assertIn("without a loaded file", logs.output[0])

    def test_begin_bid_load_during_refresh_is_rejected(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.assertTrue(nav.start_refresh(FakeUiState(), FakePlacement()))
        snapshot = nav.refresh_snapshot
        with self.assertLogs(self.logger, level="WARNING"):
            self.assertFalse(nav.begin_bid_load(has_file=True))
        self.assertEqual(nav.current_state, NavState.REFRESHING)
        self.assertIs(nav.refresh_snapshot, snapshot)

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

    def test_complete_direct_transition_matrix_remains_explicit(self):
        allowed = {
            NavState.NO_FILE: {
                NavState.NO_FILE,
                NavState.FILE_LOADED_NO_BID,
            },
            NavState.FILE_LOADED_NO_BID: {
                NavState.NO_FILE,
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
            },
            NavState.BID_ACTIVE_NO_PAGES: {
                NavState.NO_FILE,
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
                NavState.BID_ACTIVE_PAGES_SELECTED,
            },
            NavState.BID_ACTIVE_PAGES_SELECTED: {
                NavState.NO_FILE,
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
                NavState.BID_ACTIVE_PAGES_SELECTED,
                NavState.PLACE_MODE,
            },
            NavState.PLACE_MODE: {
                NavState.NO_FILE,
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
                NavState.BID_ACTIVE_PAGES_SELECTED,
                NavState.PLACE_MODE,
            },
            NavState.REFRESHING: set(),
        }

        def machine_in(source):
            nav = NavigationStateMachine()
            if source == NavState.NO_FILE:
                return nav
            nav.transition_to(NavState.FILE_LOADED_NO_BID)
            if source == NavState.FILE_LOADED_NO_BID:
                return nav
            if source == NavState.REFRESHING:
                nav.start_refresh(FakeUiState(), FakePlacement())
                return nav
            nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
            if source == NavState.BID_ACTIVE_NO_PAGES:
                return nav
            nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
            if source == NavState.BID_ACTIVE_PAGES_SELECTED:
                return nav
            nav.transition_to(NavState.PLACE_MODE)
            return nav

        for source in NavState:
            for target in NavState:
                with self.subTest(source=source, target=target):
                    nav = machine_in(source)
                    self.assertEqual(nav.current_state, source)
                    if target in allowed[source]:
                        with self.assertNoLogs(self.logger, level="WARNING"):
                            self.assertTrue(nav.transition_to(target))
                        self.assertEqual(nav.current_state, target)
                    else:
                        with self.assertLogs(self.logger, level="WARNING"):
                            self.assertFalse(nav.transition_to(target))
                        self.assertEqual(nav.current_state, source)

    def test_begin_bid_load_preserves_existing_bid_during_slow_replacement(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertTrue(nav.begin_bid_load(has_file=True))
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_PAGES_SELECTED)

    def test_refresh_entry_is_owned_only_by_atomic_start_refresh(self):
        source_paths = {
            NavState.FILE_LOADED_NO_BID: [NavState.FILE_LOADED_NO_BID],
            NavState.BID_ACTIVE_NO_PAGES: [
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
            ],
            NavState.BID_ACTIVE_PAGES_SELECTED: [
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
                NavState.BID_ACTIVE_PAGES_SELECTED,
            ],
            NavState.PLACE_MODE: [
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
                NavState.BID_ACTIVE_PAGES_SELECTED,
                NavState.PLACE_MODE,
            ],
        }
        for source, path in source_paths.items():
            with self.subTest(source=source):
                nav = NavigationStateMachine()
                for state in path:
                    nav.transition_to(state)
                with self.assertLogs(self.logger, level="WARNING"):
                    self.assertFalse(nav.transition_to(NavState.REFRESHING))
                with self.assertNoLogs(self.logger, level="WARNING"):
                    self.assertTrue(nav.start_refresh(FakeUiState(), FakePlacement()))
                self.assertEqual(nav.current_state, NavState.REFRESHING)
                self.assertIsNotNone(nav.refresh_snapshot)

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

    def test_state_computation_uses_active_2d_page_not_3d_checked_pages(self):
        bid_ref = SimpleNamespace(file_path="a.mdb", bid_uid="b1")
        nav = NavigationStateMachine()
        self.assertEqual(
            nav.compute_state_for(
                has_file=True,
                bid_ref=bid_ref,
                active_page_uid="p1",
            ),
            NavState.BID_ACTIVE_PAGES_SELECTED,
        )
        self.assertEqual(
            nav.compute_state_for(
                has_file=True,
                bid_ref=bid_ref,
                active_page_uid=None,
            ),
            NavState.BID_ACTIVE_NO_PAGES,
        )
        self.assertEqual(
            nav.compute_state_for(
                has_file=True,
                bid_ref=None,
                active_page_uid="p1",
            ),
            NavState.FILE_LOADED_NO_BID,
        )
        self.assertEqual(
            nav.compute_state_for(
                has_file=False,
                bid_ref=bid_ref,
                active_page_uid="p1",
            ),
            NavState.NO_FILE,
        )

    def test_begin_bid_load_keeps_every_loaded_state_unchanged(self):
        paths = {
            NavState.FILE_LOADED_NO_BID: [NavState.FILE_LOADED_NO_BID],
            NavState.BID_ACTIVE_NO_PAGES: [
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
            ],
            NavState.PLACE_MODE: [
                NavState.FILE_LOADED_NO_BID,
                NavState.BID_ACTIVE_NO_PAGES,
                NavState.BID_ACTIVE_PAGES_SELECTED,
                NavState.PLACE_MODE,
            ],
        }
        for source, path in paths.items():
            with self.subTest(source=source):
                nav = NavigationStateMachine()
                for state in path:
                    nav.transition_to(state)
                with self.assertNoLogs(self.logger, level="WARNING"):
                    self.assertTrue(nav.begin_bid_load(has_file=True))
                self.assertEqual(nav.current_state, source)
                with self.assertLogs(self.logger, level="WARNING"):
                    self.assertFalse(nav.begin_bid_load(has_file=False))
                self.assertEqual(nav.current_state, source)

    def test_start_refresh_snapshots_selection_and_placement_only_when_active(self):
        bid_ref = BidRef("a.mdb", "b1")
        ui_state = FakeUiState(bid_ref, database_selected=True)
        for placement_active in (True, False):
            with self.subTest(placement_active=placement_active):
                nav = NavigationStateMachine()
                nav.transition_to(NavState.FILE_LOADED_NO_BID)
                self.assertTrue(
                    nav.start_refresh(
                        ui_state,
                        FakePlacement(active=placement_active),
                        selected_area_uid="area-1",
                    )
                )
                snapshot = nav.refresh_snapshot
                self.assertEqual(snapshot.bid_ref, bid_ref)
                self.assertEqual(snapshot.page_uids, ["p1"])
                self.assertIsNot(snapshot.page_uids, ui_state.selected_page_uids)
                self.assertEqual(snapshot.active_page_uid, "p1")
                self.assertEqual(snapshot.highlighted_condition_uids, {"c1"})
                self.assertEqual(snapshot.project_uid, "project-1")
                self.assertTrue(snapshot.database_selected)
                self.assertEqual(snapshot.selected_file_path, "a.mdb")
                self.assertEqual(snapshot.selected_area_uid, "area-1")
                if placement_active:
                    self.assertEqual(snapshot.place_condition_uid, "c1")
                    self.assertEqual(snapshot.place_condition_uids, ["c1"])
                    self.assertIsNot(
                        snapshot.place_condition_uids, ui_state.place_condition_uids
                    )
                else:
                    self.assertIsNone(snapshot.place_condition_uid)
                    self.assertEqual(snapshot.place_condition_uids, [])

    def test_start_refresh_failure_leaves_state_unchanged_and_machine_usable(self):
        class BrokenUiState(FakeUiState):
            def get_selected_bid_ref(self):
                raise RuntimeError("ui state unavailable")

        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        with self.assertRaisesRegex(RuntimeError, "ui state unavailable"):
            nav.start_refresh(BrokenUiState(), FakePlacement())
        self.assertEqual(nav.current_state, NavState.FILE_LOADED_NO_BID)
        self.assertFalse(nav.is_refreshing)
        self.assertIsNone(nav.refresh_snapshot)
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertTrue(nav.transition_to(NavState.BID_ACTIVE_NO_PAGES))
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_finish_refresh_reaches_every_valid_target(self):
        targets = [
            NavState.NO_FILE,
            NavState.FILE_LOADED_NO_BID,
            NavState.BID_ACTIVE_NO_PAGES,
            NavState.BID_ACTIVE_PAGES_SELECTED,
            NavState.PLACE_MODE,
        ]
        for target in targets:
            with self.subTest(target=target):
                nav = NavigationStateMachine()
                nav.transition_to(NavState.FILE_LOADED_NO_BID)
                self.assertTrue(nav.start_refresh(FakeUiState(), FakePlacement()))
                self.assertTrue(nav.is_refreshing)
                with self.assertNoLogs(self.logger, level="WARNING"):
                    self.assertTrue(nav.finish_refresh(target))
                self.assertEqual(nav.current_state, target)
                self.assertFalse(nav.is_refreshing)
                self.assertIsNone(nav.refresh_snapshot)

    def test_finish_refresh_after_completed_refresh_is_rejected(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.assertTrue(nav.start_refresh(FakeUiState(), FakePlacement()))
        self.assertTrue(nav.finish_refresh(NavState.BID_ACTIVE_NO_PAGES))
        with self.assertLogs(self.logger, level="WARNING"):
            self.assertFalse(nav.finish_refresh(NavState.NO_FILE))
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_NO_PAGES)
