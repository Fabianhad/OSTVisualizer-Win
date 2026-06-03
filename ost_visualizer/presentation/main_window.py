import logging
import threading
from types import SimpleNamespace
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal
from ..application.events.app_events import AppEvents
from ..domain.entities.file_state import normalize_path
from .builders.component_builder import ComponentBuilder
from .components.progress_dialog import ProgressDialog, ProgressReporter
from .config import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MAIN_MARGINS,
    MAIN_TOOLBAR_LABEL,
    NO_SPACING,
    SHOW_TOOLBARS_MENU_TITLE,
    SIDEBAR_MIN_WIDTH,
    TAB_INDEX_TAKEOFF,
    PLAN_TOOLS_TOOLBAR_LABEL,
    OVERLAY_TOOLS_TOOLBAR_LABEL,
    VIEW_TOOLBAR_LABEL,
)
from .configurators.window_configurator import WindowConfigurator
from .coordinators.event_coordinator import EventCoordinator
from .coordinators.license_ui_coordinator import LicenseUICoordinator
from .coordinators.ui_event_coordinator import UIEventCoordinator
from .coordinators.workspace_state_coordinator import WorkspaceStateCoordinator
from .dialogs.create_database_dialog import CreateDatabaseDialog
from .dialogs.update_dialog import UpdateDialog
from .handlers.cover_sheet_handler import CoverSheetHandler
from .handlers.export_handler import ExportHandler
from .handlers.file_operation_handler import FileOperationHandler
from .handlers.import_handler import ImportHandler
from .handlers.project_write_handler import ProjectWriteHandler
from .managers.app_config_presentation_manager import AppConfigPresentationManager
from .managers.shortcut_manager import ShortcutManager
from .managers.ui_access_manager import Feature, UIAccessManager
from .managers.ui_state_manager import UIStateManager
from .services.bid_clipboard_service import BidClipboardService
from .services.mcp_context_bridge import McpContextBridge
from .utils.messagebox import show_warning
from .utils.qt_window_icon_provider import QtWindowIconProvider
from .utils.themed_icon import rebuild_all_icons

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    update_dialog_requested = Signal(object)
    MAIN_TOOLBAR_KEY = "main_toolbar"
    VIEW_TOOLBAR_KEY = "view_toolbar"
    PLAN_TOOLS_TOOLBAR_KEY = "plan_tools_toolbar"
    OVERLAY_TOOLS_TOOLBAR_KEY = "overlay_tools_toolbar"
    _MAIN_TOOLBAR_KEY = MAIN_TOOLBAR_KEY
    _VIEW_TOOLBAR_KEY = VIEW_TOOLBAR_KEY
    _PLAN_TOOLS_TOOLBAR_KEY = PLAN_TOOLS_TOOLBAR_KEY
    _OVERLAY_TOOLS_TOOLBAR_KEY = OVERLAY_TOOLS_TOOLBAR_KEY

    def __init__(self, app_controller, splash_screen=None):
        super().__init__()
        self._needs_create_database_prompt = False
        self.splash_screen = splash_screen
        self.app_controller = app_controller
        app_controller.container.register_instance("main_window", self)
        self.event_bus = app_controller.get_service("event_bus")
        self.license_orchestrator = app_controller.get_service("license_orchestrator")
        self._config_model = app_controller.get_service("config_model")
        self._project_data_service = app_controller.get_service("project_data_service")
        self._project_operations_service = app_controller.get_service(
            "project_operations_service"
        )
        self._visualization_service = app_controller.get_service(
            "visualization_service"
        )
        self._color_service = app_controller.get_service("color_service")
        self._container_icon_provider = app_controller.get_service("icon_provider")
        self._project_write_service = app_controller.get_service(
            "project_write_service"
        )
        self._project_read_service = app_controller.get_service("project_read_service")
        self._export_service = app_controller.get_service("export_service")
        self._infrastructure_provider = app_controller.get_service(
            "infrastructure_provider"
        )
        self._coordinate_transformer_factory = app_controller.get_service(
            "coordinate_transformer_factory"
        )
        self._annotation_write_service = app_controller.get_service(
            "annotation_write_service"
        )
        self._annotation_view_manager = app_controller.get_service(
            "annotation_view_manager"
        )
        self._view_window_manager = app_controller.get_service("view_window_manager")
        self._pdf_exporter = app_controller.get_service("pdf_exporter")
        self._ost_exporter = app_controller.get_service("ost_exporter")
        self._osp_exporter = app_controller.get_service("osp_exporter")
        self._mdb_file_parser = app_controller.get_service("mdb_file_parser")
        self._import_service = app_controller.get_service("import_service")
        self._file_loading_service = app_controller.get_service("file_loading_service")
        self._file_state_model = app_controller.get_service("file_state_model")
        self._cleanup_deleted_files_use_case = app_controller.get_service(
            "cleanup_deleted_files_use_case"
        )
        self._working_directory_service = app_controller.get_service(
            "working_directory_service"
        )
        self._config_service = app_controller.get_service("config_service")
        self._workspace_state_model = app_controller.get_service(
            "workspace_state_model"
        )
        self.ui_state_manager = UIStateManager(self._config_model)
        self.ui_access_manager = UIAccessManager(
            event_bus=self.event_bus,
            license_orchestrator=self.license_orchestrator,
            transaction_monitor=app_controller.get_service("transaction_monitor"),
            project_data=self._project_data_service,
            ui_state_manager=self.ui_state_manager,
        )
        self.icon_provider = QtWindowIconProvider()
        self.window_configurator = WindowConfigurator(
            DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT
        )
        self.window_configurator.configure(self)
        self.handlers = self._create_handlers()
        self._bid_clipboard = BidClipboardService()
        component_builder = ComponentBuilder(self)
        components = component_builder.build_components(
            event_bus=self.event_bus,
            color_service=self._color_service,
            coordinate_transformer_factory=self._coordinate_transformer_factory,
            infrastructure_provider=self._infrastructure_provider,
            project_read_service=self._project_read_service,
            project_write_service=self._project_write_service,
            project_data_service=self._project_data_service,
            annotation_write_service=self._annotation_write_service,
            register_hotlink_adapter_fn=lambda adapter: app_controller.container.register_instance(
                "hotlink_event_adapter", adapter
            ),
            ui_state_manager=self.ui_state_manager,
            ui_event_handler=self.handlers.ui_event,
            ui_access_manager=self.ui_access_manager,
        )
        self.tab_widget = components.tab_widget
        self.takeoff_tab = components.takeoff_tab
        self.takeoff_sidebar = components.takeoff_sidebar
        self.opengl_viewer = components.opengl_viewer
        self.plan_view = components.plan_view
        self._view_stack = components.view_stack
        self._plan_tools_toolbar = components.plan_tools_toolbar
        self._overlay_tools_toolbar = components.overlay_tools_toolbar
        self._view_toolbar = components.view_toolbar
        self._main_toolbar = components.main_toolbar
        self._cover_sheet_button = components.cover_sheet_button
        self._view_2d_action = components.view_2d_action
        self._view_3d_action = components.view_3d_action
        self._takeoff_splitter = components.takeoff_splitter
        self._last_takeoff_splitter_sizes = self.get_takeoff_splitter_sizes()
        self._left_splitter = components.left_splitter
        self._last_left_splitter_sizes = self.get_left_splitter_sizes()
        self._layers_toggle_action = components.layers_toggle_action
        self._conditions_toggle_action = components.conditions_toggle_action
        self._annotation_window_action = components.annotation_window_action
        self._view_window_action = components.view_window_action
        self._mesh_window_action = components.mesh_window_action
        self._conditions_sidebar = components.conditions_sidebar
        self._bid_layers_sidebar = components.bid_layers_sidebar
        self._page_settings_bar = components.page_settings_bar
        self._layers_toggle_action.toggled.connect(
            lambda visible: (self._ensure_sidebar_pane_visible(1) if visible else None)
        )
        self._conditions_toggle_action.toggled.connect(
            lambda visible: (self._ensure_sidebar_pane_visible(0) if visible else None)
        )
        self._workspace_toolbar_visibility = {
            self._MAIN_TOOLBAR_KEY: True,
            self._VIEW_TOOLBAR_KEY: True,
            self._PLAN_TOOLS_TOOLBAR_KEY: True,
            self._OVERLAY_TOOLS_TOOLBAR_KEY: True,
        }
        self._syncing_toolbar_visibility = False
        self._main_toolbar.visibilityChanged.connect(
            lambda visible: self._on_workspace_toolbar_visibility_changed(
                self._MAIN_TOOLBAR_KEY, visible
            )
        )
        self._plan_tools_toolbar.visibilityChanged.connect(
            lambda visible: self._on_workspace_toolbar_visibility_changed(
                self._PLAN_TOOLS_TOOLBAR_KEY, visible
            )
        )
        self._overlay_tools_toolbar.visibilityChanged.connect(
            lambda visible: self._on_workspace_toolbar_visibility_changed(
                self._OVERLAY_TOOLS_TOOLBAR_KEY, visible
            )
        )
        self._view_toolbar.visibilityChanged.connect(
            lambda visible: self._on_workspace_toolbar_visibility_changed(
                self._VIEW_TOOLBAR_KEY, visible
            )
        )
        self._annotation_view_manager.set_visibility_changed_callback(
            self._on_annotation_window_visibility_changed
        )
        self._view_window_manager.set_visibility_changed_callback(
            self._on_view_window_visibility_changed
        )
        self._sync_annotation_window_action()
        self._sync_view_window_action()
        self.menu_controller = None
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.handlers.ui_event.set_takeoff_sidebar(self.takeoff_sidebar)
        self.handlers.ui_event.set_opengl_viewer(self.opengl_viewer)
        self.opengl_viewer.elements_deleted.connect(
            components.plan_view_handler.on_elements_deleted
        )
        self.opengl_viewer.assign_to_area_requested.connect(
            components.plan_view_handler.on_assign_to_area
        )
        self.opengl_viewer.reassign_condition_requested.connect(
            components.plan_view_handler.on_reassign_condition
        )
        self.opengl_viewer.set_negative_requested.connect(
            components.plan_view_handler.on_set_negative
        )
        self.opengl_viewer.set_curved_requested.connect(
            components.plan_view_handler.on_set_curved
        )
        self.handlers.ui_event.set_plan_view_handler(components.plan_view_handler)
        self.handlers.ui_event.set_plan_view(self.plan_view)
        self.handlers.ui_event.set_tab_widget(self.tab_widget)
        self.handlers.ui_event.set_view_stack(components.view_stack)
        self.handlers.ui_event.set_bid_clipboard(self._bid_clipboard)
        self.handlers.ui_event.set_copy_action(components.copy_action)
        components.copy_action.triggered.connect(self._copy_selected)
        self.handlers.ui_event.set_cut_action(components.cut_action)
        components.cut_action.triggered.connect(self._cut_selected)
        self.handlers.ui_event.set_paste_action(components.paste_action)
        components.paste_action.triggered.connect(self._paste_clipboard)
        self.handlers.ui_event.set_delete_action(components.delete_action)
        components.delete_action.triggered.connect(self._delete_selected)
        self.handlers.ui_event.set_undo_action(components.undo_action)
        components.undo_action.triggered.connect(
            lambda _checked=False: self.plan_view.undo_requested.emit()
        )
        self.handlers.ui_event.set_redo_action(components.redo_action)
        components.redo_action.triggered.connect(
            lambda _checked=False: self.plan_view.redo_requested.emit()
        )
        self.handlers.ui_event.set_duplicate_action(components.duplicate_action)
        self.handlers.delete.set_duplicate_action(components.duplicate_action)
        components.duplicate_action.triggered.connect(self._duplicate_selected)
        self._select_all_action = QtGui.QAction("Select All", self)
        ShortcutManager.apply_to_action(self._select_all_action, "select_all")
        self._select_all_action.triggered.connect(self._select_all)
        self.handlers.ui_event.set_select_all_action(self._select_all_action)
        self.handlers.ui_event.set_cover_sheet_button(components.cover_sheet_button)
        components.cover_sheet_button.clicked.connect(
            self.handlers.cover_sheet.open_cover_sheet
        )
        self.handlers.ui_event.set_page_settings_bar(components.page_settings_bar)
        self.handlers.ui_event.set_select_action(components.select_action)
        self.handlers.ui_event.set_place_action(components.place_action)
        self.handlers.ui_event.set_dimension_action(components.dimension_action)
        self.handlers.ui_event.set_backout_action(components.backout_action)
        self.handlers.ui_event.set_move_overlay_action(components.move_overlay_action)
        self.handlers.ui_event.set_conditions_sidebar(components.conditions_sidebar)
        self.handlers.ui_event.set_bid_layers_sidebar(components.bid_layers_sidebar)
        self.handlers.ui_event.set_undo_service(components.undo_service)
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(*MAIN_MARGINS)
        container_layout.setSpacing(NO_SPACING)
        container_layout.addWidget(components.central_widget)
        container_layout.addWidget(components.status_panel)
        self.setCentralWidget(container)
        self.status_panel = components.status_panel
        self._status_bar_action = QtGui.QAction("Status Bar", self)
        self._status_bar_action.setCheckable(True)
        self._status_bar_action.setChecked(self.is_status_bar_visible())
        self._status_bar_action.toggled.connect(self.set_status_bar_visible)
        self.handlers.ui_event.set_status_panel(self.status_panel)
        self._plan_view_handler = components.plan_view_handler
        self.project_view = components.project_view
        self.project_view.on_restore_bid = self.handlers.delete.restore_bids
        self.project_view.set_on_move_bids(self.handlers.delete.move_bids)
        self.project_view.on_copy_bids = self._copy_project_bids
        self.project_view.on_paste_bids = self._paste_project_bids
        self.project_view.on_can_paste_bids = self._can_paste_project_bids
        self.project_view.on_empty_deleted_bids = self.handlers.delete.delete_bids
        self.project_view.on_multi_selection = self._on_project_multi_selection
        self.project_view.on_rename_project = self.handlers.delete.rename_project
        self.project_view.on_menu_command = self._trigger_project_tree_menu_command
        self.project_view.on_menu_command_enabled = (
            self._is_project_tree_menu_command_enabled
        )
        self.project_view.on_export_formats = self._project_tree_export_formats
        self.project_view.on_get_job_statuses = self._get_project_tree_job_statuses
        self.project_view.on_update_bid_job_status = (
            self._update_project_tree_bid_job_status
        )
        self.project_view.on_renumber_conditions = (
            self.handlers.ui_event.renumber_conditions
        )
        self.project_view.on_can_renumber_conditions = (
            self.handlers.ui_event.can_renumber_conditions
        )
        self.project_view.on_project_view_options_changed = (
            self._request_workspace_state_save
        )
        self.project_view.set_ui_access_manager(self.ui_access_manager)
        self._visualization_service.set_message_parent(self)
        self.menu_controller = component_builder.create_menu(
            config_service=self._config_service,
            ui_state_manager=self.ui_state_manager,
            handlers=self.handlers,
            ui_access_manager=self.ui_access_manager,
            project_data_service=self._project_data_service,
            export_service=self._export_service,
            project_read_service=self._project_read_service,
            project_write_service=self._project_write_service,
            infrastructure_provider=self._infrastructure_provider,
            event_bus=self.event_bus,
            file_loading_service=self._file_loading_service,
            create_new_database_fn=self.app_controller.create_new_database,
            shared_actions={
                "new_project": components.new_project_action,
                "new_folder": components.new_folder_action,
                "new_database": components.new_database_action,
                "open_files": components.open_files_action,
                "undo": components.undo_action,
                "redo": components.redo_action,
                "cut": components.cut_action,
                "copy": components.copy_action,
                "paste": components.paste_action,
                "duplicate": components.duplicate_action,
                "delete": components.delete_action,
                "select_all": self._select_all_action,
                "zoom_in": components.zoom_in_action,
                "zoom_out": components.zoom_out_action,
                "reset_view": components.reset_view_action,
                "next_page": components.next_page_action,
                "previous_page": components.previous_page_action,
                "select_tool": components.select_action,
                "place_tool": components.place_action,
                "zoom_tool": components.zoom_mode_action,
                "pan_tool": components.pan_action,
                "dimension_tool": components.dimension_action,
                "backout_mode": components.backout_action,
                "layers_sidebar": components.layers_toggle_action,
                "conditions_sidebar": components.conditions_toggle_action,
                "status_bar": self._status_bar_action,
                "annotation_window": components.annotation_window_action,
            },
        )

        def connect_menu_command(action: QtGui.QAction, command_key: str) -> None:
            action.triggered.connect(
                lambda _checked=False, key=command_key: (
                    self.menu_controller.trigger_menu_callback(key)
                )
            )

        connect_menu_command(components.new_project_action, "new_project")
        connect_menu_command(components.new_folder_action, "new_folder")
        connect_menu_command(components.new_database_action, "new_database")
        connect_menu_command(components.open_files_action, "open_files")
        self.plan_view.set_context_menu_command_handlers(
            self.menu_controller.trigger_menu_action,
            self.menu_controller.get_menu_action_state,
        )
        self.apply_config_preferences()
        self.opengl_viewer.set_context_menu_command_handlers(
            self.menu_controller.trigger_menu_action,
            self.menu_controller.get_menu_action_state,
        )
        self.license_coordinator = LicenseUICoordinator(
            window=self,
            icon_provider=self.icon_provider,
            license_orchestrator=self.license_orchestrator,
            event_bus=self.event_bus,
            status_panel=self.status_panel,
            menu_controller=self.menu_controller,
        )
        self.event_coordinator = EventCoordinator(self.event_bus)
        self.event_coordinator.register_many(
            {
                AppEvents.LICENSE_STATUS_CHANGED: self.license_coordinator.on_license_status_changed,
            }
        )
        self.license_coordinator.initialize()
        self._workspace_state_coordinator = WorkspaceStateCoordinator(
            main_window=self,
            workspace_state_model=self._workspace_state_model,
        )
        self._workspace_state_coordinator.restore_initial_state()
        self._mcp_context_bridge = McpContextBridge(
            main_window=self,
            ui_state_manager=self.ui_state_manager,
            project_data_service=self._project_data_service,
            plan_view=self.plan_view,
            parent=self,
        )
        self._mcp_context_bridge.start()
        self.update_dialog_requested.connect(self._show_update_dialog)
        self._update_service = self._resolve_update_service()
        QtCore.QTimer.singleShot(0, self._load_files_from_config)
        QtCore.QTimer.singleShot(0, self._show_main_window)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self.splash_screen:
            self.splash_screen.finish(self)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            rebuild_all_icons()

    def _show_main_window(self) -> None:
        self._workspace_state_coordinator.show_main_window()
        self.raise_()
        self.activateWindow()
        if self._update_service:
            QtCore.QTimer.singleShot(0, self._check_for_updates)
        if self._needs_create_database_prompt:
            self._needs_create_database_prompt = False
            QtCore.QTimer.singleShot(0, self._prompt_create_database)

    def _create_handlers(self) -> SimpleNamespace:
        handlers = SimpleNamespace()
        handlers.file_ops = FileOperationHandler(
            window=self,
            icon_provider=self.icon_provider,
            event_bus=self.event_bus,
            file_state_model=self._file_state_model,
            cleanup_deleted_files_use_case=self._cleanup_deleted_files_use_case,
            file_loading_service=self._file_loading_service,
            working_directory_service=self._working_directory_service,
            unload_file_fn=self.app_controller.unload_file,
            ui_state_manager=self.ui_state_manager,
        )
        handlers.export = ExportHandler(
            window=self,
            config_model=self._config_model,
            export_service=self._export_service,
            project_data_service=self._project_data_service,
            pdf_exporter=self._pdf_exporter,
            ost_exporter=self._ost_exporter,
            osp_exporter=self._osp_exporter,
            mdb_file_parser=self._mdb_file_parser,
        )
        handlers.import_ = ImportHandler(
            window=self,
            project_data_service=self._project_data_service,
            import_service=self._import_service,
            ui_state_manager=self.ui_state_manager,
        )
        handlers.delete = ProjectWriteHandler(
            window=self,
            project_data_service=self._project_data_service,
            project_write_service=self._project_write_service,
            ui_state_manager=self.ui_state_manager,
        )
        handlers.cover_sheet = CoverSheetHandler(
            window=self,
            icon_provider=self.icon_provider,
            project_data_service=self._project_data_service,
            project_read_service=self._project_read_service,
            project_write_service=self._project_write_service,
            infrastructure_provider=self._infrastructure_provider,
            event_bus=self.event_bus,
            ui_state_manager=self.ui_state_manager,
            ui_access_manager=self.ui_access_manager,
        )
        handlers.ui_event = UIEventCoordinator(
            main_window=self,
            ui_state_manager=self.ui_state_manager,
            ui_access_manager=self.ui_access_manager,
            event_bus=self.event_bus,
            project_data_service=self._project_data_service,
            project_operations_service=self._project_operations_service,
            visualization_service=self._visualization_service,
            color_service=self._color_service,
            icon_provider=self._container_icon_provider,
            project_write_service=self._project_write_service,
            project_read_service=self._project_read_service,
        )
        return handlers

    def _load_files_from_config(self) -> None:
        loaded_files = self.app_controller.load_files_from_config()
        if loaded_files:
            self.handlers.ui_event.sync_after_startup_load()
            self._sync_database_monitoring()
        elif not self.app_controller.has_any_databases():
            self._needs_create_database_prompt = True
        QtCore.QTimer.singleShot(
            0, self._workspace_state_coordinator.restore_deferred_state
        )

    def _prompt_create_database(self) -> None:
        if not self.ui_access_manager.is_allowed(Feature.CREATE_DATABASE):
            return
        dialog = CreateDatabaseDialog(self.icon_provider, self)
        try:
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
        finally:
            dialog.deleteLater()
        db_path = self._create_database_with_progress()
        if not db_path:
            show_warning(
                self,
                "Error",
                "Failed to create database. Check logs for details.",
            )
            return
        result = self._file_loading_service.load_file(db_path)
        if result.success:
            self.event_bus.publish(
                AppEvents.FILE_OPENED,
                file_path=result.file_path,
            )

    def _create_database_with_progress(self) -> str | None:
        reporter = ProgressReporter()
        progress = ProgressDialog(
            "new database",
            lambda: self.app_controller.create_new_database(
                progress_callback=reporter.report
            ),
            parent=self,
            reporter=reporter,
            action_text="Creating database",
        )
        try:
            rc = progress.exec()
            result = progress.result
            worker_error = progress.error
        finally:
            progress.cleanup()
            progress.deleteLater()
        if rc == QtWidgets.QDialog.DialogCode.Accepted and result:
            return result
        if worker_error is not None:
            logger.error(
                "Create database worker raised: %s",
                worker_error,
                exc_info=True,
            )
        return None

    def _sync_database_monitoring(self) -> None:
        if self._project_data_service.has_loaded_files():
            self._visualization_service.start_database_monitoring()
        else:
            self._visualization_service.stop_database_monitoring()

    def _resolve_update_service(self):
        try:
            return self.app_controller.get_service("update_check_service")
        except KeyError:
            return None

    def _check_for_updates(self) -> None:
        if not self._update_service:
            return

        def check_updates():
            try:
                update_available, version_info = (
                    self._update_service.check_for_updates()
                )
                if update_available and version_info:
                    self.update_dialog_requested.emit(version_info)
            except Exception as exc:
                logger.exception("Error checking for updates: %s", exc)

        threading.Thread(target=check_updates, daemon=True).start()

    def _show_update_dialog(self, version_info) -> None:
        self._visualization_service.set_update_dialog_active(True)
        dialog = UpdateDialog(self.icon_provider, self, version_info)
        try:
            dialog.show_dialog()
        finally:
            dialog.deleteLater()
        self._visualization_service.set_update_dialog_active(False)

    def show_license_dialog(self) -> None:
        self.license_coordinator.show_dialog()

    def _delete_selected(self) -> None:
        if self._handle_inline_text_shortcut("delete"):
            return
        if self.tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
                return
            self.plan_view.delete_selected()
        else:
            if not self.ui_access_manager.is_allowed(Feature.DELETE_BID):
                return
            self.handlers.delete.delete_selected()

    def _duplicate_selected(self) -> None:
        if self.tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
                return
            self.plan_view.duplicate_selected()
        else:
            if not self.ui_access_manager.is_allowed(Feature.DUPLICATE_BID):
                return
            self.handlers.delete.duplicate_selected()

    def _copy_selected(self) -> None:
        if self._handle_inline_text_shortcut("copy"):
            return
        if self.tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
                return
            self.plan_view.copy_selected()
            return
        if not self.ui_access_manager.is_allowed(Feature.DUPLICATE_BID):
            return
        bid_refs = self.ui_state_manager.get_selected_bid_refs()
        if not self._same_file_bid_refs(bid_refs):
            return
        self._bid_clipboard.copy(bid_refs)
        self.handlers.ui_event.refresh_toolbar()

    def _cut_selected(self) -> None:
        if self._handle_inline_text_shortcut("cut"):
            return
        if self.tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            return
        if not self.ui_access_manager.is_allowed(Feature.DELETE_BID):
            return
        bid_refs = self.ui_state_manager.get_selected_bid_refs()
        if not self._same_file_bid_refs(bid_refs):
            return
        self._bid_clipboard.cut(bid_refs)
        self.handlers.ui_event.refresh_toolbar()

    def _paste_clipboard(self) -> None:
        if self._handle_inline_text_shortcut("paste"):
            return
        if self.tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
                return
            if not self._plan_view_handler.can_paste_to_current_bid():
                return
            self.plan_view.paste_clipboard()
            return
        target = self._get_bid_paste_target()
        if target is None:
            return
        file_path, target_project_uid = target
        self._paste_project_bids(file_path, target_project_uid)

    def _copy_project_bids(self, bid_refs) -> None:
        if not self._same_file_bid_refs(bid_refs):
            return
        self._bid_clipboard.copy(bid_refs)
        self.handlers.ui_event.refresh_toolbar()

    def _paste_project_bids(
        self, file_path: str, target_project_uid: str | None
    ) -> None:
        if not self._can_paste_project_bids(file_path, target_project_uid):
            return
        is_cut = self._bid_clipboard.is_cut
        success = self.handlers.delete.paste_bids(
            self._bid_clipboard.bid_refs, target_project_uid, is_cut=is_cut
        )
        if success and is_cut:
            self._bid_clipboard.clear()
        self.handlers.ui_event.refresh_toolbar()

    def _can_paste_project_bids(
        self, file_path: str, target_project_uid: str | None
    ) -> bool:
        if target_project_uid == "1":
            return False
        if not self._bid_clipboard.has_content():
            return False
        if not self._bid_clipboard.source_matches_file(file_path):
            return False
        feature = (
            Feature.DELETE_BID if self._bid_clipboard.is_cut else Feature.DUPLICATE_BID
        )
        return self.ui_access_manager.is_project_bid_clipboard_allowed(feature)

    def _select_all(self) -> None:
        if self.tab_widget.currentIndex() != TAB_INDEX_TAKEOFF:
            return
        if self._handle_inline_text_shortcut("select_all"):
            return
        if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        self.plan_view.select_all()
        self.handlers.ui_event.refresh_toolbar()

    def _handle_inline_text_shortcut(self, action_key: str) -> bool:
        if self.tab_widget.currentIndex() != TAB_INDEX_TAKEOFF:
            return False
        return bool(
            self.plan_view
            and self.plan_view.is_text_annotation_inline_edit_active()
            and self.plan_view.handle_inline_text_shortcut(action_key)
        )

    def _same_file_bid_refs(self, bid_refs) -> bool:
        return BidClipboardService.refs_share_database(bid_refs)

    def _get_bid_paste_target(self):
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref:
            target_project_uid = self._project_data_service.find_project_uid_for_bid(
                bid_ref
            )
            if target_project_uid == "1":
                return None
            return (
                bid_ref.file_path,
                target_project_uid,
            )
        project_uid = self.ui_state_manager.selected_project_uid
        if project_uid == "1":
            return None
        file_path = self.ui_state_manager.selected_file_path
        if not file_path:
            return None
        return file_path, project_uid

    def _on_project_multi_selection(self, bid_refs, project_uids) -> None:
        self.ui_state_manager.set_bid_multi_selection(bid_refs)
        self.ui_state_manager.set_project_multi_selection(project_uids)
        self.handlers.ui_event.refresh_toolbar()

    def _trigger_project_tree_menu_command(self, command_key: str) -> None:
        if self.menu_controller:
            self.menu_controller.trigger_menu_action(command_key)

    def _is_project_tree_menu_command_enabled(self, command_key: str) -> bool:
        if not self.menu_controller:
            return False
        return self.menu_controller.is_context_command_enabled(command_key)

    def _project_tree_export_formats(self) -> list[str]:
        if not self.menu_controller:
            return []
        return self.menu_controller.get_export_formats()

    def _get_project_tree_job_statuses(self, file_path: str) -> list:
        return self._project_read_service.get_job_statuses(file_path)

    def _update_project_tree_bid_job_status(self, bid_ref, job_status_uid: str) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_BID_JOB_STATUS):
            return
        self.handlers.delete.update_bid_job_status(bid_ref, job_status_uid)

    def _on_tab_changed(self, index: int) -> None:
        self._apply_workspace_toolbar_visibility()
        if index != TAB_INDEX_TAKEOFF:
            if self._view_window_manager.is_view_open():
                self._workspace_state_coordinator.request_view_restore()
                self.set_view_window_visible(False)
            if self._annotation_view_manager.is_view_open():
                self._workspace_state_coordinator.request_annotation_restore()
                self.set_annotation_window_visible(False)
            if self.get_mesh_window() is not None:
                self._workspace_state_coordinator.request_mesh_restore()
                self.set_mesh_window_visible(False)
        self._workspace_state_coordinator.on_main_tab_changed()
        if self.menu_controller:
            self.menu_controller.update_menu_states()

    def sync_contextual_shell_visibility(self) -> None:
        self._on_tab_changed(self.tab_widget.currentIndex())

    def notify_takeoff_workspace_activated(self) -> None:
        self._workspace_state_coordinator.on_takeoff_workspace_activated()

    def get_workspace_toolbar_visibility_state(self) -> dict[str, bool]:
        return dict(self._workspace_toolbar_visibility)

    def set_workspace_toolbar_visibility_state(self, state: dict[str, bool]) -> None:
        for key in self._workspace_toolbar_visibility:
            if key in state:
                self._workspace_toolbar_visibility[key] = bool(state[key])
        self._apply_workspace_toolbar_visibility()

    def set_workspace_toolbar_preference(self, key: str, visible: bool) -> None:
        self._set_workspace_toolbar_preference(key, visible)

    def _set_workspace_toolbar_preference(self, key: str, visible: bool) -> None:
        self._workspace_toolbar_visibility[key] = bool(visible)
        self._apply_workspace_toolbar_visibility()
        self._workspace_state_coordinator.request_save()

    def _set_toolbar_visible(
        self, toolbar: QtWidgets.QToolBar, key: str, available: bool
    ) -> None:
        visible = available and self._workspace_toolbar_visibility[key]
        toolbar.setVisible(visible)

    def _apply_workspace_toolbar_visibility(self) -> None:
        self._syncing_toolbar_visibility = True
        try:
            takeoff_active = self.is_takeoff_tab_active()
            self._set_toolbar_visible(self._main_toolbar, self._MAIN_TOOLBAR_KEY, True)
            self._set_toolbar_visible(
                self._plan_tools_toolbar,
                self._PLAN_TOOLS_TOOLBAR_KEY,
                takeoff_active,
            )
            self._set_toolbar_visible(
                self._overlay_tools_toolbar,
                self._OVERLAY_TOOLS_TOOLBAR_KEY,
                takeoff_active,
            )
            self._set_toolbar_visible(
                self._view_toolbar,
                self._VIEW_TOOLBAR_KEY,
                takeoff_active,
            )
        finally:
            self._syncing_toolbar_visibility = False

    def apply_config_preferences(self) -> None:
        AppConfigPresentationManager().apply(self, self._config_model)

    def apply_toolbar_text_preference(self) -> None:
        AppConfigPresentationManager().apply_toolbar_text(self, self._config_model)

    def _on_workspace_toolbar_visibility_changed(self, key: str, visible: bool) -> None:
        if self._syncing_toolbar_visibility:
            return
        self._workspace_toolbar_visibility[key] = bool(visible)

    def createPopupMenu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        menu.setTitle(SHOW_TOOLBARS_MENU_TITLE)
        toolbar_entries = (
            (
                self._MAIN_TOOLBAR_KEY,
                MAIN_TOOLBAR_LABEL,
            ),
            (
                self._VIEW_TOOLBAR_KEY,
                VIEW_TOOLBAR_LABEL,
            ),
            (
                self._PLAN_TOOLS_TOOLBAR_KEY,
                PLAN_TOOLS_TOOLBAR_LABEL,
            ),
            (
                self._OVERLAY_TOOLS_TOOLBAR_KEY,
                OVERLAY_TOOLS_TOOLBAR_LABEL,
            ),
        )
        for key, label in toolbar_entries:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._workspace_toolbar_visibility[key])
            action.setEnabled(
                key == self._MAIN_TOOLBAR_KEY or self.is_takeoff_tab_active()
            )
            action.toggled.connect(
                lambda checked, toolbar_key=key: self._set_workspace_toolbar_preference(
                    toolbar_key, checked
                )
            )
        return menu

    def get_workspace_toolbars(self) -> list[QtWidgets.QToolBar]:
        return [
            self._main_toolbar,
            self._plan_tools_toolbar,
            self._overlay_tools_toolbar,
            self._view_toolbar,
        ]

    def get_toolbar_text_buttons(self) -> list[QtWidgets.QToolButton]:
        return [self._cover_sheet_button]

    def get_view_stack(self):
        return self._view_stack

    def get_left_splitter(self) -> QtWidgets.QSplitter:
        return self._left_splitter

    def get_project_header(self) -> QtWidgets.QHeaderView:
        return self.project_view.header()

    def get_conditions_header(self) -> QtWidgets.QHeaderView:
        return self._conditions_sidebar.header()

    def get_layers_header(self) -> QtWidgets.QHeaderView:
        return self._bid_layers_sidebar.header()

    def get_project_tree(self) -> QtWidgets.QTreeWidget:
        return self.project_view.top_tree

    def get_takeoff_splitter(self) -> QtWidgets.QSplitter:
        return self._takeoff_splitter

    def get_layers_toggle_action(self) -> QtGui.QAction:
        return self._layers_toggle_action

    def get_conditions_toggle_action(self) -> QtGui.QAction:
        return self._conditions_toggle_action

    def get_mesh_window_action(self) -> QtGui.QAction:
        return self._mesh_window_action

    def get_annotation_window_action(self) -> QtGui.QAction:
        return self._annotation_window_action

    def get_view_window_action(self) -> QtGui.QAction:
        return self._view_window_action

    def get_status_bar_action(self) -> QtGui.QAction:
        return self._status_bar_action

    def is_takeoff_tab_active(self) -> bool:
        return self.tab_widget.currentIndex() == TAB_INDEX_TAKEOFF

    def get_takeoff_plan_view(self):
        return self.plan_view

    def get_page_settings_bar(self):
        return self._page_settings_bar

    def get_active_takeoff_view(self) -> str:
        return "2d" if self._view_stack.currentIndex() == 1 else "3d"

    def can_go_previous_takeoff_page(self) -> bool:
        return self._can_go_takeoff_page(-1)

    def can_go_next_takeoff_page(self) -> bool:
        if self._can_go_takeoff_page(1):
            return True
        return (
            self._is_on_last_takeoff_page()
            and self.can_add_page_from_takeoff_tab()
            and self.is_takeoff_tab_active()
        )

    def can_add_page_from_takeoff_tab(self) -> bool:
        return (
            self._config_model.allow_add_page_from_takeoff_tab
            and self.ui_access_manager.is_allowed(Feature.COVER_SHEET)
            and not self._project_data_service.is_current_bid_locked()
            and bool(self.ui_state_manager.get_selected_bid_ref())
        )

    def _is_on_last_takeoff_page(self) -> bool:
        order = self.takeoff_sidebar.get_page_order()
        page_uid = self.takeoff_sidebar.get_active_page_uid()
        return (
            bool(order)
            and page_uid in order
            and order.index(page_uid) == len(order) - 1
        )

    def _can_go_takeoff_page(self, direction: int) -> bool:
        order = self.takeoff_sidebar.get_page_order()
        page_uid = self.takeoff_sidebar.get_active_page_uid()
        if page_uid not in order:
            return False
        target = order.index(page_uid) + direction
        return 0 <= target < len(order)

    def go_next_takeoff_page(self) -> None:
        if self._can_go_takeoff_page(1):
            self.takeoff_sidebar.go_next()
            return
        if not self.can_go_next_takeoff_page():
            return
        if self.handlers.cover_sheet.add_blank_page_from_takeoff_tab():
            order = self.takeoff_sidebar.get_page_order()
            if order:
                self.handlers.ui_event.navigate_to_takeoff_page(order[-1])

    def set_active_takeoff_view(self, active_view: str) -> None:
        index = 1 if str(active_view).lower() == "2d" else 0
        if self._view_stack.currentIndex() != index:
            self._view_stack.setCurrentIndex(index)

    def navigate_to_hotlink_page(self, page_uid: str, named_view_uid: str = "") -> None:
        self.handlers.ui_event.navigate_to_takeoff_page(page_uid, named_view_uid)
        self.set_active_takeoff_view("2d")
        self.handlers.ui_event.apply_pending_hotlink_view_focus()

    def is_takeoff_2d_tab_visible(self) -> bool:
        return self._view_2d_action.isVisible()

    def is_takeoff_3d_tab_visible(self) -> bool:
        return self._view_3d_action.isVisible()

    def set_takeoff_2d_tab_visible(self, visible: bool) -> None:
        self._set_takeoff_view_action_visible(self._view_2d_action, 1, bool(visible))
        self._request_workspace_state_save()

    def set_takeoff_3d_tab_visible(self, visible: bool) -> None:
        self._set_takeoff_view_action_visible(self._view_3d_action, 0, bool(visible))
        self._request_workspace_state_save()

    def _request_workspace_state_save(self) -> None:
        self._workspace_state_coordinator.request_save()

    def reset_workspace_state_to_defaults(self) -> None:
        self._workspace_state_coordinator.reset_to_defaults()

    def _set_takeoff_view_action_visible(
        self, action: QtGui.QAction, index: int, visible: bool
    ) -> None:
        other_action = self._view_3d_action if index == 1 else self._view_2d_action
        if not visible and not other_action.isVisible():
            visible = True
        action.setVisible(visible)
        if not visible and self._view_stack.currentIndex() == index:
            other_index = 0 if index == 1 else 1
            self._view_stack.setCurrentIndex(other_index)

    def _sync_left_splitter_visibility(self) -> None:
        self._left_splitter.setVisible(
            not self._conditions_sidebar.isHidden()
            or not self._bid_layers_sidebar.isHidden()
        )

    def is_layers_sidebar_visible(self) -> bool:
        return not self._bid_layers_sidebar.isHidden()

    def set_layers_sidebar_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self._layers_toggle_action.isChecked() != visible:
            self._layers_toggle_action.setChecked(visible)
            return
        self._bid_layers_sidebar.setVisible(visible)
        self._sync_left_splitter_visibility()
        if visible:
            self._ensure_sidebar_pane_visible(1)

    def is_conditions_sidebar_visible(self) -> bool:
        return not self._conditions_sidebar.isHidden()

    def set_conditions_sidebar_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self._conditions_toggle_action.isChecked() != visible:
            self._conditions_toggle_action.setChecked(visible)
            return
        self._conditions_sidebar.setVisible(visible)
        self._sync_left_splitter_visibility()
        if visible:
            self._ensure_sidebar_pane_visible(0)

    def is_status_bar_visible(self) -> bool:
        return not self.status_panel.isHidden()

    def set_status_bar_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self._status_bar_action.isChecked() != visible:
            self._status_bar_action.blockSignals(True)
            self._status_bar_action.setChecked(visible)
            self._status_bar_action.blockSignals(False)
        self.status_panel.setVisible(visible)

    def get_takeoff_splitter_sizes(self) -> list[int]:
        sizes = [max(0, int(size)) for size in self._takeoff_splitter.sizes()]
        if sizes[0] > 0:
            self._last_takeoff_splitter_sizes = sizes
        return sizes

    def set_takeoff_splitter_sizes(self, sizes: list[int]) -> None:
        if not sizes:
            return
        cleaned = [max(0, int(size)) for size in sizes]
        if sum(cleaned) <= 0:
            return
        self._last_takeoff_splitter_sizes = cleaned
        self._takeoff_splitter.setSizes(cleaned)

    def get_left_splitter_sizes(self) -> list[int]:
        sizes = [max(0, int(size)) for size in self._left_splitter.sizes()]
        if len(sizes) >= 2 and sizes[0] > 0 and sizes[1] > 0:
            self._last_left_splitter_sizes = sizes
        return sizes

    def set_left_splitter_sizes(self, sizes: list[int]) -> None:
        if not sizes:
            return
        cleaned = [max(0, int(size)) for size in sizes]
        if sum(cleaned) <= 0:
            return
        self._last_left_splitter_sizes = cleaned
        self._left_splitter.setSizes(cleaned)

    def get_takeoff_dropdown_popup_sizes(self) -> dict[str, list[int]]:
        sizes = {"main_page": self.takeoff_sidebar.get_popup_size()}
        sizes.update(self._page_settings_bar.get_dropdown_popup_sizes())
        for window in (self.get_annotation_window(), self.get_view_window()):
            if window is not None:
                sizes.update(window.get_dropdown_popup_sizes())
        return sizes

    def set_takeoff_dropdown_popup_sizes(self, sizes: dict[str, list[int]]) -> None:
        self.takeoff_sidebar.set_popup_size(sizes.get("main_page", []))
        self._page_settings_bar.set_dropdown_popup_sizes(sizes)
        for window in (self.get_annotation_window(), self.get_view_window()):
            if window is not None:
                window.set_dropdown_popup_sizes(sizes)

    def save_project_header_state(self) -> QtCore.QByteArray:
        return self.project_view.save_header_state()

    def restore_project_header_state(self, state: QtCore.QByteArray) -> None:
        self.project_view.restore_header_state(state)

    def get_project_expanded_node_keys(self) -> list[str]:
        return self.project_view.get_expanded_node_keys()

    def set_project_expanded_node_keys(self, keys: list[str] | None) -> None:
        self.project_view.set_expanded_node_keys(keys)

    def is_project_group_by_job_status(self) -> bool:
        return self.project_view.is_group_by_job_status()

    def set_project_group_by_job_status(self, enabled: bool) -> None:
        self.project_view.set_group_by_job_status(enabled, notify=False)

    def get_project_selected_node(self) -> dict | None:
        return self.project_view.get_selected_node_state()

    def get_selected_database_context_file_path(self) -> str | None:
        selected_node = self.project_view.get_selected_node_state()
        if not selected_node:
            return None
        file_path = selected_node.get("file_path")
        if not file_path:
            return None
        selected_path = normalize_path(file_path)
        for loaded_file in self._project_data_service.get_hierarchy().loaded_files:
            if normalize_path(loaded_file.file_path) == selected_path:
                return file_path
        return None

    def set_project_selected_node(self, node: dict | None) -> None:
        self.project_view.set_selected_node_state(node)

    def get_conditions_sidebar(self):
        return self._conditions_sidebar

    def save_conditions_header_state(self) -> QtCore.QByteArray:
        return self._conditions_sidebar.save_header_state()

    def restore_conditions_header_state(self, state: QtCore.QByteArray) -> None:
        self._conditions_sidebar.restore_header_state(state)

    def is_conditions_group_by_type_enabled(self) -> bool:
        return self._conditions_sidebar.is_group_by_type_enabled()

    def set_conditions_group_by_type(self, enabled: bool) -> None:
        self._conditions_sidebar.set_group_by_type(enabled, notify=False)

    def save_layers_header_state(self) -> QtCore.QByteArray:
        return self._bid_layers_sidebar.save_header_state()

    def restore_layers_header_state(self, state: QtCore.QByteArray) -> None:
        self._bid_layers_sidebar.restore_header_state(state)

    def _ensure_left_splitter_pane_visible(self, index: int) -> None:
        sizes = self.get_left_splitter_sizes()
        if sizes[index] > 0:
            return
        total = max(sum(sizes), self._left_splitter.height(), 2)
        saved_size = (
            self._last_left_splitter_sizes[index]
            if index < len(self._last_left_splitter_sizes)
            else 0
        )
        restored = max(1, saved_size, total // 2)
        restored = min(restored, max(1, total - 1))
        sizes[index] = restored
        other_index = 1 - index
        sizes[other_index] = max(1, total - restored)
        self._left_splitter.setSizes(sizes)

    def _ensure_sidebar_column_visible(self) -> None:
        sizes = self.get_takeoff_splitter_sizes()
        if sizes[0] > 0:
            return
        total = max(sum(sizes), self._takeoff_splitter.width(), 2)
        saved_sidebar_width = self._last_takeoff_splitter_sizes[0]
        restored = max(SIDEBAR_MIN_WIDTH, saved_sidebar_width, total // 4)
        restored = min(restored, max(1, total - 1))
        sizes[0] = restored
        sizes[1] = max(1, total - restored)
        self._takeoff_splitter.setSizes(sizes)

    def _ensure_sidebar_pane_visible(self, index: int) -> None:
        self._ensure_sidebar_column_visible()
        self._ensure_left_splitter_pane_visible(index)

    def get_active_takeoff_page_uid(self) -> str | None:
        page_uid = self.ui_state_manager.active_page_uid
        if not page_uid and self.plan_view:
            page_uid = self.plan_view.current_page_uid
        if not page_uid:
            return None
        if not self._project_data_service.get_page(page_uid):
            return None
        return page_uid

    def can_open_annotation_window(self) -> bool:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        return bool(bid_ref and self.get_active_takeoff_page_uid())

    def can_restore_annotation_window(self) -> bool:
        return self.is_takeoff_tab_active() and self.can_open_annotation_window()

    def can_open_view_window(self) -> bool:
        return self.is_annotation_window_open() and self.can_open_annotation_window()

    def can_restore_view_window(self) -> bool:
        return self.is_takeoff_tab_active() and self.can_open_view_window()

    def get_annotation_window(self):
        return self._annotation_view_manager.get_window()

    def is_annotation_window_open(self) -> bool:
        return self._annotation_view_manager.is_view_open()

    def set_annotation_window_visible(
        self,
        visible: bool,
        *,
        initial_geometry: QtCore.QByteArray | None = None,
        initial_is_maximized: bool = True,
    ) -> None:
        visible = bool(visible)
        if visible and not self.can_restore_annotation_window():
            self._annotation_window_action.blockSignals(True)
            self._annotation_window_action.setChecked(False)
            self._annotation_window_action.blockSignals(False)
            return
        if visible:
            initial_geometry, initial_is_maximized = (
                self._resolve_detached_initial_state(
                    self._workspace_state_model.state.detached_windows.annotation_view,
                    initial_geometry,
                    initial_is_maximized,
                )
            )
        action = self._annotation_window_action
        if action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        if visible:
            if self.is_annotation_window_open():
                return
            bid_ref = self.ui_state_manager.get_selected_bid_ref()
            page_uid = self.get_active_takeoff_page_uid()
            self._annotation_view_manager.set_ui_access_manager(self.ui_access_manager)
            self._annotation_view_manager.open_view(
                bid_ref,
                page_uid,
                None,
                initial_geometry=initial_geometry,
                initial_is_maximized=initial_is_maximized,
            )
            return
        if self.is_view_window_open():
            self.set_view_window_visible(False)
        self._annotation_view_manager.close_view()

    def get_view_window(self):
        return self._view_window_manager.get_window()

    def is_view_window_open(self) -> bool:
        return self._view_window_manager.is_view_open()

    def set_view_window_visible(
        self,
        visible: bool,
        *,
        initial_geometry: QtCore.QByteArray | None = None,
        initial_is_maximized: bool = True,
    ) -> None:
        visible = bool(visible)
        if visible and not self.can_restore_view_window():
            self._view_window_action.blockSignals(True)
            self._view_window_action.setChecked(False)
            self._view_window_action.blockSignals(False)
            return
        if visible:
            initial_geometry, initial_is_maximized = (
                self._resolve_detached_initial_state(
                    self._workspace_state_model.state.detached_windows.view_window,
                    initial_geometry,
                    initial_is_maximized,
                )
            )
        action = self._view_window_action
        if action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        if visible:
            if self.is_view_window_open():
                return
            annotation_view = self._annotation_view_manager.get_active_view()
            bid_ref = (
                annotation_view.bid_ref
                if annotation_view and annotation_view.bid_ref
                else self.ui_state_manager.get_selected_bid_ref()
            )
            page_uid = (
                annotation_view.target_page_uid
                if annotation_view
                else self.get_active_takeoff_page_uid()
            )
            named_view_uid = (
                annotation_view.target_named_view_uid if annotation_view else None
            )
            self._view_window_manager.set_ui_access_manager(self.ui_access_manager)
            self._view_window_manager.open_view(
                bid_ref,
                page_uid,
                named_view_uid,
                initial_geometry=initial_geometry,
                initial_is_maximized=initial_is_maximized,
            )
            return
        self._view_window_manager.close_view()

    def _sync_annotation_window_action(self) -> None:
        visible = self.is_annotation_window_open()
        self._annotation_window_action.blockSignals(True)
        self._annotation_window_action.setChecked(visible)
        self._annotation_window_action.blockSignals(False)

    def _sync_view_window_action(self) -> None:
        visible = self.is_view_window_open()
        enabled = self.is_annotation_window_open()
        self._view_window_action.blockSignals(True)
        self._view_window_action.setEnabled(enabled)
        self._view_window_action.setChecked(visible)
        self._view_window_action.blockSignals(False)

    def _on_annotation_window_visibility_changed(self, visible: bool) -> None:
        self._sync_annotation_window_action()
        if visible:
            self._workspace_state_coordinator.track_annotation_window()
        if not visible and self.is_view_window_open():
            self.set_view_window_visible(False)
            return
        self._sync_view_window_action()

    def _on_view_window_visibility_changed(self, _visible: bool) -> None:
        if self.is_view_window_open():
            self._workspace_state_coordinator.track_view_window()
        self._sync_view_window_action()

    def get_mesh_window(self):
        return self.handlers.ui_event.get_mesh_window()

    @staticmethod
    def _decode_workspace_geometry(
        geometry_b64: str | None,
    ) -> QtCore.QByteArray | None:
        if geometry_b64 is None:
            return None
        if not isinstance(geometry_b64, str):
            return QtCore.QByteArray()
        if not geometry_b64.isascii():
            return QtCore.QByteArray()
        return QtCore.QByteArray.fromBase64(geometry_b64.encode("ascii"))

    def _resolve_detached_initial_state(
        self,
        detached_state,
        initial_geometry: QtCore.QByteArray | None,
        initial_is_maximized: bool,
    ) -> tuple[QtCore.QByteArray | None, bool]:
        if initial_geometry is not None:
            return initial_geometry, initial_is_maximized
        saved_geometry = self._decode_workspace_geometry(detached_state.geometry_b64)
        if saved_geometry is None:
            return initial_geometry, initial_is_maximized
        return saved_geometry, detached_state.is_maximized

    def set_mesh_window_visible(
        self,
        visible: bool,
        *,
        initial_geometry: QtCore.QByteArray | None = None,
        initial_is_maximized: bool = True,
    ) -> None:
        visible = bool(visible)
        if visible and not self.is_takeoff_tab_active():
            self._mesh_window_action.blockSignals(True)
            self._mesh_window_action.setChecked(False)
            self._mesh_window_action.blockSignals(False)
            return
        if visible:
            initial_geometry, initial_is_maximized = (
                self._resolve_detached_initial_state(
                    self._workspace_state_model.state.detached_windows.mesh_view,
                    initial_geometry,
                    initial_is_maximized,
                )
            )
        action = self._mesh_window_action
        if action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        self.handlers.ui_event.set_mesh_window_visible(
            visible,
            initial_geometry=initial_geometry,
            initial_is_maximized=initial_is_maximized,
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.handlers.ui_event.flush_current_page_state()
        self._workspace_state_coordinator.flush()
        self._workspace_state_coordinator.cleanup()
        self.event_coordinator.cleanup()
        self.handlers.ui_event.cleanup()
        self.license_coordinator.cleanup()
        self.ui_access_manager.cleanup()
        self._mcp_context_bridge.cleanup()
        lifecycle_orchestrator = self.app_controller.get_service(
            "lifecycle_orchestrator"
        )
        lifecycle_orchestrator.shutdown()
        super().closeEvent(event)
