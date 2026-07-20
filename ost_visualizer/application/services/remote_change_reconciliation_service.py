from __future__ import annotations
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.takeoff import Takeoff, find_takeoff_parent_cycle_uids
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.collaboration_resource_catalog import (
    AREA_RESOURCE_TYPES,
    BID_CONTENT_ENTITY_RESOURCE_TYPES,
    BID_CONTENT_FAMILY_BY_RESOURCE_TYPE,
    CONDITION_RESOURCE_TYPES,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
)
from ..dtos.collaboration_dtos import (
    HydratedDatabaseChangeBatch,
    ReconciliationFailureKind,
)
from ..events.app_events import AppEvents
from ..dtos.remote_projection_dtos import RemoteProjectionBarrier
from .database_concurrency_token_service import DatabaseConcurrencyTokenService
from .conflict_resolution_service import ConflictResolutionService
from .local_draft_registry import LocalDraftRegistry


class RemoteChangeReconciliationService:
    def __init__(
        self,
        project_data: ProjectDataService,
        event_bus,
        concurrency_tokens: DatabaseConcurrencyTokenService,
        drafts: LocalDraftRegistry,
        conflict_resolution: ConflictResolutionService,
    ) -> None:
        self._project_data = project_data
        self._event_bus = event_bus
        self._concurrency_tokens = concurrency_tokens
        self._drafts = drafts
        self._conflict_resolution = conflict_resolution
        self._last_failure_kind: ReconciliationFailureKind | None = None

    @property
    def last_failure_kind(self) -> ReconciliationFailureKind | None:
        return self._last_failure_kind

    def apply(
        self,
        hydrated: HydratedDatabaseChangeBatch,
        projection_barrier: RemoteProjectionBarrier | None = None,
    ) -> bool:
        self._last_failure_kind = None
        batch = hydrated.batch
        conflicts = self._drafts.conflicts_for_changes(batch.database_id, batch.changes)
        if conflicts:
            for conflict in conflicts:
                resource = conflict.changed_resource
                plan = self._conflict_resolution.plan(conflict)
                self._event_bus.publish(
                    AppEvents.SYNCHRONIZATION_CONFLICT,
                    database_id=batch.database_id,
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    bid_uid=str(resource.bid_uid or ""),
                    message=(
                        "This item changed in another session while it was being edited. "
                        "Reload it before saving again."
                    ),
                    blocks_database=False,
                    draft_id=plan.draft_id,
                    allowed_actions=[action.value for action in plan.actions],
                )
            return False
        if any(
            change.resource.resource_type not in SUPPORTED_REMOTE_RESOURCE_TYPES
            for change in batch.changes
        ):
            self._last_failure_kind = ReconciliationFailureKind.MALFORMED_PAYLOAD
            return False
        active_ref = self._project_data.get_current_bid_ref()
        if not self._is_complete_for_active_bid(hydrated, active_ref):
            self._last_failure_kind = ReconciliationFailureKind.MALFORMED_PAYLOAD
            return False
        if active_ref is None or active_ref.file_path != batch.database_id:
            if hydrated.hierarchy_file is not None:
                self._project_data.replace_database_hierarchy(
                    hydrated.hierarchy_file,
                    hydrated.cdn_types,
                )
            self._concurrency_tokens.apply_remote_changes(
                batch.database_id, batch.changes
            )
            if hydrated.hierarchy_file is not None:
                self._event_bus.publish(
                    AppEvents.REMOTE_HIERARCHY_CHANGED,
                    database_id=batch.database_id,
                    defer_plan_projection=projection_barrier is not None,
                )
            return True
        bid_uid = int(active_ref.bid_uid)
        active_changes = tuple(
            change
            for change in batch.changes
            if change.resource.bid_uid in {None, bid_uid}
        )
        conditions = hydrated.conditions_by_bid.get(bid_uid)
        folders = hydrated.condition_folders_by_bid.get(bid_uid)
        if conditions is not None and folders is not None:
            if not self._project_data.replace_condition_family(
                BidRef(batch.database_id, str(bid_uid)), conditions, folders
            ):
                return False
        areas = hydrated.areas_by_bid.get(bid_uid)
        if areas is not None:
            if not self._project_data.replace_bid_areas(
                BidRef(batch.database_id, str(bid_uid)), areas
            ):
                return False
        bid_data = hydrated.bid_data_by_bid.get(bid_uid)
        families = set()
        if bid_data is not None:
            families = {
                BID_CONTENT_FAMILY_BY_RESOURCE_TYPE[change.resource.resource_type]
                for change in active_changes
                if change.resource.resource_type in BID_CONTENT_FAMILY_BY_RESOURCE_TYPE
            }
            if families and not self._project_data.replace_remote_bid_families(
                BidRef(batch.database_id, str(bid_uid)), bid_data, families
            ):
                return False
        if hydrated.hierarchy_file is not None:
            self._project_data.replace_database_hierarchy(
                hydrated.hierarchy_file,
                hydrated.cdn_types,
            )
        self._concurrency_tokens.apply_remote_changes(batch.database_id, batch.changes)
        if hydrated.hierarchy_file is not None:
            self._event_bus.publish(
                AppEvents.REMOTE_HIERARCHY_CHANGED,
                database_id=batch.database_id,
                defer_plan_projection=projection_barrier is not None,
            )
        if conditions is not None and folders is not None:
            self._event_bus.publish(
                AppEvents.REMOTE_CONDITIONS_CHANGED,
                database_id=batch.database_id,
                bid_uid=str(bid_uid),
                condition_uids=sorted(conditions),
                defer_plan_projection=projection_barrier is not None,
            )
        if areas is not None:
            self._event_bus.publish(
                AppEvents.REMOTE_AREAS_CHANGED,
                database_id=batch.database_id,
                bid_uid=str(bid_uid),
                area_uids=sorted(str(area.uid) for area in areas),
                defer_plan_projection=projection_barrier is not None,
            )
        if families:
            self._event_bus.publish(
                AppEvents.REMOTE_BID_CONTENT_CHANGED,
                database_id=batch.database_id,
                bid_uid=str(bid_uid),
                families=sorted(families),
                resource_uids_by_family={
                    family: sorted(
                        {
                            change.resource.resource_id
                            for change in active_changes
                            if BID_CONTENT_FAMILY_BY_RESOURCE_TYPE.get(
                                change.resource.resource_type
                            )
                            == family
                            and change.resource.resource_type
                            in BID_CONTENT_ENTITY_RESOURCE_TYPES
                        }
                    )
                    for family in families
                },
                defer_plan_projection=projection_barrier is not None,
            )
        plan_projection_required = (
            (conditions is not None and folders is not None)
            or areas is not None
            or bool(families)
        )
        if projection_barrier is not None and plan_projection_required:
            projected_families = tuple(sorted(families))
            resource_uids_by_family = {
                family: tuple(
                    sorted(
                        {
                            change.resource.resource_id
                            for change in active_changes
                            if BID_CONTENT_FAMILY_BY_RESOURCE_TYPE.get(
                                change.resource.resource_type
                            )
                            == family
                            and change.resource.resource_type
                            in BID_CONTENT_ENTITY_RESOURCE_TYPES
                        }
                    )
                )
                for family in projected_families
            }
            self._event_bus.publish(
                AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
                database_id=batch.database_id,
                bid_uid=str(bid_uid),
                runtime_generation=projection_barrier.runtime_generation,
                families=projected_families,
                condition_uids=tuple(sorted(conditions or ())),
                resource_uids_by_family=resource_uids_by_family,
                barrier=projection_barrier,
            )
        return True

    def _is_complete_for_active_bid(self, hydrated, active_ref) -> bool:
        if active_ref is None or active_ref.file_path != hydrated.batch.database_id:
            return True
        bid_uid = int(active_ref.bid_uid)
        active_changes = tuple(
            change
            for change in hydrated.batch.changes
            if change.resource.bid_uid in {None, bid_uid}
        )
        resource_types = {change.resource.resource_type for change in active_changes}
        if resource_types.intersection(CONDITION_RESOURCE_TYPES):
            if (
                bid_uid not in hydrated.conditions_by_bid
                or bid_uid not in hydrated.condition_folders_by_bid
            ):
                return False
        if resource_types.intersection(AREA_RESOURCE_TYPES):
            if bid_uid not in hydrated.areas_by_bid:
                return False
        if resource_types.intersection(BID_CONTENT_FAMILY_BY_RESOURCE_TYPE):
            if bid_uid not in hydrated.bid_data_by_bid:
                return False
            bid_data = hydrated.bid_data_by_bid[bid_uid]
            if any(
                not isinstance(takeoff, Takeoff) for takeoff in bid_data.bid_takeoffs
            ):
                return False
            takeoff_uids = [takeoff.uid for takeoff in bid_data.bid_takeoffs]
            if any(
                not takeoff.has_valid_contract() for takeoff in bid_data.bid_takeoffs
            ) or len(set(takeoff_uids)) != len(takeoff_uids):
                return False
            known_takeoffs = set(takeoff_uids)
            known_pages = set(bid_data.pages)
            available_conditions = hydrated.conditions_by_bid.get(bid_uid)
            if available_conditions is None:
                available_conditions = self._project_data.get_bid_conditions()
            known_conditions = set(available_conditions)
            parent_uid_by_takeoff_uid = {}
            for takeoff in bid_data.bid_takeoffs:
                if takeoff.page_uid not in known_pages:
                    return False
                if takeoff.condition_uid not in known_conditions:
                    return False
                if takeoff.is_hole and takeoff.parent_uid not in known_takeoffs:
                    return False
                parent_uid_by_takeoff_uid[takeoff.uid] = takeoff.parent_uid
            if find_takeoff_parent_cycle_uids(parent_uid_by_takeoff_uid):
                return False
        return True
