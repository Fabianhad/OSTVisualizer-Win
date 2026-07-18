from __future__ import annotations
import itertools
import logging
import threading
import uuid
from contextlib import contextmanager
from typing import Generator, Optional
import pyodbc
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...domain.dtos.raw_bid_data_dto import RawBidData
from ..mdb.components.constants import BID_TABLES_WRITE_ORDER
from ..mdb.schema_contract import PAGE_SECTIONS
from ..mdb.mdb_writer import MdbWriter
from .connection_manager import SqlConnectionLease, SqlConnectionManager
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
    sql_schema_mismatch,
)
from .schema_definition import LATEST_SQL_SCHEMA, schema_record_is_current
from .write_schema import CurrentSqlWriteSchema


class _DeferredIdentity(int):
    def __new__(cls, placeholder: int):
        instance = int.__new__(cls, placeholder)
        instance._resolved = None
        return instance

    def bind(self, value: int) -> None:
        self._resolved = int(value)

    @property
    def resolved(self) -> int:
        if self._resolved is None:
            raise RuntimeError("SQL identity has not been generated yet")
        return self._resolved

    def __int__(self) -> int:
        return self.resolved

    def __str__(self) -> str:
        return str(self.resolved)


class SqlProjectWriter(MdbWriter):
    """SQL transaction adapter reusing backend-neutral operation semantics."""

    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        connection_manager: Optional[SqlConnectionManager] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._requests = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._sql_connections = connection_manager or SqlConnectionManager()
        self._identity_lock = threading.Lock()
        self._identity_placeholders = itertools.count(start=-1, step=-1)
        self._write_schema = CurrentSqlWriteSchema(LATEST_SQL_SCHEMA.core_schema)

    @contextmanager
    def _connection(
        self, database_id: str
    ) -> Generator[SqlConnectionLease, None, None]:
        request = self._requests.request(database_id, read_only=False)
        with self._sql_connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                self._require_current_schema(lease)
                self._acquire_write_transaction_lock(lease)
                yield lease
                self._append_database_change(lease, database_id)
                lease.commit()
                committed = True
            finally:
                if not committed:
                    try:
                        lease.rollback()
                    except pyodbc.Error:
                        pass

    @staticmethod
    def _require_current_schema(lease) -> None:
        cursor = lease.cursor()
        try:
            cursor.execute(
                "SELECT [Version], [Checksum] FROM [ostv].[SchemaMigrations] "
                "WHERE [Version]=?",
                LATEST_SQL_SCHEMA.version,
            )
            row = cursor.fetchone()
        except pyodbc.Error:
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.SCHEMA_MISMATCH,
                    "This SQL database is not writable by this OST Visualizer version.",
                )
            ) from None
        finally:
            cursor.close()
        if row is None or not schema_record_is_current(row[0], row[1]):
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.UNSUPPORTED_SCHEMA,
                    "This SQL database uses an unsupported schema version.",
                )
            )

    @staticmethod
    def _acquire_write_transaction_lock(lease) -> None:
        """Serialize client writes without relying on UI action state.
        The lock is transaction-owned, so SQL Server releases it on commit,
        rollback, connection loss, or process failure. Entity-level optimistic
        tokens are layered on top by collaboration-aware operations.
        """
        cursor = lease.cursor()
        try:
            cursor.execute(
                "DECLARE @result int; EXEC @result=sys.sp_getapplock "
                "@Resource=N'OSTVisualizer.DatabaseWrite', "
                "@LockMode=N'Exclusive', @LockOwner=N'Transaction', "
                "@LockTimeout=30000; SELECT @result;"
            )
            row = cursor.fetchone()
            if row is None or int(row[0]) < 0:
                raise RuntimeError(
                    "Another database operation is still in progress. Try again."
                )
        finally:
            cursor.close()

    @staticmethod
    def _append_database_change(lease, database_id: str) -> None:
        """Record one coalescible delta for every writable transaction."""
        cursor = lease.cursor()
        try:
            cursor.execute(
                "INSERT INTO [ostv].[ChangeLog] ([TransactionId], [ResourceType], "
                "[ResourceId], [Operation]) VALUES (?, N'database', ?, N'write')",
                str(uuid.uuid4()),
                database_id,
            )
        finally:
            cursor.close()

    def _next_uid(self, cursor, table: str) -> int:
        del cursor, table
        with self._identity_lock:
            return _DeferredIdentity(next(self._identity_placeholders))

    def _execute_insert_values(
        self,
        cursor,
        schema,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> Optional[int]:
        filtered = self._filter_existing_write_values(
            schema, table, values, required_columns, operation
        )
        missing = [
            column
            for column in required_columns
            if column != "UID" and column not in filtered
        ]
        if missing:
            raise sql_schema_mismatch(
                f"This OST database is missing required writable columns "
                f"{table}.{', '.join(missing)} for {operation}."
            )
        identity = filtered.pop("UID", None)
        resolved_values = {
            column: self._resolve_deferred(value) for column, value in filtered.items()
        }
        if not resolved_values:
            raise sql_schema_mismatch(
                f"This OST database has no writable columns for {operation}."
            )
        columns = ", ".join(f"[{column}]" for column in resolved_values)
        placeholders = ", ".join("?" for _ in resolved_values)
        cursor.execute(
            f"INSERT INTO [dbo].[{table}] ({columns}) "
            f"OUTPUT INSERTED.[UID] VALUES ({placeholders})",
            list(resolved_values.values()),
        )
        row = cursor.fetchone()
        generated = int(row[0]) if row is not None else None
        if isinstance(identity, _DeferredIdentity) and generated is not None:
            identity.bind(generated)
        return generated

    def _filter_existing_write_values(
        self,
        schema,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> dict:
        del operation
        schema.require_table(table)
        self._require_write_columns(schema, table, required_columns)
        missing = [
            column for column in values if not schema.column_exists(table, column)
        ]
        if missing:
            raise sql_schema_mismatch(
                f"The current SQL schema is missing {table}.{', '.join(missing)}."
            )
        return dict(values)

    def _schema(self, connection) -> CurrentSqlWriteSchema:
        del connection
        return self._write_schema

    def create_project(self, db_path: str, name: str) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidProjects", ("UID", "Name"))
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO [dbo].[BidProjects] ([Name]) "
                        "OUTPUT INSERTED.[UID] VALUES (?)",
                        name,
                    )
                    row = cursor.fetchone()
                    return str(row[0]) if row is not None else None
        except (OSError, RuntimeError, TypeError, ValueError):
            self.logger.exception("Failed to create SQL project in %s", db_path)
            return None

    def import_ost_data(
        self,
        db_path: str,
        raw_data: RawBidData,
        transform_fn,
        target_project_uid: Optional[str] = None,
    ) -> bool:
        try:
            with self._connection(db_path) as connection:
                cdn_map = self._resolve_global_by_column(
                    connection, raw_data, "CdnTypes", "Name"
                )
                status_map = self._resolve_global_by_column(
                    connection, raw_data, "JobStatuses", "Name"
                )
                access_map = self._resolve_global_by_column(
                    connection, raw_data, "AccessLevels", "Description"
                )
                pay_class_map = self._resolve_global_by_column(
                    connection, raw_data, "PayClasses", "Name"
                )
                employee_map = self._resolve_sql_employees(
                    connection, raw_data, pay_class_map, access_map
                )
                remapped = transform_fn(
                    raw_data,
                    0,
                    cdn_map,
                    status_map,
                    employee_map,
                    pay_class_map,
                )
                self._assign_next_bid_no(connection, remapped)
                remapped.bid_row["BidProjectUID"] = (
                    target_project_uid if target_project_uid else None
                )
                self._write_remapped_identity_graph(connection, remapped)
            return True
        except (OSError, RuntimeError, TypeError, ValueError):
            self.logger.exception("Failed to write imported OST data to %s", db_path)
            return False

    def _resolve_global_by_column(
        self,
        connection,
        raw_data: RawBidData,
        table: str,
        identity_column: str,
    ) -> dict[str, str]:
        incoming = raw_data.global_tables.get(table, [])
        if not incoming:
            return {}
        existing = self._load_existing_uid_by_column(connection, table, identity_column)
        result: dict[str, str] = {}
        table_info = self._get_table_info(connection, table)
        for row in incoming:
            old_uid = str(row.get("UID", ""))
            identity = str(row.get(identity_column, ""))
            if identity in existing:
                result[old_uid] = existing[identity]
                continue
            actual = self._insert_identity_raw(connection, table, row, table_info)
            result[old_uid] = str(actual)
            existing[identity] = str(actual)
        return result

    def _resolve_sql_employees(
        self,
        connection,
        raw_data: RawBidData,
        pay_class_map: dict[str, str],
        access_map: dict[str, str],
    ) -> dict[str, str]:
        incoming = raw_data.global_tables.get("Employees", [])
        if not incoming:
            return {}
        existing = self._load_existing_employee_uid_by_key(connection)
        table_info = self._get_table_info(connection, "Employees")
        result: dict[str, str] = {}
        for row in incoming:
            old_uid = str(row.get("UID", ""))
            key = self._employee_identity_key(row)
            if key and key in existing:
                result[old_uid] = existing[key]
                continue
            insert_row = dict(row)
            for column, mapping in (
                ("PayClassUID", pay_class_map),
                ("AccessLevelUID", access_map),
            ):
                source_value = insert_row.get(column)
                if source_value in (None, "", "0", "NULL"):
                    insert_row[column] = None
                    continue
                source = str(source_value)
                mapped_uid = mapping.get(source)
                if mapped_uid is None:
                    raise RuntimeError(
                        f"Imported employee references an unknown {column}."
                    )
                insert_row[column] = mapped_uid
            actual = self._insert_identity_raw(
                connection, "Employees", insert_row, table_info
            )
            result[old_uid] = str(actual)
            if key:
                existing[key] = str(actual)
        return result

    def _write_remapped_identity_graph(self, connection, remapped: RawBidData) -> None:
        rows_by_table: list[tuple[str, dict]] = [("Bids", remapped.bid_row)]
        rows_by_table.extend(
            (table, row)
            for table in BID_TABLES_WRITE_ORDER
            for row in remapped.bid_tables.get(table, [])
        )
        rows_by_table.extend(
            (table, row)
            for table in PAGE_SECTIONS
            for row in remapped.page_tables.get(table, [])
        )
        internal_uids = {
            str(row.get("UID"))
            for _, row in rows_by_table
            if row.get("UID") not in (None, "", "0", "NULL")
        }
        identity_map: dict[str, int] = {}
        pending: list[tuple[str, int, str, str]] = []
        table_info_cache = {}
        for table, row in rows_by_table:
            table_info = table_info_cache.get(table)
            if table_info is None:
                table_info = self._get_table_info(connection, table)
                table_info_cache[table] = table_info
            source_uid = str(row.get("UID", ""))
            insert_row = dict(row)
            unresolved_columns: list[tuple[str, str]] = []
            for column, value in list(insert_row.items()):
                if column == "UID" or not column.endswith("UID"):
                    continue
                raw_reference = str(value or "")
                if raw_reference in ("", "0", "NULL"):
                    insert_row[column] = None
                elif raw_reference in identity_map:
                    insert_row[column] = identity_map[raw_reference]
                elif raw_reference in internal_uids:
                    insert_row[column] = None
                    unresolved_columns.append((column, raw_reference))
            actual_uid = self._insert_identity_raw(
                connection, table, insert_row, table_info
            )
            if source_uid:
                identity_map[source_uid] = actual_uid
            pending.extend(
                (table, actual_uid, column, raw_reference)
                for column, raw_reference in unresolved_columns
            )
        cursor = connection.cursor()
        try:
            for table, row_uid, column, target_source_uid in pending:
                target_uid = identity_map.get(target_source_uid)
                if target_uid is None:
                    raise RuntimeError(
                        f"Unresolved imported reference {table}.{column}"
                    )
                cursor.execute(
                    f"UPDATE [dbo].[{table}] SET [{column}]=? WHERE [UID]=?",
                    target_uid,
                    row_uid,
                )
        finally:
            cursor.close()

    def _insert_identity_raw(
        self,
        connection,
        table: str,
        row: dict,
        table_info,
    ) -> int:
        db_columns, column_types = table_info
        unknown_columns = set(row) - db_columns
        if unknown_columns:
            raise RuntimeError(
                f"Imported {table} row contains unsupported columns: "
                + ", ".join(sorted(unknown_columns))
            )
        filtered = {column: value for column, value in row.items() if column != "UID"}
        if not filtered:
            raise RuntimeError(f"No importable columns for {table}")
        columns = list(filtered)
        values = [
            self._convert_sql_import_value(
                filtered[column], column_types.get(column, "")
            )
            for column in columns
        ]
        cursor = connection.cursor()
        try:
            column_sql = ", ".join(f"[{column}]" for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            cursor.execute(
                f"INSERT INTO [dbo].[{table}] ({column_sql}) "
                f"OUTPUT INSERTED.[UID] VALUES ({placeholders})",
                values,
            )
            result = cursor.fetchone()
            if result is None:
                raise RuntimeError(f"SQL Server did not return an identity for {table}")
            return int(result[0])
        finally:
            cursor.close()

    def _convert_sql_import_value(self, value, type_name: str):
        if value is not None and not isinstance(value, str):
            return value
        normalized = type_name.casefold()
        if normalized == "datetime2":
            converted = self._convert_access_value(value, "datetime")
            if converted is None and value not in (None, "", "NULL"):
                raise ValueError("Imported date value is invalid")
            return converted
        if normalized == "varbinary":
            return self._convert_access_value(value, "longbinary")
        if value is None or value == "NULL":
            return None
        if normalized in {"int", "smallint", "bigint"}:
            return int(value) if value != "" else None
        if normalized == "float":
            return float(value) if value != "" else None
        if normalized == "bit":
            if value in {"True", "true", "-1", "1"}:
                return True
            if value in {"False", "false", "0", ""}:
                return False
            raise ValueError("Imported Boolean value is invalid")
        if normalized in {"nvarchar", "varchar", "char"}:
            return value
        raise RuntimeError(f"Unsupported SQL import type: {type_name}")

    def _get_table_info(self, connection, table: str):
        del connection
        return self._write_schema.table_info(table)

    def _assign_next_bid_no(self, connection, remapped: RawBidData) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT [NextBidNo] FROM [dbo].[Settings]")
            row = cursor.fetchone()
            if row is None or row[0] is None:
                raise RuntimeError("The current SQL database has no bid sequence.")
            next_bid_no = int(row[0])
            cursor.execute("UPDATE [dbo].[Settings] SET [NextBidNo]=?", next_bid_no + 1)
        finally:
            cursor.close()
        remapped.bid_row["BidNo"] = str(next_bid_no)

    def _load_existing_uid_by_column(
        self, connection, table: str, column: str
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT [UID], [{column}] FROM [dbo].[{table}]")
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return {str(row[1]) if row[1] is not None else "": str(row[0]) for row in rows}

    def _load_existing_employee_uid_by_key(self, connection) -> dict[str, str]:
        columns = ("UID", "EmployeeNo", "FirstName", "LastName", "EMail")
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT [UID], [EmployeeNo], [FirstName], [LastName], [EMail] "
                "FROM [dbo].[Employees]"
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()
        result: dict[str, str] = {}
        for row in rows:
            row_data = {
                column: str(row[index]) if row[index] is not None else ""
                for index, column in enumerate(columns)
            }
            key = self._employee_identity_key(row_data)
            if key:
                result[key] = row_data["UID"]
        return result

    def _insert_page_area_selection(
        self,
        cursor,
        schema,
        page_uid: int,
        area_uid: int | None,
        selected_value: int,
    ) -> None:
        self._execute_insert_values(
            cursor,
            schema,
            "BidPageSettings",
            {
                "UID": self._next_uid(cursor, "BidPageSettings"),
                "BidPageUID": page_uid,
                "BidAreaUID": area_uid,
                "BidAreaSelected": selected_value,
            },
            ("UID", "BidPageUID", "BidAreaSelected"),
            "insert_page_area_selection",
        )

    @staticmethod
    def _resolve_deferred(value):
        if isinstance(value, _DeferredIdentity):
            return value.resolved
        return value
