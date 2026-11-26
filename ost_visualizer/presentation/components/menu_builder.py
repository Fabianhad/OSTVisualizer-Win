from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from PySide6 import QtGui, QtWidgets
from ...domain.entities.config import Config
from ..actions.action_ids import (
    ACTION_ADJUST_IMAGES,
    ACTION_ANNOTATION_WINDOW,
    ACTION_BACKOUT_MODE,
    ACTION_CONDITIONS_SIDEBAR,
    ACTION_DEFAULT_LAYERS,
    ACTION_FLIP_IMAGE_HORIZONTAL,
    ACTION_FLIP_IMAGE_VERTICAL,
    ACTION_LAYERS_SIDEBAR,
    ACTION_NEW_DATABASE,
    ACTION_NEW_FOLDER,
    ACTION_NEW_PROJECT,
    ACTION_NEXT_PAGE,
    ACTION_OPEN_FILES,
    ACTION_PAN_SIDEBAR,
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
    ACTION_STATUS_BAR,
    ACTION_TOGGLE_MAIN_TOOLBAR,
    ACTION_TOGGLE_PLAN_TOOLS_TOOLBAR,
    ACTION_TOGGLE_TAKEOFF_DISPLAY_MODES_SYNC,
    ACTION_TOGGLE_VIEW_TOOLBAR,
    ACTION_ZOOM_IN,
    ACTION_ZOOM_OUT,
)
from ..texts import (
    MAIN_TOOLBAR_LABEL,
    MENU_BUILDER_ACTION_2D,
    MENU_BUILDER_ACTION_3D,
    MENU_BUILDER_ACTION_ABOUT_OST_VISUALIZER,
    MENU_BUILDER_ACTION_ADJUST_IMAGES,
    MENU_BUILDER_ACTION_BITONAL,
    MENU_BUILDER_ACTION_CHECK_AUTHORIZATION,
    MENU_BUILDER_ACTION_CLOSE,
    MENU_BUILDER_ACTION_CONDITION_TYPES,
    MENU_BUILDER_ACTION_DEFAULT_LAYERS,
    MENU_BUILDER_ACTION_EMPLOYEES,
    MENU_BUILDER_ACTION_EXIT,
    MENU_BUILDER_ACTION_FLIP_IMAGE_HORIZONTAL,
    MENU_BUILDER_ACTION_FLIP_IMAGE_VERTICAL,
    MENU_BUILDER_ACTION_FLIP_TAKEOFF_HORIZONTAL,
    MENU_BUILDER_ACTION_FLIP_TAKEOFF_VERTICAL,
    MENU_BUILDER_ACTION_GRAYSCALE,
    MENU_BUILDER_ACTION_INVERT,
    MENU_BUILDER_ACTION_JOB_STATUSES,
    MENU_BUILDER_ACTION_OPTIONS,
    MENU_BUILDER_ACTION_ORIGINAL,
    MENU_BUILDER_ACTION_OSP_FILE,
    MENU_BUILDER_ACTION_OST_FILE,
    MENU_BUILDER_ACTION_PAYROLL_CLASSES,
    MENU_BUILDER_ACTION_REMOVE_OVERLAY_IMAGE,
    MENU_BUILDER_ACTION_RENAME_PAGE,
    MENU_BUILDER_ACTION_RENUMBER_CONDITIONS,
    MENU_BUILDER_ACTION_ROTATE_IMAGE_LEFT,
    MENU_BUILDER_ACTION_ROTATE_IMAGE_RIGHT,
    MENU_BUILDER_ACTION_ROTATE_TAKEOFF_LEFT,
    MENU_BUILDER_ACTION_ROTATE_TAKEOFF_RIGHT,
    MENU_BUILDER_ACTION_SELECT_OBJECTS_IN_CURRENT_AREA,
    ACTION_SELECT_OVERLAY_IMAGE_LABEL,
    MENU_BUILDER_ACTION_SET_SCALE,
    MENU_BUILDER_ACTION_SHOW_AREAS,
    MENU_BUILDER_ACTION_SHOW_COVER_SHEET,
    ACTION_SHOW_ORIGINAL_IMAGE_LABEL,
    ACTION_SHOW_OVERLAY_IMAGE_LABEL,
    MENU_BUILDER_ACTION_SOLID,
    MENU_BUILDER_ACTION_SYNC_2D_3D_DISPLAY_MODES,
    MENU_BUILDER_ACTION_TO_CSV_FILE,
    MENU_BUILDER_ACTION_TO_FILE,
    MENU_BUILDER_ACTION_TO_OSP_FILE,
    MENU_BUILDER_ACTION_TO_OST_FILE,
    MENU_BUILDER_ACTION_TO_PDF_FILE,
    MENU_BUILDER_ACTION_TRANSPARENT,
    MENU_BUILDER_MENU_2D_DISPLAY_MODE,
    MENU_BUILDER_MENU_3D_DISPLAY_MODE,
    MENU_BUILDER_MENU_EDIT,
    MENU_BUILDER_MENU_EXPORT,
    MENU_BUILDER_MENU_FILE,
    MENU_BUILDER_MENU_HELP,
    MENU_BUILDER_MENU_IMAGE,
    MENU_BUILDER_MENU_IMPORT,
    MENU_BUILDER_MENU_MASTER,
    MENU_BUILDER_MENU_NEW,
    MENU_BUILDER_MENU_PROJECT,
    MENU_BUILDER_MENU_ROTATE_FLIP,
    MENU_BUILDER_MENU_TABS,
    MENU_BUILDER_MENU_TAKEOFF,
    MENU_BUILDER_MENU_TOOLBARS,
    MENU_BUILDER_MENU_TOOLS,
    MENU_BUILDER_MENU_VIEW,
    PLAN_TOOLS_TOOLBAR_LABEL,
    VIEW_TOOLBAR_LABEL,
)
from ..managers.icon_manager import IconManager
from ..managers.shortcut_manager import ShortcutManager
from ..utils.plan_tool_registry import PLAN_TOOL_MENU_ITEMS


