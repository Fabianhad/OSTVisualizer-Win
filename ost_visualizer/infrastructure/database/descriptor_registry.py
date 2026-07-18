from __future__ import annotations
import threading
import os
from pathlib import Path
from typing import Iterable, Optional
from ...domain.entities.database_descriptor import DatabaseDescriptor
from ...domain.entities.database_descriptor import DatabaseBackend
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)


class DatabaseDescriptorRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._descriptors: dict[str, DatabaseDescriptor] = {}
        self._access_locators: dict[str, DatabaseDescriptor] = {}

    def register(self, descriptor: DatabaseDescriptor) -> None:
        with self._lock:
            previous = self._descriptors.get(descriptor.database_id)
            if previous is not None and previous.backend == DatabaseBackend.ACCESS:
                self._access_locators.pop(_normalize_access(previous.access_path), None)
            self._descriptors[descriptor.database_id] = descriptor
            if descriptor.backend == DatabaseBackend.ACCESS:
                self._access_locators[_normalize_access(descriptor.access_path)] = (
                    descriptor
                )

    def register_all(self, descriptors: Iterable[DatabaseDescriptor]) -> None:
        for descriptor in descriptors:
            self.register(descriptor)

    def resolve(self, locator: str) -> Optional[DatabaseDescriptor]:
        with self._lock:
            descriptor = self._descriptors.get(locator)
            if descriptor is not None:
                return descriptor
            return self._access_locators.get(_normalize_access(locator))

    def unregister(self, database_id: str) -> None:
        with self._lock:
            descriptor = self._descriptors.pop(database_id, None)
            if descriptor is not None and descriptor.backend == DatabaseBackend.ACCESS:
                self._access_locators.pop(
                    _normalize_access(descriptor.access_path), None
                )


def resolve_database_backend(
    registry: IDatabaseDescriptorRegistry, locator: str
) -> DatabaseBackend:
    descriptor = registry.resolve(locator)
    if descriptor is not None:
        return descriptor.backend
    if Path(locator).suffix.casefold() == ".mdb":
        return DatabaseBackend.ACCESS
    raise LookupError("The database descriptor is not registered.")


def _normalize_access(locator: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(locator)))
