import logging
from ...application.dtos.condition_takeoff_reassignment import (
    ConditionTakeoffReassignment,
)
import contextvars
from contextlib import contextmanager
from typing import Generator, Optional, Sequence
import pyodbc
from .components.annotation_operations import AnnotationOperationsMixin
from .components.bid_operations import BidOperationsMixin
from .components.bulk_write_helpers import AccessBulkWriteMixin
from .components.condition_folder_operations import ConditionFolderOperationsMixin
from .components.condition_operations import ConditionOperationsMixin
from ..database.connection_wrapper import ConnectionWrapper
from ..database.annotation_storage import ANNOTATION_TABLE_BY_TYPE
from ..database.bid_owned_identity import (
    MissingBidOwnedUidError,
    require_existing_bid_scoped_uid_matches,
    require_existing_unique_bid_owned_uid_matches,
)
from ..database.schema_inspector_contract import IDatabaseSchemaInspector
from .components.import_operations import ImportOperationsMixin
from .components.layer_operations import LayerOperationsMixin
from .components.page_operations import PageOperationsMixin
from .components.project_operations import ProjectOperationsMixin
from .components.settings_operations import SettingsOperationsMixin
from .components.takeoff_operations import TakeoffOperationsMixin
from .connection_manager import MdbConnectionManager
from .schema_compatibility import MdbSchemaInspector, UnsupportedMdbSchemaError


