from __future__ import annotations
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional
from .annotation_style import AnnotationStyle

WORKSPACE_ACTIVE_VIEW_2D = "2d"
WORKSPACE_ACTIVE_VIEW_3D = "3d"
WORKSPACE_VALID_ACTIVE_VIEWS = frozenset(
    {WORKSPACE_ACTIVE_VIEW_2D, WORKSPACE_ACTIVE_VIEW_3D}
)
WORKSPACE_KEY_SCHEMA_VERSION = "schema_version"
WORKSPACE_KEY_MAIN_WINDOW = "main_window"
WORKSPACE_KEY_TAKEOFF_WORKSPACE = "takeoff_workspace"
WORKSPACE_KEY_PROJECT_WORKSPACE = "project_workspace"
WORKSPACE_KEY_COVER_SHEET = "cover_sheet"
WORKSPACE_KEY_TOOLBAR_VISIBILITY = "toolbar_visibility"
WORKSPACE_KEY_DETACHED_WINDOWS = "detached_windows"
WORKSPACE_KEY_ACTIVE_VIEW = "active_view"
WORKSPACE_KEY_SELECTED_NODE = "selected_node"
WORKSPACE_KEY_KIND = "kind"
WORKSPACE_KEY_FILE_PATH = "file_path"
WORKSPACE_KEY_PROJECT_UID = "project_uid"
WORKSPACE_KEY_BID_UID = "bid_uid"
WORKSPACE_NODE_KIND_DATABASE = "database"
WORKSPACE_NODE_KIND_PROJECT = "project"
WORKSPACE_NODE_KIND_BID = "bid"
WORKSPACE_SELECTED_NODE_KINDS = frozenset(
    {
        WORKSPACE_NODE_KIND_DATABASE,
        WORKSPACE_NODE_KIND_PROJECT,
        WORKSPACE_NODE_KIND_BID,
    }
)


def _coerce_optional_str(value) -> Optional[str]:
    if value in (None, ""):
        return None
    return str(value)


def _coerce_bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_int_list(value) -> List[int]:
    if not isinstance(value, list):
        return []
    result: List[int] = []
    for item in value:
        try:
            result.append(max(0, int(item)))
        except (TypeError, ValueError):
            continue
    return result


def _coerce_size_dict(value) -> Dict[str, List[int]]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, List[int]] = {}
    for key, raw_size in value.items():
        size = _coerce_int_list(raw_size)
        if len(size) >= 2 and size[0] > 0 and size[1] > 0:
            result[str(key)] = size[:2]
    return result


def _coerce_positive_int_dict(value) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, int] = {}
    for key, raw_value in value.items():
        try:
            width = int(raw_value)
        except (TypeError, ValueError):
            continue
        if width > 0:
            result[str(key)] = width
    return result


def _coerce_str_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


@dataclass
class MainWindowWorkspaceState:
    geometry_b64: Optional[str] = None
    state_b64: Optional[str] = None
    is_maximized: bool = True
    status_bar_visible: bool = True

    def to_dict(self) -> dict:
        return {
            "geometry_b64": self.geometry_b64,
            "state_b64": self.state_b64,
            "is_maximized": self.is_maximized,
            "status_bar_visible": self.status_bar_visible,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MainWindowWorkspaceState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            geometry_b64=_coerce_optional_str(data.get("geometry_b64")),
            state_b64=_coerce_optional_str(data.get("state_b64")),
            is_maximized=_coerce_bool(data.get("is_maximized"), True),
            status_bar_visible=_coerce_bool(data.get("status_bar_visible"), True),
        )


