from dataclasses import dataclass, field
from typing import Any, List, Optional
from ..dtos.collaboration_dtos import EditLeaseLoss
from ..dtos.mesh_geometry_dto import MeshGeometry, MeshSceneIdentity
from ..dtos.remote_projection_dtos import RemoteProjectionBarrier


@dataclass
class FileOpenedEvent:
    file_path: str = ""


@dataclass
class DatabaseRefreshedEvent:
    file_path: str = ""


@dataclass
class DatabaseCapabilitiesChangedEvent:
    file_path: str = ""


@dataclass
class RemoteConditionsChangedEvent:
    database_id: str = ""
    bid_uid: str = ""
    condition_uids: list = field(default_factory=list)
    defer_plan_projection: bool = False


@dataclass
class RemoteAreasChangedEvent:
    database_id: str = ""
    bid_uid: str = ""
    area_uids: list = field(default_factory=list)
    defer_plan_projection: bool = False


@dataclass
class RemoteBidContentChangedEvent:
    database_id: str = ""
    bid_uid: str = ""
    families: list = field(default_factory=list)
    resource_uids_by_family: dict = field(default_factory=dict)
    defer_plan_projection: bool = False
    local_completion: bool = False


@dataclass
class RemoteHierarchyChangedEvent:
    database_id: str = ""
    defer_plan_projection: bool = False


@dataclass
class RemoteMasterDataChangedEvent:
    database_id: str = ""
    families: list[str] = field(default_factory=list)


@dataclass
class RemotePlanProjectionRequestedEvent:
    database_id: str
    bid_uid: str
    runtime_generation: int
    families: tuple[str, ...]
    condition_uids: tuple[str, ...]
    resource_uids_by_family: dict[str, tuple[str, ...]]
    barrier: RemoteProjectionBarrier


@dataclass
class CollaborationStateChangedEvent:
    database_id: str = ""
    state: str = ""
    message: str = ""


@dataclass
class CollaborationMutationStateChangedEvent:
    database_id: str = ""
    operation_id: str = ""
    mutation_type: str = ""
    state: str = ""
    message: str = ""
    pending_count: int = 0


@dataclass
class PresenceChangedEvent:
    database_id: str = ""
    bid_uid: str = ""
    users: list = field(default_factory=list)


@dataclass
class SynchronizationConflictEvent:
    database_id: str = ""
    resource_type: str = ""
    resource_id: str = ""
    bid_uid: str = ""
    message: str = ""
    blocks_database: bool = True
    draft_id: str = ""
    allowed_actions: list[str] = field(default_factory=list)


@dataclass
class FullReconciliationRequiredEvent:
    database_id: str = ""
    reason: str = ""


@dataclass
class EditLeaseLostEvent:
    loss: EditLeaseLoss


@dataclass
class TakeoffsChangedEvent:
    page_uid: str = ""
    page_uids: list = field(default_factory=list)
    takeoff_uids: list = field(default_factory=list)
    condition_uids: list = field(default_factory=list)


@dataclass
class AnnotationsChangedEvent:
    page_uid: str = ""
    page_uids: list = field(default_factory=list)
    annotation_uids: list = field(default_factory=list)
    annotation_types: list = field(default_factory=list)


@dataclass
class PendingPlanMutationsChangedEvent:
    database_id: str
    takeoff_uids: list = field(default_factory=list)
    pending: bool = True


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
    scene_identity: MeshSceneIdentity
    scene_failed: bool


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
class OstStatusChangedEvent:
    active: bool = False


class AppEvents:
    FILE_OPENED = FileOpenedEvent
    DATABASE_REFRESHED = DatabaseRefreshedEvent
    DATABASE_CAPABILITIES_CHANGED = DatabaseCapabilitiesChangedEvent
    REMOTE_CONDITIONS_CHANGED = RemoteConditionsChangedEvent
    REMOTE_AREAS_CHANGED = RemoteAreasChangedEvent
    REMOTE_BID_CONTENT_CHANGED = RemoteBidContentChangedEvent
    REMOTE_HIERARCHY_CHANGED = RemoteHierarchyChangedEvent
    REMOTE_MASTER_DATA_CHANGED = RemoteMasterDataChangedEvent
    REMOTE_PLAN_PROJECTION_REQUESTED = RemotePlanProjectionRequestedEvent
    COLLABORATION_STATE_CHANGED = CollaborationStateChangedEvent
    COLLABORATION_MUTATION_STATE_CHANGED = CollaborationMutationStateChangedEvent
    PRESENCE_CHANGED = PresenceChangedEvent
    SYNCHRONIZATION_CONFLICT = SynchronizationConflictEvent
    FULL_RECONCILIATION_REQUIRED = FullReconciliationRequiredEvent
    EDIT_LEASE_LOST = EditLeaseLostEvent
    TAKEOFFS_CHANGED = TakeoffsChangedEvent
    ANNOTATIONS_CHANGED = AnnotationsChangedEvent
    PENDING_PLAN_MUTATIONS_CHANGED = PendingPlanMutationsChangedEvent
    FILE_UNLOADED = FileUnloadedEvent
    FILE_SELECTED = FileSelectedEvent
    APP_CONFIG_UPDATED = AppConfigUpdatedEvent
    NATIVE_SCENE_UPDATED = NativeSceneUpdatedEvent
    LAYER_VISIBILITY_CHANGED = LayerVisibilityChangedEvent
    LICENSE_STATUS_CHANGED = LicenseStatusChangedEvent
    LICENSE_EXPIRED = LicenseExpiredEvent
    HOTLINK_CLICKED = HotlinkClickedEvent
    OST_STATUS_CHANGED = OstStatusChangedEvent
