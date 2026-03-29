from dataclasses import dataclass
from enum import Enum
from typing import Dict, Union
from PySide6 import QtGui, QtWidgets
from ..utils.themed_icon import apply_themed_icon, themed_icon


class IconId(Enum):
    OPEN_FILES = "open_files"
    ADD = "add"
    EDIT = "edit"
    DELETE = "delete"
    COPY = "copy"
    CUT = "cut"
    PASTE = "paste"
    DUPLICATE = "duplicate"
    UNDO = "undo"
    REDO = "redo"
    NEW_PROJECT = "new_project"
    NEW_FOLDER = "new_folder"
    NEW_DATABASE = "new_database"
    INSERT_IMAGE_PAGE = "insert_image_page"
    PREVIOUS_PAGE = "previous_page"
    NEXT_PAGE = "next_page"
    SELECT_TOOL = "select_tool"
    TAKEOFF_TOOL = "takeoff_tool"
    PAN_TOOL = "pan_tool"
    ZOOM_TOOL = "zoom_tool"
    RESET_VIEW = "reset_view"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    ANNOTATION_WINDOW = "annotation_window"
    VIEW_WINDOW = "view_window"
    VIEW_3D = "view_3d"
    BACKOUT_MODE = "backout_mode"
    COVER_SHEET = "cover_sheet"
    LAYERS_SIDEBAR = "layers_sidebar"
    CONDITIONS_SIDEBAR = "conditions_sidebar"
    SELECT_ALL = "select_all"
    UNSELECT_ALL = "unselect_all"
    MOVE_UP = "move_up"
    MOVE_DOWN = "move_down"


@dataclass(frozen=True)
class IconSpec:
    svg_name: str


ICON_SPECS: Dict[IconId, IconSpec] = {
    IconId.OPEN_FILES: IconSpec(
        "folder_open_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.ADD: IconSpec("add_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.EDIT: IconSpec("edit_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.DELETE: IconSpec("delete_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.COPY: IconSpec("content_copy_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.CUT: IconSpec("content_cut_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.PASTE: IconSpec("content_paste_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.DUPLICATE: IconSpec("file_copy_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.UNDO: IconSpec("undo_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.REDO: IconSpec("redo_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.NEW_PROJECT: IconSpec(
        "request_page_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.NEW_FOLDER: IconSpec(
        "create_new_folder_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.NEW_DATABASE: IconSpec(
        "database_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.INSERT_IMAGE_PAGE: IconSpec(
        "image_search_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.PREVIOUS_PAGE: IconSpec(
        "arrow_back_ios_new_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.NEXT_PAGE: IconSpec(
        "arrow_forward_ios_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.SELECT_TOOL: IconSpec(
        "arrow_selector_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.TAKEOFF_TOOL: IconSpec("crosshatch.svg"),
    IconId.PAN_TOOL: IconSpec("pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.ZOOM_TOOL: IconSpec("search_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.RESET_VIEW: IconSpec(
        "find_in_page_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.ZOOM_IN: IconSpec("zoom_in_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.ZOOM_OUT: IconSpec("zoom_out_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.ANNOTATION_WINDOW: IconSpec("ad_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.VIEW_WINDOW: IconSpec("vd_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.VIEW_3D: IconSpec("3d_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.BACKOUT_MODE: IconSpec("dialogs_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.COVER_SHEET: IconSpec("book_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.LAYERS_SIDEBAR: IconSpec("stack_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.CONDITIONS_SIDEBAR: IconSpec(
        "format_align_left_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.SELECT_ALL: IconSpec(
        "select_check_box_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.UNSELECT_ALL: IconSpec(
        "check_box_outline_blank_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.MOVE_UP: IconSpec(
        "keyboard_arrow_up_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.MOVE_DOWN: IconSpec(
        "keyboard_arrow_down_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
}
ACTION_ICONS: Dict[str, IconId] = {
    "open_files": IconId.OPEN_FILES,
    "add": IconId.ADD,
    "edit": IconId.EDIT,
    "copy": IconId.COPY,
    "cut": IconId.CUT,
    "paste": IconId.PASTE,
    "duplicate": IconId.DUPLICATE,
    "delete": IconId.DELETE,
    "delete_page": IconId.DELETE,
    "undo": IconId.UNDO,
    "redo": IconId.REDO,
    "new_project": IconId.NEW_PROJECT,
    "new_folder": IconId.NEW_FOLDER,
    "new_database": IconId.NEW_DATABASE,
    "previous_page": IconId.PREVIOUS_PAGE,
    "next_page": IconId.NEXT_PAGE,
    "select_tool": IconId.SELECT_TOOL,
    "takeoff_tool": IconId.TAKEOFF_TOOL,
    "pan_tool": IconId.PAN_TOOL,
    "zoom_tool": IconId.ZOOM_TOOL,
    "reset_view": IconId.RESET_VIEW,
    "zoom_in": IconId.ZOOM_IN,
    "zoom_out": IconId.ZOOM_OUT,
    "annotation_window": IconId.ANNOTATION_WINDOW,
    "view_window": IconId.VIEW_WINDOW,
    "mesh_window": IconId.VIEW_3D,
    "backout_mode": IconId.BACKOUT_MODE,
    "cover_sheet": IconId.COVER_SHEET,
    "show_cover_sheet": IconId.COVER_SHEET,
    "layers_sidebar": IconId.LAYERS_SIDEBAR,
    "conditions_sidebar": IconId.CONDITIONS_SIDEBAR,
}
IconTarget = Union[QtGui.QAction, QtWidgets.QAbstractButton]


class IconManager:
    @staticmethod
    def icon(icon_id: IconId) -> QtGui.QIcon:
        return themed_icon(ICON_SPECS[icon_id].svg_name)

    @staticmethod
    def apply(target: IconTarget, icon_id: IconId) -> None:
        apply_themed_icon(target, ICON_SPECS[icon_id].svg_name)

    @staticmethod
    def apply_to_action(action: QtGui.QAction, action_key: str) -> None:
        icon_id = ACTION_ICONS.get(action_key)
        if icon_id is not None:
            IconManager.apply(action, icon_id)
