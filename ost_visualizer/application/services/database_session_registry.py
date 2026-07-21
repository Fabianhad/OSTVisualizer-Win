from __future__ import annotations
import threading
from ..dtos.collaboration_dtos import ResourceRef


class DatabaseSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
        self._lock_tokens: dict[tuple[str, tuple[str, str]], str] = {}
        self._lock = threading.Lock()

    def register(self, database_id: str, session_id: str) -> None:
        if not database_id or not session_id:
            raise ValueError("Database and session IDs are required.")
        with self._lock:
            self._sessions[database_id] = session_id

    def remove(self, database_id: str, session_id: str = "") -> None:
        with self._lock:
            current = self._sessions.get(database_id)
            if current is not None and (not session_id or current == session_id):
                del self._sessions[database_id]
                stale = [key for key in self._lock_tokens if key[0] == database_id]
                for key in stale:
                    del self._lock_tokens[key]

    def require(self, database_id: str) -> str:
        session_id = self.get(database_id)
        if not session_id:
            raise RuntimeError(
                "This SQL database has no active collaboration session and is read-only."
            )
        return session_id

    def get(self, database_id: str) -> str:
        with self._lock:
            return self._sessions.get(database_id, "")

    def register_lock(
        self, database_id: str, resource: ResourceRef, lock_token: str
    ) -> None:
        with self._lock:
            self._lock_tokens[(database_id, resource.lease_identity)] = lock_token

    def remove_lock(self, database_id: str, resource: ResourceRef) -> None:
        with self._lock:
            self._lock_tokens.pop((database_id, resource.lease_identity), None)

    def lock_tokens(
        self, database_id: str, resources: tuple[ResourceRef, ...]
    ) -> tuple[str, ...]:
        with self._lock:
            tokens = (
                self._lock_tokens.get((database_id, resource.lease_identity))
                for resource in resources
            )
            return tuple(dict.fromkeys(token for token in tokens if token is not None))
