import logging
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock, patch
import pyodbc
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    CALC_LINEAR_LENGTH,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_M,
)
from ost_visualizer.infrastructure import providers
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    require_single_bid_scope_for_uids,
)
from ost_visualizer.infrastructure.mdb import database_creator
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.constants import (
    TAKEOFF_REFERENCE_TABLES,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    SettingsReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.schema_contract import DEFAULT_LAYER_ROWS
from ost_visualizer.infrastructure.services.license_validation_scheduler import (
    LicenseValidationScheduler,
)


class _SqliteCursorWrapper:
    def __init__(self, connection):
        self._connection = connection
        self._cursor = None

    def execute(self, query, *params):
        self._cursor = self._connection.execute(query, params)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def fetchone(self):
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None or self._cursor.description is None:
            return row
        columns = [description[0] for description in self._cursor.description]
        return _SqliteRow(columns, row)

    def fetchall(self):
        if self._cursor is None:
            return []
        rows = self._cursor.fetchall()
        if self._cursor.description is None:
            return rows
        columns = [description[0] for description in self._cursor.description]
        return [_SqliteRow(columns, row) for row in rows]

    @property
    def rowcount(self):
        return self._cursor.rowcount if self._cursor is not None else -1

    @property
    def description(self):
        return self._cursor.description if self._cursor is not None else None

    @property
    def connection(self):
        return self._connection


class _ParameterLimitedSqliteCursorWrapper(_SqliteCursorWrapper):
    def __init__(self, connection, max_parameters):
        super().__init__(connection)
        self._max_parameters = max_parameters
        self.parameter_counts = []

    def execute(self, query, *params):
        self.parameter_counts.append(len(params))
        if len(params) > self._max_parameters:
            raise AssertionError(
                f"Query used {len(params)} parameters; limit is {self._max_parameters}."
            )
        return super().execute(query, *params)


class _SqliteRow:
    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = tuple(values)
        self._by_name = dict(zip(self._columns, self._values))

    def __getitem__(self, index):
        return self._values[index]

    def __getattr__(self, name):
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class _SqliteConnectionWrapper:
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self._connection.commit()
        return False

    def cursor(self):
        return _SqliteCursorWrapper(self._connection)


class _SqliteSchema:
    def __init__(self, connection):
        self._connection = connection

    def optional_table_missing(self, table_name):
        row = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is None

    def column_exists(self, table_name, column_name):
        return any(
            row[1] == column_name
            for row in self._connection.execute(f"PRAGMA table_info({table_name})")
        )

    def require_column(self, table_name, column_name):
        if not self.column_exists(table_name, column_name):
            raise RuntimeError(f"Missing {table_name}.{column_name}")

    def get_columns(self, table_name):
        return {
            row[1]
            for row in self._connection.execute(f"PRAGMA table_info({table_name})")
        }

    def optional_column(self, table_name, column_name, default_sql):
        if self.column_exists(table_name, column_name):
            return f"[{column_name}]"
        return f"{default_sql} AS [{column_name}]"

    def order_by_existing(self, table_name, columns, fallback):
        existing = [
            column for column in columns if self.column_exists(table_name, column)
        ]
        return ", ".join(f"[{column}]" for column in existing) or fallback

    @staticmethod
    def log_optional_write_skip(_table, _column, _operation):
        pass


class _SqliteMdbOps(
    AccessBulkWriteMixin,
    BidOperationsMixin,
    ConditionOperationsMixin,
    ConditionFolderOperationsMixin,
    LayerOperationsMixin,
    ProjectOperationsMixin,
    SettingsOperationsMixin,
    PageOperationsMixin,
    TakeoffOperationsMixin,
):
    logger = logging.getLogger("test")
    _normalize_display_size = staticmethod(MdbReader._normalize_display_size)

    def __init__(self, connection):
        self._connection_ref = connection
        self._schema_ref = _SqliteSchema(connection)

    def _connection(self, _db_path):
        return _SqliteConnectionWrapper(self._connection_ref)

    def _schema(self, _connection):
        return self._schema_ref

    def _require_write_columns(self, _schema, _table, _columns):
        pass

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False


class _SqliteDuplicateOps(_SqliteMdbOps):
    def _execute_insert_values(
        self, cursor, schema, table, values, _required, _operation
    ):
        persisted = {
            column: value
            for column, value in values.items()
            if schema.column_exists(table, column)
        }
        columns = list(persisted)
        placeholders = ", ".join("?" for _column in columns)
        cursor.execute(
            f"INSERT INTO [{table}] "
            f"({', '.join(f'[{column}]' for column in columns)}) "
            f"VALUES ({placeholders})",
            *(persisted[column] for column in columns),
        )

    def _execute_update_values(
        self,
        cursor,
        schema,
        table,
        values,
        _required,
        where_sql,
        where_params,
        _operation,
        allow_empty=False,
    ):
        del allow_empty
        persisted = {
            column: value
            for column, value in values.items()
            if schema.column_exists(table, column)
        }
        if not persisted:
            return False
        columns = list(persisted)
        assignments = ", ".join(f"[{column}]=?" for column in columns)
        cursor.execute(
            f"UPDATE [{table}] SET {assignments} WHERE {where_sql}",
            *(persisted[column] for column in columns),
            *where_params,
        )
        return True


class _ParameterLimitedSqliteConnectionWrapper(_SqliteConnectionWrapper):
    def __init__(self, connection, max_parameters):
        super().__init__(connection)
        self._max_parameters = max_parameters

    def cursor(self):
        return _ParameterLimitedSqliteCursorWrapper(
            self._connection, self._max_parameters
        )


class _ParameterLimitedSqliteOps(_SqliteDuplicateOps):
    def __init__(self, connection, max_parameters=255):
        super().__init__(connection)
        self._max_parameters = max_parameters

    def _connection(self, _db_path):
        return _ParameterLimitedSqliteConnectionWrapper(
            self._connection_ref, self._max_parameters
        )


class _SqliteAnnotationOps(AnnotationOperationsMixin, _SqliteDuplicateOps):
    pass


class _RecordingSchema:
    def __init__(self, columns_by_table=None):
        self.columns_by_table = columns_by_table or {
            "BidTakeoffs": {
                "UID",
                "BidUID",
                "BidAreaUID",
                "BidConditionUID",
                "IsNegativeQuantity",
            }
        }

    def require_column(self, table, column):
        if not self.column_exists(table, column):
            raise RuntimeError(f"Missing {table}.{column}")

    def optional_table_missing(self, table):
        return table not in self.columns_by_table

    def column_exists(self, table, column):
        return column in self.columns_by_table.get(table, set())


class _RecordingCursor:
    def __init__(self, ops):
        self.ops = ops
        self.validation_rows = []

    def execute(self, query, *params):
        if query.startswith("SELECT [UID], [BidUID] FROM ["):
            self.validation_rows = [(param, 1) for param in params]
            return
        if query.startswith("SELECT [UID] FROM ["):
            self.validation_rows = [(param,) for param in params]
            return
        self.ops.executions.append((query, tuple(params)))
        self.ops.execute_count += 1
        if (
            self.ops.fail_on_execute is not None
            and self.ops.execute_count == self.ops.fail_on_execute
        ):
            raise RuntimeError("forced chunk failure")
        if self.ops.fail_once_hy001 and not self.ops.failed_hy001:
            self.ops.failed_hy001 = True
            raise pyodbc.OperationalError(
                "HY001",
                "[HY001] [Microsoft][ODBC Microsoft Access Driver] "
                "System resource exceeded.",
            )

    def fetchall(self):
        return list(self.validation_rows)


class _RecordingConnection:
    def __init__(self, ops):
        self.ops = ops

    def cursor(self):
        return _RecordingCursor(self.ops)


class _RecordingTakeoffOps(AccessBulkWriteMixin, TakeoffOperationsMixin):
    def __init__(
        self,
        schema=None,
        fail_on_execute=None,
        fail_once_hy001=False,
    ):
        self.schema = schema or _RecordingSchema()
        self.fail_on_execute = fail_on_execute
        self.fail_once_hy001 = fail_once_hy001
        self.failed_hy001 = False
        self.execute_count = 0
        self.executions = []
        self.connection_count = 0
        self.commits = 0
        self.rollbacks = 0
        self.logger = logging.getLogger("tests.recording_takeoff_ops")

    @contextmanager
    def _connection(self, _db_path):
        self.connection_count += 1
        try:
            yield _RecordingConnection(self)
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def _schema(self, _connection):
        return self.schema

    def _require_write_columns(self, schema, table, columns):
        for column in columns:
            schema.require_column(table, column)

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False
