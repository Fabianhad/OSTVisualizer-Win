from dataclasses import dataclass
from enum import Enum
from typing import Dict, Union
from PySide6 import QtGui, QtWidgets
from ..actions.action_ids import (
    ACTION_ADD,
    ACTION_ANNOTATION_WINDOW,
    ACTION_BACKOUT_MODE,
    ACTION_CONDITIONS_SIDEBAR,
    ACTION_COPY,
    ACTION_COVER_SHEET,
    ACTION_CUT,
    ACTION_DELETE,
    ACTION_DELETE_PAGE,
    ACTION_DUPLICATE,
    ACTION_EDIT,
    ACTION_LAYERS_SIDEBAR,
    ACTION_MESH_WINDOW,
    ACTION_MOVE_OVERLAY_IMAGE,
    ACTION_NEW_DATABASE,
    ACTION_NEW_FOLDER,
    ACTION_NEW_PROJECT,
    ACTION_NEXT_PAGE,
    ACTION_OPEN_FILES,
    ACTION_PASTE,
    ACTION_PREVIOUS_PAGE,
    ACTION_REDO,
    ACTION_RESET_VIEW,
    ACTION_SHOW_COVER_SHEET,
    ACTION_UNDO,
    ACTION_VIEW_WINDOW,
    ACTION_ZOOM_IN,
    ACTION_ZOOM_OUT,
)
from ..utils.themed_icon import apply_themed_icon, build_colored_icon, themed_icon


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
    PLACE_TOOL = "place_tool"
    PAN_TOOL = "pan_tool"
    DIMENSION_TOOL = "dimension_tool"
    HOTLINK_TOOL = "hotlink_tool"
    NAMED_VIEW_TOOL = "named_view_tool"
    TEXT_ANNOTATION_TOOL = "text_annotation_tool"
    HIGHLIGHT_ANNOTATION_TOOL = "highlight_annotation_tool"
    ARROW_ANNOTATION_TOOL = "arrow_annotation_tool"
    LINE_ANNOTATION_TOOL = "line_annotation_tool"
    RECTANGLE_ANNOTATION_TOOL = "rectangle_annotation_tool"
    OVAL_ANNOTATION_TOOL = "oval_annotation_tool"
    POLYGON_ANNOTATION_TOOL = "polygon_annotation_tool"
    CLOUD_ANNOTATION_TOOL = "cloud_annotation_tool"
    INK_ANNOTATION_TOOL = "ink_annotation_tool"
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
    MOVE_OVERLAY_IMAGE = "move_overlay_image"
    FORMAT_BOLD = "format_bold"
    FORMAT_ITALIC = "format_italic"
    FORMAT_UNDERLINE = "format_underline"
    FORMAT_ALIGN_LEFT = "format_align_left"
    FORMAT_ALIGN_CENTER = "format_align_center"
    FORMAT_ALIGN_RIGHT = "format_align_right"
    PROJECT_TREE_DATABASE = "project_tree_database"
    FOLDER = "folder"
    PROJECT_TREE_BID = "project_tree_bid"
    PAGE_TAKEOFF_INDICATOR = "page_takeoff_indicator"


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
    IconId.PLACE_TOOL: IconSpec("crosshatch.svg"),
    IconId.PAN_TOOL: IconSpec("pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.DIMENSION_TOOL: IconSpec(
        "square_foot_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.HOTLINK_TOOL: IconSpec("hotlink_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.NAMED_VIEW_TOOL: IconSpec(
        "named_view_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.TEXT_ANNOTATION_TOOL: IconSpec(
        "serif_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.HIGHLIGHT_ANNOTATION_TOOL: IconSpec(
        "ink_marker_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.ARROW_ANNOTATION_TOOL: IconSpec(
        "arrow_annotation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.LINE_ANNOTATION_TOOL: IconSpec(
        "line_annotation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.RECTANGLE_ANNOTATION_TOOL: IconSpec(
        "rectangle_annotation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.OVAL_ANNOTATION_TOOL: IconSpec(
        "oval_annotation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.POLYGON_ANNOTATION_TOOL: IconSpec(
        "polygon_annotation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.CLOUD_ANNOTATION_TOOL: IconSpec(
        "cloud_annotation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.INK_ANNOTATION_TOOL: IconSpec(
        "gesture_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
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
        "lists_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
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
    IconId.MOVE_OVERLAY_IMAGE: IconSpec(
        "recenter_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.FORMAT_BOLD: IconSpec(
        "format_bold_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.FORMAT_ITALIC: IconSpec(
        "format_italic_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.FORMAT_UNDERLINE: IconSpec(
        "format_underlined_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.FORMAT_ALIGN_LEFT: IconSpec(
        "format_align_left_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.FORMAT_ALIGN_CENTER: IconSpec(
        "format_align_center_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.FORMAT_ALIGN_RIGHT: IconSpec(
        "format_align_right_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.PROJECT_TREE_DATABASE: IconSpec(
        "database_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.FOLDER: IconSpec("folder_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
    IconId.PROJECT_TREE_BID: IconSpec(
        "request_page_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
    IconId.PAGE_TAKEOFF_INDICATOR: IconSpec(
        "draft_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
    ),
}
ACTION_ICONS: Dict[str, IconId] = {
    ACTION_OPEN_FILES: IconId.OPEN_FILES,
    ACTION_ADD: IconId.ADD,
    ACTION_EDIT: IconId.EDIT,
    ACTION_COPY: IconId.COPY,
    ACTION_CUT: IconId.CUT,
    ACTION_PASTE: IconId.PASTE,
    ACTION_DUPLICATE: IconId.DUPLICATE,
    ACTION_DELETE: IconId.DELETE,
    ACTION_DELETE_PAGE: IconId.DELETE,
    ACTION_UNDO: IconId.UNDO,
    ACTION_REDO: IconId.REDO,
    ACTION_NEW_PROJECT: IconId.NEW_PROJECT,
    ACTION_NEW_FOLDER: IconId.NEW_FOLDER,
    ACTION_NEW_DATABASE: IconId.NEW_DATABASE,
    ACTION_PREVIOUS_PAGE: IconId.PREVIOUS_PAGE,
    ACTION_NEXT_PAGE: IconId.NEXT_PAGE,
    IconId.SELECT_TOOL.value: IconId.SELECT_TOOL,
    IconId.PLACE_TOOL.value: IconId.PLACE_TOOL,
    IconId.PAN_TOOL.value: IconId.PAN_TOOL,
    IconId.DIMENSION_TOOL.value: IconId.DIMENSION_TOOL,
    IconId.HOTLINK_TOOL.value: IconId.HOTLINK_TOOL,
    IconId.NAMED_VIEW_TOOL.value: IconId.NAMED_VIEW_TOOL,
    IconId.TEXT_ANNOTATION_TOOL.value: IconId.TEXT_ANNOTATION_TOOL,
    IconId.HIGHLIGHT_ANNOTATION_TOOL.value: IconId.HIGHLIGHT_ANNOTATION_TOOL,
    IconId.ARROW_ANNOTATION_TOOL.value: IconId.ARROW_ANNOTATION_TOOL,
    IconId.LINE_ANNOTATION_TOOL.value: IconId.LINE_ANNOTATION_TOOL,
    IconId.RECTANGLE_ANNOTATION_TOOL.value: IconId.RECTANGLE_ANNOTATION_TOOL,
    IconId.OVAL_ANNOTATION_TOOL.value: IconId.OVAL_ANNOTATION_TOOL,
    IconId.POLYGON_ANNOTATION_TOOL.value: IconId.POLYGON_ANNOTATION_TOOL,
    IconId.CLOUD_ANNOTATION_TOOL.value: IconId.CLOUD_ANNOTATION_TOOL,
    IconId.INK_ANNOTATION_TOOL.value: IconId.INK_ANNOTATION_TOOL,
    IconId.ZOOM_TOOL.value: IconId.ZOOM_TOOL,
    ACTION_RESET_VIEW: IconId.RESET_VIEW,
    ACTION_ZOOM_IN: IconId.ZOOM_IN,
    ACTION_ZOOM_OUT: IconId.ZOOM_OUT,
    ACTION_ANNOTATION_WINDOW: IconId.ANNOTATION_WINDOW,
    ACTION_VIEW_WINDOW: IconId.VIEW_WINDOW,
    ACTION_MESH_WINDOW: IconId.VIEW_3D,
    ACTION_BACKOUT_MODE: IconId.BACKOUT_MODE,
    ACTION_COVER_SHEET: IconId.COVER_SHEET,
    ACTION_SHOW_COVER_SHEET: IconId.COVER_SHEET,
    ACTION_LAYERS_SIDEBAR: IconId.LAYERS_SIDEBAR,
    ACTION_CONDITIONS_SIDEBAR: IconId.CONDITIONS_SIDEBAR,
    ACTION_MOVE_OVERLAY_IMAGE: IconId.MOVE_OVERLAY_IMAGE,
}
IconTarget = Union[QtGui.QAction, QtWidgets.QAbstractButton]


class IconManager:
    @staticmethod
    def icon(icon_id: IconId) -> QtGui.QIcon:
        return themed_icon(ICON_SPECS[icon_id].svg_name)

    @staticmethod
    def colored_icon(icon_id: IconId, hex_color: str) -> QtGui.QIcon:
        return build_colored_icon(ICON_SPECS[icon_id].svg_name, hex_color)

    @staticmethod
    def apply(target: IconTarget, icon_id: IconId) -> None:
        apply_themed_icon(target, ICON_SPECS[icon_id].svg_name)

    @staticmethod
    def apply_colored(target: IconTarget, icon_id: IconId, hex_color: str) -> None:
        target.setIcon(IconManager.colored_icon(icon_id, hex_color))

    @staticmethod
    def apply_to_action(action: QtGui.QAction, action_key: str) -> None:
        icon_id = ACTION_ICONS.get(action_key)
        if icon_id is not None:
            IconManager.apply(action, icon_id)