class MdbWriter(
    AccessBulkWriteMixin,
    BidOperationsMixin,
    ConditionOperationsMixin,
    ConditionFolderOperationsMixin,
    ImportOperationsMixin,
    ProjectOperationsMixin,
    SettingsOperationsMixin,
    PageOperationsMixin,
    TakeoffOperationsMixin,
    AnnotationOperationsMixin,
    LayerOperationsMixin,
):
    def __init__(
        self,
        conn_manager: Optional[MdbConnectionManager] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._conn_manager = conn_manager or MdbConnectionManager()
        self._access_transaction_depth = contextvars.ContextVar(
            "mdb_writer_transaction_depth",
            default=0,
        )
        self._access_transaction_error = contextvars.ContextVar(
            "mdb_writer_transaction_error",
            default=None,
        )

    @contextmanager
    def _connection(self, db_path: str) -> Generator[ConnectionWrapper, None, None]:
        depth = self._access_transaction_depth.get()
        depth_token = self._access_transaction_depth.set(depth + 1)
        error_token = None
        committed = False
        if depth == 0:
            error_token = self._access_transaction_error.set(None)
        try:
            with self._conn_manager.connection(db_path, autocommit=False) as conn:
                try:
                    yield conn
                    if depth == 0:
                        transaction_error = self._access_transaction_error.get()
                        if transaction_error is not None:
                            raise transaction_error
                        conn.commit()
                        committed = True
                except Exception as exc:
                    if depth > 0 and self._access_transaction_error.get() is None:
                        self._access_transaction_error.set(exc)
                    if depth == 0:
                        try:
                            conn.rollback()
                        except pyodbc.Error as rollback_error:
                            rollback_error.add_note(
                                "The MDB transaction could not be rolled back after "
                                f"{type(exc).__name__}: {exc}"
                            )
                            raise rollback_error from exc
                    raise
        finally:
            self._access_transaction_depth.reset(depth_token)
            if error_token is not None:
                self._access_transaction_error.reset(error_token)
        if committed:
            self._conn_manager.use_committed_writer_for_reads(db_path)

    def _schema(self, connection) -> IDatabaseSchemaInspector:
        return MdbSchemaInspector(connection, self.logger)

    def verify_takeoff_reassignment(
        self, database_id: str, bid_uid: str, assignment: ConditionTakeoffReassignment
    ) -> None:
        with self._connection(database_id) as connection:
            schema = self._schema(connection)
            self._require_write_columns(
                schema,
                "BidTakeoffs",
                ("UID", "BidUID", "BidPageUID", "BidConditionUID"),
            )
            cursor = connection.cursor()
            for table, uid in (
                ("BidPages", assignment.page_uid),
                ("BidConditions", assignment.condition_uid),
            ):
                require_existing_bid_scoped_uid_matches(
                    cursor, table, (int(uid),), bid_uid
                )
            expected = {int(uid) for uid in assignment.takeoff_uids}
            found = set()
            for chunk in self._iter_access_chunks(tuple(expected)):
                placeholders = ",".join("?" for _uid in chunk)
                cursor.execute(
                    "SELECT [UID], [BidPageUID], [BidConditionUID] FROM [BidTakeoffs] "
                    f"WHERE [BidUID]=? AND [UID] IN ({placeholders})",
                    int(bid_uid),
                    *chunk,
                )
                for uid, page_uid, condition_uid in cursor.fetchall():
                    if page_uid != int(assignment.page_uid) or condition_uid != int(
                        assignment.condition_uid
                    ):
                        raise MissingBidOwnedUidError(
                            "A Takeoff changed Page or Condition before reassignment started."
                        )
                    found.add(int(uid))
            if found != expected:
                raise MissingBidOwnedUidError(
                    "A Takeoff was deleted or replaced before reassignment started."
                )

    def verify_plan_items_exist(
        self,
        database_id: str,
        bid_uid: str,
        takeoff_uids: Sequence[str],
        annotations: Sequence[tuple[str, str]],
    ) -> None:
        with self._connection(database_id) as connection:
            schema = self._schema(connection)
            cursor = connection.cursor()
            require_existing_unique_bid_owned_uid_matches(cursor, "Bids", (bid_uid,))
            normalized_takeoffs = tuple(dict.fromkeys(int(uid) for uid in takeoff_uids))
            if normalized_takeoffs:
                self._require_write_columns(schema, "BidTakeoffs", ("UID", "BidUID"))
                require_existing_bid_scoped_uid_matches(
                    cursor, "BidTakeoffs", normalized_takeoffs, bid_uid
                )
                if schema.column_exists("BidTakeoffs", "ParentUID"):
                    selected_uids = set(normalized_takeoffs)
                    for uid_chunk in self._iter_access_chunks(normalized_takeoffs):
                        placeholders = ",".join("?" for _uid in uid_chunk)
                        cursor.execute(
                            "SELECT [UID] FROM [BidTakeoffs] "
                            "WHERE [BidUID]=? AND [ParentUID] IN "
                            f"({placeholders})",
                            int(bid_uid),
                            *uid_chunk,
                        )
                        if any(
                            int(row[0]) not in selected_uids
                            for row in cursor.fetchall()
                        ):
                            raise MissingBidOwnedUidError(
                                "The takeoff relationship graph changed before "
                                "the Plan mutation started."
                            )
            annotation_uids_by_table: dict[str, list[int]] = {}
            for uid, annotation_type in annotations:
                table = ANNOTATION_TABLE_BY_TYPE.get(annotation_type)
                if table is None or schema.optional_table_missing(table):
                    raise MissingBidOwnedUidError(
                        "An annotation changed or was deleted before the Plan "
                        "mutation started."
                    )
                annotation_uids_by_table.setdefault(table, []).append(int(uid))
            for table, uids in annotation_uids_by_table.items():
                self._require_write_columns(schema, table, ("UID", "BidUID"))
                require_existing_bid_scoped_uid_matches(cursor, table, uids, bid_uid)

    def _record_caught_mutation_error(self, exc: BaseException) -> bool:
        return (
            isinstance(exc, pyodbc.Error) and self._access_transaction_depth.get() > 0
        )

    def _require_write_columns(
        self, schema: IDatabaseSchemaInspector, table: str, columns: tuple[str, ...]
    ) -> None:
        for column in columns:
            schema.require_column(table, column)

    def _filter_existing_write_values(
        self,
        schema: IDatabaseSchemaInspector,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> dict:
        schema.require_table(table)
        self._require_write_columns(schema, table, required_columns)
        filtered = {}
        for column, value in values.items():
            if schema.column_exists(table, column):
                filtered[column] = value
                continue
            if column in required_columns:
                schema.require_column(table, column)
            schema.log_optional_write_skip(table, column, operation)
        return filtered

    def _execute_insert_values(
        self,
        cursor: pyodbc.Cursor,
        schema: IDatabaseSchemaInspector,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        operation: str,
    ) -> None:
        filtered = self._filter_existing_write_values(
            schema, table, values, required_columns, operation
        )
        missing = [column for column in required_columns if column not in filtered]
        if missing:
            raise UnsupportedMdbSchemaError(
                f"This OST database is missing required writable columns "
                f"{table}.{', '.join(missing)} for {operation}."
            )
        if not filtered:
            raise UnsupportedMdbSchemaError(
                f"This OST database has no writable columns for {operation}."
            )
        col_list = ", ".join(f"[{column}]" for column in filtered)
        placeholders = ", ".join("?" for _ in filtered)
        cursor.execute(
            f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})",
            list(filtered.values()),
        )

    def _execute_update_values(
        self,
        cursor: pyodbc.Cursor,
        schema: IDatabaseSchemaInspector,
        table: str,
        values: dict,
        required_columns: tuple[str, ...],
        where_sql: str,
        params: list,
        operation: str,
        allow_empty: bool = False,
    ) -> bool:
        filtered = self._filter_existing_write_values(
            schema, table, values, required_columns, operation
        )
        if not filtered:
            if allow_empty:
                return False
            raise UnsupportedMdbSchemaError(
                f"This OST database has no writable columns for {operation}."
            )
        set_clause = ", ".join(f"[{column}]=?" for column in filtered)
        cursor.execute(
            f"UPDATE [{table}] SET {set_clause} WHERE {where_sql}",
            list(filtered.values()) + params,
        )
        return True
