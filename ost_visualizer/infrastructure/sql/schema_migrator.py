from __future__ import annotations
import getpass
import hashlib
from dataclasses import dataclass, replace
import pyodbc
from ...application.interfaces.i_sql_database_creator import SqlDatabaseCreationResult
from ...domain.entities.database_descriptor import SqlServerDatabaseLocation
from .connection_manager import SqlConnectionManager, SqlConnectionRequest
from .errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
    classify_pyodbc_error,
)
from .schema_definition import (
    LATEST_SQL_SCHEMA,
    SQL_SCHEMA_V3,
    SqlSchemaDefinition,
    render_sql_index,
    render_sql_table,
)
from .schema_inspector import SqlSchemaInspector
from .schema_lock import acquire_schema_transaction_lock
from .schema_validator import SqlSchemaCompatibility, SqlSchemaValidator


@dataclass(frozen=True)
class SqlSchemaMigration:
    source_version: int
    target_version: int
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = "\n-- migration statement --\n".join(self.statements)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _version_2_schema_snapshot() -> SqlSchemaDefinition:
    tables = []
    for table in SQL_SCHEMA_V3.tables:
        if table.name == "ExternalAdapterState":
            continue
        if table.name == "DatabaseMetadata":
            table = replace(
                table,
                columns=tuple(
                    column for column in table.columns if column.name != "WriterMode"
                ),
                check_constraints=tuple(
                    constraint
                    for constraint in table.check_constraints
                    if constraint[0] != "CK_ostv_DatabaseMetadata_WriterMode"
                ),
            )
        elif table.name == "ChangeLog":
            table = replace(
                table,
                columns=tuple(
                    column
                    for column in table.columns
                    if column.name not in {"SourceKind", "ExternalTransactionKey"}
                ),
                indexes=tuple(
                    index
                    for index in table.indexes
                    if index.name != "IX_ostv_ChangeLog_SourceKindSequence"
                ),
                check_constraints=tuple(
                    constraint
                    for constraint in table.check_constraints
                    if constraint[0] != "CK_ostv_ChangeLog_SourceKind"
                ),
            )
        tables.append(table)
    return SqlSchemaDefinition(
        version=2,
        migration_name="multi-user collaboration schema",
        core_schema=SQL_SCHEMA_V3.core_schema,
        tables=tuple(tables),
    )


SQL_SCHEMA_V2 = _version_2_schema_snapshot()


def _version_2_to_3_statements() -> tuple[str, ...]:
    adapter_state = next(
        table for table in SQL_SCHEMA_V3.tables if table.name == "ExternalAdapterState"
    )
    return (
        "ALTER TABLE [ostv].[DatabaseMetadata] ADD [WriterMode] nvarchar(32) "
        "NOT NULL CONSTRAINT [DF_ostv_DatabaseMetadata_WriterMode] "
        "DEFAULT (N'ost_visualizer_only') WITH VALUES",
        "ALTER TABLE [ostv].[DatabaseMetadata] ADD CONSTRAINT "
        "[CK_ostv_DatabaseMetadata_WriterMode] CHECK "
        "([WriterMode]=N'mixed_application' OR "
        "[WriterMode]=N'ost_visualizer_only')",
        "ALTER TABLE [ostv].[ChangeLog] ADD [SourceKind] nvarchar(32) NOT NULL "
        "CONSTRAINT [DF_ostv_ChangeLog_SourceKind] "
        "DEFAULT (N'ost_visualizer') WITH VALUES, "
        "[ExternalTransactionKey] nvarchar(128) NULL",
        "ALTER TABLE [ostv].[ChangeLog] ADD CONSTRAINT "
        "[CK_ostv_ChangeLog_SourceKind] CHECK "
        "([SourceKind]=N'external' OR [SourceKind]=N'ost_visualizer')",
        "CREATE INDEX [IX_ostv_ChangeLog_SourceKindSequence] ON "
        "[ostv].[ChangeLog] ([SourceKind], [Sequence])",
        render_sql_table(adapter_state),
        *(render_sql_index(adapter_state, index) for index in adapter_state.indexes),
        "INSERT INTO [ostv].[ExternalAdapterState] ([SingletonId]) VALUES (1)",
    )


