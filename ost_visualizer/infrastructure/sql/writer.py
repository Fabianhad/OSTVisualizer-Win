from __future__ import annotations
import itertools
import contextvars
import json
import logging
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Generator, Optional, TypeVar
import pyodbc
from ...application.dtos.collaboration_resource_catalog import (
    CollaborationResourceType,
    coalesced_resource_type,
    resource_definition,
)
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...application.interfaces.i_database_session_registry import (
    IDatabaseSessionRegistry,
)
from ...application.dtos.collaboration_dtos import (
    COLLABORATION_STALE_SECONDS,
    ChangeOperation,
    ConcurrencyToken,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    ResourceRef,
    SynchronizationConflict,
)
from ...application.interfaces.i_database_mutation_executor import IMutationRecorder
from ...domain.dtos.raw_bid_data_dto import RawBidData
from ..mdb.components.constants import BID_TABLES_WRITE_ORDER
from ..mdb.raw_bid_integrity import RAW_BID_RELATIONSHIPS
from ..mdb.schema_contract import PAGE_SECTIONS
from ..mdb.mdb_writer import MdbWriter
from .connection_manager import SqlConnectionLease, SqlConnectionManager
from .client_permissions import require_sql_client_editability
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
    sql_schema_mismatch,
)
from .schema_definition import SQL_SCHEMA_V1
from .schema_lock import acquire_resource_transaction_lock
from .write_schema import CurrentSqlWriteSchema

T = TypeVar("T")
_IMPORT_GRAPH_TABLES = frozenset({"Bids", *BID_TABLES_WRITE_ORDER, *PAGE_SECTIONS})
_IMPORT_PARENT_TABLE_BY_REFERENCE = {
    (relationship.child_table, relationship.child_column): relationship.parent_table
    for relationship in RAW_BID_RELATIONSHIPS
    if relationship.parent_table in _IMPORT_GRAPH_TABLES
}


class _DeferredIdentity(int):
    def __new__(cls, placeholder: int):
        instance = int.__new__(cls, placeholder)
        instance._resolved = None
        return instance

    def bind(self, value: int) -> None:
        self._resolved = int(value)

    @property
    def resolved(self) -> int:
        if self._resolved is None:
            raise RuntimeError("SQL identity has not been generated yet")
        return self._resolved

    def __int__(self) -> int:
        return self.resolved

    def __str__(self) -> str:
        return str(self.resolved)


class _OptimisticConflict(SqlInfrastructureError):
    def __init__(
        self,
        resource: ResourceRef,
        expected: ConcurrencyToken,
        actual: Optional[ConcurrencyToken],
    ) -> None:
        super().__init__(
            SqlErrorDetails(
                SqlErrorCode.CONFLICT,
                "This SQL item changed in another session. Reload it before saving.",
            )
        )
        self.resource = resource
        self.expected = expected
        self.actual = actual


@dataclass
class _RecordedMutation:
    resource: ResourceRef
    operation: ChangeOperation
    changed_fields: tuple[str, ...] = ()
    payload: str = ""


@dataclass
class _SqlMutationState(IMutationRecorder):
    database_id: str
    lease: SqlConnectionLease
    request: DatabaseMutationRequest
    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    records: list[_RecordedMutation] = field(default_factory=list)

    def record(
        self,
        resource: ResourceRef,
        operation: ChangeOperation,
        *,
        changed_fields: tuple[str, ...] = (),
        payload: str = "",
    ) -> None:
        self.records.append(
            _RecordedMutation(resource, operation, changed_fields, payload)
        )


