from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from types import SimpleNamespace
import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
)
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    PlanSurfaceAccessState,
)
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)
from PySide6 import QtCore, QtGui, QtWidgets
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.config import (
    COMPACT_SPACING,
    OPTIONS_DIALOG_TITLE,
    OPTIONS_GROUP_AUTO_ZOOM,
    OPTIONS_GROUP_CONFIRMATIONS,
    OPTIONS_GROUP_PREFERENCES,
    OPTIONS_GROUP_SNAP_ANGLE,
    OPTIONS_LABEL_RESET_ALL_SETTINGS,
    OPTIONS_TAB_EXPORT,
    OPTIONS_TAB_FONTS_COLORS,
    OPTIONS_TAB_MCP_SETUP,
    OPTIONS_TAB_OPTIONS,
    OPTIONS_TAB_TAKEOFF_TOOLBAR,
    OPTIONS_WINDOW_WIDTH,
    RELAXED_SPACING,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _Access:
    def __init__(self):
        self.listeners = []

    def is_allowed(self, _feature: Feature) -> bool:
        return True

    def is_allowed_for_active_placement(self, _feature: Feature) -> bool:
        return True

    def can_delete_bids(self, _bid_refs) -> bool:
        return self.is_allowed(Feature.DELETE_BID)

    def can_delete_projects(self, _database_id, _project_uids) -> bool:
        return self.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE)

    def current_plan_surface_context(self):
        return object()

    def get_plan_surface_access(self, _context):
        return PlanSurfaceAccessState(
            can_select_plan_items=self.is_allowed(Feature.SELECT_PLAN_ITEMS),
            can_place_plan_items=self.is_allowed(Feature.PLACE_PLAN_ITEMS),
            can_edit_plan_items=self.is_allowed(Feature.EDIT_PLAN_ITEMS),
            can_place_annotations=self.is_allowed(Feature.PLACE_ANNOTATIONS),
            can_continue_annotation_placement=(
                self.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
            ),
            can_edit_annotations=self.is_allowed(Feature.EDIT_PLAN_ITEMS),
            can_edit_annotation_text=self.is_allowed(Feature.EDIT_ANNOTATION_TEXT),
            can_edit_page_settings=self.is_allowed(Feature.EDIT_PAGE_SETTINGS),
        )

    def is_project_bid_clipboard_allowed(
        self, feature, _file_path, _bid_refs, _project_uid
    ):
        return self.is_allowed(feature)

    def subscribe_access_state_changed(self, callback):
        if callback not in self.listeners:
            self.listeners.append(callback)

    def unsubscribe_access_state_changed(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)


class _SelectiveAccess:
    def __init__(self, allowed):
        self.listeners = []
        self.allowed = set(allowed)

    def is_allowed(self, feature: Feature) -> bool:
        return feature in self.allowed

    def is_allowed_for_active_placement(self, feature: Feature) -> bool:
        return feature in self.allowed

    current_plan_surface_context = _Access.current_plan_surface_context
    get_plan_surface_access = _Access.get_plan_surface_access
    can_delete_bids = _Access.can_delete_bids
    can_delete_projects = _Access.can_delete_projects
    is_project_bid_clipboard_allowed = _Access.is_project_bid_clipboard_allowed
    subscribe_access_state_changed = _Access.subscribe_access_state_changed
    unsubscribe_access_state_changed = _Access.unsubscribe_access_state_changed


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
        self.selected_project_uids = (
            [selected_project_uid] if selected_project_uid else []
        )
        self.selected_file_path = selected_file_path
        self.selected_project_file_path = (
            selected_file_path if selected_project_uid else None
        )
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

    def get_hierarchy(self):
        return {}


