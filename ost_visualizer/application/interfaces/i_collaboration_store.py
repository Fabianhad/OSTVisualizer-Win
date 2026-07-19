from __future__ import annotations
from typing import Optional, Protocol
from ..dtos.collaboration_dtos import (
    DatabaseChangeBatch,
    DatabaseSession,
    PresenceMode,
    PresenceSnapshot,
    ResourceLock,
    ResourceRef,
)


class ICollaborationStore(Protocol):
    def start_session(
        self,
        database_id: str,
        session_id: str,
        client_instance_id: str,
        display_name: str,
        machine_name: str,
        application_version: str,
    ) -> DatabaseSession: ...
    def heartbeat(
        self,
        database_id: str,
        session_id: str,
        acknowledged_version: int,
        bid_uid: Optional[int],
        page_uid: Optional[int],
        mode: PresenceMode,
    ) -> DatabaseSession: ...
    def close_session(self, database_id: str, session_id: str, reason: str) -> None: ...
    def list_presence(
        self, database_id: str, bid_uid: int, excluding_session_id: str
    ) -> tuple[PresenceSnapshot, ...]: ...
    def list_locks(
        self,
        database_id: str,
        excluding_session_id: str,
        bid_uid: Optional[int] = None,
    ) -> tuple[ResourceLock, ...]: ...
    def acquire_lock(
        self,
        database_id: str,
        session_id: str,
        resource: ResourceRef,
        operation_description: str,
    ) -> ResourceLock: ...
    def renew_lock(
        self, database_id: str, session_id: str, lock_token: str
    ) -> ResourceLock: ...
    def release_lock(
        self, database_id: str, session_id: str, lock_token: str
    ) -> bool: ...
    def poll_changes(
        self, database_id: str, after_version: int, limit: int
    ) -> DatabaseChangeBatch: ...
