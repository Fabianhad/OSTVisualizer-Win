import datetime
from typing import Callable, Dict, List, Optional
from PySide6 import QtWidgets
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.config import Config
from ...domain.entities.cover_sheet import CoverSheetData, CoverSheetPage
from ..components.menu_builder import MenuBuilder
from ..dialogs.about_dialog import AboutDialog
from ..dialogs.cover_sheet.dialog import CoverSheetDialog
from ..dialogs.options.dialog import OptionsDialog
from ..managers.ui_access_manager import Feature
from ..utils.image_show_mode import mode_to_flags
from ..utils.messagebox import DB_LOCKED_HINT, show_critical, show_warning
from ..utils.ost_blocking import exec_with_ost_blocking
from ..utils.windows import remove_minimize_maximize

_TAKEOFF_SCOPED_VARIABLE_KEYS = {
    "color_mode",
    "grayscale",
    "page_invert",
    "page_bitonal",
    "show_overlay_image",
    "show_original_image",
    "takeoff_2d_tab_visible",
    "takeoff_3d_tab_visible",
}


class MenuController:
    def __init__(
        self,
        window,
        icon_provider: IWindowIconProvider,
        config_service,
        ui_state_manager,
        handlers,
        ui_access_manager,
        project_data_service,
        export_service,
        project_read_service,
        project_write_service,
        infrastructure_provider,
        event_bus,
        file_loading_service,
        create_new_database_fn,
        shared_actions=None,
    ):
        self.window = window
        self.icon_provider = icon_provider
        self.config_service = config_service
        self.ui_state_manager = ui_state_manager
        self.handlers = handlers
        self.ui_access_manager = ui_access_manager
        self.project_data = project_data_service
        self._project_read_service = project_read_service
        self._project_write_service = project_write_service
        self._infrastructure_provider = infrastructure_provider
        self._event_bus = event_bus
        self._file_loading_service = file_loading_service
        self._create_new_database_fn = create_new_database_fn
        self._shared_actions = dict(shared_actions or {})
        self.menu_bar: QtWidgets.QMenuBar | None = None
        self._actions: Dict[str, QtWidgets.QAction] = {}
        self._menus: Dict[str, QtWidgets.QMenu] = {}
        self._variable_actions: Dict[str, list[QtWidgets.QAction]] = {}
        self._state_getters: Dict[str, Callable[[], object]] = {}
        self._export_formats: List[str] = export_service.get_available_formats()
        self._tool_action_enabled_state: Dict[str, bool] = {}

    def create_menu(self) -> QtWidgets.QMenuBar:
        menu_callbacks = self._get_menu_callbacks()
        state_getters = self._get_state_getters()
        menu_builder = MenuBuilder(
            self.window,
            menu_callbacks,
            state_getters,
            self._export_formats,
            self._shared_actions,
        )
        result = menu_builder.create_menu()
        self.menu_bar = result.menu_bar
        self._actions = result.actions
        self._menus = result.menus
        self._variable_actions = result.variable_actions
        self._state_getters = state_getters
        for menu in self._menus.values():
            menu.aboutToShow.connect(self.update_menu_states)
        self._sync_variable_actions()
        self.update_menu_states()
        return self.menu_bar

    def _get_menu_callbacks(self) -> Dict[str, Callable]:
        callbacks = {
            "new_project": self._new_project,
            "new_folder": self._new_folder,
            "new_database": self._new_database,
            "open_files": self.handlers.file_ops.open_files,
            "unload_file": self.handlers.file_ops.unload_file,
            "check_license": self.window.show_license_dialog,
            "quit": self._on_quit,
            "import_ost": lambda: self.handlers.import_.import_ost(),
            "import_osp": lambda: self.handlers.import_.import_osp(),
            "export_as_pdf": lambda: self.handlers.export.export_as_pdf(
                self.project_data.get_selected_page_uids()
            ),
            "export_as_ost": lambda: self.handlers.export.export_as_ost(),
            "export_as_osp": lambda: self.handlers.export.export_as_osp(),
            "set_takeoff_color_mode": self._set_takeoff_color_mode,
            "toggle_takeoff_grayscale": self._toggle_takeoff_grayscale,
            "toggle_main_toolbar": self._set_main_toolbar_visible,
            "toggle_view_toolbar": self._set_view_toolbar_visible,
            "toggle_plan_tools_toolbar": self._set_plan_tools_toolbar_visible,
            "toggle_2d_tab": self._set_2d_tab_visible,
            "toggle_3d_tab": self._set_3d_tab_visible,
            "toggle_page_invert": self.handlers.ui_event.toggle_page_invert,
            "toggle_page_bitonal": self.handlers.ui_event.toggle_page_bitonal,
            "rotate_takeoff_left": self.handlers.ui_event.rotate_selected_takeoffs_left,
            "rotate_takeoff_right": (
                self.handlers.ui_event.rotate_selected_takeoffs_right
            ),
            "flip_takeoff_horizontal": (
                self.handlers.ui_event.flip_selected_takeoffs_horizontal
            ),
            "flip_takeoff_vertical": (
                self.handlers.ui_event.flip_selected_takeoffs_vertical
            ),
            "rotate_image_left": self.handlers.ui_event.rotate_image_left,
            "rotate_image_right": self.handlers.ui_event.rotate_image_right,
            "flip_image_horizontal": self.handlers.ui_event.flip_image_horizontal,
            "flip_image_vertical": self.handlers.ui_event.flip_image_vertical,
            "select_overlay_image": self.handlers.ui_event.select_overlay_image,
            "remove_overlay_image": self.handlers.ui_event.remove_overlay_image,
            "show_overlay_image": self.handlers.ui_event.show_overlay_image,
            "show_original_image": self.handlers.ui_event.show_original_image,
            "delete_page": self.handlers.ui_event.delete_current_page,
            "show_cover_sheet": self._show_cover_sheet,
            "show_areas": self.handlers.ui_event.open_areas_dialog,
            "renumber_conditions": self.handlers.ui_event.renumber_conditions,
            "employees": self.handlers.ui_event.open_employees_dialog,
            "job_statuses": self.handlers.ui_event.open_job_statuses_dialog,
            "condition_types": self.handlers.ui_event.open_condition_types_dialog,
            "payroll_classes": self.handlers.ui_event.open_payroll_classes_dialog,
            "select_objects_in_current_area": self._select_objects_in_current_area,
            "set_scale": lambda: self.handlers.ui_event.open_set_scale_dialog(),
            "rename_page": lambda: self.handlers.ui_event.open_rename_page_dialog(),
            "adjust_images": lambda: self.handlers.ui_event.open_adjust_images_dialog(),
            "options": self._show_options_dialog,
            "show_about": self._show_about_dialog,
        }
        for fmt in self._export_formats:
            callbacks[f"export_as_{fmt}"] = (
                lambda checked=False, f=fmt: self.handlers.export.export_format(
                    f, self.project_data.get_selected_page_uids()
                )
            )
        return callbacks

    def _get_state_getters(self) -> Dict[str, Callable[[], object]]:
        return {
            "color_mode": lambda: self.ui_state_manager.state.color_mode,
            "grayscale": lambda: self.ui_state_manager.state.grayscale_enabled,
            "main_toolbar_visible": lambda: self._workspace_toolbar_visible(
                self.window.MAIN_TOOLBAR_KEY
            ),
            "view_toolbar_visible": lambda: self._workspace_toolbar_visible(
                self.window.VIEW_TOOLBAR_KEY
            ),
            "plan_tools_toolbar_visible": lambda: self._workspace_toolbar_visible(
                self.window.PLAN_TOOLS_TOOLBAR_KEY
            ),
            "page_invert": lambda: self._active_page_invert(),
            "page_bitonal": lambda: self._active_page_bitonal(),
            "show_overlay_image": lambda: self._active_page_overlay_flags()[1],
            "show_original_image": lambda: self._active_page_overlay_flags()[0],
            "takeoff_2d_tab_visible": self.window.is_takeoff_2d_tab_visible,
            "takeoff_3d_tab_visible": self.window.is_takeoff_3d_tab_visible,
        }

    def _set_takeoff_color_mode(self, color_mode: str) -> None:
        self.config_service.update_app_options({"color_mode": color_mode})

    def _toggle_takeoff_grayscale(self, _checked=False) -> bool:
        config = self.config_service.get_config_snapshot()
        self.config_service.update_app_options(
            {"grayscale_enabled": not config.grayscale_enabled}
        )
        return self.config_service.get_config_snapshot().grayscale_enabled

    def _workspace_toolbar_visible(self, key: str) -> bool:
        return self.window.get_workspace_toolbar_visibility_state().get(key, True)

    def _set_main_toolbar_visible(self, visible: bool) -> None:
        self.window.set_workspace_toolbar_preference(
            self.window.MAIN_TOOLBAR_KEY, visible
        )

    def _set_view_toolbar_visible(self, visible: bool) -> None:
        self.window.set_workspace_toolbar_preference(
            self.window.VIEW_TOOLBAR_KEY, visible
        )

    def _set_plan_tools_toolbar_visible(self, visible: bool) -> None:
        self.window.set_workspace_toolbar_preference(
            self.window.PLAN_TOOLS_TOOLBAR_KEY, visible
        )

    def _set_2d_tab_visible(self, visible: bool) -> None:
        self.window.set_takeoff_2d_tab_visible(visible)
        self._sync_variable_actions()

    def _set_3d_tab_visible(self, visible: bool) -> None:
        self.window.set_takeoff_3d_tab_visible(visible)
        self._sync_variable_actions()

    def update_menu_states(self) -> None:
        if not self.menu_bar:
            return
        takeoff_active = self.window.is_takeoff_tab_active()
        self._sync_variable_actions(takeoff_active)
        export_allowed = self.ui_access_manager.is_allowed(Feature.EXPORT)
        unload_enabled = self.ui_access_manager.is_allowed(Feature.UNLOAD_FILE)
        unload_action = self._actions.get("unload_file")
        if unload_action:
            unload_action.setEnabled(unload_enabled)
        can_create_project_tree_items = self._should_enable_project_tree_creation()
        new_project_action = self._actions.get("new_project")
        if new_project_action:
            new_project_action.setEnabled(can_create_project_tree_items)
        new_folder_action = self._actions.get("new_folder")
        if new_folder_action:
            new_folder_action.setEnabled(can_create_project_tree_items)
        new_database_action = self._actions.get("new_database")
        if new_database_action:
            new_database_action.setEnabled(
                self.ui_access_manager.is_allowed(Feature.CREATE_DATABASE)
            )
        import_menu = self._menus.get("import")
        if import_menu:
            import_menu.setEnabled(self._should_enable_import())
        export_enabled = export_allowed and self._should_enable_export()
        bid_file_export_enabled = self.ui_access_manager.is_allowed(
            Feature.EXPORT_BID_FILE
        )
        export_menu = self._menus.get("export")
        if export_menu:
            export_menu.setEnabled(export_enabled or bid_file_export_enabled)
        for fmt in self._export_formats:
            action = self._actions.get(f"export_as_{fmt}")
            if action:
                action.setEnabled(export_enabled)
        pdf_action = self._actions.get("export_as_pdf")
        if pdf_action:
            pdf_enabled = export_allowed and self._should_enable_pdf_export()
            pdf_action.setEnabled(pdf_enabled)
        ost_action = self._actions.get("export_as_ost")
        if ost_action:
            ost_action.setEnabled(bid_file_export_enabled)
        osp_action = self._actions.get("export_as_osp")
        if osp_action:
            osp_action.setEnabled(bid_file_export_enabled)
        html_options = self._menus.get("html export options".lower())
        if html_options:
            html_options.setEnabled(export_allowed)
        takeoff_menu = self._menus.get("takeoff")
        if takeoff_menu:
            takeoff_menu.setEnabled(True)
        for action_key in (
            "toggle_view_toolbar",
            "toggle_plan_tools_toolbar",
            "toggle_2d_tab",
            "toggle_3d_tab",
            "zoom_in",
            "zoom_out",
            "reset_view",
            "layers_sidebar",
            "conditions_sidebar",
            "annotation_window",
        ):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(takeoff_active)
        self._set_variable_actions_enabled("color_mode", takeoff_active)
        self._set_variable_actions_enabled("grayscale", takeoff_active)
        previous_page_action = self._actions.get("previous_page")
        if previous_page_action:
            previous_page_action.setEnabled(
                takeoff_active and self.window.can_go_previous_takeoff_page()
            )
        next_page_action = self._actions.get("next_page")
        if next_page_action:
            next_page_action.setEnabled(
                takeoff_active and self.window.can_go_next_takeoff_page()
            )
        tools_menu = self._menus.get("tools")
        if tools_menu:
            tools_menu.setEnabled(True)
        self._sync_tool_action_states(takeoff_active)
        image_menu = self._menus.get("image")
        if image_menu:
            image_menu.setEnabled(True)
        page_image_enabled = self._should_enable_page_image_action()
        for action_key in (
            "adjust_images",
            "toggle_page_invert",
            "toggle_page_bitonal",
            "rotate_image_left",
            "rotate_image_right",
            "flip_image_horizontal",
            "flip_image_vertical",
            "select_overlay_image",
            "show_original_image",
        ):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(page_image_enabled)
        active_page = self._active_page()
        page_has_overlay = bool(active_page and active_page.overlay_image_path)
        for action_key in ("remove_overlay_image", "show_overlay_image"):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(page_image_enabled and page_has_overlay)
        plan_view = self.window.get_takeoff_plan_view()
        has_selected_takeoffs = bool(plan_view and plan_view.has_selected_takeoffs)
        can_transform_takeoffs = (
            takeoff_active
            and has_selected_takeoffs
            and self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS)
        )
        for action_key in (
            "rotate_takeoff_left",
            "rotate_takeoff_right",
            "flip_takeoff_horizontal",
            "flip_takeoff_vertical",
        ):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(can_transform_takeoffs)
        rotate_flip_menu = self._menus.get("rotate/flip")
        if rotate_flip_menu:
            rotate_flip_menu.setEnabled(can_transform_takeoffs or page_image_enabled)
        select_current_area_action = self._actions.get("select_objects_in_current_area")
        if select_current_area_action:
            select_current_area_action.setEnabled(
                takeoff_active
                and bool(
                    plan_view
                    and plan_view.current_page_uid
                    and plan_view.has_takeoff_objects
                )
            )
        set_scale_action = self._actions.get("set_scale")
        if set_scale_action:
            set_scale_action.setEnabled(page_image_enabled)
        rename_page_action = self._actions.get("rename_page")
        if rename_page_action:
            rename_page_action.setEnabled(page_image_enabled)
        selected_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        project_menu = self._menus.get("project")
        if project_menu:
            project_menu.setEnabled(True)
        cover_sheet_action = self._actions.get("show_cover_sheet")
        if cover_sheet_action:
            cover_sheet_action.setEnabled(
                bool(selected_bid_ref)
                and self.ui_access_manager.is_allowed(Feature.COVER_SHEET)
            )
        show_areas_action = self._actions.get("show_areas")
        if show_areas_action:
            show_areas_action.setEnabled(
                bool(selected_bid_ref)
                and self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS)
            )
        renumber_action = self._actions.get("renumber_conditions")
        if renumber_action:
            renumber_action.setEnabled(self.handlers.ui_event.can_renumber_conditions())
        master_menu = self._menus.get("master")
        if master_menu:
            master_menu.setEnabled(True)
        master_allowed = self._can_open_master_data_dialog()
        for action_key in (
            "employees",
            "job_statuses",
            "payroll_classes",
            "condition_types",
        ):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(master_allowed)

    def trigger_menu_callback(self, command_key: str) -> None:
        callback = self._get_menu_callbacks().get(command_key)
        if callback and self.is_context_command_enabled(command_key):
            callback()

    def is_context_command_enabled(self, command_key: str) -> bool:
        if command_key in ("import_ost", "import_osp"):
            return self._should_enable_import()
        if command_key == "delete_page":
            return self.handlers.ui_event.can_delete_current_page()
        self.update_menu_states()
        action = self._actions.get(command_key)
        if action:
            return action.isEnabled()
        return command_key in self._get_menu_callbacks()

    def trigger_menu_action(self, action_key: str) -> None:
        self.update_menu_states()
        action = self._actions.get(action_key)
        if action:
            if action.isEnabled():
                action.trigger()
            return
        callback = self._get_menu_callbacks().get(action_key)
        if callback and self.is_context_command_enabled(action_key):
            callback()

    def get_menu_action_state(self, action_key: str) -> dict:
        self.update_menu_states()
        action = self._actions.get(action_key)
        if action:
            return {
                "text": action.text(),
                "enabled": action.isEnabled(),
                "checkable": action.isCheckable(),
                "checked": action.isChecked(),
            }
        if action_key == "delete_page":
            return {
                "text": "Delete Page",
                "enabled": self.handlers.ui_event.can_delete_current_page(),
                "checkable": False,
                "checked": False,
            }
        return {
            "text": action_key.replace("_", " ").title(),
            "enabled": self.is_context_command_enabled(action_key),
            "checkable": False,
            "checked": False,
        }

    def get_export_formats(self) -> List[str]:
        return list(self._export_formats)

    def _sync_tool_action_states(self, takeoff_active: bool) -> None:
        for action_key in (
            "select_tool",
            "place_tool",
            "zoom_tool",
            "pan_tool",
            "dimension_tool",
        ):
            action = self._actions.get(action_key)
            if not action:
                continue
            if takeoff_active:
                enabled = self._tool_action_enabled_state.pop(
                    action_key, action.isEnabled()
                )
                action.setEnabled(enabled)
            else:
                if (
                    action_key not in self._tool_action_enabled_state
                    or action.isEnabled()
                ):
                    self._tool_action_enabled_state[action_key] = action.isEnabled()
                action.setEnabled(False)
        backout_action = self._actions.get("backout_mode")
        if backout_action:
            self._tool_action_enabled_state.pop("backout_mode", None)
            self.handlers.ui_event.refresh_backout_action()

    def _set_variable_actions_enabled(self, variable: str, enabled: bool) -> None:
        for action in self._variable_actions.get(variable, ()):
            action.setEnabled(enabled)

    def _sync_variable_actions(self, takeoff_active: Optional[bool] = None) -> None:
        if takeoff_active is None:
            takeoff_active = self.window.is_takeoff_tab_active()
        for variable, actions in self._variable_actions.items():
            if not takeoff_active and variable in _TAKEOFF_SCOPED_VARIABLE_KEYS:
                self._clear_checked_actions(actions)
                continue
            current_value = self._current_state_value(variable)
            for action in actions:
                data = action.data()
                action.blockSignals(True)
                if data is None:
                    action.setChecked(bool(current_value))
                else:
                    action.setChecked(data == current_value)
                action.blockSignals(False)

    @staticmethod
    def _clear_checked_actions(actions) -> None:
        groups = {action.actionGroup() for action in actions if action.actionGroup()}
        previous_exclusive = {group: group.isExclusive() for group in groups}
        for group in groups:
            group.setExclusive(False)
        try:
            for action in actions:
                previous_blocked = action.blockSignals(True)
                try:
                    action.setChecked(False)
                finally:
                    action.blockSignals(previous_blocked)
        finally:
            for group, was_exclusive in previous_exclusive.items():
                group.setExclusive(was_exclusive)

    def _current_state_value(self, key: str):
        if key == "color_mode":
            return self.ui_state_manager.state.color_mode
        if key == "grayscale":
            return self.ui_state_manager.state.grayscale_enabled
        if key in (
            "main_toolbar_visible",
            "view_toolbar_visible",
            "plan_tools_toolbar_visible",
            "page_invert",
            "page_bitonal",
            "show_overlay_image",
            "show_original_image",
            "takeoff_2d_tab_visible",
            "takeoff_3d_tab_visible",
        ):
            return self._state_getters[key]()
        return None

    def _active_page(self):
        page_uid = self.ui_state_manager.active_page_uid
        if not page_uid:
            return None
        return self.project_data.get_page(page_uid)

    def _active_page_invert(self) -> bool:
        page = self._active_page()
        return bool(page and page.invert)

    def _active_page_bitonal(self) -> bool:
        page = self._active_page()
        return bool(page and page.bitonal)

    def _active_page_overlay_flags(self) -> tuple[bool, bool]:
        page = self._active_page()
        if not page:
            return (False, False)
        return mode_to_flags(page.image_show_mode)

    def _should_enable_page_image_action(self) -> bool:
        return (
            self.window.is_takeoff_tab_active()
            and self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS)
            and self._active_page() is not None
        )

    def _should_enable_export(self) -> bool:
        selected_pages = self.project_data.get_selected_page_uids()
        if not selected_pages:
            return False
        has_takeoffs = self.project_data.has_takeoffs_for_pages(selected_pages)
        has_annotations = any(
            self.project_data.get_page_annotations(page_uid)
            for page_uid in selected_pages
        )
        return has_takeoffs or has_annotations

    def _should_enable_pdf_export(self) -> bool:
        selected_pages = self.project_data.get_selected_page_uids()
        if not selected_pages:
            return False
        page_uid = selected_pages[0]
        current_page = self.project_data.get_page(page_uid)
        if not current_page:
            return False
        if current_page.width_pts <= 0 or current_page.height_pts <= 0:
            return False
        if current_page.image_path:
            image_path_lower = current_page.image_path.lower()
            if image_path_lower.endswith(".tif") or image_path_lower.endswith(".tiff"):
                return False
        return True

    def _should_enable_import(self) -> bool:
        if self.ui_state_manager.selected_project_uid == "1":
            return False
        return self.ui_access_manager.is_allowed(Feature.IMPORT)

    def _select_objects_in_current_area(self) -> None:
        if not self.window.is_takeoff_tab_active():
            return
        plan_view = self.window.get_takeoff_plan_view()
        page_settings_bar = self.window.get_page_settings_bar()
        if not plan_view or not page_settings_bar:
            return
        area_uid = page_settings_bar.get_selected_area_uid() or None
        plan_view.select_takeoffs_in_area(area_uid)
        self.handlers.ui_event.refresh_toolbar()

    def _show_cover_sheet(self) -> None:
        if not self.ui_access_manager.is_allowed(Feature.COVER_SHEET):
            return
        if not self.ui_state_manager.get_selected_bid_ref():
            return
        self.handlers.cover_sheet.open_cover_sheet()

    def _should_enable_project_tree_creation(self) -> bool:
        return self.ui_access_manager.can_create_project_tree_items(
            self._resolve_project_tree_file_path() is not None
        )

    def _can_open_master_data_dialog(self) -> bool:
        return (
            self._resolve_master_data_file_path() is not None
            and self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA)
        )

    def _resolve_master_data_file_path(self) -> Optional[str]:
        return self.window.get_selected_database_context_file_path()

    def _resolve_target_project_uid(self) -> Optional[str]:
        selected_project = self.ui_state_manager.selected_project_uid
        if selected_project and selected_project != "1":
            return selected_project
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref:
            return self.project_data.find_project_uid_for_bid(bid_ref)
        return None

    def _new_project(self) -> None:
        file_path = self._resolve_project_tree_file_path()
        if not self.ui_access_manager.can_create_project_tree_items(
            file_path is not None
        ):
            return
        target_project_uid = self._resolve_target_project_uid()
        defaults = self._project_read_service.get_settings_defaults(file_path)
        job_statuses = self._project_read_service.get_job_statuses(file_path)
        employees, pay_classes = (
            self._project_read_service.get_employees_and_pay_classes(file_path)
        )
        sf1 = defaults.get("scale_factor1", 0.125)
        sf2 = defaults.get("scale_factor2", 12.0)
        pw = defaults.get("page_width", 42.0)
        ph = defaults.get("page_height", 30.0)
        next_bid_no = defaults.get("next_bid_no", 1)
        now = datetime.datetime.now()
        bid_date_str = now.strftime("%Y %m %d %H %M 0")
        data = CoverSheetData(
            bid_uid="",
            job_status_uid="",
            job_name=f"New Project {next_bid_no}",
            estimator_uid="",
            notes="",
            bid_date=bid_date_str,
            bid_no=str(next_bid_no),
            job_id="",
            measure_base=defaults.get("measure_base", 0),
            takeoff_increments=defaults.get("takeoff_increments", 1.0),
            scale_style=defaults.get("scale_style", 1),
            scale_factor1=sf1,
            scale_factor2=sf2,
            page_width=pw,
            page_height=ph,
            pages_without_folder=[
                CoverSheetPage(
                    uid="new_page_1",
                    sheet_no="00001",
                    name="Page 1",
                    width=pw,
                    height=ph,
                    scale_factor1=sf1,
                    scale_factor2=sf2,
                    image_path="",
                    overlay_image_path="",
                    index=1,
                    show_mode=0,
                )
            ],
            job_statuses=job_statuses,
            employees=employees,
            pay_classes=pay_classes,
        )
        dialog = CoverSheetDialog(
            self.icon_provider,
            self.window,
            data,
            has_license=self.ui_access_manager.has_license(),
            save_job_statuses_fn=lambda ch: self._project_write_service.save_job_statuses(
                file_path, ch
            ),
            reload_job_statuses_fn=lambda: self._project_read_service.get_job_statuses(
                file_path
            ),
            save_employees_fn=lambda ch: self._project_write_service.save_employees(
                file_path, ch
            ),
            save_pay_classes_fn=lambda ch: self._project_write_service.save_pay_classes(
                file_path, ch
            ),
            reload_employees_fn=lambda: self._project_read_service.get_employees_and_pay_classes(
                file_path
            ),
            pdf_page_sizes_fn=self._infrastructure_provider.get_pdf_page_sizes,
            create_mode=True,
        )
        try:
            result = exec_with_ost_blocking(dialog, self._event_bus)
            if result != QtWidgets.QDialog.DialogCode.Accepted:
                return
            updates = dialog.get_updates()
            create_result = self._project_write_service.create_bid_result(
                file_path, target_project_uid, updates
            )
            if create_result.refresh_failed:
                show_warning(
                    self.window,
                    "Refresh Error",
                    "The bid was created, but the project tree could not be refreshed. "
                    "Reopen the database to see the created bid.",
                )
                return
            if not create_result:
                show_critical(
                    self.window,
                    "New Project",
                    "Failed to create bid.",
                )
                return
        finally:
            dialog.deleteLater()

    def _resolve_project_tree_file_path(self) -> Optional[str]:
        fp = self.ui_state_manager.selected_file_path
        if fp:
            return fp
        project_uid = self.ui_state_manager.selected_project_uid
        if project_uid:
            found = self.project_data.get_hierarchy().find_file_path_for_project(
                project_uid
            )
            if found:
                return found
        loaded_files = self.project_data.get_hierarchy().loaded_files
        if len(loaded_files) == 1:
            return loaded_files[0].file_path
        return None

    def _new_folder(self) -> None:
        file_path = self._resolve_project_tree_file_path()
        if not self.ui_access_manager.can_create_project_tree_items(
            file_path is not None
        ):
            return
        create_result = self._project_write_service.create_project_result(
            file_path, "New Project"
        )
        if create_result.refresh_failed:
            show_warning(
                self.window,
                "Refresh Error",
                "The project was created, but the project tree could not be refreshed. "
                "Reopen the database to see the created project.",
            )
            return
        if not create_result:
            show_critical(
                self.window,
                "New Project",
                f"Failed to create project. {DB_LOCKED_HINT}",
            )
            return
        new_uid = str(create_result.value)
        self.window.project_view.schedule_rename(new_uid)

    def _new_database(self) -> None:
        if not self.ui_access_manager.is_allowed(Feature.CREATE_DATABASE):
            return
        dialog = QtWidgets.QInputDialog(self.window)
        dialog.setWindowTitle("New Database")
        dialog.setLabelText("Database name:")
        dialog.setTextValue("")
        dialog.setModal(True)
        self.icon_provider.set_window_icon(dialog)
        remove_minimize_maximize(dialog)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name = dialog.textValue().strip()
        db_path = self._create_new_database_fn(name or None)
        if not db_path:
            show_critical(
                self.window,
                "New Database",
                "Failed to create database. Check logs for details.",
            )
            return
        result = self._file_loading_service.load_file(db_path)
        if result.success:
            self._event_bus.publish(AppEvents.FILE_OPENED, file_path=result.file_path)

    def _show_about_dialog(self) -> None:
        dialog = AboutDialog(self.icon_provider, self.window)
        try:
            dialog.exec()
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def _show_options_dialog(self) -> None:
        dialog = OptionsDialog(
            self.config_service.get_config_snapshot(),
            self.window,
            apply_callback=self.config_service.update_app_options,
            reset_callback=self._reset_all_settings,
        )
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _reset_all_settings(self) -> Config:
        default_config = Config()
        self.config_service.update_app_options(default_config)
        self.window.reset_workspace_state_to_defaults()
        return self.config_service.get_config_snapshot()

    def _on_quit(self) -> None:
        self.window.close()

    def cleanup(self) -> None:
        self.icon_provider = None
