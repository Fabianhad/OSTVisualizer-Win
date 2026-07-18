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
from .errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
    classify_pyodbc_error,
)
from .schema_definition import LATEST_SQL_SCHEMA
from .schema_inspector import SqlSchemaInspector
from .schema_validator import SqlSchemaCompatibility, SqlSchemaValidator


class SqlDatabaseCreator:
    def __init__(
        self,
        connection_manager: Optional[SqlConnectionManager] = None,
    ) -> None:
        self._schema_model = LATEST_SQL_SCHEMA.core_schema
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
        request = SqlConnectionRequest(location=location, password=password)
        actor_name = actor.strip() or location.username.strip() or getpass.getuser()
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    self._acquire_schema_lock(cursor)
                    cursor.execute(
                        "SELECT COUNT(*) FROM sys.tables t "
                        "JOIN sys.schemas s ON s.schema_id=t.schema_id "
                        "WHERE s.name IN (N'dbo', N'ostv')"
                    )
                    if int(cursor.fetchone()[0]) != 0:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.SCHEMA_MISMATCH,
                                "The selected database is not blank. Use Connect for a "
                                "compatible database or select an empty database.",
                            )
                        )
                    for statement in LATEST_SQL_SCHEMA.statements:
                        cursor.execute(statement)
                    self._insert_seed_data(cursor, location.database)
                    self._record_schema(
                        cursor,
                        application_version=application_version,
                        actor=actor_name,
                    )
                inventory = self._inspector.inspect_connection(lease)
                report = self._validator.validate(inventory)
                if report.compatibility != SqlSchemaCompatibility.CURRENT:
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
        final_location = replace(location, database_guid=inventory.database_guid)
        return SqlDatabaseCreationResult(final_location, LATEST_SQL_SCHEMA.version)

    def initialize_compatible_database(
        self,
        location: SqlServerDatabaseLocation,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
    ) -> SqlDatabaseCreationResult:
        if not location.database:
            raise ValueError("A target SQL Server database is required")
        request = SqlConnectionRequest(location=location, password=password)
        actor_name = actor.strip() or location.username.strip() or getpass.getuser()
        with self._connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    self._acquire_schema_lock(cursor)
                inventory = self._inspector.inspect_connection(lease)
                if inventory.schema_version == LATEST_SQL_SCHEMA.version:
                    report = self._validator.validate(inventory)
                    if report.compatibility != SqlSchemaCompatibility.CURRENT:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.SCHEMA_MISMATCH,
                                "The external database cannot be enabled for editing: "
                                + report.user_message,
                            )
                        )
                    initialized = inventory
                else:
                    candidate = self._validator.validate_adoption_candidate(inventory)
                    if (
                        candidate.compatibility
                        != SqlSchemaCompatibility.UNVERSIONED_READ_ONLY
                    ):
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.SCHEMA_MISMATCH,
                                "The external database cannot be enabled for editing: "
                                + candidate.user_message,
                            )
                        )
                    with lease.cursor() as cursor:
                        for statement in LATEST_SQL_SCHEMA.extension_statements:
                            cursor.execute(statement)
                        self._record_schema(
                            cursor,
                            application_version=application_version,
                            actor=actor_name,
                        )
                    initialized = self._inspector.inspect_connection(lease)
                    report = self._validator.validate(initialized)
                    if report.compatibility != SqlSchemaCompatibility.CURRENT:
                        raise SqlInfrastructureError(
                            SqlErrorDetails(
                                SqlErrorCode.SCHEMA_MISMATCH,
                                "External database initialization validation failed: "
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
        final_location = replace(location, database_guid=initialized.database_guid)
        return SqlDatabaseCreationResult(final_location, LATEST_SQL_SCHEMA.version)

    @staticmethod
    def _acquire_schema_lock(cursor) -> None:
        cursor.execute(
            "DECLARE @result int; EXEC @result=sys.sp_getapplock "
            "@Resource=N'OSTVisualizer.SchemaInitialization', "
            "@LockMode=N'Exclusive', @LockOwner=N'Transaction', "
            "@LockTimeout=10000; SELECT @result"
        )
        if int(cursor.fetchone()[0]) < 0:
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.LOCKED,
                    "Another client is initializing this database schema.",
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
            LATEST_SQL_SCHEMA.version,
            actor,
            actor,
        )
        cursor.execute(
            "INSERT INTO [ostv].[SchemaMigrations] "
            "([Version], [Name], [Checksum], [AppliedBy], [ApplicationVersion]) "
            "VALUES (?, ?, ?, ?, ?)",
            LATEST_SQL_SCHEMA.version,
            LATEST_SQL_SCHEMA.migration_name,
            LATEST_SQL_SCHEMA.checksum,
            actor,
            application_version,
        )

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
