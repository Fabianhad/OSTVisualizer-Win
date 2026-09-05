from __future__ import annotations
import itertools
import contextvars
import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Generator, Optional, Sequence, TypeVar
import pyodbc
from ...application.dtos.collaboration_resource_catalog import (
    CollaborationResourceType,
    annotation_resource_id,
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
    MutationOutcomeStatus,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ...application.interfaces.i_database_mutation_executor import IMutationRecorder
from ...domain.dtos.raw_bid_data_dto import RawBidData
from ..mdb.components.constants import (
    BID_TABLES_WRITE_ORDER,
    TAKEOFF_ANNOTATION_REFERENCE_COLUMNS,
    TAKEOFF_REFERENCE_TABLES,
    TAKEOFF_SELF_REFERENCE_COLUMNS,
)
from ..database.annotation_storage import ANNOTATION_TYPE_BY_TABLE
from ..database.master_data_identity import (
    MasterDataCandidateIndex,
    add_master_data_candidate,
    build_master_data_candidate_index,
    master_data_identity_key,
    require_unambiguous_incoming_identities,
    require_unique_master_data_uids,
    resolve_master_data_candidate,
)
from ..database.settings_cardinality import (
    fetch_optional_global_settings_row,
    normalize_next_bid_number,
    persist_next_bid_number,
)
from ..mdb.raw_bid_integrity import RAW_BID_RELATIONSHIPS
from ..mdb.schema_contract import PAGE_SECTIONS
from ..mdb.mdb_writer import MdbWriter
from ..database.schema_inspector_contract import IDatabaseSchemaInspector
from .connection_manager import SqlConnectionLease, SqlConnectionManager
from .database_metadata_contract import (
    DATABASE_METADATA_CURRENT_DATABASE_PREDICATE,
)
from .client_permissions import require_sql_client_editability
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
    sql_schema_mismatch,
)
from .schema_definition import SQL_SCHEMA_V1
from .schema_lock import (
    acquire_resource_transaction_locks,
)
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
    transaction_id: str = ""
    records: list[_RecordedMutation] = field(default_factory=list)
    operation_error: Optional[BaseException] = None

    def __post_init__(self) -> None:
        self.transaction_id = self.request.operation_id

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

    @staticmethod
    def _global_settings_read_table_sql() -> str:
        return "[dbo].[Settings] WITH (UPDLOCK, HOLDLOCK)"

    @staticmethod
    def _global_settings_write_table_sql() -> str:
        return "[dbo].[Settings]"

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
            try:
                yield active.lease
            except Exception as exc:
                if active.operation_error is None:
                    active.operation_error = exc
                raise
            return
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.SESSION_EXPIRED,
                "SQL writes must run through a collaboration mutation transaction.",
            )
        )

    def verify_plan_items_exist(
        self,
        database_id: str,
        bid_uid: str,
        takeoff_uids: Sequence[str],
        annotations: Sequence[tuple[str, str]],
    ) -> None:
        with self._connection(database_id) as connection:
            schema = self._schema(connection)
            schema.require_column("BidTakeoffs", "UID")
            schema.require_column("BidTakeoffs", "BidUID")
            for column in TAKEOFF_SELF_REFERENCE_COLUMNS:
                schema.require_column("BidTakeoffs", column)
            normalized_takeoffs = tuple(dict.fromkeys(int(uid) for uid in takeoff_uids))
            normalized_annotations: dict[tuple[str, int], dict[str, object]] = {}
            for uid, annotation_type in annotations:
                table = self._ANNOTATION_TABLE.get(str(annotation_type))
                if not table:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.CONFLICT,
                            "An annotation changed or was deleted before this "
                            "operation started.",
                        )
                    )
                schema.require_column(table, "UID")
                schema.require_column(table, "BidUID")
                annotation_uid = int(uid)
                normalized_annotations[(table, annotation_uid)] = {
                    "table": table,
                    "uid": annotation_uid,
                }
            annotation_tables = tuple(
                sorted({table for table, _uid in normalized_annotations})
            )
            missing_annotation_predicate = (
                " OR ".join(
                    "(requested.[TableName]=N'"
                    + table
                    + "' AND NOT EXISTS (SELECT 1 FROM ["
                    + table
                    + "] target WITH (UPDLOCK, HOLDLOCK) "
                    "WHERE target.[UID]=requested.[UID] AND "
                    "target.[BidUID]=@ExpectedBidUID))"
                    for table in annotation_tables
                )
                or "1=0"
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET NOCOUNT ON; DECLARE @ExpectedBidUID bigint=?; "
                    "DECLARE @RequestedTakeoffs TABLE "
                    "([UID] bigint NOT NULL PRIMARY KEY); INSERT INTO "
                    "@RequestedTakeoffs ([UID]) SELECT source.[UID] FROM "
                    "OPENJSON(?) WITH ([UID] bigint '$') source; DECLARE "
                    "@RequestedAnnotations TABLE ([TableName] nvarchar(128) "
                    "NOT NULL, [UID] bigint NOT NULL, PRIMARY KEY "
                    "([TableName], [UID])); INSERT INTO @RequestedAnnotations "
                    "([TableName], [UID]) SELECT source.[TableName], source.[UID] "
                    "FROM OPENJSON(?) WITH ([TableName] nvarchar(128) '$.table', "
                    "[UID] bigint '$.uid') source; DECLARE @Status int=0; "
                    "IF EXISTS (SELECT 1 FROM @RequestedTakeoffs requested "
                    "LEFT JOIN [BidTakeoffs] target WITH (UPDLOCK, HOLDLOCK) "
                    "ON target.[UID]=requested.[UID] WHERE target.[UID] IS NULL "
                    "OR target.[BidUID]<>@ExpectedBidUID) "
                    "SET @Status=1; ELSE IF EXISTS (SELECT 1 FROM [BidTakeoffs] "
                    "child WITH (UPDLOCK, HOLDLOCK) JOIN @RequestedTakeoffs parent "
                    "ON parent.[UID]=child.[ParentUID] LEFT JOIN "
                    "@RequestedTakeoffs selected ON selected.[UID]=child.[UID] "
                    "WHERE selected.[UID] IS NULL) SET @Status=2; ELSE IF EXISTS "
                    "(SELECT 1 FROM @RequestedAnnotations requested WHERE "
                    f"{missing_annotation_predicate}) SET @Status=3; "
                    "SELECT @Status",
                    int(bid_uid),
                    json.dumps(normalized_takeoffs, separators=(",", ":")),
                    json.dumps(
                        tuple(normalized_annotations.values()),
                        separators=(",", ":"),
                    ),
                )
                row = cursor.fetchone()
            if row is None:
                raise RuntimeError("SQL plan-item validation returned no result.")
            status = int(row[0])
            if status == 1:
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CONFLICT,
                        "A takeoff changed or was deleted before this operation "
                        "started.",
                    )
                )
            if status == 2:
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CONFLICT,
                        "The takeoff relationship graph changed before deletion.",
                    )
                )
            if status == 3:
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CONFLICT,
                        "An annotation changed or was deleted before this "
                        "operation started.",
                    )
                )
            if status != 0:
                raise RuntimeError(
                    "SQL plan-item validation returned an invalid result."
                )

    def _run_delete_takeoffs(
        self, database_id: str, uids: list[int], chunk_size: int
    ) -> None:
        del chunk_size
        if not uids:
            return
        with self._connection(database_id) as connection:
            schema = self._schema(connection)
            schema.require_column("BidTakeoffs", "UID")
            schema.require_column("BidTakeoffs", "ParentUID")
            schema.require_column("BidPercents", "BidTakeoffUID")
            for table in TAKEOFF_REFERENCE_TABLES:
                for column in TAKEOFF_ANNOTATION_REFERENCE_COLUMNS:
                    schema.require_column(table, column)
            requested_reference_match = " OR ".join(
                "requested.[UID]=target.[" + column + "]"
                for column in TAKEOFF_ANNOTATION_REFERENCE_COLUMNS
            )
            reference_deletes = " ".join(
                "DELETE target FROM ["
                + table
                + "] target WHERE EXISTS (SELECT 1 FROM @Requested requested "
                "WHERE " + requested_reference_match + "); SET @Affected+="
                "@@ROWCOUNT;"
                for table in TAKEOFF_REFERENCE_TABLES
            )
            self_reference_updates = " ".join(
                "UPDATE child SET ["
                + column
                + "]=NULL FROM [BidTakeoffs] child WHERE EXISTS (SELECT 1 "
                "FROM @Requested requested WHERE requested.[UID]=child.["
                + column
                + "]); SET @Affected+=@@ROWCOUNT;"
                for column in TAKEOFF_SELF_REFERENCE_COLUMNS
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET NOCOUNT ON; DECLARE @Requested TABLE ([UID] bigint "
                    "NOT NULL PRIMARY KEY); INSERT INTO @Requested ([UID]) "
                    "SELECT source.[UID] FROM OPENJSON(?) WITH ([UID] bigint '$') "
                    f"source; DECLARE @Affected int=0; {reference_deletes} "
                    "DELETE target FROM [BidPercents] target WHERE EXISTS "
                    "(SELECT 1 FROM @Requested requested WHERE requested.[UID]="
                    "target.[BidTakeoffUID]); SET @Affected+=@@ROWCOUNT; "
                    f"{self_reference_updates} "
                    "DECLARE @Expected int=(SELECT COUNT(*) FROM @Requested); "
                    "DELETE target FROM [BidTakeoffs] target JOIN @Requested "
                    "requested ON requested.[UID]=target.[UID]; DECLARE @Deleted "
                    "int=@@ROWCOUNT; SET @Affected+=@Deleted; IF @Deleted<>"
                    "@Expected THROW 51000, 'The takeoff deletion was incomplete.', "
                    "1; SELECT @Affected",
                    json.dumps(tuple(dict.fromkeys(uids)), separators=(",", ":")),
                )
                affected = cursor.fetchone()
            if affected is None:
                raise RuntimeError("SQL takeoff deletion returned no result.")

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
                    if request.resources and exc.details.code == SqlErrorCode.LOCKED
                    else ResourceRef(
                        CollaborationResourceType.DATABASE.value,
                        request.database_id,
                    )
                )
            )
            return DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.CONFLICT,
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
                    kind=(
                        SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY
                        if isinstance(exc, _OptimisticConflict)
                        else (
                            SynchronizationConflictKind.LEASE
                            if exc.details.code == SqlErrorCode.LOCKED
                            else SynchronizationConflictKind.SESSION
                        )
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
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.SESSION_EXPIRED,
                    "The SQL collaboration session changed before the write.",
                )
            )
        connection_request = self._requests.request(
            request.database_id, read_only=False
        )
        with self._sql_connections.connection(
            connection_request, autocommit=False
        ) as lease:
            transaction_finished = False
            commit_attempted = False
            try:
                state = _SqlMutationState(request.database_id, lease, request)
                self._require_sql_client_editability(lease, state)
                recovered = self._prepare_mutation(state)
                if recovered is not None:
                    lease.rollback()
                    transaction_finished = True
                    return recovered
                token = self._active_mutation.set(state)
                try:
                    value = operation(state)
                finally:
                    self._active_mutation.reset(token)
                if state.operation_error is not None:
                    raise state.operation_error
                if not state.records:
                    raise RuntimeError(
                        "The SQL mutation did not record an affected resource."
                    )
                versions = self._finish_mutation(state, value)
                commit_attempted = True
                try:
                    lease.commit()
                except Exception:
                    transaction_finished = True
                    return DatabaseMutationResult(
                        operation_id=request.operation_id,
                        outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                        commit_attempted=True,
                    )
                transaction_finished = True
                return DatabaseMutationResult(
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    value=value,
                    resulting_versions=versions,
                    commit_attempted=True,
                    consumed_lock_tokens=tuple(request.required_lock_tokens),
                )
            finally:
                if not transaction_finished and not commit_attempted:
                    try:
                        lease.rollback()
                    except pyodbc.Error:
                        pass
                self._clear_session_context(lease)

    @staticmethod
    def _clear_session_context(lease: SqlConnectionLease) -> None:
        try:
            with lease.cursor() as cursor:
                cursor.execute(
                    "EXEC sys.sp_set_session_context "
                    "@key=N'ostv_session_id', @value=NULL; "
                    "EXEC sys.sp_set_session_context "
                    "@key=N'ostv_transaction_id', @value=NULL"
                )
        except (pyodbc.Error, RuntimeError):
            return

    def _prepare_mutation(
        self, state: _SqlMutationState
    ) -> Optional[DatabaseMutationResult]:
        cursor = state.lease.cursor()
        try:
            cursor.execute(
                "DECLARE @LockResult int; EXEC @LockResult=sys.sp_getapplock "
                "@Resource=?, @LockMode=N'Exclusive', "
                "@LockOwner=N'Transaction', @LockTimeout=10000; SELECT "
                "@LockResult, marker.[OperationType], marker.[RequestHash], "
                "marker.[ResultFormatVersion], marker.[ResultPayload], "
                "CASE WHEN EXISTS (SELECT 1 FROM [ostv].[Sessions] sessions "
                "WHERE sessions.[SessionId]=? AND "
                "sessions.[DisconnectedAt] IS NULL AND "
                "sessions.[LastHeartbeatAt]>=DATEADD(second, ?, "
                "SYSUTCDATETIME())) THEN 1 ELSE 0 END FROM (VALUES (1)) "
                "seed([Value]) LEFT JOIN [ostv].[ChangeTransactions] marker "
                "ON marker.[TransactionId]=?",
                f"OSTV:operation:{state.request.operation_id}",
                state.request.session_id,
                -COLLABORATION_STALE_SECONDS,
                state.request.operation_id,
            )
            operation_context = cursor.fetchone()
            if operation_context is None or int(operation_context[0]) < 0:
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.LOCKED,
                        "Another session is resolving the same SQL operation.",
                    )
                )
            if operation_context[1] is not None:
                return self._recovered_operation_result(state, operation_context[1:5])
            if int(operation_context[5]) != 1:
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
            ordered_locks = tuple(
                (resource, lock_modes[resource])
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
                )
            )
            acquire_resource_transaction_locks(cursor, ordered_locks)
            self._validate_mutation_locks(state, cursor, resources)
        finally:
            cursor.close()
        return None

    @staticmethod
    def _validate_mutation_locks(state, cursor, resources) -> None:
        resource_payload = json.dumps(
            [
                {
                    "ordinal": ordinal,
                    "resource_type": resource.resource_type,
                    "resource_id": resource.resource_id,
                    "bid_uid": resource.bid_uid,
                }
                for ordinal, resource in enumerate(sorted(resources))
            ],
            separators=(",", ":"),
        )
        token_payload = json.dumps(
            sorted({token.casefold() for token in state.request.required_lock_tokens}),
            separators=(",", ":"),
        )
        expected_versions = tuple(state.request.expected_versions)
        expected_version_payload = json.dumps(
            [
                {
                    "ordinal": ordinal,
                    "resource_type": expected.resource.resource_type,
                    "resource_id": expected.resource.resource_id,
                    "expected_token": str(expected.expected),
                }
                for ordinal, expected in enumerate(expected_versions)
            ],
            separators=(",", ":"),
        )
        cursor.execute(
            "SET NOCOUNT ON; DECLARE @MutationResources TABLE ("
            "[Ordinal] int NOT NULL PRIMARY KEY, "
            "[ResourceType] nvarchar(64) NOT NULL, "
            "[ResourceId] nvarchar(128) NOT NULL, [BidUID] int NULL); "
            "INSERT INTO @MutationResources SELECT [Ordinal], [ResourceType], "
            "[ResourceId], [BidUID] FROM OPENJSON(?) WITH ("
            "[Ordinal] int '$.ordinal', "
            "[ResourceType] nvarchar(64) '$.resource_type', "
            "[ResourceId] nvarchar(128) '$.resource_id', "
            "[BidUID] int '$.bid_uid'); "
            "DECLARE @RequiredTokens TABLE ([LockToken] nvarchar(36) NOT NULL "
            "PRIMARY KEY); INSERT INTO @RequiredTokens SELECT LOWER([value]) "
            "FROM OPENJSON(?); DECLARE @ExpectedVersions TABLE ("
            "[Ordinal] int NOT NULL PRIMARY KEY, "
            "[ResourceType] nvarchar(64) NOT NULL, "
            "[ResourceId] nvarchar(128) NOT NULL, "
            "[ExpectedToken] varbinary(8) NOT NULL); "
            "INSERT INTO @ExpectedVersions SELECT [Ordinal], [ResourceType], "
            "[ResourceId], CONVERT(varbinary(8), [ExpectedTokenHex], 2) FROM "
            "OPENJSON(?) WITH ([Ordinal] int '$.ordinal', "
            "[ResourceType] nvarchar(64) '$.resource_type', "
            "[ResourceId] nvarchar(128) '$.resource_id', "
            "[ExpectedTokenHex] varchar(16) '$.expected_token'); "
            "WITH Violations AS ("
            "SELECT resources.[Ordinal]*10 AS [Priority], N'item_owner' AS [Kind], "
            "sessions.[DisplayName] AS [Owner], NULL AS [ExpectedOrdinal], "
            "CONVERT(varbinary(8), NULL) AS [ActualToken] "
            "FROM @MutationResources resources "
            "JOIN [ostv].[Locks] locks ON "
            "locks.[ResourceType]=resources.[ResourceType] AND "
            "locks.[ResourceId]=resources.[ResourceId] JOIN [ostv].[Sessions] "
            "sessions ON sessions.[SessionId]=locks.[OwnerSessionId] WHERE "
            "locks.[OwnerSessionId]<>? AND locks.[ExpiresAt]>SYSUTCDATETIME() "
            "UNION ALL SELECT resources.[Ordinal]*10+1, N'bid_owner', "
            "sessions.[DisplayName], NULL, NULL FROM @MutationResources resources "
            "JOIN [ostv].[Locks] locks ON locks.[ResourceType]=N'bid' AND "
            "locks.[ResourceId]=CONVERT(nvarchar(128), resources.[BidUID]) "
            "JOIN [ostv].[Sessions] sessions ON "
            "sessions.[SessionId]=locks.[OwnerSessionId] WHERE "
            "resources.[BidUID] IS NOT NULL AND resources.[ResourceType]<>N'bid' "
            "AND locks.[OwnerSessionId]<>? AND "
            "locks.[ExpiresAt]>SYSUTCDATETIME() "
            "UNION ALL SELECT resources.[Ordinal]*10+2, N'child_owner', "
            "sessions.[DisplayName], NULL, NULL FROM @MutationResources resources "
            "JOIN [ostv].[Locks] locks ON locks.[BidUID]=resources.[BidUID] "
            "JOIN [ostv].[Sessions] sessions ON "
            "sessions.[SessionId]=locks.[OwnerSessionId] WHERE ?=1 AND "
            "resources.[ResourceType]=N'bid' AND locks.[OwnerSessionId]<>? "
            "AND locks.[ExpiresAt]>SYSUTCDATETIME() "
            "UNION ALL SELECT resources.[Ordinal]*10+3, N'active_editor', "
            "sessions.[DisplayName], NULL, NULL FROM @MutationResources resources "
            "JOIN [ostv].[Presence] presence ON "
            "presence.[BidUID]=resources.[BidUID] JOIN [ostv].[Sessions] sessions "
            "ON sessions.[SessionId]=presence.[SessionId] WHERE ?=1 AND "
            "resources.[ResourceType]=N'bid' AND "
            "presence.[ActivityMode]=N'editing' AND presence.[SessionId]<>? "
            "AND sessions.[DisconnectedAt] IS NULL AND "
            "sessions.[LastHeartbeatAt]>=DATEADD(second, ?, SYSUTCDATETIME()) "
            "UNION ALL SELECT 100000, N'token_expired', NULL, NULL, NULL FROM "
            "@RequiredTokens tokens LEFT JOIN [ostv].[Locks] locks ON "
            "LOWER(CONVERT(nvarchar(36), locks.[LockToken]))=tokens.[LockToken] "
            "AND locks.[OwnerSessionId]=? AND "
            "locks.[ExpiresAt]>SYSUTCDATETIME() WHERE locks.[LockToken] IS NULL "
            "UNION ALL SELECT 100001, N'token_resource', NULL, NULL, NULL FROM "
            "@RequiredTokens tokens JOIN [ostv].[Locks] locks ON "
            "LOWER(CONVERT(nvarchar(36), locks.[LockToken]))=tokens.[LockToken] "
            "AND locks.[OwnerSessionId]=? AND locks.[ExpiresAt]>SYSUTCDATETIME() "
            "WHERE NOT EXISTS (SELECT 1 FROM @MutationResources resources "
            "WHERE resources.[ResourceType]=locks.[ResourceType] AND "
            "resources.[ResourceId]=locks.[ResourceId]) "
            "UNION ALL SELECT 100010+resources.[Ordinal], N'owned_omitted', "
            "NULL, NULL, NULL "
            "FROM @MutationResources resources JOIN [ostv].[Locks] locks ON "
            "locks.[ResourceType]=resources.[ResourceType] AND "
            "locks.[ResourceId]=resources.[ResourceId] AND "
            "locks.[OwnerSessionId]=? AND locks.[ExpiresAt]>SYSUTCDATETIME() "
            "LEFT JOIN @RequiredTokens tokens ON tokens.[LockToken]="
            "LOWER(CONVERT(nvarchar(36), locks.[LockToken])) "
            "WHERE tokens.[LockToken] IS NULL "
            "UNION ALL SELECT 200000+expected.[Ordinal], N'rowversion', NULL, "
            "expected.[Ordinal], versions.[Token] FROM @ExpectedVersions expected "
            "LEFT JOIN [ostv].[EntityVersions] versions WITH (UPDLOCK, HOLDLOCK) "
            "ON versions.[ResourceType]=expected.[ResourceType] AND "
            "versions.[ResourceId]=expected.[ResourceId] WHERE "
            "versions.[Token] IS NULL OR versions.[Token]<>expected.[ExpectedToken]) "
            "SELECT TOP (1) [Kind], [Owner], [ExpectedOrdinal], [ActualToken] "
            "FROM Violations ORDER BY [Priority]",
            resource_payload,
            token_payload,
            expected_version_payload,
            state.request.session_id,
            state.request.session_id,
            state.request.block_bid_child_locks,
            state.request.session_id,
            state.request.block_bid_active_editors,
            state.request.session_id,
            -COLLABORATION_STALE_SECONDS,
            state.request.session_id,
            state.request.session_id,
            state.request.session_id,
        )
        violation = cursor.fetchone()
        if violation is None:
            return
        kind = str(violation[0])
        if kind == "rowversion":
            ordinal = int(violation[2])
            if ordinal < 0 or ordinal >= len(expected_versions):
                raise RuntimeError(
                    "The SQL rowversion validation batch returned an invalid ordinal."
                )
            expected = expected_versions[ordinal]
            actual = (
                ConcurrencyToken.from_database(violation[3])
                if violation[3] is not None
                else None
            )
            raise _OptimisticConflict(expected.resource, expected.expected, actual)
        owner = str(violation[1]) if violation[1] is not None else ""
        messages = {
            "item_owner": f"This item is being edited by {owner}.",
            "bid_owner": f"This bid is being changed by {owner}.",
            "child_owner": f"This bid contains an item being edited by {owner}.",
            "active_editor": f"This bid is actively being edited by {owner}.",
            "token_expired": "A required SQL edit lock expired before the write.",
            "token_resource": "A SQL edit lock does not belong to this mutation.",
            "owned_omitted": "The mutation did not present its owned SQL edit lock.",
        }
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.LOCKED,
                messages.get(kind, "SQL edit-lock validation failed."),
            )
        )

    def _finish_mutation(self, state: _SqlMutationState, value=None):
        entity_records = self._deduplicate_records(state.records)
        feed_records = self._coalesce_records(entity_records)
        version_records = self._deduplicate_records([*entity_records, *feed_records])
        feed_by_resource = {record.resource: record for record in feed_records}
        changes = [
            {
                "ordinal": ordinal,
                "resource_type": record.resource.resource_type,
                "resource_id": record.resource.resource_id,
                "bid_uid": record.resource.bid_uid,
                "is_deleted": record.operation == ChangeOperation.DELETE,
                "is_feed": record.resource in feed_by_resource,
                "operation": feed_by_resource.get(
                    record.resource, record
                ).operation.value,
                "changed_fields": (
                    json.dumps(feed_by_resource[record.resource].changed_fields)
                    if record.resource in feed_by_resource
                    and feed_by_resource[record.resource].changed_fields
                    else None
                ),
                "payload": (
                    feed_by_resource[record.resource].payload or None
                    if record.resource in feed_by_resource
                    else None
                ),
            }
            for ordinal, record in enumerate(version_records)
        ]
        resource_families = sorted(
            {
                coalesced_resource_type(record.resource.resource_type)
                for record in feed_records
            }
        )
        result_payload = self._serialize_operation_result(value)
        cursor = state.lease.cursor()
        try:
            cursor.execute(
                "SET NOCOUNT ON; "
                "DECLARE @Changes TABLE ("
                "[Ordinal] int NOT NULL PRIMARY KEY, "
                "[ResourceType] nvarchar(64) NOT NULL, "
                "[ResourceId] nvarchar(128) NOT NULL, "
                "[BidUID] int NULL, [IsDeleted] bit NOT NULL, "
                "[IsFeed] bit NOT NULL, [Operation] nvarchar(32) NOT NULL, "
                "[ChangedFields] nvarchar(1024) NULL, "
                "[Payload] nvarchar(4000) NULL); "
                "INSERT INTO @Changes SELECT [Ordinal], [ResourceType], "
                "[ResourceId], [BidUID], [IsDeleted], [IsFeed], [Operation], "
                "[ChangedFields], [Payload] FROM OPENJSON(?) WITH ("
                "[Ordinal] int '$.ordinal', "
                "[ResourceType] nvarchar(64) '$.resource_type', "
                "[ResourceId] nvarchar(128) '$.resource_id', "
                "[BidUID] int '$.bid_uid', [IsDeleted] bit '$.is_deleted', "
                "[IsFeed] bit '$.is_feed', "
                "[Operation] nvarchar(32) '$.operation', "
                "[ChangedFields] nvarchar(1024) '$.changed_fields', "
                "[Payload] nvarchar(4000) '$.payload'); "
                "DECLARE @Versions TABLE ("
                "[ResourceType] nvarchar(64) NOT NULL, "
                "[ResourceId] nvarchar(128) NOT NULL, "
                "[Token] varbinary(8) NOT NULL, "
                "PRIMARY KEY ([ResourceType], [ResourceId])); "
                "UPDATE target WITH (UPDLOCK, HOLDLOCK) SET "
                "[BidUID]=source.[BidUID], [IsDeleted]=source.[IsDeleted], "
                "[ModifiedAt]=SYSUTCDATETIME(), [ModifiedBySessionId]=? "
                "OUTPUT INSERTED.[ResourceType], INSERTED.[ResourceId], "
                "INSERTED.[Token] INTO @Versions "
                "FROM [ostv].[EntityVersions] target JOIN @Changes source "
                "ON target.[ResourceType]=source.[ResourceType] AND "
                "target.[ResourceId]=source.[ResourceId]; "
                "INSERT INTO [ostv].[EntityVersions] "
                "([ResourceType], [ResourceId], [BidUID], [IsDeleted], "
                "[ModifiedBySessionId]) OUTPUT INSERTED.[ResourceType], "
                "INSERTED.[ResourceId], INSERTED.[Token] INTO @Versions "
                "SELECT source.[ResourceType], source.[ResourceId], "
                "source.[BidUID], source.[IsDeleted], ? FROM @Changes source "
                "WHERE NOT EXISTS (SELECT 1 FROM [ostv].[EntityVersions] target "
                "WITH (UPDLOCK, HOLDLOCK) WHERE "
                "target.[ResourceType]=source.[ResourceType] AND "
                "target.[ResourceId]=source.[ResourceId]); "
                "DECLARE @DatabaseGuid uniqueidentifier=(SELECT m.[DatabaseGuid] "
                "FROM [ostv].[DatabaseMetadata] m WHERE "
                + DATABASE_METADATA_CURRENT_DATABASE_PREDICATE
                + "); "
                "INSERT INTO [ostv].[ChangeLog] ([TransactionId], "
                "[SourceSessionId], [DatabaseGuid], [BidUID], [ResourceType], "
                "[ResourceId], [Operation], [ResultVersion], [ChangedFields], "
                "[Payload], [SourceKind]) SELECT ?, ?, @DatabaseGuid, "
                "source.[BidUID], source.[ResourceType], source.[ResourceId], "
                "source.[Operation], versions.[Token], source.[ChangedFields], "
                "source.[Payload], N'ost_visualizer' FROM @Changes source "
                "JOIN @Versions versions ON "
                "versions.[ResourceType]=source.[ResourceType] AND "
                "versions.[ResourceId]=source.[ResourceId] "
                "WHERE source.[IsFeed]=1 ORDER BY source.[Ordinal]; "
                "DECLARE @ConsumedTokens TABLE ([LockToken] nvarchar(36) "
                "NOT NULL PRIMARY KEY); INSERT INTO @ConsumedTokens SELECT "
                "LOWER([value]) FROM OPENJSON(?); DELETE locks FROM "
                "[ostv].[Locks] locks JOIN @ConsumedTokens tokens ON "
                "tokens.[LockToken]=LOWER(CONVERT(nvarchar(36), "
                "locks.[LockToken])) WHERE locks.[OwnerSessionId]=?; "
                "IF @@ROWCOUNT<>(SELECT COUNT(*) FROM @ConsumedTokens) "
                "THROW 51000, 'A validated SQL edit lock could not be "
                "consumed.', 1; "
                "INSERT INTO [ostv].[ChangeTransactions] "
                "([TransactionId], [SourceSessionId], [DatabaseGuid], "
                "[ResourceFamilySummary], [OperationType], [RequestHash], "
                "[ResultFormatVersion], [ResultPayload]) VALUES "
                "(?, ?, @DatabaseGuid, ?, ?, ?, ?, ?); "
                "SELECT changes.[Ordinal], versions.[Token] FROM @Changes changes "
                "JOIN @Versions versions ON "
                "versions.[ResourceType]=changes.[ResourceType] AND "
                "versions.[ResourceId]=changes.[ResourceId] "
                "ORDER BY changes.[Ordinal];",
                json.dumps(changes, separators=(",", ":")),
                state.request.session_id,
                state.request.session_id,
                state.transaction_id,
                state.request.session_id,
                json.dumps(
                    sorted(
                        token.casefold() for token in state.request.required_lock_tokens
                    ),
                    separators=(",", ":"),
                ),
                state.request.session_id,
                state.transaction_id,
                state.request.session_id,
                json.dumps(resource_families),
                state.request.mutation_type,
                state.request.request_hash,
                state.request.result_format_version,
                result_payload,
            )
            version_rows = cursor.fetchall()
        finally:
            cursor.close()
        if len(version_rows) != len(version_records):
            raise RuntimeError(
                "The SQL version/feed batch returned an incomplete authoritative result."
            )
        versions = {}
        for ordinal, token in version_rows:
            index = int(ordinal)
            if index < 0 or index >= len(version_records):
                raise RuntimeError(
                    "The SQL version/feed batch returned an invalid resource ordinal."
                )
            resource = version_records[index].resource
            if resource in versions:
                raise RuntimeError(
                    "The SQL version/feed batch returned a duplicate resource ordinal."
                )
            versions[resource] = ConcurrencyToken.from_database(token)
        if len(versions) != len(version_records):
            raise RuntimeError(
                "The SQL version/feed batch returned duplicate resource identities."
            )
        return versions

    @staticmethod
    def _serialize_operation_result(value) -> str:
        def json_safe(item):
            if item is None or isinstance(item, (bool, int, float, str)):
                return item
            if isinstance(item, (list, tuple)):
                return [json_safe(child) for child in item]
            if isinstance(item, dict):
                return {str(key): json_safe(child) for key, child in item.items()}
            raise TypeError

        payload = {"value": json_safe(value), "value_available": True}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _recovered_operation_result(
        state: _SqlMutationState, row
    ) -> DatabaseMutationResult:
        mutation_type = str(row[0])
        request_hash = str(row[1])
        result_format_version = int(row[2])
        if (
            mutation_type != state.request.mutation_type
            or request_hash != state.request.request_hash
            or result_format_version != state.request.result_format_version
        ):
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.CONFLICT,
                    "A committed SQL operation ID was reused with a different "
                    "request.",
                )
            )
        try:
            payload = json.loads(str(row[3]))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "A committed SQL operation has an invalid result payload."
            ) from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"value", "value_available"}
            or payload["value_available"] is not True
        ):
            raise RuntimeError(
                "A committed SQL operation cannot reconstruct its result payload."
            )
        return DatabaseMutationResult(
            operation_id=state.request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            value=payload["value"],
            commit_attempted=True,
        )

    @staticmethod
    def _deduplicate_records(
        records: Sequence[_RecordedMutation],
    ) -> tuple[_RecordedMutation, ...]:
        by_resource = {}
        for record in records:
            by_resource[record.resource] = record
        return tuple(by_resource[key] for key in sorted(by_resource))

    @classmethod
    def _coalesce_records(cls, records: Sequence[_RecordedMutation]):
        coalesced = cls._deduplicate_records(records)
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
    def _require_sql_client_editability(
        lease, state: Optional[_SqlMutationState] = None
    ) -> None:
        cursor = lease.cursor()
        try:
            require_sql_client_editability(
                cursor,
                session_id=state.request.session_id if state is not None else "",
                transaction_id=state.transaction_id if state is not None else "",
            )
        finally:
            cursor.close()

    def _next_uid(self, cursor, table: str) -> int:
        del cursor, table
        with self._identity_lock:
            return _DeferredIdentity(next(self._identity_placeholders))

    def _next_uid_preserving_references(self, cursor, schema, table: str) -> int:
        del schema
        return self._next_uid(cursor, table)

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

    def _schema(self, connection) -> IDatabaseSchemaInspector:
        del connection
        return self._write_schema

    def _record_caught_mutation_error(self, exc: BaseException) -> bool:
        state = self._active_mutation.get()
        if state is not None and state.operation_error is None:
            state.operation_error = exc
        return True

    @staticmethod
    def _is_access_resource_exceeded(_exc: BaseException) -> bool:
        return False

    def create_project(self, db_path: str, name: str) -> Optional[str]:
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

    def import_ost_data(
        self,
        db_path: str,
        raw_data: RawBidData,
        transform_fn,
        target_project_uid: Optional[str] = None,
    ) -> dict[str, object]:
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
            table_uid_maps = self._write_remapped_identity_graph(connection, remapped)
        annotation_uids = {
            annotation_resource_id(
                ANNOTATION_TYPE_BY_TABLE[table],
                source_uid,
            ): actual_uid
            for table, uid_map in table_uid_maps.items()
            if table in ANNOTATION_TYPE_BY_TABLE
            for source_uid, actual_uid in uid_map.items()
        }
        return {
            "project_uids": (
                {"target": str(target_project_uid)} if target_project_uid else {}
            ),
            "bid_uids": table_uid_maps.get("Bids", {}),
            "page_uids": table_uid_maps.get("BidPages", {}),
            "condition_uids": table_uid_maps.get("BidConditions", {}),
            "layer_uids": table_uid_maps.get("BidLayers", {}),
            "area_uids": table_uid_maps.get("BidAreas", {}),
            "takeoff_uids": table_uid_maps.get("BidTakeoffs", {}),
            "annotation_uids": annotation_uids,
            "table_uid_maps": table_uid_maps,
            "global_uid_maps": {
                "condition_types": cdn_map,
                "job_statuses": status_map,
                "employees": employee_map,
                "pay_classes": pay_class_map,
            },
        }

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
        ignore_empty_identity = table in {"AccessLevels", "PayClasses"}
        require_unambiguous_incoming_identities(
            incoming,
            lambda row: master_data_identity_key(
                table, identity_column, row.get(identity_column, "")
            ),
            f"{table}.{identity_column}",
            ignore_empty=ignore_empty_identity,
        )
        existing = self._load_existing_uid_candidates_by_column(
            connection, table, identity_column
        )
        result: dict[str, str] = {}
        table_info = self._get_table_info(connection, table)
        for row in incoming:
            old_uid = str(row.get("UID", ""))
            identity = master_data_identity_key(
                table, identity_column, row.get(identity_column, "")
            )
            existing_uid = (
                resolve_master_data_candidate(
                    existing, identity, f"{table}.{identity_column}"
                )
                if identity or not ignore_empty_identity
                else None
            )
            if existing_uid is not None:
                result[old_uid] = existing_uid
                continue
            actual = self._insert_identity_raw(connection, table, row, table_info)
            result[old_uid] = str(actual)
            add_master_data_candidate(existing, identity, str(actual))
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
        require_unambiguous_incoming_identities(
            incoming,
            self._employee_identity_key,
            "Employees business key",
            ignore_empty=True,
        )
        existing = self._load_existing_employee_uid_candidates_by_key(connection)
        table_info = self._get_table_info(connection, "Employees")
        result: dict[str, str] = {}
        for row in incoming:
            old_uid = str(row.get("UID", ""))
            key = self._employee_identity_key(row)
            existing_uid = (
                resolve_master_data_candidate(existing, key, "Employees business key")
                if key
                else None
            )
            if existing_uid is not None:
                result[old_uid] = existing_uid
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
                add_master_data_candidate(existing, key, str(actual))
        return result

    def _write_remapped_identity_graph(
        self, connection, remapped: RawBidData
    ) -> dict[str, dict[str, str]]:
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
        result: dict[str, dict[str, str]] = {}
        for (table, source_uid), actual_uid in identity_map.items():
            result.setdefault(table, {})[source_uid] = str(actual_uid)
        return result

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
            row = fetch_optional_global_settings_row(
                cursor,
                "[NextBidNo]",
                table_sql=self._global_settings_read_table_sql(),
            )
            next_bid_no = normalize_next_bid_number(row[0] if row is not None else None)
            persist_next_bid_number(
                cursor,
                row,
                next_bid_no + 1,
                table_sql=self._global_settings_write_table_sql(),
            )
        finally:
            cursor.close()
        remapped.bid_row["BidNo"] = str(next_bid_no)

    def _load_existing_uid_candidates_by_column(
        self, connection, table: str, column: str
    ) -> MasterDataCandidateIndex:
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT [UID], [{column}] FROM [dbo].[{table}]")
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return build_master_data_candidate_index(rows, table, column)

    def _load_existing_employee_uid_candidates_by_key(
        self, connection
    ) -> MasterDataCandidateIndex:
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
        require_unique_master_data_uids((row[0] for row in rows), "Employees")
        result: MasterDataCandidateIndex = {}
        for row in rows:
            row_data = {
                column: str(row[index]) if row[index] is not None else ""
                for index, column in enumerate(columns)
            }
            key = self._employee_identity_key(row_data)
            if key:
                add_master_data_candidate(result, key, row_data["UID"])
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
