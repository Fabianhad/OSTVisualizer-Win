import os
import unittest
from ost_visualizer.application.events.app_events import AppEvents
import uuid
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.components.page_settings_bar import (
    PageSettingsBar as MasterPageSettingsBar,
)
from ost_visualizer.presentation.config import (
    BID_AREAS_WINDOW_HEIGHT,
    BID_AREAS_WINDOW_WIDTH,
    CDNTYPE_WINDOW_HEIGHT,
    CDNTYPE_WINDOW_WIDTH,
    EMPLOYEES_WINDOW_HEIGHT,
    EMPLOYEES_WINDOW_WIDTH,
    JOB_STATUSES_WINDOW_HEIGHT,
    JOB_STATUSES_WINDOW_WIDTH,
    LAYERS_WINDOW_HEIGHT,
    LAYERS_WINDOW_WIDTH,
    OPEN_FILE_HEIGHT,
    OPEN_FILE_WIDTH,
    PAYROLL_CLASS_WINDOW_HEIGHT,
    PAYROLL_CLASS_WINDOW_WIDTH,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.areas_dialog import (
    BidAreaPickerDialog as MasterBidAreaPickerDialog,
    BidAreasDialog as MasterBidAreasDialog,
)
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog as MasterConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import (
    EmployeesDialog as MasterEmployeesDialog,
)
from ost_visualizer.presentation.dialogs.job_statuses_dialog import (
    JobStatusesDialog as MasterJobStatusesDialog,
)
from ost_visualizer.presentation.dialogs.layers_dialog import (
    LayersDialog as MasterLayersDialog,
    LayersDialogMode,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import (
    OpenFilesDialog as MasterOpenFilesDialog,
)
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog as MasterPayrollClassListDialog,
)
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.utils.deferred_dialog_save import (
    DeferredDialogSaveController,
)
from ost_visualizer.presentation.utils.tree_widget import DEFAULT_TREE_ROW_HEIGHT
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import delete
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)

MasterBidAreaPickerDialog = with_workspace_state(MasterBidAreaPickerDialog)
MasterBidAreasDialog = with_workspace_state(MasterBidAreasDialog)
MasterConditionTypesDialog = with_workspace_state(MasterConditionTypesDialog)
MasterEmployeesDialog = with_workspace_state(MasterEmployeesDialog)
MasterJobStatusesDialog = with_workspace_state(MasterJobStatusesDialog)
MasterLayersDialog = with_workspace_state(MasterLayersDialog)
MasterOpenFilesDialog = with_workspace_state(MasterOpenFilesDialog)
MasterPageSettingsBar = with_workspace_state(MasterPageSettingsBar)
MasterPayrollClassListDialog = with_workspace_state(MasterPayrollClassListDialog)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeIconProvider:
    def set_window_icon(self, _window):
        pass
