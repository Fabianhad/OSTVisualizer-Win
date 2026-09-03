from __future__ import annotations
import hashlib
import json
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from functools import total_ordering
from typing import Any, Generic, Optional, TypeVar
from .collaboration_resource_catalog import (
    parse_annotation_resource_id,
    resource_definition,
)
from .insert_annotation_spec_dto import InsertAnnotationSpec
from .insert_takeoff_spec_dto import InsertTakeoffSpec
from ...domain.entities.area import BidArea
from ...domain.entities.cdn_type import CdnType
from ...domain.entities.condition import Condition
from ...domain.entities.condition_folder import BidConditionFolder
from ...domain.entities.cover_sheet import CoverSheetData, JobStatus
from ...domain.entities.employee import Employee, PayClass
from ...domain.entities.file_results import BidLoadResult
from ...domain.entities.hierarchy_data import HierarchyFileEntry
from ...domain.entities.layer import BidLayer

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


class CollaborationMutationType(str, Enum):
    TAKEOFF_PLACEMENT = "takeoff_placement"
    PLAN_ITEMS_DELETE = "plan_items_delete"
    PLAN_GEOMETRY = "plan_geometry"
    TAKEOFF_PROPERTIES = "takeoff_properties"
    ANNOTATION_UPDATE = "annotation_update"
    PLAN_ITEMS_PASTE = "plan_items_paste"
    PAGE_SETTINGS = "page_settings"
    PROJECT_WRITE = "project_write"
    PROJECT_IMPORT = "project_import"


class MutationOutcomeStatus(str, Enum):
    COMMITTED = "committed"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    FAILED_BEFORE_COMMIT = "failed_before_commit"
    COMMITTED_PROJECTION_FAILED = "committed_projection_failed"
    COMMIT_STATUS_UNKNOWN = "commit_status_unknown"
    CANCELLED_BEFORE_START = "cancelled_before_start"


class PendingMutationState(str, Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    PROJECTING = "projecting"
    RECOVERING = "recovering"
    UNCERTAIN = "uncertain"


class ChangeSourceKind(str, Enum):
    OST_VISUALIZER = "ost_visualizer"
    EXTERNAL = "external"


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


class ReconciliationFailureKind(str, Enum):
    MALFORMED_PAYLOAD = "malformed_payload"


@dataclass(frozen=True, kw_only=True)
class ReconciliationResult:
    applied: bool
    failure_kind: Optional[ReconciliationFailureKind] = None

    def __post_init__(self) -> None:
        if self.applied and self.failure_kind is not None:
            raise ValueError("A successful reconciliation cannot carry a failure kind")


class SynchronizationConflictKind(str, Enum):
    OPTIMISTIC_CONCURRENCY = "optimistic_concurrency"
    LEASE = "lease"
    SESSION = "session"


def session_identities_equal(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return False
    try:
        return uuid.UUID(str(left)) == uuid.UUID(str(right))
    except ValueError:
        return False


class CollaborationShutdownState(str, Enum):
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    DRAINING = "draining"
    CLOSED = "closed"
    CLEANUP_FAILED = "cleanup_failed"


@total_ordering
@dataclass(frozen=True)
class ResourceRef:
    resource_type: str
    resource_id: str
    bid_uid: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.resource_type or len(self.resource_type) > 64:
            raise ValueError("Resource type must contain 1 to 64 characters")
        if not self.resource_id or len(self.resource_id) > 128:
            raise ValueError("Resource ID must contain 1 to 128 characters")
        resource_definition(self.resource_type)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ResourceRef):
            return NotImplemented
        return (
            self.resource_type,
            self.resource_id,
            self.bid_uid is not None,
            self.bid_uid or 0,
        ) < (
            other.resource_type,
            other.resource_id,
            other.bid_uid is not None,
            other.bid_uid or 0,
        )

    @property
    def lease_identity(self) -> tuple[str, str]:
        return self.resource_type, self.resource_id


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
    last_acknowledged_version: int = 0


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
class EditLeaseRequest:
    database_id: str
    draft_id: str
    operation_id: str
    owning_surface: str
    resources: tuple[ResourceRef, ...]
    dependency_resources: tuple[ResourceRef, ...] = ()


@dataclass(frozen=True)
class EditLeaseHandle:
    database_id: str
    draft_id: str
    runtime_generation: int
    operation_id: str
    owning_surface: str
    resources: tuple[ResourceRef, ...]
    dependency_resources: tuple[ResourceRef, ...] = ()
    locks: tuple[ResourceLock, ...] = ()


@dataclass(frozen=True)
class EditLeaseLoss:
    database_id: str
    draft_id: str
    runtime_generation: int
    operation_id: str
    owning_surface: str
    resources: tuple[ResourceRef, ...]
    reason: str


@dataclass(frozen=True)
class EditLeaseResult:
    granted: bool
    message: str = ""
    handle: Optional[EditLeaseHandle] = None

    def __post_init__(self) -> None:
        if self.granted != (self.handle is not None):
            raise ValueError(
                "A granted edit lease requires its handle, and a denial cannot "
                "carry a handle."
            )


def _canonical_mutation_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            item.name: _canonical_mutation_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, dict):
        return {
            str(key): _canonical_mutation_value(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_mutation_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_canonical_mutation_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ),
        )
    raise TypeError(
        f"Unsupported collaboration mutation payload value: {type(value).__name__}"
    )


