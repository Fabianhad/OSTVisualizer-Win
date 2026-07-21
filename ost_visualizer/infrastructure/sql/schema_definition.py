from __future__ import annotations
import hashlib
from dataclasses import dataclass
from ...application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG,
    CollaborationResourceType,
)
from ..database.schema_model import DatabaseSchemaModel, render_sql_server_schema
from ..database.annotation_storage import ANNOTATION_TYPE_BY_TABLE
from ..mdb.database_creator import get_reference_schema_model

SQL_SNAPSHOT_ISOLATION_REQUIREMENT = "ALLOW_SNAPSHOT_ISOLATION=ON"
SQL_CHANGE_TRACKING_RETENTION_DAYS = 7
SQL_CHANGE_TRACKING_AUTO_CLEANUP_REQUIREMENT = "CHANGE_TRACKING_AUTO_CLEANUP=ON"


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
    on_delete: str = ""


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
    check_constraints: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SqlSchemaDefinition:
    version: int
    name: str
    core_schema: DatabaseSchemaModel
    tables: tuple[SqlTableDefinition, ...]
    change_tracking_tables: tuple[tuple[str, str], ...] = ()
    canonical_database_requirements: tuple[str, ...] = ()

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
            statements.append(render_sql_table(table))
            statements.extend(render_sql_index(table, index) for index in table.indexes)
        statements.extend(
            f"ALTER TABLE [{schema}].[{table}] ENABLE CHANGE_TRACKING"
            for schema, table in self.change_tracking_tables
        )
        return tuple(statements)

    @property
    def checksum(self) -> str:
        source_text = "\n-- statement --\n".join(self.statements)
        if self.canonical_database_requirements:
            source_text += "\n-- database requirement --\n" + (
                "\n-- database requirement --\n".join(
                    self.canonical_database_requirements
                )
            )
        source = source_text.encode("utf-8")
        return hashlib.sha256(source).hexdigest()

    @property
    def collaboration_initialization_statements(self) -> tuple[str, ...]:
        return _entity_version_seed_statements() + (
            "INSERT INTO [ostv].[ChangeFeedState] ([SingletonId]) VALUES (1)",
            "INSERT INTO [ostv].[ExternalAdapterState] ([SingletonId]) VALUES (1)",
        )


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
    *,
    on_delete: str = "",
) -> SqlForeignKeyDefinition:
    return SqlForeignKeyDefinition(
        name,
        (column,),
        "ostv",
        referenced_table,
        (referenced_column,),
        on_delete,
    )


