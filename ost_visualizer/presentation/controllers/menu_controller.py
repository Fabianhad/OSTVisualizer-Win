import datetime
from typing import Callable, Dict, List, Optional
from PySide6 import QtWidgets
from shiboken6 import isValid
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.config import Config
from ...domain.entities.cover_sheet import CoverSheetData, CoverSheetPage
from ...domain.entities.database_descriptor import DatabaseBackend
from ...domain.entities.file_state import normalize_path
from ..actions.action_ids import (
    ACTION_ADJUST_IMAGES,
    ACTION_ANNOTATION_WINDOW,
    ACTION_BACKOUT_MODE,
    ACTION_CONDITIONS_SIDEBAR,
    ACTION_DEFAULT_LAYERS,
    ACTION_DELETE_PAGE,
    ACTION_FLIP_IMAGE_HORIZONTAL,
    ACTION_FLIP_IMAGE_VERTICAL,
    ACTION_LAYERS_SIDEBAR,
    ACTION_NEW_DATABASE,
    ACTION_NEW_FOLDER,
    ACTION_NEW_PROJECT,
    ACTION_NEXT_PAGE,
    ACTION_OPEN_FILES,
    ACTION_PREVIOUS_PAGE,
    ACTION_REMOVE_OVERLAY_IMAGE,
    ACTION_RESET_VIEW,
    ACTION_ROTATE_IMAGE_LEFT,
    ACTION_ROTATE_IMAGE_RIGHT,
    ACTION_SELECT_OVERLAY_IMAGE,
    ACTION_SET_TAKEOFF_DISPLAY_MODE_2D,
    ACTION_SET_TAKEOFF_DISPLAY_MODE_3D,
    ACTION_SHOW_COVER_SHEET,
    ACTION_SHOW_ORIGINAL_IMAGE,
    ACTION_SHOW_OVERLAY_IMAGE,
    ACTION_TOGGLE_MAIN_TOOLBAR,
    ACTION_TOGGLE_PLAN_TOOLS_TOOLBAR,
    ACTION_TOGGLE_TAKEOFF_DISPLAY_MODES_SYNC,
    ACTION_TOGGLE_VIEW_TOOLBAR,
    ACTION_ZOOM_IN,
    ACTION_ZOOM_OUT,
)
from ..components.menu_builder import MenuBuilder
from ..dialogs.about_dialog import AboutDialog
from ..dialogs.cover_sheet.dialog import CoverSheetDialog
from ..dialogs.new_database_type_dialog import NewDatabaseTypeDialog
from ..dialogs.options.dialog import OptionsDialog
from ..managers.ui_access_manager import Feature
from ..interfaces.i_workspace_shell import CurrentAreaSelectionContext
from ..utils.image_show_mode import mode_to_flags
from ..utils.dialog import delete_later_if_valid
from ..utils.messagebox import DB_LOCKED_HINT, show_critical, show_warning
from ..utils.ost_blocking import exec_with_ost_blocking
from ..utils.plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS, PLAN_TOOL_ACTION_KEYS
from ..utils.windows import remove_minimize_maximize

