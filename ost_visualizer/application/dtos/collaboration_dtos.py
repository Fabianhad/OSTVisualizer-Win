from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Generic, Optional, TypeVar
from ...domain.entities.area import BidArea
from ...domain.entities.condition import Condition
from ...domain.entities.condition_folder import BidConditionFolder
from ...domain.entities.file_results import BidLoadResult
from ...domain.entities.hierarchy_data import HierarchyFileEntry

CONDITION_RESOURCE_TYPES = frozenset(
    {"condition", "condition_folder", "conditions_collection"}
)
AREA_RESOURCE_TYPES = frozenset({"area", "areas_collection"})
BID_CONTENT_FAMILY_BY_RESOURCE_TYPE = MappingProxyType(
    {
        "takeoff": "takeoffs",
        "takeoffs_collection": "takeoffs",
        "annotation": "annotations",
        "annotations_collection": "annotations",
        "page": "pages",
        "pages_collection": "pages",
        "layer": "layers",
        "layers_collection": "layers",
    }
)
BID_CONTENT_RESOURCE_TYPES = frozenset(BID_CONTENT_FAMILY_BY_RESOURCE_TYPE)
HIERARCHY_RESOURCE_TYPES = frozenset(
    {"database", "project", "project_bids", "bid", "folder", "folders_collection"}
)
SUPPORTED_REMOTE_RESOURCE_TYPES = (
    CONDITION_RESOURCE_TYPES
    | AREA_RESOURCE_TYPES
    | BID_CONTENT_RESOURCE_TYPES
    | HIERARCHY_RESOURCE_TYPES
)
COLLABORATION_STALE_SECONDS = 45
COLLABORATION_LOCK_SECONDS = 45


class PresenceMode(str, Enum):
    VIEWING = "viewing"
    EDITING = "editing"


class ChangeOperation(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"
    REORDER = "reorder"
    BULK_REFRESH = "bulk_refresh"


class SynchronizationState(str, Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CATCHING_UP = "catching_up"
    HEALTHY = "healthy"
    DISCONNECTED = "disconnected"
    CREDENTIAL_REQUIRED = "credential_required"
    READ_ONLY = "read_only"
    CONFLICTED = "conflicted"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, order=True)
class ResourceRef:
    resource_type: str
    resource_id: str
    bid_uid: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.resource_type or len(self.resource_type) > 64:
            raise ValueError("Resource type must contain 1 to 64 characters")
        if not self.resource_id or len(self.resource_id) > 128:
            raise ValueError("Resource ID must contain 1 to 128 characters")


@dataclass(frozen=True)
class ConcurrencyToken:
    value: bytes

    def __post_init__(self) -> None:
        if len(self.value) != 8:
            raise ValueError("SQL Server rowversion tokens must contain 8 bytes")

    @classmethod
    def from_database(cls, value: object) -> "ConcurrencyToken":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise ValueError("SQL Server returned an invalid rowversion token")
        return cls(bytes(value))

    def __str__(self) -> str:
        return self.value.hex()


@dataclass(frozen=True)
class ExpectedResourceVersion:
    resource: ResourceRef
    expected: ConcurrencyToken


@dataclass(frozen=True)
class DatabaseSession:
    database_id: str
    session_id: str
    last_acknowledged_sequence: int = 0


@dataclass(frozen=True)
class PresenceSnapshot:
    database_id: str
    session_id: str
    display_name: str
    application_version: str
    bid_uid: Optional[int]
    page_uid: Optional[int]
    mode: PresenceMode


@dataclass(frozen=True)
class ResourceLock:
    database_id: str
    resource: ResourceRef
    lock_token: str


@dataclass(frozen=True)
class DatabaseChange:
    sequence: int
    transaction_id: str
    source_session_id: Optional[str]
    resource: ResourceRef
    operation: ChangeOperation
    resulting_version: Optional[ConcurrencyToken] = None
    changed_fields: tuple[str, ...] = ()
    payload: str = ""


@dataclass(frozen=True)
class DatabaseChangeBatch:
    database_id: str
    feed_epoch: str
    oldest_available_sequence: int
    high_water_sequence: int
    changes: tuple[DatabaseChange, ...] = ()


@dataclass(frozen=True)
class HydratedDatabaseChangeBatch:
    batch: DatabaseChangeBatch
    conditions_by_bid: dict[int, dict[str, Condition]] = field(default_factory=dict)
    condition_folders_by_bid: dict[int, dict[str, BidConditionFolder]] = field(
        default_factory=dict
    )
    areas_by_bid: dict[int, tuple[BidArea, ...]] = field(default_factory=dict)
    bid_data_by_bid: dict[int, BidLoadResult] = field(default_factory=dict)
    hierarchy_file: Optional[HierarchyFileEntry] = None


@dataclass(frozen=True)
class SynchronizationConflict:
    database_id: str
    resource: ResourceRef
    reason: str
    expected: Optional[ConcurrencyToken] = None
    actual: Optional[ConcurrencyToken] = None
    lock_owner: str = ""


@dataclass(frozen=True)
class DatabaseMutationRequest:
    database_id: str
    session_id: str
    resources: tuple[ResourceRef, ...] = ()
    expected_versions: tuple[ExpectedResourceVersion, ...] = ()
    required_lock_tokens: tuple[str, ...] = ()
    block_bid_child_locks: bool = False
    block_bid_active_editors: bool = False


T = TypeVar("T")


@dataclass(frozen=True)
class DatabaseMutationResult(Generic[T]):
    success: bool
    value: Optional[T] = None
    resulting_versions: dict[ResourceRef, ConcurrencyToken] = field(
        default_factory=dict
    )
    conflict: Optional[SynchronizationConflict] = None
    error_message: str = ""


@dataclass(frozen=True)
class CollaborationStatus:
    database_id: str
    state: SynchronizationState
    message: str = ""
    locked_resources: frozenset[ResourceRef] = frozenset()
    conflicted_resources: frozenset[ResourceRef] = frozenset()
