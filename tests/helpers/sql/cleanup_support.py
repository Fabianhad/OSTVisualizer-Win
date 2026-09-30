import contextlib
import json
import logging
import os
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from tests.paths import REPO_ROOT
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationMutationType,
    ConcurrencyToken,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationRequest as _DatabaseMutationRequest,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    ExpectedResourceVersion,
    MutationOutcomeStatus,
    ResourceRef,
    SynchronizationConflictKind,
)
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.database.connection_wrapper import ConnectionWrapper
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.reader_router import DatabaseProjectReader
from ost_visualizer.infrastructure.database.settings_cardinality import (
    GlobalSettingsCardinalityError,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    ACCESS_BULK_CHUNK_SIZE,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.schema_compatibility import MdbSchemaInspector
from ost_visualizer.infrastructure.providers import RepositoryProvider
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionLease,
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.database_creator import (
    SqlDatabaseCreator,
    _add_exception_note,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.permissions import SqlDatabasePermissionProbe
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlSchemaInspector,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidationReport,
    SqlSchemaValidator,
)
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from ost_visualizer.infrastructure.sql.writer import (
    SqlProjectWriter,
    _OptimisticConflict,
    _RecordedMutation,
    _SqlMutationState,
)
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from PySide6 import QtWidgets
from tests.helpers.workspace_state import with_workspace_state

FileOperationHandler = with_workspace_state(FileOperationHandler)


def DatabaseMutationRequest(
    *,
    database_id,
    session_id,
    resources=(),
    required_lock_tokens=(),
):
    """Build an explicitly identified canonical request for writer tests."""
    return _DatabaseMutationRequest(
        database_id=database_id,
        session_id=session_id,
        operation_id=str(uuid.uuid4()),
        mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
        request_hash="a" * 64,
        resources=resources,
        required_lock_tokens=required_lock_tokens,
    )


def _canonical_writer_permission_snapshot(
    *,
    roles=(1, 1, 1, 1, 1),
    metadata=None,
    collaboration=None,
    marker=(1, 1, 0, 0, 1),
):
    return (
        *roles,
        *(
            metadata
            or (
                SQL_SCHEMA_V1.version,
                SQL_SCHEMA_V1.checksum,
                "READ_WRITE",
                "ost_visualizer_only",
                "disabled",
                None,
                1,
                1,
                1,
                1,
            )
        ),
        *(collaboration or (len(SQL_CLIENT_DIRECT_WRITE_TABLES), 0, 0)),
        *marker,
    )


class _CredentialStore:
    def __init__(self):
        self.deleted = []

    def read_password(self, _target):
        return None

    def write_password(self, _target, _username, _password):
        pass

    def delete_password(self, target):
        self.deleted.append(target)


class _RawCursor:
    def __init__(self):
        self.close_count = 0
        self.timeout = 0

    def close(self):
        self.close_count += 1


class _RawConnection:
    def __init__(self):
        self.raw_cursor = _RawCursor()
        self.close_count = 0

    def cursor(self):
        return self.raw_cursor

    def close(self):
        self.close_count += 1


class _AccessTransactionConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    @staticmethod
    def cursor():
        return _RawCursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _AccessTransactionConnections:
    def __init__(self):
        self.connection_value = _AccessTransactionConnection()
        self.lease_count = 0
        self.committed_writer_reads = []

    @contextlib.contextmanager
    def connection(self, _database_id, *, autocommit=False):
        self.lease_count += 1
        self.asserted_autocommit = autocommit
        yield ConnectionWrapper(self.connection_value)

    def use_committed_writer_for_reads(self, database_id):
        self.committed_writer_reads.append(database_id)


class _InspectionCursor:
    def __init__(self):
        self._last_sql = ""
        self._last_params = ()
        self.executed = []

    def execute(self, sql, *_params):
        self._last_sql = sql
        self.executed.append(sql)
        if "SELECT s.name, t.name, i.name" in sql:
            if "FROM sys.indexes i" not in sql:
                raise AssertionError("index inventory query has no FROM sys.indexes")
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def fetchone(self):
        if "ostv_permission_snapshot" in self._last_sql:
            return _canonical_writer_permission_snapshot()
        if "database_guid" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class _InspectionLease:
    def __init__(self):
        self.cursor_value = _InspectionCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _InspectionManager:
    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        self.lease = _InspectionLease()
        yield self.lease


class _CreationCursor:
    def __init__(self):
        self._last_sql = ""
        self.executed = []
        self.schema_record = None

    def execute(self, sql, *params):
        self._last_sql = sql
        self._last_params = params
        self.executed.append(sql)
        if "INSERT INTO [ostv].[SchemaMigrations]" in sql:
            self.schema_record = (params[0], params[2])
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def fetchone(self):
        if (
            "[ostv].[DatabaseMetadata]" in self._last_sql
            and "[ostv].[SchemaMigrations]" in self._last_sql
        ):
            return (
                *self.schema_record,
                "READ_WRITE",
                "ost_visualizer_only",
                "disabled",
                None,
                1,
                1,
                1,
                1,
            )
        if "snapshot_isolation_state" in self._last_sql:
            return (1,)
        if "retention_period" in self._last_sql:
            return None
        if "IS_ROLEMEMBER" in self._last_sql:
            return (1, 1, 1, 1, 1)
        if "COUNT(*) FROM sys.tables" in self._last_sql:
            return (0,)
        if "FROM sys.tables" in self._last_sql:
            return (len(SQL_CLIENT_DIRECT_WRITE_TABLES), 0, 0)
        if "VIEW CHANGE TRACKING" in self._last_sql:
            return (1, 1, 0, 0, 1)
        if "sp_getapplock" in self._last_sql:
            return (0,)
        if "FROM [ostv].[Sessions]" in self._last_sql:
            return (1,)
        if "database_guid" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        return (0,)

    def close(self):
        pass


class _CreationLease:
    def __init__(self):
        self.cursor_value = _CreationCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _CreationManager:
    def __init__(self):
        self.lease = _CreationLease()

    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield self.lease


class _WriterCursor(_CreationCursor):
    def __init__(self, connection):
        super().__init__()
        self.connection = connection
        self.close_count = 0

    def fetchone(self):
        if "DECLARE @MutationResources TABLE" in self._last_sql:
            return None
        if "DECLARE @LockResult int" in self._last_sql:
            return (0, None, None, None, None, 1)
        if "ostv_permission_snapshot" in self._last_sql:
            return _canonical_writer_permission_snapshot()
        if "IS_ROLEMEMBER" in self._last_sql:
            return (1, 1, 1, 1, 1)
        if "SchemaMigrations" in self._last_sql:
            return (
                SQL_SCHEMA_V1.version,
                SQL_SCHEMA_V1.checksum,
                "READ_WRITE",
                "ost_visualizer_only",
                "disabled",
                None,
                1,
                1,
                1,
                1,
            )
        if "FROM sys.tables" in self._last_sql:
            return (len(SQL_CLIENT_DIRECT_WRITE_TABLES), 0, 0)
        if "VIEW CHANGE TRACKING" in self._last_sql:
            return (1, 1, 0, 0, 1)
        if "sp_getapplock" in self._last_sql:
            return (0,)
        if "FROM [ostv].[Sessions]" in self._last_sql:
            return (1,)
        if "SELECT TOP (1) [DatabaseGuid]" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        if "SELECT MAX([RefNo])" in self._last_sql:
            return (None,)
        if "OUTPUT INSERTED.[Token]" in self._last_sql:
            return (b"\x00\x00\x00\x00\x00\x00\x00\x01",)
        return None

    def fetchall(self):
        if self._last_sql.startswith("SELECT [UID], [BidUID] FROM ["):
            return [(param, 1) for param in self._last_params]
        if self._last_sql.startswith("SELECT [UID] FROM ["):
            return [(param,) for param in self._last_params]
        if "DECLARE @RequestedLocks TABLE" in self._last_sql:
            requested = json.loads(self._last_params[0])
            return [(row["ordinal"], 0) for row in requested]
        if "DECLARE @Changes TABLE" in self._last_sql:
            changes = json.loads(self._last_params[0])
            return [
                (row["ordinal"], int(row["ordinal"] + 1).to_bytes(8, "big"))
                for row in changes
            ]
        if "DECLARE @ExpectedVersions TABLE" in self._last_sql:
            expected = json.loads(self._last_params[0])
            return [
                (row["ordinal"], b"\x00\x00\x00\x00\x00\x00\x00\x01")
                for row in expected
            ]
        return []

    def close(self):
        self.close_count += 1


class _WriterLease:
    def __init__(self):
        self.cursors = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        cursor = _WriterCursor(self)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _WriterManager:
    def __init__(self):
        self.lease = _WriterLease()

    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield self.lease


def _empty_inventory():
    return SqlSchemaInventory(
        database_guid="00000000-0000-0000-0000-000000000001",
        schema_version=0,
        schema_checksum="",
        tables=frozenset(),
        columns=(),
        foreign_keys=(),
        indexes=(),
        views=(),
        triggers=(),
        procedures=(),
        functions=(),
    )
