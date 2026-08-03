from __future__ import annotations
from typing import Optional
import pyodbc
from ...application.dtos.collaboration_resource_catalog import (
    AREA_RESOURCE_TYPES,
    BID_CONTENT_RESOURCE_TYPES,
    CONDITION_RESOURCE_TYPES,
    HIERARCHY_RESOURCE_TYPES,
    MASTER_DATA_RESOURCE_TYPES,
    BID_CONTENT_FAMILY_BY_RESOURCE_TYPE,
    CollaborationResourceFamily,
    CollaborationResourceType,
)
from ...application.dtos.collaboration_dtos import (
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
from .connection_manager import SqlConnectionManager, begin_snapshot_transaction
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
        resources = [ResourceRef(CollaborationResourceType.DATABASE.value, database_id)]
        resources.extend(
            ResourceRef(resource_type, "database")
            for resource_type in (
                CollaborationResourceType.DEFAULT_LAYERS_COLLECTION.value,
                CollaborationResourceType.JOB_STATUSES_COLLECTION.value,
                CollaborationResourceType.EMPLOYEES_COLLECTION.value,
                CollaborationResourceType.PAY_CLASSES_COLLECTION.value,
            )
        )
        if bid_uid is not None:
            resources.extend(
                ResourceRef(resource_type, str(bid_uid), bid_uid)
                for resource_type in (
                    CollaborationResourceType.CONDITIONS_COLLECTION.value,
                    CollaborationResourceType.AREAS_COLLECTION.value,
                    CollaborationResourceType.TAKEOFFS_COLLECTION.value,
                    CollaborationResourceType.ANNOTATIONS_COLLECTION.value,
                    CollaborationResourceType.PAGES_COLLECTION.value,
                    CollaborationResourceType.LAYERS_COLLECTION.value,
                )
            )
            resources.append(
                ResourceRef(
                    CollaborationResourceType.COVER_SHEET.value,
                    str(bid_uid),
                    bid_uid,
                )
            )
        request = self._requests.request(database_id, read_only=True)
        with self._connections.connection(request, autocommit=False) as connection:
            transaction_finished = False
            try:
                begin_snapshot_transaction(connection)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION()")
                    version_row = cursor.fetchone()
                    if version_row is None or version_row[0] is None:
                        raise ValueError("SQL Change Tracking metadata is unavailable.")
                    high_water_version = int(version_row[0])
                    if high_water_version < checkpoint:
                        raise ValueError(
                            "The initial SQL checkpoint is ahead of the database."
                        )
                batch = DatabaseChangeBatch(
                    database_id=database_id,
                    feed_epoch="",
                    minimum_valid_version=checkpoint,
                    high_water_version=high_water_version,
                    delivered_through_version=checkpoint,
                    changes=tuple(
                        DatabaseChange(
                            sequence=high_water_version,
                            commit_version=high_water_version,
                            transaction_id="initial-reconciliation",
                            source_session_id=None,
                            resource=resource,
                            operation=ChangeOperation.BULK_REFRESH,
                        )
                        for resource in resources
                    ),
                )
                hydrated = self.hydrate_connection(batch, connection)
                connection.commit()
                transaction_finished = True
            finally:
                if not transaction_finished:
                    _rollback(connection)
        return hydrated

    def hydrate_connection(
        self, batch: DatabaseChangeBatch, connection
    ) -> HydratedDatabaseChangeBatch:
        takeoff_bids = {
            change.resource.bid_uid
            for change in batch.changes
            if change.resource.bid_uid is not None
            and BID_CONTENT_FAMILY_BY_RESOURCE_TYPE.get(change.resource.resource_type)
            == CollaborationResourceFamily.TAKEOFFS.value
        }
        condition_bids = {
            change.resource.bid_uid
            for change in batch.changes
            if change.resource.bid_uid is not None
            and change.resource.resource_type in CONDITION_RESOURCE_TYPES
        }.union(takeoff_bids)
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
        cover_sheet_bids = {
            change.resource.bid_uid
            for change in batch.changes
            if change.resource.bid_uid is not None
            and change.resource.resource_type
            == CollaborationResourceType.COVER_SHEET.value
        }
        delete_content_bids = set(cover_sheet_bids)
        delete_content_bids.update(
            change.resource.bid_uid
            for change in batch.changes
            if change.resource.bid_uid is not None
            and change.resource.resource_type
            in {
                CollaborationResourceType.PAGE.value,
                CollaborationResourceType.PAGES_COLLECTION.value,
            }
        )
        needs_default_layers = any(
            change.resource.resource_type
            == CollaborationResourceType.DEFAULT_LAYERS_COLLECTION.value
            for change in batch.changes
        )
        master_resource_types = {
            change.resource.resource_type
            for change in batch.changes
            if change.resource.resource_type in MASTER_DATA_RESOURCE_TYPES
        }
        if (
            not condition_bids
            and not area_bids
            and not bid_data_bids
            and not needs_hierarchy
            and not needs_default_layers
            and not master_resource_types
            and not cover_sheet_bids
        ):
            return HydratedDatabaseChangeBatch(batch=batch)
        takeoff_only = (
            isinstance(self._reader, SqlProjectReader)
            and bool(takeoff_bids)
            and condition_bids == takeoff_bids
            and bid_data_bids == takeoff_bids
            and not area_bids
            and not needs_hierarchy
            and not needs_default_layers
            and not master_resource_types
            and not cover_sheet_bids
            and all(
                change.resource.resource_type
                in {
                    CollaborationResourceType.TAKEOFF.value,
                    CollaborationResourceType.TAKEOFFS_COLLECTION.value,
                }
                for change in batch.changes
            )
        )
        if takeoff_only:
            return self._hydrate_takeoff_only_batch(
                batch,
                connection,
                tuple(sorted(takeoff_bids)),
            )
        conditions_by_bid = {}
        folders_by_bid = {}
        areas_by_bid = {}
        bid_data_by_bid = {}
        hierarchy_file = None
        hierarchy_cdn_types = {}
        default_layers = None
        job_statuses = None
        employees = None
        pay_classes = None
        used_job_status_uids = None
        used_employee_uids = None
        cover_sheet_by_bid = {}
        page_delete_content_uids_by_bid = {}
        settings_defaults = None
        if needs_hierarchy:
            hierarchy_file, hierarchy_cdn_types = self._reader.parse_file_connection(
                batch.database_id, connection
            )
            settings_defaults = self._reader._parse_settings_defaults(connection)
        if needs_default_layers:
            default_layers = tuple(self._reader._parse_default_layers(connection))
        if master_resource_types:
            if master_resource_types.intersection(
                {
                    CollaborationResourceType.JOB_STATUS.value,
                    CollaborationResourceType.JOB_STATUSES_COLLECTION.value,
                }
            ):
                job_statuses = tuple(self._reader._parse_job_statuses(connection))
                used_job_status_uids = frozenset(
                    self._reader._parse_used_job_status_uids(connection)
                )
            needs_people = bool(
                master_resource_types.intersection(
                    {
                        CollaborationResourceType.EMPLOYEE.value,
                        CollaborationResourceType.EMPLOYEES_COLLECTION.value,
                        CollaborationResourceType.PAY_CLASS.value,
                        CollaborationResourceType.PAY_CLASSES_COLLECTION.value,
                    }
                )
            )
            if needs_people:
                parsed_employees, parsed_pay_classes = (
                    self._reader._parse_employees_and_pay_classes(connection)
                )
                if master_resource_types.intersection(
                    {
                        CollaborationResourceType.EMPLOYEE.value,
                        CollaborationResourceType.EMPLOYEES_COLLECTION.value,
                    }
                ):
                    employees = tuple(parsed_employees)
                    used_employee_uids = frozenset(
                        self._reader._parse_used_employee_uids(connection)
                    )
                if master_resource_types.intersection(
                    {
                        CollaborationResourceType.PAY_CLASS.value,
                        CollaborationResourceType.PAY_CLASSES_COLLECTION.value,
                    }
                ):
                    pay_classes = tuple(parsed_pay_classes)
        for bid_uid in sorted(cover_sheet_bids):
            cover_sheet = self._reader._parse_cover_sheet_data(connection, str(bid_uid))
            if cover_sheet is not None:
                cover_sheet_by_bid[bid_uid] = cover_sheet
        for bid_uid in sorted(delete_content_bids):
            page_delete_content_uids_by_bid[bid_uid] = frozenset(
                self._reader._parse_pages_with_delete_content(connection, str(bid_uid))
            )
        if condition_bids or area_bids:
            schema = self._reader._schema(connection)
            cdn_types = (
                self._reader._parse_cdn_types(connection) if condition_bids else {}
            )
            for bid_uid in sorted(condition_bids):
                key = str(bid_uid)
                bid_layers = self._reader._parse_bid_layers_for_bid(connection, key)
                conditions_by_bid[bid_uid] = self._reader._parse_bid_conditions_for_bid(
                    connection,
                    key,
                    bid_layers,
                    cdn_types,
                    schema,
                )
                folders_by_bid[bid_uid] = (
                    self._reader._parse_bid_condition_folders_for_bid(
                        connection, key, schema
                    )
                )
            for bid_uid in sorted(area_bids):
                areas_by_bid[bid_uid] = tuple(
                    self._reader._parse_bid_areas_for_bid(
                        connection, str(bid_uid), schema
                    ).values()
                )
        families_by_bid = {
            bid_uid: {
                BID_CONTENT_FAMILY_BY_RESOURCE_TYPE[change.resource.resource_type]
                for change in batch.changes
                if change.resource.bid_uid == bid_uid
                and change.resource.resource_type in BID_CONTENT_FAMILY_BY_RESOURCE_TYPE
            }
            for bid_uid in bid_data_bids
        }
        if bid_data_bids:
            schema = self._reader._schema(connection)
            for bid_uid in sorted(bid_data_bids):
                bid_key = str(bid_uid)
                families = families_by_bid[bid_uid]
                needs_page_graph = bool(
                    families
                    & {
                        CollaborationResourceFamily.PAGES.value,
                        CollaborationResourceFamily.TAKEOFFS.value,
                    }
                )
                raw_layers = (
                    self._reader._parse_bid_layers_for_bid(connection, bid_key)
                    if families
                    & {
                        CollaborationResourceFamily.PAGES.value,
                        CollaborationResourceFamily.ANNOTATIONS.value,
                    }
                    else {}
                )
                takeoffs, takeoff_extras = (
                    self._reader._parse_bid_takeoffs_for_bid(
                        connection, bid_key, schema
                    )
                    if needs_page_graph
                    else ([], {})
                )
                pages = (
                    self._reader._parse_bid_pages_for_bid(
                        connection, bid_key, raw_layers, schema
                    )
                    if needs_page_graph
                    else {}
                )
                annotations = (
                    self._reader._parse_bid_annotations_for_bid(
                        connection, bid_key, raw_layers, schema
                    )
                    if CollaborationResourceFamily.ANNOTATIONS.value in families
                    else []
                )
                page_area_selections = (
                    self._reader._parse_page_area_selections_for_bid(
                        connection, pages, schema
                    )
                    if CollaborationResourceFamily.PAGES.value in families
                    else {}
                )
                layers = (
                    self._reader._parse_bid_layers_for_sidebar(connection, bid_key)
                    if CollaborationResourceFamily.LAYERS.value in families
                    else []
                )
                bid_data_by_bid[bid_uid] = BidLoadResult(
                    bid_takeoffs=takeoffs,
                    bid_pages=pages,
                    pages=build_pages_from_bid_data(pages, takeoffs),
                    page_area_selections=page_area_selections,
                    bid_annotations=annotations,
                    bid_layers=layers,
                    takeoff_extras=takeoff_extras,
                )
        return HydratedDatabaseChangeBatch(
            batch=batch,
            conditions_by_bid=conditions_by_bid,
            condition_folders_by_bid=folders_by_bid,
            areas_by_bid=areas_by_bid,
            bid_data_by_bid=bid_data_by_bid,
            hierarchy_file=hierarchy_file,
            cdn_types=hierarchy_cdn_types,
            default_layers=default_layers,
            job_statuses=job_statuses,
            employees=employees,
            pay_classes=pay_classes,
            used_job_status_uids=used_job_status_uids,
            used_employee_uids=used_employee_uids,
            cover_sheet_by_bid=cover_sheet_by_bid,
            page_delete_content_uids_by_bid=page_delete_content_uids_by_bid,
            settings_defaults=settings_defaults,
        )

    def _hydrate_takeoff_only_batch(
        self,
        batch: DatabaseChangeBatch,
        connection,
        bid_uids: tuple[int, ...],
    ) -> HydratedDatabaseChangeBatch:
        schema = self._reader._schema(connection)
        recording = _QueryRecordingConnection(schema.get_columns("BidTakeoffs"))
        self._reader._parse_cdn_types(recording)
        for bid_uid in bid_uids:
            bid_key = str(bid_uid)
            layers = self._reader._parse_bid_layers_for_bid(recording, bid_key)
            self._reader._parse_bid_conditions_for_bid(
                recording,
                bid_key,
                layers,
                {},
                schema,
            )
            self._reader._parse_bid_condition_folders_for_bid(
                recording,
                bid_key,
                schema,
            )
        for bid_uid in bid_uids:
            bid_key = str(bid_uid)
            self._reader._parse_bid_takeoffs_for_bid(recording, bid_key, schema)
            self._reader._parse_bid_pages_for_bid(recording, bid_key, {}, schema)
        replay = _execute_recorded_queries(connection, recording.queries)
        cdn_types = self._reader._parse_cdn_types(replay)
        conditions_by_bid = {}
        folders_by_bid = {}
        bid_data_by_bid = {}
        for bid_uid in bid_uids:
            bid_key = str(bid_uid)
            layers = self._reader._parse_bid_layers_for_bid(replay, bid_key)
            conditions_by_bid[bid_uid] = self._reader._parse_bid_conditions_for_bid(
                replay,
                bid_key,
                layers,
                cdn_types,
                schema,
            )
            folders_by_bid[bid_uid] = self._reader._parse_bid_condition_folders_for_bid(
                replay,
                bid_key,
                schema,
            )
        for bid_uid in bid_uids:
            bid_key = str(bid_uid)
            takeoffs, takeoff_extras = self._reader._parse_bid_takeoffs_for_bid(
                replay,
                bid_key,
                schema,
            )
            pages = self._reader._parse_bid_pages_for_bid(
                replay,
                bid_key,
                {},
                schema,
            )
            bid_data_by_bid[bid_uid] = BidLoadResult(
                bid_takeoffs=takeoffs,
                bid_pages=pages,
                pages=build_pages_from_bid_data(pages, takeoffs),
                takeoff_extras=takeoff_extras,
            )
        replay.assert_consumed()
        return HydratedDatabaseChangeBatch(
            batch=batch,
            conditions_by_bid=conditions_by_bid,
            condition_folders_by_bid=folders_by_bid,
            bid_data_by_bid=bid_data_by_bid,
        )


class _QueryRecordingCursor:
    def __init__(self, owner, takeoff_columns: frozenset[str]) -> None:
        self._owner = owner
        self._takeoff_columns = takeoff_columns
        self.description = ()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def execute(self, sql, *parameters):
        self._owner.queries.append((str(sql), tuple(parameters)))
        if "FROM [BidTakeoffs]" in str(sql):
            self.description = tuple(
                (column,) for column in sorted(self._takeoff_columns)
            )
        else:
            self.description = ()
        return self

    @staticmethod
    def fetchall():
        return ()


class _QueryRecordingConnection:
    def __init__(self, takeoff_columns: frozenset[str]) -> None:
        self._takeoff_columns = takeoff_columns
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def cursor(self):
        return _QueryRecordingCursor(self, self._takeoff_columns)


class _QueryReplayCursor:
    def __init__(self, owner) -> None:
        self._owner = owner
        self.description = ()
        self._rows = ()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def execute(self, sql, *parameters):
        expected_sql, expected_parameters, description, rows = self._owner.pop()
        if (
            _normalized_sql(sql) != _normalized_sql(expected_sql)
            or tuple(parameters) != expected_parameters
        ):
            raise RuntimeError("The SQL hydration replay query order changed.")
        self.description = description
        self._rows = rows
        return self

    def fetchall(self):
        return self._rows


class _QueryReplayConnection:
    def __init__(self, results) -> None:
        self._results = list(results)

    def cursor(self):
        return _QueryReplayCursor(self)

    def pop(self):
        if not self._results:
            raise RuntimeError("The SQL hydration replay has no result set remaining.")
        return self._results.pop(0)

    def assert_consumed(self) -> None:
        if self._results:
            raise RuntimeError("The SQL hydration replay left unused result sets.")


def _execute_recorded_queries(connection, queries):
    if not queries:
        return _QueryReplayConnection(())
    sql = "; ".join(query.rstrip().rstrip(";") for query, _parameters in queries)
    parameters = tuple(
        parameter
        for _query, query_parameters in queries
        for parameter in query_parameters
    )
    results = []
    with connection.cursor() as cursor:
        cursor.execute(sql, *parameters)
        for index, (query, query_parameters) in enumerate(queries):
            results.append(
                (
                    query,
                    query_parameters,
                    tuple(cursor.description or ()),
                    tuple(cursor.fetchall()),
                )
            )
            if index + 1 < len(queries) and not cursor.nextset():
                raise RuntimeError(
                    "The SQL takeoff hydration batch returned too few result sets."
                )
    return _QueryReplayConnection(results)


def _normalized_sql(sql) -> str:
    return " ".join(str(sql).split())


def _rollback(connection) -> None:
    try:
        connection.rollback()
    except pyodbc.Error:
        pass
