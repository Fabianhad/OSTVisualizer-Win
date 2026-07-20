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
    HydratedDatabaseChangeBatch,
    PresenceMode,
    PresenceSnapshot,
    ResourceLock,
    ResourceRef,
)
from ...application.interfaces.i_collaboration_store import ICollaborationStore
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from .connection_manager import SqlConnectionManager
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError
from .schema_lock import acquire_resource_transaction_lock
from .remote_change_reader import SqlRemoteChangeReader

_MAX_CHANGE_BATCH = 500


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
                    self._cleanup(cursor)
                    cursor.execute(
                        "SELECT [DatabaseGuid] FROM [ostv].[DatabaseMetadata]"
                    )
                    guid_row = cursor.fetchone()
                    if guid_row is None:
                        raise _session_error("SQL collaboration metadata is missing.")
                    database_guid = str(guid_row[0])
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

    def acquire_lock(
        self,
        database_id: str,
        session_id: str,
        resource: ResourceRef,
        operation_description: str,
    ) -> ResourceLock:
        request = self._requests.request(database_id, read_only=False)
        token = str(uuid.uuid4())
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    acquire_resource_transaction_lock(cursor, resource)
                    self._cleanup(cursor)
                    _require_active_session(cursor, session_id)
                    cursor.execute(
                        "SELECT l.[OwnerSessionId], s.[DisplayName], l.[LockToken] "
                        "FROM [ostv].[Locks] l JOIN [ostv].[Sessions] s "
                        "ON s.[SessionId]=l.[OwnerSessionId] "
                        "WHERE l.[ResourceType]=? AND l.[ResourceId]=? AND "
                        "l.[ExpiresAt] > SYSUTCDATETIME()",
                        resource.resource_type,
                        resource.resource_id,
                    )
                    existing = cursor.fetchone()
                    if existing is not None and str(existing[0]) != session_id:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.LOCKED,
                                f"{resource.resource_type} {resource.resource_id} "
                                f"is being edited by {existing[1]}.",
                            )
                        )
                    if existing is not None:
                        cursor.execute(
                            "UPDATE [ostv].[Locks] SET "
                            "[LastRenewedAt]=SYSUTCDATETIME(), "
                            "[ExpiresAt]=DATEADD(second, ?, SYSUTCDATETIME()) "
                            "OUTPUT INSERTED.[LockToken] WHERE [ResourceType]=? AND "
                            "[ResourceId]=? AND [OwnerSessionId]=?",
                            COLLABORATION_LOCK_SECONDS,
                            resource.resource_type,
                            resource.resource_id,
                            session_id,
                        )
                        saved = cursor.fetchone()
                        token = str(saved[0])
                    else:
                        cursor.execute(
                            "INSERT INTO [ostv].[Locks] "
                            "([ResourceType], [ResourceId], [BidUID], "
                            "[OwnerSessionId], "
                            "[LockToken], [OperationDescription], [LastRenewedAt], "
                            "[ExpiresAt]) VALUES (?, ?, ?, ?, ?, ?, "
                            "SYSUTCDATETIME(), DATEADD(second, ?, SYSUTCDATETIME()))",
                            resource.resource_type,
                            resource.resource_id,
                            resource.bid_uid,
                            session_id,
                            token,
                            operation_description[:256],
                            COLLABORATION_LOCK_SECONDS,
                        )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    _rollback(lease)
        return ResourceLock(
            database_id=database_id,
            resource=resource,
            lock_token=token,
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
                with lease.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
                    cursor.execute("BEGIN TRANSACTION")
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
                            (str(row[2]), int(row[0])) for row in marker_rows
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
                        if change.source_session_id != excluding_session_id
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
        transaction_ids = {str(row[2]) for row in rows if row[0] is not None}
        missing = {transaction_id for transaction_id, _version in markers}.difference(
            transaction_ids
        )
        if missing:
            raise ValueError(
                "A committed SQL transaction marker has no ChangeLog records."
            )
        payload_identities = tuple(
            (str(row[2]), str(row[5]), str(row[6]))
            for row in rows
            if row[0] is not None
        )
        if len(set(payload_identities)) != len(payload_identities):
            raise ValueError(
                "A committed SQL transaction contains duplicate resource payloads."
            )
        return rows

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
        transaction_id=str(row[2]),
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


def _rollback(lease) -> None:
    try:
        lease.rollback()
    except pyodbc.Error:
        pass