def canonical_mutation_request_hash(payload: object) -> str:
    encoded = json.dumps(
        _canonical_mutation_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, kw_only=True)
class AuthoritativeMutationResult:
    created_resource_ids: tuple[str, ...] = ()
    created_uid_maps: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    updated_resources: tuple[ResourceRef, ...] = ()
    deleted_resources: tuple[ResourceRef, ...] = ()
    affected_page_uids: tuple[str, ...] = ()
    affected_condition_uids: tuple[str, ...] = ()
    affected_families: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PlanItemsDeletePayload:
    takeoff_uids: tuple[str, ...] = ()
    annotations: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        takeoff_uids = tuple(
            dict.fromkeys(str(uid) for uid in self.takeoff_uids if uid)
        )
        annotations = tuple(
            dict.fromkeys(
                (str(uid), str(annotation_type))
                for uid, annotation_type in self.annotations
                if uid and annotation_type
            )
        )
        if not takeoff_uids and not annotations:
            raise ValueError("A plan-item deletion requires at least one item")
        object.__setattr__(self, "takeoff_uids", takeoff_uids)
        object.__setattr__(self, "annotations", annotations)


@dataclass(frozen=True, kw_only=True)
class PlanItemsPastePayload:
    source_bid_uid: str
    destination_bid_uid: str
    takeoff_source_uids: tuple[str, ...] = ()
    takeoff_specs: tuple[InsertTakeoffSpec, ...] = ()
    annotation_source_uids: tuple[str, ...] = ()
    annotation_specs: tuple[InsertAnnotationSpec, ...] = ()

    def __post_init__(self) -> None:
        if len(self.takeoff_source_uids) != len(self.takeoff_specs):
            raise ValueError("Paste takeoff sources and specifications must align")
        if len(self.annotation_source_uids) != len(self.annotation_specs):
            raise ValueError("Paste annotation sources and specifications must align")
        if not self.takeoff_specs and not self.annotation_specs:
            raise ValueError("A plan-item paste requires at least one item")
        if len(set(self.takeoff_source_uids)) != len(self.takeoff_source_uids):
            raise ValueError("Paste takeoff source identities must be unique")
        if len(set(self.annotation_source_uids)) != len(self.annotation_source_uids):
            raise ValueError("Paste annotation source identities must be unique")
        for source_uid, spec in zip(
            self.annotation_source_uids,
            self.annotation_specs,
        ):
            source_type, _source_uid = parse_annotation_resource_id(source_uid)
            if source_type != spec.annotation_type:
                raise ValueError(
                    "Paste annotation sources must use type-qualified identities"
                )


@dataclass(frozen=True, kw_only=True)
class PlanGeometryPayload:
    takeoff_positions: tuple[tuple[str, tuple[float, ...]], ...] = ()
    takeoff_rotations: tuple[tuple[str, float], ...] = ()
    annotation_positions: tuple[tuple[str, str, tuple[float, ...]], ...] = ()

    def __post_init__(self) -> None:
        if not (
            self.takeoff_positions
            or self.takeoff_rotations
            or self.annotation_positions
        ):
            raise ValueError("A geometry mutation requires at least one update")
        identities = [uid for uid, _position in self.takeoff_positions]
        identities.extend(uid for uid, _rotation in self.takeoff_rotations)
        if any(not uid for uid in identities):
            raise ValueError("Geometry mutation identities cannot be empty")


