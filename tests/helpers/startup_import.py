from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    parse_project_file_args,
)
from ost_visualizer.application.use_cases.project import (
    import_project_files_from_args_use_case as import_args_use_case,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.project_constants import (
    DELETED_BIDS_PROJECT_NAME,
    DELETED_BIDS_PROJECT_UID,
)
from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_NODE_KIND_BID,
    WORKSPACE_NODE_KIND_PROJECT,
    ProjectTreeSelectionState,
    WorkspaceState,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.windows.file_associations import (
    ASSOCIATIONS,
    FileAssociationRegistrar,
    FileAssociationRegistryError,
    WinRegRegistry,
    build_open_command,
)
from ost_visualizer.main import (
    _install_single_instance_handler,
    _project_file_args_from_payload,
    _project_file_args_to_payload,
)
from ost_visualizer.presentation import main_window as main_window_module
from ost_visualizer.presentation.main_window import MainWindow
from PySide6 import QtWidgets
from tests.paths import REPO_ROOT

MSI_CREATOR_ROOT = REPO_ROOT.parent / "msicreator-master"
REPO_MSI_CONFIG = REPO_ROOT / "installer" / "ostvisualizer.json"
OST_PROG_ID = ASSOCIATIONS[PROJECT_IMPORT_EXTENSION_OST][0]
OSP_PROG_ID = ASSOCIATIONS[PROJECT_IMPORT_EXTENSION_OSP][0]


class FakeImportService:
    def __init__(self, project_data=None, new_project_uid=None, reload_result=True):
        self.calls = []
        self.reloads = []
        self.project_data = project_data
        self.new_project_uid = new_project_uid
        self.reload_result = reload_result
        self.sql_collaboration = False
        self.queued_imports = []

    def import_ost(self, source, target_db, project_uid, refresh=True):
        self.calls.append(("ost", source, target_db, project_uid, refresh))
        self._add_project(target_db)
        return True

    def import_osp(self, source, target_db, project_uid, refresh=True):
        self.calls.append(("osp", source, target_db, project_uid, refresh))
        self._add_project(target_db)
        return True

    def reload_and_notify(self, target_db):
        self.reloads.append(target_db)
        return self.reload_result

    def uses_sql_collaboration_import(self, _target_db):
        return self.sql_collaboration

    def queue_project_import(
        self, source, source_kind, target_db, project_uid, callback
    ):
        self.queued_imports.append(
            (source, source_kind, target_db, project_uid, callback)
        )
        return len(self.queued_imports)

    def _add_project(self, target_db):
        if self.project_data is None or self.new_project_uid is None:
            return
        entry = self.project_data.hierarchy.loaded_files[0]
        entry.bid_projects[self.new_project_uid] = HierarchyProjectInfo(
            name="Imported Project"
        )


class FakeProjectData:
    def __init__(self, file_path):
        self.hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=file_path,
                    bid_projects={
                        "stored-project": HierarchyProjectInfo(
                            name="Stored Project",
                            bids=[HierarchyBidInfo(uid="stored-bid")],
                        )
                    },
                )
            ]
        )

    def get_hierarchy(self):
        return self.hierarchy


class FakeRegistry:
    def __init__(self):
        self.values = {}
        self.deleted = []

    def set_value(self, key_path, name, value):
        self.values[(key_path, name)] = value

    def delete_tree(self, key_path):
        self.deleted.append(key_path)


class FakeProjectView:
    def __init__(self):
        self.bid_selections = []
        self.project_selections = []
        self.file_selections = []

    def restore_bid_selection(self, bid_ref):
        self.bid_selections.append(bid_ref)

    def restore_project_selection(self, project_uid, file_path=None):
        self.project_selections.append((project_uid, file_path))

    def restore_file_selection(self, file_path):
        self.file_selections.append(file_path)


class FakeTimerQueue:
    def __init__(self):
        self.callbacks = []

    def singleShot(self, _delay_ms, callback):
        self.callbacks.append(callback)


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in list(self.callbacks):
            callback()


class FakeSocketBytes:
    def __init__(self, data):
        self._data = data

    def data(self):
        return self._data


class FragmentedLocalSocket:
    def __init__(self):
        self.readyRead = FakeSignal()
        self.disconnected = FakeSignal()
        self._buffer = bytearray()
        self._connected = True
        self.delete_later_calls = 0

    def push(self, data):
        self._buffer.extend(data)
        self.readyRead.emit()

    def bytesAvailable(self):
        return len(self._buffer)

    def readAll(self):
        data = bytes(self._buffer)
        self._buffer.clear()
        return FakeSocketBytes(data)

    def state(self):
        from PySide6.QtNetwork import QLocalSocket

        if self._connected:
            return QLocalSocket.LocalSocketState.ConnectedState
        return QLocalSocket.LocalSocketState.UnconnectedState

    def disconnect(self):
        self._connected = False
        self.disconnected.emit()

    def deleteLater(self):
        self.delete_later_calls += 1


class FakeLocalServer:
    def __init__(self, socket):
        self.newConnection = FakeSignal()
        self._pending = [socket]

    def hasPendingConnections(self):
        return bool(self._pending)

    def nextPendingConnection(self):
        return self._pending.pop(0)


class FakeStartupProgressDialog:
    result_code = QtWidgets.QDialog.DialogCode.Accepted
    instances = []

    def __init__(
        self, filename, task_fn, parent=None, reporter=None, action_text="Processing"
    ):
        self.filename = filename
        self.parent = parent
        self.action_text = action_text
        self.reporter = reporter
        self.result = task_fn()
        self.error = None
        self.cleanup_calls = 0
        self.delete_later_calls = 0
        self.window_modality = None
        self.instances.append(self)

    def setWindowModality(self, modality):
        self.window_modality = modality

    def exec(self):
        return self.result_code

    def cleanup(self):
        self.cleanup_calls += 1

    def deleteLater(self):
        self.delete_later_calls += 1


def _project_file_args(*paths):
    return parse_project_file_args([str(path) for path in paths])


def _startup_import_window():
    window = MainWindow.__new__(MainWindow)
    window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
    window._pending_project_file_args = []
    window._startup_load_complete = False
    window._main_window_ready = False
    window._project_file_import_scheduled = False
    window._project_file_import_running = False
    window._collaboration_shutdown_pending = False
    window._collaboration_shutdown_complete = False
    window._application_shutdown_finalized = False
    window._shutdown_deferred_callbacks = {}
    window._deferred_persistence_manager = SimpleNamespace(abort_shutdown=lambda: None)
    return window
