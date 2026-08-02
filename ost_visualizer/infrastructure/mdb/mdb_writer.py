import logging
import contextvars
from contextlib import contextmanager
from typing import Generator, Optional
import pyodbc
from .components.annotation_operations import AnnotationOperationsMixin
from .components.bid_operations import BidOperationsMixin
from .components.bulk_write_helpers import AccessBulkWriteMixin
from .components.condition_folder_operations import ConditionFolderOperationsMixin
from .components.condition_operations import ConditionOperationsMixin
from ..database.connection_wrapper import ConnectionWrapper
from ..database.schema_inspector_contract import IDatabaseSchemaInspector
from .components.import_operations import ImportOperationsMixin
from .components.layer_operations import LayerOperationsMixin
from .components.page_operations import PageOperationsMixin
from .components.project_operations import ProjectOperationsMixin
from .components.settings_operations import SettingsOperationsMixin
from .components.takeoff_operations import TakeoffOperationsMixin
from .connection_manager import MdbConnectionManager
from .schema_compatibility import MdbSchemaInspector, UnsupportedMdbSchemaError


class MdbWriter(
    AccessBulkWriteMixin,
    BidOperationsMixin,
    ConditionOperationsMixin,
    ConditionFolderOperationsMixin,
    ImportOperationsMixin,
    ProjectOperationsMixin,
    SettingsOperationsMixin,
    PageOperationsMixin,
    TakeoffOperationsMixin,
    AnnotationOperationsMixin,
    LayerOperationsMixin,
):
    def __init__(
        self,
        conn_manager: Optional[MdbConnectionManager] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._conn_manager = conn_manager or MdbConnectionManager()
        self._access_transaction_depth = contextvars.ContextVar(
            "mdb_writer_transaction_depth",
            default=0,
        )

    @contextmanager
    def _connection(self, db_path: str) -> Generator[ConnectionWrapper, None, None]:
        depth = self._access_transaction_depth.get()
        token = self._access_transaction_depth.set(depth + 1)
        try:
            with self._conn_manager.connection(db_path, autocommit=False) as conn:
                try:
                    yield conn
                    if depth == 0:
                        conn.commit()
                except Exception:
                    if depth == 0:
                        try:
                            conn.rollback()
                        except pyodbc.Error:
                            pass
                    raise
        finally:
            self._access_transaction_depth.reset(token)

    def _schema(self, connection) -> IDatabaseSchemaInspector:
        return MdbSchemaInspector(connection, self.logger)

    @staticmethod
    def _record_caught_mutation_error(_exc: BaseException) -> bool:
        return False

    def _require_write_columns(
        self, schema: IDatabaseSchemaInspector, table: str, columns: tuple[str, ...]
    ) -> None:
        for column in columns:
            schema.require_column(table, column)

    def _filter_existing_write_values(
        self,
        schema: IDatabaseSchemaInspector,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> dict:
        schema.require_table(table)
        self._require_write_columns(schema, table, required_columns)
        filtered = {}
        for column, value in values.items():
            if schema.column_exists(table, column):
                filtered[column] = value
                continue
            if column in required_columns:
                schema.require_column(table, column)
            schema.log_optional_write_skip(table, column, operation)
        return filtered

    def _execute_insert_values(
        self,
        cursor: pyodbc.Cursor,
        schema: IDatabaseSchemaInspector,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> None:
        filtered = self._filter_existing_write_values(
            schema, table, values, required_columns, operation
        )
        missing = [column for column in required_columns if column not in filtered]
        if missing:
            raise UnsupportedMdbSchemaError(
                f"This OST database is missing required writable columns "
                f"{table}.{', '.join(missing)} for {operation}."
            )
        if not filtered:
            raise UnsupportedMdbSchemaError(
                f"This OST database has no writable columns for {operation}."
            )
        col_list = ", ".join(f"[{column}]" for column in filtered)
        placeholders = ", ".join("?" for _ in filtered)
        cursor.execute(
            f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})",
            list(filtered.values()),
        )

    def _execute_update_values(
        self,
        cursor: pyodbc.Cursor,
        schema: IDatabaseSchemaInspector,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        where_sql: str,
        params: list,
        operation: str,
        allow_empty: bool = False,
    ) -> bool:
        filtered = self._filter_existing_write_values(
            schema, table, values, required_columns, operation
        )
        if not filtered:
            if allow_empty:
                return False
            raise UnsupportedMdbSchemaError(
                f"This OST database has no writable columns for {operation}."
            )
        set_clause = ", ".join(f"[{column}]=?" for column in filtered)
        cursor.execute(
            f"UPDATE [{table}] SET {set_clause} WHERE {where_sql}",
            list(filtered.values()) + params,
        )
        return True
