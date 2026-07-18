from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from ...domain.entities.database_descriptor import SqlServerDatabaseLocation
from .connection_manager import SqlConnectionManager, SqlConnectionRequest


@dataclass(frozen=True)
class SqlColumnInventory:
    schema_name: str
    table_name: str
    column_name: str
    ordinal: int
    data_type: str
    max_length: int
    precision: int
    scale: int
    nullable: bool
    identity: bool
    computed: bool
    default_definition: str = ""


@dataclass(frozen=True)
class SqlForeignKeyInventory:
    name: str
    child_schema: str
    child_table: str
    child_column: str
    parent_schema: str
    parent_table: str
    parent_column: str


@dataclass(frozen=True)
class SqlIndexInventory:
    schema_name: str
    table_name: str
    index_name: str
    unique: bool
    primary_key: bool
    columns: tuple[str, ...]
    filter_expression: str


@dataclass(frozen=True)
class SqlModuleInventory:
    schema_name: str
    name: str
    module_type: str


@dataclass(frozen=True)
class SqlSchemaInventory:
    database_guid: str
    schema_version: int
    schema_checksum: str
    tables: frozenset[tuple[str, str]]
    columns: tuple[SqlColumnInventory, ...]
    foreign_keys: tuple[SqlForeignKeyInventory, ...]
    indexes: tuple[SqlIndexInventory, ...]
    views: tuple[SqlModuleInventory, ...]
    triggers: tuple[SqlModuleInventory, ...]
    procedures: tuple[SqlModuleInventory, ...]
    functions: tuple[SqlModuleInventory, ...]

    def dbo_columns(self) -> dict[str, dict[str, SqlColumnInventory]]:
        result: dict[str, dict[str, SqlColumnInventory]] = {}
        for column in self.columns:
            if column.schema_name == "dbo":
                result.setdefault(column.table_name, {})[column.column_name] = column
        return result


class SqlSchemaInspector:
    def __init__(self, connection_manager: Optional[SqlConnectionManager] = None):
        self._connections = connection_manager or SqlConnectionManager()

    def inspect(
        self,
        location: SqlServerDatabaseLocation,
        password: str = "",
        *,
        database_override: Optional[str] = None,
    ) -> SqlSchemaInventory:
        request = SqlConnectionRequest(
            location=location,
            password=password,
            database_override=database_override,
            read_only=True,
        )
        return self.inspect_request(request)

    def inspect_request(self, request: SqlConnectionRequest) -> SqlSchemaInventory:
        with self._connections.connection(request, autocommit=True) as lease:
            return self.inspect_connection(lease)

    @staticmethod
    def inspect_connection(connection) -> SqlSchemaInventory:
        with connection.cursor() as cursor:
            return _read_inventory(cursor)


