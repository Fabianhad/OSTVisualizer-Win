from __future__ import annotations
from typing import Optional
from ..database.schema_model import (
    DatabaseSchemaModel,
    sql_server_type_for_access,
)
from .errors import sql_schema_mismatch


class CurrentSqlWriteSchema:
    """Exact write-time view of the one supported SQL schema."""

    def __init__(self, schema: DatabaseSchemaModel) -> None:
        self._columns = {
            table.name: frozenset(column.name for column in table.columns)
            for table in schema.tables
        }
        self._types = {
            table.name: {
                column.name: sql_server_type_for_access(column.access_type)
                .split()[0]
                .split("(")[0]
                .casefold()
                for column in table.columns
            }
            for table in schema.tables
        }

    def table_exists(self, table_name: str) -> bool:
        return table_name in self._columns

    def column_exists(self, table_name: str, column_name: str) -> bool:
        self.require_column(table_name, column_name)
        return True

    def require_table(self, table_name: str) -> None:
        if not self.table_exists(table_name):
            self._raise_mismatch(f"dbo.{table_name}")

    def require_column(self, table_name: str, column_name: str) -> None:
        self.require_table(table_name)
        if column_name not in self._columns[table_name]:
            self._raise_mismatch(f"dbo.{table_name}.{column_name}")

    def table_info(self, table_name: str) -> tuple[set[str], dict[str, str]]:
        self.require_table(table_name)
        return set(self._columns[table_name]), dict(self._types[table_name])

    def optional_table_missing(self, table_name: str) -> bool:
        self.require_table(table_name)
        return False

    def optional_column(
        self,
        table_name: str,
        column_name: str,
        default_sql: str,
        alias: Optional[str] = None,
    ) -> str:
        del default_sql
        self.require_column(table_name, column_name)
        alias_name = column_name if alias is None else alias
        if alias_name == column_name:
            return f"[{column_name}]"
        return f"[{column_name}] AS [{alias_name}]"

    def log_optional_write_skip(
        self, table_name: str, column_name: str, operation: str
    ) -> None:
        self._raise_mismatch(f"{operation}: dbo.{table_name}.{column_name}")

    @staticmethod
    def _raise_mismatch(resource: str) -> None:
        raise sql_schema_mismatch(
            f"The current SQL schema does not support {resource}."
        )
