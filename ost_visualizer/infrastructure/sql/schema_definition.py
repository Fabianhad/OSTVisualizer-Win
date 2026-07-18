from __future__ import annotations
import hashlib
from dataclasses import dataclass
from ..database.schema_model import DatabaseSchemaModel, render_sql_server_schema
from ..mdb.database_creator import get_reference_schema_model


@dataclass(frozen=True)
class SqlColumnDefinition:
    name: str
    data_type: str
    nullable: bool = False
    identity: bool = False
    default: str = ""


@dataclass(frozen=True)
class SqlForeignKeyDefinition:
    name: str
    columns: tuple[str, ...]
    referenced_schema: str
    referenced_table: str
    referenced_columns: tuple[str, ...]


@dataclass(frozen=True)
class SqlIndexDefinition:
    name: str
    columns: tuple[str, ...]
    unique: bool = False
    filter_expression: str = ""


@dataclass(frozen=True)
class SqlTableDefinition:
    schema: str
    name: str
    columns: tuple[SqlColumnDefinition, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[SqlForeignKeyDefinition, ...] = ()
    unique_constraints: tuple[tuple[str, tuple[str, ...]], ...] = ()
    indexes: tuple[SqlIndexDefinition, ...] = ()


@dataclass(frozen=True)
class SqlSchemaDefinition:
    version: int
    migration_name: str
    core_schema: DatabaseSchemaModel
    tables: tuple[SqlTableDefinition, ...]

    @property
    def statements(self) -> tuple[str, ...]:
        statements = list(render_sql_server_schema(self.core_schema))
        statements.extend(self.extension_statements)
        return tuple(statements)

    @property
    def extension_statements(self) -> tuple[str, ...]:
        statements = []
        statements.append("CREATE SCHEMA [ostv] AUTHORIZATION [dbo]")
        for table in self.tables:
            statements.append(_render_table(table))
            statements.extend(_render_index(table, index) for index in table.indexes)
        return tuple(statements)

    @property
    def checksum(self) -> str:
        source = "\n-- statement --\n".join(self.statements).encode("utf-8")
        return hashlib.sha256(source).hexdigest()


def _column(
    name: str,
    data_type: str,
    *,
    nullable: bool = False,
    identity: bool = False,
    default: str = "",
) -> SqlColumnDefinition:
    return SqlColumnDefinition(name, data_type, nullable, identity, default)


def _foreign_key(
    name: str,
    column: str,
    referenced_table: str,
    referenced_column: str,
) -> SqlForeignKeyDefinition:
    return SqlForeignKeyDefinition(
        name,
        (column,),
        "ostv",
        referenced_table,
        (referenced_column,),
    )


LATEST_SQL_SCHEMA = SqlSchemaDefinition(
    version=1,
    migration_name="initial OST Visualizer SQL schema",
    core_schema=get_reference_schema_model(),
    tables=(
        SqlTableDefinition(
            "ostv",
            "DatabaseMetadata",
            (
                _column("DatabaseGuid", "uniqueidentifier"),
                _column("Product", "nvarchar(100)"),
                _column("SchemaVersion", "int"),
                _column("CreatedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("CreatedBy", "nvarchar(256)"),
                _column("LastMigratedAt", "datetime2(3)"),
                _column("LastMigratedBy", "nvarchar(256)"),
            ),
            ("DatabaseGuid",),
        ),
        SqlTableDefinition(
            "ostv",
            "SchemaMigrations",
            (
                _column("Version", "int"),
                _column("Name", "nvarchar(200)"),
                _column("Checksum", "char(64)"),
                _column("AppliedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("AppliedBy", "nvarchar(256)"),
                _column("ApplicationVersion", "nvarchar(64)"),
            ),
            ("Version",),
        ),
        SqlTableDefinition(
            "ostv",
            "Sessions",
            (
                _column("SessionId", "uniqueidentifier"),
                _column("UserIdentity", "nvarchar(256)"),
                _column("ClientInstanceId", "uniqueidentifier"),
                _column("ApplicationVersion", "nvarchar(64)"),
                _column("ConnectedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("LastHeartbeatAt", "datetime2(3)"),
                _column("DisconnectedAt", "datetime2(3)", nullable=True),
                _column("Version", "rowversion"),
            ),
            ("SessionId",),
            indexes=(
                SqlIndexDefinition(
                    "IX_ostv_Sessions_Heartbeat",
                    ("LastHeartbeatAt",),
                    filter_expression="[DisconnectedAt] IS NULL",
                ),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "Presence",
            (
                _column("PresenceId", "bigint", identity=True),
                _column("SessionId", "uniqueidentifier"),
                _column("BidUID", "int"),
                _column("CurrentPageUID", "int", nullable=True),
                _column("EnteredAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("LastHeartbeatAt", "datetime2(3)"),
            ),
            ("PresenceId",),
            foreign_keys=(
                _foreign_key(
                    "FK_ostv_Presence_Sessions",
                    "SessionId",
                    "Sessions",
                    "SessionId",
                ),
            ),
            unique_constraints=(
                ("UQ_ostv_Presence_SessionBid", ("SessionId", "BidUID")),
            ),
            indexes=(
                SqlIndexDefinition(
                    "IX_ostv_Presence_BidHeartbeat",
                    ("BidUID", "LastHeartbeatAt"),
                ),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "Locks",
            (
                _column("LockId", "bigint", identity=True),
                _column("ResourceType", "nvarchar(64)"),
                _column("ResourceId", "nvarchar(128)"),
                _column("OwnerSessionId", "uniqueidentifier"),
                _column("LockMode", "nvarchar(32)"),
                _column("OperationDescription", "nvarchar(256)", nullable=True),
                _column("AcquiredAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("ExpiresAt", "datetime2(3)"),
            ),
            ("LockId",),
            foreign_keys=(
                _foreign_key(
                    "FK_ostv_Locks_Sessions",
                    "OwnerSessionId",
                    "Sessions",
                    "SessionId",
                ),
            ),
            unique_constraints=(
                ("UQ_ostv_Locks_Resource", ("ResourceType", "ResourceId")),
            ),
            indexes=(SqlIndexDefinition("IX_ostv_Locks_Expiry", ("ExpiresAt",)),),
        ),
        SqlTableDefinition(
            "ostv",
            "EntityVersions",
            (
                _column("ResourceType", "nvarchar(64)"),
                _column("ResourceId", "nvarchar(128)"),
                _column("BidUID", "int", nullable=True),
                _column("ModifiedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("ModifiedBySessionId", "uniqueidentifier", nullable=True),
                _column("Token", "rowversion"),
            ),
            ("ResourceType", "ResourceId"),
            foreign_keys=(
                _foreign_key(
                    "FK_ostv_EntityVersions_Sessions",
                    "ModifiedBySessionId",
                    "Sessions",
                    "SessionId",
                ),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "ChangeLog",
            (
                _column("Sequence", "bigint", identity=True),
                _column("TransactionId", "uniqueidentifier"),
                _column("SessionId", "uniqueidentifier", nullable=True),
                _column("ResourceType", "nvarchar(64)"),
                _column("ResourceId", "nvarchar(128)"),
                _column("BidUID", "int", nullable=True),
                _column("Operation", "nvarchar(32)"),
                _column("ChangedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("Payload", "nvarchar(max)", nullable=True),
            ),
            ("Sequence",),
            foreign_keys=(
                _foreign_key(
                    "FK_ostv_ChangeLog_Sessions",
                    "SessionId",
                    "Sessions",
                    "SessionId",
                ),
            ),
            indexes=(
                SqlIndexDefinition(
                    "IX_ostv_ChangeLog_BidSequence", ("BidUID", "Sequence")
                ),
                SqlIndexDefinition(
                    "IX_ostv_ChangeLog_ResourceSequence",
                    ("ResourceType", "ResourceId", "Sequence"),
                ),
            ),
        ),
    ),
)


def schema_record_is_current(version: object, checksum: object) -> bool:
    try:
        parsed_version = int(version)
    except (TypeError, ValueError):
        return False
    return (
        parsed_version == LATEST_SQL_SCHEMA.version
        and str(checksum) == LATEST_SQL_SCHEMA.checksum
    )


def _render_table(table: SqlTableDefinition) -> str:
    definitions = []
    for column in table.columns:
        identity = " IDENTITY(1,1)" if column.identity else ""
        nullability = " NULL" if column.nullable else " NOT NULL"
        default = f" DEFAULT ({column.default})" if column.default else ""
        definitions.append(
            f"[{column.name}] {column.data_type}{identity}{nullability}{default}"
        )
    primary_columns = ", ".join(f"[{name}]" for name in table.primary_key)
    definitions.append(
        f"CONSTRAINT [PK_{table.schema}_{table.name}] PRIMARY KEY ({primary_columns})"
    )
    for name, columns in table.unique_constraints:
        column_sql = ", ".join(f"[{column}]" for column in columns)
        definitions.append(f"CONSTRAINT [{name}] UNIQUE ({column_sql})")
    for foreign_key in table.foreign_keys:
        columns = ", ".join(f"[{column}]" for column in foreign_key.columns)
        referenced = ", ".join(
            f"[{column}]" for column in foreign_key.referenced_columns
        )
        definitions.append(
            f"CONSTRAINT [{foreign_key.name}] FOREIGN KEY ({columns}) REFERENCES "
            f"[{foreign_key.referenced_schema}].[{foreign_key.referenced_table}] "
            f"({referenced})"
        )
    return (
        f"CREATE TABLE [{table.schema}].[{table.name}] (\n    "
        + ",\n    ".join(definitions)
        + "\n)"
    )


def _render_index(table: SqlTableDefinition, index: SqlIndexDefinition) -> str:
    unique = "UNIQUE " if index.unique else ""
    columns = ", ".join(f"[{column}]" for column in index.columns)
    filter_sql = f" WHERE {index.filter_expression}" if index.filter_expression else ""
    return (
        f"CREATE {unique}INDEX [{index.name}] ON "
        f"[{table.schema}].[{table.name}] ({columns}){filter_sql}"
    )