@dataclass
class MenuBuildResult:
    menu_bar: QtWidgets.QMenuBar
    actions: Dict[str, QtGui.QAction]
    menus: Dict[str, QtWidgets.QMenu]
    variable_actions: Dict[str, List[QtGui.QAction]]


class MenuBuilder:
    def __init__(
        self,
        parent,
        callbacks: Dict[str, Callable],
        state_getters: Optional[Dict[str, Callable[[], object]]] = None,
        export_formats: Optional[List[str]] = None,
        shared_actions: Optional[Dict[str, QtGui.QAction]] = None,
    ):
        self.parent = parent
        self.callbacks = callbacks
        self.state_getters = state_getters or {}
        self._export_formats = export_formats or []
        self._shared_actions = dict(shared_actions or {})
        self.actions: Dict[str, QtGui.QAction] = {}
        self.menus: Dict[str, QtWidgets.QMenu] = {}
        self.variable_actions: Dict[str, List[QtGui.QAction]] = {}
        self._action_groups: Dict[str, QtGui.QActionGroup] = {}
        self._owned_actions: List[QtGui.QAction] = []

    def create_menu(self) -> MenuBuildResult:
        menu_bar = QtWidgets.QMenuBar(self.parent)
        for label, items in self._get_menu_definition().items():
            menu = menu_bar.addMenu(label)
            self.menus[label.lower()] = menu
            self._build_menu(menu, items)
        return MenuBuildResult(
            menu_bar=menu_bar,
            actions=self.actions,
            menus=self.menus,
            variable_actions=self.variable_actions,
        )

    def _get_menu_definition(self) -> Dict[str, list]:
        export_items = [
            ("cmd", MENU_BUILDER_ACTION_TO_FILE.format(fmt=fmt), f"export_as_{fmt}")
            for fmt in self._export_formats
        ]
        export_items.extend(
            [
                ("cmd", MENU_BUILDER_ACTION_TO_CSV_FILE, "export_summary_csv"),
                ("cmd", MENU_BUILDER_ACTION_TO_PDF_FILE, "export_as_pdf"),
                ("cmd", MENU_BUILDER_ACTION_TO_OST_FILE, "export_as_ost"),
                ("cmd", MENU_BUILDER_ACTION_TO_OSP_FILE, "export_as_osp"),
            ]
        )
        return {
            MENU_BUILDER_MENU_FILE: [
                (
                    "cascade",
                    MENU_BUILDER_MENU_NEW,
                    [
                        ("shared", ACTION_NEW_PROJECT),
                        ("sep",),
                        ("shared", ACTION_NEW_FOLDER),
                        ("shared", ACTION_NEW_DATABASE),
                    ],
                ),
                ("sep",),
                ("shared", ACTION_OPEN_FILES),
                ("cmd", MENU_BUILDER_ACTION_CLOSE, "unload_file"),
                ("sep",),
                (
                    "cascade",
                    MENU_BUILDER_MENU_IMPORT,
                    [
                        ("cmd", MENU_BUILDER_ACTION_OST_FILE, "import_ost"),
                        ("cmd", MENU_BUILDER_ACTION_OSP_FILE, "import_osp"),
                    ],
                ),
                ("cascade", MENU_BUILDER_MENU_EXPORT, export_items),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_CHECK_AUTHORIZATION, "check_license"),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_EXIT, "quit"),
            ],
            MENU_BUILDER_MENU_EDIT: [
                ("shared", "undo"),
                ("shared", "redo"),
                ("sep",),
                ("shared", "cut"),
                ("shared", "copy"),
                ("shared", "paste"),
                ("shared", "duplicate"),
                ("sep",),
                ("shared", "delete"),
                ("sep",),
                ("shared", "select_all"),
                (
                    "cmd",
                    MENU_BUILDER_ACTION_SELECT_OBJECTS_IN_CURRENT_AREA,
                    "select_objects_in_current_area",
                ),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_SET_SCALE, "set_scale"),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_RENAME_PAGE, "rename_page"),
            ],
            MENU_BUILDER_MENU_VIEW: [
                (
                    "cascade",
                    MENU_BUILDER_MENU_TOOLBARS,
                    [
                        (
                            "check",
                            MAIN_TOOLBAR_LABEL,
                            "main_toolbar_visible",
                            ACTION_TOGGLE_MAIN_TOOLBAR,
                        ),
                        (
                            "check",
                            VIEW_TOOLBAR_LABEL,
                            "view_toolbar_visible",
                            ACTION_TOGGLE_VIEW_TOOLBAR,
                        ),
                        (
                            "check",
                            PLAN_TOOLS_TOOLBAR_LABEL,
                            "plan_tools_toolbar_visible",
                            ACTION_TOGGLE_PLAN_TOOLS_TOOLBAR,
                        ),
                    ],
                ),
                (
                    "cascade",
                    MENU_BUILDER_MENU_TAKEOFF,
                    [
                        (
                            "check",
                            MENU_BUILDER_ACTION_SYNC_2D_3D_DISPLAY_MODES,
                            "display_modes_synced",
                            ACTION_TOGGLE_TAKEOFF_DISPLAY_MODES_SYNC,
                        ),
                        ("sep",),
                        (
                            "cascade",
                            MENU_BUILDER_MENU_3D_DISPLAY_MODE,
                            [
                                (
                                    "radio",
                                    MENU_BUILDER_ACTION_TRANSPARENT,
                                    "display_mode_3d",
                                    Config.DISPLAY_MODE_TRANSPARENT,
                                    ACTION_SET_TAKEOFF_DISPLAY_MODE_3D,
                                ),
                                (
                                    "radio",
                                    MENU_BUILDER_ACTION_SOLID,
                                    "display_mode_3d",
                                    Config.DISPLAY_MODE_SOLID,
                                    ACTION_SET_TAKEOFF_DISPLAY_MODE_3D,
                                ),
                                (
                                    "radio",
                                    MENU_BUILDER_ACTION_ORIGINAL,
                                    "display_mode_3d",
                                    Config.DISPLAY_MODE_ORIGINAL,
                                    ACTION_SET_TAKEOFF_DISPLAY_MODE_3D,
                                ),
                            ],
                        ),
                        (
                            "cascade",
                            MENU_BUILDER_MENU_2D_DISPLAY_MODE,
                            [
                                (
                                    "radio",
                                    MENU_BUILDER_ACTION_TRANSPARENT,
                                    "display_mode_2d",
                                    Config.DISPLAY_MODE_TRANSPARENT,
                                    ACTION_SET_TAKEOFF_DISPLAY_MODE_2D,
                                ),
                                (
                                    "radio",
                                    MENU_BUILDER_ACTION_SOLID,
                                    "display_mode_2d",
                                    Config.DISPLAY_MODE_SOLID,
                                    ACTION_SET_TAKEOFF_DISPLAY_MODE_2D,
                                ),
                                (
                                    "radio",
                                    MENU_BUILDER_ACTION_ORIGINAL,
                                    "display_mode_2d",
                                    Config.DISPLAY_MODE_ORIGINAL,
                                    ACTION_SET_TAKEOFF_DISPLAY_MODE_2D,
                                ),
                            ],
                        ),
                        ("sep",),
                        (
                            "check",
                            MENU_BUILDER_ACTION_GRAYSCALE,
                            "grayscale",
                            "toggle_takeoff_grayscale",
                        ),
                    ],
                ),
                (
                    "cascade",
                    MENU_BUILDER_MENU_TABS,
                    [
                        (
                            "check",
                            MENU_BUILDER_ACTION_2D,
                            "takeoff_2d_tab_visible",
                            "toggle_2d_tab",
                        ),
                        (
                            "check",
                            MENU_BUILDER_ACTION_3D,
                            "takeoff_3d_tab_visible",
                            "toggle_3d_tab",
                        ),
                    ],
                ),
                ("sep",),
                ("shared", ACTION_ZOOM_IN),
                ("shared", ACTION_ZOOM_OUT),
                ("shared", ACTION_RESET_VIEW),
                ("sep",),
                ("shared", ACTION_NEXT_PAGE),
                ("shared", ACTION_PREVIOUS_PAGE),
                ("sep",),
                ("shared", ACTION_PAN_SIDEBAR),
                ("shared", ACTION_CONDITIONS_SIDEBAR),
                ("shared", ACTION_LAYERS_SIDEBAR),
                ("shared", ACTION_STATUS_BAR),
                ("shared", ACTION_ANNOTATION_WINDOW),
            ],
            MENU_BUILDER_MENU_TOOLS: [
                *PLAN_TOOL_MENU_ITEMS,
                ("sep",),
                ("shared", ACTION_BACKOUT_MODE),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_OPTIONS, "options"),
            ],
            MENU_BUILDER_MENU_IMAGE: [
                ("cmd", MENU_BUILDER_ACTION_ADJUST_IMAGES, ACTION_ADJUST_IMAGES),
                ("sep",),
                (
                    "check",
                    MENU_BUILDER_ACTION_INVERT,
                    "page_invert",
                    "toggle_page_invert",
                ),
                (
                    "check",
                    MENU_BUILDER_ACTION_BITONAL,
                    "page_bitonal",
                    "toggle_page_bitonal",
                ),
                ("sep",),
                (
                    "cascade",
                    MENU_BUILDER_MENU_ROTATE_FLIP,
                    [
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_ROTATE_TAKEOFF_LEFT,
                            "rotate_takeoff_left",
                        ),
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_ROTATE_TAKEOFF_RIGHT,
                            "rotate_takeoff_right",
                        ),
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_FLIP_TAKEOFF_HORIZONTAL,
                            "flip_takeoff_horizontal",
                        ),
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_FLIP_TAKEOFF_VERTICAL,
                            "flip_takeoff_vertical",
                        ),
                        ("sep",),
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_ROTATE_IMAGE_LEFT,
                            ACTION_ROTATE_IMAGE_LEFT,
                        ),
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_ROTATE_IMAGE_RIGHT,
                            ACTION_ROTATE_IMAGE_RIGHT,
                        ),
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_FLIP_IMAGE_HORIZONTAL,
                            ACTION_FLIP_IMAGE_HORIZONTAL,
                        ),
                        (
                            "cmd",
                            MENU_BUILDER_ACTION_FLIP_IMAGE_VERTICAL,
                            ACTION_FLIP_IMAGE_VERTICAL,
                        ),
                    ],
                ),
                ("sep",),
                ("cmd", ACTION_SELECT_OVERLAY_IMAGE_LABEL, ACTION_SELECT_OVERLAY_IMAGE),
                (
                    "cmd",
                    MENU_BUILDER_ACTION_REMOVE_OVERLAY_IMAGE,
                    ACTION_REMOVE_OVERLAY_IMAGE,
                ),
                ("sep",),
                (
                    "check",
                    ACTION_SHOW_OVERLAY_IMAGE_LABEL,
                    ACTION_SHOW_OVERLAY_IMAGE,
                    ACTION_SHOW_OVERLAY_IMAGE,
                ),
                (
                    "check",
                    ACTION_SHOW_ORIGINAL_IMAGE_LABEL,
                    ACTION_SHOW_ORIGINAL_IMAGE,
                    ACTION_SHOW_ORIGINAL_IMAGE,
                ),
            ],
            MENU_BUILDER_MENU_PROJECT: [
                ("cmd", MENU_BUILDER_ACTION_SHOW_COVER_SHEET, ACTION_SHOW_COVER_SHEET),
                ("cmd", MENU_BUILDER_ACTION_SHOW_AREAS, "show_areas"),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_RENUMBER_CONDITIONS, "renumber_conditions"),
            ],
            MENU_BUILDER_MENU_MASTER: [
                ("cmd", MENU_BUILDER_ACTION_EMPLOYEES, "employees"),
                ("cmd", MENU_BUILDER_ACTION_JOB_STATUSES, "job_statuses"),
                ("cmd", MENU_BUILDER_ACTION_CONDITION_TYPES, "condition_types"),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_PAYROLL_CLASSES, "payroll_classes"),
                ("sep",),
                ("cmd", MENU_BUILDER_ACTION_DEFAULT_LAYERS, ACTION_DEFAULT_LAYERS),
            ],
            MENU_BUILDER_MENU_HELP: [
                ("cmd", MENU_BUILDER_ACTION_ABOUT_OST_VISUALIZER, "show_about"),
            ],
        }

    def _build_menu(self, menu: QtWidgets.QMenu, items: list) -> None:
        for item in items:
            item_type = item[0]
            if item_type == "sep":
                menu.addSeparator()
            elif item_type == "cmd":
                self._add_command(menu, item)
            elif item_type == "check":
                self._add_check_action(menu, item)
            elif item_type == "radio":
                self._add_radio_action(menu, item)
            elif item_type == "cascade":
                self._add_submenu(menu, item)
            elif item_type == "shared":
                self._add_shared_action(menu, item)

    def _add_command(self, menu: QtWidgets.QMenu, item: tuple) -> None:
        _, label, callback_key = item
        callback = self.callbacks.get(callback_key, self._no_op)
        action = menu.addAction(label)
        ShortcutManager.apply_to_action(action, callback_key)
        IconManager.apply_to_action(action, callback_key)
        action.triggered.connect(callback)
        self.actions[callback_key] = action
        self._owned_actions.append(action)

    def _add_check_action(self, menu: QtWidgets.QMenu, item: tuple) -> None:
        _, label, variable_key, callback_key = item
        callback = self.callbacks.get(callback_key, self._no_op)
        action = QtGui.QAction(label, menu)
        action.setCheckable(True)
        ShortcutManager.apply_to_action(action, callback_key)
        IconManager.apply_to_action(action, callback_key)
        getter = self.state_getters.get(variable_key)
        if getter:
            action.setChecked(bool(getter()))

        def on_check_action_triggered(checked):
            callback(checked)

        action.triggered.connect(on_check_action_triggered)
        menu.addAction(action)
        self.actions[callback_key] = action
        self._owned_actions.append(action)
        self.variable_actions.setdefault(variable_key, []).append(action)

    def _add_radio_action(self, menu: QtWidgets.QMenu, item: tuple) -> None:
        _, label, variable_key, value, callback_key = item
        callback = self.callbacks.get(callback_key, self._no_op)
        action = QtGui.QAction(label, menu)
        action.setCheckable(True)
        ShortcutManager.apply_to_action(action, callback_key)
        IconManager.apply_to_action(action, callback_key)
        getter = self.state_getters.get(variable_key)
        current_value = getter() if getter else None
        action.setChecked(current_value == value)

        def on_radio_action_triggered(checked, v=value):
            callback(v)

        action.triggered.connect(on_radio_action_triggered)
        group = self._action_groups.get(variable_key)
        if not group:
            group = QtGui.QActionGroup(menu)
            group.setExclusive(True)
            self._action_groups[variable_key] = group
        group.addAction(action)
        menu.addAction(action)
        self._owned_actions.append(action)
        self.actions.setdefault(callback_key, action)
        action.setData(value)
        self.variable_actions.setdefault(variable_key, []).append(action)

    def _add_shared_action(self, menu: QtWidgets.QMenu, item: tuple) -> None:
        _, action_key = item
        action = self._shared_actions[action_key]
        ShortcutManager.apply_to_action(action, action_key)
        IconManager.apply_to_action(action, action_key)
        menu.addAction(action)
        self.actions[action_key] = action

    def _add_submenu(self, menu: QtWidgets.QMenu, item: tuple) -> None:
        _, label, submenu_items = item
        submenu = QtWidgets.QMenu(label, menu)
        key = label.lower()
        self.menus[key] = submenu
        self._build_menu(submenu, submenu_items)
        menu.addMenu(submenu)

    @staticmethod
    def _no_op(*_args, **_kwargs) -> None:
        pass

    def cleanup(self) -> None:
        if self._owned_actions is None:
            return
        for action in self._owned_actions:
            try:
                action.triggered.disconnect()
            except (TypeError, RuntimeError):
                pass
        if self._owned_actions:
            self._owned_actions.clear()
        self._owned_actions = None
        if self.actions:
            self.actions.clear()
        self.actions = None
        if self.menus:
            self.menus.clear()
        self.menus = None
        if self.variable_actions:
            for action_list in self.variable_actions.values():
                if action_list:
                    action_list.clear()
            self.variable_actions.clear()
        self.variable_actions = None
        if self._action_groups:
            self._action_groups.clear()
        self._action_groups = None
        if self.callbacks:
            self.callbacks.clear()
        self.callbacks = None
        if self.state_getters:
            self.state_getters.clear()
        self.state_getters = None
        if self._shared_actions:
            self._shared_actions.clear()
        self._shared_actions = None
        self.parent = None
