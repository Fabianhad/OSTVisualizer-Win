import unittest
from PySide6 import QtGui, QtWidgets
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
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
    def __init__(
        self,
        selected_bid_refs=None,
        selected_bid_ref=None,
        selected_project_uid=None,
        selected_file_path=None,
    ):
        self._selected_bid_refs = selected_bid_refs or []
        self._selected_bid_ref = selected_bid_ref
        self.selected_project_uid = selected_project_uid
        self.selected_file_path = selected_file_path

    def get_selected_bid_refs(self):
        return self._selected_bid_refs

    def get_selected_bid_ref(self):
        return self._selected_bid_ref


class _ProjectData:
    def get_bid_conditions(self):
        return {"c1": Condition(uid="c1", layer_visible=True)}

    def is_current_bid_locked(self):
        return False

    def project_has_bids(self, _uid):
        return False

    def find_project_uid_for_bid(self, _bid_ref):
        return "2"


class _IndexWidget:
    def __init__(self, index: int):
        self._index = index

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        self._index = index


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

    def can_move_overlay_image(self):
        return False


class _SummaryTab:
    def __init__(self, can_copy=False, can_delete=False):
        self._can_copy = can_copy
        self._can_delete = can_delete

    def can_copy_current_row(self):
        return self._can_copy

    def can_delete_current_row(self):
        return self._can_delete


class _OverlayPlanView(_PlanView):
    def can_move_overlay_image(self):
        return True


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

    def test_move_overlay_action_enabled_for_editable_2d_overlay_page(self):
        _app()
        action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        coordinator.set_move_overlay_action(action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(_OverlayPlanView())
        coordinator.refresh()
        self.assertTrue(action.isEnabled())

    def test_move_overlay_action_disabled_without_movable_overlay(self):
        _app()
        action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        coordinator.set_move_overlay_action(action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(_PlanView())
        coordinator.refresh()
        self.assertFalse(action.isEnabled())

    def test_summary_tab_disables_project_only_edit_actions_despite_project_selection(
        self,
    ):
        _app()
        ref = BidRef("db.mdb", "bid-1")
        copy_action = QtGui.QAction()
        cut_action = QtGui.QAction()
        paste_action = QtGui.QAction()
        delete_action = QtGui.QAction()
        duplicate_action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(
            _UiState(
                selected_bid_refs=[ref],
                selected_bid_ref=ref,
                selected_project_uid="2",
                selected_file_path="db.mdb",
            ),
            _Access(),
            _ProjectData(),
        )
        coordinator.set_copy_action(copy_action)
        coordinator.set_cut_action(cut_action)
        coordinator.set_paste_action(paste_action)
        coordinator.set_delete_action(delete_action)
        coordinator.set_duplicate_action(duplicate_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_SUMMARY))
        coordinator.set_condition_summary_tab(
            _SummaryTab(can_copy=False, can_delete=False)
        )
        coordinator.refresh()
        self.assertFalse(copy_action.isEnabled())
        self.assertFalse(cut_action.isEnabled())
        self.assertFalse(paste_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())
        self.assertFalse(duplicate_action.isEnabled())

    def test_summary_copy_and_delete_follow_summary_row_state(self):
        _app()
        copy_action = QtGui.QAction()
        delete_action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        coordinator.set_copy_action(copy_action)
        coordinator.set_delete_action(delete_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_SUMMARY))
        coordinator.set_condition_summary_tab(
            _SummaryTab(can_copy=True, can_delete=True)
        )
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertTrue(delete_action.isEnabled())

    def test_project_and_takeoff_action_state_restores_after_summary(self):
        _app()
        ref = BidRef("db.mdb", "bid-1")
        copy_action = QtGui.QAction()
        delete_action = QtGui.QAction()
        duplicate_action = QtGui.QAction()
        tab_widget = _IndexWidget(TAB_INDEX_SUMMARY)
        plan_view = _PlanView()
        plan_view.has_selection = True
        coordinator = ToolbarStateCoordinator(
            _UiState(
                selected_bid_refs=[ref],
                selected_bid_ref=ref,
                selected_project_uid="2",
                selected_file_path="db.mdb",
            ),
            _Access(),
            _ProjectData(),
        )
        coordinator.set_copy_action(copy_action)
        coordinator.set_delete_action(delete_action)
        coordinator.set_duplicate_action(duplicate_action)
        coordinator.set_tab_widget(tab_widget)
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(plan_view)
        coordinator.set_condition_summary_tab(
            _SummaryTab(can_copy=False, can_delete=False)
        )
        coordinator.refresh()
        self.assertFalse(copy_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())
        self.assertFalse(duplicate_action.isEnabled())
        tab_widget.setCurrentIndex(TAB_INDEX_PROJECTS)
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertTrue(delete_action.isEnabled())
        self.assertTrue(duplicate_action.isEnabled())
        tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertTrue(delete_action.isEnabled())
        self.assertTrue(duplicate_action.isEnabled())


if __name__ == "__main__":
    unittest.main()
