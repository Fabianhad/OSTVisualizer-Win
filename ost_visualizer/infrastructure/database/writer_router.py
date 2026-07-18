from __future__ import annotations
import contextvars
import logging
from contextlib import contextmanager
from typing import Optional
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...domain.entities.database_descriptor import DatabaseBackend
from ..mdb.connection_manager import MdbConnectionManager
from ..mdb.mdb_writer import MdbWriter
from ..sql.writer import SqlProjectWriter
from .descriptor_registry import resolve_database_backend


class DatabaseProjectWriter(SqlProjectWriter):
    """Shared writer operations with one backend-specific primitive boundary."""

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
        self._conn_manager = access_connections
        self._descriptor_registry = descriptor_registry
        self._active_backend = contextvars.ContextVar(
            "database_writer_backend",
            default=None,
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
                with SqlProjectWriter._connection(self, locator) as connection:
                    yield connection
                return
            with MdbWriter._connection(self, locator) as connection:
                yield connection
        finally:
            if token is not None:
                self._active_backend.reset(token)

    @contextmanager
    def _backend_scope(self, locator: str):
        backend = resolve_database_backend(self._descriptor_registry, locator)
        token = self._active_backend.set(backend)
        try:
            yield backend
        finally:
            self._active_backend.reset(token)

    def _current_backend(self) -> DatabaseBackend:
        backend = self._active_backend.get()
        if backend is None:
            raise RuntimeError("Database writer operation has no active backend scope.")
        return backend

    def _next_uid(self, cursor, table: str) -> int:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._next_uid(self, cursor, table)
        return MdbWriter._next_uid(self, cursor, table)

    def _schema(self, connection):
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._schema(self, connection)
        return MdbWriter._schema(self, connection)

    def _execute_insert_values(
        self,
        cursor,
        schema,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ):
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._execute_insert_values(
                self,
                cursor,
                schema,
                table,
                values,
                required_columns,
                operation,
            )
        return MdbWriter._execute_insert_values(
            self,
            cursor,
            schema,
            table,
            values,
            required_columns,
            operation,
        )

    def _filter_existing_write_values(
        self,
        schema,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> dict:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._filter_existing_write_values(
                self,
                schema,
                table,
                values,
                required_columns,
                operation,
            )
        return MdbWriter._filter_existing_write_values(
            self,
            schema,
            table,
            values,
            required_columns,
            operation,
        )

    def create_project(self, locator: str, name: str):
        with self._backend_scope(locator) as backend:
            if backend == DatabaseBackend.SQL_SERVER:
                return SqlProjectWriter.create_project(self, locator, name)
            return MdbWriter.create_project(self, locator, name)

    def import_ost_data(
        self,
        locator: str,
        raw_data,
        transform_fn,
        target_project_uid=None,
    ):
        with self._backend_scope(locator) as backend:
            if backend == DatabaseBackend.SQL_SERVER:
                return SqlProjectWriter.import_ost_data(
                    self,
                    locator,
                    raw_data,
                    transform_fn,
                    target_project_uid,
                )
            return MdbWriter.import_ost_data(
                self,
                locator,
                raw_data,
                transform_fn,
                target_project_uid,
            )