@dataclass
class TakeoffWorkspaceState:
    VALID_ACTIVE_VIEWS: ClassVar[frozenset[str]] = WORKSPACE_VALID_ACTIVE_VIEWS
    active_view: str = WORKSPACE_ACTIVE_VIEW_3D
    view_2d_tab_visible: bool = True
    view_3d_tab_visible: bool = True
    conditions_sidebar_visible: bool = True
    layers_sidebar_visible: bool = True
    takeoff_splitter_sizes: List[int] = field(default_factory=list)
    left_splitter_sizes: List[int] = field(default_factory=list)
    dropdown_popup_sizes: Dict[str, List[int]] = field(default_factory=dict)
    conditions_header_state_b64: Optional[str] = None
    layers_header_state_b64: Optional[str] = None
    conditions_group_by_type: bool = True
    summary_group_by_area: bool = True
    summary_group_by_type: bool = True
    summary_group_by_page: bool = False
    summary_column_widths: Dict[str, int] = field(default_factory=dict)
    annotation_styles: Dict[str, AnnotationStyle] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            WORKSPACE_KEY_ACTIVE_VIEW: self.active_view,
            "view_2d_tab_visible": self.view_2d_tab_visible,
            "view_3d_tab_visible": self.view_3d_tab_visible,
            "conditions_sidebar_visible": self.conditions_sidebar_visible,
            "layers_sidebar_visible": self.layers_sidebar_visible,
            "takeoff_splitter_sizes": list(self.takeoff_splitter_sizes),
            "left_splitter_sizes": list(self.left_splitter_sizes),
            "dropdown_popup_sizes": {
                str(key): list(value)
                for key, value in self.dropdown_popup_sizes.items()
            },
            "conditions_header_state_b64": self.conditions_header_state_b64,
            "layers_header_state_b64": self.layers_header_state_b64,
            "conditions_group_by_type": self.conditions_group_by_type,
            "summary_group_by_area": self.summary_group_by_area,
            "summary_group_by_type": self.summary_group_by_type,
            "summary_group_by_page": self.summary_group_by_page,
            "summary_column_widths": _coerce_positive_int_dict(
                self.summary_column_widths
            ),
            "annotation_styles": {
                str(key): style.to_dict()
                for key, style in self.annotation_styles.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> TakeoffWorkspaceState:
        if not isinstance(data, dict):
            return cls()
        active_view = str(
            data.get(WORKSPACE_KEY_ACTIVE_VIEW, WORKSPACE_ACTIVE_VIEW_3D)
        ).lower()
        if active_view not in cls.VALID_ACTIVE_VIEWS:
            active_view = WORKSPACE_ACTIVE_VIEW_3D
        return cls(
            active_view=active_view,
            view_2d_tab_visible=_coerce_bool(data.get("view_2d_tab_visible"), True),
            view_3d_tab_visible=_coerce_bool(data.get("view_3d_tab_visible"), True),
            conditions_sidebar_visible=_coerce_bool(
                data.get("conditions_sidebar_visible"), True
            ),
            layers_sidebar_visible=_coerce_bool(
                data.get("layers_sidebar_visible"), True
            ),
            takeoff_splitter_sizes=_coerce_int_list(data.get("takeoff_splitter_sizes")),
            left_splitter_sizes=_coerce_int_list(data.get("left_splitter_sizes")),
            dropdown_popup_sizes=_coerce_size_dict(data.get("dropdown_popup_sizes")),
            conditions_header_state_b64=_coerce_optional_str(
                data.get("conditions_header_state_b64")
            ),
            layers_header_state_b64=_coerce_optional_str(
                data.get("layers_header_state_b64")
            ),
            conditions_group_by_type=_coerce_bool(
                data.get("conditions_group_by_type"), True
            ),
            summary_group_by_area=_coerce_bool(data.get("summary_group_by_area"), True),
            summary_group_by_type=_coerce_bool(data.get("summary_group_by_type"), True),
            summary_group_by_page=_coerce_bool(
                data.get("summary_group_by_page"), False
            ),
            summary_column_widths=_coerce_positive_int_dict(
                data.get("summary_column_widths")
            ),
            annotation_styles={
                str(key): AnnotationStyle.from_dict(value)
                for key, value in (
                    data.get("annotation_styles")
                    if isinstance(data.get("annotation_styles"), dict)
                    else {}
                ).items()
            },
        )


@dataclass
class ProjectTreeSelectionState:
    kind: str
    file_path: str
    bid_uid: Optional[str] = None
    project_uid: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            WORKSPACE_KEY_KIND: self.kind,
            WORKSPACE_KEY_FILE_PATH: self.file_path,
            WORKSPACE_KEY_BID_UID: self.bid_uid,
            WORKSPACE_KEY_PROJECT_UID: self.project_uid,
        }

    @classmethod
    def from_dict(cls, data) -> Optional[ProjectTreeSelectionState]:
        if not isinstance(data, dict):
            return None
        kind = _coerce_optional_str(data.get(WORKSPACE_KEY_KIND))
        file_path = _coerce_optional_str(data.get(WORKSPACE_KEY_FILE_PATH))
        if kind not in WORKSPACE_SELECTED_NODE_KINDS or not file_path:
            return None
        bid_uid = _coerce_optional_str(data.get(WORKSPACE_KEY_BID_UID))
        project_uid = _coerce_optional_str(data.get(WORKSPACE_KEY_PROJECT_UID))
        if kind == WORKSPACE_NODE_KIND_BID and not bid_uid:
            return None
        if kind == WORKSPACE_NODE_KIND_PROJECT and not project_uid:
            return None
        return cls(
            kind=kind,
            file_path=file_path,
            bid_uid=bid_uid if kind == WORKSPACE_NODE_KIND_BID else None,
            project_uid=(project_uid if kind == WORKSPACE_NODE_KIND_PROJECT else None),
        )


