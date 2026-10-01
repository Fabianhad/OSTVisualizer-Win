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


class _PlacementUiState:
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


class _Signal:
    def __init__(self, fail_disconnect=False):
        self.callbacks = []
        self.fail_disconnect = fail_disconnect

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        if self.fail_disconnect:
            raise RuntimeError("already disconnected")
        self.callbacks.remove(callback)


class _PlacementPlanView:
    def __init__(self):
        self.place_calls = []
        self.cancel_calls = 0
        self.place_exited = _Signal()
        self.area_placement_in_progress = _Signal()

    def activate_place_for_condition(self, condition_uid, condition_uids):
        self.place_calls.append((condition_uid, list(condition_uids)))
        return True

    def update_color_map(self, _color_map):
        pass

    def cancel_place_mode(self):
        self.cancel_calls += 1


def _placement(conditions, *, nav=None, allowed=True, plan_view=None):
    ui_state = _PlacementUiState()
    area_transitions = []
    placement = PlacementCoordinator(
        ui_state_manager=ui_state,
        ui_access_manager=SimpleNamespace(
            is_allowed=lambda feature: allowed and feature == Feature.PLACE_PLAN_ITEMS,
            set_area_placement_active=lambda active, *, surface_id: (
                area_transitions.append((active, surface_id))
            ),
        ),
        color_service=SimpleNamespace(get_color_mapping=_empty_color_mapping),
        project_data=SimpleNamespace(
            get_bid_conditions=lambda: conditions,
            get_page_takeoffs=lambda _page_uid: [],
        ),
    )
    plan_view = plan_view if plan_view is not None else _PlacementPlanView()
    placement.set_plan_view(plan_view)
    if nav is not None:
        placement.set_nav(nav)
    return placement, ui_state, plan_view, area_transitions


def _entered_placement(conditions, condition_uid, condition_uids, **kwargs):
    placement, ui_state, plan_view, area_transitions = _placement(conditions, **kwargs)
    if not placement.enter(condition_uid, condition_uids):
        raise AssertionError("placement fixture failed to enter place mode")
    return placement, ui_state, plan_view, area_transitions


def _conditions(*uids, condition_type=Condition.TYPE_AREA, layer_visible=True):
    return {
        uid: Condition(
            uid=uid, layer_visible=layer_visible, condition_type=condition_type
        )
        for uid in uids
    }


