from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum
from ..database.schema_model import (
    DatabaseSchemaModel,
    sql_server_type_for_access,
)
from .schema_definition import (
    LATEST_SQL_SCHEMA,
    SqlColumnDefinition,
    SqlSchemaDefinition,
    SqlTableDefinition,
)
from .schema_inspector import SqlColumnInventory, SqlSchemaInventory


class SqlSchemaCompatibility(str, Enum):
    CURRENT = "current"
    UNVERSIONED_READ_ONLY = "unversioned_read_only"
    INVALID = "invalid"
    UNSUPPORTED_VERSION = "unsupported_version"


@dataclass(frozen=True)
class SqlSchemaValidationReport:
    compatibility: SqlSchemaCompatibility
    schema_version: int
    problems: tuple[str, ...] = ()

    @property
    def is_read_compatible(self) -> bool:
        return self.compatibility in {
            SqlSchemaCompatibility.CURRENT,
            SqlSchemaCompatibility.UNVERSIONED_READ_ONLY,
        }

    @property
    def user_message(self) -> str:
        if self.compatibility == SqlSchemaCompatibility.UNSUPPORTED_VERSION:
            return "Database uses an unsupported OST Visualizer schema version."
        if self.problems:
            return "Schema mismatch: " + ", ".join(self.problems)
        return ""