class _BidClipboard:
    is_cut = False

    def __init__(self, bid_refs):
        self.bid_refs = list(bid_refs)

    def has_content(self):
        return True

    def reconcile(self, _hierarchy):
        pass

    def source_matches_file(self, _file_path):
        return True


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
        super().__init__()
        self.area_active = False
        self.project_data = project_data

    def set_area_placement_active(self, active: bool, *, surface_id: str) -> None:
        self.last_surface_id = surface_id
        self.area_active = bool(active)
        for callback in list(self.listeners):
            callback()

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
    def test_cleanup_unregisters_access_listener(self):
        access = _Access()
        coordinator = ToolbarStateCoordinator(_UiState(), access, _ProjectData())
        self.assertEqual(access.listeners, [coordinator.refresh])
        coordinator.cleanup()
        self.assertEqual(access.listeners, [])

    def test_cleanup_clears_references_when_listener_unsubscribe_fails(self):
        _app()

        class FailingAccess(_Access):
            def unsubscribe_access_state_changed(self, callback):
                raise RuntimeError("listener registry unavailable")

        access = FailingAccess()
        coordinator = ToolbarStateCoordinator(_UiState(), access, _ProjectData())
        action = QtGui.QAction()
        coordinator.set_copy_action(action)
        with self.assertLogs(
            "ost_visualizer.presentation.coordinators.toolbar_state_coordinator",
            level="ERROR",
        ):
            coordinator.cleanup()
        self.assertFalse(coordinator._access_listener_registered)
        self.assertIsNone(coordinator._access)
        self.assertIsNone(coordinator._ui_state)
        self.assertIsNone(coordinator._project_data)
        self.assertIsNone(coordinator._copy_action)
        with self.assertNoLogs(
            "ost_visualizer.presentation.coordinators.toolbar_state_coordinator",
            level="ERROR",
        ):
            coordinator.cleanup()

    def test_select_projection_replaces_checked_takeoff_action_exclusively(self):
        _app()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        transitions = []
        select_action.setChecked(True)
        select_action.toggled.connect(
            lambda checked: transitions.append(CURSOR_MODE_SELECT) if checked else None
        )
        place_action.setChecked(True)
        coordinator.set_select_checked()
        coordinator.set_select_checked()
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertIs(action_group.checkedAction(), select_action)
        self.assertEqual(transitions, [CURSOR_MODE_SELECT])

    def test_select_projection_replaces_disabled_hidden_takeoff_action(self):
        _app()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        select_action.setChecked(True)
        place_action.setChecked(True)
        place_action.setEnabled(False)
        place_action.setVisible(False)
        coordinator.set_select_checked()
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertIs(action_group.checkedAction(), select_action)

    def test_backout_update_preserves_caller_owned_signal_block(self):
        _app()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        backout_action = QtGui.QAction()
        backout_action.setCheckable(True)
        backout_action.blockSignals(True)
        coordinator.set_backout_action(backout_action)
        coordinator._set_backout_checked_silent(True)
        self.assertTrue(backout_action.isChecked())
        self.assertTrue(backout_action.signalsBlocked())

    def test_backout_update_is_silent_and_restores_unblocked_state(self):
        _app()
        coordinator = ToolbarStateCoordinator(_UiState(), _Access(), _ProjectData())
        backout_action = QtGui.QAction()
        backout_action.setCheckable(True)
        toggles = []
        backout_action.toggled.connect(toggles.append)
        coordinator.set_backout_action(backout_action)
        coordinator._set_backout_checked_silent(True)
        self.assertTrue(backout_action.isChecked())
        self.assertFalse(backout_action.signalsBlocked())
        coordinator._set_backout_checked_silent(False)
        self.assertFalse(backout_action.isChecked())
        self.assertFalse(backout_action.signalsBlocked())
        self.assertEqual(toggles, [])

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
        redo_action = QtGui.QAction()
        select_all_action = QtGui.QAction()
        reconciled = []
        coordinator.set_copy_action(copy_action)
        coordinator.set_paste_action(paste_action)
        coordinator.set_delete_action(delete_action)
        coordinator.set_duplicate_action(duplicate_action)
        coordinator.set_undo_action(undo_action)
        coordinator.set_redo_action(redo_action)
        coordinator.set_select_all_action(select_all_action)
        coordinator.set_undo_service(
            type(
                "Undo",
                (),
                {"can_undo": lambda self: True, "can_redo": lambda self: True},
            )()
        )
        coordinator.set_plan_view_handler(
            type(
                "Handler",
                (),
                {
                    "reconcile_geometry_edit_access": lambda self, allowed: (
                        reconciled.append(allowed)
                    ),
                    "can_paste_to_current_bid": lambda self: (
                        access.is_allowed(Feature.EDIT_PLAN_ITEMS)
                        or access.is_allowed(Feature.PLACE_ANNOTATIONS)
                    ),
                },
            )()
        )
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertFalse(paste_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())
        self.assertFalse(duplicate_action.isEnabled())
        self.assertFalse(undo_action.isEnabled())
        self.assertFalse(redo_action.isEnabled())
        self.assertTrue(select_all_action.isEnabled())
        self.assertTrue(plan_view.selection_enabled)
        self.assertFalse(plan_view.editing_enabled)
        self.assertEqual(reconciled, [False])

    def test_no_plan_access_disables_selection_dependent_actions(self):
        _app()
        access = _SelectiveAccess(set())
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), access, _ProjectData()
        )
        plan_view = _PlanView()
        plan_view.has_selection = True
        copy_action = QtGui.QAction()
        select_all_action = QtGui.QAction()
        coordinator.set_copy_action(copy_action)
        coordinator.set_select_all_action(select_all_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertFalse(copy_action.isEnabled())
        self.assertFalse(select_all_action.isEnabled())
        self.assertFalse(plan_view.selection_enabled)
        access.allowed.add(Feature.SELECT_PLAN_ITEMS)
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertTrue(select_all_action.isEnabled())
        self.assertTrue(plan_view.selection_enabled)

    def test_page_actions_wait_for_plan_projection_to_match_active_page(self):
        _app()
        ui_state = _UiState(active_page_uid="p1")
        coordinator = ToolbarStateCoordinator(ui_state, _Access(), _ProjectData())
        plan_view = _PlanView()
        plan_view.has_selection = True
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        annotation_action = QtGui.QAction()
        annotation_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        action_group.addAction(annotation_action)
        copy_action = QtGui.QAction()
        paste_action = QtGui.QAction()
        delete_action = QtGui.QAction()
        duplicate_action = QtGui.QAction()
        select_all_action = QtGui.QAction()
        undo_action = QtGui.QAction()
        page_interactive = []

        class Handler:
            def reconcile_geometry_edit_access(self, _allowed):
                pass

            def can_paste_to_current_bid(self):
                return True

        class PageSettings:
            def set_interactive(self, interactive):
                page_interactive.append(bool(interactive))

        class Undo:
            def can_undo(self):
                return True

            def can_redo(self):
                return False

        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        coordinator.set_annotation_tool_actions([annotation_action])
        coordinator.set_copy_action(copy_action)
        coordinator.set_paste_action(paste_action)
        coordinator.set_delete_action(delete_action)
        coordinator.set_duplicate_action(duplicate_action)
        coordinator.set_select_all_action(select_all_action)
        coordinator.set_undo_action(undo_action)
        coordinator.set_undo_service(Undo())
        coordinator.set_page_settings_bar(PageSettings())
        coordinator.set_plan_view_handler(Handler())
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(plan_view)
        place_action.setChecked(True)
        coordinator.refresh()
        self.assertTrue(place_action.isChecked())
        self.assertTrue(place_action.isEnabled())
        self.assertTrue(annotation_action.isEnabled())
        self.assertTrue(copy_action.isEnabled())
        self.assertTrue(paste_action.isEnabled())
        self.assertTrue(delete_action.isEnabled())
        self.assertTrue(duplicate_action.isEnabled())
        self.assertTrue(select_all_action.isEnabled())
        self.assertTrue(undo_action.isEnabled())
        self.assertTrue(page_interactive[-1])
        ui_state.active_page_uid = "p2"
        coordinator.refresh()
        self.assertFalse(place_action.isEnabled())
        self.assertFalse(annotation_action.isEnabled())
        self.assertFalse(copy_action.isEnabled())
        self.assertFalse(paste_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())
        self.assertFalse(duplicate_action.isEnabled())
        self.assertFalse(select_all_action.isEnabled())
        self.assertFalse(undo_action.isEnabled())
        self.assertFalse(page_interactive[-1])
        self.assertFalse(plan_view.selection_enabled)
        self.assertFalse(plan_view.editing_enabled)
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        plan_view.current_page_uid = "p2"
        coordinator.refresh()
        self.assertTrue(place_action.isEnabled())
        self.assertTrue(annotation_action.isEnabled())
        self.assertTrue(copy_action.isEnabled())
        self.assertTrue(paste_action.isEnabled())
        self.assertTrue(delete_action.isEnabled())
        self.assertTrue(duplicate_action.isEnabled())
        self.assertTrue(select_all_action.isEnabled())
        self.assertTrue(undo_action.isEnabled())
        self.assertTrue(page_interactive[-1])
        self.assertTrue(select_action.isChecked())

    def test_access_loss_releases_main_plan_geometry_edit_ownership(self):
        _app()
        access = _SelectiveAccess({Feature.EDIT_PLAN_ITEMS})
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"),
            access,
            _ProjectData(),
        )
        plan_view = _PlanView()
        reconciled = []
        coordinator.set_plan_view(plan_view)
        coordinator.set_plan_view_handler(
            type(
                "Handler",
                (),
                {
                    "reconcile_geometry_edit_access": lambda self, allowed: (
                        reconciled.append(allowed)
                    ),
                    "can_paste_to_current_bid": lambda self: False,
                },
            )()
        )
        coordinator.refresh()
        access.allowed.clear()
        coordinator.refresh()
        self.assertEqual(reconciled, [True, False])
        self.assertEqual(plan_view.editing_enabled_calls, [True, False])

    def test_access_loss_exits_active_takeoff_tool(self):
        _app()
        access = _SelectiveAccess({Feature.PLACE_PLAN_ITEMS})
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"),
            access,
            _ProjectData(),
        )
        plan_view = _PlanView()
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        place_action.setChecked(True)
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
        coordinator.refresh()
        self.assertTrue(place_action.isChecked())
        self.assertTrue(place_action.isEnabled())
        self.assertEqual(plan_view.cursor_modes, [])
        access.allowed.clear()
        coordinator.refresh()
        self.assertFalse(place_action.isEnabled())
        self.assertTrue(select_action.isChecked())
        self.assertTrue(plan_view.reset_ctrl_held_called)
        self.assertEqual(plan_view.cursor_modes, [CURSOR_MODE_SELECT])

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

    def test_inactive_inline_editor_or_lost_text_access_disables_canvas_editing(self):
        _app()
        for inline_active, allowed, expected_inline in (
            (False, {Feature.EDIT_ANNOTATION_TEXT}, True),
            (True, set(), False),
        ):
            with self.subTest(inline_active=inline_active, allowed=allowed):
                coordinator = ToolbarStateCoordinator(
                    _UiState(active_page_uid="p1"),
                    _SelectiveAccess(allowed),
                    _ProjectData(),
                )
                plan_view = _PlanView()
                plan_view.editing_enabled = True
                plan_view.inline_edit_active = inline_active
                coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
                coordinator.set_plan_view(plan_view)
                coordinator.refresh()
                self.assertEqual(plan_view.editing_enabled_calls, [False])
                self.assertFalse(plan_view.editing_enabled)
                self.assertIs(plan_view.inline_edit_enabled, expected_inline)

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
        select_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), _Access(), _ProjectData()
        )
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(0))
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertFalse(place_action.isEnabled())
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertTrue(plan_view.reset_ctrl_held_called)
        self.assertEqual(plan_view.cursor_modes, [CURSOR_MODE_SELECT])

    def test_3d_switch_then_takeoff_reactivation_keeps_group_exclusive(self):
        _app()
        ui_state = _UiState(active_page_uid="p1")
        plan_view = _PlanView()
        view_stack = _IndexWidget(0)
        coordinator = ToolbarStateCoordinator(ui_state, _Access(), _ProjectData())
        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        select_action.setChecked(True)
        select_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        place_action.setChecked(True)
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(view_stack)
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertIs(action_group.checkedAction(), select_action)
        view_stack.setCurrentIndex(1)
        coordinator.refresh()
        self.assertTrue(place_action.isEnabled())
        place_action.setChecked(True)
        self.assertFalse(select_action.isChecked())
        self.assertTrue(place_action.isChecked())
        self.assertIs(action_group.checkedAction(), place_action)

    def test_undo_and_redo_follow_service_state_only_on_takeoff_tab(self):
        _app()

        class Undo:
            def __init__(self):
                self.undo = True
                self.redo = False

            def can_undo(self):
                return self.undo

            def can_redo(self):
                return self.redo

        undo_service = Undo()
        undo_action = QtGui.QAction()
        redo_action = QtGui.QAction()
        tab_widget = _IndexWidget(TAB_INDEX_TAKEOFF)
        plan_view = _PlanView()
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), _Access(), _ProjectData()
        )
        coordinator.set_undo_action(undo_action)
        coordinator.set_redo_action(redo_action)
        coordinator.set_undo_service(undo_service)
        coordinator.set_tab_widget(tab_widget)
        coordinator.set_plan_view(plan_view)
        coordinator.refresh()
        self.assertTrue(undo_action.isEnabled())
        self.assertFalse(redo_action.isEnabled())
        undo_service.undo = False
        undo_service.redo = True
        coordinator.refresh()
        self.assertFalse(undo_action.isEnabled())
        self.assertTrue(redo_action.isEnabled())
        undo_service.undo = True
        tab_widget.setCurrentIndex(TAB_INDEX_PROJECTS)
        coordinator.refresh()
        self.assertFalse(undo_action.isEnabled())
        self.assertFalse(redo_action.isEnabled())

    def test_move_overlay_action_enabled_for_editable_2d_overlay_page(self):
        _app()
        action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), _Access(), _ProjectData()
        )
        coordinator.set_move_overlay_action(action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(_OverlayPlanView())
        coordinator.refresh()
        self.assertTrue(action.isEnabled())

    def test_move_overlay_action_disabled_without_movable_overlay(self):
        _app()
        action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), _Access(), _ProjectData()
        )
        coordinator.set_move_overlay_action(action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(_PlanView())
        coordinator.refresh()
        self.assertFalse(action.isEnabled())

    def test_move_overlay_action_requires_page_settings_access_page_match_and_2d(
        self,
    ):
        _app()
        cases = {
            "no page settings access": (
                _SelectiveAccess({Feature.SELECT_PLAN_ITEMS}),
                1,
                "p1",
            ),
            "3d view": (_Access(), 0, "p1"),
            "plan view on another page": (_Access(), 1, "p2"),
        }
        for label, (access, view_index, active_page_uid) in cases.items():
            with self.subTest(label):
                action = QtGui.QAction()
                coordinator = ToolbarStateCoordinator(
                    _UiState(active_page_uid=active_page_uid), access, _ProjectData()
                )
                coordinator.set_move_overlay_action(action)
                coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
                coordinator.set_view_stack(_IndexWidget(view_index))
                coordinator.set_plan_view(_OverlayPlanView())
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

    def test_place_action_requires_active_selected_condition_to_be_placeable(self):
        class PlanView(_PlanView):
            place_condition_uid = None

        class Access(_Access):
            @staticmethod
            def is_bid_locked():
                return False

            @staticmethod
            def has_license():
                return True

        class OrderedUidSet(set):
            def __iter__(self):
                return iter(("hidden", "visible"))

        _app()
        conditions = {
            "hidden": Condition(uid="hidden", name="Hidden", layer_visible=False),
            "visible": Condition(uid="visible", name="Visible", layer_visible=True),
        }
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.highlight_conditions(OrderedUidSet(("hidden", "visible")))
        self.assertEqual(sidebar.get_active_condition_uid(), "hidden")
        project_data = _ProjectData()
        project_data.get_bid_conditions = lambda: conditions
        action = QtGui.QAction()
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"),
            Access(),
            project_data,
        )
        coordinator.set_place_action(action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(PlanView())
        coordinator.set_conditions_sidebar(sidebar)
        coordinator.refresh()
        self.assertFalse(action.isEnabled())
        sidebar.tree.setCurrentItem(
            sidebar._condition_items["visible"],
            0,
            QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
        )
        coordinator.refresh()
        self.assertTrue(action.isEnabled())

    def test_place_action_ignores_conditions_on_hidden_layers(self):
        _app()
        for layer_visible in (False, True):
            with self.subTest(layer_visible=layer_visible):

                class PlanView(_PlanView):
                    place_condition_uid = "c1"

                    def selected_takeoff_condition_uid(self):
                        return "c1"

                project_data = _ProjectData()
                project_data.get_bid_conditions = lambda: {
                    "c1": Condition(uid="c1", layer_visible=layer_visible)
                }
                action = QtGui.QAction()
                coordinator = ToolbarStateCoordinator(
                    _UiState(active_page_uid="p1"), _Access(), project_data
                )
                coordinator.set_place_action(action)
                coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
                coordinator.set_view_stack(_IndexWidget(1))
                coordinator.set_plan_view(PlanView())
                coordinator.refresh()
                self.assertIs(action.isEnabled(), layer_visible)

    def test_checked_place_tool_without_placeable_condition_returns_to_select(self):
        _app()

        class PlanView(_PlanView):
            place_condition_uid = None

        select_action = QtGui.QAction()
        select_action.setCheckable(True)
        place_action = QtGui.QAction()
        place_action.setCheckable(True)
        action_group = QtGui.QActionGroup(None)
        action_group.setExclusive(True)
        action_group.addAction(select_action)
        action_group.addAction(place_action)
        plan_view = PlanView()
        select_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), _Access(), _ProjectData()
        )
        coordinator.set_select_action(select_action)
        coordinator.set_place_action(place_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(1))
        coordinator.set_plan_view(plan_view)
        place_action.setChecked(True)
        coordinator.refresh()
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertFalse(place_action.isEnabled())
        self.assertEqual(plan_view.cursor_modes, [CURSOR_MODE_SELECT])

    def test_annotation_tool_actions_require_2d_takeoff_view(self):
        _app()
        annotation_action = QtGui.QAction()
        view_stack = _IndexWidget(0)
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), _Access(), _ProjectData()
        )
        coordinator.set_annotation_tool_actions([annotation_action])
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(view_stack)
        coordinator.set_plan_view(_PlanView())
        coordinator.refresh()
        self.assertFalse(annotation_action.isEnabled())
        view_stack.setCurrentIndex(1)
        coordinator.refresh()
        self.assertTrue(annotation_action.isEnabled())

    def test_viewer_layer_and_cover_sheet_controls_follow_access(self):
        _app()

        class Recorder:
            def __init__(self):
                self.calls = []

            def set_pick_enabled(self, enabled):
                self.calls.append(("pick", enabled))

            def set_editing_enabled(self, enabled):
                self.calls.append(("edit", enabled))

            def set_interactive(self, enabled):
                self.calls.append(("interactive", enabled))

        access = _SelectiveAccess({Feature.SELECT_PLAN_ITEMS})
        viewer = Recorder()
        layers_sidebar = Recorder()
        cover_sheet_button = QtWidgets.QToolButton()
        self.addCleanup(cover_sheet_button.deleteLater)
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), access, _ProjectData()
        )
        coordinator.opengl_viewer = viewer
        coordinator.set_bid_layers_sidebar(layers_sidebar)
        coordinator.set_cover_sheet_button(cover_sheet_button)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_plan_view(_PlanView())
        coordinator.refresh()
        self.assertEqual(viewer.calls, [("pick", True), ("edit", False)])
        self.assertEqual(layers_sidebar.calls, [("interactive", False)])
        self.assertFalse(cover_sheet_button.isEnabled())
        viewer.calls.clear()
        layers_sidebar.calls.clear()
        access.allowed.update(
            {Feature.EDIT_PLAN_ITEMS, Feature.EDIT_PAGE_SETTINGS, Feature.COVER_SHEET}
        )
        coordinator.refresh()
        self.assertEqual(viewer.calls, [("pick", True), ("edit", True)])
        self.assertEqual(layers_sidebar.calls, [("interactive", True)])
        self.assertTrue(cover_sheet_button.isEnabled())

    def test_conditions_sidebar_permissions_follow_matching_access_features(self):
        _app()

        class Access(_SelectiveAccess):
            def __init__(self, allowed, locked, licensed):
                super().__init__(allowed)
                self.locked = locked
                self.licensed = licensed

            def is_bid_locked(self):
                return self.locked

            def has_license(self):
                return self.licensed

        class Sidebar:
            def __init__(self):
                self.calls = {}

            def get_active_condition_uid(self):
                return None

            def set_create_enabled(self, enabled):
                self.calls["create"] = enabled

            def set_duplicate_enabled(self, enabled):
                self.calls["duplicate"] = enabled

            def set_copy_enabled(self, enabled):
                self.calls["copy"] = enabled

            def set_delete_enabled(self, enabled):
                self.calls["delete"] = enabled

            def set_edit_enabled(self, enabled, read_only_enabled=False):
                self.calls["edit"] = (enabled, read_only_enabled)

            def set_create_folder_enabled(self, enabled):
                self.calls["folder"] = enabled

        cases = (
            (
                {Feature.EDIT_CONDITION, Feature.COPY_CONDITION},
                False,
                True,
                {
                    "create": True,
                    "duplicate": False,
                    "copy": True,
                    "delete": False,
                    "edit": (True, False),
                    "folder": False,
                },
            ),
            (
                {
                    Feature.DUPLICATE_CONDITION,
                    Feature.DELETE_CONDITION,
                    Feature.EDIT_CONDITION_STRUCTURE,
                },
                True,
                True,
                {
                    "create": False,
                    "duplicate": True,
                    "copy": False,
                    "delete": True,
                    "edit": (False, True),
                    "folder": True,
                },
            ),
            (
                set(),
                True,
                False,
                {
                    "create": False,
                    "duplicate": False,
                    "copy": False,
                    "delete": False,
                    "edit": (False, False),
                    "folder": False,
                },
            ),
        )
        for allowed, locked, licensed, expected in cases:
            with self.subTest(allowed=sorted(f.name for f in allowed), locked=locked):
                sidebar = Sidebar()
                coordinator = ToolbarStateCoordinator(
                    _UiState(), Access(allowed, locked, licensed), _ProjectData()
                )
                coordinator.set_conditions_sidebar(sidebar)
                coordinator.refresh()
                self.assertEqual(sidebar.calls, expected)

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
                plan_view.set_cursor_mode(CURSOR_MODE_ANNOTATION_PLACE)
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
                plan_view.set_cursor_mode(CURSOR_MODE_ANNOTATION_PLACE)
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
        place_action.setChecked(True)
        plan_view.begin_area()
        plan_view.current_page_uid = None
        coordinator.refresh()
        self.assertFalse(access.area_active)
        self.assertTrue(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertFalse(copy_action.isEnabled())
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

    def test_summary_delete_requires_condition_delete_permission_and_row_state(
        self,
    ):
        _app()
        copy_action = QtGui.QAction()
        delete_action = QtGui.QAction()
        access = _SelectiveAccess(set())
        summary_tab = _SummaryTab(can_copy=True, can_delete=True)
        coordinator = ToolbarStateCoordinator(_UiState(), access, _ProjectData())
        coordinator.set_copy_action(copy_action)
        coordinator.set_delete_action(delete_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_SUMMARY))
        coordinator.set_condition_summary_tab(summary_tab)
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())
        access.allowed.add(Feature.DELETE_CONDITION)
        coordinator.refresh()
        self.assertTrue(delete_action.isEnabled())
        summary_tab._can_delete = False
        summary_tab._can_copy = False
        coordinator.refresh()
        self.assertFalse(copy_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())

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

    def test_project_delete_is_blocked_for_root_project_projects_with_bids_and_no_file(
        self,
    ):
        _app()

        class ProjectsWithBids(_ProjectData):
            def project_has_bids(self, _uid, _file_path=None):
                return True

        cases = (
            ("deletable project", "2", "db.mdb", _ProjectData(), True),
            ("root project", "1", "db.mdb", _ProjectData(), False),
            ("project with bids", "2", "db.mdb", ProjectsWithBids(), False),
            ("project without file", "2", None, _ProjectData(), False),
        )
        for label, project_uid, file_path, project_data, expected in cases:
            with self.subTest(label):
                delete_action = QtGui.QAction()
                coordinator = ToolbarStateCoordinator(
                    _UiState(
                        selected_project_uid=project_uid,
                        selected_file_path=file_path,
                    ),
                    _Access(),
                    project_data,
                )
                coordinator.set_delete_action(delete_action)
                coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_PROJECTS))
                coordinator.refresh()
                self.assertIs(delete_action.isEnabled(), expected)

    def test_bid_delete_uses_bid_delete_permission_not_project_tree_permission(self):
        _app()
        ref = BidRef("db.mdb", "bid-1")
        delete_action = QtGui.QAction()
        ui_state = _UiState(
            selected_bid_refs=[ref],
            selected_bid_ref=ref,
            selected_file_path="db.mdb",
        )
        coordinator = ToolbarStateCoordinator(
            ui_state,
            _SelectiveAccess({Feature.EDIT_PROJECT_TREE_STRUCTURE}),
            _ProjectData(),
        )
        coordinator.set_delete_action(delete_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_PROJECTS))
        coordinator.refresh()
        self.assertFalse(delete_action.isEnabled())
        coordinator._access = _SelectiveAccess({Feature.DELETE_BID})
        coordinator.refresh()
        self.assertTrue(delete_action.isEnabled())

    def test_read_only_project_copy_is_separate_from_duplicate_and_paste(self):
        _app()
        ref = BidRef("sql-db", "bid-1")
        copy_action = QtGui.QAction()
        cut_action = QtGui.QAction()
        paste_action = QtGui.QAction()
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
        coordinator.set_cut_action(cut_action)
        coordinator.set_paste_action(paste_action)
        coordinator.set_duplicate_action(duplicate_action)
        coordinator.set_bid_clipboard(_BidClipboard([ref]))
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_PROJECTS))
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertFalse(cut_action.isEnabled())
        self.assertFalse(paste_action.isEnabled())
        self.assertFalse(duplicate_action.isEnabled())

    def test_bid_cut_delete_and_copy_follow_their_own_permissions(self):
        _app()
        ref = BidRef("db.mdb", "bid-1")
        cases = (
            ("delete only", {Feature.DELETE_BID}, (False, True, True)),
            ("copy only", {Feature.COPY_BID}, (True, False, False)),
            (
                "project tree only",
                {Feature.EDIT_PROJECT_TREE_STRUCTURE},
                (False, False, False),
            ),
        )
        for label, allowed, (copy, cut, delete) in cases:
            with self.subTest(label):
                copy_action = QtGui.QAction()
                cut_action = QtGui.QAction()
                delete_action = QtGui.QAction()
                coordinator = ToolbarStateCoordinator(
                    _UiState(
                        selected_bid_refs=[ref],
                        selected_bid_ref=ref,
                        selected_file_path="db.mdb",
                    ),
                    _SelectiveAccess(allowed),
                    _ProjectData(),
                )
                coordinator.set_copy_action(copy_action)
                coordinator.set_cut_action(cut_action)
                coordinator.set_delete_action(delete_action)
                coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_PROJECTS))
                coordinator.refresh()
                self.assertIs(copy_action.isEnabled(), copy)
                self.assertIs(cut_action.isEnabled(), cut)
                self.assertIs(delete_action.isEnabled(), delete)

    def test_bid_copy_and_cut_require_selection_from_one_database(self):
        _app()
        refs = [BidRef("first.mdb", "bid-1"), BidRef("second.mdb", "bid-2")]
        copy_action = QtGui.QAction()
        cut_action = QtGui.QAction()
        ui_state = _UiState(
            selected_bid_refs=refs[:1],
            selected_bid_ref=refs[0],
            selected_file_path="first.mdb",
        )
        coordinator = ToolbarStateCoordinator(ui_state, _Access(), _ProjectData())
        coordinator.set_copy_action(copy_action)
        coordinator.set_cut_action(cut_action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_PROJECTS))
        coordinator.refresh()
        self.assertTrue(copy_action.isEnabled())
        self.assertTrue(cut_action.isEnabled())
        ui_state._selected_bid_refs = refs
        coordinator.refresh()
        self.assertFalse(copy_action.isEnabled())
        self.assertFalse(cut_action.isEnabled())

    def test_summary_tab_blocks_bid_paste_that_projects_tab_allows(self):
        _app()
        ref = BidRef("db.mdb", "bid-1")
        paste_action = QtGui.QAction()
        tab_widget = _IndexWidget(TAB_INDEX_PROJECTS)
        coordinator = ToolbarStateCoordinator(
            _UiState(selected_project_uid="2", selected_file_path="db.mdb"),
            _Access(),
            _ProjectData(),
        )
        coordinator.set_paste_action(paste_action)
        coordinator.set_bid_clipboard(_BidClipboard([ref]))
        coordinator.set_tab_widget(tab_widget)
        coordinator.refresh()
        self.assertTrue(paste_action.isEnabled())
        tab_widget.setCurrentIndex(TAB_INDEX_SUMMARY)
        coordinator.refresh()
        self.assertFalse(paste_action.isEnabled())

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
                active_page_uid="p1",
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


