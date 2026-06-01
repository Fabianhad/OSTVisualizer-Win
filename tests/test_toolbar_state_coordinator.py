import unittest
from PySide6 import QtGui, QtWidgets
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _Access:
    def is_allowed(self, _feature: Feature) -> bool:
        return True


class _UiState:
    selected_project_uid = None

    def get_selected_bid_refs(self):
        return []

    def get_selected_bid_ref(self):
        return None


class _ProjectData:
    def get_bid_conditions(self):
        return {"c1": Condition(uid="c1", layer_visible=True)}

    def is_current_bid_locked(self):
        return False


class _IndexWidget:
    def __init__(self, index: int):
        self._index = index

    def currentIndex(self) -> int:
        return self._index


class _PlanView:
    place_condition_uid = "c1"
    current_page_uid = "p1"
    is_rotate_mode_active = False
    has_selection = False

    def __init__(self):
        self.reset_ctrl_held_called = False
        self.cursor_modes = []

    def selected_takeoff_condition_uid(self):
        return None

    def reset_ctrl_held(self):
        self.reset_ctrl_held_called = True

    def set_cursor_mode(self, mode: str):
        self.cursor_modes.append(mode)

    def set_selection_enabled(self, _enabled: bool):
        pass

    def backout_parent_candidate_uid(self):
        return None


class ToolbarStateCoordinatorTests(unittest.TestCase):
    def test_refresh_exits_place_when_3d_view_is_active(self):
        _app()
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        group = QtGui.QActionGroup(None)
        group.setExclusive(True)
        group.addAction(select_action)
        group.addAction(place_action)
        place_action.setChecked(True)
        plan_view = _PlanView()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(0))
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertFalse(place_action.isEnabled())
        self.assertTrue(select_action.isChecked())
        self.assertTrue(plan_view.reset_ctrl_held_called)
        self.assertEqual(plan_view.cursor_modes, ["select"])


if __name__ == "__main__":
    unittest.main()