SQL_SCHEMA_V2_TO_V3 = SqlSchemaMigration(
    source_version=SQL_SCHEMA_V2.version,
    target_version=SQL_SCHEMA_V3.version,
    statements=_version_2_to_3_statements(),
)


def _version_3_to_4_statements() -> tuple[str, ...]:
    transaction_table = next(
        table
        for table in LATEST_SQL_SCHEMA.tables
        if table.name == "ChangeTransactions"
    )
    return (
        render_sql_table(transaction_table),
        *(
            render_sql_index(transaction_table, index)
            for index in transaction_table.indexes
        ),
        "ALTER TABLE [ostv].[ChangeTransactions] ENABLE CHANGE_TRACKING",
        "ALTER TABLE [ostv].[Sessions] ADD [LastAcknowledgedVersion] bigint "
        "NOT NULL CONSTRAINT [DF_ostv_Sessions_LastAcknowledgedVersion] "
        "DEFAULT (0) WITH VALUES",
        "UPDATE [ostv].[Sessions] SET [LastAcknowledgedVersion]="
        "CHANGE_TRACKING_CURRENT_VERSION()",
        "DECLARE @SessionsDefault sysname=(SELECT dc.[name] FROM "
        "sys.default_constraints dc JOIN sys.columns c ON "
        "c.[object_id]=dc.[parent_object_id] AND "
        "c.[column_id]=dc.[parent_column_id] WHERE "
        "dc.[parent_object_id]=OBJECT_ID(N'ostv.Sessions') AND "
        "c.[name]=N'LastAcknowledgedSequence'); "
        "IF @SessionsDefault IS NOT NULL BEGIN "
        "DECLARE @SessionsSql nvarchar(max)=N'ALTER TABLE [ostv].[Sessions] "
        "DROP CONSTRAINT ' + QUOTENAME(@SessionsDefault); "
        "EXEC sys.sp_executesql @SessionsSql; END; "
        "ALTER TABLE [ostv].[Sessions] DROP COLUMN [LastAcknowledgedSequence]",
        "DECLARE @FeedDefault sysname=(SELECT dc.[name] FROM "
        "sys.default_constraints dc JOIN sys.columns c ON "
        "c.[object_id]=dc.[parent_object_id] AND "
        "c.[column_id]=dc.[parent_column_id] WHERE "
        "dc.[parent_object_id]=OBJECT_ID(N'ostv.ChangeFeedState') AND "
        "c.[name]=N'OldestAvailableSequence'); "
        "IF @FeedDefault IS NOT NULL BEGIN "
        "DECLARE @FeedSql nvarchar(max)=N'ALTER TABLE "
        "[ostv].[ChangeFeedState] DROP CONSTRAINT ' + "
        "QUOTENAME(@FeedDefault); EXEC sys.sp_executesql @FeedSql; END; "
        "ALTER TABLE [ostv].[ChangeFeedState] DROP COLUMN "
        "[OldestAvailableSequence]",
        "ALTER TABLE [ostv].[ChangeFeedState] DROP COLUMN [LastPrunedAt]",
    )


SQL_SCHEMA_V3_TO_V4 = SqlSchemaMigration(
    source_version=SQL_SCHEMA_V3.version,
    target_version=LATEST_SQL_SCHEMA.version,
    statements=_version_3_to_4_statements(),
)