class ToolbarNoPagePlacementTests(unittest.TestCase):
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

        ui_state = SimpleNamespace(
            get_selected_bid_refs=lambda: [],
            get_selected_bid_ref=lambda: None,
            selected_project_uid=None,
            selected_page_uids=[],
            active_page_uid=None,
        )
        toolbar = ToolbarStateCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: True,
                is_bid_locked=lambda: False,
                has_license=lambda: True,
                current_plan_surface_context=lambda: object(),
                get_plan_surface_access=lambda _context: PlanSurfaceAccessState(
                    can_place_plan_items=True
                ),
                subscribe_access_state_changed=lambda _callback: None,
                unsubscribe_access_state_changed=lambda _callback: None,
            ),
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: {
                    "c1": Condition(
                        uid="c1",
                        name="Area",
                        condition_type=Condition.TYPE_AREA,
                        layer_visible=True,
                    )
                }
            ),
        )
        action = FakeAction()
        plan_view = FakePlanView()
        toolbar.set_place_action(action)
        toolbar.set_plan_view(plan_view)
        toolbar.set_tab_widget(SimpleNamespace(currentIndex=lambda: TAB_INDEX_TAKEOFF))
        toolbar.set_view_stack(SimpleNamespace(currentIndex=lambda: 1))
        toolbar.refresh()
        self.assertIs(action.enabled, False)
        ui_state.active_page_uid = "p1"
        plan_view.current_page_uid = "p1"
        toolbar.refresh()
        self.assertIs(action.enabled, True)
        ui_state.active_page_uid = None
        toolbar.refresh()
        self.assertIs(action.enabled, False)


class ToolbarStateCoordinatorPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_backout_action_state_matches_context_rules(self):
        class FakeAccess:
            def __init__(self, allowed: bool):
                self.allowed = allowed

            def is_allowed(self, feature):
                return self.allowed and feature == Feature.PLACE_PLAN_ITEMS

            def subscribe_access_state_changed(self, _callback):
                pass

            def unsubscribe_access_state_changed(self, _callback):
                pass

        class FakeUiState:
            def __init__(self, active_page_uid="page-1"):
                self.active_page_uid = active_page_uid

            def get_selected_bid_refs(self):
                return []

        class FakeProjectData:
            def __init__(self, conditions):
                self.conditions = conditions

            def get_bid_conditions(self):
                return dict(self.conditions)

        class FakeIndexWidget:
            def __init__(self, index):
                self.index = index

            def currentIndex(self):
                return self.index

        class FakeCoordinateSystem:
            @staticmethod
            def parse_position(position):
                return list(position)

        class FakeSceneBuilder:
            def get_coordinate_system(self):
                return FakeCoordinateSystem()

        class BackoutPlanView:
            _valid_backout_parent_uid = TakeoffPlanView._valid_backout_parent_uid
            backout_parent_candidate_uid = TakeoffPlanView.backout_parent_candidate_uid
            current_page_uid = "page-1"

            def __init__(self, selected, takeoffs, conditions):
                self._selected_uids = set(selected)
                self._current_takeoffs = dict(takeoffs)
                self._current_conditions = dict(conditions)
                self._scene_builder = FakeSceneBuilder()
                self.cancel_calls = 0

            @property
            def backout_mode_active(self):
                return False

            def is_backout_context_valid(self):
                return False

            def cancel_backout_mode(self):
                self.cancel_calls += 1

        area_condition = Condition(
            uid="area-condition",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        hidden_area = Condition(
            uid="hidden-area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=False,
        )
        linear_condition = Condition(
            uid="linear-condition",
            condition_type=Condition.TYPE_LINEAR,
            layer_visible=True,
        )
        valid_area = Takeoff(
            uid="area",
            condition_uid="area-condition",
            position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
            parent_uid="0",
        )
        conditions = {
            condition.uid: condition
            for condition in (area_condition, hidden_area, linear_condition)
        }

        def enabled_for(
            selected,
            takeoffs,
            tab_index=TAB_INDEX_TAKEOFF,
            view_index=1,
            allowed=True,
            active_page_uid="page-1",
        ):
            _preferences_support__app()
            action = QtGui.QAction()
            coordinator = ToolbarStateCoordinator(
                FakeUiState(active_page_uid),
                FakeAccess(allowed),
                FakeProjectData(conditions),
            )
            coordinator.set_backout_action(action)
            coordinator.set_tab_widget(FakeIndexWidget(tab_index))
            coordinator.set_view_stack(FakeIndexWidget(view_index))
            coordinator.set_plan_view(BackoutPlanView(selected, takeoffs, conditions))
            coordinator.refresh_backout_action()
            return action.isEnabled()

        self.assertTrue(enabled_for({"area"}, {"area": valid_area}))
        self.assertFalse(enabled_for(set(), {"area": valid_area}))
        self.assertFalse(enabled_for({"area", "other"}, {"area": valid_area}))
        self.assertFalse(
            enabled_for(
                {"hole"},
                {
                    "hole": Takeoff(
                        uid="hole",
                        condition_uid="area-condition",
                        position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
                        parent_uid="area",
                    )
                },
            )
        )
        self.assertFalse(
            enabled_for(
                {"linear"},
                {
                    "linear": Takeoff(
                        uid="linear",
                        condition_uid="linear-condition",
                        position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
                        parent_uid="0",
                    )
                },
            )
        )
        self.assertFalse(
            enabled_for(
                {"hidden"},
                {
                    "hidden": Takeoff(
                        uid="hidden",
                        condition_uid="hidden-area",
                        position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
                        parent_uid="0",
                    )
                },
            )
        )
        self.assertFalse(
            enabled_for(
                {"short"},
                {
                    "short": Takeoff(
                        uid="short",
                        condition_uid="area-condition",
                        position=[0.0, 0.0, 4.0, 0.0],
                        parent_uid="0",
                    )
                },
            )
        )
        self.assertFalse(enabled_for({"area"}, {"area": valid_area}, view_index=0))
        self.assertFalse(enabled_for({"area"}, {"area": valid_area}, tab_index=0))
        self.assertFalse(enabled_for({"area"}, {"area": valid_area}, allowed=False))
        self.assertFalse(
            enabled_for({"area"}, {"area": valid_area}, active_page_uid="page-2")
        )
        self.assertFalse(
            enabled_for({"area"}, {"area": valid_area}, active_page_uid=None)
        )


class ToolbarBackoutActiveModeTests(unittest.TestCase):
    ENABLED_TOOLTIP = "Create a backout in the selected area takeoff"
    DISABLED_TOOLTIP = "Select a visible area takeoff to create a backout."

    class _BackoutPlanView(_PlanView):
        def __init__(self, active, context_valid, candidate_uid=None):
            super().__init__()
            self.backout_mode_active = active
            self._context_valid = context_valid
            self._candidate_uid = candidate_uid
            self.cancel_calls = 0

        def is_backout_context_valid(self):
            return self._context_valid

        def cancel_backout_mode(self):
            self.cancel_calls += 1
            self.backout_mode_active = False

        def backout_parent_candidate_uid(self):
            return self._candidate_uid

    def _refresh_backout(self, plan_view, view_index=1):
        _app()
        action = QtGui.QAction()
        action.setCheckable(True)
        coordinator = ToolbarStateCoordinator(
            _UiState(active_page_uid="p1"), _Access(), _ProjectData()
        )
        coordinator.set_backout_action(action)
        coordinator.set_tab_widget(_IndexWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_IndexWidget(view_index))
        coordinator.set_plan_view(plan_view)
        coordinator.refresh_backout_action()
        return action

    def test_valid_active_backout_keeps_action_checked_and_enabled(self):
        plan_view = self._BackoutPlanView(active=True, context_valid=True)
        action = self._refresh_backout(plan_view)
        self.assertEqual(plan_view.cancel_calls, 0)
        self.assertTrue(action.isEnabled())
        self.assertTrue(action.isChecked())
        self.assertEqual(action.toolTip(), self.ENABLED_TOOLTIP)

    def test_active_backout_with_invalid_context_is_cancelled(self):
        plan_view = self._BackoutPlanView(active=True, context_valid=False)
        action = self._refresh_backout(plan_view)
        self.assertEqual(plan_view.cancel_calls, 1)
        self.assertFalse(action.isEnabled())
        self.assertFalse(action.isChecked())
        self.assertEqual(action.toolTip(), self.DISABLED_TOOLTIP)

    def test_active_backout_is_cancelled_when_plan_context_becomes_unavailable(self):
        plan_view = self._BackoutPlanView(active=True, context_valid=True)
        action = self._refresh_backout(plan_view, view_index=0)
        self.assertEqual(plan_view.cancel_calls, 1)
        self.assertFalse(action.isEnabled())
        self.assertFalse(action.isChecked())

    def test_inactive_backout_follows_parent_candidate_and_tooltip(self):
        plan_view = self._BackoutPlanView(
            active=False, context_valid=False, candidate_uid="area"
        )
        action = self._refresh_backout(plan_view)
        self.assertEqual(plan_view.cancel_calls, 0)
        self.assertTrue(action.isEnabled())
        self.assertFalse(action.isChecked())
        self.assertEqual(action.toolTip(), self.ENABLED_TOOLTIP)