@dataclass
class ProjectWorkspaceState:
    header_state_b64: Optional[str] = None
    expanded_node_keys: Optional[List[str]] = None
    group_by_job_status: bool = False
    selected_node: Optional[ProjectTreeSelectionState] = None

    def to_dict(self) -> dict:
        return {
            "header_state_b64": self.header_state_b64,
            "expanded_node_keys": (
                list(self.expanded_node_keys)
                if self.expanded_node_keys is not None
                else None
            ),
            "group_by_job_status": self.group_by_job_status,
            WORKSPACE_KEY_SELECTED_NODE: (
                self.selected_node.to_dict() if self.selected_node else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectWorkspaceState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            header_state_b64=_coerce_optional_str(data.get("header_state_b64")),
            expanded_node_keys=(
                _coerce_str_list(data.get("expanded_node_keys"))
                if "expanded_node_keys" in data
                else None
            ),
            group_by_job_status=_coerce_bool(data.get("group_by_job_status"), False),
            selected_node=ProjectTreeSelectionState.from_dict(
                data.get(WORKSPACE_KEY_SELECTED_NODE)
            ),
        )


@dataclass
class CoverSheetWorkspaceState:
    plan_header_state_b64: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "plan_header_state_b64": self.plan_header_state_b64,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CoverSheetWorkspaceState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            plan_header_state_b64=_coerce_optional_str(
                data.get("plan_header_state_b64")
            ),
        )