def _nav_with_pages_selected():
    nav = NavigationStateMachine()
    nav.transition_to(NavState.FILE_LOADED_NO_BID)
    nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
    nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
    return nav


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
        self.assertEqual(placement.state, PlacementState.IDLE)
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
        self.assertEqual(placement.state, PlacementState.READY)
        self.assertTrue(placement.reconcile_authoritative_conditions())
        self.assertEqual(placement.state, PlacementState.READY)

    def test_placement_reconciliation_exits_when_primary_condition_is_retyped(self):
        # The retyped type check must hold even when reconstruction is accepted,
        # so it is not masked by the identity-replacement check.
        for accept_reconstructed in (False, True):
            with self.subTest(accept_reconstructed=accept_reconstructed):
                conditions = _conditions("c1")
                placement, ui_state, plan_view, _ = _entered_placement(
                    conditions, "c1", ["c1"]
                )
                conditions["c1"] = Condition(
                    uid="c1",
                    layer_visible=True,
                    condition_type=Condition.TYPE_LINEAR,
                )
                self.assertFalse(
                    placement.reconcile_authoritative_conditions(
                        accept_reconstructed_conditions=accept_reconstructed
                    )
                )
                self.assertEqual(placement.state, PlacementState.IDLE)
                self.assertIsNone(ui_state.place_condition_uid)
                self.assertEqual(ui_state.place_condition_uids, [])
                self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_for_same_uid_condition_replacement(self):
        conditions = _conditions("c1")
        placement, ui_state, plan_view, _ = _entered_placement(conditions, "c1", ["c1"])
        conditions["c1"] = Condition(
            uid="c1",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        self.assertFalse(placement.reconcile_authoritative_conditions())
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertIsNone(ui_state.place_condition_uid)
        self.assertEqual(ui_state.place_condition_uids, [])
        self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_adopts_matching_replacement_only_when_allowed(
        self,
    ):
        conditions = _conditions("c1", "c2")
        placement, ui_state, plan_view, _ = _entered_placement(
            conditions, "c1", ["c1", "c2"]
        )
        conditions.update(_conditions("c1", "c2"))
        self.assertTrue(
            placement.reconcile_authoritative_conditions(
                accept_reconstructed_conditions=True
            )
        )
        self.assertEqual(placement.state, PlacementState.READY)
        self.assertEqual(ui_state.place_condition_uid, "c1")
        self.assertEqual(ui_state.place_condition_uids, ["c1", "c2"])
        self.assertEqual(plan_view.cancel_calls, 0)
        # The adopted objects are now the authoritative identities.
        self.assertTrue(placement.reconcile_authoritative_conditions())
        conditions["c2"] = Condition(
            uid="c2", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        self.assertFalse(placement.reconcile_authoritative_conditions())
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_when_secondary_condition_is_hidden(self):
        # Hidden secondaries must exit even when reconstruction is accepted, so the
        # visibility check is not masked by the identity-replacement check.
        for accept_reconstructed in (False, True):
            with self.subTest(accept_reconstructed=accept_reconstructed):
                conditions = _conditions("c1", "c2")
                placement, ui_state, plan_view, _ = _entered_placement(
                    conditions, "c1", ["c1", "c2"]
                )
                conditions["c2"] = Condition(
                    uid="c2",
                    layer_visible=False,
                    condition_type=Condition.TYPE_AREA,
                )
                self.assertFalse(
                    placement.reconcile_authoritative_conditions(
                        accept_reconstructed_conditions=accept_reconstructed
                    )
                )
                self.assertEqual(placement.state, PlacementState.IDLE)
                self.assertEqual(ui_state.place_condition_uids, [])
                self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_when_secondary_condition_is_retyped(self):
        for accept_reconstructed in (False, True):
            with self.subTest(accept_reconstructed=accept_reconstructed):
                conditions = _conditions("c1", "c2")
                placement, _ui_state, plan_view, _ = _entered_placement(
                    conditions, "c1", ["c1", "c2"]
                )
                conditions["c2"] = Condition(
                    uid="c2",
                    layer_visible=True,
                    condition_type=Condition.TYPE_LINEAR,
                )
                self.assertFalse(
                    placement.reconcile_authoritative_conditions(
                        accept_reconstructed_conditions=accept_reconstructed
                    )
                )
                self.assertEqual(placement.state, PlacementState.IDLE)
                self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_when_condition_is_deleted(self):
        for removed_uid in ("c1", "c2"):
            with self.subTest(removed_uid=removed_uid):
                conditions = _conditions("c1", "c2")
                placement, ui_state, plan_view, _ = _entered_placement(
                    conditions, "c1", ["c1", "c2"]
                )
                del conditions[removed_uid]
                self.assertFalse(
                    placement.reconcile_authoritative_conditions(
                        accept_reconstructed_conditions=True
                    )
                )
                self.assertEqual(placement.state, PlacementState.IDLE)
                self.assertIsNone(ui_state.place_condition_uid)
                self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_when_ordered_place_set_drifts(self):
        for drifted in (["c1"], ["c2", "c1"], ["c1", "c2", "c3"]):
            with self.subTest(drifted=drifted):
                conditions = _conditions("c1", "c2", "c3")
                placement, ui_state, plan_view, _ = _entered_placement(
                    conditions, "c1", ["c1", "c2"]
                )
                ui_state.place_condition_uids = list(drifted)
                self.assertFalse(
                    placement.reconcile_authoritative_conditions(
                        accept_reconstructed_conditions=True
                    )
                )
                self.assertEqual(placement.state, PlacementState.IDLE)
                self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_exits_when_active_uid_is_not_placeable(self):
        stray_conditions = {
            "missing": None,
            "hidden": Condition(
                uid="hidden", layer_visible=False, condition_type=Condition.TYPE_AREA
            ),
            "linear": Condition(
                uid="linear", layer_visible=True, condition_type=Condition.TYPE_LINEAR
            ),
        }
        for stray_uid, stray in stray_conditions.items():
            with self.subTest(active_uid=stray_uid):
                conditions = _conditions("c1", "c2")
                if stray is not None:
                    conditions[stray_uid] = stray
                placement, ui_state, plan_view, _ = _entered_placement(
                    conditions, "c1", ["c1", "c2"]
                )
                ui_state.place_condition_uid = stray_uid
                self.assertFalse(
                    placement.reconcile_authoritative_conditions(
                        accept_reconstructed_conditions=True
                    )
                )
                self.assertEqual(placement.state, PlacementState.IDLE)
                self.assertEqual(plan_view.cancel_calls, 1)

    def test_placement_reconciliation_is_noop_while_idle(self):
        placement, ui_state, plan_view, _ = _placement(_conditions("c1"))
        self.assertTrue(placement.reconcile_authoritative_conditions())
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertEqual(plan_view.cancel_calls, 0)
        self.assertEqual(ui_state.place_condition_uids, [])

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
        for failing_signal in ("place_exited", "area_placement_in_progress"):
            with self.subTest(failing_signal=failing_signal):
                placement = PlacementCoordinator(None, None, None, None)
                old_view = _PlacementPlanView()
                new_view = _PlacementPlanView()
                placement.set_plan_view(old_view)
                old_signals = {
                    "place_exited": old_view.place_exited,
                    "area_placement_in_progress": old_view.area_placement_in_progress,
                }
                for signal in old_signals.values():
                    self.assertEqual(len(signal.callbacks), 1)
                old_signals[failing_signal].fail_disconnect = True
                placement.set_plan_view(new_view)
                for name, signal in old_signals.items():
                    self.assertEqual(
                        len(signal.callbacks), 1 if name == failing_signal else 0
                    )
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

    def test_area_placement_progress_toggles_state_and_exit_releases_surface(self):
        placement, _ui_state, plan_view, transitions = _entered_placement(
            _conditions("c1"), "c1", ["c1"]
        )
        self.assertEqual(placement.state, PlacementState.READY)
        placement._on_area_placement_changed(True)
        self.assertEqual(placement.state, PlacementState.AREA_IN_PROGRESS)
        self.assertTrue(placement.is_active)
        placement._on_area_placement_changed(False)
        self.assertEqual(placement.state, PlacementState.READY)
        placement._on_area_placement_changed(True)
        placement.exit()
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertFalse(placement.is_active)
        self.assertEqual(plan_view.cancel_calls, 1)
        self.assertEqual(
            transitions,
            [
                (True, "main-plan"),
                (False, "main-plan"),
                (True, "main-plan"),
                (False, "main-plan"),
            ],
        )

    def test_enter_and_exit_drive_place_mode_navigation_state(self):
        nav = _nav_with_pages_selected()
        placement, ui_state, plan_view, _ = _entered_placement(
            _conditions("c1", "c2"), "c1", ["c1", "c2"], nav=nav
        )
        self.assertEqual(nav.current_state, NavState.PLACE_MODE)
        self.assertEqual(placement.condition_uid, "c1")
        placement.exit()
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_PAGES_SELECTED)
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertIsNone(ui_state.place_condition_uid)
        self.assertEqual(ui_state.place_condition_uids, [])
        self.assertEqual(plan_view.cancel_calls, 1)
        placement.exit()
        self.assertEqual(plan_view.cancel_calls, 1)
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_PAGES_SELECTED)

    def test_enter_rejects_unplaceable_requests_without_activating_plan_view(self):
        hidden = _conditions("hidden", layer_visible=False)
        cases = {
            "access_denied": (_conditions("c1"), "c1", {"allowed": False}),
            "hidden_condition": (hidden, "hidden", {}),
            "unknown_condition": (_conditions("c1"), "missing", {}),
        }
        for name, (conditions, uid, options) in cases.items():
            with self.subTest(case=name):
                placement, ui_state, plan_view, _ = _placement(conditions, **options)
                self.assertFalse(placement.enter(uid, [uid]))
                self.assertEqual(plan_view.place_calls, [])
                self.assertEqual(placement.state, PlacementState.IDLE)
                self.assertIsNone(ui_state.place_condition_uid)
                self.assertEqual(ui_state.place_condition_uids, [])
        placement, _ui_state, _plan_view, _ = _placement(_conditions("c1"))
        placement._plan_view = None
        self.assertFalse(placement.enter("c1", ["c1"]))
        self.assertEqual(placement.state, PlacementState.IDLE)

    def test_enter_requires_active_page_even_without_navigation_state(self):
        placement, ui_state, plan_view, _ = _placement(_conditions("c1"))
        ui_state.active_page_uid = None
        self.assertFalse(placement.enter("c1", ["c1"]))
        self.assertEqual(plan_view.place_calls, [])
        self.assertEqual(placement.state, PlacementState.IDLE)

    def test_plan_view_place_exited_signal_finalizes_without_cancelling_view(self):
        nav = _nav_with_pages_selected()
        view = _PlacementPlanView()
        placement, ui_state, _plan_view, _ = _placement(
            _conditions("c1"), nav=nav, plan_view=view
        )
        self.assertTrue(placement.enter("c1", ["c1"]))
        self.assertEqual(nav.current_state, NavState.PLACE_MODE)
        view.place_exited.callbacks[0]()
        self.assertEqual(placement.state, PlacementState.IDLE)
        self.assertEqual(nav.current_state, NavState.BID_ACTIVE_PAGES_SELECTED)
        self.assertIsNone(ui_state.place_condition_uid)
        self.assertEqual(view.cancel_calls, 0)

    def test_cleanup_disconnects_plan_view_and_releases_collaborators(self):
        view = _PlacementPlanView()
        placement, _ui_state, _plan_view, _ = _placement(
            _conditions("c1"), nav=_nav_with_pages_selected(), plan_view=view
        )
        self.assertEqual(len(view.place_exited.callbacks), 1)
        self.assertEqual(len(view.area_placement_in_progress.callbacks), 1)
        placement.cleanup()
        self.assertEqual(view.place_exited.callbacks, [])
        self.assertEqual(view.area_placement_in_progress.callbacks, [])
        self.assertIsNone(placement._plan_view)
        self.assertIsNone(placement._nav)
        self.assertIsNone(placement._ui_state)
        self.assertIsNone(placement._access)
        self.assertIsNone(placement._project_data)
