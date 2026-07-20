from __future__ import annotations
from typing import Optional, Protocol


class IDatabaseSchemaInspector(Protocol):
    def table_exists(self, table_name: str) -> bool: ...
    def column_exists(self, table_name: str, column_name: str) -> bool: ...
    def require_table(self, table_name: str) -> None: ...
    def require_column(self, table_name: str, column_name: str) -> None: ...
    def get_columns(self, table_name: str) -> set[str]: ...
    def optional_table_missing(self, table_name: str) -> bool: ...
    def optional_column(
        self,
        table_name: str,
        column_name: str,
        default_sql: str,
        alias: Optional[str] = None,
    ) -> str: ...
    def order_by_existing(
        self,
        table_name: str,
        columns: tuple[str, ...],
        fallback: str,
    ) -> str: ...
    def log_optional_write_skip(
        self,
        table_name: str,
        column_name: str,
        operation: str,
    ) -> None: ...
