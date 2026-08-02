from __future__ import annotations
import logging
import threading
from pathlib import Path
from typing import Optional
from ....application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    PendingMutationState,
    PendingSqlOperationRecord,
    ResourceRef,
)
from ....application.interfaces.i_pending_sql_operation_repository import (
    IPendingSqlOperationRepository,
)
from ...app_paths import get_app_data_dir
from .json_repository_base import JsonRepositoryBase


class JsonPendingSqlOperationRepository(
    JsonRepositoryBase, IPendingSqlOperationRepository
):
    def __init__(
        self,
        file_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        path = file_path or (get_app_data_dir() / "pending_sql_operations.json")
        super().__init__(path, "pending SQL operations", logger)
        self._lock = threading.Lock()

    def list_all(self) -> tuple[PendingSqlOperationRecord, ...]:
        with self._lock:
            return self._load_records_locked()

    def save(self, record: PendingSqlOperationRecord) -> None:
        with self._lock:
            records = {item.operation_id: item for item in self._load_records_locked()}
            existing = records.get(record.operation_id)
            if existing is not None and existing != record:
                existing_identity = (
                    existing.database_id,
                    existing.mutation_type,
                    existing.request_hash,
                    existing.owning_surface,
                    existing.resources,
                    existing.dependency_resources,
                    existing.bid_uid,
                    existing.page_uid,
                )
                record_identity = (
                    record.database_id,
                    record.mutation_type,
                    record.request_hash,
                    record.owning_surface,
                    record.resources,
                    record.dependency_resources,
                    record.bid_uid,
                    record.page_uid,
                )
                if existing_identity != record_identity:
                    raise ValueError(
                        "A pending SQL operation ID was reused for another request"
                    )
            records[record.operation_id] = record
            self._save_records_locked(tuple(records.values()))

    def remove(self, operation_id: str) -> None:
        with self._lock:
            records = tuple(
                item
                for item in self._load_records_locked()
                if item.operation_id != operation_id
            )
            self._save_records_locked(records)

    def _load_records_locked(self) -> tuple[PendingSqlOperationRecord, ...]:
        try:
            data = self._load_json()
        except FileNotFoundError:
            return ()
        if not isinstance(data, dict) or set(data) != {"version", "operations"}:
            raise ValueError("Pending SQL operation data is not canonical")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("Pending SQL operation data has an unsupported version")
        raw_records = data["operations"]
        if not isinstance(raw_records, list):
            raise ValueError("Pending SQL operation data must contain a list")
        return tuple(self._record_from_dict(item) for item in raw_records)

    def _save_records_locked(
        self, records: tuple[PendingSqlOperationRecord, ...]
    ) -> None:
        self._save_json(
            {
                "version": 1,
                "operations": [
                    self._record_to_dict(record)
                    for record in sorted(records, key=lambda item: item.operation_id)
                ],
            }
        )

    @staticmethod
    def _record_to_dict(record: PendingSqlOperationRecord) -> dict:
        def resource(item: ResourceRef) -> dict:
            return {
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "bid_uid": item.bid_uid,
            }

        return {
            "database_id": record.database_id,
            "operation_id": record.operation_id,
            "mutation_type": record.mutation_type.value,
            "request_hash": record.request_hash,
            "owning_surface": record.owning_surface,
            "resources": [resource(item) for item in record.resources],
            "dependency_resources": [
                resource(item) for item in record.dependency_resources
            ],
            "bid_uid": record.bid_uid,
            "page_uid": record.page_uid,
            "state": record.state.value,
        }

    @staticmethod
    def _record_from_dict(data: object) -> PendingSqlOperationRecord:
        if not isinstance(data, dict):
            raise ValueError("Pending SQL operation entries must be objects")
        expected_keys = {
            "database_id",
            "operation_id",
            "mutation_type",
            "request_hash",
            "owning_surface",
            "resources",
            "dependency_resources",
            "bid_uid",
            "page_uid",
            "state",
        }
        if set(data) != expected_keys:
            raise ValueError("Pending SQL operation entries are not canonical")
        for key in (
            "database_id",
            "operation_id",
            "mutation_type",
            "request_hash",
            "owning_surface",
            "page_uid",
            "state",
        ):
            if not isinstance(data[key], str):
                raise ValueError(f"Pending SQL operation {key} must be a string")
        if data["bid_uid"] is not None and type(data["bid_uid"]) is not int:
            raise ValueError("Pending SQL operation bid_uid must be an integer")

        def resources(key: str) -> tuple[ResourceRef, ...]:
            values = data[key]
            if not isinstance(values, list):
                raise ValueError("Pending SQL operation resources must be a list")
            result = []
            for item in values:
                if not isinstance(item, dict) or set(item) != {
                    "resource_type",
                    "resource_id",
                    "bid_uid",
                }:
                    raise ValueError(
                        "Pending SQL operation resources are not canonical"
                    )
                if not isinstance(item["resource_type"], str) or not isinstance(
                    item["resource_id"], str
                ):
                    raise ValueError(
                        "Pending SQL operation resource identities must be strings"
                    )
                if item["bid_uid"] is not None and type(item["bid_uid"]) is not int:
                    raise ValueError(
                        "Pending SQL operation resource bid_uid must be an integer"
                    )
                result.append(
                    ResourceRef(
                        item["resource_type"],
                        item["resource_id"],
                        item["bid_uid"],
                    )
                )
            return tuple(result)

        return PendingSqlOperationRecord(
            database_id=data["database_id"],
            operation_id=data["operation_id"],
            mutation_type=CollaborationMutationType(data["mutation_type"]),
            request_hash=data["request_hash"],
            owning_surface=data["owning_surface"],
            resources=resources("resources"),
            dependency_resources=resources("dependency_resources"),
            bid_uid=data["bid_uid"],
            page_uid=data["page_uid"],
            state=PendingMutationState(data["state"]),
        )
