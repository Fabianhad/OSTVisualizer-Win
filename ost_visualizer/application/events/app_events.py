from dataclasses import dataclass, field
from typing import Any, Optional


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
class FileUnloadedEvent:
    file_path: str = ""
    active_context_removed: bool = True


@dataclass
class FileSelectedEvent:
    file_path: Optional[str] = None
    project_uid: Optional[str] = None
    is_database_root: bool = False


@dataclass
class PreferencesUpdatedEvent:
    setting: str
    value: Any


@dataclass
class NativeSceneUpdatedEvent:
    geometries: list
    bounds: Optional[tuple] = None


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
class OstStatusChangedEvent:
    active: bool = False


class AppEvents:
    FILE_OPENED = FileOpenedEvent
    DATABASE_REFRESHED = DatabaseRefreshedEvent
    TAKEOFFS_CHANGED = TakeoffsChangedEvent
    FILE_UNLOADED = FileUnloadedEvent
    FILE_SELECTED = FileSelectedEvent
    PREFERENCES_UPDATED = PreferencesUpdatedEvent
    NATIVE_SCENE_UPDATED = NativeSceneUpdatedEvent
    LICENSE_STATUS_CHANGED = LicenseStatusChangedEvent
    LICENSE_EXPIRED = LicenseExpiredEvent
    HOTLINK_CLICKED = HotlinkClickedEvent
    OST_STATUS_CHANGED = OstStatusChangedEvent