class SqlSchemaMigrator:
    def __init__(self, connection_manager: SqlConnectionManager) -> None:
        self._connections = connection_manager
        self._inspector = SqlSchemaInspector(connection_manager)
        self._validator = SqlSchemaValidator(LATEST_SQL_SCHEMA.core_schema)

    def migrate_version_2_to_3(
        self,
        location: SqlServerDatabaseLocation,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
    ) -> SqlDatabaseCreationResult:
        return self._migrate(
            location,
            password,
            application_version=application_version,
            actor=actor,
            source_schema=SQL_SCHEMA_V2,
            target_schema=SQL_SCHEMA_V3,
            migration=SQL_SCHEMA_V2_TO_V3,
        )

    def migrate_version_3_to_4(
        self,
        location: SqlServerDatabaseLocation,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
    ) -> SqlDatabaseCreationResult:
        return self._migrate(
            location,
            password,
            application_version=application_version,
            actor=actor,
            source_schema=SQL_SCHEMA_V3,
            target_schema=LATEST_SQL_SCHEMA,
            migration=SQL_SCHEMA_V3_TO_V4,
        )

    def _migrate(
        self,
        location: SqlServerDatabaseLocation,
        password: str,
        *,
        application_version: str,
        actor: str,
        source_schema: SqlSchemaDefinition,
        target_schema: SqlSchemaDefinition,
        migration: SqlSchemaMigration,
    ) -> SqlDatabaseCreationResult:
        if not location.database:
            raise ValueError("A target SQL Server database is required")
        actor_name = actor.strip() or location.username.strip() or getpass.getuser()
        request = SqlConnectionRequest(location=location, password=password)
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    acquire_schema_transaction_lock(cursor)
                before = self._inspector.inspect_connection(lease)
                source_report = self._validator.validate_versioned_schema(
                    before, source_schema
                )
                if source_report.compatibility != SqlSchemaCompatibility.CURRENT:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.UNSUPPORTED_SCHEMA,
                            "Only an exact OST Visualizer schema version "
                            f"{source_schema.version} database can be upgraded by "
                            "this migration.",
                        )
                    )
                if (
                    target_schema.change_tracking_tables
                    and not before.change_tracking_enabled
                ):
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.UNSUPPORTED_SCHEMA,
                            "Enable SQL Server Change Tracking on the database before "
                            "running the version 3 to 4 schema migration.",
                        )
                    )
                with lease.cursor() as cursor:
                    for statement in migration.statements:
                        cursor.execute(statement)
                    cursor.execute(
                        "INSERT INTO [ostv].[SchemaMigrations] "
                        "([Version], [Name], [Checksum], [AppliedBy], "
                        "[ApplicationVersion]) VALUES (?, ?, ?, ?, ?)",
                        target_schema.version,
                        target_schema.migration_name,
                        target_schema.checksum,
                        actor_name,
                        application_version,
                    )
                    cursor.execute(
                        "UPDATE [ostv].[DatabaseMetadata] SET [SchemaVersion]=?, "
                        "[LastMigratedAt]=SYSUTCDATETIME(), [LastMigratedBy]=? "
                        "WHERE [Product]=N'OST Visualizer' AND [SchemaVersion]=?",
                        target_schema.version,
                        actor_name,
                        source_schema.version,
                    )
                    if cursor.rowcount != 1:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.CONFLICT,
                                "The SQL schema changed while the upgrade was running.",
                            )
                        )
                after = self._inspector.inspect_connection(lease)
                final_report = self._validator.validate_versioned_schema(
                    after, target_schema
                )
                if final_report.compatibility != SqlSchemaCompatibility.CURRENT:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.SCHEMA_MISMATCH,
                            "SQL schema upgrade validation failed: "
                            + final_report.user_message,
                        )
                    )
                lease.commit()
                committed = True
            except pyodbc.Error as exc:
                raise SqlInfrastructureError(classify_pyodbc_error(exc)) from None
            finally:
                if not committed:
                    try:
                        lease.rollback()
                    except pyodbc.Error:
                        pass
        final_location = replace(location, database_guid=after.database_guid)
        return SqlDatabaseCreationResult(final_location, target_schema.version)
