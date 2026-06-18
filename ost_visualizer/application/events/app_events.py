from dataclasses import dataclass, field
from typing import Any, List, Optional
from ..dtos.mesh_geometry_dto import MeshGeometry


@dataclass
class FileOpenedEvent:
    file_path: str = ""


@dataclass
class DatabaseRefreshedEvent:
    file_path: str = ""


@dataclass
class TakeoffsChangedEvent:
    page_uid: str = ""
    takeoff_uids: list = field(default_factory=list)


@dataclass
class AnnotationsChangedEvent:
    page_uid: str = ""
    annotation_uids: list = field(default_factory=list)
    annotation_types: list = field(default_factory=list)


@dataclass
class FileUnloadedEvent:
    file_path: str = ""
    active_context_removed: bool = True


@dataclass
class FileSelectedEvent:
    file_path: Optional[str] = None
    project_uid: Optional[str] = None
    is_database_root: bool = False


@dataclass
class AppConfigUpdatedEvent:
    setting: str
    value: Any


@dataclass
class NativeSceneUpdatedEvent:
    geometries: List[MeshGeometry]
    bounds: Optional[tuple] = None


@dataclass
class LayerVisibilityChangedEvent:
    file_path: str = ""
    bid_uid: str = ""
    layer_uid: str = ""
    show: bool = True
    image_layer: bool = False
    all_layers: bool = False


@dataclass
class LicenseStatusChangedEvent:
    has_license: bool


@dataclass
class LicenseExpiredEvent:
    message: Optional[str] = None


@dataclass
class HotlinkClickedEvent:
    hotlink_uid: str
    bid_page_uid: str
    target_view_uid: Optional[str] = None
    position_x: float = 0.0
    position_y: float = 0.0


@dataclass
class NamedViewRenamedEvent:
    named_view_uid: str
    name: str


@dataclass
class NamedViewCreatedEvent:
    named_view_uid: str
    page_uid: str
    name: str


@dataclass
class NamedViewDeletedEvent:
    named_view_uids: list = field(default_factory=list)


@dataclass
class OstStatusChangedEvent:
    active: bool = False


class AppEvents:
    FILE_OPENED = FileOpenedEvent
    DATABASE_REFRESHED = DatabaseRefreshedEvent
    TAKEOFFS_CHANGED = TakeoffsChangedEvent
    ANNOTATIONS_CHANGED = AnnotationsChangedEvent
    FILE_UNLOADED = FileUnloadedEvent
    FILE_SELECTED = FileSelectedEvent
    APP_CONFIG_UPDATED = AppConfigUpdatedEvent
    NATIVE_SCENE_UPDATED = NativeSceneUpdatedEvent
    LAYER_VISIBILITY_CHANGED = LayerVisibilityChangedEvent
    LICENSE_STATUS_CHANGED = LicenseStatusChangedEvent
    LICENSE_EXPIRED = LicenseExpiredEvent
    HOTLINK_CLICKED = HotlinkClickedEvent
    NAMED_VIEW_RENAMED = NamedViewRenamedEvent
    NAMED_VIEW_CREATED = NamedViewCreatedEvent
    NAMED_VIEW_DELETED = NamedViewDeletedEvent
    OST_STATUS_CHANGED = OstStatusChangedEvent
