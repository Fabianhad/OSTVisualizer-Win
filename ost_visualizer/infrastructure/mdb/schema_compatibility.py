import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set
import pyodbc


class UnsupportedMdbSchemaError(RuntimeError):
    pass


@dataclass
class MdbCompatibilityReport:
    missing_optional_columns: Set[str] = field(default_factory=set)
    missing_required_columns: Set[str] = field(default_factory=set)
    detected_tables: Set[str] = field(default_factory=set)
    detected_schema_notes: Set[str] = field(default_factory=set)


class MdbSchemaInspector:
    _logged_optional_write_skips: Set[str] = set()

    def __init__(
        self,
        connection: "pyodbc.Connection",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.connection = connection
        self.logger = logger or logging.getLogger(__name__)
        self.report = MdbCompatibilityReport()
        self._table_columns: Dict[str, Set[str]] = {}
        self._tables: Optional[Set[str]] = None

    def table_exists(self, table_name: str) -> bool:
        return table_name in self._get_tables() or bool(self.get_columns(table_name))

    def column_exists(self, table_name: str, column_name: str) -> bool:
        return column_name in self.get_columns(table_name)

    def get_columns(self, table_name: str) -> Set[str]:
        if table_name not in self._table_columns:
            with self.connection.cursor() as cursor:
                try:
                    rows = cursor.columns(table=table_name).fetchall()
                except pyodbc.Error:
                    rows = []
            self._table_columns[table_name] = {row.column_name for row in rows}
        return self._table_columns[table_name]

    def require_table(self, table_name: str) -> None:
        if self.table_exists(table_name):
            return
        message = (
            f"This OST database is missing required table {table_name} "
            "and cannot be loaded."
        )
        raise UnsupportedMdbSchemaError(message)

    def require_column(self, table_name: str, column_name: str) -> None:
        self.require_table(table_name)
        if self.column_exists(table_name, column_name):
            return
        key = f"{table_name}.{column_name}"
        self.report.missing_required_columns.add(key)
        message = (
            f"This OST database is missing required column {key} "
            "and cannot be loaded."
        )
        raise UnsupportedMdbSchemaError(message)

    def optional_column(
        self,
        table_name: str,
        column_name: str,
        default_sql: str,
        alias: Optional[str] = None,
    ) -> str:
        alias_name = alias or column_name
        if self.column_exists(table_name, column_name):
            if alias_name == column_name:
                return f"[{column_name}]"
            return f"[{column_name}] AS [{alias_name}]"
        key = f"{table_name}.{column_name}"
        self.report.missing_optional_columns.add(key)
        return f"{default_sql} AS [{alias_name}]"

    def optional_table_missing(self, table_name: str) -> bool:
        if self.table_exists(table_name):
            return False
        self.report.detected_schema_notes.add(f"missing optional table {table_name}")
        return True

    def log_optional_write_skip(
        self, table_name: str, column_name: str, operation: str
    ) -> None:
        database_key = self._database_key()
        key = f"{database_key}:{table_name}.{column_name}:{operation}"
        if key in self._logged_optional_write_skips:
            return
        self._logged_optional_write_skips.add(key)

    def order_by_existing(
        self,
        table_name: str,
        columns: tuple[str, ...],
        fallback: str,
    ) -> str:
        order_columns = [
            f"[{column}]"
            for column in columns
            if self.column_exists(table_name, column)
        ]
        return ", ".join(order_columns) if order_columns else fallback

    def _get_tables(self) -> Set[str]:
        if self._tables is None:
            with self.connection.cursor() as cursor:
                try:
                    rows = cursor.tables(tableType="TABLE").fetchall()
                except pyodbc.Error:
                    rows = []
            self._tables = {row.table_name for row in rows}
            self.report.detected_tables.update(self._tables)
        return self._tables

    def _database_key(self) -> str:
        try:
            value = self.connection.getinfo(pyodbc.SQL_DATABASE_NAME)
        except (AttributeError, pyodbc.Error):
            return str(id(self.connection))
        return str(value) if value else str(id(self.connection))
