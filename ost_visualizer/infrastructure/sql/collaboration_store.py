from __future__ import annotations
import json
import uuid
from typing import Optional
import pyodbc
from ...application.dtos.collaboration_dtos import (
    ChangeOperation,
    ChangeSourceKind,
    COLLABORATION_LOCK_SECONDS,
    COLLABORATION_STALE_SECONDS,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseSession,
    DurableOperationResult,
    HydratedDatabaseChangeBatch,
    PresenceMode,
    PresenceSnapshot,
    ResourceLock,
    ResourceRef,
    session_identities_equal,
)
from ...application.interfaces.i_collaboration_store import ICollaborationStore
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from .connection_manager import SqlConnectionManager, begin_snapshot_transaction
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError
from .database_metadata_contract import (
    DATABASE_METADATA_CURRENT_DATABASE_PREDICATE,
)
from .schema_lock import (
    acquire_operation_transaction_lock,
)
from .remote_change_reader import SqlRemoteChangeReader

_MAX_CHANGE_BATCH = 500


def _canonical_uuid_text(value) -> str:
    return str(uuid.UUID(str(value)))


class SqlCollaborationStore(ICollaborationStore):
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        remote_reader: SqlRemoteChangeReader,
        connection_manager: Optional[SqlConnectionManager] = None,
    ) -> None:
        self._requests = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._connections = connection_manager or SqlConnectionManager()
        self._remote_reader = remote_reader

    def start_session(
        self,
        database_id: str,
        session_id: str,
        client_instance_id: str,
        display_name: str,
        machine_name: str,
        application_version: str,
    ) -> DatabaseSession:
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT m.[DatabaseGuid] "
                        "FROM [ostv].[DatabaseMetadata] m WHERE "
                        + DATABASE_METADATA_CURRENT_DATABASE_PREDICATE
                    )
                    guid_row = cursor.fetchone()
                    if guid_row is None or guid_row[0] is None:
                        raise _database_identity_error(
                            "SQL collaboration metadata is missing, duplicated, or "
                            "does not identify the current database."
                        )
                    database_guid = _canonical_uuid_text(guid_row[0])
                    try:
                        expected_database_guid = _canonical_uuid_text(
                            request.location.database_guid
                        )
                    except (AttributeError, TypeError, ValueError):
                        raise _database_identity_error(
                            "The saved SQL connection has no valid database identity. "
                            "Remove it from Open Files and add it again."
                        ) from None
                    if database_guid != expected_database_guid:
                        raise _database_identity_error(
                            "The SQL database was replaced since this connection was "
                            "saved. Remove it from Open Files and add the replacement "
                            "database explicitly."
                        )
                    self._cleanup(cursor)
                    cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION()")
                    initial_version = int(cursor.fetchone()[0] or 0)
                    cursor.execute(
                        "INSERT INTO [ostv].[Sessions] "
                        "([SessionId], [DatabaseGuid], [ClientInstanceId], "
                        "[SqlPrincipal], [DisplayName], [MachineName], "
                        "[ApplicationVersion], [LastHeartbeatAt], "
                        "[LastAcknowledgedVersion]) "
                        "VALUES (?, ?, ?, CONVERT(nvarchar(256), ORIGINAL_LOGIN()), "
                        "?, ?, ?, SYSUTCDATETIME(), ?)",
                        session_id,
                        database_guid,
                        client_instance_id,
                        display_name,
                        machine_name,
                        application_version,
                        initial_version,
                    )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    _rollback(lease)
        return DatabaseSession(
            database_id=database_id,
            session_id=session_id,
            last_acknowledged_version=initial_version,
        )

    def heartbeat(
        self,
        database_id: str,
        session_id: str,
        acknowledged_version: int,
        bid_uid: Optional[int],
        page_uid: Optional[int],
        mode: PresenceMode,
    ) -> DatabaseSession:
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    self._cleanup(cursor)
                    cursor.execute(
                        "UPDATE [ostv].[Sessions] SET "
                        "[LastHeartbeatAt]=SYSUTCDATETIME(), "
                        "[LastAcknowledgedVersion]=CASE WHEN ? > "
                        "[LastAcknowledgedVersion] THEN ? ELSE "
                        "[LastAcknowledgedVersion] END "
                        "OUTPUT INSERTED.[LastAcknowledgedVersion] "
                        "WHERE [SessionId]=? AND [DisconnectedAt] IS NULL AND "
                        "[LastHeartbeatAt] >= DATEADD(second, ?, SYSUTCDATETIME())",
                        acknowledged_version,
                        acknowledged_version,
                        session_id,
                        -COLLABORATION_STALE_SECONDS,
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise _session_error(
                            "The SQL collaboration session expired. Reconnecting is "
                            "required before editing."
                        )
                    cursor.execute(
                        "MERGE [ostv].[Presence] WITH (HOLDLOCK) AS target "
                        "USING (SELECT CONVERT(uniqueidentifier, ?) AS [SessionId]) "
                        "AS source ON target.[SessionId]=source.[SessionId] "
                        "WHEN MATCHED THEN UPDATE SET [EnteredAt]=CASE WHEN "
                        "target.[BidUID]=? OR (target.[BidUID] IS NULL AND ? IS NULL) "
                        "THEN target.[EnteredAt] ELSE SYSUTCDATETIME() END, "
                        "[BidUID]=?, "
                        "[CurrentPageUID]=?, [ActivityMode]=?, "
                        "[LastHeartbeatAt]=SYSUTCDATETIME() "
                        "WHEN NOT MATCHED THEN INSERT "
                        "([SessionId], [BidUID], [CurrentPageUID], [ActivityMode], "
                        "[LastHeartbeatAt]) VALUES (?, ?, ?, ?, SYSUTCDATETIME());",
                        session_id,
                        bid_uid,
                        bid_uid,
                        bid_uid,
                        page_uid,
                        mode.value,
                        session_id,
                        bid_uid,
                        page_uid,
                        mode.value,
                    )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    _rollback(lease)
        return DatabaseSession(
            database_id=database_id,
            session_id=session_id,
            last_acknowledged_version=int(row[0]),
        )

    def close_session(self, database_id: str, session_id: str, reason: str) -> None:
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM [ostv].[Locks] WHERE [OwnerSessionId]=?; "
                        "DELETE FROM [ostv].[Presence] WHERE [SessionId]=?; "
                        "UPDATE [ostv].[Sessions] SET "
                        "[DisconnectedAt]=SYSUTCDATETIME(), [CloseReason]=? "
                        "WHERE [SessionId]=? AND [DisconnectedAt] IS NULL",
                        session_id,
                        session_id,
                        reason[:64],
                        session_id,
                    )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    _rollback(lease)

    def list_presence(
        self, database_id: str, bid_uid: int, excluding_session_id: str
    ) -> tuple[PresenceSnapshot, ...]:
        request = self._requests.request(database_id, read_only=True)
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT p.[SessionId], s.[DisplayName], "
                    "s.[ApplicationVersion], p.[BidUID], p.[CurrentPageUID], "
                    "p.[ActivityMode] "
                    "FROM [ostv].[Presence] p JOIN [ostv].[Sessions] s "
                    "ON s.[SessionId]=p.[SessionId] "
                    "WHERE p.[BidUID]=? AND p.[SessionId]<>? AND "
                    "s.[DisconnectedAt] IS NULL AND s.[LastHeartbeatAt] >= "
                    "DATEADD(second, ?, SYSUTCDATETIME()) "
                    "ORDER BY s.[DisplayName], p.[SessionId]",
                    bid_uid,
                    excluding_session_id,
                    -COLLABORATION_STALE_SECONDS,
                )
                rows = cursor.fetchall()
        return tuple(
            PresenceSnapshot(
                database_id=database_id,
                session_id=str(row[0]),
                display_name=str(row[1]),
                application_version=str(row[2]),
                bid_uid=int(row[3]) if row[3] is not None else None,
                page_uid=int(row[4]) if row[4] is not None else None,
                mode=PresenceMode(str(row[5])),
            )
            for row in rows
        )

    def list_locks(
        self,
        database_id: str,
        excluding_session_id: str,
        bid_uid: Optional[int] = None,
    ) -> tuple[ResourceLock, ...]:
        request = self._requests.request(database_id, read_only=True)
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT l.[ResourceType], l.[ResourceId], l.[BidUID], "
                    "l.[LockToken] FROM [ostv].[Locks] l WHERE "
                    "l.[OwnerSessionId]<>? AND l.[ExpiresAt] > "
                    "SYSUTCDATETIME() AND (? IS NULL OR l.[BidUID]=?) "
                    "ORDER BY l.[ResourceType], l.[ResourceId]",
                    excluding_session_id,
                    bid_uid,
                    bid_uid,
                )
                rows = cursor.fetchall()
        return tuple(
            ResourceLock(
                database_id=database_id,
                resource=ResourceRef(
                    str(row[0]),
                    str(row[1]),
                    int(row[2]) if row[2] is not None else None,
                ),
                lock_token=str(row[3]),
            )
            for row in rows
        )

    def acquire_locks(
        self,
        database_id: str,
        session_id: str,
        resources: tuple[ResourceRef, ...],
        operation_description: str,
    ) -> tuple[ResourceLock, ...]:
        resources = tuple(sorted(set(resources)))
        if not resources:
            return ()
        request = self._requests.request(database_id, read_only=False)
        payload = json.dumps(
            [
                {
                    "ordinal": ordinal,
                    "resource_type": resource.resource_type,
                    "resource_id": resource.resource_id,
                    "bid_uid": resource.bid_uid,
                    "lock_token": str(uuid.uuid4()),
                }
                for ordinal, resource in enumerate(resources)
            ],
            separators=(",", ":"),
        )
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SET NOCOUNT ON; DECLARE @Requested TABLE ("
                        "[Ordinal] int NOT NULL PRIMARY KEY, "
                        "[ResourceType] nvarchar(64) NOT NULL, "
                        "[ResourceId] nvarchar(128) NOT NULL, [BidUID] int NULL, "
                        "[LockToken] uniqueidentifier NOT NULL); INSERT INTO "
                        "@Requested SELECT [Ordinal], [ResourceType], [ResourceId], "
                        "[BidUID], [LockToken] FROM OPENJSON(?) WITH ("
                        "[Ordinal] int '$.ordinal', "
                        "[ResourceType] nvarchar(64) '$.resource_type', "
                        "[ResourceId] nvarchar(128) '$.resource_id', "
                        "[BidUID] int '$.bid_uid', "
                        "[LockToken] uniqueidentifier '$.lock_token'); "
                        "DECLARE @LockResults TABLE ([Ordinal] int NOT NULL "
                        "PRIMARY KEY, [Result] int NOT NULL); DECLARE @Ordinal int=0, "
                        "@Count int, @Resource nvarchar(255), @Result int; "
                        "SELECT @Count=COUNT(*) FROM @Requested; WHILE @Ordinal<@Count "
                        "BEGIN SELECT @Resource=N'OSTV:' + [ResourceType] + N':' + "
                        "[ResourceId] FROM @Requested WHERE [Ordinal]=@Ordinal; "
                        "EXEC @Result=sys.sp_getapplock @Resource=@Resource, "
                        "@LockMode=N'Exclusive', @LockOwner=N'Transaction', "
                        "@LockTimeout=10000; INSERT INTO @LockResults VALUES "
                        "(@Ordinal, @Result); IF @Result<0 BREAK; "
                        "SET @Ordinal=@Ordinal+1; END; "
                        "IF EXISTS (SELECT 1 FROM @LockResults WHERE [Result]<0) "
                        "SELECT -1 AS [Status], -1 AS [Ordinal], NULL AS [Owner], "
                        "NULL AS [LockToken]; ELSE BEGIN UPDATE [ostv].[Sessions] "
                        "SET [DisconnectedAt]=SYSUTCDATETIME(), "
                        "[CloseReason]=N'expired' WHERE [DisconnectedAt] IS NULL "
                        f"AND [LastHeartbeatAt]<DATEADD(second, {-COLLABORATION_STALE_SECONDS}, "
                        "SYSUTCDATETIME()); DELETE presence FROM [ostv].[Presence] "
                        "presence JOIN [ostv].[Sessions] sessions ON "
                        "sessions.[SessionId]=presence.[SessionId] WHERE "
                        "sessions.[DisconnectedAt] IS NOT NULL; DELETE locks FROM "
                        "[ostv].[Locks] locks LEFT JOIN [ostv].[Sessions] sessions "
                        "ON sessions.[SessionId]=locks.[OwnerSessionId] WHERE "
                        "locks.[ExpiresAt]<=SYSUTCDATETIME() OR "
                        "sessions.[DisconnectedAt] IS NOT NULL; DELETE FROM "
                        "[ostv].[Sessions] WHERE [DisconnectedAt]<DATEADD(day, -30, "
                        "SYSUTCDATETIME()); IF NOT EXISTS (SELECT 1 FROM "
                        "[ostv].[Sessions] WHERE [SessionId]=? AND "
                        "[DisconnectedAt] IS NULL AND [LastHeartbeatAt]>=DATEADD("
                        f"second, {-COLLABORATION_STALE_SECONDS}, SYSUTCDATETIME())) "
                        "SELECT -2, -1, NULL, NULL; ELSE IF EXISTS (SELECT 1 FROM "
                        "@Requested requested JOIN [ostv].[Locks] locks ON "
                        "locks.[ResourceType]=requested.[ResourceType] AND "
                        "locks.[ResourceId]=requested.[ResourceId] JOIN "
                        "[ostv].[Sessions] sessions ON "
                        "sessions.[SessionId]=locks.[OwnerSessionId] WHERE "
                        "locks.[OwnerSessionId]<>? AND "
                        "locks.[ExpiresAt]>SYSUTCDATETIME()) SELECT TOP (1) -3, "
                        "requested.[Ordinal], sessions.[DisplayName], NULL FROM "
                        "@Requested requested JOIN [ostv].[Locks] locks ON "
                        "locks.[ResourceType]=requested.[ResourceType] AND "
                        "locks.[ResourceId]=requested.[ResourceId] JOIN "
                        "[ostv].[Sessions] sessions ON "
                        "sessions.[SessionId]=locks.[OwnerSessionId] WHERE "
                        "locks.[OwnerSessionId]<>? AND "
                        "locks.[ExpiresAt]>SYSUTCDATETIME() ORDER BY "
                        "requested.[Ordinal]; ELSE BEGIN UPDATE locks SET "
                        "[LastRenewedAt]=SYSUTCDATETIME(), "
                        f"[ExpiresAt]=DATEADD(second, {COLLABORATION_LOCK_SECONDS}, "
                        "SYSUTCDATETIME()) FROM [ostv].[Locks] locks JOIN @Requested "
                        "requested ON requested.[ResourceType]=locks.[ResourceType] "
                        "AND requested.[ResourceId]=locks.[ResourceId] WHERE "
                        "locks.[OwnerSessionId]=?; INSERT INTO [ostv].[Locks] "
                        "([ResourceType], [ResourceId], [BidUID], [OwnerSessionId], "
                        "[LockToken], [OperationDescription], [LastRenewedAt], "
                        "[ExpiresAt]) SELECT requested.[ResourceType], "
                        "requested.[ResourceId], requested.[BidUID], ?, "
                        "requested.[LockToken], ?, SYSUTCDATETIME(), DATEADD(second, "
                        f"{COLLABORATION_LOCK_SECONDS}, SYSUTCDATETIME()) FROM "
                        "@Requested requested WHERE NOT EXISTS (SELECT 1 FROM "
                        "[ostv].[Locks] locks WHERE "
                        "locks.[ResourceType]=requested.[ResourceType] AND "
                        "locks.[ResourceId]=requested.[ResourceId]); SELECT 0, "
                        "requested.[Ordinal], NULL, CONVERT(nvarchar(36), "
                        "locks.[LockToken]) FROM @Requested requested JOIN "
                        "[ostv].[Locks] locks ON "
                        "locks.[ResourceType]=requested.[ResourceType] AND "
                        "locks.[ResourceId]=requested.[ResourceId] ORDER BY "
                        "requested.[Ordinal]; END END",
                        payload,
                        session_id,
                        session_id,
                        session_id,
                        session_id,
                        session_id,
                        operation_description[:256],
                    )
                    rows = tuple(cursor.fetchall())
                    if not rows:
                        raise RuntimeError(
                            "SQL edit-lock acquisition returned no result."
                        )
                    status = int(rows[0][0])
                    if status == -1:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.LOCKED,
                                "Another session is changing the same SQL resource.",
                            )
                        )
                    if status == -2:
                        raise _session_error(
                            "The SQL collaboration session expired. Reconnect before editing."
                        )
                    if status == -3:
                        ordinal = int(rows[0][1])
                        resource = resources[ordinal]
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.LOCKED,
                                f"{resource.resource_type} {resource.resource_id} "
                                f"is being edited by {rows[0][2]}.",
                            )
                        )
                    if len(rows) != len(resources) or any(
                        int(row[0]) != 0 or int(row[1]) != index
                        for index, row in enumerate(rows)
                    ):
                        raise RuntimeError(
                            "SQL edit-lock acquisition returned an incomplete result."
                        )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    _rollback(lease)
        return tuple(
            ResourceLock(
                database_id=database_id,
                resource=resource,
                lock_token=str(rows[index][3]),
            )
            for index, resource in enumerate(resources)
        )

    def renew_lock(
        self, database_id: str, session_id: str, lock_token: str
    ) -> ResourceLock:
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    _require_active_session(cursor, session_id)
                    cursor.execute(
                        "UPDATE l SET [LastRenewedAt]=SYSUTCDATETIME(), "
                        "[ExpiresAt]=DATEADD(second, ?, SYSUTCDATETIME()) "
                        "OUTPUT INSERTED.[ResourceType], INSERTED.[ResourceId], "
                        "INSERTED.[BidUID] "
                        "FROM [ostv].[Locks] l "
                        "WHERE l.[LockToken]=? AND l.[OwnerSessionId]=? AND "
                        "l.[ExpiresAt] > SYSUTCDATETIME()",
                        COLLABORATION_LOCK_SECONDS,
                        lock_token,
                        session_id,
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise _session_error(
                            "The edit lock expired and can no longer be renewed."
                        )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    _rollback(lease)
        return ResourceLock(
            database_id=database_id,
            resource=ResourceRef(
                str(row[0]),
                str(row[1]),
                int(row[2]) if row[2] is not None else None,
            ),
            lock_token=lock_token,
        )

    def release_lock(self, database_id: str, session_id: str, lock_token: str) -> bool:
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM [ostv].[Locks] WHERE [LockToken]=? AND "
                        "[OwnerSessionId]=?",
                        lock_token,
                        session_id,
                    )
                    deleted = cursor.rowcount == 1
                lease.commit()
                committed = True
            finally:
                if not committed:
                    _rollback(lease)
        return deleted

    def poll_changes(
        self,
        database_id: str,
        after_version: int,
        limit: int,
        excluding_session_id: str,
    ) -> DatabaseChangePollResult:
        batch_limit = max(1, min(int(limit), _MAX_CHANGE_BATCH))
        request = self._requests.request(database_id, read_only=True)
        with self._connections.connection(request, autocommit=False) as lease:
            transaction_finished = False
            try:
                begin_snapshot_transaction(lease)
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT CONVERT(nvarchar(36), f.[FeedEpoch]) "
                        "FROM [ostv].[ChangeFeedState] f WHERE f.[SingletonId]=1"
                    )
                    state = cursor.fetchone()
                    if state is None:
                        raise _session_error("SQL change-feed metadata is missing.")
                    cursor.execute(
                        "SELECT CHANGE_TRACKING_MIN_VALID_VERSION("
                        "OBJECT_ID(N'ostv.ChangeTransactions'))"
                    )
                    minimum_row = cursor.fetchone()
                    if minimum_row is None or minimum_row[0] is None:
                        raise ValueError("SQL Change Tracking metadata is unavailable.")
                    minimum_valid_version = int(minimum_row[0])
                    cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION()")
                    high_water_row = cursor.fetchone()
                    if high_water_row is None or high_water_row[0] is None:
                        raise ValueError("SQL Change Tracking metadata is unavailable.")
                    high_water_version = int(high_water_row[0])
                    checkpoint_invalid = bool(
                        after_version
                        and (
                            after_version < minimum_valid_version
                            or after_version > high_water_version
                        )
                    )
                    if checkpoint_invalid:
                        markers: tuple[tuple[str, int], ...] = ()
                        rows = ()
                        delivered_through_version = after_version
                    else:
                        cursor.execute(
                            f"SELECT TOP ({batch_limit}) WITH TIES "
                            "ct.[SYS_CHANGE_VERSION], "
                            "ct.[SYS_CHANGE_OPERATION], "
                            "CONVERT(nvarchar(36), ct.[TransactionId]) "
                            "FROM CHANGETABLE(CHANGES "
                            "[ostv].[ChangeTransactions], ?) ct "
                            "WHERE ct.[SYS_CHANGE_VERSION] <= ? "
                            "ORDER BY ct.[SYS_CHANGE_VERSION]",
                            after_version,
                            high_water_version,
                        )
                        marker_rows = tuple(cursor.fetchall())
                        if any(str(row[1]) != "I" for row in marker_rows):
                            raise ValueError(
                                "SQL transaction-marker history contains an "
                                "invalid change."
                            )
                        markers = tuple(
                            (_canonical_uuid_text(row[2]), int(row[0]))
                            for row in marker_rows
                        )
                        if len({marker[0] for marker in markers}) != len(markers):
                            raise ValueError(
                                "SQL transaction-marker history contains a duplicate "
                                "transaction identity."
                            )
                        rows = self._load_transaction_changes(cursor, markers)
                        delivered_through_version = (
                            markers[-1][1]
                            if len(markers) >= batch_limit
                            else high_water_version
                        )
                observed_batch = DatabaseChangeBatch(
                    database_id=database_id,
                    feed_epoch=str(state[0]),
                    minimum_valid_version=minimum_valid_version,
                    high_water_version=high_water_version,
                    delivered_through_version=delivered_through_version,
                    changes=tuple(_change_from_row(row) for row in rows),
                )
                remote_batch = DatabaseChangeBatch(
                    database_id=observed_batch.database_id,
                    feed_epoch=observed_batch.feed_epoch,
                    minimum_valid_version=observed_batch.minimum_valid_version,
                    high_water_version=observed_batch.high_water_version,
                    delivered_through_version=observed_batch.delivered_through_version,
                    changes=tuple(
                        change
                        for change in observed_batch.changes
                        if not session_identities_equal(
                            change.source_session_id, excluding_session_id
                        )
                    ),
                )
                if checkpoint_invalid:
                    hydrated = HydratedDatabaseChangeBatch(remote_batch)
                    lease.rollback()
                else:
                    hydrated = self._remote_reader.hydrate_connection(
                        remote_batch, lease
                    )
                    lease.commit()
                transaction_finished = True
            finally:
                if not transaction_finished:
                    _rollback(lease)
        return DatabaseChangePollResult(
            observed_batch=observed_batch,
            remote_batch=hydrated,
        )

    def query_operation(
        self, database_id: str, operation_id: str
    ) -> DurableOperationResult:
        operation_id = str(uuid.UUID(str(operation_id)))
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            transaction_finished = False
            try:
                with lease.cursor() as cursor:
                    acquire_operation_transaction_lock(cursor, operation_id)
                    cursor.execute(
                        "SELECT [OperationType], [RequestHash], "
                        "[ResultFormatVersion], [ResultPayload] FROM "
                        "[ostv].[ChangeTransactions] WHERE [TransactionId]=?",
                        operation_id,
                    )
                    row = cursor.fetchone()
                lease.rollback()
                transaction_finished = True
            finally:
                if not transaction_finished:
                    _rollback(lease)
        if row is None:
            return DurableOperationResult(
                database_id=database_id,
                operation_id=operation_id,
                found=False,
            )
        return DurableOperationResult(
            database_id=database_id,
            operation_id=operation_id,
            found=True,
            mutation_type=str(row[0]),
            request_hash=str(row[1]),
            result_format_version=int(row[2]),
            result_payload=str(row[3]),
        )

    def hydrate_operation(
        self, database_id: str, operation_id: str
    ) -> HydratedDatabaseChangeBatch:
        operation_id = str(uuid.UUID(str(operation_id)))
        request = self._requests.request(database_id, read_only=True)
        with self._connections.connection(request, autocommit=False) as lease:
            transaction_finished = False
            try:
                begin_snapshot_transaction(lease)
                with lease.cursor() as cursor:
                    cursor.execute(
                        "DECLARE @CommitVersion bigint="
                        "CHANGE_TRACKING_CURRENT_VERSION(); SELECT @CommitVersion, "
                        "CONVERT(nvarchar(36), feed.[FeedEpoch]), "
                        "CONVERT(nvarchar(36), marker.[TransactionId]), "
                        "changes.[Sequence], @CommitVersion, "
                        "CONVERT(nvarchar(36), changes.[TransactionId]), "
                        "CONVERT(nvarchar(36), changes.[SourceSessionId]), "
                        "changes.[BidUID], changes.[ResourceType], "
                        "changes.[ResourceId], changes.[Operation], "
                        "changes.[ResultVersion], changes.[ChangedFields], "
                        "changes.[Payload], changes.[SourceKind] FROM "
                        "[ostv].[ChangeFeedState] feed LEFT JOIN "
                        "[ostv].[ChangeTransactions] marker ON "
                        "marker.[TransactionId]=? LEFT JOIN [ostv].[ChangeLog] "
                        "changes ON changes.[TransactionId]=marker.[TransactionId] "
                        "WHERE feed.[SingletonId]=1 ORDER BY changes.[Sequence]",
                        operation_id,
                    )
                    snapshot_rows = tuple(cursor.fetchall())
                    if not snapshot_rows or snapshot_rows[0][0] is None:
                        raise ValueError("SQL Change Tracking metadata is unavailable.")
                    if snapshot_rows[0][2] is None:
                        raise ValueError(
                            "The committed SQL operation marker is missing."
                        )
                    feed_epoch = str(snapshot_rows[0][1])
                    version = int(snapshot_rows[0][0])
                    rows = tuple(row[3:] for row in snapshot_rows if row[3] is not None)
                    self._validate_transaction_change_rows(
                        rows,
                        ((operation_id, version),),
                    )
                batch = DatabaseChangeBatch(
                    database_id=database_id,
                    feed_epoch=feed_epoch,
                    minimum_valid_version=version,
                    high_water_version=version,
                    delivered_through_version=version,
                    changes=tuple(_change_from_row(row) for row in rows),
                )
                hydrated = self._remote_reader.hydrate_connection(batch, lease)
                lease.commit()
                transaction_finished = True
            finally:
                if not transaction_finished:
                    _rollback(lease)
        return hydrated

    @staticmethod
    def _load_transaction_changes(cursor, markers: tuple[tuple[str, int], ...]):
        if not markers:
            return ()
        values_sql = ", ".join(
            "(CONVERT(uniqueidentifier, ?), CONVERT(bigint, ?))" for _ in markers
        )
        parameters = tuple(value for marker in markers for value in marker)
        cursor.execute(
            "WITH MarkerVersions ([TransactionId], [CommitVersion]) AS ("
            f"SELECT * FROM (VALUES {values_sql}) marker_values "
            "([TransactionId], [CommitVersion])) "
            "SELECT l.[Sequence], m.[CommitVersion], "
            "CONVERT(nvarchar(36), l.[TransactionId]), "
            "CONVERT(nvarchar(36), l.[SourceSessionId]), l.[BidUID], "
            "l.[ResourceType], l.[ResourceId], l.[Operation], "
            "l.[ResultVersion], l.[ChangedFields], l.[Payload], l.[SourceKind] "
            "FROM MarkerVersions m LEFT JOIN [ostv].[ChangeLog] l ON "
            "l.[TransactionId]=m.[TransactionId] "
            "ORDER BY m.[CommitVersion], l.[Sequence]",
            *parameters,
        )
        rows = tuple(cursor.fetchall())
        SqlCollaborationStore._validate_transaction_change_rows(rows, markers)
        return rows

    @staticmethod
    def _validate_transaction_change_rows(
        rows, markers: tuple[tuple[str, int], ...]
    ) -> None:
        transaction_ids = {
            _canonical_uuid_text(row[2]) for row in rows if row[0] is not None
        }
        missing = {
            _canonical_uuid_text(transaction_id) for transaction_id, _version in markers
        }.difference(transaction_ids)
        if missing:
            raise ValueError(
                "A committed SQL transaction marker has no ChangeLog records."
            )
        payload_identities = tuple(
            (_canonical_uuid_text(row[2]), str(row[5]), str(row[6]))
            for row in rows
            if row[0] is not None
        )
        if len(set(payload_identities)) != len(payload_identities):
            raise ValueError(
                "A committed SQL transaction contains duplicate resource payloads."
            )

    @staticmethod
    def _cleanup(cursor) -> None:
        cursor.execute(
            "UPDATE [ostv].[Sessions] SET [DisconnectedAt]=SYSUTCDATETIME(), "
            "[CloseReason]=N'expired' WHERE [DisconnectedAt] IS NULL AND "
            "[LastHeartbeatAt] < DATEADD(second, ?, SYSUTCDATETIME()); "
            "DELETE p FROM [ostv].[Presence] p JOIN [ostv].[Sessions] s "
            "ON s.[SessionId]=p.[SessionId] WHERE s.[DisconnectedAt] IS NOT NULL; "
            "DELETE l FROM [ostv].[Locks] l LEFT JOIN [ostv].[Sessions] s "
            "ON s.[SessionId]=l.[OwnerSessionId] WHERE "
            "l.[ExpiresAt] <= SYSUTCDATETIME() OR s.[DisconnectedAt] IS NOT NULL; "
            "DELETE FROM [ostv].[Sessions] WHERE [DisconnectedAt] < "
            "DATEADD(day, -30, SYSUTCDATETIME());",
            -COLLABORATION_STALE_SECONDS,
        )


