import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
    PlacementModeMixin,
)
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
)
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class DuplicatePlacementConditionBehaviorTests(unittest.TestCase):
    def _make_world(self, *, takeoff_2d_view_active=True):
        original_uid = "condition-original"
        duplicate_uid = "condition-duplicate"
        conditions = {
            original_uid: Condition(
                uid=original_uid,
                condition_type=Condition.TYPE_LINEAR,
                color_fill=0x336699,
                layer_visible=True,
            )
        }

        class UiState:
            active_page_uid = "page-1"
            place_condition_uid = None
            state = SimpleNamespace(
                display_mode_2d=Config.DISPLAY_MODE_TRANSPARENT,
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

        class PlanView(PlacementModeMixin):
            def __init__(self, color_service):
                self._color_service = color_service
                self._current_conditions = dict(conditions)
                self._current_color_map = {}
                self._place_session_uid = None
                self._backout_mode_active = False
                self._backout_parent_uid = None
                self._backout_active_uid = None

            def activate_place_for_condition(self, condition_uid, _condition_uids):
                return self.enter_place_mode_for_condition(condition_uid)

            def update_color_map(self, color_map):
                self._current_color_map = dict(color_map)

            def cancel_place_mode(self):
                self._place_session_uid = None

            def clear_place_preview(self):
                pass

            def _set_area_placement_in_progress(self, _active):
                pass

            def refresh_conditions(self):
                self._current_conditions = dict(conditions)

            def active_preview_opacity(self):
                _color, opacity = self._condition_preview_color_and_opacity(
                    self._place_session_uid
                )
                return opacity

        color_service = ColorService()
        ui_state = UiState()
        plan_view = PlanView(color_service)
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=color_service,
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
                get_page_takeoffs=lambda _page_uid: [],
            ),
        )
        placement._plan_view = plan_view
        self.assertTrue(placement.enter(original_uid, [original_uid]))
        self.assertEqual(plan_view.active_preview_opacity(), 0.5)
        conditions[duplicate_uid] = Condition(
            uid=duplicate_uid,
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0x336699,
            layer_visible=True,
        )
        calls = []
        coordinator = SimpleNamespace(
            placement=placement,
            _is_takeoff_2d_view_active=lambda: takeoff_2d_view_active,
            highlight_sidebar=lambda uids, reveal=True: calls.append(
                ("highlight", set(uids), reveal)
            ),
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=None,
            project_read_service=None,
            project_data=None,
            ui_state_manager=None,
            workspace_state_model=make_workspace_state_model(),
        )
        plan_view.refresh_conditions()
        calls.append("conditions_changed")
        return SimpleNamespace(
            handler=handler,
            plan_view=plan_view,
            ui_state=ui_state,
            calls=calls,
            original_uid=original_uid,
            duplicate_uid=duplicate_uid,
        )

    def test_duplicate_uses_condition_state_projected_before_active_placement(self):
        world = self._make_world()
        world.handler._finish_condition_duplicate(
            [world.duplicate_uid], sidebar=object()
        )
        self.assertEqual(world.calls[0], "conditions_changed")
        self.assertEqual(world.plan_view._place_session_uid, world.duplicate_uid)
        self.assertEqual(world.ui_state.place_condition_uid, world.duplicate_uid)
        self.assertEqual(world.plan_view.active_preview_opacity(), 0.5)
        self.assertEqual(world.calls[-1], ("highlight", {world.duplicate_uid}, False))

    def test_duplicate_outside_2d_view_keeps_placement_and_only_highlights(self):
        # The same wiring as above must not enter placement for the duplicate
        # when the 2D takeoff view is not active (positive control: the test
        # above enters it); the sidebar highlight still happens.
        world = self._make_world(takeoff_2d_view_active=False)
        world.handler._finish_condition_duplicate(
            [world.duplicate_uid], sidebar=object()
        )
        self.assertEqual(world.plan_view._place_session_uid, world.original_uid)
        self.assertEqual(world.ui_state.place_condition_uid, world.original_uid)
        self.assertEqual(
            world.calls,
            ["conditions_changed", ("highlight", {world.duplicate_uid}, False)],
        )

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()