class SqlSchemaValidator:
    def __init__(self, shared_schema: DatabaseSchemaModel) -> None:
        self._shared_schema = shared_schema

    def validate(self, inventory: SqlSchemaInventory) -> SqlSchemaValidationReport:
        if inventory.schema_version not in (0, LATEST_SQL_SCHEMA.version):
            return SqlSchemaValidationReport(
                SqlSchemaCompatibility.UNSUPPORTED_VERSION,
                inventory.schema_version,
            )
        problems = self._validate_core_tables(
            inventory,
            require_constraints=(inventory.schema_version == LATEST_SQL_SCHEMA.version),
        )
        if inventory.schema_version == 0:
            if any(schema == "ostv" for schema, _table in inventory.tables):
                problems.append("ostv.partial_schema")
            compatibility = (
                SqlSchemaCompatibility.UNVERSIONED_READ_ONLY
                if not problems
                else SqlSchemaCompatibility.INVALID
            )
            return SqlSchemaValidationReport(
                compatibility,
                0,
                tuple(problems),
            )
        problems.extend(self._validate_ostv_tables(inventory, LATEST_SQL_SCHEMA))
        if inventory.schema_checksum != LATEST_SQL_SCHEMA.checksum:
            problems.append("ostv.SchemaMigrations.Checksum")
        return SqlSchemaValidationReport(
            (
                SqlSchemaCompatibility.CURRENT
                if not problems
                else SqlSchemaCompatibility.INVALID
            ),
            inventory.schema_version,
            tuple(problems),
        )

    def validate_versioned_schema(
        self,
        inventory: SqlSchemaInventory,
        schema: SqlSchemaDefinition,
    ) -> SqlSchemaValidationReport:
        if inventory.schema_version != schema.version:
            return SqlSchemaValidationReport(
                SqlSchemaCompatibility.UNSUPPORTED_VERSION,
                inventory.schema_version,
            )
        problems = self._validate_core_tables(inventory, require_constraints=True)
        problems.extend(self._validate_ostv_tables(inventory, schema))
        if inventory.schema_checksum != schema.checksum:
            problems.append("ostv.SchemaMigrations.Checksum")
        return SqlSchemaValidationReport(
            (
                SqlSchemaCompatibility.CURRENT
                if not problems
                else SqlSchemaCompatibility.INVALID
            ),
            inventory.schema_version,
            tuple(problems),
        )

    def validate_adoption_candidate(
        self, inventory: SqlSchemaInventory
    ) -> SqlSchemaValidationReport:
        if inventory.schema_version != 0:
            return SqlSchemaValidationReport(
                SqlSchemaCompatibility.UNSUPPORTED_VERSION,
                inventory.schema_version,
            )
        problems = self._validate_core_tables(inventory, require_constraints=True)
        if any(schema == "ostv" for schema, _table in inventory.tables):
            problems.append("ostv.partial_schema")
        return SqlSchemaValidationReport(
            (
                SqlSchemaCompatibility.UNVERSIONED_READ_ONLY
                if not problems
                else SqlSchemaCompatibility.INVALID
            ),
            0,
            tuple(problems),
        )

    def _validate_core_tables(
        self,
        inventory: SqlSchemaInventory,
        *,
        require_constraints: bool,
    ) -> list[str]:
        actual_tables = {name for schema, name in inventory.tables if schema == "dbo"}
        expected_tables = self._shared_schema.table_names
        problems = [f"dbo.{table}" for table in sorted(expected_tables - actual_tables)]
        problems.extend(
            f"{schema}.{table}.shadows_dbo"
            for schema, table in sorted(inventory.tables)
            if schema != "dbo" and table in expected_tables
        )
        problems.extend(
            f"dbo.{table}.unexpected"
            for table in sorted(actual_tables - expected_tables)
        )
        actual_columns = inventory.dbo_columns()
        for table in self._shared_schema.tables:
            if table.name not in actual_tables:
                continue
            table_columns = actual_columns.get(table.name, {})
            expected_columns = {column.name for column in table.columns}
            problems.extend(
                f"dbo.{table.name}.{column}.unexpected"
                for column in sorted(set(table_columns) - expected_columns)
            )
            for column in table.columns:
                actual = table_columns.get(column.name)
                label = f"dbo.{table.name}.{column.name}"
                if actual is None:
                    problems.append(label)
                    continue
                if require_constraints:
                    expected_type = sql_server_type_for_access(column.access_type)
                    if not (
                        _matches_type(actual, expected_type)
                        or _matches_core_storage_type(actual, column.access_type)
                    ):
                        problems.append(label)
                    if actual.nullable == column.required:
                        problems.append(label + ".nullability")
                    expected_identity = column.access_type.strip().upper() == "COUNTER"
                    if actual.identity != expected_identity:
                        problems.append(label + ".identity")
                    if actual.computed:
                        problems.append(label + ".computed")
                    if not _matches_default(actual.default_definition, column.default):
                        problems.append(label + ".default")
                elif not _matches_core_storage_type(actual, column.access_type):
                    problems.append(label)
        if require_constraints:
            problems.extend(self._validate_core_constraints(inventory))
        return problems

    def _validate_core_constraints(self, inventory: SqlSchemaInventory) -> list[str]:
        problems: list[str] = []
        indexes = {
            (index.schema_name, index.table_name, index.index_name): index
            for index in inventory.indexes
        }
        primary_keys = {
            (index.schema_name, index.table_name): index
            for index in inventory.indexes
            if index.primary_key
        }
        for table in self._shared_schema.tables:
            primary_columns = tuple(
                column.name for column in table.columns if column.primary_key
            )
            if primary_columns:
                actual = primary_keys.get(("dbo", table.name))
                if actual is None or actual.columns != primary_columns:
                    problems.append(f"dbo.{table.name}.primary_key")
            for expected in table.indexes:
                actual = indexes.get(("dbo", table.name, expected.name))
                if actual is None:
                    actual = next(
                        (
                            candidate
                            for (
                                schema,
                                table_name,
                                _name,
                            ), candidate in indexes.items()
                            if schema == "dbo"
                            and table_name == table.name
                            and candidate.columns == expected.columns
                            and candidate.unique == expected.unique
                            and not candidate.filter_expression
                        ),
                        None,
                    )
                if (
                    actual is None
                    or actual.columns != expected.columns
                    or actual.unique != expected.unique
                    or actual.filter_expression
                ):
                    problems.append(f"dbo.{table.name}.{expected.name}")
        foreign_keys = {
            (
                foreign_key.name,
                foreign_key.child_schema,
                foreign_key.child_table,
                foreign_key.child_column,
                foreign_key.parent_schema,
                foreign_key.parent_table,
                foreign_key.parent_column,
            )
            for foreign_key in inventory.foreign_keys
        }
        for expected in self._shared_schema.foreign_keys:
            key = (
                expected.name,
                "dbo",
                expected.child_table,
                expected.child_column,
                "dbo",
                expected.parent_table,
                expected.parent_column,
            )
            semantic_key = key[1:]
            if key not in foreign_keys and not any(
                tuple(value.casefold() for value in candidate[1:])
                == tuple(value.casefold() for value in semantic_key)
                for candidate in foreign_keys
            ):
                problems.append(f"dbo.{expected.child_table}.{expected.name}")
        return problems

    @staticmethod
    def _validate_ostv_tables(
        inventory: SqlSchemaInventory, schema: SqlSchemaDefinition
    ) -> list[str]:
        actual_tables = set(inventory.tables)
        actual_columns: dict[tuple[str, str], dict[str, SqlColumnInventory]] = {}
        for column in inventory.columns:
            actual_columns.setdefault((column.schema_name, column.table_name), {})[
                column.column_name
            ] = column
        problems: list[str] = []
        for table in schema.tables:
            table_key = (table.schema, table.name)
            if table_key not in actual_tables:
                problems.append(f"{table.schema}.{table.name}")
                continue
            columns = actual_columns.get(table_key, {})
            for expected in table.columns:
                actual = columns.get(expected.name)
                label = f"{table.schema}.{table.name}.{expected.name}"
                if actual is None or not _matches_sql_column(actual, expected):
                    problems.append(label)
            problems.extend(_validate_table_constraints(inventory, table))
        return problems


