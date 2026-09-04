from __future__ import annotations
import logging
from typing import Optional
from ...application.dtos.user_workspace_state_dtos import (
    UserBidWorkspaceState,
    UserPageViewState,
)
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...application.interfaces.i_sql_workspace_state_repository import (
    ISqlWorkspaceStateRepository,
)
from .connection_manager import SqlConnectionManager
from .database_metadata_contract import (
    DATABASE_METADATA_CURRENT_DATABASE_PREDICATE,
)
from .descriptor_connection import SqlDescriptorConnectionFactory


class SqlWorkspaceStateRepository(ISqlWorkspaceStateRepository):
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        connection_manager: Optional[SqlConnectionManager] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._requests = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._connections = connection_manager or SqlConnectionManager()
        self._logger = logger or logging.getLogger(__name__)

    def load_bid_state(self, database_id: str, bid_uid: str) -> UserBidWorkspaceState:
        bid_value = _positive_uid(bid_uid, "bid")
        request = self._requests.request(database_id, read_only=True)
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                database_guid, user_sid, _principal = self._identity(cursor)
                cursor.execute(
                    "SELECT workspace.[ActivePageUID] "
                    "FROM [ostv].[UserBidWorkspaceState] workspace "
                    "JOIN [dbo].[Bids] bids ON bids.[UID]=workspace.[BidUID] "
                    "LEFT JOIN [dbo].[BidPages] pages ON "
                    "pages.[UID]=workspace.[ActivePageUID] AND "
                    "pages.[BidUID]=workspace.[BidUID] "
                    "WHERE workspace.[DatabaseGuid]=? AND workspace.[UserSid]=? "
                    "AND workspace.[BidUID]=? AND "
                    "(workspace.[ActivePageUID] IS NULL OR pages.[UID] IS NOT NULL)",
                    database_guid,
                    user_sid,
                    bid_value,
                )
                active_row = cursor.fetchone()
                active_page_uid = (
                    str(active_row[0])
                    if active_row is not None and active_row[0] is not None
                    else None
                )
                cursor.execute(
                    "SELECT workspace.[PageUID], workspace.[ZoomFac], "
                    "workspace.[CurrentX], workspace.[CurrentY] "
                    "FROM [ostv].[UserPageWorkspaceState] workspace "
                    "JOIN [dbo].[BidPages] pages ON "
                    "pages.[UID]=workspace.[PageUID] AND "
                    "pages.[BidUID]=workspace.[BidUID] "
                    "WHERE workspace.[DatabaseGuid]=? AND workspace.[UserSid]=? "
                    "AND workspace.[BidUID]=?",
                    database_guid,
                    user_sid,
                    bid_value,
                )
                page_views: dict[str, UserPageViewState] = {}
                for row in cursor.fetchall():
                    try:
                        page_views[str(row[0])] = UserPageViewState(
                            zoom_fac=float(row[1]),
                            current_x=float(row[2]),
                            current_y=float(row[3]),
                        )
                    except (TypeError, ValueError):
                        self._logger.warning(
                            "Ignoring invalid SQL workspace view state for page %s",
                            row[0],
                        )
                return UserBidWorkspaceState(active_page_uid, page_views)

    def save_active_page(self, database_id: str, bid_uid: str, page_uid: str) -> None:
        bid_value = _positive_uid(bid_uid, "bid")
        page_value = _positive_uid(page_uid, "page")
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    database_guid, user_sid, principal = self._identity(cursor)
                    self._require_page(cursor, bid_value, page_value)
                    cursor.execute(
                        "MERGE [ostv].[UserBidWorkspaceState] WITH (HOLDLOCK) "
                        "AS target USING (VALUES (?, ?, ?, ?, ?)) AS source "
                        "([DatabaseGuid], [UserSid], [BidUID], [ActivePageUID], "
                        "[UserPrincipal]) ON target.[DatabaseGuid]="
                        "source.[DatabaseGuid] AND target.[UserSid]=source.[UserSid] "
                        "AND target.[BidUID]=source.[BidUID] WHEN MATCHED THEN "
                        "UPDATE SET [ActivePageUID]=source.[ActivePageUID], "
                        "[UserPrincipal]=source.[UserPrincipal], "
                        "[UpdatedAt]=SYSUTCDATETIME() WHEN NOT MATCHED THEN "
                        "INSERT ([DatabaseGuid], [UserSid], [BidUID], "
                        "[ActivePageUID], [UserPrincipal]) VALUES "
                        "(source.[DatabaseGuid], source.[UserSid], source.[BidUID], "
                        "source.[ActivePageUID], source.[UserPrincipal]);",
                        database_guid,
                        user_sid,
                        bid_value,
                        page_value,
                        principal,
                    )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    lease.rollback()

    def save_page_view(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
        state: UserPageViewState,
    ) -> None:
        bid_value = _positive_uid(bid_uid, "bid")
        page_value = _positive_uid(page_uid, "page")
        request = self._requests.request(database_id, read_only=False)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    database_guid, user_sid, principal = self._identity(cursor)
                    self._require_page(cursor, bid_value, page_value)
                    cursor.execute(
                        "MERGE [ostv].[UserPageWorkspaceState] WITH (HOLDLOCK) "
                        "AS target USING (VALUES (?, ?, ?, ?, ?, ?, ?, ?)) "
                        "AS source ([DatabaseGuid], [UserSid], [BidUID], "
                        "[PageUID], [ZoomFac], [CurrentX], [CurrentY], "
                        "[UserPrincipal]) ON target.[DatabaseGuid]="
                        "source.[DatabaseGuid] AND target.[UserSid]=source.[UserSid] "
                        "AND target.[BidUID]=source.[BidUID] AND "
                        "target.[PageUID]=source.[PageUID] WHEN MATCHED THEN "
                        "UPDATE SET [ZoomFac]=source.[ZoomFac], "
                        "[CurrentX]=source.[CurrentX], [CurrentY]=source.[CurrentY], "
                        "[UserPrincipal]=source.[UserPrincipal], "
                        "[UpdatedAt]=SYSUTCDATETIME() WHEN NOT MATCHED THEN "
                        "INSERT ([DatabaseGuid], [UserSid], [BidUID], [PageUID], "
                        "[ZoomFac], [CurrentX], [CurrentY], [UserPrincipal]) "
                        "VALUES (source.[DatabaseGuid], source.[UserSid], "
                        "source.[BidUID], source.[PageUID], source.[ZoomFac], "
                        "source.[CurrentX], source.[CurrentY], "
                        "source.[UserPrincipal]);",
                        database_guid,
                        user_sid,
                        bid_value,
                        page_value,
                        state.zoom_fac,
                        state.current_x,
                        state.current_y,
                        principal,
                    )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    lease.rollback()

    @staticmethod
    def _identity(cursor) -> tuple[str, bytes, str]:
        cursor.execute(
            "SELECT [DatabaseGuid], "
            "CONVERT(varbinary(85), SUSER_SID(ORIGINAL_LOGIN())), "
            "CONVERT(nvarchar(256), ORIGINAL_LOGIN()) "
            "FROM [ostv].[DatabaseMetadata] m WHERE "
            + DATABASE_METADATA_CURRENT_DATABASE_PREDICATE
        )
        row = cursor.fetchone()
        if row is None or row[1] is None or not str(row[2]).strip():
            raise RuntimeError(
                "The authenticated SQL user does not have a stable workspace identity"
            )
        return str(row[0]), bytes(row[1]), str(row[2])

    @staticmethod
    def _require_page(cursor, bid_uid: int, page_uid: int) -> None:
        cursor.execute(
            "SELECT 1 FROM [dbo].[BidPages] WHERE [UID]=? AND [BidUID]=?",
            page_uid,
            bid_uid,
        )
        if cursor.fetchone() is None:
            raise ValueError("The workspace page does not belong to the requested bid")


def _positive_uid(value: str, kind: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"SQL workspace {kind} UID must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"SQL workspace {kind} UID must be positive")
    return parsed
