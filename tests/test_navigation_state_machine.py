import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
    NavState,
)
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
    PlacementState,
)
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    PlanSurfaceAccessState,
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


def _empty_color_mapping(
    _bid_conditions,
    _bid_takeoffs,
    _display_mode="solid",
    _grayscale_enabled=True,
    extra_condition_uids=None,
):
    return {}, {}


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

    def test_placement_coordinator_blocks_place_mode_when_bid_has_no_pages(self):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        ui_state = SimpleNamespace(
            active_page_uid=None,
            selected_page_uids=[],
            place_condition_uid=None,
            set_place_condition_uids=lambda _uids: None,
            clear_place_condition=lambda: None,
            state=SimpleNamespace(
                display_mode_2d="condition",
                display_mode_3d="condition",
                display_modes_synced=True,
                grayscale_enabled=False,
            ),
        )
        plan_view = SimpleNamespace(
            activate_place_for_condition=lambda _condition_uid, _condition_uids: True,
            update_color_map=lambda _color_map: None,
            cancel_place_mode=lambda: None,
        )
        project_data = SimpleNamespace(
            get_bid_conditions=lambda: {
                "c1": Condition(
                    uid="c1",
                    name="Area",
                    condition_type=Condition.TYPE_AREA,
                )
            },
            get_page_takeoffs=lambda _page_uid: [],
        )
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
            project_data=project_data,
        )
        placement._plan_view = plan_view
        placement.set_nav(nav)
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertFalse(placement.enter("c1", ["c1"]))
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_placement_coordinator_ignores_stale_active_page_when_nav_has_no_pages(
        self,
    ):
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        ui_state = SimpleNamespace(
            active_page_uid="stale-page",
            selected_page_uids=[],
            place_condition_uid=None,
            set_place_condition_uids=lambda _uids: None,
            clear_place_condition=lambda: None,
            state=SimpleNamespace(
                display_mode_2d="condition",
                display_mode_3d="condition",
                display_modes_synced=True,
                grayscale_enabled=False,
            ),
        )
        place_calls = []
        plan_view = SimpleNamespace(
            activate_place_for_condition=lambda condition_uid, condition_uids: (
                place_calls.append((condition_uid, list(condition_uids))) or True
            ),
            update_color_map=lambda _color_map: None,
            cancel_place_mode=lambda: None,
        )
        project_data = SimpleNamespace(
            get_bid_conditions=lambda: {
                "c1": Condition(
                    uid="c1",
                    name="Area",
                    condition_type=Condition.TYPE_AREA,
                )
            },
            get_page_takeoffs=lambda _page_uid: [],
        )
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
            project_data=project_data,
        )
        placement._plan_view = plan_view
        placement.set_nav(nav)
        with self.assertNoLogs(self.logger, level="WARNING"):
            self.assertFalse(placement.enter("c1", ["c1"]))
        self.assertEqual(place_calls, [])
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_placement_coordinator_keeps_active_condition_in_place_list(self):
        class UiState:
            active_page_uid = "p1"
            selected_page_uids = ["p1"]
            place_condition_uid = None
            state = SimpleNamespace(
                display_mode_2d="condition",
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

        class PlanView:
            def __init__(self):
                self.place_calls = []

            def activate_place_for_condition(self, condition_uid, condition_uids):
                self.place_calls.append((condition_uid, list(condition_uids)))
                return True

            def update_color_map(self, _color_map):
                pass

        color_map_requests = []

        def record_color_map_request(
            _bid_conditions,
            _bid_takeoffs,
            _display_mode="solid",
            _grayscale_enabled=True,
            extra_condition_uids=None,
        ):
            color_map_requests.append(extra_condition_uids)
            return {}, {}

        ui_state = UiState()
        plan_view = PlanView()
        conditions = {
            "c1": Condition(
                uid="c1", layer_visible=True, condition_type=Condition.TYPE_AREA
            ),
            "c2": Condition(
                uid="c2", layer_visible=True, condition_type=Condition.TYPE_AREA
            ),
            "linear": Condition(
                uid="linear",
                layer_visible=True,
                condition_type=Condition.TYPE_LINEAR,
            ),
            "hidden": Condition(
                uid="hidden", layer_visible=False, condition_type=Condition.TYPE_AREA
            ),
        }
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=record_color_map_request),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
                get_page_takeoffs=lambda _page_uid: [],
            ),
        )
        placement._plan_view = plan_view
        self.assertTrue(placement.enter("c2", ["c1", "c1", "hidden", "linear"]))
        self.assertEqual(ui_state.place_condition_uids, ["c1", "c2"])
        self.assertEqual(plan_view.place_calls, [("c2", ["c1", "c2"])])
        self.assertEqual(color_map_requests, [{"c1", "c2"}])
        self.assertEqual(ui_state.place_condition_uid, "c2")
        self.assertTrue(placement.reconcile_authoritative_conditions())

    def test_placement_reconciliation_exits_when_primary_condition_is_retyped(self):
        class UiState:
            active_page_uid = "p1"
            place_condition_uid = None
            state = SimpleNamespace(
                display_mode_2d="condition",
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

        class PlanView:
            def __init__(self):
                self.cancel_calls = 0

            def activate_place_for_condition(self, _condition_uid, _condition_uids):
                return True

            def update_color_map(self, _color_map):
                pass

            def cancel_place_mode(self):
                self.cancel_calls += 1

        conditions = {
            "c1": Condition(
                uid="c1",
                layer_visible=True,
                condition_type=Condition.TYPE_AREA,
            )
        }
        ui_state = UiState()
        plan_view = PlanView()
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
                get_page_takeoffs=lambda _page_uid: [],
            ),
        )
        placement._plan_view = plan_view
        self.assertTrue(placement.enter("c1", ["c1"]))
        conditions["c1"] = Condition(
            uid="c1",
            layer_visible=True,
            condition_type=Condition.TYPE_LINEAR,
        )
        self.assertFalse(placement.reconcile_authoritative_conditions())
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertIsNone(ui_state.place_condition_uid)
        self.assertEqual(ui_state.place_condition_uids, [])
        self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_for_same_uid_condition_replacement(self):
        class UiState:
            active_page_uid = "p1"
            place_condition_uid = None
            state = SimpleNamespace(
                display_mode_2d="condition",
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

        class PlanView:
            def __init__(self):
                self.cancel_calls = 0

            def activate_place_for_condition(self, _condition_uid, _condition_uids):
                return True

            def update_color_map(self, _color_map):
                pass

            def cancel_place_mode(self):
                self.cancel_calls += 1

        conditions = {
            "c1": Condition(
                uid="c1",
                layer_visible=True,
                condition_type=Condition.TYPE_AREA,
            )
        }
        ui_state = UiState()
        plan_view = PlanView()
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
                get_page_takeoffs=lambda _page_uid: [],
            ),
        )
        placement._plan_view = plan_view
        self.assertTrue(placement.enter("c1", ["c1"]))
        conditions["c1"] = Condition(
            uid="c1",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        self.assertFalse(placement.reconcile_authoritative_conditions())
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertIsNone(ui_state.place_condition_uid)
        self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_when_secondary_condition_is_hidden(self):
        class UiState:
            active_page_uid = "p1"
            place_condition_uid = None
            state = SimpleNamespace(
                display_mode_2d="condition",
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

        class PlanView:
            def __init__(self):
                self.cancel_calls = 0

            def activate_place_for_condition(self, _condition_uid, _condition_uids):
                return True

            def update_color_map(self, _color_map):
                pass

            def cancel_place_mode(self):
                self.cancel_calls += 1

        conditions = {
            uid: Condition(
                uid=uid,
                layer_visible=True,
                condition_type=Condition.TYPE_AREA,
            )
            for uid in ("c1", "c2")
        }
        ui_state = UiState()
        plan_view = PlanView()
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
                get_page_takeoffs=lambda _page_uid: [],
            ),
        )
        placement._plan_view = plan_view
        self.assertTrue(placement.enter("c1", ["c1", "c2"]))
        conditions["c2"] = Condition(
            uid="c2",
            layer_visible=False,
            condition_type=Condition.TYPE_AREA,
        )
        self.assertFalse(placement.reconcile_authoritative_conditions())
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertEqual(plan_view.cancel_calls, 1)

    def test_failed_placement_replacement_cancels_previous_plan_session(self):
        class UiState:
            active_page_uid = "p1"
            place_condition_uid = None
            state = SimpleNamespace(
                display_mode_2d="condition",
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

        class PlanView:
            def __init__(self):
                self.session_uid = None
                self.available_uids = {"original"}
                self.cancel_calls = 0

            def activate_place_for_condition(self, condition_uid, _condition_uids):
                if condition_uid not in self.available_uids:
                    return False
                self.session_uid = condition_uid
                return True

            def update_color_map(self, _color_map):
                pass

            def cancel_place_mode(self):
                self.cancel_calls += 1
                self.session_uid = None

        conditions = {
            uid: Condition(
                uid=uid,
                layer_visible=True,
                condition_type=Condition.TYPE_LINEAR,
            )
            for uid in ("original", "duplicate")
        }
        ui_state = UiState()
        plan_view = PlanView()
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
                get_page_takeoffs=lambda _page_uid: [],
            ),
        )
        placement._plan_view = plan_view
        self.assertTrue(placement.enter("original", ["original"]))
        self.assertFalse(placement.enter("duplicate", ["duplicate"]))
        self.assertIsNone(plan_view.session_uid)
        self.assertEqual(plan_view.cancel_calls, 1)
        self.assertIsNone(ui_state.place_condition_uid)
        self.assertEqual(placement.state, PlacementState.IDLE)

    def test_placement_coordinator_enters_with_active_2d_page_unchecked_for_3d(self):
        class UiState:
            active_page_uid = "p1"
            selected_page_uids = []
            place_condition_uid = None
            state = SimpleNamespace(
                display_mode_2d="condition",
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

        class PlanView:
            def __init__(self):
                self.place_calls = []

            def activate_place_for_condition(self, condition_uid, condition_uids):
                self.place_calls.append((condition_uid, list(condition_uids)))
                return True

            def update_color_map(self, _color_map):
                pass

        ui_state = UiState()
        plan_view = PlanView()
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: {
                    "c1": Condition(
                        uid="c1",
                        layer_visible=True,
                        condition_type=Condition.TYPE_AREA,
                    )
                },
                get_page_takeoffs=lambda _page_uid: [],
            ),
        )
        placement._plan_view = plan_view
        nav = NavigationStateMachine()
        nav.transition_to(NavState.FILE_LOADED_NO_BID)
        nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        placement.set_nav(nav)
        self.assertTrue(placement.enter("c1", ["c1"]))
        self.assertEqual(plan_view.place_calls, [("c1", ["c1"])])
        self.assertEqual(ui_state.place_condition_uid, "c1")
        self.assertEqual(nav.current_state, NavState.PLACE_MODE)

    def test_replacing_plan_view_disconnects_each_old_signal_independently(self):
        class Signal:
            def __init__(self, fail_disconnect=False):
                self.callbacks = []
                self.fail_disconnect = fail_disconnect

            def connect(self, callback):
                self.callbacks.append(callback)

            def disconnect(self, callback):
                if self.fail_disconnect:
                    raise RuntimeError("already disconnected")
                self.callbacks.remove(callback)

        class PlanView:
            def __init__(self, fail_place_disconnect=False):
                self.place_exited = Signal(fail_place_disconnect)
                self.area_placement_in_progress = Signal()

        placement = PlacementCoordinator(None, None, None, None)
        old_view = PlanView()
        new_view = PlanView()
        placement.set_plan_view(old_view)
        old_view.place_exited.fail_disconnect = True
        placement.set_plan_view(new_view)
        self.assertEqual(old_view.area_placement_in_progress.callbacks, [])
        self.assertEqual(len(new_view.place_exited.callbacks), 1)
        self.assertEqual(len(new_view.area_placement_in_progress.callbacks), 1)

    def test_area_placement_transition_updates_main_surface_once(self):
        transitions = []

        def record(active, *, surface_id):
            transitions.append((bool(active), surface_id))

        access = SimpleNamespace(set_area_placement_active=record)
        placement = PlacementCoordinator(None, access, None, None)
        placement._on_area_placement_changed(True)
        placement._on_area_placement_changed(True)
        placement._on_area_placement_changed(False)
        placement._on_area_placement_changed(False)
        self.assertEqual(
            transitions,
            [(True, "main-plan"), (False, "main-plan")],
        )

    def test_toolbar_disables_place_action_when_bid_has_no_active_page(self):
        class FakeAction:
            def __init__(self):
                self.enabled = None
                self.checked = False

            def setEnabled(self, enabled):
                self.enabled = enabled

            def isChecked(self):
                return self.checked

        class FakePlanView:
            has_selection = False
            current_page_uid = None
            place_condition_uid = None
            is_rotate_mode_active = False

            def selected_takeoff_condition_uid(self):
                return "c1"

            def set_selection_enabled(self, _enabled):
                pass

            def set_editing_enabled(self, _enabled):
                pass

            def set_text_annotation_inline_edit_enabled(self, _enabled):
                pass

            def is_text_annotation_inline_edit_active(self):
                return False

            def can_move_overlay_image(self):
                return False

        toolbar = ToolbarStateCoordinator(
            ui_state_manager=SimpleNamespace(
                get_selected_bid_refs=lambda: [],
                get_selected_bid_ref=lambda: None,
                selected_project_uid=None,
                selected_page_uids=[],
                active_page_uid=None,
            ),
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: True,
                is_bid_locked=lambda: False,
                has_license=lambda: True,
                current_plan_surface_context=lambda: object(),
                get_plan_surface_access=lambda _context: PlanSurfaceAccessState(),
                subscribe_access_state_changed=lambda _callback: None,
                unsubscribe_access_state_changed=lambda _callback: None,
            ),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: {
                    "c1": Condition(
                        uid="c1",
                        name="Area",
                        condition_type=Condition.TYPE_AREA,
                    )
                }
            ),
        )
        action = FakeAction()
        toolbar.set_place_action(action)
        toolbar.set_plan_view(FakePlanView())
        toolbar.set_tab_widget(SimpleNamespace(currentIndex=lambda: TAB_INDEX_TAKEOFF))
        toolbar.set_view_stack(SimpleNamespace(currentIndex=lambda: 1))
        toolbar.refresh()
        self.assertFalse(action.enabled)


if __name__ == "__main__":
    unittest.main()
