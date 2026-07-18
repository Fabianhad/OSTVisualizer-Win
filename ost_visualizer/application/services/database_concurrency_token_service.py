from __future__ import annotations
import threading
from ..dtos.collaboration_dtos import (
    ConcurrencyToken,
    DatabaseChange,
    ExpectedResourceVersion,
    ResourceRef,
)
from ..interfaces.i_entity_version_reader import IEntityVersionReader


class DatabaseConcurrencyTokenService:
    def __init__(self, reader: IEntityVersionReader) -> None:
        self._reader = reader
        self._tokens: dict[tuple[str, ResourceRef], ConcurrencyToken] = {}
        self._loaded_bids: set[tuple[str, int]] = set()
        self._edit_tokens: dict[tuple[str, ResourceRef], ConcurrencyToken] = {}
        self._lock = threading.Lock()

    def load_database(self, database_id: str) -> None:
        loaded = self._reader.read_database_versions(database_id)
        with self._lock:
            stale = [
                key
                for key in self._tokens
                if key[0] == database_id and key[1].bid_uid is None
            ]
            for key in stale:
                del self._tokens[key]
            stale_edits = [
                key
                for key in self._edit_tokens
                if key[0] == database_id and key[1].bid_uid is None
            ]
            for key in stale_edits:
                del self._edit_tokens[key]
            for resource, token in loaded.items():
                self._tokens[(database_id, resource)] = token

    def load_bid(self, database_id: str, bid_uid: str) -> None:
        loaded = self._reader.read_bid_versions(database_id, bid_uid)
        parsed_bid_uid = int(bid_uid)
        with self._lock:
            stale = [
                key
                for key in self._tokens
                if key[0] == database_id and key[1].bid_uid == parsed_bid_uid
            ]
            for key in stale:
                del self._tokens[key]
            stale_edits = [
                key
                for key in self._edit_tokens
                if key[0] == database_id and key[1].bid_uid == parsed_bid_uid
            ]
            for key in stale_edits:
                del self._edit_tokens[key]
            for resource, token in loaded.items():
                self._tokens[(database_id, resource)] = token
            self._loaded_bids.add((database_id, parsed_bid_uid))

    def ensure_resources_loaded(
        self, database_id: str, resources: tuple[ResourceRef, ...]
    ) -> None:
        bid_uids = sorted(
            {int(resource.bid_uid) for resource in resources if resource.bid_uid}
        )
        with self._lock:
            missing = [
                bid_uid
                for bid_uid in bid_uids
                if (database_id, bid_uid) not in self._loaded_bids
            ]
        for bid_uid in missing:
            self.load_bid(database_id, str(bid_uid))

    def expected_versions(
        self, database_id: str, resources: tuple[ResourceRef, ...]
    ) -> tuple[ExpectedResourceVersion, ...]:
        with self._lock:
            return tuple(
                ExpectedResourceVersion(
                    resource,
                    self._edit_tokens.get(
                        (database_id, resource),
                        self._tokens[(database_id, resource)],
                    ),
                )
                for resource in resources
                if (database_id, resource) in self._tokens
            )

    def apply_result(
        self,
        database_id: str,
        resulting_versions: dict[ResourceRef, ConcurrencyToken],
    ) -> None:
        with self._lock:
            for resource, token in resulting_versions.items():
                self._tokens[(database_id, resource)] = token
                edit_key = (database_id, resource)
                if edit_key in self._edit_tokens:
                    self._edit_tokens[edit_key] = token

    def apply_remote_changes(
        self, database_id: str, changes: tuple[DatabaseChange, ...]
    ) -> tuple[ResourceRef, ...]:
        conflicts = []
        with self._lock:
            for change in changes:
                if change.resulting_version is not None:
                    key = (database_id, change.resource)
                    edit_token = self._edit_tokens.get(key)
                    if (
                        edit_token is not None
                        and edit_token != change.resulting_version
                    ):
                        conflicts.append(change.resource)
                    self._tokens[key] = change.resulting_version
        return tuple(conflicts)

    def begin_edit(self, database_id: str, resources: tuple[ResourceRef, ...]) -> None:
        with self._lock:
            for resource in resources:
                key = (database_id, resource)
                token = self._tokens.get(key)
                if token is not None:
                    self._edit_tokens[key] = token

    def end_edit(self, database_id: str, resources: tuple[ResourceRef, ...]) -> None:
        with self._lock:
            for resource in resources:
                self._edit_tokens.pop((database_id, resource), None)

    def clear_database(self, database_id: str) -> None:
        with self._lock:
            stale = [key for key in self._tokens if key[0] == database_id]
            for key in stale:
                del self._tokens[key]
            stale_edits = [key for key in self._edit_tokens if key[0] == database_id]
            for key in stale_edits:
                del self._edit_tokens[key]
            self._loaded_bids = {
                key for key in self._loaded_bids if key[0] != database_id
            }
