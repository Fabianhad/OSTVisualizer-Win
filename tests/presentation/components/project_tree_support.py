import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.project_write_service import WriteReloadResult
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.presentation.components.project_tree_view import (
    _DELETED_PROJECT_UID,
    ProjectView,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.handlers.project_write_handler import (
    ProjectWriteHandler,
)
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete, isValid


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _EventBus:
    def publish(self, *_args, **_call_options):
        pass
