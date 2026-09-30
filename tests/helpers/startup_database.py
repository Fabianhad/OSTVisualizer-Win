import logging
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.app_controller import AppController
from ost_visualizer.application.use_cases.project.load_file_use_case import (
    LoadFileUseCase,
)
from ost_visualizer.domain.aggregates.file_state_aggregate import FileStateAggregate
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.presentation.dialogs.open_files_dialog import (
    OpenFilesDialog as StartupOpenFilesDialog,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler as StartupFileOperationHandler,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import with_workspace_state

StartupFileOperationHandler = with_workspace_state(StartupFileOperationHandler)
StartupOpenFilesDialog = with_workspace_state(StartupOpenFilesDialog)


class _OpenFilesDialogStub:
    maintenance_requested = SimpleNamespace(connect=lambda _callback: None)

    def __init__(
        self,
        icon_provider,
        parent,
        file_entries,
        working_directory_service,
        workspace_state_model,
        sql_catalog=None,
        credential_store=None,
        sql_database_creator=None,
        schema_change_allowed_fn=None,
        maintenance_allowed_fn=None,
    ):
        del (
            icon_provider,
            parent,
            file_entries,
            working_directory_service,
            workspace_state_model,
            sql_catalog,
            credential_store,
            sql_database_creator,
            schema_change_allowed_fn,
            maintenance_allowed_fn,
        )

    def exec(self):
        return QtWidgets.QDialog.DialogCode.Accepted

    def cleanup(self):
        pass

    def deleteLater(self):
        pass
