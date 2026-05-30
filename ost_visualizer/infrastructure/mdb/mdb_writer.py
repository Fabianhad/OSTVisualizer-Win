import logging
from contextlib import contextmanager
from typing import Generator, Optional
import pyodbc
from .components.annotation_operations import AnnotationOperationsMixin
from .components.bid_operations import BidOperationsMixin
from .components.condition_folder_operations import ConditionFolderOperationsMixin
from .components.condition_operations import ConditionOperationsMixin
from .components.connection_wrapper import ConnWrapper
from .components.import_operations import ImportOperationsMixin
from .components.layer_operations import LayerOperationsMixin
from .components.page_operations import PageOperationsMixin
from .components.project_operations import ProjectOperationsMixin
from .components.settings_operations import SettingsOperationsMixin
from .components.takeoff_operations import TakeoffOperationsMixin
from .connection_manager import MdbConnectionManager
from .schema_compatibility import MdbSchemaInspector, UnsupportedMdbSchemaError


class MdbWriter(
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

    @contextmanager
    def _connection(self, db_path: str) -> Generator[ConnWrapper, None, None]:
        with self._conn_manager.connection(db_path, autocommit=False) as conn:
            wrapper = ConnWrapper(conn)
            try:
                yield wrapper
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except pyodbc.Error:
                    pass
                raise
            finally:
                wrapper.close_cursors()

    def _next_uid(self, cursor: pyodbc.Cursor, table: str) -> int:
        cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
        result = cursor.fetchone()[0]
        return int(result) + 1 if result is not None else 1

    def _schema(self, connection) -> MdbSchemaInspector:
        return MdbSchemaInspector(connection, self.logger)

    def _require_write_columns(
        self, schema: MdbSchemaInspector, table: str, columns: tuple[str, ...]
    ) -> None:
        for column in columns:
            schema.require_column(table, column)

    def _filter_existing_write_values(
        self,
        schema: MdbSchemaInspector,
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
        schema: MdbSchemaInspector,
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
        schema: MdbSchemaInspector,
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
