from __future__ import annotations
import logging
import contextvars
from contextlib import contextmanager
from typing import Optional
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...domain.entities.database_descriptor import DatabaseBackend
from ..mdb.connection_manager import MdbConnectionManager
from ..mdb.mdb_reader import MdbReader
from ..sql.reader import SqlProjectReader
from .descriptor_registry import resolve_database_backend


class DatabaseProjectReader(SqlProjectReader):
    def __init__(
        self,
        access_connections: MdbConnectionManager,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(
            descriptor_registry,
            credential_store,
            logger=logger,
        )
        self._access_connections = access_connections
        self._descriptor_registry = descriptor_registry
        self._active_backend = contextvars.ContextVar(
            "database_reader_backend", default=None
        )

    def _backend(self, locator: str) -> DatabaseBackend:
        active = self._active_backend.get()
        if active is not None:
            return active
        return resolve_database_backend(self._descriptor_registry, locator)

    def _is_sql(self, locator: str) -> bool:
        return self._backend(locator) == DatabaseBackend.SQL_SERVER

    @contextmanager
    def _connection(self, locator: str):
        token = None
        backend = self._active_backend.get()
        if backend is None:
            backend = resolve_database_backend(self._descriptor_registry, locator)
            token = self._active_backend.set(backend)
        try:
            if backend == DatabaseBackend.SQL_SERVER:
                with SqlProjectReader._connection(self, locator) as connection:
                    yield connection
                return
            with self._access_connections.connection(
                locator, autocommit=True
            ) as connection:
                yield connection
        finally:
            if token is not None:
                self._active_backend.reset(token)

    def parse_file(self, locator: str):
        descriptor = self._descriptor_registry.resolve(locator)
        backend = (
            descriptor.backend
            if descriptor is not None
            else resolve_database_backend(self._descriptor_registry, locator)
        )
        if backend == DatabaseBackend.SQL_SERVER and descriptor is None:
            raise LookupError("The SQL Server database descriptor is not registered.")
        token = self._active_backend.set(backend)
        try:
            if backend == DatabaseBackend.SQL_SERVER:
                hierarchy, cdn_types = SqlProjectReader.parse_file(self, locator)
            else:
                hierarchy, cdn_types = MdbReader.parse_file(self, locator)
        finally:
            self._active_backend.reset(token)
        return hierarchy, cdn_types

    def close_connection(self, locator: Optional[str] = None) -> None:
        if locator is None:
            self._access_connections.close()
        elif not self._is_sql(locator):
            self._access_connections.close_database(locator)

    def refresh_connection(self, locator: str) -> None:
        if not self._is_sql(locator):
            self._access_connections.close_read(locator)