class SqlProjectWriter(MdbWriter):
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        session_registry: IDatabaseSessionRegistry,
        connection_manager: Optional[SqlConnectionManager] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._requests = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._sql_connections = connection_manager or SqlConnectionManager()
        self._session_registry = session_registry
        self._identity_lock = threading.Lock()
        self._identity_placeholders = itertools.count(start=-1, step=-1)
        self._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)
        self._active_mutation = contextvars.ContextVar(
            "sql_database_mutation", default=None
        )

    @contextmanager
    def _connection(
        self, database_id: str
    ) -> Generator[SqlConnectionLease, None, None]:
        active = self._active_mutation.get()
        if active is not None:
            if active.database_id != database_id:
                raise RuntimeError(
                    "A SQL mutation cannot switch databases inside its transaction."
                )
            yield active.lease
            return
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.SESSION_EXPIRED,
                "SQL writes must run through a collaboration mutation transaction.",
            )
        )

    def execute(
        self,
        request: DatabaseMutationRequest,
        operation: Callable[[IMutationRecorder], T],
    ) -> DatabaseMutationResult[T]:
        try:
            return self._execute_mutation_transaction(request, operation)
        except SqlInfrastructureError as exc:
            if exc.details.code not in {
                SqlErrorCode.CONFLICT,
                SqlErrorCode.LOCKED,
                SqlErrorCode.SESSION_EXPIRED,
            }:
                raise
            resource = (
                exc.resource
                if isinstance(exc, _OptimisticConflict)
                else (
                    request.resources[0]
                    if request.resources
                    else ResourceRef(
                        CollaborationResourceType.DATABASE.value,
                        request.database_id,
                    )
                )
            )
            return DatabaseMutationResult(
                success=False,
                conflict=SynchronizationConflict(
                    database_id=request.database_id,
                    resource=resource,
                    reason=str(exc),
                    expected=(
                        exc.expected if isinstance(exc, _OptimisticConflict) else None
                    ),
                    actual=(
                        exc.actual if isinstance(exc, _OptimisticConflict) else None
                    ),
                ),
            )

    def _execute_mutation_transaction(
        self,
        request: DatabaseMutationRequest,
        operation: Callable[[IMutationRecorder], T],
    ) -> DatabaseMutationResult[T]:
        registered_session = self._require_active_session(request.database_id)
        if request.session_id != registered_session:
            conflict = SynchronizationConflict(
                database_id=request.database_id,
                resource=ResourceRef(
                    CollaborationResourceType.DATABASE.value,
                    request.database_id,
                ),
                reason="The SQL collaboration session changed before the write.",
            )
            return DatabaseMutationResult(success=False, conflict=conflict)
        connection_request = self._requests.request(
            request.database_id, read_only=False
        )
        with self._sql_connections.connection(
            connection_request, autocommit=False
        ) as lease:
            committed = False
            try:
                self._require_sql_client_editability(lease)
                state = _SqlMutationState(request.database_id, lease, request)
                self._set_session_context(state)
                self._prepare_mutation(state)
                token = self._active_mutation.set(state)
                try:
                    value = operation(state)
                finally:
                    self._active_mutation.reset(token)
                if not state.records:
                    raise RuntimeError(
                        "The SQL mutation did not record an affected resource."
                    )
                versions = self._finish_mutation(state)
                lease.commit()
                committed = True
                return DatabaseMutationResult(
                    success=True,
                    value=value,
                    resulting_versions=versions,
                )
            finally:
                if not committed:
                    try:
                        lease.rollback()
                    except pyodbc.Error:
                        pass
                self._clear_session_context(lease)

    @staticmethod
    def _set_session_context(state: _SqlMutationState) -> None:
        with state.lease.cursor() as cursor:
            cursor.execute(
                "EXEC sys.sp_set_session_context @key=N'ostv_session_id', @value=?",
                state.request.session_id,
            )
            cursor.execute(
                "EXEC sys.sp_set_session_context @key=N'ostv_transaction_id', @value=?",
                state.transaction_id,
            )

    @staticmethod
    def _clear_session_context(lease: SqlConnectionLease) -> None:
        try:
            with lease.cursor() as cursor:
                cursor.execute(
                    "EXEC sys.sp_set_session_context "
                    "@key=N'ostv_session_id', @value=NULL"
                )
                cursor.execute(
                    "EXEC sys.sp_set_session_context "
                    "@key=N'ostv_transaction_id', @value=NULL"
                )
        except pyodbc.Error:
            return

    def _prepare_mutation(self, state: _SqlMutationState) -> None:
        cursor = state.lease.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM [ostv].[Sessions] WHERE [SessionId]=? AND "
                "[DisconnectedAt] IS NULL AND [LastHeartbeatAt] >= "
                "DATEADD(second, ?, SYSUTCDATETIME())",
                state.request.session_id,
                -COLLABORATION_STALE_SECONDS,
            )
            if cursor.fetchone() is None:
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.SESSION_EXPIRED,
                        "The SQL collaboration session expired before the write.",
                    )
                )
            resources = set(state.request.resources)
            resources.update(item.resource for item in state.request.expected_versions)
            lock_modes: dict[ResourceRef, str] = {}
            for resource in resources:
                lock_modes[resource] = "Exclusive"
                if resource.bid_uid is not None:
                    bid_resource = ResourceRef(
                        CollaborationResourceType.BID.value,
                        str(resource.bid_uid),
                        resource.bid_uid,
                    )
                    if bid_resource not in lock_modes:
                        lock_modes[bid_resource] = "Shared"
            for resource in resources:
                if resource.resource_type == CollaborationResourceType.BID.value:
                    lock_modes[resource] = "Exclusive"
            for resource in sorted(
                lock_modes,
                key=lambda item: (
                    (
                        0
                        if item.resource_type == CollaborationResourceType.BID.value
                        else 1
                    ),
                    item.resource_type,
                    item.resource_id,
                ),
            ):
                acquire_resource_transaction_lock(
                    cursor, resource, lock_modes[resource]
                )
            for resource in sorted(resources):
                cursor.execute(
                    "SELECT s.[DisplayName] FROM [ostv].[Locks] l JOIN "
                    "[ostv].[Sessions] s ON s.[SessionId]=l.[OwnerSessionId] "
                    "WHERE l.[ResourceType]=? AND l.[ResourceId]=? AND "
                    "l.[OwnerSessionId]<>? AND l.[ExpiresAt] > SYSUTCDATETIME()",
                    resource.resource_type,
                    resource.resource_id,
                    state.request.session_id,
                )
                lock_owner = cursor.fetchone()
                if lock_owner is not None:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.LOCKED,
                            f"This item is being edited by {lock_owner[0]}.",
                        )
                    )
                if (
                    resource.bid_uid is not None
                    and resource.resource_type != CollaborationResourceType.BID.value
                ):
                    cursor.execute(
                        "SELECT s.[DisplayName] FROM [ostv].[Locks] l JOIN "
                        "[ostv].[Sessions] s ON "
                        "s.[SessionId]=l.[OwnerSessionId] WHERE "
                        "l.[ResourceType]=? AND l.[ResourceId]=? AND "
                        "l.[OwnerSessionId]<>? AND "
                        "l.[ExpiresAt] > SYSUTCDATETIME()",
                        CollaborationResourceType.BID.value,
                        str(resource.bid_uid),
                        state.request.session_id,
                    )
                    bid_lock_owner = cursor.fetchone()
                    if bid_lock_owner is not None:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.LOCKED,
                                f"This bid is being changed by {bid_lock_owner[0]}.",
                            )
                        )
                if (
                    state.request.block_bid_child_locks
                    and resource.resource_type == CollaborationResourceType.BID.value
                ):
                    cursor.execute(
                        "SELECT TOP (1) s.[DisplayName] FROM [ostv].[Locks] l "
                        "JOIN [ostv].[Sessions] s ON "
                        "s.[SessionId]=l.[OwnerSessionId] WHERE l.[BidUID]=? "
                        "AND l.[OwnerSessionId]<>? AND "
                        "l.[ExpiresAt] > SYSUTCDATETIME()",
                        resource.bid_uid,
                        state.request.session_id,
                    )
                    child_lock_owner = cursor.fetchone()
                    if child_lock_owner is not None:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.LOCKED,
                                "This bid contains an item being edited by "
                                f"{child_lock_owner[0]}.",
                            )
                        )
                if (
                    state.request.block_bid_active_editors
                    and resource.resource_type == CollaborationResourceType.BID.value
                ):
                    cursor.execute(
                        "SELECT TOP (1) s.[DisplayName] FROM [ostv].[Presence] p "
                        "JOIN [ostv].[Sessions] s ON "
                        "s.[SessionId]=p.[SessionId] WHERE p.[BidUID]=? AND "
                        "p.[ActivityMode]=N'editing' AND p.[SessionId]<>? AND "
                        "s.[DisconnectedAt] IS NULL AND s.[LastHeartbeatAt] >= "
                        "DATEADD(second, ?, SYSUTCDATETIME())",
                        resource.bid_uid,
                        state.request.session_id,
                        -COLLABORATION_STALE_SECONDS,
                    )
                    active_editor = cursor.fetchone()
                    if active_editor is not None:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.LOCKED,
                                "This bid is actively being edited by "
                                f"{active_editor[0]}.",
                            )
                        )
            requested_keys = {
                (resource.resource_type, resource.resource_id) for resource in resources
            }
            required_tokens = set(state.request.required_lock_tokens)
            for lock_token in required_tokens:
                cursor.execute(
                    "SELECT [ResourceType], [ResourceId] FROM [ostv].[Locks] "
                    "WHERE [LockToken]=? AND "
                    "[OwnerSessionId]=? AND [ExpiresAt] > SYSUTCDATETIME()",
                    lock_token,
                    state.request.session_id,
                )
                lock_row = cursor.fetchone()
                if lock_row is None:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.LOCKED,
                            "A required SQL edit lock expired before the write.",
                        )
                    )
                if (str(lock_row[0]), str(lock_row[1])) not in requested_keys:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.LOCKED,
                            "A SQL edit lock does not belong to this mutation.",
                        )
                    )
            for resource in sorted(resources):
                cursor.execute(
                    "SELECT CONVERT(nvarchar(36), [LockToken]) FROM "
                    "[ostv].[Locks] WHERE [ResourceType]=? AND [ResourceId]=? "
                    "AND [OwnerSessionId]=? AND [ExpiresAt] > SYSUTCDATETIME()",
                    resource.resource_type,
                    resource.resource_id,
                    state.request.session_id,
                )
                owned_lock = cursor.fetchone()
                if owned_lock is not None and str(owned_lock[0]) not in required_tokens:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.LOCKED,
                            "The mutation did not present its owned SQL edit lock.",
                        )
                    )
            for expected in state.request.expected_versions:
                cursor.execute(
                    "SELECT [Token] FROM [ostv].[EntityVersions] WITH "
                    "(UPDLOCK, HOLDLOCK) WHERE [ResourceType]=? AND [ResourceId]=?",
                    expected.resource.resource_type,
                    expected.resource.resource_id,
                )
                row = cursor.fetchone()
                actual = (
                    ConcurrencyToken.from_database(row[0]) if row is not None else None
                )
                if actual != expected.expected:
                    raise _OptimisticConflict(
                        expected.resource,
                        expected.expected,
                        actual,
                    )
        finally:
            cursor.close()

    def _finish_mutation(self, state: _SqlMutationState):
        versions = {}
        cursor = state.lease.cursor()
        try:
            cursor.execute(
                "SELECT TOP (1) [DatabaseGuid] " "FROM [ostv].[DatabaseMetadata]"
            )
            database_guid = cursor.fetchone()[0]
            records = self._coalesce_records(state.records)
            for record in records:
                cursor.execute(
                    "MERGE [ostv].[EntityVersions] WITH (HOLDLOCK) AS target "
                    "USING (SELECT ? AS [ResourceType], ? AS [ResourceId]) AS source "
                    "ON target.[ResourceType]=source.[ResourceType] AND "
                    "target.[ResourceId]=source.[ResourceId] "
                    "WHEN MATCHED THEN UPDATE SET [BidUID]=?, [IsDeleted]=?, "
                    "[ModifiedAt]=SYSUTCDATETIME(), [ModifiedBySessionId]=? "
                    "WHEN NOT MATCHED THEN INSERT ([ResourceType], [ResourceId], "
                    "[BidUID], [IsDeleted], [ModifiedBySessionId]) "
                    "VALUES (?, ?, ?, ?, ?) OUTPUT INSERTED.[Token];",
                    record.resource.resource_type,
                    record.resource.resource_id,
                    record.resource.bid_uid,
                    record.operation == ChangeOperation.DELETE,
                    state.request.session_id,
                    record.resource.resource_type,
                    record.resource.resource_id,
                    record.resource.bid_uid,
                    record.operation == ChangeOperation.DELETE,
                    state.request.session_id,
                )
                version = ConcurrencyToken.from_database(cursor.fetchone()[0])
                versions[record.resource] = version
                cursor.execute(
                    "INSERT INTO [ostv].[ChangeLog] ([TransactionId], "
                    "[SourceSessionId], [DatabaseGuid], [BidUID], [ResourceType], "
                    "[ResourceId], [Operation], [ResultVersion], [ChangedFields], "
                    "[Payload], [SourceKind]) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, N'ost_visualizer')",
                    state.transaction_id,
                    state.request.session_id,
                    database_guid,
                    record.resource.bid_uid,
                    record.resource.resource_type,
                    record.resource.resource_id,
                    record.operation.value,
                    version.value,
                    (
                        json.dumps(record.changed_fields)
                        if record.changed_fields
                        else None
                    ),
                    record.payload or None,
                )
            resource_families = sorted(
                {
                    coalesced_resource_type(record.resource.resource_type)
                    for record in records
                }
            )
            cursor.execute(
                "INSERT INTO [ostv].[ChangeTransactions] "
                "([TransactionId], [SourceSessionId], [DatabaseGuid], "
                "[ResourceFamilySummary]) VALUES (?, ?, ?, ?)",
                state.transaction_id,
                state.request.session_id,
                database_guid,
                json.dumps(resource_families),
            )
        finally:
            cursor.close()
        return versions

    @staticmethod
    def _coalesce_records(records: list[_RecordedMutation]):
        by_resource = {}
        for record in records:
            by_resource[record.resource] = record
        coalesced = tuple(by_resource[key] for key in sorted(by_resource))
        if len(coalesced) <= 450:
            return coalesced
        families = {}
        for record in coalesced:
            family = coalesced_resource_type(record.resource.resource_type)
            family_definition = resource_definition(family)
            bid_uid = record.resource.bid_uid if family_definition.bid_scoped else None
            resource_id = str(bid_uid) if bid_uid is not None else "database"
            key = (family, bid_uid)
            families[key] = _RecordedMutation(
                ResourceRef(
                    family,
                    resource_id,
                    bid_uid,
                ),
                ChangeOperation.BULK_REFRESH,
            )
        family_records = tuple(
            families[key]
            for key in sorted(families, key=lambda item: (item[0], str(item[1])))
        )
        if len(family_records) <= 450:
            return family_records
        return tuple(
            _RecordedMutation(
                ResourceRef(resource_type, "database"),
                ChangeOperation.BULK_REFRESH,
            )
            for resource_type in sorted(
                {record.resource.resource_type for record in family_records}
            )
        )

    def _require_active_session(self, database_id: str) -> str:
        try:
            return self._session_registry.require(database_id)
        except RuntimeError as exc:
            raise SqlInfrastructureError(
                SqlErrorDetails(SqlErrorCode.SESSION_EXPIRED, str(exc))
            ) from None

    @staticmethod
    def _require_sql_client_editability(lease) -> None:
        cursor = lease.cursor()
        try:
            require_sql_client_editability(cursor)
        except pyodbc.Error:
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.SCHEMA_MISMATCH,
                    "This SQL database is not writable by this OST Visualizer version.",
                )
            ) from None
        finally:
            cursor.close()

    def _next_uid(self, cursor, table: str) -> int:
        del cursor, table
        with self._identity_lock:
            return _DeferredIdentity(next(self._identity_placeholders))

    def _execute_insert_values(
        self,
        cursor,
        schema,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> Optional[int]:
        filtered = self._filter_existing_write_values(
            schema, table, values, required_columns, operation
        )
        missing = [
            column
            for column in required_columns
            if column != "UID" and column not in filtered
        ]
        if missing:
            raise sql_schema_mismatch(
                f"This OST database is missing required writable columns "
                f"{table}.{', '.join(missing)} for {operation}."
            )
        identity = filtered.pop("UID", None)
        resolved_values = {
            column: self._resolve_deferred(value) for column, value in filtered.items()
        }
        if not resolved_values:
            raise sql_schema_mismatch(
                f"This OST database has no writable columns for {operation}."
            )
        columns = ", ".join(f"[{column}]" for column in resolved_values)
        placeholders = ", ".join("?" for _ in resolved_values)
        cursor.execute(
            f"INSERT INTO [dbo].[{table}] ({columns}) "
            f"OUTPUT INSERTED.[UID] VALUES ({placeholders})",
            list(resolved_values.values()),
        )
        row = cursor.fetchone()
        generated = int(row[0]) if row is not None else None
        if isinstance(identity, _DeferredIdentity) and generated is not None:
            identity.bind(generated)
        return generated

    def _filter_existing_write_values(
        self,
        schema,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> dict:
        del operation
        schema.require_table(table)
        self._require_write_columns(schema, table, required_columns)
        missing = [
            column for column in values if not schema.column_exists(table, column)
        ]
        if missing:
            raise sql_schema_mismatch(
                f"The current SQL schema is missing {table}.{', '.join(missing)}."
            )
        return dict(values)

    def _schema(self, connection) -> CurrentSqlWriteSchema:
        del connection
        return self._write_schema

    def create_project(self, db_path: str, name: str) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidProjects", ("UID", "Name"))
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO [dbo].[BidProjects] ([Name]) "
                        "OUTPUT INSERTED.[UID] VALUES (?)",
                        name,
                    )
                    row = cursor.fetchone()
                    return str(row[0]) if row is not None else None
        except (OSError, RuntimeError, TypeError, ValueError):
            self.logger.exception("Failed to create SQL project in %s", db_path)
            return None

    def import_ost_data(
        self,
        db_path: str,
        raw_data: RawBidData,
        transform_fn,
        target_project_uid: Optional[str] = None,
    ) -> bool:
        with self._connection(db_path) as connection:
            cdn_map = self._resolve_global_by_column(
                connection, raw_data, "CdnTypes", "Name"
            )
            status_map = self._resolve_global_by_column(
                connection, raw_data, "JobStatuses", "Name"
            )
            access_map = self._resolve_global_by_column(
                connection, raw_data, "AccessLevels", "Description"
            )
            pay_class_map = self._resolve_global_by_column(
                connection, raw_data, "PayClasses", "Name"
            )
            employee_map = self._resolve_sql_employees(
                connection, raw_data, pay_class_map, access_map
            )
            remapped = transform_fn(
                raw_data,
                0,
                cdn_map,
                status_map,
                employee_map,
                pay_class_map,
            )
            self._assign_next_bid_no(connection, remapped)
            remapped.bid_row["BidProjectUID"] = (
                target_project_uid if target_project_uid else None
            )
            self._write_remapped_identity_graph(connection, remapped)
        return True

    def _resolve_global_by_column(
        self,
        connection,
        raw_data: RawBidData,
        table: str,
        identity_column: str,
    ) -> dict[str, str]:
        incoming = raw_data.global_tables.get(table, [])
        if not incoming:
            return {}
        existing = self._load_existing_uid_by_column(connection, table, identity_column)
        result: dict[str, str] = {}
        table_info = self._get_table_info(connection, table)
        for row in incoming:
            old_uid = str(row.get("UID", ""))
            identity = str(row.get(identity_column, ""))
            if identity in existing:
                result[old_uid] = existing[identity]
                continue
            actual = self._insert_identity_raw(connection, table, row, table_info)
            result[old_uid] = str(actual)
            existing[identity] = str(actual)
        return result

    def _resolve_sql_employees(
        self,
        connection,
        raw_data: RawBidData,
        pay_class_map: dict[str, str],
        access_map: dict[str, str],
    ) -> dict[str, str]:
        incoming = raw_data.global_tables.get("Employees", [])
        if not incoming:
            return {}
        existing = self._load_existing_employee_uid_by_key(connection)
        table_info = self._get_table_info(connection, "Employees")
        result: dict[str, str] = {}
        for row in incoming:
            old_uid = str(row.get("UID", ""))
            key = self._employee_identity_key(row)
            if key and key in existing:
                result[old_uid] = existing[key]
                continue
            insert_row = dict(row)
            for column, mapping in (
                ("PayClassUID", pay_class_map),
                ("AccessLevelUID", access_map),
            ):
                source_value = insert_row.get(column)
                if source_value in (None, "", "0", "NULL"):
                    insert_row[column] = None
                    continue
                source = str(source_value)
                mapped_uid = mapping.get(source)
                if mapped_uid is None:
                    raise RuntimeError(
                        f"Imported employee references an unknown {column}."
                    )
                insert_row[column] = mapped_uid
            actual = self._insert_identity_raw(
                connection, "Employees", insert_row, table_info
            )
            result[old_uid] = str(actual)
            if key:
                existing[key] = str(actual)
        return result

    def _write_remapped_identity_graph(self, connection, remapped: RawBidData) -> None:
        rows_by_table: list[tuple[str, dict]] = [("Bids", remapped.bid_row)]
        rows_by_table.extend(
            (table, row)
            for table in BID_TABLES_WRITE_ORDER
            for row in remapped.bid_tables.get(table, [])
        )
        rows_by_table.extend(
            (table, row)
            for table in PAGE_SECTIONS
            for row in remapped.page_tables.get(table, [])
        )
        internal_uids = {
            (table, str(row.get("UID")))
            for table, row in rows_by_table
            if row.get("UID") not in (None, "", "0", "NULL")
        }
        identity_map: dict[tuple[str, str], int] = {}
        pending: list[tuple[str, int, str, str, str]] = []
        table_info_cache = {}
        actual_bid_uid: Optional[int] = None
        for table, row in rows_by_table:
            table_info = table_info_cache.get(table)
            if table_info is None:
                table_info = self._get_table_info(connection, table)
                table_info_cache[table] = table_info
            source_uid = str(row.get("UID", ""))
            insert_row = dict(row)
            unresolved_columns: list[tuple[str, str, str]] = []
            for column, value in list(insert_row.items()):
                if table != "Bids" and column == "BidUID":
                    continue
                parent_table = _IMPORT_PARENT_TABLE_BY_REFERENCE.get((table, column))
                if parent_table is None:
                    continue
                raw_reference = str(value or "")
                reference_key = (parent_table, raw_reference)
                if raw_reference in ("", "0", "NULL"):
                    insert_row[column] = None
                elif reference_key in identity_map:
                    insert_row[column] = identity_map[reference_key]
                elif reference_key in internal_uids:
                    insert_row[column] = None
                    unresolved_columns.append((column, parent_table, raw_reference))
            if table != "Bids" and "BidUID" in table_info[0]:
                if actual_bid_uid is None:
                    raise RuntimeError(
                        "Imported bid identity was not allocated before child rows."
                    )
                insert_row["BidUID"] = actual_bid_uid
            actual_uid = self._insert_identity_raw(
                connection, table, insert_row, table_info
            )
            if table == "Bids":
                actual_bid_uid = actual_uid
            if source_uid:
                identity_map[(table, source_uid)] = actual_uid
            pending.extend(
                (table, actual_uid, column, parent_table, raw_reference)
                for column, parent_table, raw_reference in unresolved_columns
            )
        cursor = connection.cursor()
        try:
            for table, row_uid, column, parent_table, target_source_uid in pending:
                target_uid = identity_map.get((parent_table, target_source_uid))
                if target_uid is None:
                    raise RuntimeError(
                        f"Unresolved imported reference {table}.{column}"
                    )
                cursor.execute(
                    f"UPDATE [dbo].[{table}] SET [{column}]=? WHERE [UID]=?",
                    target_uid,
                    row_uid,
                )
        finally:
            cursor.close()

    def _insert_identity_raw(
        self,
        connection,
        table: str,
        row: dict,
        table_info,
    ) -> int:
        db_columns, column_types = table_info
        unknown_columns = set(row) - db_columns
        if unknown_columns:
            raise RuntimeError(
                f"Imported {table} row contains unsupported columns: "
                + ", ".join(sorted(unknown_columns))
            )
        filtered = {column: value for column, value in row.items() if column != "UID"}
        if not filtered:
            raise RuntimeError(f"No importable columns for {table}")
        columns = list(filtered)
        values = [
            self._convert_sql_import_value(
                filtered[column], column_types.get(column, "")
            )
            for column in columns
        ]
        cursor = connection.cursor()
        try:
            column_sql = ", ".join(f"[{column}]" for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            cursor.execute(
                f"INSERT INTO [dbo].[{table}] ({column_sql}) "
                f"OUTPUT INSERTED.[UID] VALUES ({placeholders})",
                values,
            )
            result = cursor.fetchone()
            if result is None:
                raise RuntimeError(f"SQL Server did not return an identity for {table}")
            return int(result[0])
        finally:
            cursor.close()

    def _convert_sql_import_value(self, value, type_name: str):
        if value is not None and not isinstance(value, str):
            return value
        normalized = type_name.casefold()
        if normalized == "datetime2":
            converted = self._convert_access_value(value, "datetime")
            if converted is None and value not in (None, "", "NULL"):
                raise ValueError("Imported date value is invalid")
            return converted
        if normalized == "varbinary":
            return self._convert_access_value(value, "longbinary")
        if value is None or value == "NULL":
            return None
        if normalized in {"int", "smallint", "bigint"}:
            return int(value) if value != "" else None
        if normalized == "float":
            return float(value) if value != "" else None
        if normalized == "bit":
            if value in {"True", "true", "-1", "1"}:
                return True
            if value in {"False", "false", "0", ""}:
                return False
            raise ValueError("Imported Boolean value is invalid")
        if normalized in {"nvarchar", "varchar", "char"}:
            return value
        raise RuntimeError(f"Unsupported SQL import type: {type_name}")

    def _get_table_info(self, connection, table: str):
        del connection
        return self._write_schema.table_info(table)

    def _assign_next_bid_no(self, connection, remapped: RawBidData) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT [NextBidNo] FROM [dbo].[Settings]")
            row = cursor.fetchone()
            if row is None or row[0] is None:
                raise RuntimeError("The current SQL database has no bid sequence.")
            next_bid_no = int(row[0])
            cursor.execute("UPDATE [dbo].[Settings] SET [NextBidNo]=?", next_bid_no + 1)
        finally:
            cursor.close()
        remapped.bid_row["BidNo"] = str(next_bid_no)

    def _load_existing_uid_by_column(
        self, connection, table: str, column: str
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT [UID], [{column}] FROM [dbo].[{table}]")
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return {str(row[1]) if row[1] is not None else "": str(row[0]) for row in rows}

    def _load_existing_employee_uid_by_key(self, connection) -> dict[str, str]:
        columns = ("UID", "EmployeeNo", "FirstName", "LastName", "EMail")
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT [UID], [EmployeeNo], [FirstName], [LastName], [EMail] "
                "FROM [dbo].[Employees]"
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()
        result: dict[str, str] = {}
        for row in rows:
            row_data = {
                column: str(row[index]) if row[index] is not None else ""
                for index, column in enumerate(columns)
            }
            key = self._employee_identity_key(row_data)
            if key:
                result[key] = row_data["UID"]
        return result

    def _insert_page_area_selection(
        self,
        cursor,
        schema,
        page_uid: int,
        area_uid: int | None,
        selected_value: int,
    ) -> None:
        self._execute_insert_values(
            cursor,
            schema,
            "BidPageSettings",
            {
                "UID": self._next_uid(cursor, "BidPageSettings"),
                "BidPageUID": page_uid,
                "BidAreaUID": area_uid,
                "BidAreaSelected": selected_value,
            },
            ("UID", "BidPageUID", "BidAreaSelected"),
            "insert_page_area_selection",
        )

    @staticmethod
    def _resolve_deferred(value):
        if isinstance(value, _DeferredIdentity):
            return value.resolved
        return value