@dataclass(frozen=True, kw_only=True)
class PlanPropertyPayload:
    property_kind: str
    updates_json: str

    def __post_init__(self) -> None:
        if self.property_kind not in {
            "takeoff_text",
            "takeoff_area",
            "takeoff_condition",
            "takeoff_negative",
            "takeoff_curve",
            "annotation_text",
            "annotation_style",
        }:
            raise ValueError("Unsupported plan property mutation")
        try:
            updates = json.loads(self.updates_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("Plan property updates must be valid JSON") from exc
        if not isinstance(updates, list) or not updates:
            raise ValueError("Plan property updates must be a non-empty list")

    @classmethod
    def from_updates(cls, property_kind: str, updates: list) -> "PlanPropertyPayload":
        return cls(
            property_kind=property_kind,
            updates_json=json.dumps(
                updates,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )

    def decoded_updates(self) -> list:
        return json.loads(self.updates_json)


@dataclass(frozen=True, kw_only=True)
class PageSettingsPayload:
    setting_kind: str
    updates_json: str

    def __post_init__(self) -> None:
        if self.setting_kind not in {
            "scale",
            "show_mode",
            "overlay_image",
            "overlay_rect",
            "invert",
            "bitonal",
            "image_adjustments",
            "area",
            "name",
            "layer_show",
        }:
            raise ValueError("Unsupported page setting mutation")
        try:
            updates = json.loads(self.updates_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("Page setting updates must be valid JSON") from exc
        if not isinstance(updates, list) or not updates:
            raise ValueError("Page setting updates must be a non-empty list")

    @classmethod
    def from_updates(cls, setting_kind: str, updates: list) -> "PageSettingsPayload":
        return cls(
            setting_kind=setting_kind,
            updates_json=json.dumps(
                updates,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )

    def decoded_updates(self) -> list:
        return json.loads(self.updates_json)


@dataclass(frozen=True, kw_only=True)
class ProjectWritePayload:
    write_kind: str
    values_json: str

    def __post_init__(self) -> None:
        if self.write_kind not in {
            "create_condition",
            "create_condition_folder",
            "create_bid",
            "create_project",
            "delete_bids",
            "delete_condition_folders",
            "delete_conditions",
            "delete_pages",
            "delete_projects",
            "duplicate_bids",
            "duplicate_conditions",
            "insert_layer",
            "delete_layer",
            "delete_layers",
            "rename_condition_folder",
            "rename_project",
            "renumber_conditions",
            "swap_layers",
            "update_conditions",
            "update_bid_job_status",
            "move_bids",
            "rename_layer",
            "save_bid_areas",
            "save_condition_types",
            "save_cover_sheet",
            "save_default_layers",
            "save_employees",
            "save_job_statuses",
            "save_pay_classes",
        }:
            raise ValueError("Unsupported queued project write")
        try:
            values = json.loads(self.values_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("Project write values must be valid JSON") from exc
        if not isinstance(values, dict):
            raise ValueError("Project write values must be a JSON object")

    @classmethod
    def from_values(cls, write_kind: str, values: dict) -> "ProjectWritePayload":
        return cls(
            write_kind=write_kind,
            values_json=json.dumps(
                values,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )


@dataclass(frozen=True, kw_only=True)
class ProjectImportPayload:
    source_path: str
    source_kind: str
    source_size: int
    source_modified_ns: int
    target_project_uid: str = ""

    def __post_init__(self) -> None:
        if not self.source_path:
            raise ValueError("A project import requires a source path")
        if self.source_kind not in {"ost", "osp"}:
            raise ValueError("A project import source must be OST or OSP")
        if self.source_size < 0 or self.source_modified_ns < 0:
            raise ValueError("Project import file metadata cannot be negative")


@dataclass(frozen=True, kw_only=True)
class QueuedMutationRequest:
    database_id: str
    operation_id: str
    mutation_type: CollaborationMutationType
    owning_surface: str
    resources: tuple[ResourceRef, ...]
    dependency_resources: tuple[ResourceRef, ...] = ()
    bid_uid: Optional[int] = None
    page_uid: str = ""
    payload: object = None
    payload_format_version: int = 1
    lifecycle_critical: bool = True
    request_hash: str = field(init=False)
    edit_lease_handle: Optional[EditLeaseHandle] = None

    def __post_init__(self) -> None:
        try:
            operation_id = str(uuid.UUID(str(self.operation_id)))
        except ValueError as exc:
            raise ValueError("Queued mutation operation IDs must be UUIDs") from exc
        if not self.database_id:
            raise ValueError("A queued mutation requires a database ID")
        if not self.owning_surface:
            raise ValueError("A queued mutation requires an owning surface")
        if not self.resources:
            raise ValueError("A queued mutation requires at least one resource")
        if self.edit_lease_handle is not None:
            handle = self.edit_lease_handle
            if (
                handle.database_id != self.database_id
                or handle.owning_surface != self.owning_surface
                or not set(self.resources).issubset(handle.resources)
            ):
                raise ValueError(
                    "A queued mutation's edit lease must own its affected resources"
                )
        if self.payload_format_version != 1:
            raise ValueError("Only mutation payload format version 1 is supported")
        request_hash = canonical_mutation_request_hash(
            {
                "mutation_type": self.mutation_type.value,
                "payload_format_version": self.payload_format_version,
                "payload": self.payload,
            }
        )
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "resources", tuple(sorted(set(self.resources))))
        object.__setattr__(
            self,
            "dependency_resources",
            tuple(sorted(set(self.dependency_resources))),
        )
        object.__setattr__(self, "request_hash", request_hash)


@dataclass(frozen=True, kw_only=True)
class PendingMutation:
    request: QueuedMutationRequest
    state: PendingMutationState = PendingMutationState.QUEUED
    runtime_generation: int = 0
    message: str = ""


@dataclass(frozen=True, kw_only=True)
class PendingSqlOperationRecord:
    database_id: str
    operation_id: str
    mutation_type: CollaborationMutationType
    request_hash: str
    owning_surface: str
    resources: tuple[ResourceRef, ...]
    dependency_resources: tuple[ResourceRef, ...] = ()
    bid_uid: Optional[int] = None
    page_uid: str = ""
    state: PendingMutationState = PendingMutationState.QUEUED

    def __post_init__(self) -> None:
        try:
            operation_id = str(uuid.UUID(str(self.operation_id)))
        except ValueError as exc:
            raise ValueError("Pending SQL operation IDs must be UUIDs") from exc
        if not self.database_id or not self.owning_surface or not self.resources:
            raise ValueError("A pending SQL operation record is incomplete")
        if len(self.request_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.request_hash
        ):
            raise ValueError(
                "Pending SQL operation hashes must be lowercase SHA-256 hex"
            )
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "resources", tuple(sorted(set(self.resources))))
        object.__setattr__(
            self,
            "dependency_resources",
            tuple(sorted(set(self.dependency_resources))),
        )

    @classmethod
    def from_request(
        cls,
        request: QueuedMutationRequest,
        state: PendingMutationState = PendingMutationState.QUEUED,
    ) -> "PendingSqlOperationRecord":
        return cls(
            database_id=request.database_id,
            operation_id=request.operation_id,
            mutation_type=request.mutation_type,
            request_hash=request.request_hash,
            owning_surface=request.owning_surface,
            resources=request.resources,
            dependency_resources=request.dependency_resources,
            bid_uid=request.bid_uid,
            page_uid=request.page_uid,
            state=state,
        )


@dataclass(frozen=True, kw_only=True)
class MutationExecutionResult:
    outcome_status: MutationOutcomeStatus
    created_resource_ids: tuple[str, ...] = ()
    authoritative_result: Optional[AuthoritativeMutationResult] = None
    message: str = ""
    conflict: Optional[SynchronizationConflict] = None
    commit_attempted: bool = False
    consumed_lock_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.conflict is not None
            and self.outcome_status != MutationOutcomeStatus.CONFLICT
        ):
            raise ValueError("Only a conflict outcome may carry a conflict")
        if (
            self.outcome_status == MutationOutcomeStatus.COMMITTED
            and not self.commit_attempted
        ):
            object.__setattr__(self, "commit_attempted", True)


@dataclass(frozen=True, kw_only=True)
class QueuedMutationResult:
    database_id: str
    runtime_generation: int
    operation_id: str
    outcome_status: MutationOutcomeStatus
    created_resource_ids: tuple[str, ...] = ()
    authoritative_result: Optional[AuthoritativeMutationResult] = None
    message: str = ""
    conflict: Optional[SynchronizationConflict] = None
    commit_attempted: bool = False

    def __post_init__(self) -> None:
        try:
            operation_id = str(uuid.UUID(str(self.operation_id)))
        except ValueError as exc:
            raise ValueError("Queued mutation result IDs must be UUIDs") from exc
        if (
            self.conflict is not None
            and self.outcome_status != MutationOutcomeStatus.CONFLICT
        ):
            raise ValueError("Only a conflict outcome may carry a conflict")
        if (
            self.outcome_status == MutationOutcomeStatus.COMMITTED
            and not self.commit_attempted
        ):
            object.__setattr__(self, "commit_attempted", True)
        object.__setattr__(self, "operation_id", operation_id)


_QUEUED_TAKEOFF_PREVIEW_UID_PREFIX = "pending:takeoff-placement:"


def queued_takeoff_preview_uid(operation_id: str, index: int) -> str:
    return f"{_QUEUED_TAKEOFF_PREVIEW_UID_PREFIX}{operation_id}:{index}"


def is_queued_takeoff_preview_uid(uid: str) -> bool:
    return uid.startswith(_QUEUED_TAKEOFF_PREVIEW_UID_PREFIX)


@dataclass(frozen=True)
class DatabaseChange:
    sequence: int
    commit_version: int
    transaction_id: str
    source_session_id: Optional[str]
    resource: ResourceRef
    operation: ChangeOperation
    resulting_version: Optional[ConcurrencyToken] = None
    changed_fields: tuple[str, ...] = ()
    payload: str = ""
    source_kind: ChangeSourceKind = ChangeSourceKind.OST_VISUALIZER


@dataclass(frozen=True)
class DatabaseChangeBatch:
    database_id: str
    feed_epoch: str
    minimum_valid_version: int
    high_water_version: int
    delivered_through_version: int
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
    cdn_types: dict[str, CdnType] = field(default_factory=dict)
    default_layers: Optional[tuple[BidLayer, ...]] = None
    job_statuses: Optional[tuple[JobStatus, ...]] = None
    employees: Optional[tuple[Employee, ...]] = None
    pay_classes: Optional[tuple[PayClass, ...]] = None
    used_job_status_uids: Optional[frozenset[str]] = None
    used_employee_uids: Optional[frozenset[str]] = None
    cover_sheet_by_bid: dict[int, CoverSheetData] = field(default_factory=dict)
    page_delete_content_uids_by_bid: dict[int, frozenset[str]] = field(
        default_factory=dict
    )
    settings_defaults: Optional[dict] = None


@dataclass(frozen=True)
class DatabaseChangePollResult:
    observed_batch: DatabaseChangeBatch
    remote_batch: HydratedDatabaseChangeBatch

    def __post_init__(self) -> None:
        observed = self.observed_batch
        remote = self.remote_batch.batch
        if (
            observed.database_id,
            observed.feed_epoch,
            observed.minimum_valid_version,
            observed.high_water_version,
            observed.delivered_through_version,
        ) != (
            remote.database_id,
            remote.feed_epoch,
            remote.minimum_valid_version,
            remote.high_water_version,
            remote.delivered_through_version,
        ):
            raise ValueError("Observed and hydrated SQL change batches must match.")


@dataclass(frozen=True)
class SynchronizationConflict:
    database_id: str
    resource: ResourceRef
    reason: str
    expected: Optional[ConcurrencyToken] = None
    actual: Optional[ConcurrencyToken] = None
    kind: SynchronizationConflictKind = (
        SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY
    )


@dataclass(frozen=True)
class DatabaseMutationRequest:
    database_id: str
    session_id: str
    operation_id: str
    mutation_type: str
    request_hash: str
    result_format_version: int = 1
    resources: tuple[ResourceRef, ...] = ()
    expected_versions: tuple[ExpectedResourceVersion, ...] = ()
    required_lock_tokens: tuple[str, ...] = ()
    block_bid_child_locks: bool = False
    block_bid_active_editors: bool = False

    def __post_init__(self) -> None:
        try:
            operation_id = str(uuid.UUID(str(self.operation_id)))
        except ValueError as exc:
            raise ValueError("Database mutation operation IDs must be UUIDs") from exc
        try:
            mutation_type = CollaborationMutationType(str(self.mutation_type)).value
        except ValueError as exc:
            raise ValueError("Database mutation types must be canonical") from exc
        request_hash = self.request_hash
        if len(request_hash) != 64 or any(
            character not in "0123456789abcdef" for character in request_hash
        ):
            raise ValueError("Mutation request hashes must be lowercase SHA-256 hex")
        if self.result_format_version != 1:
            raise ValueError("Only mutation result format version 1 is supported")
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "mutation_type", mutation_type)
        object.__setattr__(self, "request_hash", request_hash)


T = TypeVar("T")


@dataclass(frozen=True)
class DatabaseMutationResult(Generic[T]):
    operation_id: str
    outcome_status: MutationOutcomeStatus
    value: Optional[T] = None
    resulting_versions: dict[ResourceRef, ConcurrencyToken] = field(
        default_factory=dict
    )
    conflict: Optional[SynchronizationConflict] = None
    commit_attempted: bool = False
    consumed_lock_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            operation_id = str(uuid.UUID(str(self.operation_id)))
        except ValueError as exc:
            raise ValueError("Database mutation result IDs must be UUIDs") from exc
        if (
            self.conflict is not None
            and self.outcome_status != MutationOutcomeStatus.CONFLICT
        ):
            raise ValueError("Only a conflict outcome may carry a conflict")
        if (
            self.outcome_status == MutationOutcomeStatus.COMMITTED
            and not self.commit_attempted
        ):
            object.__setattr__(self, "commit_attempted", True)
        object.__setattr__(self, "operation_id", operation_id)


@dataclass(frozen=True, kw_only=True)
class DurableOperationResult:
    database_id: str
    operation_id: str
    found: bool
    mutation_type: str = ""
    request_hash: str = ""
    result_format_version: int = 0
    result_payload: str = ""

    def __post_init__(self) -> None:
        try:
            normalized_operation_id = str(uuid.UUID(str(self.operation_id)))
        except ValueError as exc:
            raise ValueError("Durable operation IDs must be UUIDs") from exc
        object.__setattr__(self, "operation_id", normalized_operation_id)
        if self.found:
            try:
                CollaborationMutationType(self.mutation_type)
            except ValueError as exc:
                raise ValueError(
                    "A durable operation result has a noncanonical mutation type"
                ) from exc
            if len(self.request_hash) != 64 or any(
                character not in "0123456789abcdef" for character in self.request_hash
            ):
                raise ValueError(
                    "A durable operation result has an invalid request hash"
                )
            if self.result_format_version != 1 or not self.result_payload:
                raise ValueError("A durable operation result is incomplete")


@dataclass(frozen=True)
class CollaborationStatus:
    database_id: str
    state: SynchronizationState
    message: str = ""
    locked_resources: frozenset[ResourceRef] = frozenset()
    conflicted_resources: frozenset[ResourceRef] = frozenset()


@dataclass(frozen=True)
class CollaborationMetrics:
    database_id: str
    poll_count: int = 0
    poll_duration_seconds: float = 0.0
    transaction_count: int = 0
    change_row_count: int = 0
    reconciliation_count: int = 0
    reconciliation_duration_seconds: float = 0.0
    retention_gap_count: int = 0
    reconnect_count: int = 0


@dataclass(frozen=True)
class CollaborationPollingPolicy:
    selected_database_seconds: float = 1.0
    active_edit_seconds: float = 0.5
    inactive_database_seconds: float = 5.0
    heartbeat_seconds: float = 10.0
    jitter_ratio: float = 0.1
    maximum_batch_size: int = 500
    reconnect_backoff_seconds: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)
