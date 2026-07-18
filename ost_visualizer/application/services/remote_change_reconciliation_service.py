from __future__ import annotations
from ...domain.entities.identity_refs import BidRef
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.collaboration_dtos import (
    BID_CONTENT_FAMILY_BY_RESOURCE_TYPE,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
    HydratedDatabaseChangeBatch,
)
from ..events.app_events import AppEvents
from .database_concurrency_token_service import DatabaseConcurrencyTokenService


class RemoteChangeReconciliationService:
    def __init__(
        self,
        project_data: ProjectDataService,
        event_bus,
        concurrency_tokens: DatabaseConcurrencyTokenService,
    ) -> None:
        self._project_data = project_data
        self._event_bus = event_bus
        self._concurrency_tokens = concurrency_tokens

    def apply(self, hydrated: HydratedDatabaseChangeBatch) -> bool:
        batch = hydrated.batch
        conflicts = self._concurrency_tokens.apply_remote_changes(
            batch.database_id, batch.changes
        )
        if conflicts:
            for resource in conflicts:
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
                )
            return False
        if hydrated.hierarchy_file is not None:
            self._project_data.replace_database_hierarchy(hydrated.hierarchy_file)
            self._event_bus.publish(
                AppEvents.REMOTE_HIERARCHY_CHANGED,
                database_id=batch.database_id,
            )
        active_ref = self._project_data.get_current_bid_ref()
        if active_ref is None or active_ref.file_path != batch.database_id:
            return True
        bid_uid = int(active_ref.bid_uid)
        active_changes = tuple(
            change
            for change in batch.changes
            if change.resource.bid_uid in {None, bid_uid}
        )
        if any(
            change.resource.resource_type not in SUPPORTED_REMOTE_RESOURCE_TYPES
            for change in active_changes
        ):
            return False
        conditions = hydrated.conditions_by_bid.get(bid_uid)
        folders = hydrated.condition_folders_by_bid.get(bid_uid)
        if conditions is not None and folders is not None:
            if not self._project_data.replace_condition_family(
                BidRef(batch.database_id, str(bid_uid)), conditions, folders
            ):
                return False
            self._event_bus.publish(
                AppEvents.REMOTE_CONDITIONS_CHANGED,
                database_id=batch.database_id,
                bid_uid=str(bid_uid),
                condition_uids=sorted(conditions),
            )
        areas = hydrated.areas_by_bid.get(bid_uid)
        if areas is not None:
            if not self._project_data.replace_bid_areas(
                BidRef(batch.database_id, str(bid_uid)), areas
            ):
                return False
            self._event_bus.publish(
                AppEvents.REMOTE_AREAS_CHANGED,
                database_id=batch.database_id,
                bid_uid=str(bid_uid),
                area_uids=sorted(str(area.uid) for area in areas),
            )
        bid_data = hydrated.bid_data_by_bid.get(bid_uid)
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
                                in {"takeoff", "annotation", "page", "layer"}
                            }
                        )
                        for family in families
                    },
                )
        return True
