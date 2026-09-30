import json
import re
import threading
import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pyodbc
from ost_visualizer.application.dtos.collaboration_dtos import SynchronizationState
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
    SqlDatabaseRuntimeCredentials,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    SQL_CLIENT_PROTECTED_OSTV_TABLES,
    require_sql_client_editability,
)
from ost_visualizer.infrastructure.sql.client_provisioning import (
    SqlAuthenticatedClient,
    authenticate_runtime_client,
    provision_runtime_client,
    verify_runtime_client,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.descriptor_connection import (
    SqlDescriptorConnectionFactory,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
    SqlConnectionDialogResult,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import with_workspace_state

_GUID = "00000000-0000-0000-0000-000000000123"
_CREATOR = SqlServerDatabaseLocation(
    server="test-server",
    database="",
    authentication_mode=SqlAuthenticationMode.SQL_SERVER,
    username="setup-admin",
    encrypt=True,
    trust_server_certificate=False,
    connection_timeout_seconds=7,
    command_timeout_seconds=17,
)
_CLIENT = SqlAuthenticatedClient("client", b"client-sid", "test-server")
_RUNTIME = SqlDatabaseRuntimeCredentials(
    SqlAuthenticationMode.SQL_SERVER, "client", "runtime-test-secret"
)


def _snapshot():
    return [
        1,
        1,
        1,
        1,
        1,
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
        len(SQL_CLIENT_DIRECT_WRITE_TABLES),
        0,
        0,
        1,
        1,
        0,
        0,
        1,
    ]


class _Lease:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, statement, *parameters):
        self.statements.append((statement, parameters))

    def fetchone(self):
        row = self.rows.pop(0)
        if isinstance(row, Exception):
            raise row
        return row

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Connections:
    def __init__(self, *rows_per_connection):
        self.leases = [_Lease(rows) for rows in rows_per_connection]
        self.requests = []

    @contextmanager
    def connection(self, request, *, autocommit):
        lease = self.leases[len(self.requests)]
        self.requests.append((request, autocommit))
        yield lease


def _error():
    return SqlInfrastructureError(
        SqlErrorDetails(SqlErrorCode.PERMISSION_DENIED, "Client permission denied.")
    )
