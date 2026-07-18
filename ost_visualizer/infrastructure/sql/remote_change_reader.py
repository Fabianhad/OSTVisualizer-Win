from __future__ import annotations
from typing import Optional
from ...application.dtos.collaboration_dtos import (
    AREA_RESOURCE_TYPES,
    BID_CONTENT_RESOURCE_TYPES,
    CONDITION_RESOURCE_TYPES,
    HIERARCHY_RESOURCE_TYPES,
    DatabaseChangeBatch,
    DatabaseChange,
    HydratedDatabaseChangeBatch,
    ChangeOperation,
    ResourceRef,
)
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...application.interfaces.i_remote_change_reader import IRemoteChangeReader
from ...domain.entities.file_results import BidLoadResult
from ...domain.entities.page import build_pages_from_bid_data
from .connection_manager import SqlConnectionManager
from .descriptor_connection import SqlDescriptorConnectionFactory
from .reader import SqlProjectReader


class SqlRemoteChangeReader(IRemoteChangeReader):
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        connection_manager: Optional[SqlConnectionManager] = None,
    ) -> None:
        self._requests = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._connections = connection_manager or SqlConnectionManager()
        self._reader = SqlProjectReader(
            descriptor_registry,
            credential_store,
            connection_manager=self._connections,
        )

    def initial_reconciliation(
        self, database_id: str, bid_uid: int | None, checkpoint: int
    ) -> HydratedDatabaseChangeBatch:
        resources = [ResourceRef("database", database_id)]
        if bid_uid is not None:
            resources.extend(
                ResourceRef(resource_type, str(bid_uid), bid_uid)
                for resource_type in (
                    "conditions_collection",
                    "areas_collection",
                    "takeoffs_collection",
                    "annotations_collection",
                    "pages_collection",
                    "layers_collection",
                )
            )
        batch = DatabaseChangeBatch(
            database_id=database_id,
            feed_epoch="",
            oldest_available_sequence=checkpoint,
            high_water_sequence=checkpoint,
            changes=tuple(
                DatabaseChange(
                    sequence=checkpoint,
                    transaction_id="initial-reconciliation",
                    source_session_id=None,
                    resource=resource,
                    operation=ChangeOperation.BULK_REFRESH,
                )
                for resource in resources
            ),
        )
        return self.hydrate(batch)

    def hydrate(self, batch: DatabaseChangeBatch) -> HydratedDatabaseChangeBatch:
        condition_bids = {
            change.resource.bid_uid
            for change in batch.changes
            if change.resource.bid_uid is not None
            and change.resource.resource_type in CONDITION_RESOURCE_TYPES
        }
        area_bids = {
            change.resource.bid_uid
            for change in batch.changes
            if change.resource.bid_uid is not None
            and change.resource.resource_type in AREA_RESOURCE_TYPES
        }
        bid_data_bids = {
            change.resource.bid_uid
            for change in batch.changes
            if change.resource.bid_uid is not None
            and change.resource.resource_type in BID_CONTENT_RESOURCE_TYPES
        }
        needs_hierarchy = any(
            change.resource.resource_type in HIERARCHY_RESOURCE_TYPES
            for change in batch.changes
        )
        if (
            not condition_bids
            and not area_bids
            and not bid_data_bids
            and not needs_hierarchy
        ):
            return HydratedDatabaseChangeBatch(batch=batch)
        conditions_by_bid = {}
        folders_by_bid = {}
        areas_by_bid = {}
        bid_data_by_bid = {}
        hierarchy_file = None
        if needs_hierarchy:
            hierarchy_file, _cdn_types = self._reader.parse_file(batch.database_id)
        if condition_bids or area_bids:
            request = self._requests.request(batch.database_id, read_only=True)
            with self._connections.connection(request, autocommit=True) as connection:
                for bid_uid in sorted(condition_bids):
                    key = str(bid_uid)
                    conditions_by_bid[bid_uid] = (
                        self._reader._parse_bid_conditions_for_bid(connection, key)
                    )
                    folders_by_bid[bid_uid] = (
                        self._reader._parse_bid_condition_folders_for_bid(
                            connection, key
                        )
                    )
                for bid_uid in sorted(area_bids):
                    areas_by_bid[bid_uid] = tuple(
                        self._reader._parse_bid_areas_for_bid(connection, str(bid_uid))
                    )
        for bid_uid in sorted(bid_data_bids):
            (
                conditions,
                takeoffs,
                areas,
                pages,
                page_area_selections,
                _cdn_types,
                annotations,
                condition_folders,
                selected_page_uid,
                takeoff_extras,
            ) = self._reader.get_bid_data(batch.database_id, str(bid_uid))
            layers = self._reader.get_bid_layers_for_sidebar(
                batch.database_id, str(bid_uid)
            )
            bid_data_by_bid[bid_uid] = BidLoadResult(
                bid_conditions=conditions,
                bid_takeoffs=takeoffs,
                bid_areas=areas,
                bid_pages=pages,
                pages=build_pages_from_bid_data(pages, takeoffs),
                page_area_selections=page_area_selections,
                bid_annotations=annotations,
                bid_layers=layers,
                bid_condition_folders=condition_folders,
                selected_page_uid=selected_page_uid,
                takeoff_extras=takeoff_extras,
            )
        return HydratedDatabaseChangeBatch(
            batch=batch,
            conditions_by_bid=conditions_by_bid,
            condition_folders_by_bid=folders_by_bid,
            areas_by_bid=areas_by_bid,
            bid_data_by_bid=bid_data_by_bid,
            hierarchy_file=hierarchy_file,
        )