def _require_active_session(cursor, session_id: str) -> None:
    cursor.execute(
        "SELECT 1 FROM [ostv].[Sessions] WHERE [SessionId]=? AND "
        "[DisconnectedAt] IS NULL AND [LastHeartbeatAt] >= "
        "DATEADD(second, ?, SYSUTCDATETIME())",
        session_id,
        -COLLABORATION_STALE_SECONDS,
    )
    if cursor.fetchone() is None:
        raise _session_error(
            "The SQL collaboration session expired. Reconnect before editing."
        )


def _change_from_row(row) -> DatabaseChange:
    changed_fields: tuple[str, ...] = ()
    if row[9]:
        parsed = json.loads(str(row[9]))
        if not isinstance(parsed, list) or not all(
            isinstance(value, str) for value in parsed
        ):
            raise ValueError("SQL ChangeLog contains invalid changed-field data")
        changed_fields = tuple(parsed)
    return DatabaseChange(
        sequence=int(row[0]),
        commit_version=int(row[1]),
        transaction_id=_canonical_uuid_text(row[2]),
        source_session_id=str(row[3]) if row[3] else None,
        resource=ResourceRef(
            resource_type=str(row[5]),
            resource_id=str(row[6]),
            bid_uid=int(row[4]) if row[4] is not None else None,
        ),
        operation=ChangeOperation(str(row[7])),
        resulting_version=(
            ConcurrencyToken.from_database(row[8]) if row[8] is not None else None
        ),
        changed_fields=changed_fields,
        payload=str(row[10] or ""),
        source_kind=ChangeSourceKind(str(row[11])),
    )


def _session_error(message: str) -> SqlInfrastructureError:
    return SqlInfrastructureError(
        SqlErrorDetails(SqlErrorCode.SESSION_EXPIRED, message)
    )


def _database_identity_error(message: str) -> SqlInfrastructureError:
    return SqlInfrastructureError(
        SqlErrorDetails(SqlErrorCode.SCHEMA_MISMATCH, message)
    )


def _rollback(lease) -> None:
    try:
        lease.rollback()
    except pyodbc.Error:
        pass
