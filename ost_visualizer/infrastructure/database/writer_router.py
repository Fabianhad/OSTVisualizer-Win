from __future__ import annotations
import contextvars
import logging
from contextlib import contextmanager
from typing import Callable, Optional, TypeVar
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...application.interfaces.i_database_session_registry import (
    IDatabaseSessionRegistry,
)
from ...application.interfaces.i_database_mutation_executor import IMutationRecorder
from ...application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    ResourceRef,
)
from ...domain.dtos.raw_bid_data_dto import RawBidData
from ...domain.entities.database_descriptor import DatabaseBackend
from ..mdb.connection_manager import MdbConnectionManager
from ..mdb.mdb_writer import MdbWriter
from ..sql.writer import SqlProjectWriter
from .descriptor_registry import resolve_database_backend
from .schema_inspector_contract import IDatabaseSchemaInspector

T = TypeVar("T")


class DatabaseProjectWriter(SqlProjectWriter):
    def __init__(
        self,
        access_connections: MdbConnectionManager,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        session_registry: IDatabaseSessionRegistry,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(
            descriptor_registry,
            credential_store,
            session_registry,
            logger=logger,
        )
        self._conn_manager = access_connections
        self._descriptor_registry = descriptor_registry
        self._access_transaction_depth = contextvars.ContextVar(
            "database_project_writer_access_transaction_depth",
            default=0,
        )
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

    def execute(
        self,
        request: DatabaseMutationRequest,
        operation: Callable[[IMutationRecorder], T],
    ) -> DatabaseMutationResult[T]:
        with self._backend_scope(request.database_id) as backend:
            if backend == DatabaseBackend.SQL_SERVER:
                return SqlProjectWriter.execute(self, request, operation)
            with MdbWriter._connection(self, request.database_id):
                value = operation(_AccessMutationRecorder())
            return DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

    def _next_uid(self, cursor, table: str) -> int:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._next_uid(self, cursor, table)
        return MdbWriter._next_uid(self, cursor, table)

    def _record_caught_mutation_error(self, exc: BaseException) -> bool:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._record_caught_mutation_error(self, exc)
        return MdbWriter._record_caught_mutation_error(exc)

    def _is_access_resource_exceeded(self, exc: BaseException) -> bool:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._is_access_resource_exceeded(exc)
        return MdbWriter._is_access_resource_exceeded(self, exc)

    def _schema(self, connection) -> IDatabaseSchemaInspector:
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

    def _assign_next_bid_no(self, connection, remapped) -> None:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._assign_next_bid_no(self, connection, remapped)
        return MdbWriter._assign_next_bid_no(self, connection, remapped)

    def _get_table_info(self, connection, table: str):
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._get_table_info(self, connection, table)
        return MdbWriter._get_table_info(self, connection, table)

    def _load_existing_uid_by_column(
        self, connection, table: str, column: str
    ) -> dict[str, str]:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._load_existing_uid_by_column(
                self, connection, table, column
            )
        return MdbWriter._load_existing_uid_by_column(self, connection, table, column)

    def _load_existing_employee_uid_by_key(self, connection) -> dict[str, str]:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._load_existing_employee_uid_by_key(self, connection)
        return MdbWriter._load_existing_employee_uid_by_key(self, connection)

    def _insert_page_area_selection(
        self,
        cursor,
        schema,
        page_uid: int,
        area_uid: int | None,
        selected_value: int,
    ) -> None:
        if self._current_backend() == DatabaseBackend.SQL_SERVER:
            return SqlProjectWriter._insert_page_area_selection(
                self,
                cursor,
                schema,
                page_uid,
                area_uid,
                selected_value,
            )
        return MdbWriter._insert_page_area_selection(
            self,
            cursor,
            schema,
            page_uid,
            area_uid,
            selected_value,
        )

    def create_project(self, db_path: str, name: str) -> Optional[str]:
        with self._backend_scope(db_path) as backend:
            if backend == DatabaseBackend.SQL_SERVER:
                return SqlProjectWriter.create_project(self, db_path, name)
            return MdbWriter.create_project(self, db_path, name)

    def import_ost_data(
        self,
        db_path: str,
        raw_data: RawBidData,
        transform_fn: Callable,
        target_project_uid: Optional[str] = None,
    ) -> bool:
        with self._backend_scope(db_path) as backend:
            if backend == DatabaseBackend.SQL_SERVER:
                return SqlProjectWriter.import_ost_data(
                    self,
                    db_path,
                    raw_data,
                    transform_fn,
                    target_project_uid,
                )
            return MdbWriter.import_ost_data(
                self,
                db_path,
                raw_data,
                transform_fn,
                target_project_uid,
            )

    def save_page_view_state(
        self,
        db_path: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> bool:
        if (
            resolve_database_backend(self._descriptor_registry, db_path)
            == DatabaseBackend.SQL_SERVER
        ):
            return True
        return MdbWriter.save_page_view_state(
            self, db_path, page_uid, zoom_fac, current_x, current_y
        )

    def save_bid_selected_page(self, db_path: str, bid_uid: str, page_uid: str) -> bool:
        if (
            resolve_database_backend(self._descriptor_registry, db_path)
            == DatabaseBackend.SQL_SERVER
        ):
            return True
        return MdbWriter.save_bid_selected_page(self, db_path, bid_uid, page_uid)


class _AccessMutationRecorder:
    def record(
        self,
        resource: ResourceRef,
        operation: ChangeOperation,
        *,
        changed_fields: tuple[str, ...] = (),
        payload: str = "",
    ) -> None:
        del resource, operation, changed_fields, payload