@dataclass
class DetachedWindowState:
    open: bool = False
    geometry_b64: Optional[str] = None
    is_maximized: bool = False
    is_fullscreen: bool = False

    def to_dict(self) -> dict:
        return {
            "open": self.open,
            "geometry_b64": self.geometry_b64,
            "is_maximized": self.is_maximized,
            "is_fullscreen": self.is_fullscreen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DetachedWindowState:
        if not isinstance(data, dict):
            return cls()
        if not data:
            return cls()
        return cls(
            open=_coerce_bool(data.get("open"), False),
            geometry_b64=_coerce_optional_str(data.get("geometry_b64")),
            is_maximized=_coerce_bool(data.get("is_maximized"), False),
            is_fullscreen=_coerce_bool(data.get("is_fullscreen"), False),
        )


@dataclass
class DetachedWindowsState:
    mesh_view: DetachedWindowState = field(default_factory=DetachedWindowState)
    annotation_view: DetachedWindowState = field(default_factory=DetachedWindowState)
    view_window: DetachedWindowState = field(default_factory=DetachedWindowState)

    def to_dict(self) -> dict:
        return {
            "mesh_view": self.mesh_view.to_dict(),
            "annotation_view": self.annotation_view.to_dict(),
            "view_window": self.view_window.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> DetachedWindowsState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            mesh_view=DetachedWindowState.from_dict(data.get("mesh_view", {})),
            annotation_view=DetachedWindowState.from_dict(
                data.get("annotation_view", {})
            ),
            view_window=DetachedWindowState.from_dict(data.get("view_window", {})),
        )


@dataclass
class ToolbarVisibilityState:
    main_toolbar_visible: bool = True
    view_toolbar_visible: bool = True
    plan_tools_toolbar_visible: bool = True

    def to_dict(self) -> dict:
        return {
            "main_toolbar_visible": self.main_toolbar_visible,
            "view_toolbar_visible": self.view_toolbar_visible,
            "plan_tools_toolbar_visible": self.plan_tools_toolbar_visible,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ToolbarVisibilityState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            main_toolbar_visible=_coerce_bool(
                data.get("main_toolbar_visible"),
                True,
            ),
            view_toolbar_visible=_coerce_bool(
                data.get("view_toolbar_visible"),
                True,
            ),
            plan_tools_toolbar_visible=_coerce_bool(
                data.get("plan_tools_toolbar_visible"),
                True,
            ),
        )


@dataclass
class WorkspaceState:
    CURRENT_SCHEMA_VERSION: ClassVar[int] = 1
    schema_version: int = CURRENT_SCHEMA_VERSION
    main_window: MainWindowWorkspaceState = field(
        default_factory=MainWindowWorkspaceState
    )
    takeoff_workspace: TakeoffWorkspaceState = field(
        default_factory=TakeoffWorkspaceState
    )
    project_workspace: ProjectWorkspaceState = field(
        default_factory=ProjectWorkspaceState
    )
    cover_sheet: CoverSheetWorkspaceState = field(
        default_factory=CoverSheetWorkspaceState
    )
    toolbar_visibility: ToolbarVisibilityState = field(
        default_factory=ToolbarVisibilityState
    )
    detached_windows: DetachedWindowsState = field(default_factory=DetachedWindowsState)

    def to_dict(self) -> dict:
        return {
            WORKSPACE_KEY_SCHEMA_VERSION: self.CURRENT_SCHEMA_VERSION,
            WORKSPACE_KEY_MAIN_WINDOW: self.main_window.to_dict(),
            WORKSPACE_KEY_TAKEOFF_WORKSPACE: self.takeoff_workspace.to_dict(),
            WORKSPACE_KEY_PROJECT_WORKSPACE: self.project_workspace.to_dict(),
            WORKSPACE_KEY_COVER_SHEET: self.cover_sheet.to_dict(),
            WORKSPACE_KEY_TOOLBAR_VISIBILITY: self.toolbar_visibility.to_dict(),
            WORKSPACE_KEY_DETACHED_WINDOWS: self.detached_windows.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkspaceState:
        if not isinstance(data, dict):
            return cls()
        raw_schema = data.get(WORKSPACE_KEY_SCHEMA_VERSION, cls.CURRENT_SCHEMA_VERSION)
        try:
            schema_version = max(1, int(raw_schema))
        except (TypeError, ValueError):
            schema_version = cls.CURRENT_SCHEMA_VERSION
        return cls(
            schema_version=schema_version,
            main_window=MainWindowWorkspaceState.from_dict(
                data.get(WORKSPACE_KEY_MAIN_WINDOW, {})
            ),
            takeoff_workspace=TakeoffWorkspaceState.from_dict(
                data.get(WORKSPACE_KEY_TAKEOFF_WORKSPACE, {})
            ),
            project_workspace=ProjectWorkspaceState.from_dict(
                data.get(WORKSPACE_KEY_PROJECT_WORKSPACE, {})
            ),
            cover_sheet=CoverSheetWorkspaceState.from_dict(
                data.get(WORKSPACE_KEY_COVER_SHEET, {})
            ),
            toolbar_visibility=ToolbarVisibilityState.from_dict(
                data.get(WORKSPACE_KEY_TOOLBAR_VISIBILITY, {})
            ),
            detached_windows=DetachedWindowsState.from_dict(
                data.get(WORKSPACE_KEY_DETACHED_WINDOWS, {})
            ),
        )