def _read_inventory(cursor) -> SqlSchemaInventory:
    cursor.execute(
        "SELECT CONVERT(nvarchar(36), database_guid) "
        "FROM sys.database_recovery_status WHERE database_id=DB_ID()"
    )
    guid_row = cursor.fetchone()
    database_guid = str(guid_row[0]) if guid_row and guid_row[0] else ""
    cursor.execute(
        "SELECT s.name, t.name FROM sys.tables t "
        "JOIN sys.schemas s ON s.schema_id=t.schema_id"
    )
    tables = frozenset((str(row[0]), str(row[1])) for row in cursor.fetchall())
    schema_version = 0
    schema_checksum = ""
    if ("ostv", "DatabaseMetadata") in tables:
        cursor.execute(
            "SELECT COALESCE(MAX([SchemaVersion]), 0) " "FROM [ostv].[DatabaseMetadata]"
        )
        version_row = cursor.fetchone()
        schema_version = int(version_row[0] or 0) if version_row else 0
        if ("ostv", "SchemaMigrations") in tables and schema_version:
            cursor.execute(
                "SELECT [Checksum] FROM [ostv].[SchemaMigrations] " "WHERE [Version]=?",
                schema_version,
            )
            checksum_row = cursor.fetchone()
            schema_checksum = str(checksum_row[0]) if checksum_row is not None else ""
    cursor.execute(
        "SELECT s.name, t.name, c.name, c.column_id, ty.name, "
        "c.max_length, c.precision, c.scale, c.is_nullable, "
        "c.is_identity, c.is_computed, COALESCE(dc.definition, N'') "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "JOIN sys.columns c ON c.object_id=t.object_id "
        "JOIN sys.types ty ON ty.user_type_id=c.user_type_id "
        "LEFT JOIN sys.default_constraints dc ON dc.parent_object_id=t.object_id "
        "AND dc.parent_column_id=c.column_id "
        "ORDER BY s.name, t.name, c.column_id"
    )
    columns = tuple(
        SqlColumnInventory(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            int(row[3]),
            str(row[4]),
            int(row[5]),
            int(row[6]),
            int(row[7]),
            bool(row[8]),
            bool(row[9]),
            bool(row[10]),
            str(row[11] or ""),
        )
        for row in cursor.fetchall()
    )
    cursor.execute(
        "SELECT fk.name, cs.name, ct.name, cc.name, ps.name, pt.name, pc.name "
        "FROM sys.foreign_keys fk "
        "JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id "
        "JOIN sys.tables ct ON ct.object_id=fkc.parent_object_id "
        "JOIN sys.schemas cs ON cs.schema_id=ct.schema_id "
        "JOIN sys.columns cc ON cc.object_id=ct.object_id "
        "AND cc.column_id=fkc.parent_column_id "
        "JOIN sys.tables pt ON pt.object_id=fkc.referenced_object_id "
        "JOIN sys.schemas ps ON ps.schema_id=pt.schema_id "
        "JOIN sys.columns pc ON pc.object_id=pt.object_id "
        "AND pc.column_id=fkc.referenced_column_id "
        "ORDER BY fk.name, fkc.constraint_column_id"
    )
    foreign_keys = tuple(
        SqlForeignKeyInventory(*(str(value) for value in row))
        for row in cursor.fetchall()
    )
    cursor.execute(
        "SELECT s.name, t.name, i.name, i.is_unique, i.is_primary_key, "
        "c.name, ic.key_ordinal, COALESCE(i.filter_definition, N'') "
        "FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id "
        "JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "JOIN sys.index_columns ic ON ic.object_id=i.object_id "
        "AND ic.index_id=i.index_id AND ic.key_ordinal > 0 "
        "JOIN sys.columns c ON c.object_id=i.object_id "
        "AND c.column_id=ic.column_id "
        "WHERE i.name IS NOT NULL ORDER BY s.name, t.name, i.name, ic.key_ordinal"
    )
    indexes = _group_indexes(cursor.fetchall())
    views = _modules(cursor, "V")
    procedures = _modules(cursor, "P")
    functions = _modules(cursor, "FN", "IF", "TF", "FS", "FT")
    cursor.execute(
        "SELECT s.name, tr.name, 'TR' FROM sys.triggers tr "
        "JOIN sys.objects parent ON parent.object_id=tr.parent_id "
        "JOIN sys.schemas s ON s.schema_id=parent.schema_id "
        "WHERE tr.parent_class=1 ORDER BY s.name, tr.name"
    )
    triggers = tuple(
        SqlModuleInventory(str(row[0]), str(row[1]), str(row[2]))
        for row in cursor.fetchall()
    )
    return SqlSchemaInventory(
        database_guid=database_guid,
        schema_version=schema_version,
        schema_checksum=schema_checksum,
        tables=tables,
        columns=columns,
        foreign_keys=foreign_keys,
        indexes=indexes,
        views=views,
        triggers=triggers,
        procedures=procedures,
        functions=functions,
    )


def _group_indexes(rows) -> tuple[SqlIndexInventory, ...]:
    grouped: dict[tuple[str, str, str, bool, bool, str], list[tuple[int, str]]] = {}
    for row in rows:
        key = (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            bool(row[3]),
            bool(row[4]),
            str(row[7]),
        )
        grouped.setdefault(key, []).append((int(row[6]), str(row[5])))
    return tuple(
        SqlIndexInventory(
            schema_name=key[0],
            table_name=key[1],
            index_name=key[2],
            unique=key[3],
            primary_key=key[4],
            columns=tuple(name for _, name in sorted(values)),
            filter_expression=key[5],
        )
        for key, values in sorted(grouped.items())
    )


def _modules(cursor, *module_types: str) -> tuple[SqlModuleInventory, ...]:
    placeholders = ",".join("?" for _ in module_types)
    cursor.execute(
        "SELECT s.name, o.name, o.type FROM sys.objects o "
        "JOIN sys.schemas s ON s.schema_id=o.schema_id "
        f"WHERE o.type IN ({placeholders}) ORDER BY s.name, o.name",
        *module_types,
    )
    return tuple(
        SqlModuleInventory(str(row[0]), str(row[1]), str(row[2]))
        for row in cursor.fetchall()
    )
