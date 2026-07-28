import unittest
from PySide6 import QtGui, QtWidgets
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _Access:
    def is_allowed(self, _feature: Feature) -> bool:
        return True

    def is_allowed_for_active_placement(self, _feature: Feature) -> bool:
        return True


class _SelectiveAccess:
    def __init__(self, allowed):
        self.allowed = set(allowed)

    def is_allowed(self, feature: Feature) -> bool:
        return feature in self.allowed

    def is_allowed_for_active_placement(self, feature: Feature) -> bool:
        return feature in self.allowed


class _UiState:
    def __init__(
        self,
        selected_bid_refs=None,
        selected_bid_ref=None,
        selected_project_uid=None,
        selected_file_path=None,
        selected_page_uids=None,
        active_page_uid=None,
    ):
        self._selected_bid_refs = selected_bid_refs or []
        self._selected_bid_ref = selected_bid_ref
        self.selected_project_uid = selected_project_uid
        self.selected_file_path = selected_file_path
        self.selected_page_uids = selected_page_uids or []
        self.active_page_uid = active_page_uid

    def get_selected_bid_refs(self):
        return self._selected_bid_refs

    def get_selected_bid_ref(self):
        return self._selected_bid_ref


class _ProjectData:
    def get_bid_conditions(self):
        return {"c1": Condition(uid="c1", layer_visible=True)}

    def is_current_bid_locked(self):
        return False

    def project_has_bids(self, _uid, _file_path=None):
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
        self.selection_enabled = None
        self.editing_enabled = None
        self.editing_enabled_calls = []
        self.inline_edit_active = False
        self.inline_edit_enabled = None

    def selected_takeoff_condition_uid(self):
        return None

    def reset_ctrl_held(self):
        self.reset_ctrl_held_called = True

    def set_cursor_mode(self, mode: str):
        self.cursor_modes.append(mode)

    def set_selection_enabled(self, enabled: bool):
        self.selection_enabled = bool(enabled)

    def set_editing_enabled(self, enabled: bool):
        self.editing_enabled = bool(enabled)
        self.editing_enabled_calls.append(bool(enabled))

    def set_text_annotation_inline_edit_enabled(self, enabled: bool):
        self.inline_edit_enabled = bool(enabled)

    def is_text_annotation_inline_edit_active(self):
        return self.inline_edit_active

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


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def disconnect(self, callback):
        self._callbacks.remove(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class _AreaPlacementAccess(_Access):
    def __init__(self, project_data):
        self.area_active = False
        self.project_data = project_data

    def set_area_placement_active(self, active: bool) -> None:
        self.area_active = bool(active)

    def is_allowed(self, feature: Feature) -> bool:
        if (
            feature == Feature.PLACE_ANNOTATIONS
            and not self.project_data.annotation_layer_visible
        ):
            return False
        if self.area_active and feature in {
            Feature.SELECT_PLAN_ITEMS,
            Feature.EDIT_PLAN_ITEMS,
            Feature.PLACE_ANNOTATIONS,
            Feature.EDIT_ANNOTATION_TEXT,
        }:
            return False
        return True

    def is_allowed_for_active_placement(self, feature: Feature) -> bool:
        if feature == Feature.PLACE_ANNOTATIONS:
            return self.project_data.annotation_layer_visible
        return feature == Feature.PLACE_PLAN_ITEMS


class _AreaPlacementProjectData(_ProjectData):
    def __init__(self):
        self.annotation_layer_visible = True


class _AreaPlacementPlanView(_PlanView):
    def __init__(self):
        super().__init__()
        self.place_exited = _Signal()
        self.area_placement_in_progress = _Signal()
        self.place_condition_uid = None
        self.cursor_mode = CURSOR_MODE_SELECT
        self.area_active = False

    def begin_area(self):
        self.area_active = True
        self.area_placement_in_progress.emit(True)

    def end_area(self):
        if not self.area_active:
            return
        self.area_active = False
        self.area_placement_in_progress.emit(False)

    def set_cursor_mode(self, mode: str):
        super().set_cursor_mode(mode)
        self.cursor_mode = mode
        if mode == CURSOR_MODE_SELECT:
            self.end_area()
            self.place_condition_uid = None

    def cancel_place_mode(self):
        self.set_cursor_mode(CURSOR_MODE_SELECT)


class _CancellingAreaPlacementPlanView(_AreaPlacementPlanView):
    def __init__(self):
        super().__init__()
        self.editing_enabled = True
        self.editing_disable_cancellations = 0

    def set_editing_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if self.editing_enabled == enabled:
            return
        super().set_editing_enabled(enabled)
        if not enabled:
            self.editing_disable_cancellations += 1
            self.cancel_place_mode()


class ToolbarStateCoordinatorTests(unittest.TestCase):
    def test_silent_action_updates_preserve_caller_owned_signal_blocks(self):
        _app()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        select_action.blockSignals(True)
        backout_action = QtGui.QAction()
        backout_action.setCheckable(True)
        backout_action.blockSignals(True)
        coordinator.set_select_action(select_action)
        coordinator.set_backout_action(backout_action)
        coordinator.set_select_checked()
        coordinator._set_backout_checked_silent(True)
        self.assertTrue(select_action.isChecked())
        self.assertTrue(select_action.signalsBlocked())
        self.assertTrue(backout_action.isChecked())
        self.assertTrue(backout_action.signalsBlocked())

    def test_read_only_plan_actions_keep_copy_and_selection_but_disable_mutations(self):
        _app()
        access = _SelectiveAccess({Feature.SELECT_PLAN_ITEMS})
        bid_ref = BidRef("sql-db", "bid-1")
        coordinator = ToolbarStateCoordinator(
            _UiState(
                selected_bid_refs=[bid_ref],
                selected_bid_ref=bid_ref,
                selected_file_path="sql-db",
                active_page_uid="p1",
            ),
            access,
            _ProjectData(),
        )
        plan_view = _PlanView()
        plan_view.has_selection = True
        copy_action = QtGui.QAction()
        paste_action = QtGui.QAction()
        delete_action = QtGui.QAction()
        duplicate_action = QtGui.QAction()
        undo_action = QtGui.QAction()
        coordinator.set_copy_action(copy_action)
        coordinator.set_paste_action(paste_action)
        coordinator.set_delete_action(delete_action)
        coordinator.set_duplicate_action(duplicate_action)
        coordinator.set_undo_action(undo_action)
        coordinator.set_undo_service(
            type(
                "Undo",
                (),
                {"can_undo": lambda self: True, "can_redo": lambda self: True},
            )()
        )
        coordinator.set_plan_view_handler(
            type("Handler", (), {"can_paste_to_current_bid": lambda self: True})()
        )
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertFalse(paste_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())
        self.assertFalse(duplicate_action.isEnabled())
        self.assertFalse(undo_action.isEnabled())
        self.assertTrue(plan_view.selection_enabled)
        self.assertFalse(plan_view.editing_enabled)

    def test_active_inline_editor_keeps_canvas_editing_capability(self):
        _app()
        access = _SelectiveAccess({Feature.EDIT_ANNOTATION_TEXT})
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"),
            access,
            _ProjectData(),
        )
        plan_view = _PlanView()
        plan_view.editing_enabled = True
        plan_view.inline_edit_active = True
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertEqual(plan_view.editing_enabled_calls, [])
        self.assertTrue(plan_view.editing_enabled)
        self.assertTrue(plan_view.inline_edit_enabled)

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

    def test_place_action_enabled_for_active_2d_page_without_3d_page_selection(self):
        class PlanView(_PlanView):
            place_condition_uid = None

            def selected_takeoff_condition_uid(self):
                return "c1"

        _app()
        action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(
            _UiState(selected_page_uids=[], active_page_uid="p1"),
            _Access(),
            _ProjectData(),
        )
        coordinator.set_place_action(action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(PlanView())
        coordinator.refresh()
        self.assertTrue(action.isEnabled())

    def test_active_annotation_area_survives_refresh_and_unlocks_actions_on_end(self):
        _app()
        project_data = _AreaPlacementProjectData()
        access = _AreaPlacementAccess(project_data)
        ui_state = _UiState(active_page_uid="p1")
        plan_view = _CancellingAreaPlacementPlanView()
        coordinator = ToolbarStateCoordinator(ui_state, access, project_data)
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        annotation_action = QtGui.QAction()
        annotation_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(annotation_action)
        copy_action = QtGui.QAction()
        select_action.setChecked(True)
        select_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        annotation_action.toggled.connect(
            lambda checked: (
                setattr(plan_view, "cursor_mode", CURSOR_MODE_ANNOTATION_PLACE)
                if checked
                else None
            )
        )
        coordinator.set_select_action(select_action)
        coordinator.set_annotation_tool_actions([annotation_action])
        coordinator.set_copy_action(copy_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(plan_view)
        placement = PlacementCoordinator(ui_state, access, None, project_data)
        placement.set_plan_view(plan_view)
        placement.set_area_state_change_callback(coordinator.refresh)
        annotation_action.setChecked(True)
        plan_view.has_selection = True
        plan_view.begin_area()
        self.assertTrue(access.area_active)
        self.assertTrue(annotation_action.isChecked())
        self.assertFalse(copy_action.isEnabled())
        coordinator.refresh()
        self.assertTrue(access.area_active)
        self.assertTrue(annotation_action.isChecked())
        self.assertEqual(plan_view.cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(plan_view.editing_disable_cancellations, 0)
        plan_view.end_area()
        self.assertFalse(access.area_active)
        self.assertTrue(annotation_action.isChecked())
        self.assertTrue(annotation_action.isEnabled())
        self.assertTrue(copy_action.isEnabled())

    def test_active_takeoff_area_survives_first_point_toolbar_refresh(self):
        _app()
        project_data = _AreaPlacementProjectData()
        access = _AreaPlacementAccess(project_data)
        ui_state = _UiState(active_page_uid="p1")
        plan_view = _CancellingAreaPlacementPlanView()
        plan_view.place_condition_uid = "c1"
        plan_view.cursor_mode = CURSOR_MODE_PLACE
        coordinator = ToolbarStateCoordinator(ui_state, access, project_data)
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        select_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(plan_view)
        placement = PlacementCoordinator(ui_state, access, None, project_data)
        placement.set_plan_view(plan_view)
        placement.set_area_state_change_callback(coordinator.refresh)
        area_transitions = []
        plan_view.area_placement_in_progress.connect(area_transitions.append)
        place_action.setChecked(True)
        plan_view.begin_area()
        self.assertEqual(area_transitions, [True])
        self.assertTrue(access.area_active)
        self.assertTrue(place_action.isChecked())
        self.assertFalse(select_action.isChecked())
        self.assertEqual(plan_view.cursor_mode, CURSOR_MODE_PLACE)
        self.assertTrue(plan_view.editing_enabled)
        self.assertEqual(plan_view.editing_disable_cancellations, 0)

    def test_invalid_active_area_cancels_once_before_toolbar_projection(self):
        _app()
        project_data = _AreaPlacementProjectData()
        access = _AreaPlacementAccess(project_data)
        ui_state = _UiState(active_page_uid="p1")
        plan_view = _AreaPlacementPlanView()
        coordinator = ToolbarStateCoordinator(ui_state, access, project_data)
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        annotation_action = QtGui.QAction()
        annotation_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(annotation_action)
        copy_action = QtGui.QAction()
        select_action.setChecked(True)
        select_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        annotation_action.toggled.connect(
            lambda checked: (
                setattr(plan_view, "cursor_mode", CURSOR_MODE_ANNOTATION_PLACE)
                if checked
                else None
            )
        )
        coordinator.set_select_action(select_action)
        coordinator.set_annotation_tool_actions([annotation_action])
        coordinator.set_copy_action(copy_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(plan_view)
        placement = PlacementCoordinator(ui_state, access, None, project_data)
        placement.set_plan_view(plan_view)
        placement.set_area_state_change_callback(coordinator.refresh)
        area_transitions = []
        plan_view.area_placement_in_progress.connect(area_transitions.append)
        annotation_action.setChecked(True)
        plan_view.has_selection = True
        plan_view.begin_area()
        project_data.annotation_layer_visible = False
        coordinator.refresh()
        self.assertEqual(area_transitions, [True, False])
        self.assertFalse(access.area_active)
        self.assertTrue(select_action.isChecked())
        self.assertFalse(annotation_action.isChecked())
        self.assertFalse(annotation_action.isEnabled())
        self.assertTrue(copy_action.isEnabled())
        self.assertEqual(plan_view.cursor_modes.count(CURSOR_MODE_SELECT), 1)

    def test_invalid_takeoff_area_cancellation_does_not_leave_stale_actions(self):
        _app()
        project_data = _AreaPlacementProjectData()
        access = _AreaPlacementAccess(project_data)
        ui_state = _UiState(active_page_uid="p1")
        plan_view = _AreaPlacementPlanView()
        plan_view.place_condition_uid = "c1"
        plan_view.cursor_mode = CURSOR_MODE_PLACE
        plan_view.has_selection = True
        coordinator = ToolbarStateCoordinator(ui_state, access, project_data)
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        copy_action = QtGui.QAction()
        select_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        coordinator.set_copy_action(copy_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(plan_view)
        placement = PlacementCoordinator(ui_state, access, None, project_data)
        placement.set_plan_view(plan_view)
        placement.set_area_state_change_callback(coordinator.refresh)
        place_action.setChecked(True)
        plan_view.begin_area()
        plan_view.current_page_uid = None
        coordinator.refresh()
        self.assertFalse(access.area_active)
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertTrue(copy_action.isEnabled())
        self.assertEqual(plan_view.cursor_modes.count(CURSOR_MODE_SELECT), 1)

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

    def test_project_delete_uses_project_tree_permission_not_bid_delete(self):
        _app()
        delete_action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(
            _UiState(selected_project_uid="2", selected_file_path="db.mdb"),
            _SelectiveAccess({Feature.EDIT_PROJECT_TREE_STRUCTURE}),
            _ProjectData(),
        )
        coordinator.set_delete_action(delete_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_PROJECTS))
        coordinator.refresh()
        self.assertTrue(delete_action.isEnabled())
        coordinator._access = _SelectiveAccess({Feature.DELETE_BID})
        coordinator.refresh()
        self.assertFalse(delete_action.isEnabled())

    def test_read_only_project_copy_is_separate_from_duplicate_and_paste(self):
        _app()
        ref = BidRef("sql-db", "bid-1")
        copy_action = QtGui.QAction()
        duplicate_action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(
            _UiState(
                selected_bid_refs=[ref],
                selected_bid_ref=ref,
                selected_file_path="sql-db",
            ),
            _SelectiveAccess({Feature.COPY_BID}),
            _ProjectData(),
        )
        coordinator.set_copy_action(copy_action)
        coordinator.set_duplicate_action(duplicate_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_PROJECTS))
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertFalse(duplicate_action.isEnabled())

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
