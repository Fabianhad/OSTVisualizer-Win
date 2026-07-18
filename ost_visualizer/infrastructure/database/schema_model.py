from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class SchemaColumn:
    name: str
    access_type: str
    required: bool = False
    primary_key: bool = False
    default: Optional[str] = None


@dataclass(frozen=True)
class SchemaIndex:
    name: str
    unique: bool
    columns: tuple[str, ...]


@dataclass(frozen=True)
class SchemaForeignKey:
    name: str
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str


@dataclass(frozen=True)
class SchemaTable:
    name: str
    columns: tuple[SchemaColumn, ...]
    indexes: tuple[SchemaIndex, ...] = ()


@dataclass(frozen=True)
class DatabaseSchemaModel:
    tables: tuple[SchemaTable, ...]
    foreign_keys: tuple[SchemaForeignKey, ...]

    @property
    def table_names(self) -> frozenset[str]:
        return frozenset(table.name for table in self.tables)

    @property
    def column_count(self) -> int:
        return sum(len(table.columns) for table in self.tables)

    def table(self, name: str) -> SchemaTable:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)


_TABLE_PATTERN = re.compile(
    r"CREATE\s+TABLE\s+\[([^]]+)]\s*\((.*)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_COLUMN_PATTERN = re.compile(r"^\[([^]]+)]\s+(.+?)\s*$", re.DOTALL)


def schema_model_from_access_ddl(
    table_ddl: Iterable[str],
    *,
    required_uid_tables: Iterable[str] = (),
    field_defaults: Optional[Mapping[tuple[str, str], str]] = None,
    indexes: Sequence[tuple[str, str, bool, tuple[str, ...]]] = (),
    relationships: Sequence[tuple[str, str, str, str, str]] = (),
) -> DatabaseSchemaModel:
    required = frozenset(required_uid_tables)
    defaults = {} if field_defaults is None else field_defaults
    indexes_by_table: dict[str, list[SchemaIndex]] = {}
    for table_name, index_name, unique, columns in indexes:
        indexes_by_table.setdefault(table_name, []).append(
            SchemaIndex(index_name, bool(unique), tuple(columns))
        )
    tables: list[SchemaTable] = []
    for statement in table_ddl:
        match = _TABLE_PATTERN.match(statement.strip())
        if match is None:
            raise ValueError("Unsupported Access table definition")
        table_name, body = match.groups()
        columns: list[SchemaColumn] = []
        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line:
                continue
            column_match = _COLUMN_PATTERN.match(line)
            if column_match is None:
                raise ValueError(f"Unsupported column definition in {table_name}")
            column_name, declaration = column_match.groups()
            upper_declaration = declaration.upper()
            primary_key = "PRIMARY KEY" in upper_declaration
            explicitly_required = "NOT NULL" in upper_declaration
            access_type = re.sub(
                r"\s+PRIMARY\s+KEY\s*$", "", declaration, flags=re.IGNORECASE
            ).strip()
            access_type = re.sub(
                r"\s+NOT\s+NULL\s*$", "", access_type, flags=re.IGNORECASE
            ).strip()
            columns.append(
                SchemaColumn(
                    name=column_name,
                    access_type=access_type,
                    required=primary_key
                    or explicitly_required
                    or (column_name == "UID" and table_name in required),
                    primary_key=primary_key,
                    default=defaults.get((table_name, column_name)),
                )
            )
        tables.append(
            SchemaTable(
                name=table_name,
                columns=tuple(columns),
                indexes=tuple(indexes_by_table.get(table_name, ())),
            )
        )
    foreign_keys = tuple(
        SchemaForeignKey(*relationship) for relationship in relationships
    )
    return DatabaseSchemaModel(tuple(tables), foreign_keys)


def render_sql_server_schema(model: DatabaseSchemaModel) -> tuple[str, ...]:
    statements: list[str] = []
    for table in model.tables:
        column_sql = []
        for column in table.columns:
            declaration = (
                f"[{column.name}] {sql_server_type_for_access(column.access_type)}"
            )
            declaration += " NOT NULL" if column.required else " NULL"
            if column.default is not None:
                declaration += f" DEFAULT ({column.default})"
            if column.primary_key:
                declaration += " PRIMARY KEY"
            column_sql.append(declaration)
        statements.append(
            f"CREATE TABLE [dbo].[{table.name}] (\n    "
            + ",\n    ".join(column_sql)
            + "\n)"
        )
    for table in model.tables:
        for index in table.indexes:
            unique = "UNIQUE " if index.unique else ""
            columns = ", ".join(f"[{name}]" for name in index.columns)
            statements.append(
                f"CREATE {unique}INDEX [{index.name}] ON "
                f"[dbo].[{table.name}] ({columns})"
            )
    for relationship in model.foreign_keys:
        statements.append(
            f"ALTER TABLE [dbo].[{relationship.child_table}] ADD CONSTRAINT "
            f"[{relationship.name}] FOREIGN KEY ([{relationship.child_column}]) "
            f"REFERENCES [dbo].[{relationship.parent_table}] "
            f"([{relationship.parent_column}])"
        )
    return tuple(statements)


def sql_server_type_for_access(access_type: str) -> str:
    normalized = access_type.strip().upper()
    if normalized == "COUNTER":
        return "int IDENTITY(1,1)"
    if normalized == "INTEGER":
        return "int"
    if normalized == "SMALLINT":
        return "smallint"
    if normalized == "DOUBLE":
        return "float"
    if normalized == "YESNO":
        return "bit"
    if normalized == "IMAGE":
        return "varbinary(max)"
    if normalized == "DATETIME":
        return "datetime2(3)"
    varchar_match = re.fullmatch(r"VARCHAR\((\d+)\)", normalized)
    if varchar_match:
        return f"nvarchar({varchar_match.group(1)})"
    raise ValueError(f"Unsupported Access type: {access_type}")
