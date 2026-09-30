import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from PySide6 import QtCore
from tests.helpers.workspace_state import InMemoryWorkspaceStateRepository


def _encoded_geometry(value: bytes = b"geometry") -> str:
    return bytes(QtCore.QByteArray(value).toBase64()).decode("ascii")


class FakeWorkspaceSaveTimer:
    def __init__(self, active=True):
        self._active = active
        self.stopped = False
        self.started = False

    def isActive(self):
        return self._active

    def stop(self):
        self.stopped = True
        self._active = False

    def start(self):
        self.started = True
        self._active = True


class RecordingWorkspaceStateRepository(InMemoryWorkspaceStateRepository):
    def __init__(self, initial_state=None):
        super().__init__(initial_state)
        self.saved_states = []

    def save(self, state):
        super().save(state)
        self.saved_states.append(self.load())


def _workspace_state_model(initial_state=None):
    repository = RecordingWorkspaceStateRepository(initial_state)
    return WorkspaceStateAggregate(repository), repository


class FakeDetachedWindow:
    def __init__(
        self,
        *,
        visible: bool = True,
        maximized: bool = False,
        minimized: bool = False,
        fullscreen: bool = False,
    ):
        self.visible = visible
        self.maximized = maximized
        self.minimized = minimized
        self.fullscreen = fullscreen
        self.initial_states = []
        self.restored_geometries = []
        self.show_maximized_calls = 0
        self.show_normal_calls = 0
        self.dropdown_sizes = None
        self.raise_calls = 0
        self.activate_calls = 0
        self.installed_filters = []
        self.dropdown_size_changed = SimpleNamespace(connect=lambda callback: None)
        self.destroyed = SimpleNamespace(connect=lambda callback: None)

    def isVisible(self):
        return self.visible

    def set_initial_window_state(self, geometry, is_maximized):
        self.initial_states.append((bytes(geometry), is_maximized))

    def restoreGeometry(self, geometry):
        self.restored_geometries.append(bytes(geometry))

    def isMaximized(self):
        return self.maximized

    def isFullScreen(self):
        return self.fullscreen

    def isMinimized(self):
        return self.minimized

    def showMaximized(self):
        self.show_maximized_calls += 1
        self.maximized = True
        self.minimized = False
        self.fullscreen = False

    def showNormal(self):
        self.show_normal_calls += 1
        self.maximized = False
        self.minimized = False
        self.fullscreen = False

    def set_dropdown_popup_sizes(self, sizes):
        self.dropdown_sizes = dict(sizes)

    def windowState(self):
        state = QtCore.Qt.WindowState.WindowNoState
        if self.minimized:
            state |= QtCore.Qt.WindowState.WindowMinimized
        if self.maximized:
            state |= QtCore.Qt.WindowState.WindowMaximized
        return state

    def raise_(self):
        self.raise_calls += 1

    def activateWindow(self):
        self.activate_calls += 1

    def installEventFilter(self, event_filter):
        self.installed_filters.append(event_filter)

    def removeEventFilter(self, event_filter):
        if event_filter in self.installed_filters:
            self.installed_filters.remove(event_filter)


class FakeSplitterForSidebarSizes:
    def __init__(self, sizes=None, height=898, width=None, visible=True):
        self._sizes = list(sizes or [0, 0])
        self._height = height
        self._width = height if width is None else width
        self._visible = visible
        self.applied_sizes = []

    def sizes(self):
        return list(self._sizes)

    def height(self):
        return self._height

    def width(self):
        return self._width

    def isVisible(self):
        return self._visible

    def setSizes(self, sizes):
        self._sizes = list(sizes)
        self.applied_sizes.append(list(sizes))


class FakeCheckAction:
    def __init__(self):
        self.checked = False

    def isChecked(self):
        return self.checked

    def setChecked(self, checked):
        self.checked = bool(checked)

    def blockSignals(self, _blocked):
        pass
