import ctypes
import os
import tempfile
import time
import unittest
from collections import deque
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import delete, isValid
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.utils.windows import (
    remove_minimize,
    remove_minimize_maximize,
)
from tests.presentation.dialogs.cover_sheet.path_support import (
    CoverSheetDialog,
    _FakeIconProvider,
    _ManualRunnablePool,
    _cover_sheet_data,
)
import tests.presentation.components.test_project_tree_view as project_fixture


class _CursorTrace(QtCore.QObject):
    """Record ownership transitions without changing the cursor or event delivery."""

    def __init__(self):
        super().__init__()
        self.records = deque(maxlen=16)

    def eventFilter(self, watched, event):
        if isinstance(watched, QtWidgets.QWidget) and event.type() in (
            QtCore.QEvent.Type.Enter,
            QtCore.QEvent.Type.Leave,
            QtCore.QEvent.Type.FocusIn,
            QtCore.QEvent.Type.FocusOut,
            QtCore.QEvent.Type.CursorChange,
            QtCore.QEvent.Type.Hide,
        ):
            self.record(watched, event.type().name)
        return False

    def record(self, widget, source):
        override = QtWidgets.QApplication.overrideCursor()
        window = widget.window().windowHandle()
        self.records.append(
            (
                time.perf_counter_ns(),
                source,
                widget.metaObject().className(),
                widget.objectName(),
                widget.cursor().shape().name,
                window.cursor().shape().name if window else None,
                override.shape().name if override else None,
                widget.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow),
            )
        )