_ANNOTATION_TOOL_ACTION_KEYS = {spec.action_key for spec in PLAN_ANNOTATION_TOOL_SPECS}
_TAKEOFF_SCOPED_VARIABLE_KEYS = {
    "display_modes_synced",
    "display_mode_3d",
    "display_mode_2d",
    "grayscale",
    "page_invert",
    "page_bitonal",
    ACTION_SHOW_OVERLAY_IMAGE,
    ACTION_SHOW_ORIGINAL_IMAGE,
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
        deferred_persistence_manager,
        workspace_state_model,
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
        self._deferred_persistence = deferred_persistence_manager
        self._workspace_state_model = workspace_state_model
        self._shared_actions = dict(shared_actions or {})
        self.menu_bar: QtWidgets.QMenuBar | None = None
        self._actions: Dict[str, QtWidgets.QAction] = {}
        self._menus: Dict[str, QtWidgets.QMenu] = {}
        self._variable_actions: Dict[str, list[QtWidgets.QAction]] = {}
        self._state_getters: Dict[str, Callable[[], object]] = {}
        self._export_formats: List[str] = export_service.get_available_formats()
        self._tool_action_enabled_state: Dict[str, bool] = {}

    def _flush_deferred_for_file(self, file_path: Optional[str]) -> bool:
        if not file_path:
            return True
        return bool(self._deferred_persistence.flush_for_file(file_path))

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
            ACTION_NEW_PROJECT: self._new_project,
            ACTION_NEW_FOLDER: self._new_folder,
            ACTION_NEW_DATABASE: self._new_database,
            ACTION_OPEN_FILES: self.handlers.file_ops.open_files,
            "unload_file": self.handlers.file_ops.unload_file,
            "check_license": self.window.show_license_dialog,
            "quit": self._on_quit,
            "import_ost": lambda: self.handlers.import_.import_ost(),
            "import_osp": lambda: self.handlers.import_.import_osp(),
            "export_as_pdf": lambda: self.handlers.export.export_as_pdf(
                self.project_data.get_selected_page_uids()
            ),
            "export_summary_csv": lambda: self.handlers.export.export_summary_csv(),
            "export_as_ost": lambda: self.handlers.export.export_as_ost(),
            "export_as_osp": lambda: self.handlers.export.export_as_osp(),
            ACTION_SET_TAKEOFF_DISPLAY_MODE_3D: self._set_takeoff_display_mode_3d,
            ACTION_SET_TAKEOFF_DISPLAY_MODE_2D: self._set_takeoff_display_mode_2d,
            ACTION_TOGGLE_TAKEOFF_DISPLAY_MODES_SYNC: (
                self._toggle_takeoff_display_modes_sync
            ),
            "toggle_takeoff_grayscale": self._toggle_takeoff_grayscale,
            ACTION_TOGGLE_MAIN_TOOLBAR: self._set_main_toolbar_visible,
            ACTION_TOGGLE_VIEW_TOOLBAR: self._set_view_toolbar_visible,
            ACTION_TOGGLE_PLAN_TOOLS_TOOLBAR: self._set_plan_tools_toolbar_visible,
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
            ACTION_ROTATE_IMAGE_LEFT: self.handlers.ui_event.rotate_image_left,
            ACTION_ROTATE_IMAGE_RIGHT: self.handlers.ui_event.rotate_image_right,
            ACTION_FLIP_IMAGE_HORIZONTAL: self.handlers.ui_event.flip_image_horizontal,
            ACTION_FLIP_IMAGE_VERTICAL: self.handlers.ui_event.flip_image_vertical,
            ACTION_SELECT_OVERLAY_IMAGE: self.handlers.ui_event.select_overlay_image,
            ACTION_REMOVE_OVERLAY_IMAGE: self.handlers.ui_event.remove_overlay_image,
            ACTION_SHOW_OVERLAY_IMAGE: self.handlers.ui_event.show_overlay_image,
            ACTION_SHOW_ORIGINAL_IMAGE: self.handlers.ui_event.show_original_image,
            ACTION_DELETE_PAGE: self.handlers.ui_event.delete_current_page,
            ACTION_SHOW_COVER_SHEET: self._show_cover_sheet,
            "show_areas": self.handlers.ui_event.open_areas_dialog,
            "renumber_conditions": self.handlers.ui_event.renumber_conditions,
            "employees": self.handlers.ui_event.open_employees_dialog,
            "job_statuses": self.handlers.ui_event.open_job_statuses_dialog,
            "condition_types": self.handlers.ui_event.open_condition_types_dialog,
            "payroll_classes": self.handlers.ui_event.open_payroll_classes_dialog,
            ACTION_DEFAULT_LAYERS: self.handlers.ui_event.open_default_layers_dialog,
            "select_objects_in_current_area": self._select_objects_in_current_area,
            "set_scale": lambda: self.handlers.ui_event.open_set_scale_dialog(),
            "rename_page": lambda: self.handlers.ui_event.open_rename_page_dialog(),
            ACTION_ADJUST_IMAGES: lambda: (
                self.handlers.ui_event.open_adjust_images_dialog()
            ),
            "options": self._show_options_dialog,
            "show_about": self._show_about_dialog,
        }
        for fmt in self._export_formats:
            callbacks[f"export_as_{fmt}"] = (
                lambda _checked=False, f=fmt: self.handlers.export.export_format(
                    f,
                    self.project_data.get_selected_page_uids(),
                    self.ui_state_manager.active_page_uid,
                )
            )
        return callbacks

    def _get_state_getters(self) -> Dict[str, Callable[[], object]]:
        return {
            "display_modes_synced": (
                lambda: self.ui_state_manager.state.display_modes_synced
            ),
            "display_mode_3d": lambda: self.ui_state_manager.state.display_mode_3d,
            "display_mode_2d": lambda: self.ui_state_manager.state.display_mode_2d,
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
            ACTION_SHOW_OVERLAY_IMAGE: lambda: self._active_page_overlay_flags()[1],
            ACTION_SHOW_ORIGINAL_IMAGE: lambda: self._active_page_overlay_flags()[0],
            "takeoff_2d_tab_visible": self.window.is_takeoff_2d_tab_visible,
            "takeoff_3d_tab_visible": self.window.is_takeoff_3d_tab_visible,
        }

    def _set_takeoff_display_mode_3d(self, display_mode: str) -> None:
        config = self.config_service.get_config_snapshot()
        update = {"display_mode_3d": display_mode}
        if config.display_modes_synced:
            update["display_mode_2d"] = display_mode
        self.config_service.update_app_options(update)

    def _set_takeoff_display_mode_2d(self, display_mode: str) -> None:
        config = self.config_service.get_config_snapshot()
        update = {"display_mode_2d": display_mode}
        if config.display_modes_synced:
            update["display_mode_3d"] = display_mode
        self.config_service.update_app_options(update)

    def _toggle_takeoff_display_modes_sync(self, _checked=False) -> bool:
        config = self.config_service.get_config_snapshot()
        next_synced = not config.display_modes_synced
        update = {"display_modes_synced": next_synced}
        if next_synced:
            update["display_mode_2d"] = config.display_mode_3d
        self.config_service.update_app_options(update)
        return self.config_service.get_config_snapshot().display_modes_synced

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
        unload_enabled = self.ui_access_manager.is_allowed(Feature.UNLOAD_FILE)
        unload_action = self._actions.get("unload_file")
        if unload_action:
            unload_action.setEnabled(unload_enabled)
        can_create_project_tree_items = self._should_enable_project_tree_creation()
        new_project_action = self._actions.get(ACTION_NEW_PROJECT)
        if new_project_action:
            new_project_action.setEnabled(can_create_project_tree_items)
        new_folder_action = self._actions.get(ACTION_NEW_FOLDER)
        if new_folder_action:
            new_folder_action.setEnabled(can_create_project_tree_items)
        new_database_action = self._actions.get(ACTION_NEW_DATABASE)
        if new_database_action:
            new_database_action.setEnabled(
                self.ui_access_manager.is_allowed(Feature.CREATE_DATABASE)
            )
        import_menu = self._menus.get("import")
        if import_menu:
            import_menu.setEnabled(self._should_enable_import())
        export_action_states = self._export_action_enabled_states()
        export_menu = self._menus.get("export")
        if export_menu:
            export_menu.setEnabled(any(export_action_states.values()))
        for fmt in self._export_formats:
            action = self._actions.get(f"export_as_{fmt}")
            if action:
                action.setEnabled(export_action_states.get(f"export_as_{fmt}", False))
        pdf_action = self._actions.get("export_as_pdf")
        if pdf_action:
            pdf_action.setEnabled(export_action_states["export_as_pdf"])
        summary_csv_action = self._actions.get("export_summary_csv")
        if summary_csv_action:
            summary_csv_action.setEnabled(export_action_states["export_summary_csv"])
        ost_action = self._actions.get("export_as_ost")
        if ost_action:
            ost_action.setEnabled(export_action_states["export_as_ost"])
        osp_action = self._actions.get("export_as_osp")
        if osp_action:
            osp_action.setEnabled(export_action_states["export_as_osp"])
        html_options = self._menus.get("html export options".lower())
        if html_options:
            html_options.setEnabled(export_action_states.get("export_as_html", False))
        takeoff_menu = self._menus.get("takeoff")
        if takeoff_menu:
            takeoff_menu.setEnabled(True)
        for action_key in (
            "toggle_view_toolbar",
            "toggle_plan_tools_toolbar",
            "toggle_2d_tab",
            "toggle_3d_tab",
            ACTION_ZOOM_IN,
            ACTION_ZOOM_OUT,
            ACTION_RESET_VIEW,
            ACTION_LAYERS_SIDEBAR,
            ACTION_CONDITIONS_SIDEBAR,
            ACTION_ANNOTATION_WINDOW,
        ):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(takeoff_active)
        self._set_variable_actions_enabled("display_modes_synced", takeoff_active)
        self._set_variable_actions_enabled("display_mode_3d", takeoff_active)
        self._set_variable_actions_enabled("display_mode_2d", takeoff_active)
        self._set_variable_actions_enabled("grayscale", takeoff_active)
        previous_page_action = self._actions.get(ACTION_PREVIOUS_PAGE)
        if previous_page_action:
            previous_page_action.setEnabled(
                takeoff_active and self.window.can_go_previous_takeoff_page()
            )
        next_page_action = self._actions.get(ACTION_NEXT_PAGE)
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
            ACTION_ADJUST_IMAGES,
            "toggle_page_invert",
            "toggle_page_bitonal",
            ACTION_ROTATE_IMAGE_LEFT,
            ACTION_ROTATE_IMAGE_RIGHT,
            ACTION_FLIP_IMAGE_HORIZONTAL,
            ACTION_FLIP_IMAGE_VERTICAL,
            ACTION_SELECT_OVERLAY_IMAGE,
        ):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(page_image_enabled)
        active_page = self._active_page()
        page_has_original = bool(active_page and active_page.image_path)
        page_has_overlay = bool(active_page and active_page.overlay_image_path)
        show_original_action = self._actions.get(ACTION_SHOW_ORIGINAL_IMAGE)
        if show_original_action:
            show_original_action.setEnabled(page_image_enabled and page_has_original)
        for action_key in (ACTION_REMOVE_OVERLAY_IMAGE, ACTION_SHOW_OVERLAY_IMAGE):
            action = self._actions.get(action_key)
            if action:
                action.setEnabled(page_image_enabled and page_has_overlay)
        plan_view = self.window.get_takeoff_plan_view()
        has_selected_takeoffs = bool(plan_view and plan_view.has_selected_takeoffs)
        can_transform_takeoffs = (
            takeoff_active
            and has_selected_takeoffs
            and self.ui_access_manager.is_allowed(Feature.EDIT_PLAN_ITEMS)
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
            area_context = self._current_area_selection_context()
            area_plan_view = area_context.plan_view
            select_current_area_action.setEnabled(
                self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS)
                and bool(
                    area_plan_view
                    and area_plan_view.current_page_uid
                    and area_plan_view.has_takeoff_objects
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
        cover_sheet_action = self._actions.get(ACTION_SHOW_COVER_SHEET)
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
            ACTION_DEFAULT_LAYERS,
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
        if command_key == ACTION_DELETE_PAGE:
            return self.handlers.ui_event.can_delete_current_page()
        export_enabled = self._export_command_enabled(command_key)
        if export_enabled is not None:
            return export_enabled
        self.update_menu_states()
        action = self._actions.get(command_key)
        if action:
            return self._is_menu_action_enabled(command_key, action)
        return command_key in self._get_menu_callbacks()

    def trigger_menu_action(self, action_key: str) -> None:
        self.update_menu_states()
        action = self._actions.get(action_key)
        if action:
            if self._is_menu_action_enabled(action_key, action):
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
                "enabled": self._is_menu_action_enabled(action_key, action),
                "checkable": action.isCheckable(),
                "checked": action.isChecked(),
            }
        if action_key == ACTION_DELETE_PAGE:
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

    def _export_action_enabled_states(self) -> Dict[str, bool]:
        command_keys = [f"export_as_{fmt}" for fmt in self._export_formats]
        command_keys.extend(
            ["export_summary_csv", "export_as_pdf", "export_as_ost", "export_as_osp"]
        )
        return {
            command_key: bool(self._export_command_enabled(command_key))
            for command_key in command_keys
        }

    def _export_command_enabled(self, command_key: str) -> Optional[bool]:
        export_allowed = self.ui_access_manager.is_allowed(Feature.EXPORT)
        if command_key == "export_summary_csv":
            return export_allowed and self._should_enable_summary_csv_export()
        if command_key == "export_as_pdf":
            return export_allowed and self._should_enable_pdf_export()
        if command_key in ("export_as_ost", "export_as_osp"):
            return self.ui_access_manager.is_allowed(Feature.EXPORT_BID_FILE) and bool(
                self._active_selected_bid_ref()
            )
        if command_key.startswith("export_as_"):
            format_key = command_key[len("export_as_") :]
            if format_key in self._export_formats:
                return export_allowed and self._should_enable_export()
        return None

    def _is_menu_action_enabled(self, action_key: str, action) -> bool:
        if action_key in _ANNOTATION_TOOL_ACTION_KEYS:
            return action.isEnabled() and self.ui_access_manager.is_allowed(
                Feature.PLACE_ANNOTATIONS
            )
        return action.isEnabled()

    def _sync_tool_action_states(self, takeoff_active: bool) -> None:
        for action_key in PLAN_TOOL_ACTION_KEYS:
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
        backout_action = self._actions.get(ACTION_BACKOUT_MODE)
        if backout_action:
            self._tool_action_enabled_state.pop(ACTION_BACKOUT_MODE, None)
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
                if data is None:
                    action.setChecked(bool(current_value))
                else:
                    action.setChecked(data == current_value)

    @staticmethod
    def _clear_checked_actions(actions) -> None:
        groups = {action.actionGroup() for action in actions if action.actionGroup()}
        previous_exclusive = {group: group.isExclusive() for group in groups}
        for group in groups:
            group.setExclusive(False)
        try:
            for action in actions:
                action.setChecked(False)
        finally:
            for group, was_exclusive in previous_exclusive.items():
                stale_checked_action = group.checkedAction()
                if stale_checked_action and not stale_checked_action.isChecked():
                    group_actions = list(group.actions())
                    for action in group_actions:
                        group.removeAction(action)
                    for action in group_actions:
                        group.addAction(action)
                group.setExclusive(was_exclusive)

    def _current_state_value(self, key: str):
        getter = self._state_getters.get(key)
        return getter() if getter else None

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
        if not self._active_selected_bid_ref():
            return False
        selected_pages = self.project_data.get_selected_page_uids()
        if not selected_pages:
            return False
        return self.project_data.has_takeoffs_for_pages(selected_pages)

    def _should_enable_pdf_export(self) -> bool:
        if not self._active_selected_bid_ref():
            return False
        selected_pages = self.project_data.get_selected_page_uids()
        return any(
            page and page.width_pts > 0 and page.height_pts > 0
            for page in (self.project_data.get_page(uid) for uid in selected_pages)
        )

    def _should_enable_summary_csv_export(self) -> bool:
        return bool(
            self._active_selected_bid_ref()
            and self.project_data.get_bid_conditions()
            and self.project_data.get_all_takeoffs()
        )

    def _active_selected_bid_ref(self):
        selected_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not selected_bid_ref:
            return None
        current_bid_ref = self.project_data.get_current_bid_ref()
        if current_bid_ref != selected_bid_ref:
            return None
        return selected_bid_ref

    def _should_enable_import(self) -> bool:
        if self.ui_state_manager.selected_project_uid == "1":
            return False
        return self.ui_access_manager.is_allowed(Feature.IMPORT)

    def _is_summary_tab_active(self) -> bool:
        return self.window.is_summary_tab_active()

    def _select_objects_in_current_area(self) -> None:
        if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        context = self._current_area_selection_context()
        if context.plan_view is None:
            show_warning(
                context.parent,
                "Select Objects in Current Area",
                "The active plan view is no longer available. Activate an open plan "
                "view and try again.",
            )
            return
        context.plan_view.select_takeoffs_in_area(context.area_uid)
        self.handlers.ui_event.refresh_toolbar()

    def _current_area_selection_context(self) -> CurrentAreaSelectionContext:
        return self.window.resolve_current_area_selection_context()

    def _show_cover_sheet(self) -> None:
        if not self.ui_access_manager.is_allowed(Feature.COVER_SHEET):
            return
        if not self.ui_state_manager.get_selected_bid_ref():
            return
        self.handlers.cover_sheet.open_cover_sheet()

    def _should_enable_project_tree_creation(self) -> bool:
        if self._is_summary_tab_active():
            return False
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
        target_project_uid = self._resolve_target_project_uid()
        if file_path is None:
            return
        self._new_project_at(
            file_path,
            target_project_uid,
            require_current_context=True,
        )

    def new_project_at(self, file_path: str, target_project_uid: Optional[str]) -> None:
        self._new_project_at(file_path, target_project_uid)

    def _new_project_at(
        self,
        file_path: str,
        target_project_uid: Optional[str],
        *,
        require_current_context: bool = False,
    ) -> None:
        if not self.ui_access_manager.can_create_bid(file_path, target_project_uid):
            return
        target_identity = self._resolve_project_tree_target_identity(
            file_path, target_project_uid
        )
        if target_identity is None:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            file_path
        )
        defaults = (
            self.project_data.get_settings_defaults_snapshot(file_path)
            if uses_sql_queue
            else self._project_read_service.get_settings_defaults(file_path)
        )
        if uses_sql_queue:
            job_statuses = self.project_data.get_job_status_snapshot(file_path)
            employees = self.project_data.get_employee_snapshot(file_path)
            pay_classes = self.project_data.get_pay_class_snapshot(file_path)
        else:
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
        lease_session = (
            self.handlers.cover_sheet.create_new_bid_lease_session(
                file_path, target_project_uid, data
            )
            if uses_sql_queue
            else None
        )
        dialog = CoverSheetDialog(
            self.icon_provider,
            self.window,
            data,
            has_license=self.ui_access_manager.has_license(),
            save_job_statuses_fn=lambda ch: (
                self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA)
                and self._flush_deferred_for_file(file_path)
                and self._project_write_service.save_job_statuses(file_path, ch)
            ),
            save_job_statuses_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self.handlers.cover_sheet.save_master_data_async(
                            file_path,
                            "Job Statuses",
                            self._project_write_service.queue_job_statuses_save,
                            changes,
                            lease_completed,
                            "job_statuses",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            reload_job_statuses_fn=(
                (lambda: self.project_data.get_job_status_snapshot(file_path))
                if uses_sql_queue
                else (lambda: self._project_read_service.get_job_statuses(file_path))
            ),
            save_employees_fn=lambda ch: (
                self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA)
                and self._flush_deferred_for_file(file_path)
                and self._project_write_service.save_employees_result(file_path, ch)
            ),
            save_pay_classes_fn=lambda ch: (
                self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA)
                and self._flush_deferred_for_file(file_path)
                and self._project_write_service.save_pay_classes(file_path, ch)
            ),
            save_employees_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self.handlers.cover_sheet.save_master_data_async(
                            file_path,
                            "Employees",
                            self._project_write_service.queue_employees_save,
                            changes,
                            lease_completed,
                            "employees",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            save_pay_classes_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self.handlers.cover_sheet.save_master_data_async(
                            file_path,
                            "Payroll Classes",
                            self._project_write_service.queue_pay_classes_save,
                            changes,
                            lease_completed,
                            "pay_classes",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            reload_employees_fn=(
                (
                    lambda: (
                        self.project_data.get_employee_snapshot(file_path),
                        self.project_data.get_pay_class_snapshot(file_path),
                    )
                )
                if uses_sql_queue
                else lambda: self._project_read_service.get_employees_and_pay_classes(
                    file_path
                )
            ),
            save_cover_sheet_async_fn=(
                (
                    lambda updates, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self.handlers.cover_sheet.create_bid_async(
                            file_path,
                            target_project_uid,
                            updates,
                            lambda success: lease_completed(success, None),
                            edit_lease_handle=handle,
                        ),
                        lambda success, _value: completed(success),
                    )
                )
                if uses_sql_queue
                else None
            ),
            pdf_page_sizes_fn=self._infrastructure_provider.get_pdf_page_sizes,
            create_mode=True,
            workspace_state_model=self._workspace_state_model,
        )

        def execute_dialog() -> None:
            try:
                result = exec_with_ost_blocking(dialog, self._event_bus)
                if not isValid(self.window) or not isValid(dialog):
                    return
                if result != QtWidgets.QDialog.DialogCode.Accepted:
                    return
                if uses_sql_queue:
                    return
                if require_current_context and (
                    self._resolve_project_tree_file_path() != file_path
                    or self._resolve_target_project_uid() != target_project_uid
                ):
                    return
                if not self._project_tree_target_identity_is_current(
                    file_path, target_project_uid, target_identity
                ):
                    return
                if not self.ui_access_manager.can_create_bid(
                    file_path, target_project_uid
                ):
                    return
                updates = dialog.get_updates()
                if not self._flush_deferred_for_file(file_path):
                    return
                create_result = self._project_write_service.create_bid_result(
                    file_path, target_project_uid, updates
                )
                if create_result.refresh_failed:
                    show_warning(
                        self.window,
                        "Refresh Error",
                        "The bid was created, but the project tree could not be "
                        "refreshed. Reopen the database to see the created bid.",
                    )
                    return
                if not create_result:
                    show_critical(
                        self.window,
                        "New Project",
                        "Failed to create bid.",
                    )
            finally:
                if lease_session is not None:
                    lease_session.close()
                delete_later_if_valid(dialog)

        if lease_session is None:
            execute_dialog()
            return
        lease_session.bind_dialog(dialog)
        lease_session.request_initial(
            lambda result: (
                execute_dialog() if result.granted else delete_later_if_valid(dialog)
            )
        )

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

    def _resolve_project_tree_target_identity(
        self, file_path: str, project_uid: Optional[str]
    ):
        file_key = normalize_path(file_path)
        for file_entry in self.project_data.get_hierarchy().loaded_files:
            if normalize_path(file_entry.file_path) != file_key:
                continue
            if project_uid is None:
                return file_entry, None
            project = file_entry.bid_projects.get(project_uid)
            if project is not None:
                return file_entry, project
            return None
        return None

    def _project_tree_target_identity_is_current(
        self, file_path: str, project_uid: Optional[str], expected_identity
    ) -> bool:
        current = self._resolve_project_tree_target_identity(file_path, project_uid)
        return bool(
            current is not None
            and current[0] is expected_identity[0]
            and current[1] is expected_identity[1]
        )

    def _new_folder(self) -> None:
        file_path = self._resolve_project_tree_file_path()
        if file_path is None:
            return
        self.new_folder_in(file_path)

    def new_folder_in(self, file_path: str) -> None:
        if not self.ui_access_manager.can_create_project(file_path):
            return
        if not self._flush_deferred_for_file(file_path):
            return
        if self._project_write_service.uses_sql_collaboration_mutations(file_path):
            self.handlers.delete.create_project(
                file_path,
                "New Project",
                lambda new_uid: self.window.project_view.schedule_rename(
                    new_uid, file_path
                ),
            )
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
        self.window.project_view.schedule_rename(new_uid, file_path)

    def _new_database(self) -> None:
        if not self.ui_access_manager.is_allowed(Feature.CREATE_DATABASE):
            return
        type_dialog = NewDatabaseTypeDialog(self.icon_provider, self.window)
        selected_backend = None
        try:
            result = type_dialog.exec()
            if not isValid(self.window) or not isValid(type_dialog):
                return
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                selected_backend = type_dialog.selected_backend()
        finally:
            try:
                type_dialog.cleanup()
            finally:
                delete_later_if_valid(type_dialog)
        if selected_backend is None:
            return
        if selected_backend == DatabaseBackend.SQL_SERVER:
            self.handlers.file_ops.create_sql_database()
            return
        dialog = QtWidgets.QInputDialog(self.window)
        try:
            dialog.setWindowTitle("New Database")
            dialog.setLabelText("Database name:")
            dialog.setTextValue("")
            dialog.setModal(True)
            self.icon_provider.set_window_icon(dialog)
            remove_minimize_maximize(dialog)
            result = dialog.exec()
            if not isValid(self.window) or not isValid(dialog):
                return
            if result != QtWidgets.QDialog.DialogCode.Accepted:
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
                self._event_bus.publish(
                    AppEvents.FILE_OPENED, file_path=result.file_path
                )
        finally:
            delete_later_if_valid(dialog)

    def _show_about_dialog(self) -> None:
        dialog = AboutDialog(self.icon_provider, self.window)
        try:
            dialog.exec()
        finally:
            try:
                if isValid(dialog):
                    dialog.cleanup()
            finally:
                delete_later_if_valid(dialog)

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
            delete_later_if_valid(dialog)

    def _reset_all_settings(self) -> Config:
        default_config = Config()
        self.config_service.update_app_options(default_config)
        self.window.reset_workspace_state_to_defaults()
        return self.config_service.get_config_snapshot()

    def _on_quit(self) -> None:
        self.window.close()

    def cleanup(self) -> None:
        self.icon_provider = None
