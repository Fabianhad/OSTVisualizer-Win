from __future__ import annotations
import getpass
from dataclasses import replace
from typing import Optional
import pyodbc
from ...domain.entities.database_descriptor import (
    SqlServerDatabaseLocation,
    validate_sql_database_name,
)
from ...application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
)
from ..mdb.database_creator import (
    get_reference_seed_data,
)
from .connection_manager import SqlConnectionManager, SqlConnectionRequest
from .client_permissions import apply_sql_client_permissions
from .errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
    classify_pyodbc_error,
)
from .schema_definition import (
    SQL_SCHEMA_V1,
    SQL_CHANGE_TRACKING_RETENTION_DAYS,
)
from .schema_inspector import SqlSchemaInspector
from .schema_validator import SqlSchemaValidator
from .schema_lock import SQL_SCHEMA_LOCK_RESOURCE, acquire_schema_transaction_lock


class SqlDatabaseCreator:
    def __init__(
        self,
        connection_manager: Optional[SqlConnectionManager] = None,
    ) -> None:
        self._schema_model = SQL_SCHEMA_V1.core_schema
        self._schema_versions, self._default_layers = get_reference_seed_data()
        self._connections = connection_manager or SqlConnectionManager()
        self._inspector = SqlSchemaInspector(self._connections)
        self._validator = SqlSchemaValidator(self._schema_model)

    def can_create_database(
        self, location: SqlServerDatabaseLocation, password: str = ""
    ) -> bool:
        request = SqlConnectionRequest(
            location=location,
            password=password,
            database_override="master",
        )
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT CASE WHEN IS_SRVROLEMEMBER(N'dbcreator')=1 "
                    "OR IS_SRVROLEMEMBER(N'sysadmin')=1 "
                    "OR HAS_PERMS_BY_NAME(NULL, NULL, N'CREATE ANY DATABASE')=1 "
                    "THEN 1 ELSE 0 END"
                )
                return bool(cursor.fetchone()[0])

    def create_database(
        self,
        location: SqlServerDatabaseLocation,
        database_name: str,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
    ) -> SqlDatabaseCreationResult:
        validate_sql_database_name(database_name)
        master_request = SqlConnectionRequest(
            location=location,
            password=password,
            database_override="master",
        )
        with self._connections.connection(master_request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT CASE WHEN DB_ID(?) IS NULL THEN 0 ELSE 1 END",
                    database_name,
                )
                if bool(cursor.fetchone()[0]):
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.SCHEMA_MISMATCH,
                            "A database with that name already exists.",
                        )
                    )
                cursor.execute(f"CREATE DATABASE {_quote_identifier(database_name)}")
        target = replace(location, database=database_name)
        try:
            return self.initialize_blank_database(
                target,
                password,
                application_version=application_version,
                actor=actor,
            )
        except (SqlInfrastructureError, OSError, ValueError):
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.SCHEMA_MISMATCH,
                    "The database container was created, but initialization failed. "
                    "No automatic drop was attempted; an administrator should inspect "
                    f"'{database_name}' before removing it.",
                )
            ) from None

    def initialize_blank_database(
        self,
        location: SqlServerDatabaseLocation,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
    ) -> SqlDatabaseCreationResult:
        if not location.database:
            raise ValueError("A target SQL Server database is required")
        self._validate_blank_candidate(location, password)
        self._ensure_snapshot_isolation(location, password)
        enabled_change_tracking = self._ensure_database_change_tracking(
            location, password
        )
        request = SqlConnectionRequest(location=location, password=password)
        actor_name = actor.strip() or location.username.strip() or getpass.getuser()
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    acquire_schema_transaction_lock(cursor)
                    cursor.execute(
                        "SELECT COUNT(*) FROM sys.tables t "
                        "JOIN sys.schemas s ON s.schema_id=t.schema_id "
                        "WHERE s.name IN (N'dbo', N'ostv')"
                    )
                    if int(cursor.fetchone()[0]) != 0:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.SCHEMA_MISMATCH,
                                "The selected database is not blank. Select an empty "
                                "database or create a new one.",
                            )
                        )
                    for statement in SQL_SCHEMA_V1.statements:
                        cursor.execute(statement)
                    self._insert_seed_data(cursor, location.database)
                    self._initialize_collaboration_state(cursor)
                    self._record_schema(
                        cursor,
                        application_version=application_version,
                        actor=actor_name,
                    )
                    apply_sql_client_permissions(cursor, location.username)
                inventory = self._inspector.inspect_connection(lease)
                report = self._validator.validate(inventory)
                if not report.is_valid:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.SCHEMA_MISMATCH,
                            "SQL database initialization validation failed: "
                            + report.user_message,
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
                    if enabled_change_tracking:
                        self._disable_database_change_tracking(location, password)
        final_location = replace(location, database_guid=inventory.database_guid)
        return SqlDatabaseCreationResult(final_location, SQL_SCHEMA_V1.version)

    def _ensure_database_change_tracking(
        self, location: SqlServerDatabaseLocation, password: str
    ) -> bool:
        request = SqlConnectionRequest(location=location, password=password)
        try:
            with self._connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT [retention_period], [retention_period_units_desc], "
                        "[is_auto_cleanup_on] FROM sys.change_tracking_databases "
                        "WHERE [database_id]=DB_ID()"
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "ALTER DATABASE CURRENT SET CHANGE_TRACKING = ON "
                            "(CHANGE_RETENTION = "
                            f"{SQL_CHANGE_TRACKING_RETENTION_DAYS} DAYS, "
                            "AUTO_CLEANUP = ON)"
                        )
                        return True
                    if (
                        int(row[0]) != SQL_CHANGE_TRACKING_RETENTION_DAYS
                        or str(row[1]).casefold() != "days"
                        or not bool(row[2])
                    ):
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.SCHEMA_MISMATCH,
                                "SQL Server Change Tracking must use seven-day "
                                "retention with automatic cleanup enabled.",
                            )
                        )
        except pyodbc.Error as exc:
            raise SqlInfrastructureError(classify_pyodbc_error(exc)) from None
        return False

    def _ensure_snapshot_isolation(
        self, location: SqlServerDatabaseLocation, password: str
    ) -> None:
        request = SqlConnectionRequest(location=location, password=password)
        try:
            with self._connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT [snapshot_isolation_state] FROM sys.databases "
                        "WHERE [database_id]=DB_ID()"
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.CONNECTION_FAILED,
                                "The exact SQL database target could not be resolved.",
                            )
                        )
                    if int(row[0]) != 1:
                        cursor.execute(
                            "ALTER DATABASE CURRENT SET ALLOW_SNAPSHOT_ISOLATION ON"
                        )
                        cursor.execute(
                            "SELECT [snapshot_isolation_state] FROM sys.databases "
                            "WHERE [database_id]=DB_ID()"
                        )
                        verified = cursor.fetchone()
                        if verified is None or int(verified[0]) != 1:
                            raise SqlInfrastructureError(
                                SqlErrorDetails(
                                    SqlErrorCode.SCHEMA_MISMATCH,
                                    "SQL Server snapshot isolation could not be enabled.",
                                )
                            )
        except pyodbc.Error as exc:
            raise SqlInfrastructureError(classify_pyodbc_error(exc)) from None

    def _disable_database_change_tracking(
        self, location: SqlServerDatabaseLocation, password: str
    ) -> None:
        request = SqlConnectionRequest(location=location, password=password)
        try:
            with self._connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "DECLARE @result int; "
                        "EXEC @result=sys.sp_getapplock @Resource=?, "
                        "@LockMode=N'Exclusive', @LockOwner=N'Session', "
                        "@LockTimeout=10000; "
                        "IF @result < 0 THROW 51000, "
                        "'Could not verify Change Tracking ownership.', 1; "
                        "BEGIN TRY "
                        "IF NOT EXISTS (SELECT 1 FROM sys.tables t "
                        "JOIN sys.schemas s ON s.[schema_id]=t.[schema_id] "
                        "WHERE s.[name]=N'ostv') "
                        "ALTER DATABASE CURRENT SET CHANGE_TRACKING = OFF; "
                        "EXEC sys.sp_releaseapplock @Resource=?, "
                        "@LockOwner=N'Session'; "
                        "END TRY BEGIN CATCH "
                        "EXEC sys.sp_releaseapplock @Resource=?, "
                        "@LockOwner=N'Session'; THROW; END CATCH",
                        SQL_SCHEMA_LOCK_RESOURCE,
                        SQL_SCHEMA_LOCK_RESOURCE,
                        SQL_SCHEMA_LOCK_RESOURCE,
                    )
        except pyodbc.Error as exc:
            raise SqlInfrastructureError(classify_pyodbc_error(exc)) from None

    def _validate_blank_candidate(
        self, location: SqlServerDatabaseLocation, password: str
    ) -> None:
        request = SqlConnectionRequest(
            location=location,
            password=password,
            read_only=True,
        )
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM sys.tables t JOIN sys.schemas s "
                    "ON s.schema_id=t.schema_id WHERE s.name IN (N'dbo', N'ostv')"
                )
                if int(cursor.fetchone()[0]) != 0:
                    raise SqlInfrastructureError(
                        SqlErrorDetails(
                            SqlErrorCode.SCHEMA_MISMATCH,
                            "The selected database is not blank. Select an empty "
                            "database or create a new one.",
                        )
                    )

    @staticmethod
    def _record_schema(cursor, *, application_version: str, actor: str) -> None:
        cursor.execute(
            "SELECT CONVERT(uniqueidentifier, database_guid) "
            "FROM sys.database_recovery_status WHERE database_id=DB_ID()"
        )
        database_guid = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO [ostv].[DatabaseMetadata] "
            "([DatabaseGuid], [Product], [SchemaVersion], [CreatedBy], "
            "[LastMigratedAt], [LastMigratedBy]) "
            "VALUES (?, N'OST Visualizer', ?, ?, SYSUTCDATETIME(), ?)",
            database_guid,
            SQL_SCHEMA_V1.version,
            actor,
            actor,
        )
        cursor.execute(
            "INSERT INTO [ostv].[SchemaMigrations] "
            "([Version], [Name], [Checksum], [AppliedBy], [ApplicationVersion]) "
            "VALUES (?, ?, ?, ?, ?)",
            SQL_SCHEMA_V1.version,
            SQL_SCHEMA_V1.name,
            SQL_SCHEMA_V1.checksum,
            actor,
            application_version,
        )

    @staticmethod
    def _initialize_collaboration_state(cursor) -> None:
        for statement in SQL_SCHEMA_V1.collaboration_initialization_statements:
            cursor.execute(statement)

    def _insert_seed_data(self, cursor, database_name: str) -> None:
        cursor.execute(
            "INSERT INTO [Settings] ([Name], [Created], [NextBidNo], "
            "[LoginRequired], [MeasureBase], [PriceUsing], "
            "[QuantitiesInLegend], [HoursPerDay], [StartWeekOn], "
            "[GridCountMethod], [TakeoffIncrements], [ScaleStyle], "
            "[IsCustomScale], [ScaleFactor1], [ScaleFactor2], "
            "[PageScale], [PageWidth], [PageHeight], "
            "[LabelHours1], [LabelHours2], [LabelHours3], [LabelHours4], "
            "[IgnoreBidAreas], [SendImageFiles], [BackupNo], [BackupPeriod], "
            "[CompressPeriod]) VALUES (?, SYSUTCDATETIME(), 1, 0, 0, 0, 1, "
            "8, 0, 0, 1.0, 1, 0, 0.125, 12.0, 1.0, 42.0, 30.0, "
            "N'Regular', N'Overtime', N'Time + 1/2', N'Double', 0, 0, 2, 2, 2)",
            database_name,
        )
        cursor.execute("INSERT INTO [BidProjects] ([Name]) VALUES (N'Deleted Bids')")
        for layer_name, show, locked, sequence in self._default_layers:
            cursor.execute(
                "INSERT INTO [BidLayers] "
                "([IsTemplate], [Name], [Show], [IsLocked], [Sequence]) "
                "VALUES (1, ?, ?, ?, ?)",
                layer_name,
                bool(show),
                bool(locked),
                sequence,
            )
        for version in self._schema_versions:
            cursor.execute(
                "INSERT INTO [SchemaRegistry] ([Version], [Product]) VALUES (?, 2)",
                version,
            )


def _quote_identifier(value: str) -> str:
    return "[" + value.replace("]", "]]") + "]"