SQL_SCHEMA_V1 = SqlSchemaDefinition(
    version=1,
    name="canonical OST Visualizer schema",
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
                _column(
                    "WriterMode",
                    "nvarchar(32)",
                    default="N'ost_visualizer_only'",
                ),
            ),
            ("DatabaseGuid",),
            check_constraints=(
                (
                    "CK_ostv_DatabaseMetadata_WriterMode",
                    "[WriterMode]=N'mixed_application' OR "
                    "[WriterMode]=N'ost_visualizer_only'",
                ),
            ),
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
                _column("DatabaseGuid", "uniqueidentifier"),
                _column("ClientInstanceId", "uniqueidentifier"),
                _column("SqlPrincipal", "nvarchar(256)"),
                _column("DisplayName", "nvarchar(256)"),
                _column("MachineName", "nvarchar(256)"),
                _column("ApplicationVersion", "nvarchar(64)"),
                _column("ConnectedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("LastHeartbeatAt", "datetime2(3)"),
                _column("DisconnectedAt", "datetime2(3)", nullable=True),
                _column("LastAcknowledgedVersion", "bigint", default="0"),
                _column("CloseReason", "nvarchar(64)", nullable=True),
                _column("Version", "rowversion"),
            ),
            ("SessionId",),
            foreign_keys=(
                SqlForeignKeyDefinition(
                    "FK_ostv_Sessions_DatabaseMetadata",
                    ("DatabaseGuid",),
                    "ostv",
                    "DatabaseMetadata",
                    ("DatabaseGuid",),
                ),
            ),
            indexes=(
                SqlIndexDefinition(
                    "IX_ostv_Sessions_Heartbeat",
                    ("LastHeartbeatAt",),
                    filter_expression="[DisconnectedAt] IS NULL",
                ),
                SqlIndexDefinition(
                    "IX_ostv_Sessions_ClientHeartbeat",
                    ("ClientInstanceId", "LastHeartbeatAt"),
                ),
                SqlIndexDefinition(
                    "IX_ostv_Sessions_DatabaseHeartbeat",
                    ("DatabaseGuid", "LastHeartbeatAt"),
                ),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "Presence",
            (
                _column("SessionId", "uniqueidentifier"),
                _column("BidUID", "int", nullable=True),
                _column("CurrentPageUID", "int", nullable=True),
                _column("ActivityMode", "nvarchar(16)", default="N'viewing'"),
                _column("EnteredAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("LastHeartbeatAt", "datetime2(3)"),
                _column("Version", "rowversion"),
            ),
            ("SessionId",),
            foreign_keys=(
                _foreign_key(
                    "FK_ostv_Presence_Sessions",
                    "SessionId",
                    "Sessions",
                    "SessionId",
                ),
            ),
            indexes=(
                SqlIndexDefinition(
                    "IX_ostv_Presence_BidHeartbeat",
                    ("BidUID", "LastHeartbeatAt"),
                    filter_expression="[BidUID] IS NOT NULL",
                ),
            ),
            check_constraints=(
                (
                    "CK_ostv_Presence_ActivityMode",
                    "[ActivityMode]=N'editing' OR [ActivityMode]=N'viewing'",
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
                _column("BidUID", "int", nullable=True),
                _column("OwnerSessionId", "uniqueidentifier"),
                _column("LockToken", "uniqueidentifier"),
                _column("LockMode", "nvarchar(32)", default="N'exclusive'"),
                _column("OperationDescription", "nvarchar(256)", nullable=True),
                _column("AcquiredAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("LastRenewedAt", "datetime2(3)"),
                _column("ExpiresAt", "datetime2(3)"),
                _column("Version", "rowversion"),
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
                ("UQ_ostv_Locks_Token", ("LockToken",)),
            ),
            indexes=(
                SqlIndexDefinition("IX_ostv_Locks_Expiry", ("ExpiresAt",)),
                SqlIndexDefinition(
                    "IX_ostv_Locks_OwnerExpiry",
                    ("OwnerSessionId", "ExpiresAt"),
                ),
                SqlIndexDefinition(
                    "IX_ostv_Locks_BidExpiry",
                    ("BidUID", "ExpiresAt"),
                    filter_expression="[BidUID] IS NOT NULL",
                ),
            ),
            check_constraints=(
                ("CK_ostv_Locks_Mode", "[LockMode] = N'exclusive'"),
                ("CK_ostv_Locks_Expiry", "[ExpiresAt] > [AcquiredAt]"),
            ),
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
                _column("IsDeleted", "bit", default="0"),
                _column("Token", "rowversion"),
            ),
            ("ResourceType", "ResourceId"),
            foreign_keys=(
                _foreign_key(
                    "FK_ostv_EntityVersions_Sessions",
                    "ModifiedBySessionId",
                    "Sessions",
                    "SessionId",
                    on_delete="SET NULL",
                ),
            ),
            indexes=(
                SqlIndexDefinition(
                    "IX_ostv_EntityVersions_BidType",
                    ("BidUID", "ResourceType"),
                ),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "ChangeLog",
            (
                _column("Sequence", "bigint", identity=True),
                _column("TransactionId", "uniqueidentifier"),
                _column("SourceSessionId", "uniqueidentifier", nullable=True),
                _column("DatabaseGuid", "uniqueidentifier"),
                _column("ResourceType", "nvarchar(64)"),
                _column("ResourceId", "nvarchar(128)"),
                _column("BidUID", "int", nullable=True),
                _column("Operation", "nvarchar(32)"),
                _column("ResultVersion", "varbinary(8)", nullable=True),
                _column("ChangedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("ChangedFields", "nvarchar(1024)", nullable=True),
                _column("Payload", "nvarchar(4000)", nullable=True),
                _column(
                    "SourceKind",
                    "nvarchar(32)",
                    default="N'ost_visualizer'",
                ),
                _column("ExternalTransactionKey", "nvarchar(128)", nullable=True),
            ),
            ("Sequence",),
            foreign_keys=(
                _foreign_key(
                    "FK_ostv_ChangeLog_Sessions",
                    "SourceSessionId",
                    "Sessions",
                    "SessionId",
                    on_delete="SET NULL",
                ),
                SqlForeignKeyDefinition(
                    "FK_ostv_ChangeLog_DatabaseMetadata",
                    ("DatabaseGuid",),
                    "ostv",
                    "DatabaseMetadata",
                    ("DatabaseGuid",),
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
                SqlIndexDefinition(
                    "IX_ostv_ChangeLog_SourceSequence",
                    ("SourceSessionId", "Sequence"),
                ),
                SqlIndexDefinition(
                    "IX_ostv_ChangeLog_TransactionSequence",
                    ("TransactionId", "Sequence"),
                ),
                SqlIndexDefinition(
                    "IX_ostv_ChangeLog_SourceKindSequence",
                    ("SourceKind", "Sequence"),
                ),
            ),
            check_constraints=(
                (
                    "CK_ostv_ChangeLog_Operation",
                    "[Operation]=N'bulk_refresh' OR [Operation]=N'reorder' OR "
                    "[Operation]=N'move' OR [Operation]=N'delete' OR "
                    "[Operation]=N'update' OR [Operation]=N'create'",
                ),
                (
                    "CK_ostv_ChangeLog_ChangedFieldsJson",
                    "[ChangedFields] IS NULL OR ISJSON([ChangedFields])=(1)",
                ),
                (
                    "CK_ostv_ChangeLog_PayloadJson",
                    "[Payload] IS NULL OR ISJSON([Payload])=(1)",
                ),
                (
                    "CK_ostv_ChangeLog_SourceKind",
                    "[SourceKind]=N'external' OR [SourceKind]=N'ost_visualizer'",
                ),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "ChangeFeedState",
            (
                _column("SingletonId", "tinyint"),
                _column("FeedEpoch", "uniqueidentifier", default="NEWID()"),
            ),
            ("SingletonId",),
            check_constraints=(
                ("CK_ostv_ChangeFeedState_Singleton", "[SingletonId]=(1)"),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "ExternalAdapterState",
            (
                _column("SingletonId", "tinyint"),
                _column("AdapterType", "nvarchar(32)", default="N'none'"),
                _column("AdapterVersion", "nvarchar(64)", nullable=True),
                _column("AdapterState", "nvarchar(32)", default="N'disabled'"),
                _column("AdapterEpoch", "uniqueidentifier", default="NEWID()"),
                _column("ResourceCatalogChecksum", "char(64)", nullable=True),
                _column("ValidatedAt", "datetime2(3)", nullable=True),
                _column("LastCheckedAt", "datetime2(3)", nullable=True),
                _column("FailureCode", "nvarchar(128)", nullable=True),
                _column("Version", "rowversion"),
            ),
            ("SingletonId",),
            check_constraints=(
                (
                    "CK_ostv_ExternalAdapterState_Singleton",
                    "[SingletonId]=(1)",
                ),
                (
                    "CK_ostv_ExternalAdapterState_State",
                    "[AdapterState]=N'invalid' OR "
                    "[AdapterState]=N'validated' OR "
                    "[AdapterState]=N'validating' OR "
                    "[AdapterState]=N'disabled'",
                ),
            ),
        ),
        SqlTableDefinition(
            "ostv",
            "ChangeTransactions",
            (
                _column("TransactionId", "uniqueidentifier"),
                _column("SourceSessionId", "uniqueidentifier", nullable=True),
                _column("DatabaseGuid", "uniqueidentifier"),
                _column("CommittedAt", "datetime2(3)", default="SYSUTCDATETIME()"),
                _column("ResourceFamilySummary", "nvarchar(1024)", nullable=True),
            ),
            ("TransactionId",),
            foreign_keys=(
                SqlForeignKeyDefinition(
                    "FK_ostv_ChangeTransactions_DatabaseMetadata",
                    ("DatabaseGuid",),
                    "ostv",
                    "DatabaseMetadata",
                    ("DatabaseGuid",),
                ),
            ),
            indexes=(
                SqlIndexDefinition(
                    "IX_ostv_ChangeTransactions_SourceCommitted",
                    ("SourceSessionId", "CommittedAt"),
                ),
                SqlIndexDefinition(
                    "IX_ostv_ChangeTransactions_CommittedAt",
                    ("CommittedAt",),
                ),
            ),
        ),
    ),
    change_tracking_tables=(("ostv", "ChangeTransactions"),),
    canonical_database_requirements=(
        SQL_SNAPSHOT_ISOLATION_REQUIREMENT,
        f"CHANGE_TRACKING_RETENTION={SQL_CHANGE_TRACKING_RETENTION_DAYS} DAYS",
        SQL_CHANGE_TRACKING_AUTO_CLEANUP_REQUIREMENT,
    ),
)


def schema_record_is_canonical(version: object, checksum: object) -> bool:
    if type(version) is not int or not isinstance(checksum, str):
        return False
    return version == SQL_SCHEMA_V1.version and checksum == SQL_SCHEMA_V1.checksum


def _entity_version_seed_statements() -> tuple[str, ...]:
    statements = [
        _seed_entity_version(
            definition.resource_type.value,
            definition.entity_table,
            definition.entity_uid_column,
            definition.entity_bid_column,
            definition.seed_filter,
        )
        for definition in COLLABORATION_RESOURCE_CATALOG.values()
        if definition.entity_table
    ]
    static_collections = (
        CollaborationResourceType.PROJECTS_COLLECTION,
        CollaborationResourceType.JOB_STATUSES_COLLECTION,
        CollaborationResourceType.EMPLOYEES_COLLECTION,
        CollaborationResourceType.PAY_CLASSES_COLLECTION,
        CollaborationResourceType.CONDITION_TYPES_COLLECTION,
        CollaborationResourceType.DEFAULT_LAYERS_COLLECTION,
    )
    statements.extend(
        _seed_static_collection(resource_type.value, "database")
        for resource_type in static_collections
    )
    statements.append(
        _seed_static_collection(CollaborationResourceType.PROJECT_BIDS.value, "orphan")
    )
    statements.extend(
        _seed_annotation(table, annotation_type)
        for table, annotation_type in ANNOTATION_TYPE_BY_TABLE.items()
    )
    statements.extend(
        (
            *(
                _seed_bid_collection(definition.resource_type.value)
                for definition in COLLABORATION_RESOURCE_CATALOG.values()
                if definition.collection and definition.bid_scoped
            ),
            "INSERT INTO [ostv].[EntityVersions] "
            "([ResourceType], [ResourceId], [BidUID]) "
            "SELECT N'project_bids', CONVERT(nvarchar(128), [UID]), NULL "
            "FROM [dbo].[BidProjects]",
        )
    )
    return tuple(statements)


def _seed_entity_version(
    resource_type: str,
    table: str,
    uid_column: str,
    bid_column: str = "",
    where: str = "",
) -> str:
    bid_sql = f"CONVERT(int, [{bid_column}])" if bid_column else "NULL"
    where_sql = f" WHERE {where}" if where else ""
    return (
        "INSERT INTO [ostv].[EntityVersions] "
        "([ResourceType], [ResourceId], [BidUID]) "
        f"SELECT N'{resource_type}', CONVERT(nvarchar(128), [{uid_column}]), "
        f"{bid_sql} FROM [dbo].[{table}]{where_sql}"
    )


def _seed_annotation(table: str, annotation_type: str) -> str:
    return (
        "INSERT INTO [ostv].[EntityVersions] "
        "([ResourceType], [ResourceId], [BidUID]) "
        f"SELECT N'annotation', N'{annotation_type}/' + "
        "CONVERT(nvarchar(100), [UID]), "
        f"CONVERT(int, [BidUID]) FROM [dbo].[{table}]"
    )


def _seed_static_collection(resource_type: str, resource_id: str) -> str:
    return (
        "INSERT INTO [ostv].[EntityVersions] "
        "([ResourceType], [ResourceId], [BidUID]) VALUES "
        f"(N'{resource_type}', N'{resource_id}', NULL)"
    )


def _seed_bid_collection(resource_type: str) -> str:
    return (
        "INSERT INTO [ostv].[EntityVersions] "
        "([ResourceType], [ResourceId], [BidUID]) "
        f"SELECT N'{resource_type}', CONVERT(nvarchar(128), [UID]), "
        "CONVERT(int, [UID]) FROM [dbo].[Bids]"
    )


def render_sql_table(table: SqlTableDefinition) -> str:
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
        on_delete = (
            f" ON DELETE {foreign_key.on_delete}" if foreign_key.on_delete else ""
        )
        definitions.append(
            f"CONSTRAINT [{foreign_key.name}] FOREIGN KEY ({columns}) REFERENCES "
            f"[{foreign_key.referenced_schema}].[{foreign_key.referenced_table}] "
            f"({referenced}){on_delete}"
        )
    for name, expression in table.check_constraints:
        definitions.append(f"CONSTRAINT [{name}] CHECK ({expression})")
    return (
        f"CREATE TABLE [{table.schema}].[{table.name}] (\n    "
        + ",\n    ".join(definitions)
        + "\n)"
    )


def render_sql_index(table: SqlTableDefinition, index: SqlIndexDefinition) -> str:
    unique = "UNIQUE " if index.unique else ""
    columns = ", ".join(f"[{column}]" for column in index.columns)
    filter_sql = f" WHERE {index.filter_expression}" if index.filter_expression else ""
    return (
        f"CREATE {unique}INDEX [{index.name}] ON "
        f"[{table.schema}].[{table.name}] ({columns}){filter_sql}"
    )
