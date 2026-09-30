import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
    NavState,
)
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
    PlacementState,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    PlanSurfaceAccessState,
)


def _empty_color_mapping(
    _bid_conditions,
    _bid_takeoffs,
    _display_mode="solid",
    _grayscale_enabled=True,
    extra_condition_uids=None,
):
    return {}, {}


class PlacementCoordinatorNavigationTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(
            "ost_visualizer.presentation.coordinators.navigation_state_machine"
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
