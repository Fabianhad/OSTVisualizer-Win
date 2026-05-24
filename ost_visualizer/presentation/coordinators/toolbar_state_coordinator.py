from typing import Optional
from PySide6 import QtGui, QtWidgets
from ..config import TAB_INDEX_TAKEOFF
from ..managers.ui_access_manager import Feature


class ToolbarStateCoordinator:
    def __init__(self, ui_state_manager, ui_access_manager, project_data):
        self._ui_state = ui_state_manager
        self._access = ui_access_manager
        self._project_data = project_data
        self._copy_action: Optional[QtGui.QAction] = None
        self._cut_action: Optional[QtGui.QAction] = None
        self._paste_action: Optional[QtGui.QAction] = None
        self._delete_action: Optional[QtGui.QAction] = None
        self._undo_action: Optional[QtGui.QAction] = None
        self._redo_action: Optional[QtGui.QAction] = None
        self._duplicate_action: Optional[QtGui.QAction] = None
        self._select_action: Optional[QtGui.QAction] = None
        self._select_all_action: Optional[QtGui.QAction] = None
        self._cover_sheet_button: Optional[QtWidgets.QToolButton] = None
        self._page_settings_bar = None
        self._bid_layers_sidebar = None
        self._place_action: Optional[QtGui.QAction] = None
        self.plan_view = None
        self.plan_view_handler = None
        self.bid_clipboard = None
        self.undo_service = None
        self.opengl_viewer = None
        self.conditions_sidebar = None
        self._tab_widget = None

    def set_copy_action(self, action: QtGui.QAction) -> None:
        self._copy_action = action

    def set_cut_action(self, action: QtGui.QAction) -> None:
        self._cut_action = action

    def set_paste_action(self, action: QtGui.QAction) -> None:
        self._paste_action = action

    def set_delete_action(self, action: QtGui.QAction) -> None:
        self._delete_action = action

    def set_undo_action(self, action: QtGui.QAction) -> None:
        self._undo_action = action

    def set_redo_action(self, action: QtGui.QAction) -> None:
        self._redo_action = action

    def set_duplicate_action(self, action: QtGui.QAction) -> None:
        self._duplicate_action = action

    def set_select_action(self, action: QtGui.QAction) -> None:
        self._select_action = action

    def set_select_all_action(self, action: QtGui.QAction) -> None:
        self._select_all_action = action

    def set_cover_sheet_button(self, btn: QtWidgets.QToolButton) -> None:
        self._cover_sheet_button = btn

    def set_page_settings_bar(self, bar) -> None:
        self._page_settings_bar = bar

    def set_bid_layers_sidebar(self, sidebar) -> None:
        self._bid_layers_sidebar = sidebar

    def set_place_action(self, action: QtGui.QAction) -> None:
        self._place_action = action

    def set_plan_view(self, view) -> None:
        self.plan_view = view

    def set_plan_view_handler(self, handler) -> None:
        self.plan_view_handler = handler

    def set_bid_clipboard(self, clipboard) -> None:
        self.bid_clipboard = clipboard

    def set_undo_service(self, undo_service) -> None:
        self.undo_service = undo_service

    def set_conditions_sidebar(self, sidebar) -> None:
        self.conditions_sidebar = sidebar

    def set_tab_widget(self, tab_widget) -> None:
        self._tab_widget = tab_widget

    def _is_condition_placeable(self, condition_uid: str) -> bool:
        condition = self._project_data.get_bid_conditions().get(condition_uid)
        return bool(condition and condition.layer_visible)

    def refresh(self) -> None:
        current_tab = self._tab_widget.currentIndex() if self._tab_widget else 0
        on_takeoff_tab = current_tab == TAB_INDEX_TAKEOFF
        has_takeoff_selection = bool(self.plan_view and self.plan_view.has_selection)
        selected_bid_refs = self._ui_state.get_selected_bid_refs()
        selected_bids_same_file = self._same_file_refs(selected_bid_refs)
        bid_paste_allowed = self._can_paste_bid_clipboard()
        if self._copy_action:
            if on_takeoff_tab:
                self._copy_action.setEnabled(
                    self._access.is_allowed(Feature.SELECT_TAKEOFFS)
                    and has_takeoff_selection
                )
            else:
                self._copy_action.setEnabled(
                    bool(selected_bid_refs)
                    and selected_bids_same_file
                    and self._access.is_allowed(Feature.DUPLICATE_BID)
                )
        if self._cut_action:
            if on_takeoff_tab:
                self._cut_action.setEnabled(False)
            else:
                self._cut_action.setEnabled(
                    bool(selected_bid_refs)
                    and selected_bids_same_file
                    and self._access.is_allowed(Feature.DELETE_BID)
                )
        if self._paste_action:
            if on_takeoff_tab:
                self._paste_action.setEnabled(
                    self._access.is_allowed(Feature.SELECT_TAKEOFFS)
                    and bool(
                        self.plan_view_handler
                        and self.plan_view_handler.can_paste_to_current_bid()
                    )
                )
            else:
                self._paste_action.setEnabled(bid_paste_allowed)
        if self._delete_action:
            if on_takeoff_tab:
                self._delete_action.setEnabled(
                    self._access.is_allowed(Feature.SELECT_TAKEOFFS)
                    and bool(self.plan_view and self.plan_view.has_selection)
                )
            elif not self._access.is_allowed(Feature.DELETE_BID):
                self._delete_action.setEnabled(False)
            elif self._ui_state.get_selected_bid_ref():
                self._delete_action.setEnabled(True)
            elif self._ui_state.selected_project_uid:
                uid = self._ui_state.selected_project_uid
                self._delete_action.setEnabled(
                    uid != "1" and not self._project_data.project_has_bids(uid)
                )
            else:
                self._delete_action.setEnabled(False)
        undo_redo_allowed = (
            on_takeoff_tab
            and self._access.is_allowed(Feature.SELECT_TAKEOFFS)
            and bool(self.undo_service)
        )
        if self._undo_action:
            self._undo_action.setEnabled(
                undo_redo_allowed and self.undo_service.can_undo()
            )
        if self._redo_action:
            self._redo_action.setEnabled(
                undo_redo_allowed and self.undo_service.can_redo()
            )
        if self._duplicate_action:
            if on_takeoff_tab:
                self._duplicate_action.setEnabled(
                    self._access.is_allowed(Feature.SELECT_TAKEOFFS)
                    and bool(self.plan_view and self.plan_view.has_selection)
                )
            else:
                self._duplicate_action.setEnabled(
                    self._access.is_allowed(Feature.DUPLICATE_BID)
                )
        if self._select_all_action:
            if on_takeoff_tab:
                self._select_all_action.setEnabled(
                    self._access.is_allowed(Feature.SELECT_TAKEOFFS)
                    and bool(self.plan_view)
                )
            else:
                self._select_all_action.setEnabled(False)
        if self._cover_sheet_button:
            self._cover_sheet_button.setEnabled(
                self._access.is_allowed(Feature.COVER_SHEET)
            )
        if self._page_settings_bar:
            self._page_settings_bar.set_interactive(
                self._access.is_allowed(Feature.EDIT_PAGE_SETTINGS)
            )
        selected_condition_uids = (
            self.conditions_sidebar.get_selected_condition_uids()
            if self.conditions_sidebar
            else []
        )
        selected_placeable_condition_uids = [
            uid
            for uid in selected_condition_uids
            if self.conditions_sidebar.is_condition_placeable(uid)
        ]
        selected_takeoff_condition_uid = (
            self.plan_view.selected_takeoff_condition_uid() if self.plan_view else None
        )
        selected_takeoff_condition_placeable = bool(
            selected_takeoff_condition_uid
        ) and self._is_condition_placeable(selected_takeoff_condition_uid)
        active_place_condition_uid = (
            self.plan_view.place_condition_uid if self.plan_view else None
        )
        active_place_condition_placeable = bool(
            active_place_condition_uid
        ) and self._is_condition_placeable(active_place_condition_uid)
        can_place_takeoff = (
            on_takeoff_tab
            and self._access.is_allowed(Feature.PLACE_TAKEOFF)
            and bool(self.plan_view)
            and (
                bool(selected_placeable_condition_uids)
                or selected_takeoff_condition_placeable
                or active_place_condition_placeable
            )
        )
        if self._place_action:
            self._place_action.setEnabled(can_place_takeoff)
            if (
                not can_place_takeoff
                and self._place_action.isChecked()
                and self._select_action
            ):
                self._select_action.setChecked(True)
        select_allowed = self._access.is_allowed(Feature.SELECT_TAKEOFFS)
        if self.plan_view:
            self.plan_view.set_selection_enabled(select_allowed)
        if self.opengl_viewer:
            self.opengl_viewer.set_pick_enabled(select_allowed)
        if self._bid_layers_sidebar:
            self._bid_layers_sidebar.set_interactive(
                self._access.is_allowed(Feature.EDIT_PAGE_SETTINGS)
            )
        if self.conditions_sidebar:
            self.conditions_sidebar.set_create_enabled(
                self._access.is_allowed(Feature.EDIT_CONDITION)
            )
            self.conditions_sidebar.set_duplicate_enabled(
                self._access.is_allowed(Feature.DUPLICATE_CONDITION)
            )
            self.conditions_sidebar.set_delete_enabled(
                self._access.is_allowed(Feature.DELETE_CONDITION)
            )
            self.conditions_sidebar.set_edit_enabled(
                self._access.is_allowed(Feature.EDIT_CONDITION),
                read_only_enabled=(
                    self._access.is_bid_locked() and self._access.has_license()
                ),
            )
            self.conditions_sidebar.set_create_folder_enabled(
                self._access.is_allowed(Feature.CREATE_FOLDER)
            )

    def cleanup(self) -> None:
        self._copy_action = None
        self._cut_action = None
        self._paste_action = None
        self._delete_action = None
        self._undo_action = None
        self._redo_action = None
        self._duplicate_action = None
        self._select_action = None
        self._select_all_action = None
        self._cover_sheet_button = None
        self._page_settings_bar = None
        self._bid_layers_sidebar = None
        self._place_action = None
        self.plan_view = None
        self.plan_view_handler = None
        self.bid_clipboard = None
        self.undo_service = None
        self.opengl_viewer = None
        self.conditions_sidebar = None
        self._tab_widget = None
        self._ui_state = None
        self._access = None
        self._project_data = None

    def _same_file_refs(self, refs: list) -> bool:
        if not refs:
            return False
        file_path = refs[0].file_path
        return all(ref.file_path == file_path for ref in refs)

    def _can_paste_bid_clipboard(self) -> bool:
        if not self.bid_clipboard or not self.bid_clipboard.has_content():
            return False
        target_file_path = self._ui_state.selected_file_path
        if not target_file_path:
            return False
        if self.bid_clipboard.source_file_path != target_file_path:
            return False
        bid_ref = self._ui_state.get_selected_bid_ref()
        target_project_uid = (
            self._project_data.find_project_uid_for_bid(bid_ref) if bid_ref else None
        )
        if target_project_uid == "1":
            return False
        feature = (
            Feature.DELETE_BID if self.bid_clipboard.is_cut else Feature.DUPLICATE_BID
        )
        if not self._access.is_allowed(feature):
            return False
        return self._ui_state.selected_project_uid != "1"
