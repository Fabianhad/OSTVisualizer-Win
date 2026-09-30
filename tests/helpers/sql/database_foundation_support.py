import ctypes
import json
import os
import re
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from tests.paths import REPO_ROOT
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.application_info import APPLICATION_VERSION
from ost_visualizer.application.dtos.collaboration_dtos import SynchronizationState
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    SqlDatabaseCatalogEntry,
)
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
)
from ost_visualizer.application.services.database_capability_service import (
    DatabaseCapabilityService,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.use_cases.project.cleanup_deleted_files_use_case import (
    CleanupDeletedFilesUseCase,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.schema_model import render_sql_server_schema
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.credential_store import (
    _CREDENTIALW,
    WindowsCredentialStore,
)
from ost_visualizer.infrastructure.sql.errors import SqlErrorCode, classify_pyodbc_error
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlColumnInventory,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidator,
    _matches_type,
    _normalize_filter,
)
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from ost_visualizer.presentation.config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    NEW_DATABASE_TYPE_DIALOG_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
    SELECT_DATABASE_TYPE_DIALOG_WIDTH,
    SQL_CONNECTION_DIALOG_WIDTH,
    SQL_DATABASE_PROPERTIES_DIALOG_WIDTH,
)
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.dialogs.new_database_type_dialog import (
    NewDatabaseTypeDialog,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.dialogs.select_database_type_dialog import (
    SelectDatabaseTypeDialog,
)
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
    SqlConnectionDialogResult,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
    SqlDatabasePropertiesResult,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.utils.qt_callback_bridge import QtCallbackBridge
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import delete
from tests.helpers.workspace_state import with_workspace_state

FileOperationHandler = with_workspace_state(FileOperationHandler)
OpenFilesDialog = with_workspace_state(OpenFilesDialog)


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _IconProvider:
    def set_window_icon(self, _widget):
        pass


class _CredentialStore:
    def __init__(self):
        self.passwords = {}
        self.deleted = []

    def write_password(self, target, username, password):
        self.passwords[target] = (username, password)

    def read_password(self, target):
        value = self.passwords.get(target)
        return value[1] if value else None

    def delete_password(self, target):
        self.deleted.append(target)
        self.passwords.pop(target, None)


class _Catalog:
    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def list_databases(self, location, password=""):
        self.calls.append((location, password))
        return list(self.entries)

    def get_database(self, location, database_name, password=""):
        self.calls.append((location, database_name, password))
        for entry in self.entries:
            if entry.name == database_name:
                return entry
        raise DatabaseCatalogError(
            "The selected database is no longer available to this login."
        )


class _SqlDatabaseCreator:
    def create_database(
        self,
        _location,
        _database_name,
        _password="",
        *,
        application_version,
        actor="",
    ):
        _ = application_version, actor
        raise AssertionError("creation was not requested")


class _FakeApiFunction:
    def __init__(self, callback):
        self._callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self._callback(*args)


class _FakeCredentialApi:
    def __init__(self):
        self._records = {}
        self._read_buffers = []
        self.CredWriteW = _FakeApiFunction(self._write)
        self.CredReadW = _FakeApiFunction(self._read)
        self.CredDeleteW = _FakeApiFunction(self._delete)
        self.CredFree = _FakeApiFunction(lambda _pointer: None)

    def _write(self, credential_pointer, _flags):
        credential = credential_pointer._obj
        blob = ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize
        )
        self._records[credential.TargetName] = (credential.UserName, blob)
        return True

    def _read(self, target, _credential_type, _flags, result_pointer):
        username, blob_bytes = self._records[target]
        blob = (ctypes.c_ubyte * len(blob_bytes)).from_buffer_copy(blob_bytes)
        credential = _CREDENTIALW()
        credential.UserName = username
        credential.CredentialBlobSize = len(blob_bytes)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        pointer = ctypes.pointer(credential)
        ctypes.cast(
            result_pointer,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        )[0] = pointer
        self._read_buffers.append((blob, credential, pointer))
        return True

    def _delete(self, target, _credential_type, _flags):
        self._records.pop(target, None)
        return True
