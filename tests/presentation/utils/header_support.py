import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_NODE_GROUP,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
)
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from ost_visualizer.infrastructure.persistence.repositories.json_workspace_state_repository import (
    JsonWorkspaceStateRepository,
)
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.dialogs.areas_dialog import BidAreasDialog
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.utils.persistent_header import (
    PersistentHeaderController,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import InMemoryWorkspaceStateRepository


class _IconProvider:
    def set_window_icon(self, _window):
        pass


class _EventBus:
    def publish(self, *_args, **_call_options):
        pass


class _CountingWorkspaceStateRepository(InMemoryWorkspaceStateRepository):
    def __init__(self, state: WorkspaceState):
        super().__init__(state)
        self.saves = 0

    def save(self, state: WorkspaceState) -> None:
        super().save(state)
        self.saves += 1


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