def _matches_sql_column(
    actual: SqlColumnInventory,
    expected: SqlColumnDefinition,
) -> bool:
    return (
        _matches_type(actual, expected.data_type)
        and actual.nullable == expected.nullable
        and actual.identity == expected.identity
        and not actual.computed
        and _matches_default(actual.default_definition, expected.default or None)
    )


def _validate_table_constraints(
    inventory: SqlSchemaInventory,
    table: SqlTableDefinition,
) -> list[str]:
    problems: list[str] = []
    table_indexes = [
        index
        for index in inventory.indexes
        if index.schema_name == table.schema and index.table_name == table.name
    ]
    primary = next((index for index in table_indexes if index.primary_key), None)
    if primary is None or primary.columns != table.primary_key:
        problems.append(f"{table.schema}.{table.name}.primary_key")
    named_indexes = {index.index_name: index for index in table_indexes}
    for name, columns in table.unique_constraints:
        actual = named_indexes.get(name)
        if (
            actual is None
            or actual.columns != columns
            or not actual.unique
            or actual.filter_expression
        ):
            problems.append(f"{table.schema}.{table.name}.{name}")
    for expected in table.indexes:
        actual = named_indexes.get(expected.name)
        if (
            actual is None
            or actual.columns != expected.columns
            or actual.unique != expected.unique
            or _normalize_filter(actual.filter_expression)
            != _normalize_filter(expected.filter_expression)
        ):
            problems.append(f"{table.schema}.{table.name}.{expected.name}")
    actual_foreign_keys = {
        (
            foreign_key.name,
            foreign_key.child_column,
            foreign_key.parent_schema,
            foreign_key.parent_table,
            foreign_key.parent_column,
            foreign_key.on_delete_action,
        )
        for foreign_key in inventory.foreign_keys
        if foreign_key.child_schema == table.schema
        and foreign_key.child_table == table.name
    }
    for expected in table.foreign_keys:
        for child, parent in zip(expected.columns, expected.referenced_columns):
            key = (
                expected.name,
                child,
                expected.referenced_schema,
                expected.referenced_table,
                parent,
                (
                    expected.on_delete.replace(" ", "_")
                    if expected.on_delete
                    else "NO_ACTION"
                ),
            )
            if key not in actual_foreign_keys:
                problems.append(f"{table.schema}.{table.name}.{expected.name}")
    actual_checks = {
        check.name: _normalize_filter(check.definition)
        for check in inventory.check_constraints
        if check.schema_name == table.schema and check.table_name == table.name
    }
    for name, expression in table.check_constraints:
        if actual_checks.get(name) != _normalize_filter(expression):
            problems.append(f"{table.schema}.{table.name}.{name}")
    return problems


def _matches_default(actual: str, expected: str | None) -> bool:
    if expected is None:
        return not actual
    return _normalize_default(actual) == _normalize_default(expected)


def _normalize_default(value: str) -> str:
    normalized = value.strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return "".join(normalized.casefold().split())


def _normalize_filter(value: str) -> str:
    normalized = value.strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return "".join(normalized.casefold().split())


def _matches_type(actual: SqlColumnInventory, expected_type: str) -> bool:
    normalized = expected_type.casefold().replace(" identity(1,1)", "")
    if normalized == "rowversion":
        return actual.data_type.casefold() in {"rowversion", "timestamp"}
    match = re.fullmatch(r"(n?varchar|varbinary|char)\((max|\d+)\)", normalized)
    if match:
        type_name, length = match.groups()
        if actual.data_type.casefold() != type_name:
            return False
        if length == "max":
            return actual.max_length == -1
        expected_length = int(length) * (2 if type_name == "nvarchar" else 1)
        return actual.max_length == expected_length
    datetime_match = re.fullmatch(r"datetime2\((\d+)\)", normalized)
    if datetime_match:
        return actual.data_type.casefold() == "datetime2" and actual.scale == int(
            datetime_match.group(1)
        )
    return actual.data_type.casefold() == normalized


def _matches_core_storage_type(
    actual: SqlColumnInventory,
    access_type: str,
) -> bool:
    normalized = access_type.strip().upper()
    actual_type = actual.data_type.casefold()
    if normalized in {"COUNTER", "INTEGER"}:
        return actual_type == "int"
    if normalized == "SMALLINT":
        return actual_type == "smallint"
    if normalized == "DOUBLE":
        return actual_type == "float"
    if normalized == "YESNO":
        return actual_type == "bit"
    if normalized == "IMAGE":
        return actual_type in {"image", "varbinary"}
    if normalized == "DATETIME":
        return actual_type in {"datetime", "datetime2"}
    if normalized.startswith("VARCHAR("):
        return actual_type in {"varchar", "nvarchar"}
    return False
